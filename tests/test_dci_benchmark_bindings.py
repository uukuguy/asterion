"""DCI benchmark bindings are exact, private, and provider-free."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from asterion.benchmarks import BenchmarkTaskRequest
from asterion.capability_packages import BenchmarkSuiteRef
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkInvocation,
    create_benchmark_bindings,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)


_SENTINEL = "DCI-BENCHMARK-PRIVATE-SENTINEL"
_INPUTS = DciBenchmarkOperatorInputs(
    dataset_roots={
        "bcplus": Path("/operator/datasets/bcplus"),
        "beir": Path("/operator/datasets/beir"),
        "bright": Path("/operator/datasets/bright"),
        "qa": Path("/operator/datasets/qa"),
        "paper-full": Path("/operator/datasets/paper-full"),
    },
    corpus_roots={
        "bcplus": Path("/operator/corpora/bcplus"),
        "beir": Path("/operator/corpora/beir"),
        "bright": Path("/operator/corpora/bright"),
        "wiki": Path("/operator/corpora/wiki"),
    },
    private_environment={"DCI_API_KEY": _SENTINEL},
    amount=Decimal("12.50"),
)


class DciBenchmarkBindingTests(unittest.TestCase):
    def test_complete_binding_table_builds_exact_private_contracts(self) -> None:
        bindings = create_benchmark_bindings(_INPUTS)
        by_id = {binding.binding_id: binding for binding in bindings}
        expected = {
            "bcplus.level3": (
                "bcplus.level3", "browsecomp-plus.main.all830", "bcplus",
                "bcplus_qa.jsonl", "bcplus", "bc_plus_docs", 830,
            ),
            "bcplus.main": (
                "bcplus.openai", "browsecomp-plus.main.all830", "bcplus",
                "bcplus_qa.jsonl", "bcplus", "bc_plus_docs", 830,
            ),
            "beir.arguana": (
                "beir.arguana", "beir.arguana.main.random50", "beir",
                "arguana/test.jsonl", "beir", "arguana", 50,
            ),
            "beir.scifact": (
                "beir.scifact", "beir.scifact.main.random50", "beir",
                "scifact/test.jsonl", "beir", "scifact", 50,
            ),
            "bright.biology": (
                "bright.biology", "bright.biology.main.full", "bright",
                "biology/bright_biology.jsonl", "bright", "biology", 103,
            ),
            "bright.earth-science": (
                "bright.earth-science", "bright.earth-science.main.full", "bright",
                "earth_science/bright_earth_science.jsonl", "bright", "earth_science", 116,
            ),
            "bright.economics": (
                "bright.economics", "bright.economics.main.full", "bright",
                "economics/economics_full.jsonl", "bright", "economics", 103,
            ),
            "bright.robotics": (
                "bright.robotics", "bright.robotics.main.full", "bright",
                "robotics/bright_robotics.jsonl", "bright", "robotics", 101,
            ),
            "qa.2wikimultihopqa": (
                "qa.2wikimultihopqa", "qa.2wikimultihopqa.main.random50", "qa",
                "2wikimultihopqa/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
            "qa.bamboogle.github-sample50": (
                "qa.bamboogle", "qa.bamboogle.upstream.sample50", "qa",
                "bamboogle/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
            "qa.bamboogle.paper-full125": (
                "qa.bamboogle", "qa.bamboogle.main.full", "paper-full",
                "bamboogle/test-125.jsonl", "wiki", "wiki_corpus", 125,
            ),
            "qa.hotpotqa": (
                "qa.hotpotqa", "qa.hotpotqa.main.random50", "qa",
                "hotpotqa/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
            "qa.musique": (
                "qa.musique", "qa.musique.main.random50", "qa",
                "musique/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
            "qa.nq": (
                "qa.nq", "qa.nq.main.random50", "qa",
                "nq/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
            "qa.triviaqa": (
                "qa.triviaqa", "qa.triviaqa.main.random50", "qa",
                "triviaqa/test.jsonl", "wiki", "wiki_corpus", 50,
            ),
        }

        self.assertEqual(set(by_id), set(expected))
        self.assertEqual(len(bindings), 15)
        for task_id, (
            profile, scope_id, dataset_root, dataset_relative,
            corpus_root, corpus_relative, selection_limit,
        ) in expected.items():
            with self.subTest(task_id=task_id):
                request = BenchmarkTaskRequest(
                    run_id="dci-binding-test",
                    suite_ref=BenchmarkSuiteRef("dci.all", "1.0.0"),
                    task_id=task_id,
                    case_limit=min(50, selection_limit),
                    output_directory=Path("/operator/output") / task_id,
                )
                invocation = by_id[task_id].implementation.build_invocation(request)

                self.assertEqual(invocation.task_id, task_id)
                self.assertEqual(invocation.binding_id, task_id)
                self.assertIsInstance(invocation.private_payload, DciBenchmarkInvocation)
                payload = invocation.private_payload
                self.assertEqual(payload.profile, profile)
                self.assertEqual(payload.experiment_scope_id, scope_id)
                self.assertEqual(
                    payload.dataset,
                    _INPUTS.dataset_roots[dataset_root] / dataset_relative,
                )
                self.assertEqual(
                    payload.corpus,
                    _INPUTS.corpus_roots[corpus_root] / corpus_relative,
                )
                self.assertEqual(payload.selection_limit, selection_limit)
                self.assertEqual(payload.case_limit, request.case_limit)
                self.assertEqual(
                    invocation.public_arguments,
                    ("profile", "case-limit", "output-directory"),
                )
                rendered = f"{invocation!r} {payload!r} {invocation.public_arguments!r}"
                for private in (
                    str(payload.dataset), str(payload.corpus), _SENTINEL,
                    str(_INPUTS.amount),
                ):
                    self.assertNotIn(private, rendered)

    def test_missing_operator_input_fails_before_runtime_work(self) -> None:
        inputs = DciBenchmarkOperatorInputs(
            dataset_roots={},
            corpus_roots={},
            private_environment={"DCI_API_KEY": _SENTINEL},
        )
        binding = next(
            binding for binding in create_benchmark_bindings(inputs)
            if binding.binding_id == "qa.bamboogle.paper-full125"
        )
        request = BenchmarkTaskRequest(
            run_id="dci-binding-test",
            suite_ref=BenchmarkSuiteRef("dci.paper-main", "1.0.0"),
            task_id="qa.bamboogle.paper-full125",
            case_limit=125,
            output_directory=Path("/operator/output"),
        )

        with self.assertRaisesRegex(ValueError, "operator input"):
            binding.implementation.build_invocation(request)

    def test_none_amount_is_private_and_valid(self) -> None:
        inputs = DciBenchmarkOperatorInputs(
            dataset_roots=_INPUTS.dataset_roots,
            corpus_roots=_INPUTS.corpus_roots,
            private_environment=_INPUTS.private_environment,
            amount=None,
        )
        binding = next(
            binding for binding in create_benchmark_bindings(inputs)
            if binding.binding_id == "qa.bamboogle.github-sample50"
        )
        request = BenchmarkTaskRequest(
            run_id="dci-binding-test",
            suite_ref=BenchmarkSuiteRef("dci.github", "1.0.0"),
            task_id="qa.bamboogle.github-sample50",
            case_limit=50,
            output_directory=Path("/operator/output"),
        )

        invocation = binding.implementation.build_invocation(request)

        self.assertIsNone(invocation.private_payload.amount)
        self.assertNotIn("amount", invocation.public_arguments)
        self.assertNotIn("None", repr(invocation))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
