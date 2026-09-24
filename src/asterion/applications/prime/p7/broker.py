"""Native, source-independent authority for one fixed P7 ARC game."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, cast

from .game import DEFAULT_GAME, P7GameSelection
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
class ArcAction:
    name: str
    data: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ArcStatus:
    primitive_actions: int
    levels_completed: int
    actions_remaining: int
    terminal_reason: str


@dataclass(frozen=True, slots=True)
class ArcTerminalSnapshot:
    """Final broker state available only after execution has closed."""

    observation: ArcObservation
    status: ArcStatus


@dataclass(frozen=True, slots=True)
class ArcTransition:
    sequence: int
    action: str
    before_sha256: str
    after_sha256: str
    levels_completed: int
    data: tuple[tuple[str, int], ...] = ()


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


def _canonical_action(value: object) -> ArcAction:
    if type(value) is str:
        value = ArcAction(value)
    if type(value) is not ArcAction or type(value.name) is not str:
        raise ValueError
    if value.name != "RESET" and value.name not in {f"ACTION{number}" for number in range(1, 8)}:
        raise ValueError
    if value.name == "ACTION6":
        if (
            type(value.data) is not tuple
            or len(value.data) != 2
            or any(type(item) is not tuple or len(item) != 2 for item in value.data)
            or tuple(item[0] for item in value.data) != ("x", "y")
            or any(type(item[1]) is not int or not 0 <= item[1] <= 63 for item in value.data)
        ):
            raise ValueError
    elif value.data != ():
        raise ValueError
    return value


def _available_action_name(value: object) -> str:
    if type(value) is int and not isinstance(value, bool):
        value = f"ACTION{value}"
    return _action_name(value)


def _snapshot_observation(value: object, *, win_levels: int) -> ArcObservation:
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
        or value["win_levels"] != win_levels
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


def _engine_identity(engine: object, game: P7GameSelection) -> tuple[str, int]:
    game_id, seed = getattr(engine, "game_id", None), getattr(engine, "seed", None)
    if type(game_id) is not str or type(seed) is not int or type(seed) is bool:
        raise ValueError
    if game_id != game.game_id or seed != game.seed:
        raise ValueError
    return game_id, seed


class ArcBroker:
    """Journal bounded actions through the selected target level."""

    def __init__(self, *, engine: object, game: P7GameSelection = DEFAULT_GAME) -> None:
        if type(game) is not P7GameSelection:
            raise ArcBrokerError("unavailable")
        if not callable(getattr(engine, "observe", None)) or not (
            callable(getattr(engine, "step", None)) or callable(getattr(engine, "act", None))
        ):
            raise ArcBrokerError("unavailable")
        typed_engine = cast(_ArcEngine, engine)
        try:
            self._identity = _engine_identity(engine, game)
            initial = _snapshot_observation(typed_engine.observe(), win_levels=game.win_levels)
            if initial.levels_completed != 0 or initial.state != "NOT_FINISHED":
                raise ValueError
        except BaseException:
            raise ArcBrokerError("unavailable") from None
        self._engine = typed_engine
        self._game = game
        self._initial = initial
        self._current = initial
        self._journal: list[ArcTransition] = []
        self._terminal_reason = "active"
        self._actions_dispatched = 0
        self._failed_action: str | None = None
        self._level_gameplay_actions = 0

    @property
    def journal(self) -> tuple[ArcTransition, ...]:
        return tuple(self._journal)

    @property
    def game(self) -> P7GameSelection:
        return self._game

    def _require_open(self) -> None:
        if self._terminal_reason not in {"active", "reset-required"}:
            raise ArcBrokerError("closed")

    @property
    def _primitive_actions(self) -> int:
        return self._actions_dispatched

    def observe(self) -> ArcObservation:
        self._require_open()
        return self._current

    def status(self) -> ArcStatus:
        self._require_open()
        return self._status()

    def _status(self) -> ArcStatus:
        return ArcStatus(
            self._primitive_actions,
            self._current.levels_completed - self._initial.levels_completed,
            self._game.action_cap - self._primitive_actions,
            self._terminal_reason,
        )

    def terminal_snapshot(self) -> ArcTerminalSnapshot:
        """Return the final recorded observation and status after broker closure."""

        if self._terminal_reason in {"active", "reset-required"}:
            raise ArcBrokerError("unavailable")
        return ArcTerminalSnapshot(self._current, self._status())

    def _validate_actions(self, actions: object) -> tuple[ArcAction, ...]:
        if type(actions) is not tuple or not actions or len(actions) > self._game.action_cap - self._primitive_actions:
            raise ArcBrokerError("unavailable")
        try:
            validated = tuple(_canonical_action(action) for action in actions)
        except ValueError:
            raise ArcBrokerError("unavailable") from None
        if any(action.name != "RESET" and action.name not in self._current.available_actions for action in validated):
            raise ArcBrokerError("unavailable")
        return validated

    def _step(self, action: ArcAction) -> object:
        step = getattr(self._engine, "step", None)
        if callable(step):
            if action.data:
                return step(action.name, dict(action.data))
            return step(action.name)
        act = getattr(self._engine, "act", None)
        if not callable(act):
            raise ValueError
        return act({"name": action.name, "data": dict(action.data)})

    def act(self, actions: tuple[str | ArcAction, ...]) -> ArcActResult:
        self._require_open()
        validated = self._validate_actions(actions)
        transitions: list[ArcTransition] = []
        for action in validated:
            if action.name == "RESET":
                if self._level_gameplay_actions == 0:
                    raise ArcBrokerError("unavailable")
            elif self._terminal_reason == "reset-required":
                raise ArcBrokerError("unavailable")
            elif action.name not in self._current.available_actions:
                self._failed_action = action.name
                self._terminal_reason = "action-unavailable"
                raise ArcBrokerError("unavailable")
            before = self._current
            self._actions_dispatched += 1
            try:
                after = _snapshot_observation(self._step(action), win_levels=self._game.win_levels)
            except BaseException:
                self._failed_action = action.name
                self._terminal_reason = "engine-uncertain"
                raise ArcBrokerError("uncertain") from None
            if (
                after.win_levels != before.win_levels
                or (action.name == "RESET" and (after.levels_completed != before.levels_completed or after.state != "NOT_FINISHED"))
                or (action.name != "RESET" and (after.levels_completed < before.levels_completed or after.levels_completed > before.levels_completed + 1))
            ):
                self._failed_action = action.name
                self._terminal_reason = "engine-invalid"
                raise ArcBrokerError("unavailable")
            transition = ArcTransition(
                self._primitive_actions,
                action.name,
                _observation_digest(before),
                _observation_digest(after),
                after.levels_completed - self._initial.levels_completed,
                action.data,
            )
            self._journal.append(transition)
            transitions.append(transition)
            self._current = after
            if action.name == "RESET" or after.levels_completed > before.levels_completed:
                self._level_gameplay_actions = 0
            else:
                self._level_gameplay_actions += 1
            if after.levels_completed == self._game.target_level:
                self._terminal_reason = (
                    ("game-won" if after.state == "WIN" else "game-incomplete")
                    if self._game.is_full_game else "level-completed"
                )
                break
            if self._primitive_actions == self._game.action_cap:
                self._terminal_reason = "action-cap"
                break
            if after.state == "GAME_OVER":
                self._terminal_reason = (
                    "reset-required" if self._level_gameplay_actions > 0 else "game-over"
                )
                break
            self._terminal_reason = "active"
            if action.name == "RESET" or after.levels_completed > before.levels_completed:
                break
        return ArcActResult(len(transitions), self._current.levels_completed - self._initial.levels_completed, tuple(transitions))

    def seal(self) -> ArcRunReceipt:
        if self._terminal_reason == "active":
            raise ArcBrokerError("unavailable")
        reason = "game-over" if self._terminal_reason == "reset-required" else self._terminal_reason
        return ArcRunReceipt(
            *self._identity,
            self._primitive_actions,
            self._current.levels_completed - self._initial.levels_completed,
            reason,
            replay_sha256(self._journal, terminal_reason=reason, uncertain_action=self._failed_action),
        )

    def replay(self, engine_factory: Callable[[], object]) -> ArcRunReceipt:
        from .replay import replay_arc_run

        return replay_arc_run(self.journal, self.seal(), engine_factory, game=self._game)


__all__ = (
    "ArcActResult",
    "ArcAction",
    "ArcBroker",
    "ArcBrokerError",
    "ArcObservation",
    "ArcRunReceipt",
    "ArcStatus",
    "ArcTerminalSnapshot",
    "ArcTransition",
    "P7_ACTION_CAP",
    "P7_GAME_ID",
    "P7_SEED",
)
