from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkModelError,
    BenchmarkTaskImplementation,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    ResolvedCapability,
    public_plan_dict,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    BenchmarkTaskBinding,
    BenchmarkTaskManifest,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


class ExampleBenchmarkImplementation:
    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id="example.binding",
            public_arguments=("case-limit", str(request.case_limit)),
            private_payload={"secret": "SECRET-PAYLOAD"},
        )


class BenchmarkModelTests(unittest.TestCase):
    def test_task_request_is_frozen_and_hides_output_directory(self) -> None:
        request = BenchmarkTaskRequest(
            run_id="run-001",
            suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
            task_id="example.task",
            case_limit=3,
            output_directory=Path("/private/SECRET-output"),
        )

        with self.assertRaises(FrozenInstanceError):
            setattr(request, "case_limit", 4)
        self.assertNotIn("SECRET-output", repr(request))
        self.assertEqual(str(request.output_directory), "/private/SECRET-output")

    def test_task_invocation_snapshots_public_arguments_and_hides_private_payload(
        self,
    ) -> None:
        arguments = ["symbolic", "limit-3"]
        invocation = BenchmarkTaskInvocation(
            task_id="example.task",
            binding_id="example.binding",
            public_arguments=cast(tuple[str, ...], arguments),
            private_payload={"secret": "SECRET-PAYLOAD"},
        )
        arguments.append("mutated")

        self.assertEqual(invocation.public_arguments, ("symbolic", "limit-3"))
        self.assertNotIn("SECRET-PAYLOAD", repr(invocation))
        with self.assertRaises(FrozenInstanceError):
            setattr(invocation, "binding_id", "changed")

    def test_task_implementation_protocol_is_runtime_checkable(self) -> None:
        self.assertIsInstance(ExampleBenchmarkImplementation(), BenchmarkTaskImplementation)

    def test_resolved_plan_snapshots_tuples_and_public_dict_redacts_private_values(
        self,
    ) -> None:
        tasks = [self._resolved_task(1, "example.task")]
        locks = [
            CapabilitySourceLock(
                entries=(
                    CapabilitySourceLockEntry(
                        package_ref=CapabilityPackageRef("example.package", "1.0.0"),
                        payload_sha256="a" * 64,
                        source_id="example-source",
                    ),
                )
            )
        ]
        plan = ResolvedBenchmarkPlan(
            run_id="run-001",
            application_ref=ApplicationRef("example.application", "1.0.0"),
            suite=self._suite("example.task"),
            tasks=cast(tuple[ResolvedBenchmarkTask, ...], tasks),
            case_limit=5,
            package_locks=cast(tuple[CapabilitySourceLock, ...], locks),
        )
        tasks.append(self._resolved_task(2, "example.other"))
        locks.clear()

        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(len(plan.package_locks), 1)
        self.assertEqual(
            public_plan_dict(plan),
            {
                "run_id": "run-001",
                "application": "example.application@1.0.0",
                "suite": "example.suite@1.0.0",
                "case_limit": 5,
                "tasks": [
                    {
                        "ordinal": 1,
                        "task_id": "example.task",
                        "capability": "example.capability@1.0.0",
                        "binding_id": "example.binding",
                    }
                ],
            },
        )
        rendered = repr(plan) + repr(public_plan_dict(plan))
        for sentinel in (
            "SECRET-PAYLOAD",
            "SECRET-output",
            "IMPLEMENTATION-SECRET",
            "/private",
        ):
            self.assertNotIn(sentinel, rendered)

    def test_resolved_plan_rejects_invalid_case_limit_ordinals_and_duplicate_tasks(
        self,
    ) -> None:
        valid_task = self._resolved_task(1, "example.task")

        cases = (
            (
                "case limit",
                {"case_limit": 0, "tasks": (valid_task,)},
            ),
            (
                "ordinal gap",
                {"case_limit": 1, "tasks": (self._resolved_task(2, "example.task"),)},
            ),
            (
                "duplicate task",
                {
                    "case_limit": 1,
                    "tasks": (
                        valid_task,
                        self._resolved_task(2, "example.task"),
                    ),
                },
            ),
        )
        for label, overrides in cases:
            with self.subTest(label):
                with self.assertRaises(BenchmarkModelError):
                    self._plan(**overrides)

    def _plan(
        self,
        *,
        case_limit: int = 1,
        tasks: tuple[ResolvedBenchmarkTask, ...] | None = None,
    ) -> ResolvedBenchmarkPlan:
        return ResolvedBenchmarkPlan(
            run_id="run-001",
            application_ref=ApplicationRef("example.application", "1.0.0"),
            suite=self._suite("example.task"),
            tasks=tasks if tasks is not None else (self._resolved_task(1, "example.task"),),
            case_limit=case_limit,
            package_locks=(),
        )

    def _suite(self, *task_ids: str) -> BenchmarkSuiteManifest:
        return BenchmarkSuiteManifest(
            suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
            owner_package=CapabilityPackageRef("example.package", "1.0.0"),
            tasks=tuple(self._task_manifest(task_id) for task_id in task_ids),
            artifact_media_types=("application/json",),
            default_case_limit=10,
            default_concurrency=1,
        )

    def _task_manifest(self, task_id: str) -> BenchmarkTaskManifest:
        return BenchmarkTaskManifest(
            task_id=task_id,
            capability=CapabilityRef("example.capability", "1.0.0"),
            binding_id="example.binding",
            metric_contract_id="example.metric",
            result_contract_id="example.result",
            note="public note",
        )

    def _resolved_task(self, ordinal: int, task_id: str) -> ResolvedBenchmarkTask:
        return ResolvedBenchmarkTask(
            ordinal=ordinal,
            task=self._task_manifest(task_id),
            capability=ResolvedCapability(
                ref=CapabilityRef("example.capability", "1.0.0"),
                manifest={"kind": "example.capability", "secret": "SECRET-PAYLOAD"},
            ),
            binding=BenchmarkTaskBinding(
                owner_package=CapabilityPackageRef("example.package", "1.0.0"),
                binding_id="example.binding",
                implementation=SecretImplementation(),
            ),
        )


class SecretImplementation:
    def __repr__(self) -> str:
        return "IMPLEMENTATION-SECRET"


if __name__ == "__main__":
    unittest.main()
