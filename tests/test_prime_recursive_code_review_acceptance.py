"""Provider-free P3 acceptance must not inspect or promote injected services."""

from __future__ import annotations

import unittest
import json

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.operator.recursive_code_review_workload import RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
from asterion.applications.prime_agent.operator.recursive_code_review_release import canonical_recursive_code_review_frame
from asterion.applications.prime_agent.operator.recursive_code_review_worker import (
    RecursiveCodeReviewBroker, RecursiveCodeReviewDockerWorker, RecursiveCodeReviewInspection,
)
from asterion.applications.prime_agent.recursive_code_review_acceptance import (
    RecursiveCodeReviewAcceptanceError,
    RecursiveCodeReviewProviderFreeObservation,
    accept_recursive_code_review,
)
from asterion.applications.prime_agent.restricted_worker import PrimeRestrictedWorkerProfile
from asterion.services.restricted_worker import RestrictedWorkerRequest
from asterion.services.restricted_worker import RestrictedWorkerLease


_IMAGE = "sha256:" + "a" * 64
_CHALLENGE = "sha256:" + "b" * 64


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = dict(image_digest=_IMAGE, network_mode="none", workspace_mode="disposable", credential_mode="absent", max_runtime_seconds=1, max_output_bytes=53260)
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = dict(role_id="prime.recursive-workflow", image_digest=_IMAGE, run_id="run-1", challenge_digest=_CHALLENGE, workload_digest=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST, max_runtime_seconds=1, max_output_bytes=53260)
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


class _Probe:
    accesses = 0

    def __getattribute__(self, name: str) -> object:
        if name != "accesses":
            type(self).accesses += 1
        return super().__getattribute__(name)


def _completion() -> bytes:
    from tests.test_prime_recursive_code_review_launcher_protocol import _stream

    frames: list[bytes] = []
    for raw in _stream().rstrip(b"\n").split(b"\n"):
        frame = json.loads(raw)
        frames.append(canonical_recursive_code_review_frame(
            worker_id="worker-1", run_id="run-1", challenge_digest=_CHALLENGE,
            workload_digest=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
            sequence=frame["sequence"], kind=frame["kind"], payload=frame["payload"],
        ))
    return b"\n".join(frames) + b"\n"


class _Engine:
    async def launch(self, **_: object) -> RestrictedWorkerLease:
        return RestrictedWorkerLease("worker-1", "prime.recursive-workflow", "run-1", _CHALLENGE, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST)

    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
        return _completion()

    async def inspect(self, lease: RestrictedWorkerLease) -> RecursiveCodeReviewInspection:
        return RecursiveCodeReviewInspection(lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest, lease.workload_digest, _IMAGE, "/usr/local/bin/prime-recursive-code-review.mjs", "prime-recursive-code-review", (), True, True, True, True, True, True, True)

    async def remove(self, lease: RestrictedWorkerLease) -> None:
        return None


class _Endpoint:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def admit_root(self, lease: RestrictedWorkerLease) -> None:
        self.events.append("admit")

    async def relay_once(self, body: bytes) -> bytes:
        self.events.append("relay")
        return _completion()

    async def revoke(self) -> None:
        self.events.append("revoke")


class TestRecursiveCodeReviewAcceptance(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _Probe.accesses = 0

    async def test_fake_full_chain_revokes_destroys_and_stays_provider_free(self) -> None:
        endpoint = _Endpoint()
        receipt = await accept_recursive_code_review(
            profile=_profile(), request=_request(),
            worker=RecursiveCodeReviewDockerWorker(image_digest=_IMAGE, engine=_Engine()),
            broker=RecursiveCodeReviewBroker(endpoint),
            observation=RecursiveCodeReviewProviderFreeObservation("asterion.prime-recursive-code-review-fixture/v1", True, True),
        )
        self.assertEqual(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
        self.assertEqual(endpoint.events, ["admit", "relay", "revoke"])

    async def test_invalid_profile_rejects_before_service_access(self) -> None:
        worker, broker = _Probe(), _Probe()
        with self.assertRaises(RecursiveCodeReviewAcceptanceError):
            await accept_recursive_code_review(profile=_profile(network_mode="host"), request=_request(), worker=worker, broker=broker, observation=object())
        self.assertEqual(_Probe.accesses, 0)
