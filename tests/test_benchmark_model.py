from __future__ import annotations

import unittest
from collections.abc import Mapping
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

    def test_task_invocation_accepts_only_explicit_symbolic_public_arguments(
        self,
    ) -> None:
        accepted = (
            "case-limit",
            "limit_3",
            "model.v1",
            "top5@stable",
            "n0",
            "monkey",
            "keynote",
        )
        invocation = BenchmarkTaskInvocation(
            task_id="example.task",
            binding_id="example.binding",
            public_arguments=accepted,
            private_payload=None,
        )
        self.assertEqual(invocation.public_arguments, accepted)

        rejected = (
            "",
            "two words",
            "/absolute/path",
            "relative/path",
            r"relative\path",
            ".",
            "..",
            "../case",
            "https://example.test",
            "provider=model",
            "config=prod",
            "SECRET-value",
            "sk-live-secret",
        )
        for argument in rejected:
            with self.subTest(argument=argument):
                with self.assertRaises(BenchmarkModelError):
                    BenchmarkTaskInvocation(
                        task_id="example.task",
                        binding_id="example.binding",
                        public_arguments=(argument,),
                        private_payload={"secret": "SECRET-PAYLOAD"},
                    )

    def test_task_invocation_rejects_reserved_public_argument_tokens_without_echo(
        self,
    ) -> None:
        rejected = (
            "password",
            "token",
            "api-key",
            "apikey",
            "config.prod",
            "provider.model",
            "env.prod",
            "credential",
            "auth",
            "authorization",
        )
        for argument in rejected:
            with self.subTest(argument=argument):
                with self.assertRaises(BenchmarkModelError) as context:
                    BenchmarkTaskInvocation(
                        task_id="example.task",
                        binding_id="example.binding",
                        public_arguments=(argument,),
                        private_payload=None,
                    )
                self.assertNotIn(argument, repr(context.exception))

    def test_task_implementation_protocol_is_runtime_checkable(self) -> None:
        self.assertIsInstance(ExampleBenchmarkImplementation(), BenchmarkTaskImplementation)

    def test_resolved_task_requires_implementation_protocol_without_calling_it(
        self,
    ) -> None:
        task = self._resolved_task(
            1,
            "example.task",
            implementation=ExplodingBenchmarkImplementation(),
        )

        self.assertIsInstance(task.binding.implementation, ExplodingBenchmarkImplementation)

        with self.assertRaises(BenchmarkModelError) as context:
            self._resolved_task(
                1,
                "example.task",
                implementation=NonBenchmarkImplementation(),
            )
        self.assertNotIn("SECRET-NON-IMPLEMENTATION", repr(context.exception))

    def test_resolved_capability_freezes_manifest_and_requires_matching_identity(
        self,
    ) -> None:
        manifest: dict[str, object] = {
            "capability_id": "example.capability",
            "version": "1.0.0",
            "nested": {
                "items": [{"name": "alpha"}],
                "tags": {"stable", "public"},
            },
        }
        capability = ResolvedCapability(
            ref=CapabilityRef("example.capability", "1.0.0"),
            manifest=manifest,
        )
        manifest["capability_id"] = "example.changed"
        nested = manifest["nested"]
        assert isinstance(nested, dict)
        items = nested["items"]
        assert isinstance(items, list)
        items.append({"name": "mutated"})

        self.assertEqual(capability.manifest["capability_id"], "example.capability")
        frozen_nested = capability.manifest["nested"]
        self.assertIsInstance(frozen_nested, object)
        self.assertEqual(
            frozen_nested,
            {
                "items": ({"name": "alpha"},),
                "tags": frozenset({"public", "stable"}),
            },
        )
        with self.assertRaises(TypeError):
            capability.manifest["capability_id"] = "example.changed"  # type: ignore[index]
        self.assertIsInstance(frozen_nested, Mapping)
        frozen_nested_mapping = cast(Mapping[str, object], frozen_nested)
        frozen_items = frozen_nested_mapping["items"]
        self.assertIsInstance(frozen_items, tuple)
        with self.assertRaises(TypeError):
            cast(dict[str, object], frozen_nested)["items"] = ()
        with self.assertRaises(TypeError):
            cast(dict[str, object], cast(tuple[object, ...], frozen_items)[0])[
                "name"
            ] = "changed"

        with self.assertRaises(BenchmarkModelError) as context:
            ResolvedCapability(
                ref=CapabilityRef("example.capability", "1.0.0"),
                manifest={
                    "capability_id": "other.capability",
                    "version": "1.0.0",
                    "secret": "SECRET-MANIFEST",
                },
            )
        self.assertNotIn("SECRET-MANIFEST", repr(context.exception))

    def test_resolved_capability_rejects_non_json_like_manifest_values_redacted(
        self,
    ) -> None:
        cases: tuple[tuple[str, object, tuple[str, ...]], ...] = (
            ("bytes", b"SECRET-BYTES", ("SECRET-BYTES",)),
            ("bytearray", bytearray(b"SECRET-BYTEARRAY"), ("SECRET-BYTEARRAY",)),
            ("custom object", HostileManifestValue(), ("SECRET-HOSTILE",)),
            ("positive infinity", float("inf"), ("inf",)),
            ("negative infinity", float("-inf"), ("inf",)),
            ("nan", float("nan"), ("nan",)),
        )
        for label, value, sentinels in cases:
            with self.subTest(label):
                with self.assertRaises(BenchmarkModelError) as context:
                    ResolvedCapability(
                        ref=CapabilityRef("example.capability", "1.0.0"),
                        manifest={
                            "capability_id": "example.capability",
                            "version": "1.0.0",
                            "value": value,
                        },
                    )
                self.assertIsNone(context.exception.__cause__)
                self.assertIsNone(context.exception.__context__)
                rendered = repr(context.exception)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, rendered)

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

    def test_resolved_plan_requires_suite_task_order_and_owner_package_identity(
        self,
    ) -> None:
        first = self._task_manifest("example.first")
        second = self._task_manifest("example.second")
        suite = self._suite_from_tasks(first, second)

        cases = (
            (
                "manifest order",
                (
                    self._resolved_task_from_manifest(1, second),
                    self._resolved_task_from_manifest(2, first),
                ),
            ),
            (
                "owner package",
                (
                    self._resolved_task_from_manifest(
                        1,
                        first,
                        owner_package=CapabilityPackageRef("other.package", "1.0.0"),
                    ),
                    self._resolved_task_from_manifest(2, second),
                ),
            ),
        )
        for label, tasks in cases:
            with self.subTest(label):
                with self.assertRaises(BenchmarkModelError):
                    self._plan(suite=suite, tasks=tasks)

    def _plan(
        self,
        *,
        case_limit: int = 1,
        suite: BenchmarkSuiteManifest | None = None,
        tasks: tuple[ResolvedBenchmarkTask, ...] | None = None,
    ) -> ResolvedBenchmarkPlan:
        return ResolvedBenchmarkPlan(
            run_id="run-001",
            application_ref=ApplicationRef("example.application", "1.0.0"),
            suite=suite if suite is not None else self._suite("example.task"),
            tasks=tasks if tasks is not None else (self._resolved_task(1, "example.task"),),
            case_limit=case_limit,
            package_locks=(),
        )

    def _suite(self, *task_ids: str) -> BenchmarkSuiteManifest:
        return self._suite_from_tasks(
            *(self._task_manifest(task_id) for task_id in task_ids)
        )

    def _suite_from_tasks(
        self, *tasks: BenchmarkTaskManifest
    ) -> BenchmarkSuiteManifest:
        return BenchmarkSuiteManifest(
            suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
            owner_package=CapabilityPackageRef("example.package", "1.0.0"),
            tasks=tasks,
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

    def _resolved_task(
        self,
        ordinal: int,
        task_id: str,
        *,
        implementation: object | None = None,
    ) -> ResolvedBenchmarkTask:
        return self._resolved_task_from_manifest(
            ordinal,
            self._task_manifest(task_id),
            implementation=implementation,
        )

    def _resolved_task_from_manifest(
        self,
        ordinal: int,
        task: BenchmarkTaskManifest,
        *,
        owner_package: CapabilityPackageRef | None = None,
        implementation: object | None = None,
    ) -> ResolvedBenchmarkTask:
        return ResolvedBenchmarkTask(
            ordinal=ordinal,
            task=task,
            capability=ResolvedCapability(
                ref=CapabilityRef("example.capability", "1.0.0"),
                manifest={
                    "capability_id": "example.capability",
                    "version": "1.0.0",
                    "secret": "SECRET-PAYLOAD",
                },
            ),
            binding=BenchmarkTaskBinding(
                owner_package=owner_package
                if owner_package is not None
                else CapabilityPackageRef("example.package", "1.0.0"),
                binding_id="example.binding",
                implementation=implementation
                if implementation is not None
                else SecretImplementation(),
            ),
        )


class SecretImplementation:
    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id="example.binding",
            public_arguments=("case-limit", str(request.case_limit)),
            private_payload={"secret": "SECRET-PAYLOAD"},
        )

    def __repr__(self) -> str:
        return "IMPLEMENTATION-SECRET"


class ExplodingBenchmarkImplementation:
    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        raise AssertionError("implementation must not be called")


class NonBenchmarkImplementation:
    def __repr__(self) -> str:
        return "SECRET-NON-IMPLEMENTATION"


class HostileManifestValue:
    def __repr__(self) -> str:
        raise RuntimeError("SECRET-HOSTILE-REPR")

    def __str__(self) -> str:
        raise RuntimeError("SECRET-HOSTILE-STR")


if __name__ == "__main__":
    unittest.main()
