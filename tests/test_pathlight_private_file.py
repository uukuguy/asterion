"""Regression tests for Pathlight's shared private-file trust boundary."""

from __future__ import annotations

import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.pathlight._private_file import (
    PrivateFileError,
    read_private_file,
    write_private_file,
)


_FILENAME = "private.json"
_MAX_BYTES = 64
_PAYLOAD = b'{"safe":true}'
_SENTINEL = "SENTINEL_PRIVATE_FILE_VALUE"


class TestPathlightPrivateFile(unittest.TestCase):
    def assert_private_error(self, error: BaseException, expected: str) -> None:
        self.assertEqual(type(error), PrivateFileError)
        self.assertEqual(str(error), expected)
        self.assertNotIn(_SENTINEL, str(error))

    def test_writer_closes_new_ancestor_when_previous_descriptor_close_fails(self) -> None:
        close_calls: list[int] = []

        def close_with_first_failure(descriptor: int) -> None:
            close_calls.append(descriptor)
            if close_calls == [10]:
                raise OSError(f"{_SENTINEL}: close")

        with patch(
            "asterion.pathlight._private_file.os.open", side_effect=(10, 11)
        ), patch(
            "asterion.pathlight._private_file.os.close",
            side_effect=close_with_first_failure,
        ), self.assertRaises(PrivateFileError) as raised:
            write_private_file(Path("/ancestor/private.json"), _PAYLOAD)

        self.assertEqual(close_calls, [10, 11, 10])
        self.assert_private_error(raised.exception, "private file target is unavailable")

    def test_writer_uses_descriptor_relative_nofollow_exclusive_private_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            original_open = os.open
            final_calls: list[tuple[object, int, int, int | None]] = []

            def recording_open(
                name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if name == _FILENAME:
                    final_calls.append((name, flags, mode, dir_fd))
                return original_open(name, flags, mode, dir_fd=dir_fd)

            with patch(
                "asterion.pathlight._private_file.os.open", side_effect=recording_open
            ):
                write_private_file(path, _PAYLOAD)

            with self.assertRaises(PrivateFileError):
                write_private_file(path, _PAYLOAD)

        self.assertEqual(len(final_calls), 1)
        _, flags, mode, directory_fd = final_calls[0]
        self.assertIsNotNone(directory_fd)
        self.assertEqual(
            flags & (os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        )
        self.assertEqual(flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
        self.assertEqual(mode, 0o600)

    def test_writer_rejects_ancestor_and_final_symlinks_without_touching_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            ancestor = root / "ancestor"
            ancestor.symlink_to(target, target_is_directory=True)

            with self.assertRaises(PrivateFileError):
                write_private_file(ancestor / _FILENAME, _PAYLOAD)
            self.assertFalse((target / _FILENAME).exists())

            replacement = root / "replacement.json"
            replacement.write_bytes(b"replacement")
            final_link = root / _FILENAME
            final_link.symlink_to(replacement)
            with self.assertRaises(PrivateFileError):
                write_private_file(final_link, _PAYLOAD)
            self.assertEqual(replacement.read_bytes(), b"replacement")

    def test_writer_preserves_partial_output_and_path_replacement_without_unlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            original_write = os.write

            def partial_then_fail(descriptor: int, data: bytes) -> int:
                original_write(descriptor, data[:1])
                raise OSError(f"{_SENTINEL}: partial")

            with patch(
                "asterion.pathlight._private_file.os.write",
                side_effect=partial_then_fail,
            ), self.assertRaises(PrivateFileError):
                write_private_file(path, _PAYLOAD)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(read_private_file(path, _MAX_BYTES), _PAYLOAD[:1])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / _FILENAME
            partial = root / "partial.json"
            replacement = root / "replacement.json"
            replacement.write_bytes(b"replacement")

            def replace_then_fail(descriptor: int, mode: int) -> None:
                del descriptor, mode
                path.rename(partial)
                replacement.rename(path)
                raise OSError(f"{_SENTINEL}: mode")

            with patch(
                "asterion.pathlight._private_file.os.fchmod",
                side_effect=replace_then_fail,
            ), patch(
                "asterion.pathlight._private_file.os.unlink"
            ) as unlink, self.assertRaises(PrivateFileError):
                write_private_file(path, _PAYLOAD)

            unlink.assert_not_called()
            self.assertEqual(path.read_bytes(), b"replacement")

    def test_reader_rejects_ancestor_and_final_symlinks_wrong_mode_and_nonregular(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            target_file = target / _FILENAME
            write_private_file(target_file, _PAYLOAD)
            final_link = root / _FILENAME
            final_link.symlink_to(target_file)
            with self.assertRaises(PrivateFileError):
                read_private_file(final_link, _MAX_BYTES)
            ancestor = root / "ancestor"
            ancestor.symlink_to(target, target_is_directory=True)
            with self.assertRaises(PrivateFileError):
                read_private_file(ancestor / _FILENAME, _MAX_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            write_private_file(path, _PAYLOAD)
            path.chmod(0o640)
            with self.assertRaises(PrivateFileError):
                read_private_file(path, _MAX_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            path.mkdir()
            with self.assertRaises(PrivateFileError):
                read_private_file(path, _MAX_BYTES)

    def test_reader_rejects_fifo_promptly_without_a_writer(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("os.mkfifo is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            os.mkfifo(path, 0o600)
            path.chmod(0o600)
            completed = threading.Event()
            outcomes: list[BaseException | bytes] = []

            def read_fifo() -> None:
                try:
                    outcomes.append(read_private_file(path, _MAX_BYTES))
                except BaseException as error:
                    outcomes.append(error)
                finally:
                    completed.set()

            thread = threading.Thread(target=read_fifo, daemon=True)
            thread.start()
            finished_without_writer = completed.wait(0.25)
            if not finished_without_writer:
                writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                os.close(writer)
                thread.join(1)

            self.assertTrue(finished_without_writer, "private-file FIFO read blocked")
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], PrivateFileError)

    def test_reader_rejects_initial_and_post_stat_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            path.write_bytes(b"x" * (_MAX_BYTES + 1))
            path.chmod(0o600)
            with self.assertRaises(PrivateFileError):
                read_private_file(path, _MAX_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            write_private_file(path, _PAYLOAD)
            original_fstat = os.fstat
            calls = 0

            def grow_on_second_stat(descriptor: int) -> os.stat_result:
                nonlocal calls
                result = original_fstat(descriptor)
                calls += 1
                if calls == 2:
                    values = list(result)
                    values[6] = _MAX_BYTES + 1
                    return os.stat_result(values)
                return result

            with patch(
                "asterion.pathlight._private_file.os.fstat",
                side_effect=grow_on_second_stat,
            ), self.assertRaises(PrivateFileError):
                read_private_file(path, _MAX_BYTES)

    def test_reader_rejects_identity_mutation_and_normalizes_close_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            write_private_file(path, _PAYLOAD)
            original_fstat = os.fstat
            calls = 0

            def mutate_identity(descriptor: int) -> os.stat_result:
                nonlocal calls
                result = original_fstat(descriptor)
                calls += 1
                if calls == 2:
                    values = list(result)
                    values[1] = result.st_ino + 1
                    return os.stat_result(values)
                return result

            with patch(
                "asterion.pathlight._private_file.os.fstat",
                side_effect=mutate_identity,
            ), self.assertRaises(PrivateFileError):
                read_private_file(path, _MAX_BYTES)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            write_private_file(path, _PAYLOAD)
            original_close = os.close
            failed = False

            def close_once(descriptor: int) -> None:
                nonlocal failed
                original_close(descriptor)
                if not failed:
                    failed = True
                    raise OSError(f"{_SENTINEL}: close")

            with patch(
                "asterion.pathlight._private_file.os.close", side_effect=close_once
            ), self.assertRaises(PrivateFileError) as raised:
                read_private_file(path, _MAX_BYTES)

            self.assert_private_error(
                raised.exception, "private file source is invalid"
            )

    def test_round_trip_returns_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / _FILENAME
            write_private_file(path, _PAYLOAD)
            self.assertEqual(read_private_file(path, _MAX_BYTES), _PAYLOAD)


if __name__ == "__main__":
    unittest.main()
