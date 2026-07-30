from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
            "dci.qa.bamboogle.github-sample50@1.0.0"
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


if __name__ == "__main__":
    unittest.main()
