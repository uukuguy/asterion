"""Focused development-only P1 Docker/model host wiring checks."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerTokenUsage,
)
from asterion.services.restricted_worker import RestrictedWorkerLease
from tests.test_prime_docker_worker import _IMAGE_DIGEST, _Transport


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"


class _Provider:
    async def __call__(self, _body: bytes) -> bytes:
        return b"from pathlib import Path\nPath('/workspace/solution.py').write_text('def answer() -> int:\\n    return 42\\n')"

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        return PrimeModelBrokerTokenUsage(3, 4, 5)


class TestPrimeP1DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_development_run_waits_for_request_then_snapshots_and_cleans_up(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_host as subject,
        )

        transport = _Transport()
        transport.lease = RestrictedWorkerLease(
            "worker-1", "prime.ipython-coding", "prime-p1-development-" + "a" * 32,
            subject._CHALLENGE_DIGEST, subject.PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,  # noqa: SLF001
        )
        snapshots = iter((_INITIAL, _FINAL))
        transport.closed = False  # type: ignore[attr-defined]

        async def snapshot_solution(container_id: str, *, control: object) -> bytes:
            del control
            transport.assert_container_id(container_id)
            transport.calls.append("snapshot_solution")
            return next(snapshots)

        transport.snapshot_solution = snapshot_solution  # type: ignore[method-assign]
        transport.close = lambda: setattr(transport, "closed", True)  # type: ignore[attr-defined]
        with (
            patch.object(subject, "uuid4", return_value=SimpleNamespace(hex="a" * 32)),
            patch.object(subject, "DockerCliEngineTransport", return_value=transport),
            patch.object(subject, "create_prime_p1_development_provider", return_value=_Provider()),
        ):
            trace = await subject.run_prime_p1_development(
                docker_executable="/operator/docker",
                socket_path="/operator/docker.sock",
                seccomp_profile_fd=9,
                platform=ImagePlatformDescriptor("linux", "amd64", None),
                image_digest=_IMAGE_DIGEST,
                operator_config={"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
            )

        self.assertEqual((trace.scope, trace.promotion), ("p1-a-development", "unpromoted"))
        self.assertRegex(trace.trace.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertLess(
            transport.calls.index("model_request"), transport.calls.index("snapshot_solution")
        )
        self.assertEqual(transport.calls.count("snapshot_solution"), 2)
        self.assertEqual(transport.calls[-2:], ["force_remove", "assert_absent"])
        self.assertTrue(transport.closed)  # type: ignore[attr-defined]
