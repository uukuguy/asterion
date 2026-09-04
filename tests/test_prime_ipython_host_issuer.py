"""Provider-free tests for the concrete P1 Docker/model live-run issuer."""

from __future__ import annotations

import unittest

from asterion.applications.prime_agent.operator.ipython_host_supervisor import IpythonHostExpectedIdentity
from asterion.applications.prime_agent.operator.launcher_barrier import PrimeLauncherBarrier
from asterion.applications.prime_agent.operator.model_broker import _new_host_coordinator
from asterion.services.bounded_model_session import BoundedModelSessionLease, BoundedModelSessionRequest
from tests.test_prime_docker_worker import _IMAGE_DIGEST, _Transport, _request


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"


class TestIpythonHostIssuer(unittest.IsolatedAsyncioTestCase):
    def test_issuer_has_no_public_generic_factory(self) -> None:
        import asterion.applications.prime_agent.operator.ipython_host_issuer as subject

        self.assertEqual(subject.__all__, ())
        self.assertFalse(hasattr(subject, "issue_live_run"))

    async def test_manual_production_capability_cannot_issue_a_live_run(self) -> None:
        import asterion.applications.prime_agent.operator.ipython_host_issuer as subject

        with self.assertRaisesRegex(Exception, "unavailable"):
            await subject._issue_production_ipython_host_live_run(  # noqa: SLF001
                capability=object()
            )


class TestConcreteIpythonHostIssuer(unittest.IsolatedAsyncioTestCase):
    async def test_fake_docker_and_provider_cannot_issue_a_public_pass(self) -> None:
        import asterion.applications.prime_agent.operator.ipython_host_issuer as subject
        from asterion.applications.prime_agent.operator.docker_worker import DockerRestrictedWorkerService

        transport = _Transport()
        snapshots = iter((_INITIAL, _FINAL))

        async def snapshot_solution(container_id: str, *, control: object) -> bytes:
            transport.assert_container_id(container_id)
            transport.calls.append("snapshot_solution")
            return next(snapshots)

        transport.snapshot_solution = snapshot_solution  # type: ignore[method-assign]
        service = DockerRestrictedWorkerService(image_digest=_IMAGE_DIGEST, transport=transport)
        request = _request()
        async with service.open(request) as lease:
            attestation = await service.attest(lease)
            barrier = PrimeLauncherBarrier(
                role_id=lease.role_id, run_id=lease.run_id,
                challenge_digest=lease.challenge_digest, workload_digest=lease.workload_digest,
            )
            barrier.admit(lease, attestation)

            async def provider(_body: bytes) -> bytes:
                return _FINAL

            broker = _new_host_coordinator(
                lease=BoundedModelSessionLease("session-1", lease.run_id),
                session=BoundedModelSessionRequest(
                    run_id=lease.run_id, max_requests=1, max_input_tokens=128,
                    max_output_tokens=128, max_input_bytes=128, max_output_bytes=128,
                    max_cost_microunits=1, deadline_seconds=10,
                ),
                worker=lease, barrier=barrier, provider=provider, session_id="session-1",
                worker_id=lease.worker_id, run_id=lease.run_id,
                challenge_digest=lease.challenge_digest, cleanup_grace_seconds=0.1,
            )
            identity = IpythonHostExpectedIdentity(
                "prime.ipython-coding@1.0.0", "prime-agent@1.0.0",
                "prime.ipython-coding@1.0.0", _IMAGE_DIGEST, lease.workload_digest,
                "sha256:85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
                "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
                "sha256:486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a",
            )
            with self.assertRaisesRegex(Exception, "unavailable"):
                subject._issue_docker_model_live_run(  # noqa: SLF001
                    service=service, lease=lease, identity=identity, broker=broker,
                )
        self.assertNotIn("model_response", transport.calls)
