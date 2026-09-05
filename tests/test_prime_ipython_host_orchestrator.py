"""Provider-free tests for the closed P1 trusted host orchestration path."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import unittest
from typing import Any, cast
from unittest.mock import patch

import asterion.applications.prime_agent.operator.ipython_host_orchestrator as subject
from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerModelResponse,
    DockerWorkerWorkspaceSnapshot,
)
from asterion.applications.prime_agent.operator.ipython_host_supervisor import IpythonHostExpectedIdentity
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerReceipt,
    PrimeModelBrokerUsage,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import RestrictedWorkerLease
from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"
_CELL = "def answer() -> int:\n    return 42\n"
_CHALLENGE = "sha256:" + "a" * 64
_WORKLOAD = PRIME_IPYTHON_CODING_WORKLOAD_DIGEST


class _HostCallbackSentinel(BaseException):
    pass


def _identity(**changes: object) -> IpythonHostExpectedIdentity:
    values: dict[str, object] = {
        "assembly_id": "prime.ipython-coding@1.0.0", "package_id": "prime-agent@1.0.0",
        "implementation_id": "prime.ipython-coding@1.0.0", "image_digest": "sha256:" + "b" * 64,
        "workload_digest": _WORKLOAD,
        "oracle_digest": "sha256:85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
        "starter_digest": "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
        "source_digest": "sha256:486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a",
    }
    values.update(changes)
    return IpythonHostExpectedIdentity(**values)  # type: ignore[arg-type]


def _lease() -> RestrictedWorkerLease:
    return RestrictedWorkerLease("worker-1", "prime.ipython-coding", "run-1", _CHALLENGE, _WORKLOAD)


class _Signal(CancellationSignal):
    def __init__(self) -> None:
        self.cancelled_value = False

    @property
    def cancelled(self) -> bool:
        return self.cancelled_value


class _LateHostCallbackSignal(CancellationSignal):
    def __init__(self) -> None:
        self.reads = 0

    @property
    def cancelled(self) -> bool:
        self.reads += 1
        if self.reads == 6:
            raise _HostCallbackSentinel("SENTINEL-LATE-HOST-CALLBACK")
        return False


class _HostOperations:
    def __init__(self, identity: IpythonHostExpectedIdentity) -> None:
        self.identity = identity
        self.calls: list[str] = []
        self.fail_remove: BaseException | None = None
        self.hang_revoke = False
        self.revoke_reaped = False

    async def snapshot(self, lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
        del lease
        self.calls.append("snapshot")
        return DockerWorkerWorkspaceSnapshot(_INITIAL if self.calls.count("snapshot") == 1 else _FINAL)

    async def brokered_cell(self, lease: RestrictedWorkerLease) -> subject._IpythonBrokeredCell:
        self.calls.append("brokered_cell")
        return subject._IpythonBrokeredCell(
            identity=self.identity,
            response=DockerWorkerModelResponse(lease.workload_digest, "ipython", _CELL),
            sent_cell_digest="sha256:" + sha256(_CELL.encode()).hexdigest(),
            model_receipt_digest="sha256:" + "c" * 64,
            usage=PrimeModelBrokerUsage("session-1", lease.run_id, lease.worker_id, lease.challenge_digest, 1, 3, len(_CELL.encode())),
        )

    async def revoke_broker(self, lease: RestrictedWorkerLease) -> PrimeModelBrokerReceipt:
        self.calls.append("revoke_broker")
        if self.hang_revoke:
            try:
                await asyncio.Event().wait()
            finally:
                self.revoke_reaped = True
        return PrimeModelBrokerReceipt(
            "session-1", lease.run_id, lease.worker_id, lease.challenge_digest,
            1, 3, len(_CELL.encode()), "revoked",
        )

    async def force_remove(self, lease: RestrictedWorkerLease) -> None:
        del lease
        self.calls.append("force_remove")
        if self.fail_remove is not None:
            raise self.fail_remove

    async def assert_absent(self, lease: RestrictedWorkerLease) -> None:
        del lease
        self.calls.append("assert_absent")


def _issued(operations: _HostOperations, *, signal: CancellationSignal | None = None) -> subject.IpythonHostLiveRun:
    sealed = subject._IpythonHostOperations(  # noqa: SLF001 - trusted-host fixture
        _seal=subject._LIVE_RUN_SEAL,  # noqa: SLF001 - trusted-host fixture
        snapshot=operations.snapshot, brokered_cell=operations.brokered_cell,
        revoke_broker=operations.revoke_broker, force_remove=operations.force_remove,
        assert_absent=operations.assert_absent,
    )
    return subject._issue_ipython_host_live_run(  # noqa: SLF001 - trusted-host fixture
        identity=operations.identity, lease=_lease(), operations=sealed, signal=signal
    )


class TestIpythonHostOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def test_fake_host_operations_can_return_only_a_body_free_trace(self) -> None:
        operations = _HostOperations(_identity())
        trace = await _issued(operations).trace()
        self.assertFalse(hasattr(trace, "status"))
        self.assertEqual(operations.calls, ["snapshot", "brokered_cell", "snapshot", "revoke_broker", "force_remove", "assert_absent"])
        self.assertNotIn(_CELL, repr(trace))
        self.assertNotIn("PASS", repr(trace))

    async def test_issued_context_and_operations_cannot_be_mutated(self) -> None:
        live_run = _issued(_HostOperations(_identity()))
        with self.assertRaises(AttributeError):
            live_run._signal = None  # noqa: SLF001 - adversarial boundary test
        with self.assertRaises(AttributeError):
            live_run._operations.force_remove = live_run._operations.assert_absent  # noqa: SLF001

    async def test_force_remove_failure_still_attempts_absence_and_redacts(self) -> None:
        operations = _HostOperations(_identity())
        operations.fail_remove = RuntimeError("SECRET-CONTAINER-PATH")
        with self.assertRaises(subject.IpythonHostOrchestrationError) as raised:
            await _issued(operations).trace()
        self.assertEqual(operations.calls[-2:], ["force_remove", "assert_absent"])
        self.assertNotIn("SECRET", str(raised.exception))

    async def test_non_cancellation_base_exception_is_cleaned_up_and_redacted(self) -> None:
        operations = _HostOperations(_identity())

        async def failed_snapshot(lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
            del lease
            operations.calls.append("snapshot")
            raise _HostCallbackSentinel("SENTINEL-HOST-CALLBACK")

        operations.snapshot = failed_snapshot  # type: ignore[method-assign]
        with self.assertRaises(subject.IpythonHostOrchestrationError) as raised:
            await _issued(operations).trace()
        self.assertEqual(operations.calls, ["snapshot", "revoke_broker", "force_remove", "assert_absent"])
        self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_late_signal_base_exception_after_cleanup_is_redacted(self) -> None:
        operations = _HostOperations(_identity())
        signal = _LateHostCallbackSignal()
        with self.assertRaises(subject.IpythonHostOrchestrationError) as raised:
            await _issued(operations, signal=signal).trace()
        self.assertEqual(signal.reads, 6)
        self.assertEqual(operations.calls, ["snapshot", "brokered_cell", "snapshot", "revoke_broker", "force_remove", "assert_absent"])
        self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_hanging_cleanup_revocation_still_attempts_removal_and_absence(self) -> None:
        operations = _HostOperations(_identity())
        operations.hang_revoke = True
        signal = _Signal()
        signal.cancelled_value = True
        with patch.object(subject, "_CLEANUP_SECONDS", 0.03), self.assertRaises(asyncio.CancelledError):
            await _issued(operations, signal=signal).trace()
        self.assertEqual(operations.calls, ["revoke_broker", "force_remove", "assert_absent"])
        self.assertTrue(operations.revoke_reaped)

    async def test_cancellation_resistant_cleanup_is_bounded_and_still_attempts_removal_and_absence(self) -> None:
        operations = _HostOperations(_identity())
        release_revoke = asyncio.Event()

        async def cancellation_resistant_revoke(lease: RestrictedWorkerLease) -> None:
            del lease
            operations.calls.append("revoke_broker")
            while not release_revoke.is_set():
                try:
                    await release_revoke.wait()
                except asyncio.CancelledError:
                    pass

        operations.revoke_broker = cancellation_resistant_revoke  # type: ignore[method-assign]
        signal = _Signal()
        signal.cancelled_value = True
        with patch.object(subject, "_CLEANUP_SECONDS", 0.03):
            task = asyncio.create_task(_issued(operations, signal=signal).trace())
            try:
                await asyncio.sleep(0.06)
                self.assertEqual(operations.calls, ["revoke_broker", "force_remove", "assert_absent"])
            finally:
                release_revoke.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        release_revoke.set()
        await asyncio.sleep(0)

    async def test_caller_cancellation_during_cleanup_overrides_body_failure(self) -> None:
        operations = _HostOperations(_identity())
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def failed_snapshot(lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
            del lease
            operations.calls.append("snapshot")
            raise RuntimeError("SENTINEL-BODY-FAILURE")

        async def blocked_revoke(lease: RestrictedWorkerLease) -> None:
            del lease
            operations.calls.append("revoke_broker")
            cleanup_started.set()
            await release_cleanup.wait()

        operations.snapshot = failed_snapshot  # type: ignore[method-assign]
        operations.revoke_broker = blocked_revoke  # type: ignore[method-assign]
        task = asyncio.create_task(_issued(operations).trace())
        await cleanup_started.wait()
        task.cancel("SENTINEL-CANCELLATION")
        release_cleanup.set()
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task
        self.assertEqual(raised.exception.args, ())
        self.assertEqual(operations.calls, ["snapshot", "revoke_broker", "force_remove", "assert_absent"])

    async def test_adapter_cancellation_is_fresh_redacted_and_cleanup_is_reaped(self) -> None:
        operations = _HostOperations(_identity())

        async def cancelled_snapshot(lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
            del lease
            operations.calls.append("snapshot")
            raise asyncio.CancelledError("SENTINEL-SECRET")

        operations.snapshot = cancelled_snapshot  # type: ignore[method-assign]
        with self.assertRaises(asyncio.CancelledError) as raised:
            await _issued(operations).trace()
        self.assertEqual(raised.exception.args, ())
        self.assertEqual(operations.calls, ["snapshot", "revoke_broker", "force_remove", "assert_absent"])
        self.assertNotIn("SENTINEL", repr(raised.exception))

    async def test_main_cancellation_is_fresh_and_cleanup_completes(self) -> None:
        operations = _HostOperations(_identity())
        snapshot_started = asyncio.Event()

        async def blocked_snapshot(lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
            del lease
            operations.calls.append("snapshot")
            snapshot_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        operations.snapshot = blocked_snapshot  # type: ignore[method-assign]
        task = asyncio.create_task(_issued(operations).trace())
        await snapshot_started.wait()
        task.cancel("SENTINEL-SECRET")
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task
        self.assertEqual(raised.exception.args, ())
        self.assertEqual(operations.calls, ["snapshot", "revoke_broker", "force_remove", "assert_absent"])

    async def test_structural_adapter_cannot_mint_a_public_pass(self) -> None:
        self.assertFalse(hasattr(subject, "run_ipython_host_orchestration"))
        with self.assertRaises(subject.IpythonHostOrchestrationError):
            subject.IpythonHostLiveRun()  # type: ignore[call-arg]

    async def test_private_operation_token_rejects_manual_or_structural_values(self) -> None:
        fake = _HostOperations(_identity())
        with self.assertRaises(subject.IpythonHostOrchestrationError):
            subject._IpythonHostOperations(  # noqa: SLF001 - adversarial boundary test
                _seal=object(), snapshot=cast(Any, fake.snapshot), brokered_cell=cast(Any, fake.brokered_cell),
                revoke_broker=fake.revoke_broker, force_remove=fake.force_remove, assert_absent=fake.assert_absent,
            )

    async def test_public_surface_exports_no_generic_adapter_or_runner(self) -> None:
        self.assertEqual(subject.__all__, ("IpythonHostOrchestrationError", "IpythonHostLiveRun"))
        self.assertFalse(hasattr(subject, "_IpythonHostAdapter"))
        self.assertFalse(hasattr(subject, "IpythonHostCompletion"))
