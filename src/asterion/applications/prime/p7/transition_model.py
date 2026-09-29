"""Bounded declarative transition rules for verified P7 history replay."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from .verified_history import ArcHistoryRecord, ArcPredictionError, _action_fields
from .world_model import WorldModelSnapshot

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _hash(value: object) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ArcPredictionError
    return value


def _action_data(action: object, data: object) -> None:
    if type(data) is not tuple:
        raise ArcPredictionError
    try:
        _, canonical = _action_fields({"name": action, "data": dict(data)})
    except (TypeError, ValueError, ArcPredictionError):
        raise ArcPredictionError from None
    if canonical != data:
        raise ArcPredictionError


def _cells(value: object) -> None:
    if type(value) is not tuple or len(value) > 80:
        raise ArcPredictionError
    coordinates = []
    for item in value:
        if (type(item) is not tuple or len(item) != 4
                or any(type(part) is not int for part in item)
                or not 0 <= item[0] <= 63 or not 0 <= item[1] <= 63
                or not 0 <= item[2] <= 255 or not 0 <= item[3] <= 255
                or item[2] == item[3]):
            raise ArcPredictionError
        coordinates.append((item[1], item[0]))
    if coordinates != sorted(set(coordinates)):
        raise ArcPredictionError


def _common(action: object, data: object, prior_state_sha256: object,
            after_state_sha256: object, after_frame_sha256: object,
            changed_cells: object, levels_completed: object, state: object) -> None:
    if type(action) is not str:
        raise ArcPredictionError
    _action_data(action, data)
    _hash(prior_state_sha256)
    _hash(after_state_sha256)
    _hash(after_frame_sha256)
    _cells(changed_cells)
    if type(levels_completed) is not int or levels_completed < 0:
        raise ArcPredictionError
    if type(state) is not str or not state:
        raise ArcPredictionError


@dataclass(frozen=True, slots=True)
class ActionExpectation:
    action: str
    data: tuple[tuple[str, int], ...]
    prior_state_sha256: str
    after_state_sha256: str
    after_frame_sha256: str
    changed_cells: tuple[tuple[int, int, int, int], ...]
    levels_completed: int
    state: str

    def __post_init__(self) -> None:
        _common(self.action, self.data, self.prior_state_sha256, self.after_state_sha256,
                self.after_frame_sha256, self.changed_cells, self.levels_completed, self.state)


@dataclass(frozen=True, slots=True)
class TransitionRule:
    action: str
    data: tuple[tuple[str, int], ...]
    prior_state_sha256: str
    after_state_sha256: str
    prior_level: int
    prior_state: str
    prior_frame_sha256: str
    after_frame_sha256: str
    changed_cells: tuple[tuple[int, int, int, int], ...]
    levels_completed: int
    state: str

    def __post_init__(self) -> None:
        _common(self.action, self.data, self.prior_state_sha256, self.after_state_sha256,
                self.after_frame_sha256, self.changed_cells, self.levels_completed, self.state)
        _hash(self.prior_frame_sha256)
        if type(self.prior_level) is not int or self.prior_level < 0:
            raise ArcPredictionError
        if type(self.prior_state) is not str or not self.prior_state:
            raise ArcPredictionError

    def expectation(self) -> ActionExpectation:
        return ActionExpectation(self.action, self.data, self.prior_state_sha256,
                                 self.after_state_sha256, self.after_frame_sha256,
                                 self.changed_cells, self.levels_completed, self.state)


@dataclass(frozen=True, slots=True)
class RetrodictionReport:
    ok: bool
    failures: tuple[str, ...] = ()
    records_checked: int = 0


@dataclass(frozen=True, slots=True)
class TransitionModel:
    rules: tuple[TransitionRule, ...]

    def __post_init__(self) -> None:
        if type(self.rules) is not tuple or any(type(rule) is not TransitionRule for rule in self.rules):
            raise ArcPredictionError

    @classmethod
    def from_history(cls, records: Sequence[ArcHistoryRecord], *, world: WorldModelSnapshot) -> "TransitionModel":
        try:
            rows = tuple(records)
        except (TypeError, ValueError):
            raise ArcPredictionError from None
        if type(world) is not WorldModelSnapshot or not rows or any(type(item) is not ArcHistoryRecord for item in rows):
            raise ArcPredictionError
        report = _validate_chain(rows, world=world)
        if not report.ok:
            raise ArcPredictionError
        rules = []
        for previous, record in zip(rows, rows[1:]):
            rules.append(TransitionRule(
                record.action or "", record.data, previous.after_state_sha256,
                record.after_state_sha256, previous.levels_completed, previous.state,
                previous.after_frame_sha256, record.after_frame_sha256,
                record.changed_cells, record.levels_completed, record.state,
            ))
        return cls(tuple(rules))

    def expectations(self) -> tuple[ActionExpectation, ...]:
        return tuple(rule.expectation() for rule in self.rules)


def _validate_chain(records: tuple[ArcHistoryRecord, ...], *, world: WorldModelSnapshot | None = None) -> RetrodictionReport:
    failures: list[str] = []
    first = records[0]
    if first.sequence != 0:
        failures.append("sequence:start")
    if world is not None and (first.game_id != world.game_id or first.seed != world.seed):
        failures.append("identity:world")
    for previous, record in zip(records, records[1:]):
        if record.sequence != previous.sequence + 1:
            failures.append("sequence:gap")
        if record.game_id != previous.game_id or record.seed != previous.seed or record.run_id != previous.run_id:
            failures.append("identity:record")
        if record.before_state_sha256 != previous.after_state_sha256:
            failures.append("before_state:hash")
        if record.before_frame_sha256 != previous.after_frame_sha256:
            failures.append("before_frame:hash")
    return RetrodictionReport(not failures, tuple(failures), len(records))


def retrodict(model: TransitionModel, records: Sequence[ArcHistoryRecord]) -> RetrodictionReport:
    if type(model) is not TransitionModel:
        return RetrodictionReport(False, ("expectation:model",), 0)
    try:
        rows = tuple(records)
    except (TypeError, ValueError):
        return RetrodictionReport(False, ("sequence:invalid",), 0)
    if not rows:
        return RetrodictionReport(False, ("sequence:empty",), 0)
    if any(type(item) is not ArcHistoryRecord for item in rows):
        return RetrodictionReport(False, ("sequence:invalid",), len(rows))
    chain = _validate_chain(rows)
    failures = list(chain.failures)
    if len(model.rules) != len(rows) - 1:
        failures.append("expectation:count")
    for previous, record, rule in zip(rows, rows[1:], model.rules):
        if record.action != rule.action or record.data != rule.data:
            failures.append("action:identity")
        if previous.levels_completed != rule.prior_level or record.levels_completed != rule.levels_completed:
            failures.append("level:mismatch")
        if previous.state != rule.prior_state or record.state != rule.state:
            failures.append("state:mismatch")
        if previous.after_state_sha256 != rule.prior_state_sha256:
            failures.append("expectation:before_state")
        if record.after_state_sha256 != rule.after_state_sha256:
            failures.append("expectation:state_hash")
        if previous.after_frame_sha256 != rule.prior_frame_sha256:
            failures.append("expectation:before_frame")
        if record.after_frame_sha256 != rule.after_frame_sha256:
            failures.append("expectation:frame")
        if record.changed_cells != rule.changed_cells:
            failures.append("expectation:cells")
    return RetrodictionReport(not failures, tuple(failures), len(rows))
