"""Focused tests for Prime P1 Docker executable descriptor admission."""

from __future__ import annotations

from pathlib import Path
import os
import stat
import tempfile
import threading
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfig,
)


_SENTINEL = "DOCKER_EXECUTABLE_SECRET_SENTINEL"
_FSTAT = os.fstat
_STAT = os.stat


def _config(*, path: str) -> PrimeP1OperatorConfig:
    return PrimeP1OperatorConfig(
        MappingProxyType({"ASTERION_PRIME_P1_DOCKER_EXECUTABLE": path}),
        object(),  # type: ignore[arg-type]
    )


class TestPrimeP1AuthorityDockerExecutable(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        root = Path(self.temporary.name)
        self.executable = root / "docker"
        self.executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        self.executable.chmod(0o755)
        self.relative = Path("docker")
        self.final_symlink = root / "docker-link"
        self.final_symlink.symlink_to(self.executable)
        self.parent = root / "parent"
        self.parent.mkdir()
        self.parent_symlink = root / "parent-link"
        self.parent_symlink.symlink_to(self.parent, target_is_directory=True)
        self.parent_symlink_child = self.parent_symlink / "docker"
        (self.parent / "docker").write_bytes(self.executable.read_bytes())
        (self.parent / "docker").chmod(0o755)
        self.writable = root / "writable"
        self.writable.write_bytes(self.executable.read_bytes())
        self.writable.chmod(0o775)
        self.non_root = root / "non-root"
        self.non_root.write_bytes(self.executable.read_bytes())
        self.non_root.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _root_owned_stat(self, fd: int) -> os.stat_result:
        info = _FSTAT(fd)
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_mode=info.st_mode,
            st_uid=0,
            st_gid=info.st_gid,
            st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns,
        )  # type: ignore[return-value]

    def _mutate_open_file(self) -> None:
        before = _STAT(self.executable)
        with self.executable.open("r+b") as output:
            output.seek(0)
            output.write(b"#!/bin/sh\nexit 1\n")
        os.utime(
            self.executable,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )

    def test_root_ownership_seam_preserves_each_identity_field(self) -> None:
        actual = _STAT(self.executable)
        fd = os.open(self.executable, os.O_RDONLY | os.O_CLOEXEC)
        try:
            rooted = self._root_owned_stat(fd)
            self.assertEqual(rooted.st_uid, 0)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_gid",
                "st_size",
                "st_mtime_ns",
            ):
                with self.subTest(field=field):
                    self.assertEqual(getattr(rooted, field), getattr(actual, field))
        finally:
            os.close(fd)

    def test_admits_root_owned_non_writable_regular_executable_and_revalidates(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            AdmittedPrimeP1DockerExecutable,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        with patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_executable(_config(path=str(self.executable)))
            self.assertIsInstance(resource, AdmittedPrimeP1DockerExecutable)
            resource.revalidate_for_spawn()
        self.assertEqual(repr(resource), "AdmittedPrimeP1DockerExecutable(redacted)")
        resource.close()

    def test_rejects_relative_symlink_parent_symlink_writable_or_non_root_paths(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        with patch.object(module.os, "fstat", wraps=os.fstat) as fstat:
            for value in (
                self.relative,
                self.final_symlink,
                self.parent_symlink_child,
                self.writable,
            ):
                with self.subTest(value=value):
                    with self.assertRaises(PrimeP1DockerExecutableError):
                        admit_docker_executable(_config(path=str(value)))
            with self.assertRaises(PrimeP1DockerExecutableError):
                admit_docker_executable(_config(path=str(self.non_root)))
        self.assertGreater(fstat.call_count, 0)

    def test_rejects_empty_repeated_separator_dot_or_parent_components(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )

        root = self.executable.parent
        for value in (
            "/",
            f"{root}//docker",
            f"{root}/./docker",
            f"{root}/parent/../docker",
        ):
            with self.subTest(value=value):
                with self.assertRaises(PrimeP1DockerExecutableError):
                    admit_docker_executable(_config(path=value))

    def test_rejects_each_required_metadata_field(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        original = _FSTAT
        mutations = {
            "not-regular": lambda values: values.__setitem__(0, stat.S_IFIFO | 0o755),
            "not-executable": lambda values: values.__setitem__(0, stat.S_IFREG | 0o644),
            "group-writable": lambda values: values.__setitem__(0, stat.S_IFREG | 0o775),
            "world-writable": lambda values: values.__setitem__(0, stat.S_IFREG | 0o757),
            "not-root": lambda values: values.__setitem__(4, 1),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                def changed(fd: int, mutate: object = mutate) -> os.stat_result:
                    values = list(original(fd))
                    values[4] = 0
                    mutate(values)  # type: ignore[operator]
                    return os.stat_result(values)

                with (
                    patch.object(module.os, "fstat", side_effect=changed),
                    self.assertRaises(PrimeP1DockerExecutableError),
                ):
                    admit_docker_executable(_config(path=str(self.executable)))

    def test_revalidation_rejects_each_snapshot_metadata_change(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        changes = {
            "device": ("st_dev", 1),
            "inode": ("st_ino", 1),
            "owner": ("st_uid", 1),
            "group": ("st_gid", 1),
            "size": ("st_size", 1),
            "mtime": ("st_mtime_ns", 1),
        }
        for name, (field, delta) in changes.items():
            with self.subTest(name=name):
                with patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
                    resource = admit_docker_executable(_config(path=str(self.executable)))

                def changed(
                    fd: int, field: str = field, delta: int = delta
                ) -> SimpleNamespace:
                    info = _FSTAT(fd)
                    values = {
                        attribute: getattr(info, attribute)
                        for attribute in (
                            "st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                            "st_size", "st_mtime_ns",
                        )
                    }
                    values["st_uid"] = 0
                    values[field] += delta
                    return SimpleNamespace(**values)

                with (
                    patch.object(module.os, "fstat", side_effect=changed),
                    self.assertRaises(PrimeP1DockerExecutableError),
                ):
                    resource.revalidate_for_spawn()
                resource.close()

    def test_revalidation_rejects_valid_regular_executable_mode_change(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        with patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_executable(_config(path=str(self.executable)))
        original_mode = _FSTAT(resource._fd).st_mode
        mutated_mode = (original_mode & stat.S_IFMT(original_mode)) | 0o700
        self.assertTrue(stat.S_ISREG(mutated_mode))
        self.assertNotEqual(mutated_mode & 0o111, 0)
        self.assertEqual(mutated_mode & 0o022, 0)
        self.assertNotEqual(mutated_mode, resource._identity.mode)

        def changed(fd: int) -> SimpleNamespace:
            info = self._root_owned_stat(fd)
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_mode=mutated_mode,
                st_uid=info.st_uid,
                st_gid=info.st_gid,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
            )

        with (
            patch.object(module.os, "fstat", side_effect=changed) as fstat,
            self.assertRaises(PrimeP1DockerExecutableError),
        ):
            resource.revalidate_for_spawn()
        self.assertGreater(fstat.call_count, 0)
        resource.close()

    def test_revalidation_rejects_mutated_fd_contents_and_closed_resource(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        with patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_executable(_config(path=str(self.executable)))
            self._mutate_open_file()
            self.assertEqual(_STAT(self.executable).st_size, resource._identity.size)
            self.assertEqual(
                _STAT(self.executable).st_mtime_ns, resource._identity.mtime_ns
            )
            with self.assertRaises(PrimeP1DockerExecutableError):
                resource.revalidate_for_spawn()
            resource.close()
            with self.assertRaises(PrimeP1DockerExecutableError):
                resource.revalidate_for_spawn()

    def test_rejects_executable_larger_than_bound_before_reading(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        def oversized(fd: int) -> SimpleNamespace:
            info = self._root_owned_stat(fd)
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_mode=info.st_mode,
                st_uid=info.st_uid,
                st_gid=info.st_gid,
                st_size=module._MAX_EXECUTABLE_BYTES + 1,
                st_mtime_ns=info.st_mtime_ns,
            )

        with (
            patch.object(module.os, "fstat", side_effect=oversized),
            patch.object(module.os, "read", side_effect=AssertionError("read")) as read,
            self.assertRaises(PrimeP1DockerExecutableError),
        ):
            admit_docker_executable(_config(path=str(self.executable)))
        read.assert_not_called()

    def test_rejection_closes_opened_descriptor_once_and_redacts_failures(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            PrimeP1DockerExecutableError,
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        fd = os.open(self.executable, os.O_RDONLY | os.O_CLOEXEC)
        with (
            patch.object(module, "_open_absolute_executable_without_symlinks", return_value=fd),
            patch.object(module.os, "fstat", side_effect=OSError(_SENTINEL)),
            patch.object(module.os, "close", wraps=os.close) as close,
            self.assertRaises(PrimeP1DockerExecutableError) as raised,
        ):
            admit_docker_executable(_config(path=str(self.executable)))
        close.assert_called_once_with(fd)
        for value in (str(raised.exception), repr(raised.exception), str(raised.exception.__cause__), str(raised.exception.__context__)):
            self.assertNotIn(_SENTINEL, value)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_close_is_exactly_once_when_called_concurrently(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_executable import (
            admit_docker_executable,
        )
        import asterion.applications.prime_agent.operator.authority_docker_executable as module

        with patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_executable(_config(path=str(self.executable)))
        with patch.object(module.os, "close", wraps=os.close) as close:
            threads = [threading.Thread(target=resource.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
