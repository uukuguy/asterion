"""Provider-free tests for the closed P1 trusted host orchestration path."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import unittest
from typing import cast

import asterion.applications.prime_agent.operator.ipython_host_orchestrator as subject
from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerModelResponse,
    DockerWorkerWorkspaceSnapshot,
)
from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostExpectedIdentity,
)
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerUsage
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import RestrictedWorkerLease


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"
_CELL = "def answer() -> int:\n    return 42\n"
_CHALLENGE = "sha256:" + "a" * 64
_WORKLOAD = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"


def _identity(**changes: object) -> IpythonHostExpectedIdentity:
    values: dict[str, object] = {
        "assembly_id": "prime.capability-program@1.0.0",
        "package_id": "prime-agent@1.0.0",
        "implementation_id": "prime.ipython-coding@1.0.0",
        "image_digest": "sha256:" + "b" * 64,
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


class _HostAdapter(subject._IpythonHostAdapter):
    def __init__(self, identity: IpythonHostExpectedIdentity) -> None:
        self.identity = identity
        self.calls: list[str] = []
        self.pre = _INITIAL
        self.post = _FINAL
        self.sent_digest = "sha256:" + sha256(_CELL.encode()).hexdigest()
        self.broker_identity = identity
        self.cleanup_error: BaseException | None = None
        self.signal: _Signal | None = None

    async def snapshot(self, lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
        self.calls.append("snapshot")
        return DockerWorkerWorkspaceSnapshot(self.pre if self.calls.count("snapshot") == 1 else self.post)

    async def brokered_cell(self, lease: RestrictedWorkerLease) -> subject._IpythonBrokeredCell:
        self.calls.append("brokered_cell")
        usage = PrimeModelBrokerUsage("session-1", lease.run_id, lease.worker_id, lease.challenge_digest, 1, 3, len(_CELL.encode()))
        return subject._IpythonBrokeredCell(
            identity=self.broker_identity,
            response=DockerWorkerModelResponse(lease.workload_digest, "ipython", _CELL),
            sent_cell_digest=self.sent_digest,
            model_receipt_digest="sha256:" + "c" * 64,
            usage=usage,
        )

    async def revoke_broker(self, lease: RestrictedWorkerLease) -> None:
        self.calls.append("revoke_broker")

    async def force_remove(self, lease: RestrictedWorkerLease) -> None:
        self.calls.append("force_remove")
        if self.cleanup_error is not None:
            raise self.cleanup_error

    async def assert_absent(self, lease: RestrictedWorkerLease) -> None:
        self.calls.append("assert_absent")


class TestIpythonHostOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def test_orders_host_attestations_and_returns_body_free_completion(self) -> None:
        adapter = _HostAdapter(_identity())
        completion = await subject.run_ipython_host_orchestration(_identity(), _lease(), adapter)

        self.assertEqual(completion.status, "PASS")
        self.assertEqual(adapter.calls, ["snapshot", "brokered_cell", "snapshot", "revoke_broker", "force_remove", "assert_absent"])
        self.assertNotIn(_CELL, repr(completion))

    async def test_rejects_manual_worker_terminal_frames_as_completion_facts(self) -> None:
        adapter = _HostAdapter(_identity())
        adapter.completed_frame = {"terminal": "completed", "stdout": "SECRET"}  # type: ignore[attr-defined]
        with self.assertRaises(subject.IpythonHostOrchestrationError) as raised:
            await subject.run_ipython_host_orchestration(
                _identity(), _lease(), cast(subject._IpythonHostAdapter, object())
            )
        self.assertNotIn("SECRET", str(raised.exception))

    async def test_rejects_mismatched_broker_identity_or_sent_cell_digest(self) -> None:
        for changed in ("identity", "digest"):
            with self.subTest(changed=changed):
                adapter = _HostAdapter(_identity())
                if changed == "identity":
                    adapter.broker_identity = _identity(image_digest="sha256:" + "d" * 64)
                else:
                    adapter.sent_digest = "sha256:" + "d" * 64
                with self.assertRaises(subject.IpythonHostOrchestrationError):
                    await subject.run_ipython_host_orchestration(_identity(), _lease(), adapter)
                self.assertEqual(adapter.calls[-2:], ["force_remove", "assert_absent"])

    async def test_cancellation_propagates_after_complete_cleanup(self) -> None:
        adapter = _HostAdapter(_identity())
        signal = _Signal()
        adapter.signal = signal
        original = adapter.brokered_cell

        async def cancelling(lease: RestrictedWorkerLease) -> subject._IpythonBrokeredCell:
            value = await original(lease)
            signal.cancelled_value = True
            return value

        adapter.brokered_cell = cancelling  # type: ignore[method-assign]
        with self.assertRaises(asyncio.CancelledError):
            await subject.run_ipython_host_orchestration(_identity(), _lease(), adapter, signal=signal)
        self.assertEqual(adapter.calls[-3:], ["revoke_broker", "force_remove", "assert_absent"])

    async def test_outer_cancellation_waits_for_cleanup_then_propagates(self) -> None:
        adapter = _HostAdapter(_identity())
        removal_started, release_removal = asyncio.Event(), asyncio.Event()

        async def slow_remove(lease: RestrictedWorkerLease) -> None:
            adapter.calls.append("force_remove")
            removal_started.set()
            await release_removal.wait()

        adapter.force_remove = slow_remove  # type: ignore[method-assign]
        task = asyncio.create_task(subject.run_ipython_host_orchestration(_identity(), _lease(), adapter))
        await removal_started.wait()
        task.cancel()
        release_removal.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(adapter.calls[-2:], ["force_remove", "assert_absent"])

    async def test_cleanup_failure_never_issues_completion_and_is_redacted(self) -> None:
        adapter = _HostAdapter(_identity())
        adapter.cleanup_error = RuntimeError("SECRET-CONTAINER-PATH")
        with self.assertRaises(subject.IpythonHostOrchestrationError) as raised:
            await subject.run_ipython_host_orchestration(_identity(), _lease(), adapter)
        self.assertNotIn("SECRET", str(raised.exception))
        self.assertEqual(adapter.calls[-1], "force_remove")
