from __future__ import annotations

import unittest
from dataclasses import replace
from typing import cast

from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioEngine,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


_IMAGE = "sha256:" + "a" * 64
_DIGEST = "sha256:" + "b" * 64


class TestRestrictedScenarioWorker(unittest.IsolatedAsyncioTestCase):
    async def test_worker_uses_adapter_literals_and_issues_cleanup_receipt(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
            RestrictedScenarioAdapter,
            RestrictedScenarioInspection,
            RestrictedScenarioWorker,
        )

        class Engine:
            def __init__(self) -> None:
                self.launches: list[tuple[object, ...]] = []

            async def launch(self, **kwargs: object) -> RestrictedWorkerLease:
                self.launches.append(
                    tuple(
                        kwargs[name]
                        for name in ("role_id", "env", "entrypoint", "seccomp")
                    )
                )
                return RestrictedWorkerLease(
                    "worker-1", "prime.test", "run-1", _DIGEST, _DIGEST
                )

            async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes:
                return b"ok"

            async def inspect(
                self, lease: RestrictedWorkerLease
            ) -> RestrictedScenarioInspection:
                return RestrictedScenarioInspection(
                    lease,
                    _IMAGE,
                    "/entry",
                    "test-seccomp",
                    (),
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                )

            async def remove(self, lease: RestrictedWorkerLease) -> None:
                self.removed = lease

        adapter = RestrictedScenarioAdapter(
            "prime.test/v1",
            "prime.test",
            _DIGEST,
            "/entry",
            "test-seccomp",
            3,
            8,
            lambda raw: raw == b"ok",
        )
        engine = Engine()
        worker = RestrictedScenarioWorker(
            image_digest=_IMAGE, engine=engine, adapter=adapter
        )
        request = RestrictedWorkerRequest(
            "prime.test", _IMAGE, "run-1", _DIGEST, _DIGEST, 1, 8
        )
        async with worker.open(request) as lease:
            receipt = await worker.execution_receipt(lease)
            self.assertEqual(
                receipt.result_digest,
                "sha256:"
                + "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df",
            )
        self.assertEqual(
            engine.launches, [("prime.test", (), "/entry", "test-seccomp")]
        )
        self.assertTrue((await worker.cleanup_receipt(lease)).destroyed)

    async def test_worker_rejects_foreign_request_before_launch(self) -> None:
        from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
            RestrictedScenarioAdapter,
            RestrictedScenarioWorker,
        )

        class Engine:
            pass

        adapter = RestrictedScenarioAdapter(
            "prime.test/v1",
            "prime.test",
            _DIGEST,
            "/entry",
            "test-seccomp",
            3,
            8,
            lambda raw: raw == b"ok",
        )
        worker = RestrictedScenarioWorker(
            image_digest=_IMAGE,
            engine=cast("RestrictedScenarioEngine", Engine()),
            adapter=adapter,
        )
        request = RestrictedWorkerRequest(
            "prime.test", _IMAGE, "run-1", _DIGEST, _DIGEST, 1, 8
        )
        with self.assertRaises(ValueError):
            worker.open(replace(request, role_id="prime.other"))
