"""Fail-closed bootstrap tests for the Linux-only P1 authority process."""

from __future__ import annotations

import unittest
import socket as socket_module
import threading
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_process import (
    AuthorityLaunchContract,
    AdmittedAuthorityDescriptors,
    PrimeP1AuthorityBootstrapError,
    admit_authority_launch,
    admit_retained_authority_descriptors,
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


if __name__ == "__main__":
    unittest.main()
