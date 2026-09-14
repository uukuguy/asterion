"""Native P1 runtime state machine and exact dispatch tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast
import unittest

from asterion.applications.prime.p1.runtime_binding import (
    P1_RUNTIME_OPTIONS,
    P1WorkerOwnerAdapter,
    build_p1_runtime,
)
from asterion.applications.prime.p1.worker import P1WorkerCleanupReceipt
from asterion.applications.prime.runtime_binding import (
    _ERROR,
    build_asterion_prime_runtime,
    build_p7_runtime,
)
from asterion.capabilities.prime_ipython_coding_native.host import (
    P1Finalization,
    P1RuntimeHost,
    P1RuntimeHostError,
    P1StageMilestone,
    P1StageTwoRelease,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError


ASSEMBLY = (
    Path(__file__).resolve().parents[1]
    / "src/asterion/applications/prime/assemblies/prime-ipython-coding.json"
)
DIGESTS = tuple(f"{index:x}" * 64 for index in range(1, 7))


class _Service(P1RuntimeHost):
    def __init__(self, final: str = "completed", fail_at: str | None = None) -> None:
        self.final = final
        self.fail_at = fail_at
        self.calls: list[object] = []

    def validate_runtime_services(
        self,
        *,
        ipython: object,
        oracle: object,
        pi_extension: object,
        private_trace: object,
    ) -> None:
        self.calls.append(
            (
                "validate-runtime-services",
                ipython,
                oracle,
                pi_extension,
                private_trace,
            )
        )

    async def execute_stage_one(
        self, *, run_id: str, signal: object
    ) -> P1StageMilestone:
        del signal
        self.calls.append(("stage-one", run_id))
        if self.fail_at == "budget":
            raise P1RuntimeHostError("budget-limited")
        if self.fail_at == "recovery":
            raise P1RuntimeHostError("recovery-required")
        return P1StageMilestone("stage-one", DIGESTS[0], 11, 7)

    async def publish_milestone(
        self, *, run_id: str, milestone: P1StageMilestone
    ) -> None:
        self.calls.append(("publish", run_id, milestone.stage, milestone.effect_sha256))

    async def wait_stage_two_release(
        self, *, run_id: str, stage_one: P1StageMilestone, signal: object
    ) -> P1StageTwoRelease:
        del signal
        self.calls.append(("wait-release", run_id, stage_one.effect_sha256))
        return P1StageTwoRelease(DIGESTS[1], DIGESTS[2], 300, 120, 2, 14_744)

    async def execute_stage_two(
        self, *, run_id: str, release: P1StageTwoRelease, signal: object
    ) -> P1StageMilestone:
        del signal
        self.calls.append(("stage-two", run_id, release.checkpoint_sha256))
        return P1StageMilestone("stage-two", DIGESTS[3], 13, 5)

    async def report_execution_stopped(
        self, *, run_id: str, pending_classification: str
    ) -> None:
        self.calls.append(("execution-stopped", run_id, pending_classification))

    async def wait_finalization(self, *, run_id: str, signal: object) -> P1Finalization:
        del signal
        self.calls.append(("wait-finalization", run_id))
        if self.fail_at == "finalization":
            raise RuntimeError("private-finalization-failure")
        digest = DIGESTS[4] if self.final == "completed" else None
        return P1Finalization(cast(object, self.final), digest)  # type: ignore[arg-type]


def _context(service: object, **changes: object) -> RuntimeFactoryContext:
    values: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.ipython-coding",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": ASSEMBLY,
        "options": P1_RUNTIME_OPTIONS,
        "host_services": {
            "prime.ipython": object(),
            "prime.p1-oracle": object(),
            "prime.launch": object(),
            "prime.private-trace": object(),
            "prime.session-backend": service,
        },
    }
    values.update(changes)
    return RuntimeFactoryContext(**values)  # type: ignore[arg-type]


async def _events(service: _Service):
    runtime = build_p1_runtime(_context(service))
    return tuple(
        [
            event
            async for event in runtime.run(
                RunRequest(
                    "p1-runtime-test",
                    "fixed-small-verification",
                    ("prime.tool.ipython",),
                    600_000,
                )
            )
        ]
    )


class TestAsterionPrimeP1Runtime(unittest.TestCase):
    def test_runtime_options_are_fixed_and_immutable(self) -> None:
        self.assertEqual(
            dict(P1_RUNTIME_OPTIONS),
            {
                "aggregate_tokens": "64000",
                "cost_micros": "500000",
                "deadline_ms": "600000",
                "max_callbacks": "8",
                "max_tool_callbacks": "4",
            },
        )
        with self.assertRaises(TypeError):
            P1_RUNTIME_OPTIONS["deadline_ms"] = "1"  # type: ignore[index]

    def test_worker_owner_adapter_preserves_lifecycle_token_and_close_receipt(
        self,
    ) -> None:
        token = object()
        receipt = P1WorkerCleanupReceipt(DIGESTS[0], DIGESTS[1], True, True, True, 1)

        class Worker:
            identity_sha256 = DIGESTS[0]
            cleanup_receipt = None

            def validate_lifecycle(self) -> object:
                return token

            async def close(self) -> P1WorkerCleanupReceipt:
                self.cleanup_receipt = receipt
                return receipt

        adapter = P1WorkerOwnerAdapter(Worker())  # type: ignore[arg-type]
        self.assertIs(adapter.validate_lifecycle(), token)
        self.assertIsNone(adapter.cleanup_receipt)
        asyncio.run(adapter.close())
        self.assertIs(adapter.cleanup_receipt, receipt)
        asyncio.run(adapter.close())
        self.assertIs(adapter.cleanup_receipt, receipt)

    def test_worker_owner_adapter_rejects_non_digest_identity(self) -> None:
        class Worker:
            identity_sha256 = "z" * 64
            cleanup_receipt = None

            def validate_lifecycle(self) -> object:
                return object()

            async def close(self) -> P1WorkerCleanupReceipt:
                raise AssertionError("invalid worker must not be closed")

        with self.assertRaisesRegex(RuntimeFactoryError, _ERROR):
            P1WorkerOwnerAdapter(Worker())  # type: ignore[arg-type]

    def test_success_owns_stage_machine_and_projects_one_safe_receipt(self) -> None:
        service = _Service()
        events = asyncio.run(_events(service))

        self.assertEqual(
            [event.type for event in events],
            [
                "run.started",
                "usage.reported",
                "usage.reported",
                "artifact.created",
                "run.completed",
            ],
        )
        self.assertEqual([event.sequence for event in events], [1, 2, 3, 4, 5])
        self.assertEqual(events[-1].payload, {"status": "completed"})
        artifact = events[-2].payload["artifact"]
        self.assertEqual(
            artifact,
            {
                "artifact_id": "prime.p1-native.receipt",
                "kind": "p1-native",
                "media_type": "application/vnd.asterion.prime.p1-native-receipt+json",
                "sha256": DIGESTS[4],
            },
        )
        self.assertEqual(
            service.calls[1:],
            [
                ("stage-one", "p1-runtime-test"),
                ("publish", "p1-runtime-test", "stage-one", DIGESTS[0]),
                ("wait-release", "p1-runtime-test", DIGESTS[0]),
                ("stage-two", "p1-runtime-test", DIGESTS[1]),
                ("publish", "p1-runtime-test", "stage-two", DIGESTS[3]),
                ("execution-stopped", "p1-runtime-test", "completed"),
                ("wait-finalization", "p1-runtime-test"),
            ],
        )
        validation_call = service.calls[0]
        self.assertIsInstance(validation_call, tuple)
        assert isinstance(validation_call, tuple)
        self.assertEqual(validation_call[0], "validate-runtime-services")

    def test_budget_and_uncertain_recovery_map_to_fixed_failed_terminals(self) -> None:
        cases = (
            ("budget", "budget-limited", "p1_budget_limited"),
            ("recovery", "recovery-required", "p1_recovery_required"),
        )
        for fail_at, final, code in cases:
            with self.subTest(fail_at=fail_at):
                service = _Service(final=final, fail_at=fail_at)
                events = asyncio.run(_events(service))
                self.assertEqual(
                    [event.type for event in events], ["run.started", "run.failed"]
                )
                self.assertEqual(events[-1].payload["code"], code)
                self.assertNotIn("budget-limited", repr(events[-1].payload))
                self.assertEqual(
                    service.calls[-2:],
                    [
                        ("execution-stopped", "p1-runtime-test", final),
                        ("wait-finalization", "p1-runtime-test"),
                    ],
                )

    def test_aggregate_usage_includes_both_stages_and_compact_charge(self) -> None:
        class AggregateBudgetService(_Service):
            async def execute_stage_one(
                self, *, run_id: str, signal: object
            ) -> P1StageMilestone:
                del signal
                self.calls.append(("stage-one", run_id))
                return P1StageMilestone("stage-one", DIGESTS[0], 20_000, 10_000)

            async def wait_stage_two_release(
                self,
                *,
                run_id: str,
                stage_one: P1StageMilestone,
                signal: object,
            ) -> P1StageTwoRelease:
                del signal
                self.calls.append(("wait-release", run_id, stage_one.effect_sha256))
                return P1StageTwoRelease(DIGESTS[1], DIGESTS[2], 300, 120, 2, 16_000)

            async def execute_stage_two(
                self, *, run_id: str, release: P1StageTwoRelease, signal: object
            ) -> P1StageMilestone:
                del signal
                self.calls.append(("stage-two", run_id, release.checkpoint_sha256))
                return P1StageMilestone("stage-two", DIGESTS[3], 10_000, 10_000)

        service = AggregateBudgetService(final="budget-limited")
        events = asyncio.run(_events(service))

        self.assertEqual(events[-1].type, "run.failed")
        self.assertEqual(events[-1].payload["code"], "p1_budget_limited")
        self.assertNotIn("artifact.created", [event.type for event in events])
        self.assertIn(
            ("execution-stopped", "p1-runtime-test", "budget-limited"),
            service.calls,
        )

    def test_missing_cleanup_gated_finalization_is_a_protocol_failure(self) -> None:
        service = _Service(fail_at="finalization")

        with self.assertRaisesRegex(
            ProtocolError, "P1 runtime finalization failed"
        ) as raised:
            asyncio.run(_events(service))
        self.assertNotIn("private-finalization-failure", str(raised.exception))
        self.assertEqual(service.calls[-1], ("wait-finalization", "p1-runtime-test"))

    def test_missing_extra_and_structurally_invalid_hosts_reject_before_use(
        self,
    ) -> None:
        exact = dict(_context(_Service()).host_services)
        cases = {
            "missing": {
                key: value for key, value in exact.items() if key != "prime.ipython"
            },
            "extra": {**exact, "prime.unknown": object()},
            "invalid": {**exact, "prime.session-backend": object()},
        }
        for name, services in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeFactoryError, _ERROR):
                    build_p1_runtime(_context(_Service(), host_services=services))

    def test_single_binding_dispatches_exact_p1_and_p7_keys_only(self) -> None:
        service = _Service()
        self.assertIs(
            type(build_asterion_prime_runtime(_context(service))),
            type(build_p1_runtime(_context(service))),
        )

        unknown = _context(service, application_id="prime.unknown")
        with self.assertRaisesRegex(RuntimeFactoryError, _ERROR):
            build_asterion_prime_runtime(unknown)

        self.assertTrue(callable(build_p7_runtime))


if __name__ == "__main__":
    unittest.main()
