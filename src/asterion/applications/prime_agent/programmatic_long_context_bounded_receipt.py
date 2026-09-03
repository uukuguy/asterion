"""Sealed bounded evidence reduction for Prime programmatic long context."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
)
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.worker_gate import (
    PrimeWorkerBoundaryReceipt,
    issue_prime_bounded_evidence,
)


_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")

# These code-owned P2 identities are intentionally not caller-selectable.
PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_SHA256: Final = (
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST
)


class ProgrammaticLongContextBoundedReceiptError(ValueError):
    """Raised when P2 facts cannot support bounded evidence."""


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


@dataclass(frozen=True, repr=False)
class ProgrammaticLongContextBoundedObservation:
    """Private P2 facts reduced without model, corpus, or program contents.

    A worker boundary receipt exists only after worker destruction; a revoked
    broker receipt establishes broker cleanup before this reducer can emit.
    """

    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    corpus_sha256: str
    program_sha256: str
    response_sha256: str
    aggregate_sha256: str
    oracle_sha256: str
    ipython_cell_executed: bool
    oracle_passed: bool
    broker_receipt: PrimeModelBrokerReceipt
    worker_receipt: PrimeWorkerBoundaryReceipt

    def __repr__(self) -> str:
        return "ProgrammaticLongContextBoundedObservation(redacted)"


def verify_programmatic_long_context_bounded_receipt(
    observation: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED_SANDBOXED,
) -> PrimeEvidenceReceipt:
    """Issue P2 bounded evidence solely from the admitted worker result."""

    if (
        type(observation) is not ProgrammaticLongContextBoundedObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.BOUNDED_SANDBOXED
        or observation.built_in_tools != ("ipython",)
        or observation.active_tool_names != ("ipython",)
        or observation.corpus_sha256 != PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256
        or observation.oracle_sha256 != PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256
        or not all(
            _digest(value)
            for value in (
                observation.program_sha256,
                observation.response_sha256,
                observation.aggregate_sha256,
            )
        )
        or observation.response_sha256 != observation.program_sha256
        or observation.ipython_cell_executed is not True
        or observation.oracle_passed is not True
    ):
        raise ProgrammaticLongContextBoundedReceiptError(
            "programmatic long-context bounded receipt is invalid"
        )
    _verify_broker_and_worker_binding(observation)
    try:
        return issue_prime_bounded_evidence(
            "prime.programmatic-long-context/v1",
            observation.aggregate_sha256,
            observation.worker_receipt,
        )
    except ValueError:
        raise ProgrammaticLongContextBoundedReceiptError(
            "programmatic long-context bounded receipt is invalid"
        ) from None


def _verify_broker_and_worker_binding(
    observation: ProgrammaticLongContextBoundedObservation,
) -> None:
    broker, worker = observation.broker_receipt, observation.worker_receipt
    if (
        type(broker) is not PrimeModelBrokerReceipt
        or broker.status != "revoked"
        or type(worker) is not PrimeWorkerBoundaryReceipt
        or worker.status != "PASS"
        or worker.scenario_id != "prime.programmatic-long-context/v1"
        or worker.role_id != "prime.programmatic-long-context"
        or worker.workload_digest != PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_SHA256
        or worker.result_digest != observation.aggregate_sha256
        or worker.worker_id != broker.worker_id
        or worker.run_id != broker.run_id
        or worker.challenge_digest != broker.challenge_digest
        or not all(
            _identifier(value)
            for value in (broker.session_id, broker.run_id, broker.worker_id)
        )
        or not all(
            _digest(value)
            for value in (
                broker.challenge_digest,
                worker.challenge_digest,
                worker.workload_digest,
                worker.result_digest,
                worker.image_digest,
            )
        )
        or type(broker.request_count) is not int
        or broker.request_count <= 0
        or type(broker.output_bytes) is not int
        or broker.output_bytes <= 0
        or type(broker.input_bytes) is not int
        or broker.input_bytes < 0
    ):
        raise ProgrammaticLongContextBoundedReceiptError(
            "programmatic long-context bounded receipt is invalid"
        )
