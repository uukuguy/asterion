"""Read-only P1 verification over provider-owned worker observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING

from .task import P1_INPUT_TUPLE
from .worker import (
    P1CellObservation,
    P1InstrumentationSnapshot,
    P1Worker,
    P1WorkerCleanupReceipt,
)

if TYPE_CHECKING:
    from .receipt import P1CleanupReceipt


class P1OracleError(ValueError):
    def __init__(self) -> None:
        super().__init__("P1 oracle rejected")


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _validate_receipt(value: P1StageOneReceipt | P1OracleReceipt) -> None:
    for key, item in asdict(value).items():
        if key.endswith("_sha256"):
            if type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None:
                raise P1OracleError()
        elif key != "final_status":
            if type(item) is not int or item < 0:
                raise P1OracleError()


@dataclass(frozen=True, slots=True)
class P1StageOneReceipt:
    worker_identity_sha256: str
    setup_effect_sha256: str
    stage_one_effect_sha256: str
    after_sequence: int

    def __post_init__(self) -> None:
        _validate_receipt(self)
        if self.after_sequence != 2:
            raise P1OracleError()

    def sha256(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class P1OracleReceipt:
    worker_identity_sha256: str
    stage_one_receipt_sha256: str
    stage_one_effect_sha256: str
    stage_two_effect_sha256: str
    checkpoint_sha256: str
    compact_receipt_sha256: str
    kernel_generation: int
    before_attachment_generation: int
    after_attachment_generation: int
    before_context_tokens: int
    after_context_tokens: int
    final_status: str = "verified"

    def __post_init__(self) -> None:
        _validate_receipt(self)
        if (
            self.final_status != "verified"
            or self.kernel_generation < 1
            or self.before_attachment_generation < 1
            or self.after_attachment_generation != self.before_attachment_generation + 1
            or self.after_context_tokens >= self.before_context_tokens
        ):
            raise P1OracleError()

    @property
    def succeeded(self) -> bool:
        return self.final_status == "verified"

    def sha256(self) -> str:
        return _digest(asdict(self))


class P1Oracle:
    """Bind once to a live worker; never execute or seed solution cells."""

    def __init__(self, worker: P1Worker, *, kernel_generation: int = 1) -> None:
        if type(kernel_generation) is not int or kernel_generation < 1:
            raise P1OracleError()
        initial = worker.snapshot()
        if initial.cells or initial.checkpoint is not None:
            raise P1OracleError()
        if initial.seeded_symbols != ("input_tuple", "task_statement"):
            raise P1OracleError()
        self._worker = worker
        self._identity = initial.identity
        self._authority = initial.authority
        self._kernel_generation = kernel_generation
        self._first: P1StageOneReceipt | None = None
        self._prefix: tuple[P1CellObservation, ...] = ()
        self._final: P1OracleReceipt | None = None
        self._cleanup: P1CleanupReceipt | None = None

    def __repr__(self) -> str:
        return "<P1Oracle>"

    def _validate_snapshot(
        self, snapshot: P1InstrumentationSnapshot, count: int
    ) -> None:
        current = self._worker.snapshot()
        if (
            type(snapshot) is not P1InstrumentationSnapshot
            or snapshot.authority is not self._authority
            or snapshot.identity != self._identity
            or snapshot != current
            or snapshot.seeded_symbols != ("input_tuple", "task_statement")
            or len(snapshot.cells) != count
        ):
            raise P1OracleError()
        if (
            len({cell.request_id for cell in snapshot.cells}) != count
            or len({cell.turn_id for cell in snapshot.cells}) != count
        ):
            raise P1OracleError()
        for sequence, cell in enumerate(snapshot.cells, 1):
            if (
                cell.sequence != sequence
                or cell.status != "completed"
                or cell.audit_denials != 0
            ):
                raise P1OracleError()

    def _validate_objects(self, cells: tuple[P1CellObservation, ...]) -> None:
        multiplier, offset, first_input, second_input = P1_INPUT_TUPLE
        expected_probe = (
            multiplier * first_input + offset,
            multiplier * second_input + offset,
        )
        expected_file = (
            json.dumps(
                {"input": list(P1_INPUT_TUPLE), "setup_value": expected_probe[0]},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        expected_sha256 = sha256(expected_file).hexdigest()
        object_id = cells[0].accumulator_id
        if type(object_id) is not int or object_id <= 0:
            raise P1OracleError()
        for cell in cells:
            if (
                cell.accumulator_id != object_id
                or cell.class_name != "AffineAccumulator"
                or cell.callable_probe != expected_probe
                or cell.file_bytes != expected_file
                or cell.file_sha256 != expected_sha256
            ):
                raise P1OracleError()
        verification = cells[1]
        if (
            verification.stage_one_verified
            != {
                "object_id": object_id,
                "probe": expected_probe[0],
                "file_sha256": expected_sha256,
            }
            or verification.file_reads != 1
            or verification.file_read_sha256 != (expected_sha256,)
            or (object_id, first_input, expected_probe[0])
            not in verification.call_observations
        ):
            raise P1OracleError()

    def verify_stage_one(
        self, snapshot: P1InstrumentationSnapshot
    ) -> P1StageOneReceipt:
        self._validate_snapshot(snapshot, 2)
        if snapshot.checkpoint is not None:
            raise P1OracleError()
        self._validate_objects(snapshot.cells)
        setup, verification = snapshot.cells
        multiplier, offset, first_input, _ = P1_INPUT_TUPLE
        if (
            setup.stage_one_verified is not None
            or setup.final_result is not None
            or verification.final_result is not None
            or (setup.accumulator_id, first_input, multiplier * first_input + offset)
            not in setup.call_observations
        ):
            raise P1OracleError()
        if self._first is not None:
            if self._prefix != snapshot.cells:
                raise P1OracleError()
            return self._first
        self._prefix = snapshot.cells
        self._first = P1StageOneReceipt(
            self._identity.sha256(),
            setup.sha256(),
            verification.sha256(),
            2,
        )
        return self._first

    def verify_stage_two(
        self,
        snapshot: P1InstrumentationSnapshot,
        stage_one: P1StageOneReceipt,
    ) -> P1OracleReceipt:
        self._validate_snapshot(snapshot, 3)
        if (
            self._first is None
            or stage_one is not self._first
            or snapshot.cells[:2] != self._prefix
        ):
            raise P1OracleError()
        checkpoint = snapshot.checkpoint
        if (
            checkpoint is None
            or checkpoint.after_sequence != 2
            or checkpoint.worker_identity_sha256 != self._identity.sha256()
            or checkpoint.after_attachment_generation
            != checkpoint.before_attachment_generation + 1
            or checkpoint.kernel_generation != self._kernel_generation
            or not 0
            <= checkpoint.after_context_tokens
            < checkpoint.before_context_tokens
        ):
            raise P1OracleError()
        self._validate_objects(snapshot.cells)
        final = snapshot.cells[-1]
        multiplier, offset, first_input, second_input = P1_INPUT_TUPLE
        second_value = multiplier * second_input + offset
        expected_result = multiplier * first_input + offset + second_value
        if (
            type(final.final_result) is not int
            or final.final_result != expected_result
            or final.file_reads != 1
            or final.file_read_sha256 != (final.file_sha256,)
            or final.stage_one_verified != self._prefix[-1].stage_one_verified
            or (final.accumulator_id, second_input, second_value)
            not in final.call_observations
        ):
            raise P1OracleError()
        if self._final is None:
            self._final = P1OracleReceipt(
                self._identity.sha256(),
                stage_one.sha256(),
                stage_one.stage_one_effect_sha256,
                final.sha256(),
                checkpoint.checkpoint_sha256,
                checkpoint.compact_receipt_sha256,
                checkpoint.kernel_generation,
                checkpoint.before_attachment_generation,
                checkpoint.after_attachment_generation,
                checkpoint.before_context_tokens,
                checkpoint.after_context_tokens,
            )
        elif self._final.stage_two_effect_sha256 != final.sha256():
            raise P1OracleError()
        return self._final

    def validates_result(self, result: P1OracleReceipt) -> bool:
        return self._final is not None and result is self._final

    def validates_worker_cleanup(self, cleanup: P1WorkerCleanupReceipt) -> bool:
        return (
            type(cleanup) is P1WorkerCleanupReceipt
            and self._final is not None
            and cleanup is self._worker.cleanup_receipt
            and cleanup.worker_identity_sha256 == self._identity.sha256()
            and cleanup.last_effect_sha256 == self._final.stage_two_effect_sha256
            and cleanup.reaped is True
            and cleanup.pipes_closed is True
            and cleanup.root_removed is True
            and cleanup.reap_count == 1
        )
