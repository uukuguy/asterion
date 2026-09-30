"""Bounded action effects and immutable states used by P7 experience learning.

This module is deliberately independent of the broker and the ARC engine.  It
turns two adjacent, already verified history records into a small observation
that can be retained, compared, and later compiled into a declarative model.
It never infers a game rule from a single effect and never dispatches an
action.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from .verified_history import ArcHistoryRecord, CellChange, Grid

_ACTIONS = frozenset(f"ACTION{i}" for i in range(1, 8))
_STATES = frozenset({"NOT_FINISHED", "WIN", "GAME_OVER"})


def _immutable(value: object) -> object:
    """Return a bounded JSON-like value with no mutable containers."""

    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("entity keys must be strings")
        return tuple(sorted((key, _immutable(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_immutable(item) for item in value)
    raise ValueError("entity values must be JSON-like")


@dataclass(frozen=True, slots=True)
class EffectComponent:
    """A bounded 4-connected group of changed cells."""

    bounds: tuple[int, int, int, int]
    cells: tuple[tuple[int, int], ...]
    old_values: tuple[int, ...]
    new_values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ActionEffect:
    """One verified action transition, with no unbounded frame payload."""

    game_id: str
    seed: int
    run_id: str
    sequence: int
    level: int
    levels_completed: int
    state: str
    action: str
    data: tuple[tuple[str, int], ...]
    before_state_sha256: str
    after_state_sha256: str
    before_frame_sha256: str
    after_frame_sha256: str
    changed_cell_count: int
    changed_cells: tuple[CellChange, ...]
    changed_cells_omitted: int
    outcome: str
    components: tuple[EffectComponent, ...]


@dataclass(frozen=True, slots=True)
class EffectHypothesis:
    """A bounded, declarative effect candidate assembled from observations."""

    key: str
    game_id: str
    seed: int
    level: int
    action_family: str
    action: str
    data: tuple[tuple[str, int], ...]
    signature: str
    status: str
    evidence_sequences: tuple[int, ...]
    conflict_sequences: tuple[int, ...]
    template: ActionEffect | None = None
    win_levels: int = 1

    @property
    def support_count(self) -> int:
        return len(self.evidence_sequences)


@dataclass(frozen=True, slots=True)
class ProbePlan:
    """Read-only probe suggestion; it never dispatches an action."""

    status: str
    reason: str
    action: str | None = None
    data: tuple[tuple[str, int], ...] = ()
    candidate_keys: tuple[str, ...] = ()
    expected_signatures: tuple[str, ...] = ()
    rejected_candidates: tuple[str, ...] = ()


def _components(changes: tuple[CellChange, ...]) -> tuple[EffectComponent, ...]:
    """Group a complete changed-cell sample into deterministic components."""

    if not changes:
        return ()
    by_position = {(x, y): (old, new) for x, y, old, new in changes}
    unseen = set(by_position)
    result: list[EffectComponent] = []
    while unseen:
        start = min(unseen, key=lambda cell: (cell[1], cell[0]))
        stack = [start]
        unseen.remove(start)
        cells: list[tuple[int, int]] = []
        while stack:
            x, y = stack.pop()
            cells.append((x, y))
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    stack.append(neighbour)
        cells.sort(key=lambda cell: (cell[1], cell[0]))
        result.append(EffectComponent(
            bounds=(
                min(x for x, _ in cells), min(y for _, y in cells),
                max(x for x, _ in cells), max(y for _, y in cells),
            ),
            cells=tuple(cells),
            old_values=tuple(by_position[cell][0] for cell in cells),
            new_values=tuple(by_position[cell][1] for cell in cells),
        ))
    return tuple(result)


def extract_action_effect(
    previous: ArcHistoryRecord, record: ArcHistoryRecord,
) -> ActionEffect:
    """Extract one effect from adjacent verified records.

    The function checks run identity and hash continuity before exposing an
    effect.  If the history retained only a sample of changed cells, component
    summaries are omitted rather than pretending the sample is complete.
    """

    if not isinstance(previous, ArcHistoryRecord) or not isinstance(record, ArcHistoryRecord):
        raise ValueError("history records required")
    if (
        previous.game_id != record.game_id
        or previous.seed != record.seed
        or previous.run_id != record.run_id
        or record.sequence != previous.sequence + 1
        or record.action is None
        or record.before_state_sha256 != previous.after_state_sha256
        or record.before_frame_sha256 != previous.after_frame_sha256
    ):
        raise ValueError("history records are not adjacent")
    if record.action not in _ACTIONS:
        raise ValueError("unsupported action")
    if record.changed_cell_count == 0:
        outcome = "no-effect"
    elif record.levels_completed > previous.levels_completed:
        outcome = "level-transition"
    elif record.state in {"WIN", "GAME_OVER"}:
        outcome = "game-over"
    else:
        outcome = "changed"
    return ActionEffect(
        game_id=record.game_id,
        seed=record.seed,
        run_id=record.run_id,
        sequence=record.sequence,
        level=previous.levels_completed,
        levels_completed=record.levels_completed,
        state=record.state,
        action=record.action,
        data=tuple(record.data),
        before_state_sha256=record.before_state_sha256,
        after_state_sha256=record.after_state_sha256,
        before_frame_sha256=record.before_frame_sha256,
        after_frame_sha256=record.after_frame_sha256,
        changed_cell_count=record.changed_cell_count,
        changed_cells=tuple(record.changed_cells),
        changed_cells_omitted=record.changed_cells_omitted,
        outcome=outcome,
        components=() if record.changed_cells_omitted else _components(record.changed_cells),
    )


def _action_family(action: str) -> str:
    return "click" if action == "ACTION6" else "keyboard"


def _signature(effect: ActionEffect) -> str:
    """Create a coordinate-independent signature for grouping effects."""

    components = []
    for component in effect.components:
        origin_x, origin_y = component.bounds[:2]
        components.append((
            tuple((x - origin_x, y - origin_y) for x, y in component.cells),
            component.old_values,
            component.new_values,
        ))
    return repr((effect.outcome, effect.state, effect.levels_completed, tuple(components)))


class ExperienceInducer:
    """Accumulate effects and form/reconcile small mechanism candidates."""

    def __init__(self, *, max_effects: int = 128, win_levels: int = 1) -> None:
        if type(max_effects) is not int or not 1 <= max_effects <= 1024:
            raise ValueError("max_effects must be between 1 and 1024")
        if type(win_levels) is not int or win_levels <= 0:
            raise ValueError("win_levels must be positive")
        self._max_effects = max_effects
        self._win_levels = win_levels
        self._effects: list[ActionEffect] = []
        self._candidates: dict[str, EffectHypothesis] = {}

    def observe(self, effect: ActionEffect) -> tuple[EffectHypothesis, ...]:
        """Record one effect and return the candidates touched by it."""

        if not isinstance(effect, ActionEffect):
            raise ValueError("ActionEffect required")
        if self._effects and (
            effect.game_id != self._effects[-1].game_id
            or effect.seed != self._effects[-1].seed
            or effect.run_id != self._effects[-1].run_id
        ):
            raise ValueError("effects must belong to one run")
        self._effects.append(effect)
        if len(self._effects) > self._max_effects:
            del self._effects[: len(self._effects) - self._max_effects]
        family = _action_family(effect.action)
        signature = _signature(effect)
        key = ":".join((effect.game_id, str(effect.seed), str(effect.level), family, signature))
        broad = [
            candidate for candidate in self._candidates.values()
            if candidate.game_id == effect.game_id
            and candidate.seed == effect.seed
            and candidate.level == effect.level
            and candidate.action_family == family
        ]
        touched: list[EffectHypothesis] = []
        candidate = self._candidates.get(key)
        if candidate is None:
            candidate = EffectHypothesis(
                key=key, game_id=effect.game_id, seed=effect.seed,
                level=effect.level, action_family=family, action=effect.action,
                data=effect.data, signature=signature, status="hypothesis",
                evidence_sequences=(effect.sequence,), conflict_sequences=(),
                template=effect, win_levels=self._win_levels,
            )
            if broad:
                # A second incompatible delta for the same action family is
                # evidence of context dependence, so neither variant is
                # eligible for model compilation until a later partitioning
                # fact is supplied.
                for prior in broad:
                    prior = replace(
                        prior, status="contradicted",
                        conflict_sequences=prior.conflict_sequences + (effect.sequence,),
                    )
                    self._candidates[prior.key] = prior
                    touched.append(prior)
                candidate = replace(
                    candidate, status="contradicted",
                    conflict_sequences=(effect.sequence,),
                )
            self._candidates[key] = candidate
            touched.append(candidate)
        else:
            candidate = replace(
                candidate,
                evidence_sequences=candidate.evidence_sequences + (effect.sequence,),
            )
            self._candidates[key] = candidate
            touched.append(candidate)
        return tuple(touched)

    def effects(self) -> tuple[ActionEffect, ...]:
        return tuple(self._effects)

    def candidates(self) -> tuple[EffectHypothesis, ...]:
        return tuple(sorted(self._candidates.values(), key=lambda item: item.key))

    @staticmethod
    def probe_plan(
        current: "SimState",
        candidates: Sequence[EffectHypothesis],
        *,
        tried_actions: Sequence[tuple[str, tuple[tuple[str, int], ...]]] = (),
    ) -> ProbePlan:
        """Rank a safe, information-bearing probe without executing it."""

        if not isinstance(current, SimState):
            raise ValueError("SimState required")
        tried = set(tried_actions)
        rejected: list[str] = []
        eligible: list[EffectHypothesis] = []
        width, height = len(current.frame[0]), len(current.frame)
        for candidate in candidates:
            if candidate.status != "hypothesis" or candidate.level != current.level:
                continue
            action = (candidate.action, candidate.data)
            if candidate.action not in current.available_actions or action in tried:
                continue
            if candidate.action == "ACTION6":
                values = dict(candidate.data)
                if (
                    set(values) != {"x", "y"}
                    or not 0 <= values["x"] < width
                    or not 0 <= values["y"] < height
                ):
                    rejected.append(candidate.key)
                    continue
            eligible.append(candidate)
        if not eligible:
            return ProbePlan(
                status="no-discriminating-probe", reason="no-current-safe-candidate",
                rejected_candidates=tuple(sorted(rejected)),
            )
        # Prefer the candidate with the least support, since it offers the
        # most information, then make the result deterministic by key.
        eligible.sort(key=lambda item: (item.support_count, item.key))
        chosen = eligible[0]
        return ProbePlan(
            status="ready", reason="candidate-prediction-available",
            action=chosen.action, data=chosen.data,
            candidate_keys=tuple(item.key for item in eligible),
            expected_signatures=tuple(item.signature for item in eligible),
            rejected_candidates=tuple(sorted(rejected)),
        )


@dataclass(frozen=True, slots=True)
class SimState:
    """Immutable bounded state accepted by the declarative simulator."""

    frame: Grid
    level: int
    state: str
    available_actions: tuple[str, ...]
    entities: tuple[tuple[str, object], ...] = ()
    unknown_fields: tuple[str, ...] = ()

    @classmethod
    def from_observation(
        cls,
        *,
        frame: object,
        level: int,
        state: str,
        available_actions: Sequence[str],
        entities: Mapping[str, object] | None = None,
        unknown_fields: Sequence[str] = (),
    ) -> "SimState":
        if type(level) is not int or level < 0 or state not in _STATES:
            raise ValueError("invalid simulation state")
        if not isinstance(frame, (list, tuple)) or not frame:
            raise ValueError("frame must be a non-empty grid")
        rows: list[tuple[int, ...]] = []
        width: int | None = None
        for row in frame:
            if not isinstance(row, (list, tuple)) or not row:
                raise ValueError("frame must be rectangular")
            if any(type(value) is not int or not 0 <= value <= 255 for value in row):
                raise ValueError("frame values must be colors")
            if width is None:
                width = len(row)
            elif width != len(row):
                raise ValueError("frame must be rectangular")
            rows.append(tuple(row))
        actions = tuple(available_actions)
        if (
            not actions or len(set(actions)) != len(actions)
            or any(type(action) is not str or action not in _ACTIONS for action in actions)
        ):
            raise ValueError("available actions must be unique ARC actions")
        if any(type(field) is not str or not field for field in unknown_fields):
            raise ValueError("unknown fields must be named")
        frozen_entities: tuple[tuple[str, object], ...] = ()
        if entities is not None:
            if not isinstance(entities, Mapping):
                raise ValueError("entities must be a mapping")
            frozen_entities = tuple(sorted(
                (key, _immutable(value)) for key, value in entities.items()
            ))
        return cls(
            frame=tuple(rows), level=level, state=state,
            available_actions=actions, entities=frozen_entities,
            unknown_fields=tuple(unknown_fields),
        )


__all__ = [
    "ActionEffect", "EffectComponent", "EffectHypothesis", "ExperienceInducer",
    "ProbePlan", "SimState", "extract_action_effect",
]
