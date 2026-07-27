from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.benchmarks.model import (
    ApplicationRef,
    BenchmarkPlan,
    BenchmarkTaskImplementation,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    PlannedBenchmarkTask,
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


_SECRET = "OPERATOR_SECRET_SENTINEL"
_PRIVATE_OUTPUT = Path("/operator/private/evidence")
_PRIVATE_CAPABILITY_ROOT = Path("/operator/private/capabilities/example.json")


class _TaskImplementation:
    def __init__(self, private_value: str = _SECRET) -> None:
        self.private_value = private_value

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=f"{request.task_id}.binding",
            public_arguments=("synthetic",),
            private_payload={"credential": self.private_value},
        )


class _NonCallableImplementation:
    build_invocation = "not callable"


class BenchmarkModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = CapabilityPackageRef("example.package", "1.0.0")
        self.application_ref = ApplicationRef("example.application", "1.0.0")
        self.task_a = BenchmarkTaskManifest(
            task_id="example.task-a",
            capability=CapabilityRef("example.capability-a", "1.0.0"),
            binding_id="example.binding-a",
            metric_contract_id="example.metric",
            result_contract_id="example.result",
            note="Synthetic task A.",
        )
        self.task_b = BenchmarkTaskManifest(
            task_id="example.task-b",
            capability=CapabilityRef("example.capability-b", "1.0.0"),
            binding_id="example.binding-b",
            metric_contract_id="example.metric",
            result_contract_id="example.result",
            note="Synthetic task B.",
        )
        self.suite = BenchmarkSuiteManifest(
            suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
            owner_package=self.owner,
            tasks=(self.task_a, self.task_b),
            artifact_media_types=("application/vnd.example.result+json",),
            default_case_limit=8,
            default_concurrency=1,
        )
        self.capability_a = ResolvedCapability(
            ref=self.task_a.capability,
            source=_PRIVATE_CAPABILITY_ROOT,
            manifest={
                "capability_id": self.task_a.capability.capability_id,
                "version": self.task_a.capability.version,
            },
        )
        self.capability_b = ResolvedCapability(
            ref=self.task_b.capability,
            source=_PRIVATE_CAPABILITY_ROOT.with_name("example-b.json"),
            manifest={
                "capability_id": self.task_b.capability.capability_id,
                "version": self.task_b.capability.version,
            },
        )
        self.planned_a = PlannedBenchmarkTask(1, self.task_a, self.capability_a)
        self.planned_b = PlannedBenchmarkTask(2, self.task_b, self.capability_b)
        self.lock_a = self._lock("example.package", "source-a", "a")
        self.lock_b = self._lock("example.support", "source-b", "b")

    def _lock(
        self, package_id: str, source_id: str, digest_character: str
    ) -> CapabilitySourceLock:
        return CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    package_ref=CapabilityPackageRef(package_id, "1.0.0"),
                    payload_sha256=digest_character * 64,
                    source_id=source_id,
                ),
            )
        )

    def _plan(
        self,
        *,
        tasks: object | None = None,
        package_locks: object | None = None,
    ) -> BenchmarkPlan:
        return BenchmarkPlan(
            run_id="run-001",
            application_ref=self.application_ref,
            suite=self.suite,
            tasks=[self.planned_a, self.planned_b] if tasks is None else tasks,
            case_limit=4,
            package_locks=[self.lock_a, self.lock_b]
            if package_locks is None
            else package_locks,
        )

    def test_constructor_sequences_are_snapshotted_and_canonically_ordered(
        self,
    ) -> None:
        public_arguments = ["synthetic", "--bounded-mode"]
        invocation = BenchmarkTaskInvocation(
            task_id=self.task_a.task_id,
            binding_id=self.task_a.binding_id,
            public_arguments=public_arguments,
            private_payload={"credential": _SECRET},
        )
        tasks = [self.planned_b, self.planned_a]
        locks = [self.lock_b, self.lock_a]

        plan = self._plan(tasks=tasks, package_locks=locks)
        public_arguments.append("mutated")
        tasks.clear()
        locks.clear()

        self.assertEqual(
            invocation.public_arguments, ("synthetic", "--bounded-mode")
        )
        self.assertEqual(
            tuple(task.ordinal for task in plan.tasks),
            (1, 2),
        )
        self.assertEqual(
            tuple(
                lock.entries[0].package_ref.package_id
                for lock in plan.package_locks
            ),
            ("example.package", "example.support"),
        )

    def test_runtime_values_are_frozen(self) -> None:
        request = BenchmarkTaskRequest(
            run_id="run-001",
            suite_ref=self.suite.suite_ref,
            task_id=self.task_a.task_id,
            case_limit=4,
            output_directory=_PRIVATE_OUTPUT,
        )
        invocation = BenchmarkTaskInvocation(
            task_id=self.task_a.task_id,
            binding_id=self.task_a.binding_id,
            public_arguments=("synthetic",),
            private_payload={"credential": _SECRET},
        )
        plan = self._plan()
        binding = BenchmarkTaskBinding(
            owner_package=self.owner,
            binding_id=self.task_a.binding_id,
            implementation=_TaskImplementation(),
        )
        resolved_task = ResolvedBenchmarkTask(self.planned_a, binding)
        resolved_plan = ResolvedBenchmarkPlan(
            plan,
            [
                resolved_task,
                ResolvedBenchmarkTask(
                    self.planned_b,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id=self.task_b.binding_id,
                        implementation=_TaskImplementation(),
                    ),
                ),
            ],
        )

        for value, field, replacement in (
            (request, "case_limit", 5),
            (invocation, "task_id", "example.changed"),
            (self.planned_a, "ordinal", 2),
            (plan, "run_id", "changed"),
            (resolved_task, "planned", self.planned_b),
            (resolved_plan, "plan", plan),
        ):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, field, replacement)

    def test_plan_rejects_noncontiguous_ordinals_and_duplicate_task_ids(
        self,
    ) -> None:
        cases = {
            "noncontiguous ordinals": (
                self.planned_a,
                PlannedBenchmarkTask(3, self.task_b, self.capability_b),
            ),
            "duplicate task ids": (
                self.planned_a,
                PlannedBenchmarkTask(2, self.task_a, self.capability_a),
            ),
        }

        for name, tasks in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, "benchmark plan tasks are invalid"
                ):
                    self._plan(tasks=tasks)

    def test_resolved_plan_requires_exact_complete_implementation_bindings(
        self,
    ) -> None:
        valid_binding_a = BenchmarkTaskBinding(
            owner_package=self.owner,
            binding_id=self.task_a.binding_id,
            implementation=_TaskImplementation(),
        )
        valid_binding_b = BenchmarkTaskBinding(
            owner_package=self.owner,
            binding_id=self.task_b.binding_id,
            implementation=_TaskImplementation(),
        )
        cases = {
            "missing task": (
                ResolvedBenchmarkTask(self.planned_a, valid_binding_a),
            ),
            "wrong binding id": (
                ResolvedBenchmarkTask(
                    self.planned_a,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id="example.wrong",
                        implementation=_TaskImplementation(),
                    ),
                ),
                ResolvedBenchmarkTask(self.planned_b, valid_binding_b),
            ),
            "wrong owner": (
                ResolvedBenchmarkTask(
                    self.planned_a,
                    BenchmarkTaskBinding(
                        owner_package=CapabilityPackageRef(
                            "example.other", "1.0.0"
                        ),
                        binding_id=self.task_a.binding_id,
                        implementation=_TaskImplementation(),
                    ),
                ),
                ResolvedBenchmarkTask(self.planned_b, valid_binding_b),
            ),
            "invalid implementation": (
                ResolvedBenchmarkTask(
                    self.planned_a,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id=self.task_a.binding_id,
                        implementation=object(),
                    ),
                ),
                ResolvedBenchmarkTask(self.planned_b, valid_binding_b),
            ),
            "non-callable implementation": (
                ResolvedBenchmarkTask(
                    self.planned_a,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id=self.task_a.binding_id,
                        implementation=_NonCallableImplementation(),
                    ),
                ),
                ResolvedBenchmarkTask(self.planned_b, valid_binding_b),
            ),
        }

        for name, tasks in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, "resolved benchmark plan is invalid"
                ):
                    ResolvedBenchmarkPlan(self._plan(), tasks)

        resolved = ResolvedBenchmarkPlan(
            self._plan(),
            [
                ResolvedBenchmarkTask(self.planned_b, valid_binding_b),
                ResolvedBenchmarkTask(self.planned_a, valid_binding_a),
            ],
        )
        self.assertEqual(
            tuple(task.planned.ordinal for task in resolved.tasks), (1, 2)
        )
        self.assertIsInstance(
            resolved.tasks[0].binding.implementation,
            BenchmarkTaskImplementation,
        )

    def test_private_values_and_paths_are_absent_from_repr_and_public_plan(
        self,
    ) -> None:
        request = BenchmarkTaskRequest(
            run_id="run-001",
            suite_ref=self.suite.suite_ref,
            task_id=self.task_a.task_id,
            case_limit=4,
            output_directory=_PRIVATE_OUTPUT,
        )
        invocation = BenchmarkTaskInvocation(
            task_id=self.task_a.task_id,
            binding_id=self.task_a.binding_id,
            public_arguments=("synthetic",),
            private_payload={"credential": _SECRET},
        )
        plan = self._plan()
        resolved = ResolvedBenchmarkPlan(
            plan,
            (
                ResolvedBenchmarkTask(
                    self.planned_a,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id=self.task_a.binding_id,
                        implementation=_TaskImplementation(),
                    ),
                ),
                ResolvedBenchmarkTask(
                    self.planned_b,
                    BenchmarkTaskBinding(
                        owner_package=self.owner,
                        binding_id=self.task_b.binding_id,
                        implementation=_TaskImplementation(),
                    ),
                ),
            ),
        )

        representation = "\n".join(
            (repr(request), repr(invocation), repr(plan), repr(resolved))
        )
        serialized = json.dumps(public_plan_dict(plan), sort_keys=True)
        for private_value in (
            _SECRET,
            str(_PRIVATE_OUTPUT),
            str(_PRIVATE_CAPABILITY_ROOT),
            "private_payload",
            "output_directory",
        ):
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value, representation)
                self.assertNotIn(private_value, serialized)

        self.assertEqual(
            public_plan_dict(plan),
            {
                "run_id": "run-001",
                "application": "example.application@1.0.0",
                "suite": "example.suite@1.0.0",
                "case_limit": 4,
                "tasks": [
                    {
                        "ordinal": 1,
                        "task_id": "example.task-a",
                        "capability": "example.capability-a@1.0.0",
                        "binding_id": "example.binding-a",
                    },
                    {
                        "ordinal": 2,
                        "task_id": "example.task-b",
                        "capability": "example.capability-b@1.0.0",
                        "binding_id": "example.binding-b",
                    },
                ],
            },
        )

    def test_public_arguments_reject_paths_and_operator_values(self) -> None:
        for argument in (
            "/operator/private/input",
            "../operator-input",
            "credential=secret",
            _SECRET,
        ):
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(
                    ValueError, "benchmark public arguments are invalid"
                ):
                    BenchmarkTaskInvocation(
                        task_id=self.task_a.task_id,
                        binding_id=self.task_a.binding_id,
                        public_arguments=(argument,),
                        private_payload=None,
                    )


if __name__ == "__main__":
    unittest.main()
