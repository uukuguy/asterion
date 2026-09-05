"""Descriptor-relative verification tests for authority bundle files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator.authority_bundle import (
    AuthorityBundleError,
    AuthorityBundleFile,
    AuthorityExternalRuntimeFile,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)


def _elf(machine: int = 183) -> bytes:
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header)


def _file(path: str, role: str, content: bytes, mode: int = 0o555) -> AuthorityBundleFile:
    return AuthorityBundleFile(path, role, mode, len(content), hashlib.sha256(content).hexdigest())


class TestPrimeAuthorityBundleFiles(unittest.TestCase):
    def _root_owned_bundle(self) -> tuple[tempfile.TemporaryDirectory[str], Path, tuple[AuthorityBundleFile, ...]]:
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "bundle"
        root.mkdir(mode=0o755)
        (root / "bin").mkdir(mode=0o755)
        bootstrap, interpreter = b"bootstrap\n", _elf()
        (root / "bin" / "bootstrap").write_bytes(bootstrap)
        (root / "bin" / "python3").write_bytes(interpreter)
        os.chmod(root / "bin" / "bootstrap", 0o555)
        os.chmod(root / "bin" / "python3", 0o555)
        return directory, root, (
            _file("bin/bootstrap", "bootstrap", bootstrap),
            _file("bin/python3", "interpreter", interpreter),
        )

    def test_accepts_exact_root_owned_tree_and_returns_owned_interpreter(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_files,
        )

        if os.geteuid() != 0:
            self.skipTest("actual root-owned filesystem qualification requires Linux root")
        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        result = verify_authority_bundle_files(
            root_fd,
            files,
            "bin/python3",
            ImagePlatformDescriptor("linux", "arm64", None),
            (-1, -1),
        )
        self.addCleanup(os.close, result.interpreter_fd)
        self.assertTrue(stat.S_ISREG(os.fstat(result.interpreter_fd).st_mode))
        self.assertEqual(result.root_identity[:2], (os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino))

    def test_opens_root_level_bootstrap_by_root_descriptor(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_bootstrap,
        )

        if os.geteuid() != 0:
            self.skipTest("actual root-owned filesystem qualification requires Linux root")
        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        bootstrap = b"root bootstrap\n"
        (root / "bin" / "bootstrap").unlink()
        (root / "bootstrap.py").write_bytes(bootstrap)
        os.chmod(root / "bootstrap.py", 0o444)
        files = (
            _file("bin/python3", "interpreter", _elf()),
            _file("bootstrap.py", "bootstrap", bootstrap, 0o444),
        )
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        bootstrap_fd = verify_authority_bundle_bootstrap(root_fd, files, "bootstrap.py", (-1, -1))
        self.addCleanup(os.close, bootstrap_fd)
        os.lseek(bootstrap_fd, 0, os.SEEK_SET)
        self.assertEqual(os.read(bootstrap_fd, len(bootstrap)), bootstrap)

    def test_rejects_extra_tree_entries_and_preserves_borrowed_root_fd(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_files,
        )

        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        (root / "unexpected").mkdir()
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        with self.assertRaisesRegex(AuthorityBundleError, "unavailable"):
            verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))
        os.fstat(root_fd)

    def test_rejects_non_root_owned_tree_before_file_reads(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_files,
        )

        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        if os.geteuid() == 0:
            self.skipTest("this owner-rejection case requires a non-root test process")
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        with self.assertRaises(AuthorityBundleError):
            verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))

    def test_rejects_hardlinked_file_and_wrong_elf_machine(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_files,
        )

        if os.geteuid() != 0:
            self.skipTest("hard-link matrix needs root-owned files")
        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        outside = Path(directory.name) / "outside-python"
        outside.write_bytes(_elf())
        os.chmod(outside, 0o555)
        (root / "bin" / "python3").unlink()
        os.link(outside, root / "bin" / "python3")
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        with self.assertRaises(AuthorityBundleError):
            verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))
        (root / "bin" / "python3").unlink()
        (root / "bin" / "python3").write_bytes(_elf(62))
        os.chmod(root / "bin" / "python3", 0o555)
        wrong_machine = _file("bin/python3", "interpreter", _elf(62))
        with self.assertRaises(AuthorityBundleError):
            verify_authority_bundle_files(root_fd, (files[0], wrong_machine), "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))

    def test_verifies_external_runtime_file_and_rejects_noncanonical_path(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_external_runtime_files,
        )

        temp_parent = "/root" if os.geteuid() == 0 and sys.platform.startswith("linux") else None
        with tempfile.TemporaryDirectory(dir=temp_parent) as directory:
            path = Path(directory) / "library.so"
            content = b"library"
            path.write_bytes(content)
            os.chmod(path, 0o444)
            record = AuthorityExternalRuntimeFile(str(path), "shared-library", 0o444, len(content), hashlib.sha256(content).hexdigest())
            if os.geteuid() == 0 and sys.platform.startswith("linux"):
                verify_external_runtime_files((record,))
            else:
                with self.assertRaises(AuthorityBundleError):
                    verify_external_runtime_files((record,))
            with self.assertRaises(AuthorityBundleError):
                verify_external_runtime_files((AuthorityExternalRuntimeFile("relative", "shared-library", 0o444, 0, "0" * 64),))

    def test_rejects_fifo_without_blocking_and_file_entry_mutations(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle_files import (
            verify_authority_bundle_files,
        )

        if os.geteuid() != 0 or not sys.platform.startswith("linux"):
            self.skipTest("actual FIFO qualification requires Linux root")
        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        (root / "bin" / "bootstrap").unlink()
        os.mkfifo(root / "bin" / "bootstrap", 0o555)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        started = time.monotonic()
        with self.assertRaises(AuthorityBundleError):
            verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))
        self.assertLess(time.monotonic() - started, 1)

    def test_rejects_forged_record_contracts_before_traversal(self) -> None:
        from asterion.applications.prime_agent.operator import authority_bundle_files

        interpreter = _file("bin/python3", "interpreter", _elf(), 0o444)
        bootstrap = _file("bin/bootstrap", "bootstrap", b"bootstrap\n")
        with self.subTest("missing-bootstrap"):
            with self.assertRaises(ValueError):
                authority_bundle_files._bundle_records((interpreter,), "bin/python3")
        with self.subTest("non-executable-interpreter"):
            with self.assertRaises(ValueError):
                authority_bundle_files._bundle_records((bootstrap, interpreter), "bin/python3")
        with self.subTest("file-count-cap"):
            too_many = (bootstrap, _file("bin/python3", "interpreter", _elf())) + tuple(
                _file(f"data/{index}", "data", b"") for index in range(99_999)
            )
            with self.assertRaises(ValueError):
                authority_bundle_files._bundle_records(too_many, "bin/python3")

    def test_required_open_flags_and_failed_external_ancestor_do_not_leak_fds(self) -> None:
        from asterion.applications.prime_agent.operator import authority_bundle_files

        directory, root, files = self._root_owned_bundle()
        self.addCleanup(directory.cleanup)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        with mock.patch.object(authority_bundle_files, "_NOFOLLOW", 0):
            with self.assertRaises(AuthorityBundleError):
                authority_bundle_files.verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))
        if os.geteuid() != 0 or not sys.platform.startswith("linux"):
            self.skipTest("descriptor leak matrix requires Linux root")
        bad = Path(directory.name) / "bad"
        bad.mkdir(mode=0o777)
        os.chmod(bad, 0o777)
        record = AuthorityExternalRuntimeFile(str(bad / "library.so"), "shared-library", 0o444, 0, "0" * 64)
        before = len(os.listdir("/proc/self/fd"))
        with self.assertRaises(AuthorityBundleError):
            authority_bundle_files.verify_external_runtime_files((record,))
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_rejects_symlink_mode_and_read_time_file_mutation(self) -> None:
        from asterion.applications.prime_agent.operator import authority_bundle_files

        if os.geteuid() != 0 or not sys.platform.startswith("linux"):
            self.skipTest("actual filesystem mutation matrix requires Linux root")
        for case in ("symlink", "mode", "mutation"):
            with self.subTest(case=case):
                directory, root, files = self._root_owned_bundle()
                self.addCleanup(directory.cleanup)
                root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                self.addCleanup(os.close, root_fd)
                bootstrap = root / "bin" / "bootstrap"
                if case == "symlink":
                    bootstrap.unlink()
                    os.symlink("python3", bootstrap)
                    context = mock.patch.object(authority_bundle_files.os, "read", wraps=os.read)
                elif case == "mode":
                    os.chmod(bootstrap, 0o644)
                    context = mock.patch.object(authority_bundle_files.os, "read", wraps=os.read)
                else:
                    original_read = os.read
                    changed = False

                    def mutate_after_read(fd: int, count: int) -> bytes:
                        nonlocal changed
                        value = original_read(fd, count)
                        if not changed:
                            changed = True
                            bootstrap.write_bytes(b"changedxx\n")
                            os.chmod(bootstrap, 0o555)
                        return value

                    context = mock.patch.object(authority_bundle_files.os, "read", side_effect=mutate_after_read)
                with context, self.assertRaises(AuthorityBundleError):
                    authority_bundle_files.verify_authority_bundle_files(root_fd, files, "bin/python3", ImagePlatformDescriptor("linux", "arm64", None), (-1, -1))
