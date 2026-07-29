"""Exact in-package task bindings for the DCI benchmark suites."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    BenchmarkTaskInvocation,
    BenchmarkTaskRequest,
    CapabilityPackageRef,
)
from asterion.capabilities.dci.implementation.operator_inputs import (
    DciBenchmarkOperatorInputs,
)
_DCI_PACKAGE = CapabilityPackageRef("dci", "1.0.0")
_DCI_SUITES = frozenset(("dci.all", "dci.github", "dci.paper-main"))


class DciBenchmarkBindingError(ValueError):
    """Raised before execution when a DCI task cannot be bound exactly."""


@dataclass(frozen=True, slots=True)
class _TaskContract:
    task_id: str
    profile_id: str
    selection_variant: str
    runtime_context_level: str | None = None


_TASK_CONTRACTS = (
    _TaskContract("bcplus.level3", "bcplus.level3", "github-level3"),
    _TaskContract(
        "bcplus.main",
        "bcplus.openai",
        "main",
        runtime_context_level="level3",
    ),
    _TaskContract("beir.arguana", "beir.arguana", "paper-main"),
    _TaskContract("beir.scifact", "beir.scifact", "paper-main"),
    _TaskContract("bright.biology", "bright.biology", "main"),
    _TaskContract(
        "bright.earth-science",
        "bright.earth-science",
        "main",
    ),
    _TaskContract("bright.economics", "bright.economics", "main"),
    _TaskContract("bright.robotics", "bright.robotics", "main"),
    _TaskContract("qa.2wikimultihopqa", "qa.2wikimultihopqa", "main"),
    _TaskContract(
        "qa.bamboogle.github-sample50",
        "qa.bamboogle",
        "github-sample50",
    ),
    _TaskContract(
        "qa.bamboogle.paper-full125",
        "qa.bamboogle",
        "paper-full125",
    ),
    _TaskContract("qa.hotpotqa", "qa.hotpotqa", "main"),
    _TaskContract("qa.musique", "qa.musique", "main"),
    _TaskContract("qa.nq", "qa.nq", "main"),
    _TaskContract("qa.triviaqa", "qa.triviaqa", "main"),
)


@dataclass(frozen=True, slots=True)
class _DciBenchmarkInvocationPayload:
    profile_id: str
    selection_variant: str
    dataset: Path = field(repr=False)
    corpus: Path = field(repr=False)
    output_directory: Path = field(repr=False)
    private_environment: Mapping[str, str] = field(repr=False)
    amount: Decimal | None = field(repr=False)
    case_limit: int
    max_concurrency: int
    resume_policy: str
    runtime_context_level: str | None


class _DciBenchmarkTaskImplementation:
    __slots__ = ("_contract", "_operator_inputs")

    def __init__(
        self,
        contract: _TaskContract,
        operator_inputs: DciBenchmarkOperatorInputs | None,
    ) -> None:
        self._contract = contract
        self._operator_inputs = operator_inputs

    def __repr__(self) -> str:
        return (
            "_DciBenchmarkTaskImplementation("
            f"task_id={self._contract.task_id!r})"
        )

    def build_invocation(
        self,
        request: BenchmarkTaskRequest,
    ) -> BenchmarkTaskInvocation:
        contract = self._contract
        inputs = self._operator_inputs
        if (
            not isinstance(request, BenchmarkTaskRequest)
            or request.task_id != contract.task_id
            or request.suite_ref.suite_id not in _DCI_SUITES
            or request.suite_ref.version != "1.0.0"
        ):
            raise DciBenchmarkBindingError(
                "DCI benchmark task request is invalid"
            )
        if inputs is None:
            raise DciBenchmarkBindingError(
                "DCI benchmark operator input is unavailable"
            )
        dataset = inputs.dataset_roots.get(contract.task_id)
        corpus = inputs.corpus_roots.get(contract.task_id)
        if not isinstance(dataset, Path) or not isinstance(corpus, Path):
            raise DciBenchmarkBindingError(
                "DCI benchmark operator input is unavailable"
            )
        return BenchmarkTaskInvocation(
            task_id=contract.task_id,
            binding_id=contract.task_id,
            public_arguments=(
                contract.profile_id,
                contract.selection_variant,
                f"limit-{request.case_limit}",
            ),
            private_payload=_DciBenchmarkInvocationPayload(
                profile_id=contract.profile_id,
                selection_variant=contract.selection_variant,
                dataset=dataset,
                corpus=corpus,
                output_directory=request.output_directory,
                private_environment=inputs.private_environment,
                amount=inputs.amount,
                case_limit=request.case_limit,
                max_concurrency=1,
                resume_policy="compatible",
                runtime_context_level=contract.runtime_context_level,
            ),
        )


def create_benchmark_bindings(
    *,
    operator_inputs: DciBenchmarkOperatorInputs | None = None,
) -> tuple[BenchmarkTaskBinding, ...]:
    """Return all exact DCI bindings, optionally closed over private inputs."""

    if operator_inputs is not None and not isinstance(
        operator_inputs,
        DciBenchmarkOperatorInputs,
    ):
        raise DciBenchmarkBindingError("DCI benchmark operator input is invalid")
    return tuple(
        BenchmarkTaskBinding(
            owner_package=_DCI_PACKAGE,
            binding_id=contract.task_id,
            implementation=_DciBenchmarkTaskImplementation(
                contract,
                operator_inputs,
            ),
        )
        for contract in _TASK_CONTRACTS
    )


__all__ = (
    "DciBenchmarkBindingError",
    "create_benchmark_bindings",
)
