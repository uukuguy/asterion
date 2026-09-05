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
        # AF_UNIX pathname limits are much shorter than promotion worktree paths.
        # The test fixture still uses real filesystem ancestry, while the focused
        # admission assertions retain their explicit unsafe-subtree coverage.
        self.temporary = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.safe = self.root / "safe"
        self.safe.mkdir(mode=0o755)
        self.socket = self.safe / "docker.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
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
        self.addCleanup(self.writable_listener.close)
        self.writable_listener.bind(str(self.writable_socket))
        self.writable_socket.chmod(0o600)

    def tearDown(self) -> None:
        pass

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
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "execv",
            "execve",
            "execvp",
            "execvpe",
            "posix_spawn",
            "posix_spawnp",
            "system",
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

    def test_import_is_platform_neutral_without_linux_flags_or_config_dependency(
        self,
    ) -> None:
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
            patch.object(
                module.os, "open", side_effect=AssertionError("open")
            ) as open_,
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
                with (
                    self.subTest(value=value),
                    self.assertRaises(PrimeP1DockerSocketError),
                ):
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
            with (
                self.subTest(name=name),
                self._linux(module),
                patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
                self.assertRaises(PrimeP1DockerSocketError),
            ):
                admit_docker_socket(_config(**kwargs))

    def test_revalidation_rejects_closed_or_replaced_resource(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
        ):
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

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
        ):
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
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation), self.assertRaises(TypeError):
                operation(resource)
        resource.close()

    def test_private_projection_probe_uses_fixed_request_and_accepts_fragmented_content_length(
        self,
    ) -> None:
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
                    b'Content-Length:53\r\n\r\n{"Version":"26.1.4",',
                    b'"ApiVersion":"1.41","extra":true}',
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

    def test_projection_parser_rejects_strict_framing_and_json_failures(self) -> None:
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        def content(body: bytes, extra: bytes = b"") -> bytes:
            return (
                b"HTTP/1.1 200 OK\r\nContent-Type:application/json\r\nContent-Length:"
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
                + extra
            )

        valid = b'{"Version":"26.1.4","ApiVersion":"1.41"}'
        invalid = (
            content(valid, b"x"),
            content(valid).replace(
                b"Content-Length:", b"Content-Length:0\r\nContent-Length:"
            ),
            content(valid).replace(
                b"Content-Length:", b"Transfer-Encoding:chunked\r\nContent-Length:"
            ),
            content(b'{"Version":"26.1.4","Version":"x","ApiVersion":"1.41"}'),
            content(b'{"Version":NaN,"ApiVersion":"1.41"}'),
            content(
                b'{"Version":"26.1.4","ApiVersion":"1.41","x":'
                + b'{"x":' * 65
                + b"0"
                + b"}" * 66
            ),
            content(b'\xef\xbb\xbf{"Version":"26.1.4","ApiVersion":"1.41"}'),
            content(b'{"Version":"26.1.4","ApiVersion":"1.41"}x'),
            b"HTTP/1.1 200 OK\r\nContent-Type:application/json\r\nTransfer-Encoding:chunked\r\n\r\n2;x\r\n{}\r\n0\r\n\r\n",
        )
        for response in invalid:
            with self.subTest(response=response[:40]), self.assertRaises(ValueError):
                module._verify_daemon_projection(response, "26.1.4", "1.41")

    def test_projection_parser_rejects_controls_and_explicit_contract_failures(
        self,
    ) -> None:
        """Every HTTP boundary violation is rejected before JSON is trusted."""
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        body = b'{"Version":"26.1.4","ApiVersion":"1.41"}'

        def response(headers: bytes, payload: bytes = body) -> bytes:
            return (
                b"HTTP/1.1 200 OK\r\n"
                + headers.replace(b"@", str(len(payload)).encode())
                + b"\r\n\r\n"
                + payload
            )

        cases = {
            "status": response(
                b"Content-Type:application/json\r\nContent-Length:@"
            ).replace(b"200 OK", b"201 OK"),
            "bare-lf": response(
                b"Content-Type:application/json\r\nContent-Length:@\r\nX-Test:ok\nbad"
            ),
            "bare-cr": response(
                b"Content-Type:application/json\r\nContent-Length:@\r\nX-Test:ok\rbad"
            ),
            "control-name": response(
                b"Content\x01-Type:application/json\r\nContent-Length:@"
            ),
            "control-value": response(
                b"Content-Type:application/json\r\nContent-Length:@\r\nX-Test:ok\x1f"
            ),
            "wrong-content-type": response(
                b"Content-Type:application/json; charset=utf-8\r\nContent-Length:@"
            ),
            "both-framings": response(
                b"Content-Type:application/json\r\nContent-Length:@\r\n"
                b"Transfer-Encoding:chunked"
            ),
            "truncated-chunk": response(
                b"Content-Type:application/json\r\nTransfer-Encoding:chunked",
                b"26\r\n" + body[:-1],
            ),
            "invalid-utf8": response(
                b"Content-Type:application/json\r\nContent-Length:@", b"\xff\xff"
            ),
            "missing-version": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"ApiVersion":"1.41"}',
            ),
            "wrong-version-type": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"Version":26,"ApiVersion":"1.41"}',
            ),
            "mismatched-version": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"Version":"26.1.3","ApiVersion":"1.41"}',
            ),
            "missing-api-version": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"Version":"26.1.4"}',
            ),
            "wrong-api-version-type": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"Version":"26.1.4","ApiVersion":141}',
            ),
            "mismatched-api-version": response(
                b"Content-Type:application/json\r\nContent-Length:@",
                b'{"Version":"26.1.4","ApiVersion":"1.40"}',
            ),
        }
        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                module._verify_daemon_projection(value, "26.1.4", "1.41")

    def test_new_daemon_client_uses_atomic_flags_without_patching_constructor(self) -> None:
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        if not all(
            isinstance(getattr(socket, name, None), int)
            for name in ("SOCK_CLOEXEC", "SOCK_NONBLOCK")
        ):
            self.skipTest("atomic Linux socket flags are unavailable")
        client = module._new_daemon_client()
        try:
            self.assertEqual(client.family, socket.AF_UNIX)
            self.assertEqual(client.type & socket.SOCK_STREAM, socket.SOCK_STREAM)
            self.assertFalse(client.getblocking())
            self.assertFalse(client.get_inheritable())
        finally:
            client.close()

    def test_new_daemon_client_accepts_stdlib_socketkind_atomic_flags(self) -> None:
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        cloexec = getattr(socket, "SOCK_CLOEXEC", None)
        nonblock = getattr(socket, "SOCK_NONBLOCK", None)
        if (
            not isinstance(cloexec, int)
            or not isinstance(nonblock, int)
            or type(cloexec) is int
            or type(nonblock) is int
        ):
            self.skipTest("stdlib socket flags are unavailable or plain integers")
        client = module._new_daemon_client()
        try:
            self.assertFalse(client.getblocking())
            self.assertFalse(client.get_inheritable())
        finally:
            client.close()

    def test_new_daemon_client_constructs_with_atomic_cloexec_and_nonblock_flags(self) -> None:
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        calls: list[tuple[object, ...]] = []

        class Client:
            def setblocking(self, value: bool) -> None:
                self.blocking = value

            def set_inheritable(self, value: bool) -> None:
                self.inheritable = value

            def close(self) -> None:
                self.closed = True

        def construct(*args: object) -> Client:
            calls.append(args)
            return Client()

        with (
            patch.object(module.socket, "SOCK_CLOEXEC", 0x100, create=True),
            patch.object(module.socket, "SOCK_NONBLOCK", 0x200, create=True),
            patch.object(module.socket, "socket", side_effect=construct),
        ):
            client = module._new_daemon_client()
        self.assertIsInstance(client, Client)
        self.assertEqual(
            calls,
            [(socket.AF_UNIX, socket.SOCK_STREAM | 0x100 | 0x200)],
        )

    def test_queued_probe_deadline_and_cancel_do_not_create_clients_and_close_once(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(1)
        connected = threading.Event()
        release = threading.Event()

        def serve() -> None:
            client, _ = self.listener.accept()
            with client:
                client.recv(4096)
                connected.set()
                release.wait(2)
                client.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type:application/json\r\n"
                    b"Content-Length:40\r\n\r\n"
                    b'{"Version":"26.1.4","ApiVersion":"1.41"}'
                )

        class CloseSpy:
            def __init__(self, client: socket.socket) -> None:
                self.client = client
                self.close_calls = 0

            def __getattr__(self, name: str) -> object:
                return getattr(self.client, name)

            def close(self) -> None:
                self.close_calls += 1
                self.client.close()

        server = threading.Thread(target=serve)
        server.start()
        spies: list[CloseSpy] = []

        def new_client() -> CloseSpy:
            spy = CloseSpy(_configured_client())
            spies.append(spy)
            return spy

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(module, "_new_daemon_client", side_effect=new_client),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))

            async def run() -> None:
                first = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 2)
                )
                while not resource._probe_lock.locked():
                    await asyncio.sleep(0)
                await asyncio.to_thread(connected.wait, 1)
                queued_deadline = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 0.02)
                )
                await asyncio.sleep(0)
                with self.assertRaises(PrimeP1DockerSocketError):
                    await queued_deadline
                queued_cancel = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 2)
                )
                await asyncio.sleep(0)
                queued_cancel.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await queued_cancel
                self.assertEqual(len(spies), 1)
                release.set()
                await first

            asyncio.run(run())
        server.join(2)
        self.assertFalse(server.is_alive())
        self.assertEqual([spy.close_calls for spy in spies], [1])
        resource.close()

    def test_probe_recursively_redacts_socket_level_sentinels_and_exception_links(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
        failures = (
            patch.object(
                type(resource), "revalidate_path", side_effect=RuntimeError(_SENTINEL)
            ),
            patch.object(module, "_new_daemon_client", side_effect=RuntimeError(_SENTINEL)),
        )
        for failure in failures:
            with self.subTest(failure=failure):
                with failure, self.assertRaises(PrimeP1DockerSocketError) as raised:
                    asyncio.run(resource._verify_daemon_projection(time.monotonic() + 1))
                self.assertNotIn(_SENTINEL, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
        resource.close()

    def test_probe_rejects_a_fake_daemon_response_over_the_cap(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(1)

        def serve() -> None:
            client, _ = self.listener.accept()
            with client:
                client.recv(4096)
                client.sendall(b"x" * (module._DAEMON_RESPONSE_LIMIT + 1))

        server = threading.Thread(target=serve)
        server.start()
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(module, "_new_daemon_client", side_effect=_configured_client),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            with self.assertRaises(PrimeP1DockerSocketError):
                asyncio.run(resource._verify_daemon_projection(time.monotonic() + 2))
        server.join(2)
        self.assertFalse(server.is_alive())
        resource.close()

    def test_private_projection_probe_accepts_fragmented_chunked_response(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(1)
        body = b'{"Version":"26.1.4","ApiVersion":"1.41"}'
        request = []

        def serve() -> None:
            client, _ = self.listener.accept()
            with client:
                request.append(client.recv(4096))
                for fragment in (
                    b"HTTP/1.1 200 OK\r\nContent-Type:application/json\r\nTransfer-Encoding:chunked\r\n\r\n",
                    b"10\r\n" + body[:16] + b"\r\n",
                    f"{len(body[16:]):x}".encode()
                    + b"\r\n"
                    + body[16:]
                    + b"\r\n0\r\n\r\n",
                ):
                    client.sendall(fragment)

        server = threading.Thread(target=serve)
        server.start()
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(module, "_new_daemon_client", side_effect=_configured_client),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))
            asyncio.run(resource._verify_daemon_projection(time.monotonic() + 2))
        server.join(2)
        self.assertFalse(server.is_alive())
        self.assertEqual(b"".join(request), module._VERSION_REQUEST)
        resource.close()

    def test_projection_probe_revalidates_on_each_replacement_timing(self) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        for replacement_call in (1, 2, 3):
            with self.subTest(replacement_call=replacement_call):
                # A distinct fixture is needed because replacing a Unix path is irreversible.
                with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
                    safe = Path(directory) / "safe"
                    safe.mkdir(mode=0o755)
                    path = safe / "docker.sock"
                    listener = _SOCKET(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.addCleanup(listener.close)
                    listener.bind(str(path))
                    path.chmod(0o600)
                    listener.listen(1)
                    listener.settimeout(0.2)
                    accepted = threading.Event()

                    def serve() -> None:
                        try:
                            client, _ = listener.accept()
                            accepted.set()
                            with client:
                                client.recv(4096)
                                client.sendall(
                                    b'HTTP/1.1 200 OK\r\nContent-Type:application/json\r\nContent-Length:38\r\n\r\n{"Version":"26.1.4","ApiVersion":"1.41"}'
                                )
                        except OSError:
                            pass

                    server = threading.Thread(target=serve)
                    server.start()
                    with (
                        self._linux(module),
                        patch.object(
                            module.os, "fstat", side_effect=self._root_owned_stat
                        ),
                        patch.object(
                            module, "_new_daemon_client", side_effect=_configured_client
                        ),
                    ):
                        resource = admit_docker_socket(_config(path=str(path)))
                        original = type(resource).revalidate_path
                        calls = 0

                        def revalidate(instance: object) -> None:
                            nonlocal calls
                            calls += 1
                            if calls == replacement_call:
                                path.unlink()
                                replacement = _SOCKET(
                                    socket.AF_UNIX, socket.SOCK_STREAM
                                )
                                replacement.bind(str(path))
                                replacement.close()
                            original(instance)  # type: ignore[arg-type]

                        with (
                            patch.object(
                                type(resource), "revalidate_path", new=revalidate
                            ),
                            self.assertRaises(PrimeP1DockerSocketError),
                        ):
                            asyncio.run(
                                resource._verify_daemon_projection(time.monotonic() + 1)
                            )
                    resource.close()
                    listener.close()
                    server.join(1)
                    self.assertFalse(server.is_alive())

    def test_projection_probe_after_close_concurrent_and_close_during_are_safe(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(2)
        first_connected = threading.Event()
        release_first = threading.Event()
        closed_by_peer = threading.Event()

        def serve() -> None:
            client, _ = self.listener.accept()
            first_connected.set()
            with client:
                client.recv(4096)
                release_first.wait(2)
                client.sendall(
                    b'HTTP/1.1 200 OK\r\nContent-Type:application/json\r\nContent-Length:38\r\n\r\n{"Version":"26.1.4","ApiVersion":"1.41"}'
                )
                while client.recv(4096):
                    pass
            closed_by_peer.set()

        server = threading.Thread(target=serve)
        server.start()
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(module, "_new_daemon_client", side_effect=_configured_client),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))

            async def run() -> None:
                first = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 2)
                )
                await asyncio.to_thread(first_connected.wait, 1)
                second = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 2)
                )
                resource.close()
                release_first.set()
                for task in (first, second):
                    with self.assertRaises(PrimeP1DockerSocketError):
                        await task

            asyncio.run(run())
        self.assertTrue(closed_by_peer.wait(1))
        server.join(1)

    def test_projection_probe_stall_deadline_and_cancellation_close_client(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.authority_docker_socket import (
            PrimeP1DockerSocketError,
            admit_docker_socket,
        )
        import asterion.applications.prime_agent.operator.authority_docker_socket as module

        self.listener.listen(2)
        peer_closed = threading.Event()
        connections = 0

        def serve() -> None:
            nonlocal connections
            while connections < 2:
                client, _ = self.listener.accept()
                connections += 1
                with client:
                    client.recv(4096)
                    while client.recv(4096):
                        pass
                if connections == 2:
                    peer_closed.set()

        server = threading.Thread(target=serve)
        server.start()
        with (
            self._linux(module),
            patch.object(module.os, "fstat", side_effect=self._root_owned_stat),
            patch.object(module, "_new_daemon_client", side_effect=_configured_client),
        ):
            resource = admit_docker_socket(_config(path=str(self.socket)))

            async def run() -> None:
                with self.assertRaises(PrimeP1DockerSocketError):
                    await resource._verify_daemon_projection(time.monotonic() + 0.05)
                task = asyncio.create_task(
                    resource._verify_daemon_projection(time.monotonic() + 2)
                )
                await asyncio.sleep(0.02)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            asyncio.run(run())
        self.assertTrue(peer_closed.wait(1))
        resource.close()
        server.join(1)


if __name__ == "__main__":
    unittest.main()
