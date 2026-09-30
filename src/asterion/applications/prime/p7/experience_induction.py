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

from .verified_history import ArcHistoryRecord, CellChange, Grid, stable_changed_cells

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
class EffectMotion:
    """A repeated object/component translation inferred from a full delta."""

    source_value: int
    clear_value: int
    shape: tuple[tuple[int, int], ...]
    dx: int
    dy: int
    count: int = 1


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
    # ``changed_cells`` remains the bounded public sample.  These fields are
    # private semantic evidence derived from the retained frame pair.
    full_changed_cells: tuple[CellChange, ...] = ()
    motions: tuple[EffectMotion, ...] = ()
    motion_complete: bool = False


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


def _connected_cells(cells: set[tuple[int, int]]) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return deterministic 4-connected components for a coordinate set."""

    remaining = set(cells)
    result: list[tuple[tuple[int, int], ...]] = []
    while remaining:
        start = min(remaining, key=lambda cell: (cell[1], cell[0]))
        stack = [start]
        remaining.remove(start)
        component: list[tuple[int, int]] = []
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    stack.append(neighbour)
        result.append(tuple(sorted(component, key=lambda cell: (cell[1], cell[0]))))
    return tuple(result)


def _motions(
    changes: tuple[CellChange, ...],
    before: Grid | None = None,
    after: Grid | None = None,
) -> tuple[tuple[EffectMotion, ...], bool]:
    """Infer conservative source→clear and clear→source translations.

    A motion is emitted only when the complete changed set can be paired by a
    single displacement.  This deliberately leaves mixed or partially
    observed effects unmodelled instead of guessing a rule.
    """

    by_pair: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for x, y, old, new in changes:
        by_pair.setdefault((old, new), set()).add((x, y))
    descriptors: list[tuple[int, int, tuple[tuple[int, int], ...], int, int]] = []
    covered: set[tuple[int, int]] = set()
    for (source, clear), source_cells in sorted(by_pair.items()):
        if source == clear or not source_cells or (clear, source) not in by_pair:
            continue
        # The reverse delta is the same physical translation viewed from the
        # destination.  Prefer a non-background source (and use a stable
        # colour ordering for two nonzero colours) so one action yields one
        # forward motion rather than two inverse rules.
        if source == 0 and clear != 0:
            continue
        if source != 0 and clear != 0 and source < clear:
            continue
        destination_cells = by_pair[(clear, source)]
        if before is not None and after is not None:
            source_colour = {
                (x, y) for y, row in enumerate(before)
                for x, value in enumerate(row) if value == source
            }
            destination_colour = {
                (x, y) for y, row in enumerate(after)
                for x, value in enumerate(row) if value == source
            }
            source_components = tuple(
                component for component in _connected_cells(source_colour)
                if set(component) & source_cells
            )
            destination_components = tuple(
                component for component in _connected_cells(destination_colour)
                if set(component) & destination_cells
            )
        else:
            source_components = _connected_cells(source_cells)
            destination_components = _connected_cells(destination_cells)
        for component in source_components:
            if not component:
                continue
            # Try each destination anchor; only an exact translated component
            # is accepted.  Components are small and frame cells are bounded.
            component_set = set(component)
            component_set = set(component)
            destination_sets = [set(item) for item in destination_components]
            candidate_offsets = sorted(
                (dx - component[0][0], dy - component[0][1])
                for dx, dy in (destination_cells if before is None else {
                    point for item in destination_sets for point in item
                })
            )
            matches: list[tuple[int, int]] = []
            for offset in candidate_offsets:
                translated = {(x + offset[0], y + offset[1]) for x, y in component_set}
                if before is None:
                    valid = translated <= destination_cells
                else:
                    valid = any(translated == item for item in destination_sets)
                if valid:
                    matches.append(offset)
            if len(set(matches)) != 1 and before is not None and after is not None:
                # Unchanged cells of the same colour can join the changed
                # component in a full-frame connected-component view.  Fall
                # back to the changed source/destination sets; this still
                # requires an exact translated shape and therefore does not
                # guess through an incomplete delta.
                source_components = _connected_cells(source_cells)
                destination_components = _connected_cells(destination_cells)
                destination_sets = [set(item) for item in destination_components]
                matches = []
                for fallback_component in source_components:
                    component_set = set(fallback_component)
                    candidate_offsets = sorted(
                        (dx - fallback_component[0][0], dy - fallback_component[0][1])
                        for dx, dy in destination_cells
                    )
                    local_matches = []
                    for offset in candidate_offsets:
                        translated = {(x + offset[0], y + offset[1]) for x, y in component_set}
                        if any(translated == set(item) for item in destination_components):
                            local_matches.append(offset)
                    if len(set(local_matches)) == 1:
                        matches = local_matches
                        component = fallback_component
                        break
            if len(set(matches)) != 1:
                continue
            dx, dy = matches[0]
            translated = {(x + dx, y + dy) for x, y in component_set}
            # Avoid treating a source component as motion when a separate
            # destination component is left unexplained by this pairing.
            if before is None:
                if not translated <= destination_cells:
                    continue
            elif not any(translated == item for item in destination_sets):
                continue
            min_x = min(x for x, _ in component)
            min_y = min(y for _, y in component)
            shape = tuple(sorted(
                ((x - min_x, y - min_y) for x, y in component),
                key=lambda cell: (cell[1], cell[0]),
            ))
            descriptors.append((source, clear, shape, dx, dy))
            covered.update(component_set & source_cells)
            covered.update(translated & destination_cells)
    grouped: dict[tuple[int, int, tuple[tuple[int, int], ...], int, int], int] = {}
    for descriptor in descriptors:
        grouped[descriptor] = grouped.get(descriptor, 0) + 1
    motions = tuple(
        EffectMotion(source, clear, shape, dx, dy, count)
        for (source, clear, shape, dx, dy), count in sorted(grouped.items())
    )
    return motions, covered == {(x, y) for x, y, _old, _new in changes}


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
    full_count, full_changes, full_omitted = stable_changed_cells(
        previous.frame, record.frame, limit=len(previous.frame) * len(previous.frame[0]),
    )
    if full_count != record.changed_cell_count or full_omitted != 0:
        raise ValueError("history frame delta is inconsistent")
    motions, motion_complete = _motions(full_changes, previous.frame, record.frame)
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
        components=_components(full_changes),
        full_changed_cells=full_changes,
        motions=motions,
        motion_complete=motion_complete,
    )


def _action_family(action: str) -> str:
    return "click" if action == "ACTION6" else "keyboard"


def _signature(effect: ActionEffect) -> str:
    """Create a coordinate-independent signature for grouping effects."""

    if effect.motion_complete and effect.motions:
        return repr((
            "translation", effect.outcome, effect.state, effect.levels_completed,
            tuple((
                motion.source_value, motion.clear_value, motion.shape,
                motion.dx, motion.dy, motion.count,
            ) for motion in effect.motions),
        ))

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
        key = ":".join((effect.game_id, str(effect.seed), str(effect.level), effect.action, repr(effect.data), signature))
        broad = [
            candidate for candidate in self._candidates.values()
            if candidate.game_id == effect.game_id
            and candidate.seed == effect.seed
            and candidate.level == effect.level
            and candidate.action == effect.action
            and candidate.data == effect.data
        ]
        touched: list[EffectHypothesis] = []
        candidate = self._candidates.get(key)
        if candidate is None:
            candidate = EffectHypothesis(
                key=key, game_id=effect.game_id, seed=effect.seed,
                level=effect.level, action_family=family, action=effect.action,
                data=effect.data, signature=signature,
                status="boundary" if effect.outcome == "no-effect" else "hypothesis",
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
            if effect.sequence in candidate.evidence_sequences:
                return (candidate,)
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
    "ActionEffect", "EffectComponent", "EffectHypothesis", "EffectMotion", "ExperienceInducer",
    "ProbePlan", "SimState", "extract_action_effect",
]
