"""Native, source-independent authority for one fixed P7 ARC game."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Mapping, Protocol, cast

from .game import ArcGameContract, DEFAULT_GAME, P7GameSelection
from .score import P7_ACTION_CAP, P7_GAME_ID, P7_SEED, digest, replay_sha256
from .transition_model import TransitionModel
from .verified_history import ArcHistoryRecord, ArcPredictionError, validate_history_query, validate_prediction
from .world_model import EvidenceRef, WorldModelSnapshot, WorldModelStore


class ArcBrokerError(RuntimeError):
    """Public P7 broker failure; its message contains no engine data."""


@dataclass(frozen=True, slots=True)
class Tool:
    """Application-level tool description exposed to the model.

    The P7 framework prompt only carries general principles; each P7
    application (or framework extension) registers the concrete tools it
    exposes via :class:`P7ToolRegistry`. The operator renders the
    registered tools into the model's prompt at run start so the model
    knows what methods exist on ``p7_client``.
    """

    name: str
    description: str
    signature: str
    category: str


class P7ToolRegistry:
    """Mutable tool registry scoped to one P7 run; thread-unsafe."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add or replace a tool. ``tool.name`` is the unique key."""
        if type(tool) is not Tool:
            raise TypeError("tool must be a Tool instance")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def render_section(self) -> str:
        """Return the markdown 'Tool reference' section; empty if no tools."""
        if not self._tools:
            return ""
        lines: list[str] = ["Tool reference (application surface; not game-specific):"]
        for tool in self._tools.values():
            lines.append(f"- `{tool.signature}`: {tool.description}")
        return "\n".join(lines)


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


def _engine_identity(engine: object, game: P7GameSelection | ArcGameContract) -> tuple[str, int]:
    game_id, seed = getattr(engine, "game_id", None), getattr(engine, "seed", None)
    if type(game_id) is not str or type(seed) is not int or type(seed) is bool:
        raise ValueError
    if game_id != game.game_id or seed != game.seed:
        raise ValueError
    return game_id, seed


class ArcBroker:
    """Journal bounded actions through the selected target level."""

    def __init__(
        self,
        *,
        engine: object,
        game: P7GameSelection | ArcGameContract = DEFAULT_GAME,
        world_model: WorldModelStore | None = None,
    ) -> None:
        if type(game) not in (P7GameSelection, ArcGameContract):
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
        if world_model is not None and (
            type(world_model) is not WorldModelStore
            or world_model.snapshot.game_id != game.game_id
            or world_model.snapshot.seed != game.seed
            or world_model.snapshot.win_levels != game.win_levels
        ):
            raise ArcBrokerError("unavailable")
        self._world_model = world_model
        self._transition_model: TransitionModel | None = None
        self._playbook_projection: dict[str, object] = {}
        self._world_evidence: list[EvidenceRef] = []
        self._initial = initial
        self._current = initial
        self._journal: list[ArcTransition] = []
        self._terminal_reason = "active"
        self._actions_dispatched = 0
        self._failed_action: str | None = None
        self._level_gameplay_actions = 0
        self._history: list[ArcHistoryRecord] | None = None
        # Stable-last-frame no-effect guard is a generic runtime observation:
        # it counts repeated (level, action) pairs with no observed frame
        # change during the current run and surfaces that count to the model.
        # It starts empty and accumulates only from the current run.
        self._no_effect_guard = True
        self._no_effect_counts: dict[tuple[int, str], int] = {}
        # Retrodict: track every (level, action, position) tuple the model
        # has tried this run, with counts. Position is the (x, y) tuple for
        # click actions and None for direction/interact actions. The model
        # can query this through the broker API to avoid repeating probes.
        self._tried_actions: dict[tuple[int, str, tuple[tuple[str, int], ...] | None], int] = {}

    @property
    def journal(self) -> tuple[ArcTransition, ...]:
        return tuple(self._journal)

    @property
    def game(self) -> P7GameSelection | ArcGameContract:
        return self._game

    def world_model(self) -> WorldModelSnapshot | None:
        """Return the immutable private model snapshot for application wiring."""

        return None if self._world_model is None else self._world_model.snapshot

    def transition_model(self) -> TransitionModel | None:
        """Return the last replay-validated transition model, if available."""

        return self._transition_model

    def world_evidence(self) -> tuple[EvidenceRef, ...]:
        """Return immutable evidence references recorded for accepted transitions."""

        return tuple(self._world_evidence)

    def playbook_projection(self) -> dict[str, object]:
        """Return a detached bounded playbook projection."""

        return json.loads(json.dumps(self._playbook_projection, separators=(",", ":")))

    def set_playbook_projection(self, projection: Mapping[str, object]) -> None:
        """Install an application-owned bounded projection without exposing mutability."""

        if not isinstance(projection, Mapping):
            raise ArcBrokerError("unavailable")
        encoded = json.dumps(dict(projection), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 8192:
            raise ArcBrokerError("unavailable")
        self._playbook_projection = json.loads(encoded)

    def _record_world_evidence(self, record: ArcHistoryRecord) -> None:
        if self._world_model is None:
            return
        try:
            self._world_evidence.append(EvidenceRef(
                frame_id=f"frame-{record.sequence}",
                action_id=None if record.action is None else f"action-{record.sequence}",
                source_run=record.run_id,
                summary_hash=record.after_state_sha256.removeprefix("sha256:"),
            ))
            self._world_model.refresh_level(min(record.levels_completed, self._game.win_levels - 1))
            self._transition_model = TransitionModel.from_history(self._bound_history(), world=self._world_model.snapshot)
        except (ArcPredictionError, ValueError):
            self._transition_model = None

    def bind_history(self, run_id: str) -> None:
        if (
            self._history is not None or self._journal
            or self._actions_dispatched != 0 or self._terminal_reason != "active"
            or type(run_id) is not str or not run_id or not run_id.isascii()
        ):
            raise ArcBrokerError("unavailable")
        try:
            initial = ArcHistoryRecord.initial(
                game_id=self._identity[0], seed=self._identity[1], run_id=run_id,
                frame=self._initial.frame[-1], levels_completed=0,
                state=self._initial.state,
                after_state_sha256=_observation_digest(self._initial),
            )
        except ArcPredictionError:
            raise ArcBrokerError("unavailable") from None
        self._history = [initial]

    def _bound_history(self) -> list[ArcHistoryRecord]:
        if self._history is None:
            raise ArcBrokerError("unavailable")
        return self._history

    def history(self, start: int, limit: int) -> list[dict[str, object]]:
        records = self._bound_history()
        try:
            validate_history_query(start=start, limit=limit, latest_sequence=len(records) - 1)
            # A history request is a bounded page, not a promise that all 32
            # records fit in one transport frame.  Large changed-cell samples
            # can make a valid page exceed the worker budget, so shrink the
            # page while preserving sequence order.  The caller can continue
            # from the last returned sequence.
            page_size = limit
            while page_size >= 1:
                page = [record.public_view() for record in records[start:start + page_size]]
                if len(json.dumps(page, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) <= 16384:
                    return page
                if page_size == 1:
                    raise ArcPredictionError
                page_size = max(1, page_size // 2)
        except ArcPredictionError:
            raise ArcBrokerError("unavailable") from None
        raise ArcBrokerError("unavailable")

    def frame_at(self, sequence: int) -> list[list[int]]:
        records = self._bound_history()
        if type(sequence) is not int or not 0 <= sequence < len(records):
            raise ArcBrokerError("unavailable")
        return [list(row) for row in records[sequence].frame]

    def act_checked(self, plan: object) -> dict[str, object]:
        records = self._bound_history()
        self._require_open()
        if type(plan) is not list or not 1 <= len(plan) <= 20:
            raise ArcBrokerError("unavailable")
        try:
            checked = [validate_prediction(item, current_levels=self._current.levels_completed) for item in plan]
        except ArcPredictionError:
            raise ArcBrokerError("unavailable") from None
        transitions: list[ArcTransition] = []
        feedback: list[dict[str, object]] = []

        def append_feedback(record: ArcHistoryRecord, item_stop_reason: str) -> None:
            # Project only bounded delta evidence; never include the settled
            # frame itself in a checked-action result.
            feedback.append({
                "changed_cell_count": record.changed_cell_count,
                "changed_cells": [list(item) for item in record.changed_cells],
                "changed_cells_omitted": record.changed_cells_omitted,
                "before_frame_sha256": record.before_frame_sha256,
                "after_frame_sha256": record.after_frame_sha256,
                "levels_completed": record.levels_completed,
                "state": record.state,
                "no_effect": record.changed_cell_count == 0,
                "stop_reason": item_stop_reason,
            })

        stop_reason = "matched"
        mismatch: dict[str, object] | None = None
        for name, data, expected in checked:
            if (
                self._primitive_actions >= self._game.action_cap
                or (name == "RESET" and self._level_gameplay_actions == 0)
                or (name != "RESET" and (
                    self._terminal_reason == "reset-required"
                    or name not in self._current.available_actions
                ))
            ):
                stop_reason = "action-unavailable"
                break
            previous_levels = self._current.levels_completed
            distinguishing = len(plan) == 1 and self._guard_probe_distinguishes(expected)
            try:
                batch = self.act((ArcAction(name, data),), _allow_guard_probe=distinguishing)
            except ArcBrokerError as error:
                if str(error) != "REPLAN_REQUIRED":
                    raise
                stop_reason = "REPLAN_REQUIRED"
                break
            transitions.extend(batch.transitions)
            record = records[-1]
            cell = expected.get("cell")
            mismatch = None
            if cell is not None:
                cell = cast(dict[str, int], cell)
                x, y = cell["x"], cell["y"]
                if y >= len(record.frame) or x >= len(record.frame[0]) or record.frame[y][x] != cell["value"]:
                    mismatch = {"cell": dict(cell)}
            for key, actual in (
                ("frame_sha256", record.after_frame_sha256),
                ("levels_completed", record.levels_completed),
                ("state", record.state),
            ):
                if key in expected and expected[key] != actual:
                    mismatch = {**(mismatch or {}), key: expected[key]}
            if mismatch is not None:
                stop_reason = "prediction-mismatch"
                append_feedback(record, stop_reason)
                break
            if name == "RESET":
                stop_reason = "reset-applied"
                append_feedback(record, stop_reason)
                break
            if record.levels_completed > previous_levels:
                stop_reason = "level-advanced"
                append_feedback(record, stop_reason)
                break
            if self._no_effect_guard and self._settled_grid_unchanged(record):
                stop_reason = "observation-no-change"
                # Retrodict: attach a small no-effect summary so the model can
                # see, in-band, which (action, position) tuples it has already
                # tried at this level. Generic — no game-specific content.
                this_action_pos = dict(plan[0].get("action", {}).get("data", {})) if plan else {}
                self._retrodict_no_effect_hint = {
                    "action": name,
                    "position": this_action_pos or None,
                    "level": previous_levels,
                    "no_effect_count_for_action_at_level":
                        self._no_effect_counts.get((previous_levels, name), 0),
                    "total_tried_action_names_at_level":
                        sum(
                            1 for k in self._tried_actions
                            if k[0] == previous_levels
                        ),
                }
                append_feedback(record, stop_reason)
                break
            if record.state == "GAME_OVER":
                stop_reason = "game-over"
                append_feedback(record, stop_reason)
                break
            if self._primitive_actions >= self._game.action_cap:
                stop_reason = "action-cap"
                append_feedback(record, stop_reason)
                break
            append_feedback(record, "matched")
        result = ArcActResult(len(transitions), self._current.levels_completed - self._initial.levels_completed, tuple(transitions))
        return {
            "applied_count": result.applied_count,
            "stop_reason": stop_reason,
            "mismatch": mismatch,
            "observation": self._current,
            "terminal": self._status(),
            "batch": result,
            "feedback": feedback,
            "unexecuted_count": len(plan) - result.applied_count,
            "retrodiction": {
                "status": "verified" if self._transition_model is not None else "unavailable",
                "records_checked": len(records),
            },
            "conflict": mismatch,
        }

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

    def act(
        self,
        actions: tuple[str | ArcAction, ...],
        *,
        _allow_guard_probe: bool = False,
    ) -> ArcActResult:
        self._require_open()
        validated = self._validate_actions(actions)
        if (
            self._no_effect_guard
            and not _allow_guard_probe
            and any(self._no_effect_counts.get((self._current.levels_completed, action.name), 0) >= 3 for action in validated)
        ):
            raise ArcBrokerError("REPLAN_REQUIRED")
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
            if self._history is not None:
                try:
                    record = ArcHistoryRecord.following(
                        self._history[-1], action=action,
                        before_state_sha256=transition.before_sha256,
                        after_state_sha256=transition.after_sha256,
                        frame=after.frame[-1], levels_completed=after.levels_completed,
                        state=after.state,
                    )
                except ArcPredictionError:
                    self._failed_action = action.name
                    self._terminal_reason = "engine-invalid"
                    raise ArcBrokerError("unavailable") from None
                self._history.append(record)
                self._record_world_evidence(record)
            self._journal.append(transition)
            transitions.append(transition)
            self._current = after
            if action.name == "RESET" or after.levels_completed > before.levels_completed:
                self._clear_no_effect_level(before.levels_completed)
                self._level_gameplay_actions = 0
            else:
                self._level_gameplay_actions += 1
                # Retrodict: record every attempted (level, action, position)
                # tuple, regardless of outcome. The model can query this to
                # see what it has already tried — both succeeded and not.
                self._record_tried_action(action, after.levels_completed)
                if self._no_effect_guard and after.frame[-1] == before.frame[-1]:
                    self._record_no_effect(action, after.levels_completed)
            if after.levels_completed == self._game.target_level:
                self._terminal_reason = (
                    ("game-won" if after.state == "WIN" else "game-incomplete")
                    if self._game.is_full_game else "level-completed"
                )
                break
            if self._primitive_actions == self._game.action_cap:
                self._terminal_reason = (
                    "human-baseline"
                    if isinstance(self._game, P7GameSelection)
                    and self._game.action_cap_override is not None
                    else "action-cap"
                )
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

    @staticmethod
    def _settled_grid_unchanged(record: ArcHistoryRecord) -> bool:
        return record.changed_cell_count == 0

    def _guard_probe_distinguishes(self, expected: Mapping[str, object]) -> bool:
        """Allow a guarded probe only when it predicts a changed fact."""

        if "cell" in expected:
            cell = cast(dict[str, int], expected["cell"])
            x, y = cell["x"], cell["y"]
            current = self._current.frame[-1]
            if y < len(current) and x < len(current[0]) and current[y][x] != cell["value"]:
                return True
        if "frame_sha256" in expected and expected["frame_sha256"] != digest(self._current.frame[-1]):
            return True
        if "levels_completed" in expected and expected["levels_completed"] != self._current.levels_completed:
            return True
        if "state" in expected and expected["state"] != self._current.state:
            return True
        return False

    def _record_no_effect(self, action: ArcAction, level: int) -> None:
        key = (level, action.name)
        self._no_effect_counts[key] = min(3, self._no_effect_counts.get(key, 0) + 1)
        # NOTE: _tried_actions is already incremented by the unconditional
        # _record_tried_action call in act(); do not double-count here.

    def _clear_no_effect_level(self, level: int) -> None:
        for key in tuple(self._no_effect_counts):
            if key[0] == level:
                del self._no_effect_counts[key]
        for key in tuple(self._tried_actions):
            if key[0] == level:
                del self._tried_actions[key]

    @staticmethod
    def _position_key(action: ArcAction) -> tuple[tuple[str, int], ...] | None:
        """Canonicalize click/coord position; None for direction actions."""
        if action.name == "ACTION6":
            x = None
            y = None
            for k, v in action.data:
                if k == "x" and type(v) is int:
                    x = v
                elif k == "y" and type(v) is int:
                    y = v
            if x is not None and y is not None:
                return (("x", x), ("y", y))
        return None

    def _record_tried_action(self, action: ArcAction, level: int) -> None:
        """Retrodict: track this attempt unconditionally."""
        pos_key = self._position_key(action)
        tried_key = (level, action.name, pos_key)
        self._tried_actions[tried_key] = self._tried_actions.get(tried_key, 0) + 1

    def tried_actions(self, level: int | None = None) -> list[dict[str, object]]:
        """Retrodict: enumerate (action, position, count) tuples tried in this run.

        ``level=None`` returns all levels. The returned dict shape mirrors
        the data the broker has tracked from the current run; the model can
        inspect it to avoid repeating probes that already had no observed
        frame change. Position is None for direction / interact actions.
        """
        result: list[dict[str, object]] = []
        for (lvl, action_name, pos_key), count in sorted(self._tried_actions.items()):
            if level is not None and lvl != level:
                continue
            entry: dict[str, object] = {
                "level": lvl,
                "action": action_name,
                "count": count,
            }
            if pos_key is not None:
                pos = {k: v for k, v in pos_key}
                entry["position"] = pos
            else:
                entry["position"] = None
            result.append(entry)
        return result

    def last_outcome_summary(self, level: int | None = None) -> dict[str, object]:
        """Retrodict: per-action aggregate of attempts and no-effect outcomes."""
        attempts: dict[str, int] = {}
        no_effect: dict[str, int] = {}
        for (lvl, action_name, _pos), count in self._tried_actions.items():
            if level is not None and lvl != level:
                continue
            attempts[action_name] = attempts.get(action_name, 0) + count
        for (lvl, action_name), count in self._no_effect_counts.items():
            if level is not None and lvl != level:
                continue
            no_effect[action_name] = count
        return {"attempts": attempts, "no_effect": no_effect}

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

        if type(self._game) is not P7GameSelection:
            raise ArcBrokerError("unavailable")
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
    "P7ToolRegistry",
    "Tool",
    "P7_ACTION_CAP",
    "P7_GAME_ID",
    "P7_SEED",
)
