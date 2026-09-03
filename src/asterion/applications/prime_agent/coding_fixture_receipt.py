"""Closed provider-free receipt for the fixed Prime IPython coding fixture.

The fixture intentionally records only normalized metadata.  It is not a
runtime transcript and cannot support a sandboxed evidence claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final, Literal

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.worker_gate import PrimeWorkerBoundaryReceipt
from asterion.services.bounded_model_session import BoundedModelSessionRequest


_IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_POST_COMPACTION_KINDS: Final = (
    "cwd", "function", "import", "namespace", "workspace-file",
)
_WITNESS_KIND = Literal["namespace", "import", "function", "cwd", "workspace-file"]


class CodingFixtureReceiptError(ValueError):
    """Raised when the fixed coding-fixture truth table is incomplete."""


def _identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _digest(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True, repr=False)
class CodingFixtureWitness:
    """A named post-compaction continuity witness without its private value."""

    session_id: str
    kernel_generation: str
    turn: int
    kind: _WITNESS_KIND

    def __post_init__(self) -> None:
        if (
            not _identifier(self.session_id)
            or not _identifier(self.kernel_generation)
            or not _positive_integer(self.turn)
            or self.kind not in _POST_COMPACTION_KINDS
        ):
            raise CodingFixtureReceiptError("coding fixture receipt is invalid")

    def __repr__(self) -> str:
        return "CodingFixtureWitness(redacted)"


@dataclass(frozen=True, repr=False)
class CodingFixtureObservation:
    """Internal, normalized facts used by the fixed provider-free fixture."""

    built_in_tools: tuple[str, ...]
    model_tool_calls: tuple[str, ...]
    turn_count: int
    compaction_turn: int
    session_id: str
    kernel_generation: str
    image_digest: str
    witnesses: tuple[CodingFixtureWitness, ...]
    child_session_opened: bool
    other_action_taken: bool
    oracle_initially_failed: bool
    oracle_eventually_passed: bool
    session_limits: BoundedModelSessionRequest
    broker_receipt: PrimeModelBrokerReceipt
    worker_receipt: PrimeWorkerBoundaryReceipt

    def __post_init__(self) -> None:
        if (
            type(self.built_in_tools) is not tuple
            or any(type(tool) is not str for tool in self.built_in_tools)
            or type(self.model_tool_calls) is not tuple
            or any(type(tool) is not str for tool in self.model_tool_calls)
            or not _positive_integer(self.turn_count)
            or type(self.compaction_turn) is not int
            or not _identifier(self.session_id)
            or not _identifier(self.kernel_generation)
            or not _digest(self.image_digest)
            or type(self.witnesses) is not tuple
            or any(type(witness) is not CodingFixtureWitness for witness in self.witnesses)
            or any(type(value) is not bool for value in (
                self.child_session_opened, self.other_action_taken,
                self.oracle_initially_failed, self.oracle_eventually_passed,
            ))
        ):
            raise CodingFixtureReceiptError("coding fixture receipt is invalid")

    def __repr__(self) -> str:
        return "CodingFixtureObservation(redacted)"


def verify_prime_coding_fixture_receipt(
    observation: CodingFixtureObservation,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt:
    """Emit the sole allowed fixture receipt, or fail closed on any mismatch."""
    if (
        type(observation) is not CodingFixtureObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.PROVIDER_FREE
        or observation.built_in_tools != ("ipython",)
        or not observation.model_tool_calls
        or any(tool != "ipython" for tool in observation.model_tool_calls)
        or observation.turn_count < 2
        or not 0 < observation.compaction_turn < observation.turn_count
        or observation.child_session_opened is not False
        or observation.other_action_taken is not False
        or observation.oracle_initially_failed is not True
        or observation.oracle_eventually_passed is not True
    ):
        raise CodingFixtureReceiptError("coding fixture receipt is invalid")

    _verify_witnesses(observation)
    _verify_broker_binding(observation)
    _verify_worker_binding(observation)
    return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
        scenario_id="prime.ipython-coding/v1",
        level=PrimeEvidenceLevel.PROVIDER_FREE,
        status="PASS",
    ))


def _verify_witnesses(observation: CodingFixtureObservation) -> None:
    witnesses = observation.witnesses
    if (
        len(witnesses) != len(_POST_COMPACTION_KINDS)
        or tuple(witness.kind for witness in witnesses) != _POST_COMPACTION_KINDS
        or any(
            witness.session_id != observation.session_id
            or witness.kernel_generation != observation.kernel_generation
            or witness.turn <= observation.compaction_turn
            or witness.turn > observation.turn_count
            for witness in witnesses
        )
    ):
        raise CodingFixtureReceiptError("coding fixture receipt is invalid")


def _verify_broker_binding(observation: CodingFixtureObservation) -> None:
    limits, receipt = observation.session_limits, observation.broker_receipt
    if (
        type(limits) is not BoundedModelSessionRequest
        or type(receipt) is not PrimeModelBrokerReceipt
        or receipt.status != "revoked"
        or receipt.session_id != observation.session_id
        or receipt.run_id != limits.run_id
        or receipt.request_count != len(observation.model_tool_calls)
        or any(type(value) is not int or value < 0 for value in (
            receipt.request_count, receipt.input_bytes, receipt.output_bytes,
        ))
        or receipt.request_count > limits.max_requests
        or receipt.input_bytes > limits.max_input_bytes
        or receipt.output_bytes > limits.max_output_bytes
    ):
        raise CodingFixtureReceiptError("coding fixture receipt is invalid")


def _verify_worker_binding(observation: CodingFixtureObservation) -> None:
    broker, worker = observation.broker_receipt, observation.worker_receipt
    if (
        type(worker) is not PrimeWorkerBoundaryReceipt
        or worker.status != "PASS"
        or worker.scenario_id != "prime.ipython-coding/v1"
        or worker.role_id != "prime.ipython-coding"
        or worker.worker_id != broker.worker_id
        or worker.run_id != broker.run_id
        or worker.challenge_digest != broker.challenge_digest
        or worker.image_digest != observation.image_digest
        or not _identifier(worker.worker_id)
        or not _identifier(worker.run_id)
        or not _digest(worker.challenge_digest)
        or not _digest(worker.workload_digest)
        or not _digest(worker.result_digest)
        or not _digest(worker.image_digest)
    ):
        raise CodingFixtureReceiptError("coding fixture receipt is invalid")
