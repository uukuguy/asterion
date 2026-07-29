from __future__ import annotations

import unittest
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from asterion.benchmarks.model import (
    BenchmarkTaskImplementation,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
)
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkBindingError,
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)
from asterion.capability_packages.model import BenchmarkTaskBinding
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
)


RESOURCE_ROOT = Path("/operator/dci-resources")
OUTPUT_ROOT = Path("/operator/private-output")
SENTINEL_SECRET = "sentinel-private-value"
EXPECTED_CONTRACTS = {
    "bcplus.level3": (
        "bcplus.level3",
        "github-level3",
        "data/bcplus_qa.jsonl",
        "corpus/bc_plus_docs",
    ),
    "bcplus.main": (
        "bcplus.openai",
        "main",
        "data/bcplus_qa.jsonl",
        "corpus/bc_plus_docs",
    ),
    "beir.arguana": (
        "beir.arguana",
        "paper-main",
        "data/dci-bench/data/beir_arguana/test.jsonl",
        "corpus/beir/arguana",
    ),
    "beir.scifact": (
        "beir.scifact",
        "paper-main",
        "data/dci-bench/data/beir_scifact/test.jsonl",
        "corpus/beir/scifact",
    ),
    "bright.biology": (
        "bright.biology",
        "main",
        "data/dci-bench/data/bright_biology/bright_biology.jsonl",
        "corpus/bright_corpus/biology",
    ),
    "bright.earth-science": (
        "bright.earth-science",
        "main",
        "data/dci-bench/data/bright_earth_science/bright_earth_science.jsonl",
        "corpus/bright_corpus/earth_science",
    ),
    "bright.economics": (
        "bright.economics",
        "main",
        "data/dci-bench/data/bright_economics/economics_full.jsonl",
        "corpus/bright_corpus/economics",
    ),
    "bright.robotics": (
        "bright.robotics",
        "main",
        "data/dci-bench/data/bright_robotics/bright_robotics.jsonl",
        "corpus/bright_corpus/robotics",
    ),
    "qa.2wikimultihopqa": (
        "qa.2wikimultihopqa",
        "main",
        "data/dci-bench/data/2wikimultihopqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.bamboogle.github-sample50": (
        "qa.bamboogle",
        "github-sample50",
        "data/dci-bench/data/bamboogle/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.bamboogle.paper-full125": (
        "qa.bamboogle",
        "paper-full125",
        "paper-full/data/bamboogle/test-125.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.hotpotqa": (
        "qa.hotpotqa",
        "main",
        "data/dci-bench/data/hotpotqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.musique": (
        "qa.musique",
        "main",
        "data/dci-bench/data/musique/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.nq": (
        "qa.nq",
        "main",
        "data/dci-bench/data/nq/test.jsonl",
        "corpus/wiki_corpus",
    ),
    "qa.triviaqa": (
        "qa.triviaqa",
        "main",
        "data/dci-bench/data/triviaqa/test.jsonl",
        "corpus/wiki_corpus",
    ),
}


class _DciPayload(Protocol):
    profile_id: str
    selection_variant: str
    dataset: Path
    corpus: Path
    output_directory: Path
    private_environment: Mapping[str, str]
    amount: Decimal | None
    case_limit: int


def _request(task_id: str, *, case_limit: int = 3) -> BenchmarkTaskRequest:
    return BenchmarkTaskRequest(
        run_id="dci-binding-test",
        suite_ref=BenchmarkSuiteRef("dci.all", "1.0.0"),
        task_id=task_id,
        case_limit=case_limit,
        output_directory=OUTPUT_ROOT / task_id,
    )


def _invoke(
    binding: BenchmarkTaskBinding,
    request: BenchmarkTaskRequest,
) -> tuple[BenchmarkTaskInvocation, _DciPayload]:
    implementation = cast(
        BenchmarkTaskImplementation,
        binding.implementation,
    )
    invocation = implementation.build_invocation(request)
    return invocation, cast(_DciPayload, invocation.private_payload)


class DciBenchmarkBindingTests(unittest.TestCase):
    def test_exact_binding_table_preserves_launcher_semantics(self) -> None:
        inputs = DciBenchmarkOperatorInputs.from_resource_root(
            RESOURCE_ROOT,
            private_environment={"ASTERION_SENTINEL": SENTINEL_SECRET},
        )
        bindings = create_benchmark_bindings(operator_inputs=inputs)

        self.assertEqual(
            tuple(binding.binding_id for binding in bindings),
            tuple(sorted(EXPECTED_CONTRACTS)),
        )
        self.assertEqual(len(bindings), 15)
        self.assertEqual(len({binding.binding_id for binding in bindings}), 15)
        self.assertTrue(
            all(
                binding.owner_package == CapabilityPackageRef("dci", "1.0.0")
                for binding in bindings
            )
        )

        for binding in bindings:
            with self.subTest(task_id=binding.binding_id):
                invocation, payload = _invoke(
                    binding,
                    _request(binding.binding_id),
                )
                profile, variant, dataset, corpus = EXPECTED_CONTRACTS[
                    binding.binding_id
                ]
                self.assertEqual(invocation.task_id, binding.binding_id)
                self.assertEqual(invocation.binding_id, binding.binding_id)
                self.assertEqual(payload.profile_id, profile)
                self.assertEqual(payload.selection_variant, variant)
                self.assertEqual(payload.dataset, RESOURCE_ROOT / dataset)
                self.assertEqual(payload.corpus, RESOURCE_ROOT / corpus)
                self.assertEqual(payload.case_limit, 3)
                self.assertEqual(
                    payload.output_directory,
                    OUTPUT_ROOT / binding.binding_id,
                )

    def test_bamboogle_variants_remain_distinct(self) -> None:
        bindings = {
            binding.binding_id: binding
            for binding in create_benchmark_bindings(
                operator_inputs=DciBenchmarkOperatorInputs.from_resource_root(
                    RESOURCE_ROOT,
                    private_environment={},
                )
            )
        }

        _, github = _invoke(
            bindings["qa.bamboogle.github-sample50"],
            _request("qa.bamboogle.github-sample50", case_limit=50),
        )
        _, paper = _invoke(
            bindings["qa.bamboogle.paper-full125"],
            _request("qa.bamboogle.paper-full125", case_limit=125),
        )

        self.assertEqual(github.selection_variant, "github-sample50")
        self.assertEqual(paper.selection_variant, "paper-full125")
        self.assertNotEqual(github.dataset, paper.dataset)
        self.assertEqual(github.case_limit, 50)
        self.assertEqual(paper.case_limit, 125)

    def test_public_values_hide_all_operator_inputs(self) -> None:
        inputs = DciBenchmarkOperatorInputs.from_resource_root(
            RESOURCE_ROOT,
            private_environment={
                "ASTERION_SENTINEL": SENTINEL_SECRET,
                "OPENAI_API_KEY": "sk-private-credential",
            },
            amount=Decimal("1.25"),
        )
        binding = create_benchmark_bindings(operator_inputs=inputs)[0]
        invocation, payload = _invoke(
            binding,
            _request(binding.binding_id),
        )
        rendered = " ".join(
            (
                repr(inputs),
                repr(binding),
                repr(binding.implementation),
                repr(invocation),
                repr(invocation.public_arguments),
            )
        )

        for private in (
            str(RESOURCE_ROOT),
            str(OUTPUT_ROOT),
            SENTINEL_SECRET,
            "sk-private-credential",
            "OPENAI_API_KEY",
            "1.25",
        ):
            self.assertNotIn(private, rendered)
        self.assertEqual(payload.amount, Decimal("1.25"))
        self.assertEqual(
            payload.private_environment["ASTERION_SENTINEL"],
            SENTINEL_SECRET,
        )

    def test_missing_operator_input_fails_before_execution(self) -> None:
        binding = create_benchmark_bindings()[0]

        with self.assertRaisesRegex(
            DciBenchmarkBindingError,
            "^DCI benchmark operator input is unavailable$",
        ):
            _invoke(binding, _request(binding.binding_id))

        complete = DciBenchmarkOperatorInputs.from_resource_root(
            RESOURCE_ROOT,
            private_environment={},
        )
        missing_dataset = DciBenchmarkOperatorInputs(
            dataset_roots={
                key: value
                for key, value in complete.dataset_roots.items()
                if key != binding.binding_id
            },
            corpus_roots=complete.corpus_roots,
            private_environment={},
        )
        incomplete_binding = create_benchmark_bindings(
            operator_inputs=missing_dataset
        )[0]
        with self.assertRaisesRegex(
            DciBenchmarkBindingError,
            "^DCI benchmark operator input is unavailable$",
        ):
            _invoke(
                incomplete_binding,
                _request(incomplete_binding.binding_id),
            )

    def test_amount_none_is_preserved_and_case_limit_is_generic(self) -> None:
        inputs = DciBenchmarkOperatorInputs.from_resource_root(
            RESOURCE_ROOT,
            private_environment={},
            amount=None,
        )
        binding = create_benchmark_bindings(operator_inputs=inputs)[0]
        invocation, payload = _invoke(
            binding,
            _request(binding.binding_id, case_limit=7),
        )

        self.assertIsNone(payload.amount)
        self.assertEqual(payload.case_limit, 7)
        self.assertNotIn("none", invocation.public_arguments)
        self.assertNotIn("amount", invocation.public_arguments)


if __name__ == "__main__":
    unittest.main()
