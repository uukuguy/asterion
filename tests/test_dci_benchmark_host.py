from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.dci_agent_lite.benchmark_host import (
    DciBenchmarkHost,
    DciBenchmarkHostError,
    DciLoadedBenchmarkProviders,
)
from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.applications.dci_agent_lite.operator_config import load_operator_config
from asterion.benchmarks import BenchmarkTaskRequest
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource


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
            providers = host.load_selected_providers(payloads, authorization)

            self.assertEqual(plan.tasks, draft.tasks)
            self.assertIsInstance(providers, DciLoadedBenchmarkProviders)
            self.assertEqual(source.provider_loads, 1)
            self.assertEqual(len(providers.packages[0].benchmark_bindings), 15)
            binding = providers.packages[0].benchmark_bindings[0]
            invocation = binding.implementation.build_invocation(
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
        instance = select_benchmark_instance(
            "dci.qa.bamboogle@1.0.0"
        )
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

    def test_real_host_selects_runnable_asterion_safe_agent_and_judge(self) -> None:
        instance = select_benchmark_instance(
            "dci.qa.bamboogle@1.0.0"
        )
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
