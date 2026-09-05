"""Fail-closed bootstrap tests for the Linux-only P1 authority process."""

from __future__ import annotations

import os
import socket as socket_module
import threading
import traceback
import unittest
import errno
from array import array
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_process import (
    AuthorityLaunchContract,
    AdmittedAuthorityDescriptors,
    PrimeP1AuthorityBootstrapError,
    admit_authority_launch,
    admit_retained_authority_descriptors,
    _consume_session_key,
    _receive_authority_packet,
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

    def recvmsg(self, _size: int, _ancillary_size: int) -> object:
        self.calls += 1
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class _RecordingUnixSocket:
    def __init__(self, connection: socket_module.socket) -> None:
        self.connection = connection
        self.ancillary: list[tuple[int, int, bytes]] | None = None
        self.flags: int | None = None

    def recvmsg(
        self, size: int, ancillary_size: int
    ) -> tuple[bytes, list[tuple[int, int, bytes]], int, object]:
        packet, ancillary, flags, address = self.connection.recvmsg(
            size, ancillary_size
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


class TestPrimeP1AuthorityProcess(unittest.TestCase):
    def test_private_packet_receive_rejects_real_scm_rights_without_obtaining_fd(
        self,
    ) -> None:
        if not all(
            hasattr(socket_module, name) for name in ("SCM_RIGHTS", "MSG_CTRUNC")
        ):
            self.skipTest("SCM_RIGHTS or MSG_CTRUNC is unavailable")
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
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
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
        with self.assertRaises(OSError):
            os.fstat(receiver.fileno())

    def test_private_packet_receive_returns_one_raw_packet_and_closes_consumed_socket(
        self,
    ) -> None:
        connection = _PacketSocket([(b'{"canonical":true}', [], 0, None)])
        bundle = AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
        self.assertEqual(_receive_authority_packet(bundle), b'{"canonical":true}')
        self.assertTrue(connection.closed)
        self.assertEqual(connection.close_calls, 1)
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
                    _receive_authority_packet(bundle)
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
            _receive_authority_packet(
                AdmittedAuthorityDescriptors(connection, 11, 12, lambda _: None)
            ),
            b"x",
        )
        self.assertEqual(connection.calls, 2)
        exhausted = _PacketSocket([OSError(errno.EINTR, "SENTINEL")] * 9)
        with self.assertRaises(PrimeP1AuthorityBootstrapError):
            _receive_authority_packet(
                AdmittedAuthorityDescriptors(exhausted, 11, 12, lambda _: None)
            )
        self.assertEqual(exhausted.calls, 9)
        success_responses: list[object] = [OSError(errno.EINTR, "SENTINEL")] * 8
        success_responses.append((b"x", [], 0, None))
        succeeded = _PacketSocket(success_responses)
        self.assertEqual(
            _receive_authority_packet(
                AdmittedAuthorityDescriptors(succeeded, 11, 12, lambda _: None)
            ),
            b"x",
        )
        self.assertEqual(succeeded.calls, 9)

    def test_private_packet_receive_redacts_close_failure(self) -> None:
        connection = _PacketSocket([(b"x", [], 0, None)])
        connection.close = lambda: (_ for _ in ()).throw(OSError("CLOSE_SENTINEL"))  # type: ignore[method-assign]
        with self.assertRaises(PrimeP1AuthorityBootstrapError) as raised:
            _receive_authority_packet(
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
