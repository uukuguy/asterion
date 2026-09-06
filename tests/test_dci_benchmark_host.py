from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from asterion.applications.dci_agent_lite.benchmark_host import (
    DciBenchmarkHost,
    DciBenchmarkHostError,
    DciLoadedBenchmarkProviders,
    coverage_execution_config_sha256,
    optimization_execution_config_sha256,
)
from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.applications.dci_agent_lite.operator_config import load_operator_config
from asterion.benchmarks import (
    BenchmarkTaskExecutor,
    BenchmarkTaskImplementation,
    BenchmarkTaskRequest,
)
from asterion.capability_packages import (
    BenchmarkTaskBinding,
    CapabilityPackageCandidate,
)
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capabilities.dci.implementation.research.query_planning import (
    BASELINE_QUERY_PLAN,
    DECOMPOSED_QUERY_PLAN,
    materialize_query_planning_prompt,
    resolve_query_planning_contract,
)


class RecordingBuiltinSource:
    def __init__(self) -> None:
        self.delegate = BuiltinCapabilitySource()
        self.provider_loads = 0

    def discover_metadata(self):
        return self.delegate.discover_metadata()

    def open_payload(self, candidate):
        return self.delegate.open_payload(candidate)

    def validate_source_identity(self, candidate, payload):
        return self.delegate.validate_source_identity(candidate, payload)

    def load_provider(self, candidate):
        self.provider_loads += 1
        return self.delegate.load_provider(candidate)


class AlternateBuiltinSource:
    def __init__(self) -> None:
        self.delegate = BuiltinCapabilitySource()
        self.provider_loads = 0

    def discover_metadata(self):
        candidate = next(
            candidate
            for candidate in self.delegate.discover_metadata()
            if candidate.package_ref.package_id == "dci"
        )
        return (
            CapabilityPackageCandidate(
                package_ref=candidate.package_ref,
                source_id="dci.alternate-builtin",
                source_kind=candidate.source_kind,
                payload_sha256=candidate.payload_sha256,
                metadata=candidate.metadata,
            ),
        )

    def open_payload(self, candidate):
        original = next(
            candidate
            for candidate in self.delegate.discover_metadata()
            if candidate.package_ref.package_id == "dci"
        )
        return self.delegate.open_payload(original)

    def validate_source_identity(self, candidate, payload):
        if (
            candidate.source_id != "dci.alternate-builtin"
            or candidate.source_kind != "builtin"
            or payload.manifest.package_ref != candidate.package_ref
        ):
            raise ValueError("alternate source is invalid")

    def load_provider(self, candidate):
        self.provider_loads += 1
        raise AssertionError("alternate provider must not load")


def _resolved(host, instance, lock_path: Path):
    metadata = host.discover_metadata(
        application_ref=instance.application_ref,
        suite_ref=instance.suite_ref,
    )
    source_lock = host.resolve_source_lock(lock_path)
    payloads = host.open_selected_payloads(metadata, source_lock)
    resolved = host.resolve_application(
        payloads,
        application_ref=instance.application_ref,
        suite_ref=instance.suite_ref,
    )
    return payloads, resolved


class DciBenchmarkHostTests(unittest.TestCase):
    def test_coverage_config_digest_binds_dci_implementation_identity(self) -> None:
        environment = {"DEEPSEEK_API_KEY": "SENTINEL-PRIVATE-KEY"}
        with patch(
            "asterion.applications.dci_agent_lite.benchmark_executor."
            "dci_complete_implementation_identity",
            side_effect=["a" * 64, "b" * 64],
            create=True,
        ):
            first = coverage_execution_config_sha256(environment)
            second = coverage_execution_config_sha256(environment)

        self.assertNotEqual(first, second)
        self.assertNotIn("SENTINEL-PRIVATE-KEY", first)
        self.assertNotIn("SENTINEL-PRIVATE-KEY", second)

    def test_candidate_query_plan_is_rejected_for_non_bright_host(self) -> None:
        instance = select_benchmark_instance("dci.qa.bamboogle@1.0.0")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o700)
            prompt = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, root)
            with self.assertRaises(DciBenchmarkHostError):
                DciBenchmarkHost(
                    instance=instance,
                    operator_config=None,
                    query_planning_contract=resolve_query_planning_contract(
                        DECOMPOSED_QUERY_PLAN
                    ),
                    query_planning_prompt_file=prompt,
                )

    def test_candidate_query_plan_rejects_an_unbound_executor_factory(self) -> None:
        instance = select_benchmark_instance("dci.bright.biology@1.0.0")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o700)
            prompt = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, root)
            with self.assertRaises(DciBenchmarkHostError):
                DciBenchmarkHost(
                    instance=instance,
                    operator_config=None,
                    query_planning_contract=resolve_query_planning_contract(
                        DECOMPOSED_QUERY_PLAN
                    ),
                    query_planning_prompt_file=prompt,
                    executor_factory=lambda _instance: cast(
                        BenchmarkTaskExecutor, object()
                    ),
                )

    def test_optimization_config_digest_changes_only_with_query_plan_contract(
        self,
    ) -> None:
        environment = {"DEEPSEEK_API_KEY": "SENTINEL-PRIVATE-KEY"}
        baseline = optimization_execution_config_sha256(
            environment,
            resolve_query_planning_contract(BASELINE_QUERY_PLAN),
        )
        candidate = optimization_execution_config_sha256(
            environment,
            resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN),
        )

        self.assertNotEqual(baseline, candidate)
        self.assertNotIn("SENTINEL-PRIVATE-KEY", baseline)
        self.assertNotIn("SENTINEL-PRIVATE-KEY", candidate)

    def test_local_host_plans_authorizes_and_rehydrates_private_bindings(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        source = RecordingBuiltinSource()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            lock_path = root / "lock.json"
            write_benchmark_source_lock(
                resolve_benchmark_source_lock(
                    instance,
                    package_sources=(source,),
                ),
                lock_path,
            )
            host = DciBenchmarkHost(
                instance=instance,
                operator_config=None,
                package_sources=(source,),
            )
            payloads, resolved = _resolved(host, instance, lock_path)
            draft = host.create_plan(
                resolved,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                execute=False,
                authorization=None,
                resume_run_id=None,
            )
            authorization = host.authorize_execution(
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                evidence_root=root / "evidence",
                resume_run_id=None,
            )
            plan = host.create_plan(
                resolved,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                execute=True,
                authorization=authorization,
                resume_run_id=None,
            )
            providers = cast(
                DciLoadedBenchmarkProviders,
                host.load_selected_providers(payloads, authorization),
            )

            self.assertEqual(plan.tasks, draft.tasks)
            self.assertIsInstance(providers, DciLoadedBenchmarkProviders)
            self.assertEqual(source.provider_loads, 1)
            self.assertEqual(len(providers.packages[0].benchmark_bindings), 15)
            binding = cast(
                BenchmarkTaskBinding, providers.packages[0].benchmark_bindings[0]
            )
            implementation = cast(BenchmarkTaskImplementation, binding.implementation)
            invocation = implementation.build_invocation(
                BenchmarkTaskRequest(
                    run_id=plan.run_id,
                    suite_ref=instance.suite_ref,
                    task_id=binding.binding_id,
                    case_limit=1,
                    output_directory=root / "output",
                )
            )
            self.assertNotIn(str(root), repr(invocation))

    def test_real_host_requires_private_config_before_provider_loading(self) -> None:
        instance = select_benchmark_instance("dci.qa.bamboogle@1.0.0")
        source = RecordingBuiltinSource()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            lock_path = root / "lock.json"
            write_benchmark_source_lock(
                resolve_benchmark_source_lock(
                    instance,
                    package_sources=(source,),
                ),
                lock_path,
            )
            host = DciBenchmarkHost(
                instance=instance,
                operator_config=None,
                package_sources=(source,),
            )
            payloads, resolved = _resolved(host, instance, lock_path)
            host.create_plan(
                resolved,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                execute=False,
                authorization=None,
                resume_run_id=None,
            )
            authorization = host.authorize_execution(
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                evidence_root=root / "evidence",
                resume_run_id=None,
            )
            host.create_plan(
                resolved,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                execute=True,
                authorization=authorization,
                resume_run_id=None,
            )
            with self.assertRaises(DciBenchmarkHostError):
                host.load_selected_providers(payloads, authorization)

        self.assertEqual(source.provider_loads, 0)

    def test_rejects_selection_not_bound_to_draft_before_provider_load(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        source_a = RecordingBuiltinSource()
        source_b = AlternateBuiltinSource()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            lock_a_path = root / "lock-a.json"
            lock_b_path = root / "lock-b.json"
            write_benchmark_source_lock(
                resolve_benchmark_source_lock(instance, package_sources=(source_a,)),
                lock_a_path,
            )
            write_benchmark_source_lock(
                resolve_benchmark_source_lock(instance, package_sources=(source_b,)),
                lock_b_path,
            )
            host = DciBenchmarkHost(
                instance=instance,
                operator_config=None,
                package_sources=(source_a, source_b),
            )
            _, resolved_a = _resolved(host, instance, lock_a_path)
            host.create_plan(
                resolved_a,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                execute=False,
                authorization=None,
                resume_run_id=None,
            )
            authorization = host.authorize_execution(
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
                evidence_root=root / "evidence",
                resume_run_id=None,
            )
            metadata = host.discover_metadata(
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
            )
            payloads_b = host.open_selected_payloads(
                metadata,
                host.resolve_source_lock(lock_b_path),
            )
            with self.assertRaises(DciBenchmarkHostError) as raised:
                host.load_selected_providers(payloads_b, authorization)

        self.assertEqual(str(raised.exception), "DCI benchmark host is invalid")
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(source_a.provider_loads, 0)
        self.assertEqual(source_b.provider_loads, 0)
        self.assertNotIn("delegate", repr(payloads_b.resolution._prepared_packages[0]))

    def test_real_host_selects_runnable_asterion_safe_agent_and_judge(self) -> None:
        instance = select_benchmark_instance("dci.qa.bamboogle@1.0.0")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = load_operator_config(
                root,
                environment={"DEEPSEEK_API_KEY": "PRIVATE-JUDGE-KEY"},
                max_native_attempts=1,
            )
            sentinel = object()
            with patch(
                "asterion.applications.dci_agent_lite.benchmark_host.RealDciBenchmarkExecutor",
                return_value=sentinel,
            ) as executor:
                selected = DciBenchmarkHost(
                    instance=instance,
                    operator_config=config,
                )._default_executor()

        self.assertIs(selected, sentinel)
        arguments = executor.call_args.kwargs
        self.assertEqual(arguments["experiment_profile"], "asterion-safe/pi")
        self.assertEqual(arguments["max_turns"], 100)
        self.assertEqual(arguments["max_native_attempts"], 1)
        self.assertEqual(arguments["runtime_options"].runtime, "pi")
        self.assertEqual(arguments["runtime_options"].provider, "openai-codex")
        self.assertEqual(arguments["runtime_options"].model, "gpt-5.6-luna")
        self.assertEqual(arguments["runtime_options"].tools, "read,bash")
        self.assertEqual(arguments["judge_config"].api_key, "PRIVATE-JUDGE-KEY")


if __name__ == "__main__":
    unittest.main()
