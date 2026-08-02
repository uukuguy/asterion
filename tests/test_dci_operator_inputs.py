from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from asterion.applications.dci_agent_lite.operator_config import load_operator_config
from asterion.benchmarks.model import BenchmarkTaskImplementation, BenchmarkTaskRequest
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputError,
    DciBenchmarkOperatorInputs,
)
from asterion.capability_packages.protocol import BenchmarkSuiteRef


_COVERAGE_TASK_IDS = (
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
)


class DciOperatorCoverageInputTests(unittest.TestCase):
    def test_explicit_coverage_root_binds_five_exact_private_registry_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            coverage_root = root / "PRIVATE_COVERAGE_SENTINEL"
            config = load_operator_config(
                root,
                environment={"ASTERION_DCI_COVERAGE_ROOT": str(coverage_root)},
            )

        registries = getattr(
            config.benchmark_inputs,
            "coverage_registry_roots",
            None,
        )
        self.assertEqual(
            registries,
            {
                task_id: coverage_root / task_id / "registry.json"
                for task_id in _COVERAGE_TASK_IDS
            },
        )
        rendered = repr(config) + json.dumps(config.public_summary(), sort_keys=True)
        self.assertNotIn(str(coverage_root), rendered)
        self.assertNotIn("ASTERION_DCI_COVERAGE_ROOT", rendered)

    def test_omitted_coverage_root_binds_no_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_operator_config(
                Path(directory).resolve(),
                environment={},
            )

        self.assertEqual(
            getattr(config.benchmark_inputs, "coverage_registry_roots", None),
            {},
        )

    def test_binding_passes_only_the_exact_task_registry_in_private_payload(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            coverage_root = root / "PRIVATE_COVERAGE_SENTINEL"
            inputs = load_operator_config(
                root,
                environment={"ASTERION_DCI_COVERAGE_ROOT": str(coverage_root)},
            ).benchmark_inputs
            bindings = {
                binding.binding_id: binding
                for binding in create_benchmark_bindings(operator_inputs=inputs)
            }

            for task_id in (*_COVERAGE_TASK_IDS, "qa.bamboogle.paper-full125"):
                with self.subTest(task_id=task_id):
                    implementation = cast(
                        BenchmarkTaskImplementation,
                        bindings[task_id].implementation,
                    )
                    invocation = implementation.build_invocation(
                        BenchmarkTaskRequest(
                            run_id="coverage-binding-test",
                            suite_ref=BenchmarkSuiteRef("dci.all", "1.0.0"),
                            task_id=task_id,
                            case_limit=1,
                            output_directory=root / "output" / task_id,
                        )
                    )
                    payload = invocation.private_payload
                    expected = (
                        coverage_root / task_id / "registry.json"
                        if task_id in _COVERAGE_TASK_IDS
                        else None
                    )
                    self.assertEqual(
                        getattr(payload, "coverage_registry", None),
                        expected,
                    )
                    self.assertNotIn(str(coverage_root), repr(payload))
                    self.assertNotIn(str(coverage_root), repr(invocation))

    def test_coverage_registry_mapping_rejects_non_exact_task_or_path(self) -> None:
        coverage_root = Path("/operator/private-coverage")
        invalid = (
            {"qa.hotpotqa": coverage_root / "qa.hotpotqa" / "registry.json"},
            {
                "bright.biology": coverage_root
                / "bright.robotics"
                / "registry.json"
            },
            {"bright.biology": coverage_root / "bright.biology" / "other.json"},
        )
        for coverage_registry_roots in invalid:
            with self.subTest(mapping=coverage_registry_roots), self.assertRaisesRegex(
                DciBenchmarkOperatorInputError,
                "^DCI benchmark operator input is invalid$",
            ):
                DciBenchmarkOperatorInputs(
                    dataset_roots={},
                    corpus_roots={},
                    private_environment={},
                    coverage_registry_roots=coverage_registry_roots,
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
