"""Native, source-independent authority for one fixed P7 ARC game."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, cast

from .score import P7_ACTION_CAP, P7_GAME_ID, P7_SEED, digest, replay_sha256


class ArcBrokerError(RuntimeError):
    """Public P7 broker failure; its message contains no engine data."""


class _ArcEngine(Protocol):
    def observe(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ArcObservation:
    available_actions: tuple[str, ...]
    frame: tuple[tuple[tuple[int, ...], ...], ...]
    levels_completed: int
    state: str
    win_levels: int


@dataclass(frozen=True, slots=True)
class ArcStatus:
    primitive_actions: int
    levels_completed: int
    actions_remaining: int
    terminal_reason: str


@dataclass(frozen=True, slots=True)
class ArcTransition:
    sequence: int
    action: str
    before_sha256: str
    after_sha256: str
    levels_completed: int


@dataclass(frozen=True, slots=True)
class ArcActResult:
    applied_count: int
    levels_completed: int
    transitions: tuple[ArcTransition, ...]


@dataclass(frozen=True, slots=True, repr=False)
class ArcRunReceipt:
    game_id: str
    seed: int
    primitive_actions: int
    levels_completed: int
    terminal_reason: str
    replay_sha256: str

    def __repr__(self) -> str:
        return "ArcRunReceipt(redacted)"


def _frame(value: object) -> tuple[tuple[tuple[int, ...], ...], ...]:
    if type(value) is not list or not value:
        raise ValueError
    layers: list[tuple[tuple[int, ...], ...]] = []
    for layer in value:
        if type(layer) is not list or not layer:
            raise ValueError
        rows: list[tuple[int, ...]] = []
        width: int | None = None
        for row in layer:
            if type(row) is not list or not row or any(type(item) is not int or not 0 <= item <= 255 for item in row):
                raise ValueError
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise ValueError
            rows.append(tuple(row))
        layers.append(tuple(rows))
    return tuple(layers)


def _action_name(value: object) -> str:
    if type(value) is not str or value not in {f"ACTION{number}" for number in range(1, 8)}:
        raise ValueError
    return value


def _available_action_name(value: object) -> str:
    if type(value) is int and not isinstance(value, bool):
        value = f"ACTION{value}"
    return _action_name(value)


def _snapshot_observation(value: object) -> ArcObservation:
    if type(value) is not dict or set(value) != {
        "available_actions", "frame", "levels_completed", "state", "win_levels"
    }:
        raise ValueError
    available = value["available_actions"]
    if (
        type(available) is not list
        or type(value["levels_completed"]) is not int
        or value["levels_completed"] < 0
        or type(value["win_levels"]) is not int
        or value["win_levels"] != 7
        or value["levels_completed"] > value["win_levels"]
        or type(value["state"]) is not str
        or not value["state"]
    ):
        raise ValueError
    names = tuple(_available_action_name(item) for item in available)
    if tuple(sorted(set(names))) != names:
        raise ValueError
    return ArcObservation(names, _frame(value["frame"]), value["levels_completed"], value["state"], value["win_levels"])


def _observation_digest(value: ArcObservation) -> str:
    return digest(
        {
            "available_actions": value.available_actions,
            "frame": value.frame,
            "levels_completed": value.levels_completed,
            "state": value.state,
            "win_levels": value.win_levels,
        }
    )


def _engine_identity(engine: object) -> tuple[str, int]:
    game_id, seed = getattr(engine, "game_id", None), getattr(engine, "seed", None)
    if type(game_id) is not str or type(seed) is not int or type(seed) is bool:
        raise ValueError
    if game_id != P7_GAME_ID or seed != P7_SEED:
        raise ValueError
    return game_id, seed


class ArcBroker:
    """Journal bounded primitive actions and close at the first level transition."""

    def __init__(self, *, engine: object) -> None:
        if not callable(getattr(engine, "observe", None)) or not (
            callable(getattr(engine, "step", None)) or callable(getattr(engine, "act", None))
        ):
            raise ArcBrokerError("unavailable")
        typed_engine = cast(_ArcEngine, engine)
        try:
            self._identity = _engine_identity(engine)
            initial = _snapshot_observation(typed_engine.observe())
            if initial.levels_completed != 0:
                raise ValueError
        except BaseException:
            raise ArcBrokerError("unavailable") from None
        self._engine = typed_engine
        self._initial = initial
        self._current = initial
        self._journal: list[ArcTransition] = []
        self._terminal_reason = "active"
        self._actions_dispatched = 0
        self._failed_action: str | None = None

    @property
    def journal(self) -> tuple[ArcTransition, ...]:
        return tuple(self._journal)

    def _require_open(self) -> None:
        if self._terminal_reason != "active":
            raise ArcBrokerError("closed")

    @property
    def _primitive_actions(self) -> int:
        return self._actions_dispatched

    def observe(self) -> ArcObservation:
        self._require_open()
        return self._current

    def status(self) -> ArcStatus:
        self._require_open()
        return ArcStatus(
            self._primitive_actions,
            self._current.levels_completed - self._initial.levels_completed,
            P7_ACTION_CAP - self._primitive_actions,
            self._terminal_reason,
        )

    def _validate_actions(self, actions: object) -> tuple[str, ...]:
        if type(actions) is not tuple or not actions or len(actions) > P7_ACTION_CAP - self._primitive_actions:
            raise ArcBrokerError("unavailable")
        try:
            validated = tuple(_action_name(action) for action in actions)
        except ValueError:
            raise ArcBrokerError("unavailable") from None
        if any(action not in self._current.available_actions for action in validated):
            raise ArcBrokerError("unavailable")
        return validated

    def _step(self, action: str) -> object:
        step = getattr(self._engine, "step", None)
        if callable(step):
            return step(action)
        act = getattr(self._engine, "act", None)
        if not callable(act):
            raise ValueError
        return act({"name": action, "data": {}})

    def act(self, actions: tuple[str, ...]) -> ArcActResult:
        self._require_open()
        validated = self._validate_actions(actions)
        transitions: list[ArcTransition] = []
        for action in validated:
            if action not in self._current.available_actions:
                self._failed_action = action
                self._terminal_reason = "action-unavailable"
                raise ArcBrokerError("unavailable")
            before = self._current
            self._actions_dispatched += 1
            try:
                after = _snapshot_observation(self._step(action))
            except BaseException:
                self._failed_action = action
                self._terminal_reason = "engine-uncertain"
                raise ArcBrokerError("uncertain") from None
            if (
                after.win_levels != before.win_levels
                or after.levels_completed < before.levels_completed
                or after.levels_completed > before.levels_completed + 1
            ):
                self._failed_action = action
                self._terminal_reason = "engine-invalid"
                raise ArcBrokerError("unavailable")
            transition = ArcTransition(
                self._primitive_actions,
                action,
                _observation_digest(before),
                _observation_digest(after),
                after.levels_completed - self._initial.levels_completed,
            )
            self._journal.append(transition)
            transitions.append(transition)
            self._current = after
            if after.levels_completed > before.levels_completed:
                self._terminal_reason = "level-completed"
                break
            if self._primitive_actions == P7_ACTION_CAP:
                self._terminal_reason = "action-cap"
                break
        return ArcActResult(len(transitions), self._current.levels_completed - self._initial.levels_completed, tuple(transitions))

    def seal(self) -> ArcRunReceipt:
        if self._terminal_reason == "active":
            raise ArcBrokerError("unavailable")
        return ArcRunReceipt(
            P7_GAME_ID,
            P7_SEED,
            self._primitive_actions,
            self._current.levels_completed - self._initial.levels_completed,
            self._terminal_reason,
            replay_sha256(self._journal, terminal_reason=self._terminal_reason, uncertain_action=self._failed_action),
        )

    def replay(self, engine_factory: Callable[[], object]) -> ArcRunReceipt:
        from .replay import replay_arc_run

        return replay_arc_run(self.journal, self.seal(), engine_factory)


__all__ = (
    "ArcActResult",
    "ArcBroker",
    "ArcBrokerError",
    "ArcObservation",
    "ArcRunReceipt",
    "ArcStatus",
    "ArcTransition",
    "P7_ACTION_CAP",
    "P7_GAME_ID",
    "P7_SEED",
)
