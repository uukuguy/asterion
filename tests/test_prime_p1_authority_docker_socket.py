"""Focused tests for Prime P1 Docker Unix-socket descriptor admission."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
import copy
from pathlib import Path
import os
import pickle
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfig,
)


_SENTINEL = "DOCKER_SOCKET_SECRET_SENTINEL"
_FSTAT = os.fstat
_SOCKET = socket.socket


def _configured_client() -> socket.socket:
    client = _SOCKET(socket.AF_UNIX, socket.SOCK_STREAM)
    client.setblocking(False)
    return client


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
                "ASTERION_PRIME_P1_DOCKER_SERVER_API_VERSION": "1.41",
                "ASTERION_PRIME_P1_DOCKER_SERVER_VERSION": "26.1.4",
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

    @contextmanager
    def _forbidden_effects(self):
        """Prove socket admission does not cross into effectful APIs."""
        import asterion.applications.prime_agent.operator.authority_process as process
        import asterion.applications.prime_agent.operator.authority_resources as resources

        targets = {
            "socket.socket.connect": (socket.socket, "connect"),
            "socket.socket.connect_ex": (socket.socket, "connect_ex"),
            "socket.create_connection": (socket, "create_connection"),
            "asyncio.open_unix_connection": (asyncio, "open_unix_connection"),
            "asyncio.BaseEventLoop.create_unix_connection": (
                asyncio.BaseEventLoop,
                "create_unix_connection",
            ),
            "asyncio.create_subprocess_exec": (asyncio, "create_subprocess_exec"),
            "asyncio.create_subprocess_shell": (asyncio, "create_subprocess_shell"),
            "subprocess.run": (subprocess, "run"),
            "subprocess.Popen": (subprocess, "Popen"),
            "authority_resources.admit_static_authority_resources": (
                resources,
                "admit_static_authority_resources",
            ),
            "authority_process._run_ready_execute_exchange": (
                process,
                "_run_ready_execute_exchange",
            ),
        }
        for name in (
            "spawnv", "spawnve", "spawnvp", "spawnvpe",
            "execv", "execve", "execvp", "execvpe",
            "posix_spawn", "posix_spawnp", "system",
        ):
            if hasattr(os, name):
                targets[f"os.{name}"] = (os, name)
        with ExitStack() as stack:
            guards = {
                label: stack.enter_context(
                    patch.object(target, name, side_effect=AssertionError(label))
                )
                for label, (target, name) in targets.items()
            }
            yield guards
            for guard in guards.values():
                guard.assert_not_called()

    def test_admits_exact_socket_without_connecting_or_spawning(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            AdmittedPrimeP1DockerSocket,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module
        import asterion.applications.prime_agent.operator.authority_process as process
        import asterion.applications.prime_agent.operator.authority_resources as resources

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            self._forbidden_effects(),
            patch.object(
                resources,
                "admit_production_authority_resources",
                side_effect=AssertionError("aggregate"),
            ) as aggregate,
            patch.object(
                process,
                "admit_authority_launch",
                side_effect=AssertionError("authority-ready"),
            ) as ready,
            patch.object(
                AdmittedPrimeP1DockerSocket,
                "_verify_daemon_projection",
                side_effect=AssertionError("daemon-probe"),
            ) as probe,
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            self.assertIsInstance(resource, AdmittedPrimeP1DockerSocket)
            resource.revalidate_path()
        self.assertEqual(repr(resource), "AdmittedPrimeP1DockerSocket(redacted)")
        aggregate.assert_not_called()
        ready.assert_not_called()
        probe.assert_not_called()
        resource.close()

    def test_forbidden_effect_guard_covers_process_and_authority_seams(self) -> None:
        required = {
            "authority_resources.admit_static_authority_resources",
            "authority_process._run_ready_execute_exchange",
        }
        required.update(
            f"os.{name}"
            for name in ("posix_spawn", "posix_spawnp", "system")
            if hasattr(os, name)
        )
        with self._forbidden_effects() as guards:
            self.assertTrue(required.issubset(guards))

    def test_import_is_platform_neutral_without_linux_flags_or_config_dependency(self) -> None:
        script = """
import importlib.abc
import os
import sys

import asterion.applications.prime_agent.operator
assert 'asterion.applications.prime_agent.operator.authority_config' not in sys.modules
sys.modules.pop('fcntl', None)

class BlockFcntl(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'fcntl':
            raise ImportError('fcntl denied')
        return None

sys.meta_path.insert(0, BlockFcntl())
for name in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC'):
    delattr(os, name)
module = __import__('asterion.applications.prime_agent.operator.authority_docker_socket', fromlist=['*'])
module.sys.platform = 'darwin'
try:
    module.admit_docker_socket(object())
except module.PrimeP1DockerSocketError as error:
    assert str(error) == 'prime P1 Docker socket resource is unavailable'
else:
    raise AssertionError('admission unexpectedly succeeded')
assert 'asterion.applications.prime_agent.operator.authority_config' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(
                module,
                "_new_daemon_client",
                side_effect=lambda: _configured_client(),
            ),
        ):
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

    def test_private_projection_probe_uses_fixed_request_and_accepts_fragmented_content_length(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(1)
        observed: list[bytes] = []

        def serve() -> None:
            client, _ = self.listener.accept()
            with client:
                while b"\r\n\r\n" not in b"".join(observed):
                    observed.append(client.recv(4096))
                for fragment in (
                    b"HTTP/1.1 200 OK\r\nContent-Type:application/json\r\n",
                    b"Content-Length:53\r\n\r\n{\"Version\":\"26.1.4\",",
                    b"\"ApiVersion\":\"1.41\",\"extra\":true}",
                ):
                    client.sendall(fragment)

        server = threading.Thread(target=serve)
        server.start()
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(
                module,
                "_new_daemon_client",
                side_effect=lambda: _configured_client(),
            ),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            asyncio.run(resource._verify_daemon_projection(time.monotonic() + 2))
        server.join(timeout=2)
        self.assertFalse(server.is_alive())
        self.assertEqual(
            b"".join(observed),
            b"GET /version HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n",
        )
        resource.close()


if __name__ == "__main__":
    unittest.main()
