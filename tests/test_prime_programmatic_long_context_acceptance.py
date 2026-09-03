"""Provider-free end-to-end acceptance for the sealed Prime P2 worker."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from hashlib import sha256
from typing import cast
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.programmatic_long_context_acceptance import (
    ProgrammaticLongContextAcceptanceError,
    ProgrammaticLongContextAcceptanceFacts,
    accept_programmatic_long_context,
)
from asterion.applications.prime_agent.restricted_worker import PrimeRestrictedWorkerProfile
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


def _digest(value: str) -> str:
    return "sha256:" + value * 64


_IMAGE = _digest("a")
_CHALLENGE = _digest("b")
_AGGREGATE = _digest("c")
_RESPONSE = "sha256:" + sha256(b"opaque-response").hexdigest()


class _WorkerContext(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(self, worker: "_Worker") -> None:
        self.worker = worker

    async def __aenter__(self) -> RestrictedWorkerLease:
        self.worker.events.append("open")
        return self.worker.lease

    async def __aexit__(self, *args: object) -> None:
        self.worker.events.append("destroy")
        self.worker.destroyed = True


class _Worker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.destroyed = False
        self.lease = RestrictedWorkerLease(
            "worker-1", "prime.programmatic-long-context", "run-1", _CHALLENGE,
            PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        )

    def open(self, request: RestrictedWorkerRequest, **_: object) -> _WorkerContext:
        self.events.append("admit")
        return _WorkerContext(self)

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        self.events.append("attest")
        return RestrictedWorkerAttestation(
            lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
            lease.workload_digest, _IMAGE, True, True, True, True, True, True, True,
        )

    async def execution_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerExecutionReceipt:
        self.events.append("result")
        return RestrictedWorkerExecutionReceipt(
            lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
            lease.workload_digest, _AGGREGATE,
        )

    async def cleanup_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerCleanupReceipt:
        self.events.append("cleanup")
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
            lease.workload_digest, self.destroyed,
        )


class _Broker:
    def __init__(self, events: list[str], **changes: object) -> None:
        self.events = events
        self.changes = changes

    async def admit(self, attestation: RestrictedWorkerAttestation) -> None:
        self.events.append("broker-admit")

    async def release(self) -> bytes:
        self.events.append("release")
        return b"opaque-response"

    async def revoke(self) -> PrimeModelBrokerReceipt:
        self.events.append("revoke")
        values: dict[str, object] = dict(
            session_id="session-1", run_id="run-1", worker_id="worker-1",
            challenge_digest=_CHALLENGE, request_count=1, input_bytes=0,
            output_bytes=15, status="revoked",
        )
        values.update(self.changes)
        return PrimeModelBrokerReceipt(**values)  # type: ignore[arg-type]


class _AttributeProbe:
    def __init__(self) -> None:
        self.accesses = 0

    def __getattr__(self, name: str) -> object:
        self.accesses += 1
        raise AssertionError(f"unexpected attribute access: {name}")


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = dict(
        role_id="prime.programmatic-long-context", image_digest=_IMAGE,
        run_id="run-1", challenge_digest=_CHALLENGE,
        workload_digest=PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        max_runtime_seconds=30, max_output_bytes=4096,
    )
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = dict(
        image_digest=_IMAGE, network_mode="none", workspace_mode="disposable",
        credential_mode="absent", max_runtime_seconds=30, max_output_bytes=4096,
    )
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


def _facts(**changes: object) -> ProgrammaticLongContextAcceptanceFacts:
    values: dict[str, object] = dict(
        built_in_tools=("ipython",), active_tool_names=("ipython",),
        corpus_sha256=PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
        program_sha256=_RESPONSE, response_sha256=_RESPONSE,
        aggregate_sha256=_AGGREGATE, oracle_sha256=PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
        ipython_cell_executed=True, oracle_passed=True,
    )
    values.update(changes)
    return ProgrammaticLongContextAcceptanceFacts(**values)  # type: ignore[arg-type]


class TestProgrammaticLongContextAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_runs_the_fake_full_chain_before_issuing_bounded_evidence(self) -> None:
        worker = _Worker()
        broker = _Broker(worker.events)

        receipt = await accept_programmatic_long_context(
            worker=worker, profile=_profile(), request=_request(), broker=broker, facts=_facts()
        )

        self.assertEqual(worker.events, [
            "admit", "open", "attest", "broker-admit", "release", "result",
            "revoke", "destroy", "cleanup",
        ])
        self.assertEqual(receipt.scenario_id, "prime.programmatic-long-context/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED_SANDBOXED)

    async def test_rejects_all_identity_mismatches_and_never_reduces(self) -> None:
        cases = (
            ("request-role", _request(role_id="prime.ipython-coding"), _facts()),
            ("request-workload", _request(workload_digest=_digest("e")), _facts()),
            ("facts-result", _request(), _facts(aggregate_sha256=_digest("e"))),
            ("facts-response", _request(), _facts(response_sha256=_digest("e"))),
        )
        for name, request, facts in cases:
            with self.subTest(name=name), self.assertRaises(ProgrammaticLongContextAcceptanceError):
                await accept_programmatic_long_context(
                    worker=_Worker(), profile=_profile(), request=request,
                    broker=_Broker([]), facts=facts,
                )

    async def test_rejects_open_sandbox_profiles_before_worker_or_broker_admission(self) -> None:
        cases = (
            ("network", {"network_mode": "bridge"}),
            ("workspace", {"workspace_mode": "persistent"}),
            ("credentials", {"credential_mode": "inherited"}),
        )
        for name, changes in cases:
            worker = _Worker()
            broker = _Broker(worker.events)
            with self.subTest(name=name), self.assertRaises(ProgrammaticLongContextAcceptanceError):
                await accept_programmatic_long_context(
                    worker=worker, profile=_profile(**changes), request=_request(),
                    broker=broker, facts=_facts(),
                )
            self.assertEqual(worker.events, [])

    async def test_invalid_profile_does_not_inspect_injected_service_attributes(self) -> None:
        worker, broker = _AttributeProbe(), _AttributeProbe()

        with self.assertRaises(ProgrammaticLongContextAcceptanceError):
            await accept_programmatic_long_context(
                worker=cast("_Worker", worker), profile=_profile(network_mode="bridge"),
                request=_request(), broker=cast("_Broker", broker), facts=_facts(),
            )

        self.assertEqual((worker.accesses, broker.accesses), (0, 0))

    async def test_rejects_each_broker_identity_or_quiescence_mismatch(self) -> None:
        cases = (
            ("run", {"run_id": "run-2"}),
            ("worker", {"worker_id": "worker-2"}),
            ("challenge", {"challenge_digest": _digest("e")}),
            ("active", {"status": "active"}),
            ("no-requests", {"request_count": 0}),
            ("no-output", {"output_bytes": 0}),
        )
        for name, changes in cases:
            worker = _Worker()
            with self.subTest(name=name), self.assertRaises(ProgrammaticLongContextAcceptanceError):
                await accept_programmatic_long_context(
                    worker=worker, profile=_profile(), request=_request(),
                    broker=_Broker(worker.events, **changes), facts=_facts(),
                )
            self.assertIn("destroy", worker.events)

    async def test_rejects_compatibility_like_facts_without_lifecycle(self) -> None:
        with self.assertRaises(ProgrammaticLongContextAcceptanceError):
            await accept_programmatic_long_context(
                worker=cast("_Worker", object()), profile=_profile(), request=_request(),
                broker=cast("_Broker", object()), facts=_facts(),
            )
