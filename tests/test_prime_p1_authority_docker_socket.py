"""Focused tests for Prime P1 Docker Unix-socket descriptor admission."""

from __future__ import annotations

from contextlib import contextmanager
import copy
from pathlib import Path
import os
import pickle
import socket
import subprocess
import tempfile
import threading
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfig,
)


_SENTINEL = "DOCKER_SOCKET_SECRET_SENTINEL"
_FSTAT = os.fstat


def _config(
    *, path: str, uid: int = os.geteuid(), gid: int = os.getegid(), mode: str = "0600"
) -> PrimeP1OperatorConfig:
    return PrimeP1OperatorConfig(
        MappingProxyType(
            {
                "ASTERION_PRIME_P1_DOCKER_SOCKET": path,
                "ASTERION_PRIME_P1_DOCKER_SOCKET_OWNER_UID": str(uid),
                "ASTERION_PRIME_P1_DOCKER_SOCKET_GROUP_GID": str(gid),
                "ASTERION_PRIME_P1_DOCKER_SOCKET_MODE": mode,
            }
        ),
        object(),  # type: ignore[arg-type]
    )


class TestPrimeP1AuthorityDockerSocket(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name)
        self.safe = self.root / "safe"
        self.safe.mkdir(mode=0o755)
        self.socket = self.safe / "docker.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.socket))
        self.socket.chmod(0o600)
        self.final_link = self.safe / "socket-link"
        self.final_link.symlink_to(self.socket)
        self.link_parent = self.root / "link-parent"
        self.link_parent.symlink_to(self.safe, target_is_directory=True)
        self.writable = self.root / "writable"
        self.writable.mkdir(mode=0o755)
        self.writable_socket = self.writable / "docker.sock"
        self.writable_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.writable_listener.bind(str(self.writable_socket))
        self.writable_socket.chmod(0o600)

    def tearDown(self) -> None:
        self.listener.close()
        self.writable_listener.close()
        self.temporary.cleanup()

    @staticmethod
    def _root_owned_stat(fd: int) -> os.stat_result:
        info = _FSTAT(fd)
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_mode=info.st_mode,
            st_uid=0,
            st_gid=0,
        )  # type: ignore[return-value]

    @contextmanager
    def _linux(self, module: object):
        with (
            patch.object(module.sys, "platform", "linux"),  # type: ignore[attr-defined]
            patch.object(module.os, "name", "posix"),  # type: ignore[attr-defined]
        ):
            yield

    def test_admits_exact_socket_without_connecting_or_spawning(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            AdmittedPrimeP1DockerSocket,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(socket.socket, "connect", side_effect=AssertionError("connect")) as connect,
            patch.object(subprocess, "run", side_effect=AssertionError("subprocess")) as run,
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            self.assertIsInstance(resource, AdmittedPrimeP1DockerSocket)
            resource.revalidate_path()
        self.assertEqual(repr(resource), "AdmittedPrimeP1DockerSocket(redacted)")
        connect.assert_not_called()
        run.assert_not_called()
        resource.close()

    def test_rejects_wrong_config_and_non_linux_before_filesystem_access(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with (
            patch.object(module.sys, "platform", "darwin"),
            patch.object(module.os, "open", side_effect=AssertionError("open")) as open_,
            self.assertRaises(PrimeP1DockerSocketError),
        ):
            admit_docker_socket(_config(path=str(self.socket)))
        open_.assert_not_called()
        with self._linux(module), self.assertRaises(PrimeP1DockerSocketError):
            admit_docker_socket(object())

    def test_rejects_noncanonical_symlink_and_writable_ancestor_paths(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.writable.chmod(0o777)
        values = (
            "relative.sock",
            "/",
            f"{self.root}//safe/docker.sock",
            f"{self.root}/safe/./docker.sock",
            f"{self.root}/safe/../safe/docker.sock",
            str(self.final_link),
            str(self.link_parent / "docker.sock"),
            str(self.writable_socket),
        )
        with self._linux(module), patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            for value in values:
                with self.subTest(value=value), self.assertRaises(PrimeP1DockerSocketError):
                    admit_docker_socket(_config(path=value))

    def test_rejects_regular_socket_metadata_mismatch_and_final_link(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        regular = self.safe / "regular"
        regular.write_text("not a socket")
        for name, kwargs in (
            ("regular", {"path": str(regular)}),
            ("uid", {"path": str(self.socket), "uid": os.geteuid() + 1}),
            ("gid", {"path": str(self.socket), "gid": os.getegid() + 1}),
            ("mode", {"path": str(self.socket), "mode": "0660"}),
            ("final-link", {"path": str(self.final_link)}),
        ):
            with self.subTest(name=name), self._linux(module), patch.object(module.os, "fstat", side_effect=self._root_owned_stat), self.assertRaises(PrimeP1DockerSocketError):
                admit_docker_socket(_config(**kwargs))

    def test_revalidation_rejects_closed_or_replaced_resource(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with self._linux(module), patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            resource.close()
            with self.assertRaises(PrimeP1DockerSocketError):
                resource.revalidate_path()
            resource = admit_docker_socket(_config(path=str(self.socket)))
            self.listener.close()
            self.socket.unlink()
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(replacement.close)
            replacement.bind(str(self.socket))
            self.socket.chmod(0o600)
            with self.assertRaises(PrimeP1DockerSocketError):
                resource.revalidate_path()
            resource.close()

    def test_redacts_errors_and_closes_retained_parent_exactly_once(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with self._linux(module), patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_socket(_config(path=str(self.socket)))
        with patch.object(module.os, "close", wraps=os.close) as close:
            threads = [threading.Thread(target=resource.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        close.assert_called_once()
        with (
            self._linux(module),
            patch.object(module.os, "open", side_effect=OSError(_SENTINEL)),
            self.assertRaises(PrimeP1DockerSocketError) as raised,
        ):
            admit_docker_socket(_config(path=str(self.socket)))
        self.assertNotIn(_SENTINEL, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_resource_cannot_be_constructed_copied_or_pickled(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            AdmittedPrimeP1DockerSocket,
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with self.assertRaises(PrimeP1DockerSocketError):
            AdmittedPrimeP1DockerSocket(-1, (), (), object())  # type: ignore[arg-type]
        with self._linux(module), patch.object(module.os, "fstat", side_effect=self._root_owned_stat):
            resource = admit_docker_socket(_config(path=str(self.socket)))
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation), self.assertRaises(TypeError):
                operation(resource)
        resource.close()


if __name__ == "__main__":
    unittest.main()
