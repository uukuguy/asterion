"""Exact, private DCI implementations for portable benchmark task IDs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from asterion.benchmarks import BenchmarkTaskInvocation, BenchmarkTaskRequest
from asterion.capability_packages import BenchmarkTaskBinding, CapabilityPackageRef
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)
from asterion.dci.paper_benchmarks import (
    PaperBenchmark,
    PaperExperimentScope,
    resolve_experiment_scope,
    resolve_paper_benchmark,
)


_OWNER = CapabilityPackageRef("dci", "1.0.0")
_PUBLIC_ARGUMENTS = ("profile", "case-limit", "output-directory")


@dataclass(frozen=True, slots=True)
class DciBenchmarkInvocation:
    """Private DCI execution values assembled from one selected task."""

    profile: str
    experiment_scope_id: str
    dataset_contract_id: str
    mode: str
    selection_limit: int
    case_limit: int
    dataset: Path = field(repr=False)
    corpus: Path = field(repr=False)
    output_directory: Path = field(repr=False)
    benchmark: PaperBenchmark = field(repr=False)
    experiment_scope: PaperExperimentScope = field(repr=False)
    private_environment: Mapping[str, str] = field(repr=False)
    amount: Decimal | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class _DciTaskSpec:
    task_id: str
    profile: str
    experiment_scope_id: str
    dataset_contract_id: str
    dataset_root: str
    dataset_relative: str
    corpus_root: str
    corpus_relative: str


_SPECS = (
    _DciTaskSpec("bcplus.level3", "bcplus.level3", "browsecomp-plus.main.all830", "browsecomp-plus", "bcplus", "bcplus_qa.jsonl", "bcplus", "bc_plus_docs"),
    _DciTaskSpec("bcplus.main", "bcplus.openai", "browsecomp-plus.main.all830", "browsecomp-plus", "bcplus", "bcplus_qa.jsonl", "bcplus", "bc_plus_docs"),
    _DciTaskSpec("beir.arguana", "beir.arguana", "beir.arguana.main.random50", "beir.arguana", "beir", "arguana/test.jsonl", "beir", "arguana"),
    _DciTaskSpec("beir.scifact", "beir.scifact", "beir.scifact.main.random50", "beir.scifact", "beir", "scifact/test.jsonl", "beir", "scifact"),
    _DciTaskSpec("bright.biology", "bright.biology", "bright.biology.main.full", "bright.biology", "bright", "biology/bright_biology.jsonl", "bright", "biology"),
    _DciTaskSpec("bright.earth-science", "bright.earth-science", "bright.earth-science.main.full", "bright.earth-science", "bright", "earth_science/bright_earth_science.jsonl", "bright", "earth_science"),
    _DciTaskSpec("bright.economics", "bright.economics", "bright.economics.main.full", "bright.economics", "bright", "economics/economics_full.jsonl", "bright", "economics"),
    _DciTaskSpec("bright.robotics", "bright.robotics", "bright.robotics.main.full", "bright.robotics", "bright", "robotics/bright_robotics.jsonl", "bright", "robotics"),
    _DciTaskSpec("qa.2wikimultihopqa", "qa.2wikimultihopqa", "qa.2wikimultihopqa.main.random50", "qa.2wikimultihopqa", "qa", "2wikimultihopqa/test.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.bamboogle.github-sample50", "qa.bamboogle", "qa.bamboogle.upstream.sample50", "qa.bamboogle", "qa", "bamboogle/test.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.bamboogle.paper-full125", "qa.bamboogle", "qa.bamboogle.main.full", "qa.bamboogle", "paper-full", "bamboogle/test-125.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.hotpotqa", "qa.hotpotqa", "qa.hotpotqa.main.random50", "qa.hotpotqa", "qa", "hotpotqa/test.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.musique", "qa.musique", "qa.musique.main.random50", "qa.musique", "qa", "musique/test.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.nq", "qa.nq", "qa.nq.main.random50", "qa.nq", "qa", "nq/test.jsonl", "wiki", "wiki_corpus"),
    _DciTaskSpec("qa.triviaqa", "qa.triviaqa", "qa.triviaqa.main.random50", "qa.triviaqa", "qa", "triviaqa/test.jsonl", "wiki", "wiki_corpus"),
)


@dataclass(frozen=True, slots=True)
class _DciBenchmarkTaskBinding:
    spec: _DciTaskSpec
    inputs: DciBenchmarkOperatorInputs = field(repr=False)
    benchmark: PaperBenchmark = field(repr=False)
    experiment_scope: PaperExperimentScope = field(repr=False)

    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation:
        if request.task_id != self.spec.task_id:
            raise ValueError("DCI benchmark task request is invalid")
        dataset_root = self.inputs.dataset_roots.get(self.spec.dataset_root)
        corpus_root = self.inputs.corpus_roots.get(self.spec.corpus_root)
        if dataset_root is None or corpus_root is None:
            raise ValueError("DCI benchmark operator input is unavailable")
        return BenchmarkTaskInvocation(
            task_id=request.task_id,
            binding_id=self.spec.task_id,
            public_arguments=_PUBLIC_ARGUMENTS,
            private_payload=DciBenchmarkInvocation(
                profile=self.spec.profile,
                experiment_scope_id=self.spec.experiment_scope_id,
                dataset_contract_id=self.spec.dataset_contract_id,
                mode=self.benchmark.mode,
                selection_limit=self.experiment_scope.selection_count,
                case_limit=request.case_limit,
                dataset=dataset_root / self.spec.dataset_relative,
                corpus=corpus_root / self.spec.corpus_relative,
                output_directory=request.output_directory,
                benchmark=self.benchmark,
                experiment_scope=self.experiment_scope,
                private_environment=self.inputs.private_environment,
                amount=self.inputs.amount,
            ),
        )


def create_benchmark_bindings(
    operator_inputs: DciBenchmarkOperatorInputs,
) -> tuple[BenchmarkTaskBinding, ...]:
    """Create the closed DCI binding catalog with host-injected inputs."""

    if type(operator_inputs) is not DciBenchmarkOperatorInputs:
        raise ValueError("DCI benchmark operator input is invalid")
    return tuple(
        BenchmarkTaskBinding(
            owner_package=_OWNER,
            binding_id=spec.task_id,
            implementation=_DciBenchmarkTaskBinding(
                spec=spec,
                inputs=operator_inputs,
                benchmark=resolve_paper_benchmark(spec.dataset_contract_id),
                experiment_scope=resolve_experiment_scope(
                    spec.experiment_scope_id,
                ),
            ),
        )
        for spec in _SPECS
    )
