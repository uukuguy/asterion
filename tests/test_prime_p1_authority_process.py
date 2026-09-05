"""Fail-closed bootstrap tests for the Linux-only P1 authority process."""

from __future__ import annotations

import os
import socket as socket_module
import sys
import threading
import tempfile
from pathlib import Path
import traceback
import unittest
import enum
import errno
import fcntl
from array import array
from typing import Any, cast
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_process import (
    AuthorityLaunchContract,
    AdmittedAuthorityDescriptors,
    PrimeP1AuthorityBootstrapError,
    admit_authority_launch,
    admit_retained_authority_descriptors,
    _consume_session_key,
    _receive_authority_packet,
    _receive_authority_packet_from_connection,
    _run_ready_execute_exchange,
    _send_authority_packet,
)
class _Socket:
    family = 1
    type = 5

    def __init__(self, *, peer: tuple[int, int], socket_type: int = 5) -> None:
        self.peer = peer
        self.socket_type = socket_type
        self.closed = False

    def getsockopt(self, *_: object) -> int:
        return self.socket_type

    def close(self) -> None:
        self.closed = True


class _PacketSocket(_Socket):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(peer=(300, 400))
        self.responses = iter(responses)
        self.calls = 0
        self.close_calls = 0
        self.flags: list[int] = []

    def recvmsg(self, _size: int, _ancillary_size: int, flags: int) -> object:
        self.calls += 1
        self.flags.append(flags)
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class _SendingSocket:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[object, object, int]] = []

    def sendmsg(self, buffers: object, ancillary: object, flags: int) -> object:
        self.calls.append((buffers, ancillary, flags))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result


class _ExchangeSocket(_SendingSocket):
    def __init__(self, received: object) -> None:
        super().__init__([])
        self.received = received
        self.closed = False

    def sendmsg(self, buffers: object, ancillary: object, flags: int) -> object:
        self.calls.append((buffers, ancillary, flags))
        return sum(len(buffer) for buffer in cast(list[bytes], buffers))

    def recvmsg(self, _size: int, _ancillary_size: int, _flags: int) -> object:
        if isinstance(self.received, BaseException):
            raise self.received
        return self.received

    def close(self) -> None:
        self.closed = True


class _RecordingUnixSocket:
    def __init__(self, connection: socket_module.socket) -> None:
        self.connection = connection
        self.ancillary: list[tuple[int, int, bytes]] | None = None
        self.flags: int | None = None

    def recvmsg(
        self, size: int, ancillary_size: int, flags: int
    ) -> tuple[bytes, list[tuple[int, int, bytes]], int, object]:
        packet, ancillary, flags, address = self.connection.recvmsg(
            size, ancillary_size, flags
        )
        self.ancillary = ancillary
        self.flags = flags
        return packet, ancillary, flags, address

    def close(self) -> None:
        self.connection.close()


class _InstrumentedLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.first = threading.Event()
        self.second = threading.Event()
        self.release = threading.Event()

    def __enter__(self) -> None:
        if not self._lock.acquire(blocking=False):
            self.second.set()
            self._lock.acquire()
            return
        self.first.set()
        self.release.wait()

    def __exit__(self, *_: object) -> None:
        self._lock.release()


def _receive_packet(bundle: AdmittedAuthorityDescriptors) -> bytes:
    with patch.object(socket_module, "MSG_CMSG_CLOEXEC", 1, create=True):
        return _receive_authority_packet(bundle)


def _send_packet(connection: object, packet: bytes) -> None:
    with patch.object(socket_module, "MSG_NOSIGNAL", 64, create=True):
        _send_authority_packet(connection, packet)


class TestPrimeP1AuthorityProcess(unittest.TestCase):
    def _config_fd(self, *, values: dict[str, str] | None = None) -> int:
        root = Path(tempfile.mkdtemp(dir=Path.cwd()))
        path = root / "operator.env"
        self.addCleanup(lambda: root.rmdir())
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        settings = values or {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/a",
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
            "ASTERION_PRIME_P1_MODEL_ID": "model",
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/a",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "key",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
            "DEEPSEEK_API_KEY": "secret",
        }
        path.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))
        path.chmod(0o600)
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)

    def test_private_ready_execute_exchange_rejects_malformed_config_before_ready_and_closes_once(
        self,
    ) -> None:
        session_id = "a" * 64
        secret = "CONFIG_SECRET_SENTINEL"
        settings = {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/a",
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/a",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "key",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
            "DEEPSEEK_API_KEY": secret,
        }
        key_read, key_write = os.pipe()
        os.write(key_write, b"k" * 32)
        os.close(key_write)
        config_read = self._config_fd(values=settings)
        connection = _ExchangeSocket((b"unused", [], 0, None))
        native_close = os.close
        closed: list[int] = []

        def close_fd(fd: int) -> None:
            closed.append(fd)
            native_close(fd)

        import asterion.applications.prime_agent.operator.authority_config as config_module

        bundle = AdmittedAuthorityDescriptors(
            connection, key_read, config_read, close_fd
        )
        with (
            patch.object(config_module.os, "close", side_effect=close_fd),
            patch.object(socket_module, "MSG_CMSG_CLOEXEC", 1, create=True),
            patch.object(socket_module, "MSG_NOSIGNAL", 64, create=True),
            self.assertRaises(PrimeP1AuthorityBootstrapError) as raised,
        ):
            _run_ready_execute_exchange(bundle, session_id)
        self.assertEqual(connection.calls, [])
        self.assertTrue(connection.closed)
        self.assertEqual(closed.count(key_read), 1)
        self.assertEqual(closed.count(config_read), 1)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(secret, rendered)
        self.assertNotIn(secret, repr(raised.exception))

    def test_pre_ready_resource_gate_never_consumes_key_or_socket(self) -> None:
        session_id = "a" * 64
        secret = "RESOURCE_SECRET_SENTINEL"
        key_read, key_write = os.pipe()
        os.write(key_write, b"k" * 32)
        os.close(key_write)
        config_read = self._config_fd(
            values={
                **{
                    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
                    "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
                    "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/a",
                    "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
                    "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
                    "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
                    "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
                    "ASTERION_PRIME_P1_MODEL_ID": "model",
                    "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/a",
                    "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "key",
                    "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
                },
                "DEEPSEEK_API_KEY": secret,
            }
        )
        connection = _ExchangeSocket(AssertionError("transport must not run"))
        native_close = os.close
        closed: list[int] = []

        def close_fd(fd: int) -> None:
            closed.append(fd)
            native_close(fd)

        class ForbiddenAccess(BaseException):
            pass

        def forbidden(*_: object, **__: object) -> object:
            raise ForbiddenAccess("host or handshake access is forbidden")

        import asterion.applications.prime_agent.operator.authority_config as config_module
        import asterion.applications.prime_agent.operator.authority_process as module

        bundle = AdmittedAuthorityDescriptors(
            connection, key_read, config_read, close_fd
        )
        with (
            patch.object(config_module.os, "close", side_effect=close_fd),
            patch.object(bundle, "consume_session_key_fd", side_effect=forbidden),
            patch.object(bundle, "consume_socket", side_effect=forbidden),
            patch.object(module, "_consume_session_key", side_effect=forbidden),
            patch.object(module, "_send_authority_packet", side_effect=forbidden),
            patch.object(
                module, "_receive_authority_packet_from_connection", side_effect=forbidden
            ),
            patch.object(module.os, "getenv", side_effect=forbidden),
            patch.object(module.os, "getcwd", side_effect=forbidden),
            patch.object(module.os, "system", side_effect=forbidden),
            patch.object(module.socket, "socket", side_effect=forbidden),
            self.assertRaises(PrimeP1AuthorityBootstrapError) as raised,
        ):
            _run_ready_execute_exchange(bundle, session_id)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(secret, "".join(traceback.format_exception(raised.exception)))
        self.assertEqual(connection.calls, [])
        self.assertTrue(connection.closed)
        self.assertEqual(closed.count(key_read), 1)
        self.assertEqual(closed.count(config_read), 1)

    def test_pre_ready_cleanup_normalizes_arbitrary_socket_and_fd_close_errors(
        self,
    ) -> None:
        class RuntimeCloseSocket(_ExchangeSocket):
            def __init__(self) -> None:
                super().__init__(AssertionError("transport must not run"))
                self.close_attempts = 0

            def close(self) -> None:
                self.close_attempts += 1
                raise RuntimeError("SOCKET_CLOSE_SENTINEL")

        key_read, key_write = os.pipe()
        os.write(key_write, b"k" * 32)
        os.close(key_write)
        config_read = self._config_fd()
        connection = RuntimeCloseSocket()
        close_attempts: list[int] = []

        def failing_close(fd: int) -> None:
            close_attempts.append(fd)
            raise RuntimeError("FD_CLOSE_SENTINEL")

        def cleanup_key() -> None:
            try:
                os.close(key_read)
            except OSError:
                pass

        self.addCleanup(cleanup_key)
        bundle = AdmittedAuthorityDescriptors(
            connection, key_read, config_read, failing_close
        )
        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            _run_ready_execute_exchange(bundle, "a" * 64)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn("SOCKET_CLOSE_SENTINEL", rendered)
        self.assertNotIn("FD_CLOSE_SENTINEL", rendered)
        self.assertEqual(connection.close_attempts, 1)
        self.assertEqual(close_attempts, [key_read])
        with self.assertRaises(OSError):
            os.fstat(config_read)

    def test_rejected_descriptor_subclass_uses_base_cleanup_without_override(
        self,
    ) -> None:
        class OverrideCloseBundle(AdmittedAuthorityDescriptors):
            def __init__(self, connection: object, close_fd: object) -> None:
                super().__init__(connection, 101, 102, cast(Any, close_fd))
                self.override_called = False

            def close(self) -> None:
                self.override_called = True
                raise RuntimeError("OVERRIDE_CLOSE_SENTINEL")

        class RuntimeCloseSocket:
            def __init__(self) -> None:
                self.attempts = 0

            def close(self) -> None:
                self.attempts += 1
                raise RuntimeError("SOCKET_CLOSE_SENTINEL")

        connection = RuntimeCloseSocket()
        closed: list[int] = []

        def failing_close(fd: int) -> None:
            closed.append(fd)
            raise RuntimeError("FD_CLOSE_SENTINEL")

        bundle = OverrideCloseBundle(connection, failing_close)
        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            _run_ready_execute_exchange(bundle, "a" * 64)
        self.assertIsNone(raised.exception.__context__)
        self.assertFalse(bundle.override_called)
        self.assertEqual(connection.attempts, 1)
        self.assertEqual(closed, [101, 102])
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn("OVERRIDE_CLOSE_SENTINEL", rendered)
        self.assertNotIn("SOCKET_CLOSE_SENTINEL", rendered)
        self.assertNotIn("FD_CLOSE_SENTINEL", rendered)

    def test_pre_ready_resource_gate_stays_unavailable_after_future_resolution(
        self,
    ) -> None:
        key_read, key_write = os.pipe()
        os.write(key_write, b"k" * 32)
        os.close(key_write)
        connection = _ExchangeSocket(AssertionError("transport must not run"))
        bundle = AdmittedAuthorityDescriptors(
            connection, key_read, self._config_fd(), os.close
        )
        import asterion.applications.prime_agent.operator.authority_process as module

        class ForbiddenAccess(BaseException):
            pass

        with (
            patch.object(module, "admit_static_image_resource", return_value=object()) as admit,
            patch.object(bundle, "consume_session_key_fd", side_effect=ForbiddenAccess),
            patch.object(bundle, "consume_socket", side_effect=ForbiddenAccess),
            self.assertRaises(PrimeP1AuthorityBootstrapError),
        ):
            _run_ready_execute_exchange(bundle, "a" * 64)
        admit.assert_called_once()
        self.assertEqual(connection.calls, [])
        self.assertTrue(connection.closed)

    def test_spoofed_descriptor_class_never_receives_cleanup_access(self) -> None:
        class ForbiddenAccess(BaseException):
            pass

        class SpoofedDescriptor:
            class_queries = 0

            @property
            def __class__(  # type: ignore[reportIncompatibleMethodOverride]
                self,
            ) -> type[AdmittedAuthorityDescriptors]:
                SpoofedDescriptor.class_queries += 1
                return AdmittedAuthorityDescriptors

            def __getattribute__(self, _: str) -> object:
                raise ForbiddenAccess("SPOOFED_DESCRIPTOR_ACCESS")

        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            cast(Any, _run_ready_execute_exchange)(SpoofedDescriptor(), "a" * 64)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(SpoofedDescriptor.class_queries, 0)
        self.assertNotIn(
            "SPOOFED_DESCRIPTOR_ACCESS",
            "".join(traceback.format_exception(raised.exception)),
        )

    def test_descriptor_cleanup_ancestry_never_uses_hostile_equality(self) -> None:
        class EqualityTrap(type):
            def __eq__(self, _: object) -> bool:
                raise BaseException("MRO_EQUALITY_SENTINEL")

        class TrappedDescriptor(metaclass=EqualityTrap):
            pass

        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            cast(Any, _run_ready_execute_exchange)(TrappedDescriptor(), "a" * 64)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(
            "MRO_EQUALITY_SENTINEL",
            "".join(traceback.format_exception(raised.exception)),
        )

    def test_pre_ready_resource_gate_rejects_legacy_digest_arguments(self) -> None:
        with self.assertRaises(TypeError):
            cast(Any, _run_ready_execute_exchange)(
                object(), "a" * 64, "b" * 64, "c" * 64
            )
        with self.assertRaises(TypeError):
            cast(Any, _run_ready_execute_exchange)(
                object(),
                "a" * 64,
                request_contract_sha256="b" * 64,
                resource_set_sha256="c" * 64,
            )

    def test_connection_level_packet_receive_never_closes_caller_connection(
        self,
    ) -> None:
        for responses, expected in (
            ([(b"x", [], 0, None)], b"x"),
            ([(b"x", [], socket_module.MSG_TRUNC, None)], None),
        ):
            with self.subTest(responses=responses):
                connection = _PacketSocket(list(responses))
                with patch.object(socket_module, "MSG_CMSG_CLOEXEC", 1, create=True):
                    if expected is None:
                        with self.assertRaises(PrimeP1AuthorityBootstrapError):
                            _receive_authority_packet_from_connection(connection)
                    else:
                        self.assertEqual(
                            _receive_authority_packet_from_connection(connection),
                            expected,
                        )
                self.assertFalse(connection.closed)
                self.assertEqual(connection.close_calls, 0)

    def test_private_packet_send_emits_exact_packet_without_ancillary_or_socket_ownership_change(
        self,
    ) -> None:
        connection = _SendingSocket([3])
        _send_packet(connection, b"abc")
        self.assertEqual(connection.calls, [([b"abc"], [], 64)])

    def test_private_packet_send_rejects_invalid_partial_and_redacts_transport_errors(
        self,
    ) -> None:
        for packet, results in (
            (b"", [0]),
            (bytearray(b"x"), [1]),
            (b"x" * 8193, [8193]),
            (b"x", [0]),
            (b"x", [2]),
            (b"x", [OSError("SEND_SENTINEL")]),
        ):
            with self.subTest(packet=type(packet), results=results):
                connection = _SendingSocket(list(results))
                with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
                    _send_packet(connection, packet)  # type: ignore[arg-type]
                self.assertIsNone(raised.exception.__context__)
                self.assertNotIn(
                    "SEND_SENTINEL",
                    "".join(traceback.format_exception(raised.exception)),
                )

        for capability in (None, False, 0):
            with self.subTest(capability=capability):
                with patch.object(
                    socket_module, "MSG_NOSIGNAL", capability, create=True
                ):
                    with self.assertRaises(PrimeP1AuthorityBootstrapError):
                        _send_authority_packet(_SendingSocket([1]), b"x")

    def test_private_packet_send_retries_eintr_eight_times_then_fails_closed(
        self,
    ) -> None:
        results: list[object] = [OSError(errno.EINTR, "SEND_SENTINEL")] * 8
        results.append(1)
        connection = _SendingSocket(results)
        _send_packet(connection, b"x")
        self.assertEqual(len(connection.calls), 9)
        exhausted = _SendingSocket([OSError(errno.EINTR, "SEND_SENTINEL")] * 9)
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            _send_packet(exhausted, b"x")
        self.assertEqual(len(exhausted.calls), 9)

    def test_private_packet_receive_requires_cmsg_cloexec_without_zero_fallback(
        self,
    ) -> None:
        connection = _PacketSocket([(b"x", [], 0, None)])
        with patch.object(socket_module, "MSG_CMSG_CLOEXEC", None, create=True):
            with self.assertRaises(PrimeP1AuthorityBootstrapError):
                _receive_authority_packet(
                    AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
                )
        self.assertTrue(connection.closed)
        self.assertEqual(connection.flags, [])

        connection = _PacketSocket([(b"x", [], 0, None)])
        with patch.object(socket_module, "MSG_CMSG_CLOEXEC", 64, create=True):
            self.assertEqual(
                _receive_authority_packet(
                    AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
                ),
                b"x",
            )
        self.assertEqual(connection.flags, [64])

        class _Flags(enum.IntFlag):
            CLOEXEC = 128

        connection = _PacketSocket([(b"x", [], 0, None)])
        with patch.object(
            socket_module, "MSG_CMSG_CLOEXEC", _Flags.CLOEXEC, create=True
        ):
            self.assertEqual(
                _receive_authority_packet(
                    AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
                ),
                b"x",
            )
        self.assertEqual(connection.flags, [128])

    def test_private_packet_receive_rejects_real_scm_rights_without_obtaining_fd(
        self,
    ) -> None:
        if sys.platform != "linux" or not all(
            hasattr(socket_module, name)
            for name in ("SCM_RIGHTS", "MSG_CTRUNC", "MSG_CMSG_CLOEXEC")
        ):
            self.skipTest("Linux SCM_RIGHTS MSG_CMSG_CLOEXEC is unavailable")
        sender, receiver = socket_module.socketpair(
            socket_module.AF_UNIX, socket_module.SOCK_STREAM
        )
        sent_fd, write_fd = os.pipe()
        self.addCleanup(lambda: os.close(write_fd))
        self.addCleanup(lambda: os.close(sent_fd))
        self.addCleanup(sender.close)
        wrapped = _RecordingUnixSocket(receiver)
        sender.sendmsg(
            [b"x"],
            [
                (
                    socket_module.SOL_SOCKET,
                    socket_module.SCM_RIGHTS,
                    array("i", [sent_fd]),
                )
            ],
        )
        received_flags: list[int] = []
        native_close = os.close

        def inspect_then_close(fd: int) -> None:
            received_flags.append(fcntl.fcntl(fd, fcntl.F_GETFD))
            native_close(fd)

        with (
            patch(
                "asterion.applications.prime_agent.operator.authority_process.os.close",
                side_effect=inspect_then_close,
            ),
            self.assertRaises(PrimeP1AuthorityBootstrapError),
        ):
            _receive_authority_packet(
                AdmittedAuthorityDescriptors(wrapped, 11, 12, lambda _: None)
            )
        self.assertIsNotNone(wrapped.ancillary)
        flags = wrapped.flags
        assert flags is not None
        self.assertTrue(wrapped.ancillary or flags & socket_module.MSG_CTRUNC)
        if wrapped.ancillary:
            received_fd = array("i")
            received_fd.frombytes(wrapped.ancillary[0][2])
            with self.assertRaises(OSError):
                os.fstat(received_fd[0])
        self.assertEqual(len(received_flags), 1)
        self.assertTrue(received_flags[0] & fcntl.FD_CLOEXEC)
        with self.assertRaises(OSError):
            os.fstat(receiver.fileno())

    def test_private_packet_receive_returns_one_raw_packet_and_closes_consumed_socket(
        self,
    ) -> None:
        connection = _PacketSocket([(b'{"canonical":true}', [], 0, None)])
        bundle = AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
        self.assertEqual(_receive_packet(bundle), b'{"canonical":true}')
        self.assertTrue(connection.closed)
        self.assertEqual(connection.close_calls, 1)
        self.assertEqual(connection.flags, [1])
        bundle.close()
        self.assertTrue(connection.closed)
        self.assertEqual(connection.close_calls, 1)

    def test_private_packet_receive_rejects_transport_shapes_and_bounds_eintr(
        self,
    ) -> None:
        invalid = (
            [(b"x", [], socket_module.MSG_TRUNC, None)],
            [(b"x", [], int(socket_module.MSG_CTRUNC), None)],
            [(b"x", [(1, 2, b"fd")], 0, None)],
            [(b"", [], 0, None)],
            [(None, [], 0, None)],
            [(b"x" * 8193, [], 0, None)],
            [OSError("RECV_SENTINEL")],
        )
        for responses in invalid:
            with self.subTest(responses=responses):
                connection = _PacketSocket(list(responses))
                bundle = AdmittedAuthorityDescriptors(
                    connection, 11, 12, lambda _: None
                )
                with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
                    _receive_packet(bundle)
                self.assertIsNone(raised.exception.__context__)
                self.assertNotIn(
                    "RECV_SENTINEL",
                    "".join(traceback.format_exception(raised.exception)),
                )
                self.assertTrue(connection.closed)

        connection = _PacketSocket(
            [OSError(errno.EINTR, "SENTINEL"), (b"x", [], 0, None)]
        )
        self.assertEqual(
            _receive_packet(
                AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
            ),
            b"x",
        )
        self.assertEqual(connection.calls, 2)
        exhausted = _PacketSocket([OSError(errno.EINTR, "SENTINEL")] * 9)
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            _receive_packet(
                AdmittedAuthorityDescriptors(exhausted, 11, 12, lambda _: None)
            )
        self.assertEqual(exhausted.calls, 9)
        success_responses: list[object] = [OSError(errno.EINTR, "SENTINEL")] * 8
        success_responses.append((b"x", [], 0, None))
        succeeded = _PacketSocket(success_responses)
        self.assertEqual(
            _receive_packet(
                AdmittedAuthorityDescriptors(succeeded, 11, 12, lambda _: None)
            ),
            b"x",
        )
        self.assertEqual(succeeded.calls, 9)

    def test_private_packet_receive_redacts_close_failure(self) -> None:
        connection = _PacketSocket([(b"x", [], 0, None)])
        connection.close = lambda: (_ for _ in ()).throw(OSError("CLOSE_SENTINEL"))  # type: ignore[method-assign]
        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            _receive_packet(
                AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
            )
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(
            "CLOSE_SENTINEL", "".join(traceback.format_exception(raised.exception))
        )

    def test_private_session_key_reader_handles_eof_eintr_matrix_and_bounds_retries(
        self,
    ) -> None:
        for reads, expected in (
            ((b"k" * 32, OSError(errno.EINTR, "SENTINEL"), b""), b"k" * 32),
            ((b"k" * 32, OSError(errno.EINTR, "SENTINEL"), b"x"), None),
            ((b"k" * 32, None), None),
            ((b"k" * 32, ""), None),
            ((b"k" * 32, 0), None),
        ):
            with self.subTest(reads=reads):
                descriptors = AdmittedAuthorityDescriptorsForTest(
                    11, close_fd=lambda _: None
                )
                values = iter(reads)

                def reader(_fd: int, _size: int) -> bytes:
                    value = next(values)
                    if isinstance(value, OSError):
                        raise value
                    return value  # type: ignore[return-value]

                if expected is None:
                    with self.assertRaises(PrimeP1AuthorityBootstrapError):
                        _consume_session_key(
                            descriptors.bundle, reader=reader, close_fd=lambda _: None
                        )
                else:
                    self.assertEqual(
                        _consume_session_key(
                            descriptors.bundle, reader=reader, close_fd=lambda _: None
                        ),
                        expected,
                    )

        attempts = 0
        descriptors = AdmittedAuthorityDescriptorsForTest(11, close_fd=lambda _: None)

        def always_interrupted(_fd: int, _size: int) -> bytes:
            nonlocal attempts
            attempts += 1
            raise OSError(errno.EINTR, "SENTINEL")

        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            _consume_session_key(
                descriptors.bundle, reader=always_interrupted, close_fd=lambda _: None
            )
        self.assertEqual(
            attempts, 9
        )  # Eight retries, then the ninth EINTR fails closed.

        values = iter(
            [OSError(errno.EINTR, "SENTINEL")] * 4
            + [b"k" * 32]
            + [OSError(errno.EINTR, "SENTINEL")] * 4
            + [b""]
        )
        descriptors = AdmittedAuthorityDescriptorsForTest(11, close_fd=lambda _: None)

        def bounded_reader(_fd: int, _size: int) -> bytes:
            value = next(values)
            if isinstance(value, OSError):
                raise value
            return value

        self.assertEqual(
            _consume_session_key(
                descriptors.bundle, reader=bounded_reader, close_fd=lambda _: None
            ),
            b"k" * 32,
        )

    def test_private_session_key_reader_discards_reader_and_closer_exception_context(
        self,
    ) -> None:
        for reader, closer in (
            (
                lambda *_: (_ for _ in ()).throw(OSError("READER_SENTINEL")),
                lambda _: None,
            ),
            (
                (lambda values=iter((b"k" * 32, b"")): lambda *_: next(values))(),
                lambda _: (_ for _ in ()).throw(OSError("CLOSE_SENTINEL")),
            ),
        ):
            with self.subTest(reader=reader, closer=closer):
                descriptors = AdmittedAuthorityDescriptorsForTest(
                    11, close_fd=lambda _: None
                )
                with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
                    _consume_session_key(
                        descriptors.bundle, reader=reader, close_fd=closer
                    )
                self.assertIsNone(raised.exception.__context__)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn("READER_SENTINEL", rendered)
                self.assertNotIn("CLOSE_SENTINEL", rendered)

    def test_private_session_key_reader_consumes_exact_key_and_closes_fd_once(
        self,
    ) -> None:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"k" * 32)
        os.close(write_fd)
        descriptors = AdmittedAuthorityDescriptorsForTest(read_fd)
        key = _consume_session_key(descriptors.bundle)
        self.assertEqual(key, b"k" * 32)
        with self.assertRaises(OSError):
            os.fstat(read_fd)
        descriptors.bundle.close()

    def test_private_session_key_reader_rejects_short_extra_or_reader_error_without_leaks(
        self,
    ) -> None:
        for reads in ((b"k" * 31, b""), (b"k" * 32, b"x"), (OSError("SENTINEL_KEY"),)):
            with self.subTest(reads=reads):
                closed: list[int] = []
                descriptors = AdmittedAuthorityDescriptorsForTest(
                    11, close_fd=closed.append
                )
                values = iter(reads)

                def reader(_fd: int, _size: int) -> bytes:
                    value = next(values)
                    if isinstance(value, BaseException):
                        raise value
                    return value

                with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
                    _consume_session_key(
                        descriptors.bundle, reader=reader, close_fd=closed.append
                    )
                self.assertEqual(
                    str(raised.exception), "prime P1 authority bootstrap is unavailable"
                )
                self.assertNotIn("SENTINEL_KEY", repr(raised.exception))
                self.assertEqual(closed, [11])
                descriptors.bundle.close()
                self.assertEqual(closed, [11])

    def test_private_session_key_reader_retries_bounded_eintr_and_redacts_close_error(
        self,
    ) -> None:
        closed: list[int] = []
        descriptors = AdmittedAuthorityDescriptorsForTest(11, close_fd=closed.append)
        values = iter((OSError(errno.EINTR, "SENTINEL_KEY"), b"k" * 32, b""))

        def interrupted_reader(_fd: int, _size: int) -> bytes:
            value = next(values)
            if isinstance(value, OSError):
                raise value
            return value

        self.assertEqual(
            _consume_session_key(
                descriptors.bundle,
                reader=interrupted_reader,
                close_fd=closed.append,
            ),
            b"k" * 32,
        )
        self.assertEqual(closed, [11])

        descriptors = AdmittedAuthorityDescriptorsForTest(12, close_fd=lambda _: None)
        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            _consume_session_key(
                descriptors.bundle,
                reader=lambda *_: b"k" * 32,
                close_fd=lambda _: (_ for _ in ()).throw(OSError("SENTINEL_KEY")),
            )
        self.assertNotIn("SENTINEL_KEY", repr(raised.exception))

    def test_instrumented_consume_vs_consume_has_one_owner(self) -> None:
        closed: list[int] = []
        bundle = AdmittedAuthorityDescriptors(
            _Socket(peer=(300, 400)), 11, 12, closed.append
        )
        lock = _InstrumentedLock()
        bundle._lock = lock  # type: ignore[assignment]
        results: list[object] = []

        def consume() -> None:
            try:
                results.append(bundle.consume_session_key_fd())
            except PrimeP1AuthorityBootstrapError:
                results.append("unavailable")

        first, second = (
            threading.Thread(target=consume),
            threading.Thread(target=consume),
        )
        first.start()
        self.assertTrue(lock.first.wait(1))
        second.start()
        self.assertTrue(lock.second.wait(1))
        lock.release.set()
        first.join()
        second.join()
        self.assertCountEqual(results, [11, "unavailable"])

    def test_instrumented_consume_vs_close_preserves_returned_fd(self) -> None:
        closed: list[int] = []
        bundle = AdmittedAuthorityDescriptors(
            _Socket(peer=(300, 400)), 11, 12, closed.append
        )
        lock = _InstrumentedLock()
        bundle._lock = lock  # type: ignore[assignment]
        result: list[int] = []
        consumer = threading.Thread(
            target=lambda: result.append(bundle.consume_session_key_fd())
        )
        consumer.start()
        self.assertTrue(lock.first.wait(1))
        closer = threading.Thread(target=bundle.close)
        closer.start()
        self.assertTrue(lock.second.wait(1))
        lock.release.set()
        consumer.join()
        closer.join()
        self.assertEqual(result, [11])
        self.assertEqual(closed, [12])

    def test_consume_then_close_never_closes_returned_fd(self) -> None:
        closed: list[int] = []
        bundle = AdmittedAuthorityDescriptors(
            _Socket(peer=(300, 400)), 11, 12, closed.append
        )
        self.assertEqual(bundle.consume_session_key_fd(), 11)
        bundle.close()
        self.assertEqual(closed, [12])

    def test_close_wins_before_consume_closes_fd_once(self) -> None:
        closed: list[int] = []
        bundle = AdmittedAuthorityDescriptors(
            _Socket(peer=(300, 400)), 11, 12, closed.append
        )
        bundle.close()
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            bundle.consume_session_key_fd()
        self.assertEqual(closed, [11, 12])

    def test_concurrent_consumers_have_exactly_one_owner(self) -> None:
        admitted = admit_retained_authority_descriptors(
            AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400),
            platform_name="linux",
            effective_uid=lambda: 100,
            process_id=lambda: 200,
            socket_factory=lambda _: _Socket(peer=(300, 400)),
            get_fd_flags=lambda _: 1,
            peer_credentials=lambda _: (300, 400),
            close_fd=lambda _: None,
            seqpacket_type=5,
            peercred_option=17,
        )
        barrier = threading.Barrier(3)
        results: list[object] = []

        def consume() -> None:
            barrier.wait()
            try:
                results.append(admitted.consume_session_key_fd())
            except PrimeP1AuthorityBootstrapError:
                results.append("unavailable")

        threads = [threading.Thread(target=consume), threading.Thread(target=consume)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertCountEqual(results, [11, "unavailable"])

    def test_constructor_failure_closes_every_inherited_descriptor(self) -> None:
        closed: list[int] = []
        connection = _Socket(peer=(300, 400))
        with patch(
            "asterion.applications.prime_agent.operator.authority_process.AdmittedAuthorityDescriptors",
            side_effect=MemoryError,
        ):
            with self.assertRaises(PrimeP1AuthorityBootstrapError):
                admit_retained_authority_descriptors(
                    AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400),
                    platform_name="linux",
                    effective_uid=lambda: 100,
                    process_id=lambda: 200,
                    socket_factory=lambda _: connection,
                    get_fd_flags=lambda _: 1,
                    peer_credentials=lambda _: (300, 400),
                    close_fd=closed.append,
                    seqpacket_type=5,
                    peercred_option=17,
                )
        self.assertTrue(connection.closed)
        self.assertEqual(closed, [11, 12])

    def test_retained_bundle_transfers_each_descriptor_once_and_closes_only_unconsumed(
        self,
    ) -> None:
        closed: list[int] = []
        connection = _Socket(peer=(300, 400))
        admitted = admit_retained_authority_descriptors(
            AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400),
            platform_name="linux",
            effective_uid=lambda: 100,
            process_id=lambda: 200,
            socket_factory=lambda _: connection,
            get_fd_flags=lambda _: 1,
            peer_credentials=lambda _: (300, 400),
            close_fd=closed.append,
            seqpacket_type=5,
            peercred_option=17,
        )
        self.assertEqual(repr(admitted), "AdmittedAuthorityDescriptors(redacted)")
        self.assertIs(admitted.consume_socket(), connection)
        self.assertEqual(admitted.consume_session_key_fd(), 11)
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            admitted.consume_socket()
        admitted.close()
        admitted.close()
        self.assertEqual(closed, [12])
        self.assertFalse(connection.closed)
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            admitted.consume_config_fd()

    def test_retained_admission_failure_closes_every_transferred_descriptor_once(
        self,
    ) -> None:
        closed: list[int] = []
        connection = _Socket(peer=(999, 400))
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            admit_retained_authority_descriptors(
                AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400),
                platform_name="linux",
                effective_uid=lambda: 100,
                process_id=lambda: 200,
                socket_factory=lambda _: connection,
                get_fd_flags=lambda _: 1,
                peer_credentials=lambda _: (999, 400),
                close_fd=closed.append,
                seqpacket_type=5,
                peercred_option=17,
            )
        self.assertTrue(connection.closed)
        self.assertEqual(closed, [11, 12])

    def test_rejects_non_linux_before_any_weak_fallback_and_closes_all_fds(
        self,
    ) -> None:
        closed: list[int] = []
        contract = AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400)
        with self.assertRaisesRegex(PrimeP1AuthorityBootstrapError, "unavailable"):
            admit_authority_launch(
                contract, platform_name="darwin", close_fd=closed.append
            )
        self.assertEqual(closed, [10, 11, 12])

    def test_admits_only_exact_linux_seqpacket_cloexec_and_peer_identity(self) -> None:
        closed: list[int] = []
        socket = _Socket(peer=(300, 400))
        contract = AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400)
        bootstrap = admit_authority_launch(
            contract,
            platform_name="linux",
            effective_uid=lambda: 100,
            process_id=lambda: 200,
            socket_factory=lambda _: socket,
            get_fd_flags=lambda _: 1,
            peer_credentials=lambda _: (300, 400),
            close_fd=closed.append,
            seqpacket_type=5,
            peercred_option=17,
        )
        self.assertEqual(repr(bootstrap), "AuthorityBootstrap(redacted)")
        self.assertEqual(closed, [11, 12])
        self.assertTrue(socket.closed)

    def test_rejects_duplicate_or_noninteger_descriptors_and_closes_unique_integer_fds(
        self,
    ) -> None:
        for contract, expected_closed in (
            (AuthorityLaunchContract(10, 10, 12, 100, 200, 300, 400), [10, 12]),
            (AuthorityLaunchContract(10, "11", 12, 100, 200, 300, 400), [10, 12]),  # type: ignore[arg-type]
        ):
            with self.subTest(contract=repr(contract)):
                closed: list[int] = []
                with self.assertRaises(PrimeP1AuthorityBootstrapError):
                    admit_authority_launch(
                        contract, platform_name="linux", close_fd=closed.append
                    )
                self.assertEqual(closed, expected_closed)

    def test_rejects_missing_cloexec_wrong_socket_or_wrong_peer_without_leaking_details(
        self,
    ) -> None:
        cases = ((0, 5, (300, 400)), (1, 1, (300, 400)), (1, 5, (999, 400)))
        for flags, socket_type, peer in cases:
            with self.subTest(flags=flags, socket_type=socket_type, peer=peer):
                closed: list[int] = []
                socket = _Socket(peer=peer, socket_type=socket_type)
                with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
                    admit_authority_launch(
                        AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400),
                        platform_name="linux",
                        effective_uid=lambda: 100,
                        process_id=lambda: 200,
                        socket_factory=lambda _: socket,
                        get_fd_flags=lambda _: flags,
                        peer_credentials=lambda _: peer,
                        close_fd=closed.append,
                        seqpacket_type=5,
                        peercred_option=17,
                    )
                self.assertEqual(
                    str(raised.exception), "prime P1 authority bootstrap is unavailable"
                )
                self.assertNotIn("999", repr(raised.exception))
                self.assertEqual(closed, [11, 12] if flags else [10, 11, 12])
                self.assertEqual(socket.closed, flags != 0)

    def test_accepts_socketkind_constant_and_rejects_identity_collisions(self) -> None:
        contract = AuthorityLaunchContract(10, 11, 12, 100, 200, 300, 400)
        admitted = admit_authority_launch(
            contract,
            platform_name="linux",
            effective_uid=lambda: 100,
            process_id=lambda: 200,
            socket_factory=lambda _: _Socket(peer=(300, 400)),
            get_fd_flags=lambda _: 1,
            peer_credentials=lambda _: (300, 400),
            close_fd=lambda _: None,
            seqpacket_type=socket_module.SOCK_SEQPACKET,
            peercred_option=17,
        )
        self.assertEqual(repr(admitted), "AuthorityBootstrap(redacted)")
        for authority_uid, authority_pid, supervisor_uid, supervisor_pid in (
            (100, 200, 100, 400),
            (100, 200, 300, 200),
            (100, 0, 300, 400),
        ):
            with self.subTest(
                values=(authority_uid, authority_pid, supervisor_uid, supervisor_pid)
            ):
                with self.assertRaises(PrimeP1AuthorityBootstrapError):
                    admit_authority_launch(
                        AuthorityLaunchContract(
                            10,
                            11,
                            12,
                            authority_uid,
                            authority_pid,
                            supervisor_uid,
                            supervisor_pid,
                        ),
                        platform_name="linux",
                        close_fd=lambda _: None,
                    )


class AdmittedAuthorityDescriptorsForTest:
    """Build the opaque bundle only through test-local trusted inputs."""

    def __init__(self, session_key_fd: int, *, close_fd: object = os.close) -> None:
        self.bundle = AdmittedAuthorityDescriptors(
            _Socket(peer=(300, 400)),
            session_key_fd,
            12,
            close_fd,  # type: ignore[arg-type]
        )
        self.bundle.consume_config_fd()


if __name__ == "__main__":
    unittest.main()
