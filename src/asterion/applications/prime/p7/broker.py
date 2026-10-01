"""Native, source-independent authority for one fixed P7 ARC game."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Callable, Mapping, Protocol, TypedDict, cast

from .mechanism_model import MechanismSpec, ModelCertificate, compile_effect_hypothesis, validate_mechanism
from .model_search import search_model
from .experience_induction import EffectHypothesis, ExperienceInducer, SimState, extract_action_effect
from .cognition import GameCognitionStore
from .playbook import (LevelCompletion, PlaybookKey, PlaybookSnapshot, CheckedFact, CheckedRoute, append_checked_route, capture_completed_level, branch_playbook)
from .game import ArcGameContract, DEFAULT_GAME, P7GameSelection
from .score import P7_ACTION_CAP, P7_GAME_ID, P7_SEED, digest, replay_sha256
from .transition_model import ActionExpectation, TransitionModel
from .verified_history import ArcHistoryRecord, ArcPredictionError, validate_history_query, validate_prediction
from .world_model import EvidenceRef, WorldModelSnapshot, WorldModelStore
from .visual_priors import derive_visual_candidates


class ArcBrokerError(RuntimeError):
    """Public P7 broker failure; its message contains no engine data."""


class _PendingProbe(TypedDict):
    layer: str
    key: str
    spec: MechanismSpec
    action: str
    data: tuple[tuple[str, int], ...]
    sequence: int
    before: str


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
        cognition_store: GameCognitionStore | None = None,
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
        if cognition_store is not None and type(cognition_store) is not GameCognitionStore:
            raise ArcBrokerError("unavailable")
        self._cognition_store = cognition_store
        self._transition_model: TransitionModel | None = None
        self._retrodiction_status = "unavailable"
        self._retrodiction_reasons: list[str] = []
        self._playbook_projection: dict[str, object] = {}
        self._world_evidence: list[EvidenceRef] = []
        self._playbook = PlaybookSnapshot(PlaybookKey(game.game_id, game.seed, game.win_levels))
        self._model_conflicts: list[str] = []
        self._pending_probe: _PendingProbe | None = None
        self._probe_tokens: set[tuple[int, str, str, int]] = set()
        self._mechanism_certificate: ModelCertificate | None = None
        self._mechanism_spec: MechanismSpec | None = None
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
        self._retrodict_no_effect_hint: dict[str, object] | None = None
        # Retrodict: track every (level, action, position) tuple the model
        # has tried this run, with counts. Position is the (x, y) tuple for
        # click actions and None for direction/interact actions. The model
        # can query this through the broker API to avoid repeating probes.
        self._tried_actions: dict[tuple[int, str, tuple[tuple[str, int], ...] | None], int] = {}
        self._experience_inducer = ExperienceInducer(win_levels=game.win_levels)

    @property
    def journal(self) -> tuple[ArcTransition, ...]:
        return tuple(self._journal)

    @property
    def game(self) -> P7GameSelection | ArcGameContract:
        return self._game

    def world_model(self) -> WorldModelSnapshot | None:
        """Return the immutable private model snapshot for application wiring."""

        return None if self._world_model is None else self._world_model.snapshot

    def cognition_projection(self) -> dict[str, object]:
        """Return advisory type cognition and exact-game progress memory."""

        if self._cognition_store is None:
            return {"status": "unavailable"}
        return self._cognition_store.projection(
            game_id=self._game.game_id,
            seed=self._game.seed,
            win_levels=self._game.win_levels,
        )

    def _record_cognition(self) -> None:
        """Persist bounded progress without making persistence a run gate."""

        if self._cognition_store is None:
            return
        try:
            self._cognition_store.observe(
                game_id=self._game.game_id,
                seed=self._game.seed,
                win_levels=self._game.win_levels,
                available_actions=self._current.available_actions,
                levels_completed=self._current.levels_completed,
                primitive_actions=self._actions_dispatched,
            )
            if self._current.levels_completed >= self._game.target_level:
                certificate = self._mechanism_certificate
                self._cognition_store.record_experience(
                    game_id=self._game.game_id,
                    seed=self._game.seed,
                    win_levels=self._game.win_levels,
                    levels_completed=self._current.levels_completed,
                    primitive_actions=self._actions_dispatched,
                    model_digest=None if certificate is None else certificate.model_digest,
                )
        except (OSError, TypeError, ValueError):
            # Cognition is an advisory learning cache.  A cache failure must
            # never prevent normal exploration or a valid action dispatch.
            self._retrodiction_reasons = [
                *self._retrodiction_reasons[-15:], "cognition-persistence-unavailable"
            ]

    def transition_model(self) -> TransitionModel | None:
        """Return the last replay-validated transition model, if available."""

        return self._transition_model

    def action_effects(self) -> tuple[dict[str, object], ...]:
        """Return bounded learned effect summaries for this run."""
        current = [{
            "sequence": effect.sequence,
            "level": effect.level,
            "action": {"name": effect.action, "data": dict(effect.data)},
            "outcome": effect.outcome,
            "changed_cell_count": effect.changed_cell_count,
            "changed_cells": [list(cell) for cell in effect.changed_cells],
            "changed_cells_omitted": effect.changed_cells_omitted,
            "motions": [{
                "source_value": motion.source_value,
                "clear_value": motion.clear_value,
                "shape": [list(cell) for cell in motion.shape],
                "dx": motion.dx,
                "dy": motion.dy,
                "count": motion.count,
            } for motion in effect.motions],
            "motion_complete": effect.motion_complete,
            "state": effect.state,
            "after_frame_sha256": effect.after_frame_sha256,
        } for effect in self._experience_inducer.effects()]
        seen = {item["sequence"] for item in current}
        for fact in self._playbook.effect_summaries:
            value = fact.value
            if isinstance(value, Mapping) and value.get("sequence") not in seen:
                current.append({**value, "source": "playbook", "status": "stale"})
        return tuple(current[-256:])

    def mechanism_candidates(self) -> tuple[dict[str, object], ...]:
        """Return candidate lifecycle and evidence without execution authority."""

        current = []
        for candidate in self._experience_inducer.candidates():
            item: dict[str, object] = {
                "key": candidate.key,
                "level": candidate.level,
                "action_family": candidate.action_family,
                "action": {"name": candidate.action, "data": dict(candidate.data)},
                "signature": candidate.signature,
                "status": candidate.status,
                "support_count": candidate.support_count,
                "evidence_sequences": list(candidate.evidence_sequences),
                "conflict_sequences": list(candidate.conflict_sequences),
            }
            # This is a declarative proposal only.  It is useful to the model
            # when constructing a falsifiable probe, but never grants planner
            # authority until record_hypothesis + retrodiction succeeds.
            compiled = compile_effect_hypothesis(candidate)
            if compiled is not None:
                item["compiled_mechanism"] = compiled.to_mapping()
            current.append(item)
        seen = {item["key"] for item in current}
        for fact in self._playbook.candidate_summaries:
            value = fact.value
            if not isinstance(value, Mapping) or value.get("key") in seen:
                continue
            level = value.get("level")
            same_level = type(level) is int and level == self._current.levels_completed
            status = value.get("status")
            # A persisted candidate is still only a hypothesis.  Reclassify a
            # same-level hypothesis as probe-eligible so the next run can
            # validate it against the fresh frame; it never grants execution
            # authority or bypasses record_hypothesis/retrodiction.
            restored_status = "hypothesis" if same_level and status == "hypothesis" else "stale"
            current.append({**value, "status": restored_status, "source": "playbook"})
        bundle = self._compiled_induced_mechanism()
        bundle_item: dict[str, object] | None = None
        if bundle is not None:
            bundle_item = {
                "key": "experience.induced.bundle",
                "level": self._current.levels_completed,
                "action_family": "mixed",
                "action": {"name": "MODEL", "data": {}},
                "status": "hypothesis",
                "support_count": sum(
                    candidate.support_count
                    for candidate in self._experience_inducer.candidates()
                    if candidate.status == "hypothesis" and compile_effect_hypothesis(candidate) is not None
                ),
                "evidence_sequences": sorted({
                    sequence
                    for candidate in self._experience_inducer.candidates()
                    if candidate.status == "hypothesis" and compile_effect_hypothesis(candidate) is not None
                    for sequence in candidate.evidence_sequences
                })[-32:],
                "compiled_mechanism": bundle.to_mapping(),
                "source": "induced-bundle",
            }
        # Put the compact, current induced bundle first.  A candidate response
        # may share the worker's bounded output budget with large evidence
        # fields; the reusable summary must not be hidden at the tail.
        stale = [item for item in current if item.get("source") == "playbook"]
        live = [item for item in current if item.get("source") != "playbook"]
        ordered = ([] if bundle_item is None else [bundle_item]) + live + stale
        return tuple(ordered[:64])

    def _persisted_candidates(self) -> tuple[dict[str, object], ...]:
        """Return bounded same-game candidate priors from the loaded Playbook.

        Candidate summaries are semantic experience, not routes.  Only a
        hypothesis recorded for the current level is exposed as a reusable
        prior; all other summaries remain diagnostics and are counted as
        stale.  The caller still needs a fresh distinguishing probe before
        any mechanism can become planner-eligible.
        """

        result: list[dict[str, object]] = []
        for fact in self._playbook.candidate_summaries:
            value = fact.value
            if not isinstance(value, Mapping):
                continue
            key = value.get("key")
            level = value.get("level")
            status = value.get("status")
            if type(key) is not str or type(level) is not int or type(status) is not str:
                continue
            if status != "hypothesis":
                continue
            item = dict(value)
            item["status"] = (
                "hypothesis" if level == self._current.levels_completed else "stale"
            )
            item["source"] = "playbook"
            result.append(item)
        return tuple(result)

    def _persisted_hypotheses(self) -> tuple[EffectHypothesis, ...]:
        """Rehydrate same-level Playbook candidates for probe planning.

        Playbook records are deliberately summaries rather than executable
        objects.  Rebuilding the bounded hypothesis value here lets the
        ordinary probe planner rank a persisted prior while retaining the
        normal current-frame/action-whitelist checks.
        """

        result: list[EffectHypothesis] = []
        for item in self._persisted_candidates():
            if item.get("status") != "hypothesis":
                continue
            action = item.get("action")
            if not isinstance(action, Mapping):
                continue
            name = action.get("name")
            raw_data = action.get("data")
            if type(name) is not str or not isinstance(raw_data, Mapping):
                continue
            try:
                data = tuple(sorted((key, value) for key, value in raw_data.items()))
                if any(type(key) is not str or type(value) is not int for key, value in data):
                    continue
                evidence = tuple(int(value) for value in item.get("evidence_sequences", ()))
                conflicts = tuple(int(value) for value in item.get("conflict_sequences", ()))
                support = item.get("support_count", len(evidence))
                if type(support) is not int or support < 0:
                    continue
                result.append(EffectHypothesis(
                    key=item["key"], game_id=self._game.game_id,
                    seed=self._game.seed, level=self._current.levels_completed,
                    action_family=item.get("action_family", "unknown"),
                    action=name, data=data, signature=item.get("signature", "persisted"),
                    status="hypothesis", evidence_sequences=evidence,
                    conflict_sequences=conflicts, template=None,
                    win_levels=self._game.win_levels,
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    def _compiled_induced_mechanism(self) -> MechanismSpec | None:
        """Combine non-conflicting induced rules into one advisory model."""

        by_action: dict[tuple[str, tuple[tuple[str, int], ...]], object] = {}
        for candidate in self._experience_inducer.candidates():
            if candidate.status != "hypothesis":
                continue
            compiled = compile_effect_hypothesis(candidate)
            if compiled is None or len(compiled.rules) != 1:
                continue
            rule = compiled.rules[0]
            action_key = (rule.action, candidate.data)
            prior = by_action.get(action_key)
            if prior is False:
                continue
            if prior is not None and prior.mapping() != rule.mapping():
                # Two different rules for one action remain ambiguous; do not
                # synthesize a conflicting model merely to make it visible.
                by_action.pop(action_key, None)
                by_action[action_key] = False
                continue
            if prior is not False:
                by_action[action_key] = rule
        rules = tuple(
            value for value in by_action.values()
            if value is not False
        )
        if not rules:
            return None
        try:
            return MechanismSpec(
                self._game.game_id, self._game.seed, self._game.win_levels,
                tuple(rules), revision=0,
            )
        except (TypeError, ValueError):
            return None

    def learning_hint(self) -> dict[str, object]:
        """Return a small advisory induction summary for the next model turn.

        The normal model path may never call the optional candidate tool.  This
        bounded projection keeps reusable semantic evidence visible in the
        observation without turning it into a route or planner certificate.
        """

        candidates = self._experience_inducer.candidates()
        current_level = self._current.levels_completed
        current_candidates = tuple(
            candidate for candidate in candidates
            if candidate.level == current_level
        )
        persisted_candidates = self._persisted_candidates()
        persisted_current = tuple(
            item for item in persisted_candidates
            if item.get("level") == current_level and item.get("status") == "hypothesis"
        )
        current_keys = {candidate.key for candidate in current_candidates}
        persisted_current = tuple(
            item for item in persisted_current
            if item.get("key") not in current_keys
        )
        all_candidate_keys = {
            candidate.key for candidate in candidates
        } | {
            item["key"] for item in persisted_candidates
            if type(item.get("key")) is str
        }
        current_candidate_total = len(current_candidates) + len(persisted_current)
        compiled_candidates: list[dict[str, object]] = []
        candidate_previews: list[dict[str, object]] = []
        # Level-local hypotheses are the only candidates that can guide a
        # current probe.  Prior-level candidates remain available through the
        # full mechanism-candidate tool, but must not make a replayed level
        # look probe-ready in this bounded hint.
        for candidate in current_candidates:
            candidate_previews.append({
                "action": {"name": candidate.action, "data": dict(candidate.data)},
                "status": candidate.status,
                "support_count": candidate.support_count,
                "evidence_sequences": list(candidate.evidence_sequences[-4:]),
                "motion_complete": bool(candidate.template and candidate.template.motion_complete),
                "changed_cell_count": int(candidate.template.changed_cell_count) if candidate.template else 0,
            })
            compiled = compile_effect_hypothesis(candidate)
            if compiled is None:
                continue
            compiled_candidates.append({
                "key": candidate.key,
                "action": {"name": candidate.action, "data": dict(candidate.data)},
                "support_count": candidate.support_count,
                "evidence_sequences": list(candidate.evidence_sequences[-8:]),
                "compiled_mechanism": compiled.to_mapping(),
            })
        for item in persisted_current:
            action = item.get("action")
            if not isinstance(action, Mapping):
                continue
            candidate_previews.append({
                "action": dict(action),
                "status": "hypothesis",
                "support_count": item.get("support_count", 0),
                "evidence_sequences": list(item.get("evidence_sequences", ())),
                "motion_complete": False,
                "changed_cell_count": 0,
                "source": "playbook",
            })
            compiled = item.get("compiled_mechanism")
            if isinstance(compiled, Mapping):
                compiled_candidates.append({
                    "key": item["key"],
                    "action": dict(action),
                    "support_count": item.get("support_count", 0),
                    "evidence_sequences": list(item.get("evidence_sequences", ())),
                    "compiled_mechanism": dict(compiled),
                    "source": "playbook",
                })
        compiled_candidates.sort(
            key=lambda item: (-int(item["support_count"]), str(item["key"]))
        )
        # The hint is repeated in every observation.  Keep large compiled
        # patterns in the on-demand mechanism_candidates tool instead of
        # replaying them into every model turn.  Small synthetic mechanisms
        # remain inline for a useful bounded fast path.
        bounded_compiled: list[dict[str, object]] = []
        for item in compiled_candidates[:4]:
            encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode()
            if len(encoded) <= 2048:
                bounded_compiled.append(item)
            else:
                bounded_compiled.append({
                    "key": item["key"],
                    "action": item["action"],
                    "support_count": item["support_count"],
                    "evidence_sequences": item["evidence_sequences"],
                    "compiled_mechanism_omitted": True,
                    "compiled_mechanism_digest": digest(item),
                    **({"source": item["source"]} if "source" in item else {}),
                })
        candidate_previews.sort(
            key=lambda item: (-int(item["support_count"]), str(item["action"]))
        )
        probe_status = self.probe_plan().get("status")
        if compiled_candidates and probe_status == "ready":
            recommendation = "inspect_candidate_and_probe"
        elif current_candidates or persisted_current:
            recommendation = "inspect_candidates"
        else:
            recommendation = "ordinary_exploration"
        simulator = self.simulator_status()
        return {
            "recommendation": recommendation,
            "candidate_count": len(all_candidate_keys),
            "current_candidate_count": current_candidate_total,
            "stale_candidate_count": len(all_candidate_keys) - current_candidate_total,
            "candidate_previews": candidate_previews[:4],
            "compiled_candidates": bounded_compiled,
            "simulator": {
                "status": simulator["status"],
                "confirmed_model": simulator["confirmed_model"],
            },
            "execution_authority": "none",
        }

    def probe_plan(self) -> dict[str, object]:
        """Suggest one current-state probe; never dispatch it."""

        try:
            current = SimState.from_observation(
                frame=self._current.frame[-1], level=self._current.levels_completed,
                state=self._current.state, available_actions=self._current.available_actions,
            )
            tried = tuple(
                (action, data or ())
                for (level, action, data), _count in self._tried_actions.items()
                if level == self._current.levels_completed
            )
            live_candidates = self._experience_inducer.candidates()
            live_keys = {candidate.key for candidate in live_candidates}
            persisted = tuple(
                candidate for candidate in self._persisted_hypotheses()
                if candidate.key not in live_keys
            )
            plan = ExperienceInducer.probe_plan(
                current, (*live_candidates, *persisted), tried_actions=tried,
            )
            return {
                "status": plan.status,
                "reason": plan.reason,
                "action": None if plan.action is None else {
                    "name": plan.action, "data": dict(plan.data),
                },
                "candidate_keys": list(plan.candidate_keys),
                "expected_signatures": list(plan.expected_signatures),
                "rejected_candidates": list(plan.rejected_candidates),
            }
        except (TypeError, ValueError):
            return {"status": "unknown", "reason": "current-state-unavailable"}

    def simulator_status(self) -> dict[str, object]:
        """Expose simulator coverage without granting planner authority."""

        certificate = self._mechanism_certificate
        # A submitted hypothesis is already a simulator model under test even
        # though it has no planner authority until its distinguishing probe
        # and complete history replay succeed.  Expose that intermediate
        # lifecycle state instead of reporting the simulator as absent.
        hypothesis_present = self._mechanism_spec is not None or self._pending_probe is not None
        return {
            "status": "verified" if certificate is not None and certificate.planner_eligible else (
                "hypothesis" if hypothesis_present else "absent"
            ),
            "effects": len(self._experience_inducer.effects()),
            "candidates": len(self._experience_inducer.candidates()),
            "confirmed_model": certificate is not None and certificate.planner_eligible,
            "model_digest": None if certificate is None else certificate.model_digest,
            "certificate_records": 0 if certificate is None else certificate.record_count,
            "unknown_reasons": list(self._retrodiction_reasons[-16:]),
        }

    def retrodiction_status(self) -> dict[str, object]:
        certificate = self._mechanism_certificate
        hypothesis_present = self._mechanism_spec is not None or self._pending_probe is not None
        if certificate is None:
            model_status = "hypothesis" if hypothesis_present else "absent"
        elif certificate.planner_eligible:
            model_status = "verified"
        else:
            model_status = "stale"
        return {
            "status": self._retrodiction_status,
            "records_checked": len(self._history or ()),
            "reasons": list(self._retrodiction_reasons[-16:]),
            "planner": {
                "status": model_status,
                "eligible": bool(certificate is not None and certificate.planner_eligible),
                "model_digest": None if certificate is None else certificate.model_digest,
                "records_certified": 0 if certificate is None else certificate.record_count,
            },
        }

    def model_search(
        self,
        *,
        max_nodes: int = 512,
        max_depth: int = 24,
        strategy: str = "astar",
    ) -> dict[str, object]:
        """Search the current state with the verified same-game mechanism.

        This is a planning query only.  It never dispatches an action.  The
        caller must explicitly pass the returned checked plan to
        :meth:`act_checked`, which will stop on the first divergence.
        """

        self._require_open()
        certificate = self._mechanism_certificate
        spec = self._mechanism_spec
        if spec is None or certificate is None or not certificate.planner_eligible:
            return {
                "status": "model-unavailable",
                "reason": "no-planner-certificate",
                "plan": [],
                "expanded_nodes": 0,
                "generated_nodes": 0,
                "start": None,
            }
        try:
            actions = self._model_search_actions()
            world = self._world_model.snapshot if self._world_model is not None else None
            entities = (
                {key: fact.value for key, fact in world.entities.items()}
                if world is not None
                else {}
            )
            result = search_model(
                spec,
                frame=self._current.frame[-1],
                level=self._current.levels_completed,
                state=self._current.state,
                actions=actions,
                target_level=self._game.target_level,
                entities=entities,
                max_nodes=max_nodes,
                max_depth=max_depth,
                strategy=strategy,
                certificate=certificate,
            )
        except (TypeError, ValueError):
            return {
                "status": "model-unavailable",
                "reason": "invalid-search-request",
                "plan": [],
                "expanded_nodes": 0,
                "generated_nodes": 0,
                "start": None,
            }
        projection = result.projection()
        projection.update({
            "model_digest": certificate.model_digest,
            "certificate_records": certificate.record_count,
            "certificate_coverage": certificate.coverage,
            "target_level": self._game.target_level,
            "candidate_action_count": len(actions),
        })
        return projection

    def _model_search_actions(self) -> tuple[dict[str, object], ...]:
        """Build a bounded, evidence-backed action set for model search."""

        records = self._bound_history()
        candidates: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
        click_positions: set[tuple[int, int]] = set()
        for index, record in enumerate(records):
            # A transition record is labelled with its successor level, while
            # its action was performed on the preceding level.  Search may
            # reuse generic keyboard names from any history, but click data
            # and changed-cell coordinates are only valid when their action
            # was observed on the current level.
            action_level = record.levels_completed
            if index > 0 and records[index - 1].levels_completed < record.levels_completed:
                action_level -= 1
            if record.action is not None and record.action in self._current.available_actions:
                if record.action != "ACTION6" or action_level == self._current.levels_completed:
                    candidates.add((record.action, record.data))
            if record.action == "ACTION6" and action_level == self._current.levels_completed and len(record.data) == 2:
                data = dict(record.data)
                if set(data) == {"x", "y"}:
                    click_positions.add((data["x"], data["y"]))
            if action_level == self._current.levels_completed:
                for x, y, _, _ in record.changed_cells:
                    click_positions.add((x, y))
        world = self._world_model.snapshot if self._world_model is not None else None
        if world is not None:
            for fact in (*world.entities.values(), *world.hypotheses.values()):
                value = fact.value
                if not isinstance(value, Mapping):
                    continue
                bounds = tuple(value.get(name) for name in ("min_x", "max_x", "min_y", "max_y"))
                if any(type(item) is not int for item in bounds):
                    continue
                min_x, max_x, min_y, max_y = cast(tuple[int, int, int, int], bounds)
                if min_x <= max_x and min_y <= max_y:
                    click_positions.add(((min_x + max_x) // 2, (min_y + max_y) // 2))
        for name in self._current.available_actions:
            if name != "ACTION6":
                candidates.add((name, ()))
        if "ACTION6" in self._current.available_actions:
            for x, y in sorted(click_positions)[:32]:
                candidates.add(("ACTION6", (("x", x), ("y", y))))
        return tuple(
            {"name": name, "data": dict(data)}
            for name, data in sorted(candidates, key=lambda item: (item[0], item[1]))
        )

    def world_evidence(self) -> tuple[EvidenceRef, ...]:
        """Return immutable evidence references recorded for accepted transitions."""

        return tuple(self._world_evidence)

    def playbook_projection(self) -> dict[str, object]:
        return self._playbook.projection()

    def playbook_visual_hypotheses(self) -> tuple[dict[str, object], ...]:
        """Return the bounded visual candidates without requiring route replay data.

        A checked route can be larger than the model tool's 8 KiB response
        budget.  Visual candidates are still useful in that case, so expose
        this narrow projection separately instead of making callers inspect
        the mutable Playbook object.
        """

        return tuple(
            {
                "layer": fact.layer,
                "key": fact.key,
                "value": fact.value,
                "level": fact.level,
                "evidence_digests": list(fact.evidence_digests),
                "status": "hypothesis",
            }
            for fact in self._playbook.visual_hypotheses
        )

    def load_playbook(self, snapshot: PlaybookSnapshot) -> None:
        if type(snapshot) is not PlaybookSnapshot or snapshot.key != self._playbook.key or self._journal:
            raise ArcBrokerError("unavailable")
        self._playbook = snapshot
        if self._world_model is not None:
            for fact in snapshot.confirmed_facts:
                if fact.layer != "mechanics" and fact.level != self._world_model.current_level:
                    continue
                refs = tuple(EvidenceRef(summary_hash=d) for d in fact.evidence_digests)
                current = self._world_model.snapshot
                existing_fact = getattr(current, fact.layer).get(fact.key)
                existing_hypothesis = current.hypotheses.get(f"{fact.layer}:{fact.key}")
                if existing_fact is not None:
                    if existing_fact.value != fact.value:
                        raise ArcBrokerError("unavailable")
                    # Loading the same snapshot twice is intentionally
                    # idempotent; the current confirmed fact already carries
                    # an equivalent value and needs no duplicate record.
                elif existing_hypothesis is not None:
                    if existing_hypothesis.value != fact.value:
                        raise ArcBrokerError("unavailable")
                    self._world_model.confirm(
                        fact.layer, fact.key, evidence=refs, observed_value=fact.value,
                    )
                else:
                    self._world_model.record_hypothesis(
                        fact.layer, fact.key, fact.value, level=fact.level, evidence=refs,
                    )
                    self._world_model.confirm(fact.layer, fact.key, evidence=refs, observed_value=fact.value)
                if fact.layer == "mechanics" and self._mechanism_spec is None:
                    try:
                        candidate = MechanismSpec.from_mapping(fact.value)
                    except (TypeError, ValueError):
                        continue
                    if (
                        candidate.game_id,
                        candidate.seed,
                        candidate.win_levels,
                    ) == (
                        self._game.game_id,
                        self._game.seed,
                        self._game.win_levels,
                    ):
                        self._mechanism_spec = candidate
            # Visual candidates are advisory and level-local.  Rehydrate only
            # the broker's current level so a later prefix replay can refresh
            # them before any promotion attempt.
            for fact in snapshot.visual_hypotheses:
                if fact.level != self._world_model.current_level:
                    continue
                current = self._world_model.snapshot
                if (
                    getattr(current, fact.layer).get(fact.key) is not None
                    or current.hypotheses.get(f"{fact.layer}:{fact.key}") is not None
                ):
                    # bind_history already projected the current frame's
                    # visual priors.  They are advisory and level-local, so
                    # retaining the live observation is preferable to
                    # inserting a duplicate or replacing it with stale data.
                    continue
                refs = tuple(EvidenceRef(summary_hash=d) for d in fact.evidence_digests)
                self._world_model.record_hypothesis(
                    fact.layer,
                    fact.key,
                    fact.value,
                    level=fact.level,
                    evidence=refs,
                )

    def export_playbook(self, *, successful: bool) -> PlaybookSnapshot:
        snapshot = self._playbook
        def merge_facts(
            previous: tuple[CheckedFact, ...],
            current: tuple[CheckedFact, ...],
        ) -> tuple[CheckedFact, ...]:
            # A broker is normally short lived, while a Playbook spans many
            # runs.  Export must update facts learned this run without
            # discarding semantic evidence from earlier runs.
            merged = {(fact.layer, fact.key): fact for fact in previous}
            merged.update({(fact.layer, fact.key): fact for fact in current})
            return tuple(merged.values())

        effect_facts: list[CheckedFact] = []
        for effect in self._experience_inducer.effects()[-256:]:
            evidence = effect.after_frame_sha256.removeprefix("sha256:")
            level = min(effect.level, self._game.win_levels - 1)
            effect_key = f"experience.effect.{digest((effect.run_id, effect.sequence, effect.after_frame_sha256)).removeprefix('sha256:')[:32]}"
            effect_value = {
                    "sequence": effect.sequence,
                    "level": effect.level,
                    "action": {"name": effect.action, "data": dict(effect.data)},
                    "outcome": effect.outcome,
                    "changed_cell_count": effect.changed_cell_count,
                    "changed_cells": [list(cell) for cell in effect.changed_cells],
                    "changed_cells_omitted": effect.changed_cells_omitted,
                    "motions": [{
                        "source_value": motion.source_value,
                        "clear_value": motion.clear_value,
                        "shape": [list(cell) for cell in motion.shape],
                        "dx": motion.dx,
                        "dy": motion.dy,
                        "count": motion.count,
                    } for motion in effect.motions],
                    "motion_complete": effect.motion_complete,
                    "state": effect.state,
                    "after_frame_sha256": effect.after_frame_sha256,
                }
            try:
                effect_facts.append(CheckedFact("mechanics", effect_key, effect_value, level, (evidence,)))
            except ValueError:
                # A full component/motion description can exceed the bounded
                # fact-value contract for a large moving object.  Preserve a
                # useful, auditable effect summary rather than dropping the
                # whole Playbook (and any level-completion evidence) because
                # one detail is too large.
                effect_facts.append(CheckedFact(
                    "mechanics", effect_key, {
                        "sequence": effect.sequence,
                        "level": effect.level,
                        "action": {"name": effect.action, "data": dict(effect.data)},
                        "outcome": effect.outcome,
                        "changed_cell_count": effect.changed_cell_count,
                        "changed_cells_omitted": effect.changed_cells_omitted,
                        "motion_count": len(effect.motions),
                        "motion_complete": effect.motion_complete,
                        "state": effect.state,
                        "after_frame_sha256": effect.after_frame_sha256,
                        "details_omitted": True,
                    }, level, (evidence,),
                ))
        candidate_facts: list[CheckedFact] = []
        for candidate in self._experience_inducer.candidates()[-256:]:
            evidence = digest(candidate.key).removeprefix("sha256:")
            level = min(candidate.level, self._game.win_levels - 1)
            candidate_key = f"experience.candidate.{evidence[:32]}"
            # Motion signatures can contain a full object shape and exceed the
            # Playbook text bound.  Keep a stable compact identity for
            # persistence; the action/evidence fields remain the useful prior.
            persisted_candidate_id = (
                candidate.key if len(candidate.key) <= 1024 else f"sha256:{evidence}"
            )
            try:
                compiled = compile_effect_hypothesis(candidate)
            except (TypeError, ValueError):
                # Candidate compilation is advisory.  A large or otherwise
                # unsupported pattern must remain a persisted hypothesis,
                # rather than aborting export of the whole Playbook.
                compiled = None
            candidate_value = {
                    "key": persisted_candidate_id,
                    "level": candidate.level,
                    "action_family": candidate.action_family,
                    "action": {"name": candidate.action, "data": dict(candidate.data)},
                    "signature": candidate.signature,
                    "status": candidate.status,
                    "support_count": candidate.support_count,
                    "evidence_sequences": list(candidate.evidence_sequences),
                    "conflict_sequences": list(candidate.conflict_sequences),
                    **({"compiled_mechanism": compiled.to_mapping()}
                       if compiled is not None else {}),
                }
            try:
                candidate_facts.append(CheckedFact("mechanics", candidate_key, candidate_value, level, (evidence,)))
            except ValueError:
                candidate_facts.append(CheckedFact(
                    "mechanics", candidate_key, {
                        "key": persisted_candidate_id,
                        "level": candidate.level,
                        "action_family": candidate.action_family,
                        "action": {"name": candidate.action, "data": dict(candidate.data)},
                        "status": candidate.status,
                        "support_count": candidate.support_count,
                        "evidence_sequences": list(candidate.evidence_sequences),
                        "conflict_sequences": list(candidate.conflict_sequences),
                        "details_omitted": True,
                    }, level, (evidence,),
                ))
        simulator_fact = CheckedFact(
            "mechanics", "experience.simulator.status", self.simulator_status(),
            min(self._current.levels_completed, self._game.win_levels - 1),
            (digest(self.simulator_status()).removeprefix("sha256:"),),
        )
        snapshot = replace(
            snapshot,
            effect_summaries=merge_facts(snapshot.effect_summaries, tuple(effect_facts)),
            candidate_summaries=merge_facts(snapshot.candidate_summaries, tuple(candidate_facts)),
            simulator_summaries=merge_facts(snapshot.simulator_summaries, (simulator_fact,)),
        )
        if not successful:
            return branch_playbook(snapshot, "run-failed")
        if self._transition_model is not None:
            # Split at level boundaries: each route contains only its own level.
            grouped: dict[int, list] = {}
            for rule in self._transition_model.rules:
                grouped.setdefault(rule.prior_level, []).append(rule.expectation())
            for level, expectations in grouped.items():
                if expectations[-1].levels_completed <= level:
                    continue
                old = next((r for r in snapshot.checked_routes if r.level == level), None)
                if old is not None and len(old.expectations) <= len(expectations):
                    continue
                snapshot = replace(snapshot, checked_routes=tuple(r for r in snapshot.checked_routes if r.level != level))
                snapshot = append_checked_route(snapshot, CheckedRoute(level, tuple(expectations), digest([e.after_state_sha256 for e in expectations])))
        return snapshot

    def _record_model_conflict(self, sequence: int, reason: str) -> dict[str, object]:
        code = f"sequence-{sequence}:{reason}"
        self._model_conflicts = [*self._model_conflicts[-63:], code]
        self._retrodiction_reasons = [*self._retrodiction_reasons[-15:], reason]
        self._playbook = replace(self._playbook, conflict_metadata=tuple(sorted(set((*self._playbook.conflict_metadata[-63:], code)))))
        self._retrodiction_status = "conflict"
        return {"sequence": sequence, "reason": reason, "replan_required": True}

    def _confirmed_entity_values(self) -> dict[str, object]:
        if self._world_model is None:
            return {}
        return {
            key: fact.value
            for key, fact in self._world_model.snapshot.entities.items()
            if fact.status == "confirmed"
        }

    def record_hypothesis(self, layer: str, key: str, value: object) -> dict[str, object]:
        """Reserve one falsifiable mechanism probe; callers cannot confirm facts."""
        self._require_open()
        records = self._bound_history()
        world = self._world_model
        try:
            if world is None or self._pending_probe is not None or len(self._probe_tokens) >= 256:
                raise ValueError
            if type(value) is not dict or set(value) != {"mechanism", "probe", "dependencies"}:
                raise ValueError
            spec = MechanismSpec.from_mapping(value["mechanism"])
            if (spec.game_id, spec.seed, spec.win_levels) != (self._game.game_id, self._game.seed, self._game.win_levels):
                raise ValueError
            dependencies = value["dependencies"]
            if type(dependencies) is not list or len(dependencies) > 32 or any(type(x) is not str for x in dependencies):
                raise ValueError
            known = {f"{name}:{k}" for name in ("mechanics", "entities", "relations") for k in getattr(world.snapshot, name)}
            if len(set(dependencies)) != len(dependencies) or not set(dependencies) <= known:
                raise ValueError
            name, data, expected = validate_prediction(value["probe"], current_levels=self._current.levels_completed)
            prediction = spec.predict(
                frame=records[-1].frame,
                action=ArcAction(name, data),
                level=records[-1].levels_completed,
                state=records[-1].state,
                entities=self._confirmed_entity_values(),
            )
            if prediction.status != "predicted" or not self._guard_probe_distinguishes(expected):
                raise ValueError
            # Bind the probe to the full predicted successor, never a free-text claim.
            if "frame_sha256" in expected and expected["frame_sha256"] != digest(prediction.frame):
                raise ValueError
            if "cell" in expected:
                cell = cast(dict[str, int], expected["cell"])
                x, y, value = (cell.get("x"), cell.get("y"), cell.get("value"))
                if type(x) is not int or type(y) is not int or type(value) is not int:
                    raise ValueError
                predicted_frame = prediction.frame
                if predicted_frame is None:
                    raise ValueError
                if predicted_frame[cast(int, y)][cast(int, x)] != cast(int, value):
                    raise ValueError
            if "levels_completed" in expected and prediction.level != expected["levels_completed"]:
                raise ValueError
            if "state" in expected and prediction.state != expected["state"]:
                raise ValueError
            token = (world.current_level, layer, key, spec.revision)
            if token in self._probe_tokens:
                raise ValueError
            previous = records[-1]
            ref = EvidenceRef(frame_id=f"frame-{previous.sequence}", source_run=previous.run_id, summary_hash=previous.after_state_sha256.removeprefix("sha256:"))
            world.record_hypothesis(layer, key, spec.to_mapping(), level=world.current_level, evidence=ref)
            self._probe_tokens.add(token)
            self._pending_probe = _PendingProbe(
                layer=layer, key=key, spec=spec, action=name, data=data,
                sequence=previous.sequence + 1, before=previous.after_state_sha256,
            )
            self._retrodiction_status = "hypothesis"
            return {"status": "hypothesis", "probe_sequence": previous.sequence + 1, "probes_remaining": 1}
        except (ValueError, TypeError, ArcPredictionError):
            raise ArcBrokerError("unavailable") from None

    def promote_hypothesis(self, key: str, evidence_kind: str) -> dict[str, object]:
        """Confirm one visual candidate after broker-verified action evidence.

        Visual priors are intentionally hypotheses.  This narrow promotion
        path accepts only a current-level entity component whose bounding box
        intersects a changed settled cell from the most recent action.  The
        model cannot self-report evidence, and a no-effect or truncated delta
        therefore never promotes a candidate.
        """
        self._require_open()
        world = self._world_model
        records = self._bound_history()
        try:
            if world is None or type(key) is not str or type(evidence_kind) is not str:
                raise ValueError
            if key.startswith("entities:"):
                key = key.removeprefix("entities:")
            if evidence_kind != "changed_cell_in_bounds" or len(records) < 2:
                raise ValueError
            latest = records[-1]
            if latest.action is None or latest.changed_cell_count == 0 or latest.changed_cells_omitted:
                raise ValueError
            fact = world.snapshot.hypotheses.get(f"entities:{key}")
            if fact is None or fact.level != world.current_level:
                raise ValueError
            value = fact.value
            if not isinstance(value, Mapping):
                raise ValueError
            bounds = tuple(value.get(name) for name in ("min_x", "max_x", "min_y", "max_y"))
            if any(type(item) is not int for item in bounds):
                raise ValueError
            min_x, max_x, min_y, max_y = cast(tuple[int, int, int, int], bounds)
            if min_x > max_x or min_y > max_y:
                raise ValueError
            if not any(min_x <= cell[0] <= max_x and min_y <= cell[1] <= max_y for cell in latest.changed_cells):
                raise ValueError
            ref = EvidenceRef(
                frame_id=f"frame-{latest.sequence}",
                action_id=f"action-{latest.sequence}",
                source_run=latest.run_id,
                summary_hash=latest.after_state_sha256.removeprefix("sha256:"),
            )
            fact = world.confirm("entities", key, evidence=ref, observed_value=fact.value)
            return {
                "status": fact.status,
                "layer": fact.layer,
                "key": fact.key,
                "evidence_kind": evidence_kind,
                "sequence": latest.sequence,
            }
        except (ValueError, TypeError):
            raise ArcBrokerError("unavailable") from None

    def _consume_probe(self, record: ArcHistoryRecord, ref: EvidenceRef) -> None:
        pending = self._pending_probe
        if pending is None or self._world_model is None:
            return
        self._pending_probe = None
        matches = (record.sequence == pending["sequence"] and record.before_state_sha256 == pending["before"] and record.action == pending["action"] and record.data == pending["data"])
        certificate = (
            validate_mechanism(
                pending["spec"],
                self._bound_history(),
                entities=self._confirmed_entity_values(),
            )
            if matches
            else None
        )
        if certificate is not None and certificate.planner_eligible:
            self._world_model.confirm(pending["layer"], pending["key"], evidence=ref, observed_value=pending["spec"].to_mapping())
            self._mechanism_certificate = certificate
            self._mechanism_spec = pending["spec"]
            self._retrodiction_status = "verified"
        else:
            self._world_model.conflict(pending["layer"], pending["key"], observed_value={"reason": "probe-contradicted"}, evidence=ref)
            self._record_model_conflict(record.sequence, "probe-contradicted" if matches else "probe-expired")

    def _record_world_evidence(self, record: ArcHistoryRecord) -> None:
        try:
            records = self._bound_history()
            if len(records) >= 2:
                effect = extract_action_effect(records[-2], record)
                self._experience_inducer.observe(effect)
            if self._world_model is None:
                return
            ref = EvidenceRef(
                frame_id=f"frame-{record.sequence}",
                action_id=None if record.action is None else f"action-{record.sequence}",
                source_run=record.run_id,
                summary_hash=record.after_state_sha256.removeprefix("sha256:"),
            )
            self._world_evidence.append(ref)
            self._consume_probe(record, ref)
            if self._mechanism_spec is not None:
                certificate = validate_mechanism(
                    self._mechanism_spec,
                    self._bound_history(),
                    entities=self._confirmed_entity_values(),
                )
                if certificate is None:
                    self._mechanism_certificate = None
                    self._mechanism_spec = None
                    self._record_model_conflict(record.sequence, "mechanism-contradicted")
                else:
                    self._mechanism_certificate = certificate
            level = self._world_model.current_level
            if record.levels_completed > level:
                completion_reason = (
                    (
                        "game-won" if record.state == "WIN" else "game-incomplete"
                    )
                    if record.levels_completed == self._game.target_level
                    and self._game.is_full_game
                    else "level-completed"
                )
                history = self._bound_history()
                level_actions = sum(
                    1 for before, _after in zip(history, history[1:])
                    if before.levels_completed == level
                )
                completion = LevelCompletion(
                    action_count=level_actions,
                    terminal_reason=completion_reason,
                    replay_sha256=replay_sha256(
                        self._journal,
                        terminal_reason=completion_reason,
                        uncertain_action=self._failed_action,
                    ),
                    final_state_sha256=record.after_state_sha256,
                    final_frame_sha256=record.after_frame_sha256,
                )
                self._playbook = capture_completed_level(
                    self._playbook, self._world_model.snapshot,
                    level=level, completion=completion,
                )
                if record.levels_completed < self._game.win_levels:
                    self._world_model.refresh_level(record.levels_completed)
                    self._world_model.record_visual_candidates(
                        derive_visual_candidates(record.frame),
                        level=record.levels_completed,
                        evidence=ref,
                    )
            self._transition_model = TransitionModel.from_history(self._bound_history(), world=self._world_model.snapshot)
            # TransitionModel.from_history is a checked transcript, not a
            # generalized mechanism certificate.  Do not call this verified.
            if self._retrodiction_status not in {"verified", "conflict", "hypothesis"}:
                self._retrodiction_status = "observed"
        except (ArcPredictionError, ValueError):
            self._transition_model = None
            self._retrodiction_status = "unavailable"
            self._retrodiction_reasons = [
                *self._retrodiction_reasons[-15:], "history-validation-failed"
            ]

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
        if self._world_model is not None:
            try:
                self._world_model.record_visual_candidates(
                    derive_visual_candidates(self._initial.frame[-1]),
                    level=0,
                    evidence=EvidenceRef(
                        frame_id="frame-0",
                        source_run=run_id,
                        summary_hash=initial.after_state_sha256.removeprefix("sha256:"),
                    ),
                )
            except (TypeError, ValueError):
                # Visual priors are advisory and cannot make the game
                # unavailable when a candidate projection is rejected.
                self._retrodiction_reasons = [
                    *self._retrodiction_reasons[-15:], "visual-prior-unavailable"
                ]
        self._record_cognition()

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

    def _visual_promotion_candidates(self, record: ArcHistoryRecord) -> list[str]:
        """List candidate keys whose recorded bounds intersect this delta."""
        world = self._world_model
        if world is None or record.changed_cell_count == 0 or record.changed_cells_omitted:
            return []
        candidates: list[str] = []
        for qualified, fact in world.snapshot.hypotheses.items():
            layer, key = qualified.split(":", 1)
            if layer != "entities" or fact.level != world.current_level or ".component." not in key:
                continue
            value = fact.value
            if not isinstance(value, Mapping):
                continue
            bounds = tuple(value.get(name) for name in ("min_x", "max_x", "min_y", "max_y"))
            if any(type(item) is not int for item in bounds):
                continue
            min_x, max_x, min_y, max_y = cast(tuple[int, int, int, int], bounds)
            if min_x <= max_x and min_y <= max_y and any(
                min_x <= cell[0] <= max_x and min_y <= cell[1] <= max_y
                for cell in record.changed_cells
            ):
                candidates.append(key)
        return sorted(candidates)[:16]

    def act_checked(
        self, plan: object, *, replay_expectations: tuple[ActionExpectation, ...] = ()
    ) -> dict[str, object]:
        records = self._bound_history()
        self._require_open()
        if type(plan) is not list or not 1 <= len(plan) <= 20:
            raise ArcBrokerError("unavailable")
        try:
            checked = [validate_prediction(item, current_levels=self._current.levels_completed) for item in plan]
        except ArcPredictionError:
            raise ArcBrokerError("unavailable") from None
        if type(replay_expectations) is not tuple or any(type(item) is not ActionExpectation for item in replay_expectations):
            raise ArcBrokerError("unavailable")
        if replay_expectations and (
            len(replay_expectations) > len(checked)
            or any((name, data) != (w.action, w.data) for (name, data, _), w in zip(checked, replay_expectations))
        ):
            raise ArcBrokerError("unavailable")
        transitions: list[ArcTransition] = []
        feedback: list[dict[str, object]] = []
        self._retrodict_no_effect_hint = None

        def append_feedback(record: ArcHistoryRecord, item_stop_reason: str) -> None:
            # Project only bounded delta evidence; never include the settled
            # frame itself in a checked-action result.
            item = {
                "changed_cell_count": record.changed_cell_count,
                "changed_cells": [list(item) for item in record.changed_cells],
                "changed_cells_omitted": record.changed_cells_omitted,
                "before_frame_sha256": record.before_frame_sha256,
                "after_frame_sha256": record.after_frame_sha256,
                "levels_completed": record.levels_completed,
                "state": record.state,
                "no_effect": record.changed_cell_count == 0,
                "stop_reason": item_stop_reason,
            }
            promotion_candidates = self._visual_promotion_candidates(record)
            if promotion_candidates:
                item["promotion_candidates"] = promotion_candidates
            feedback.append(item)

        stop_reason = "matched"
        mismatch: dict[str, object] | None = None
        conflict: dict[str, object] | None = None
        unavailable_action: str | None = None
        for index, (name, data, expected) in enumerate(checked):
            witness = replay_expectations[index] if index < len(replay_expectations) else None
            if replay_expectations and witness is None:
                stop_reason = "route-plan-diverged"
                break
            if witness is not None and records[-1].after_state_sha256 != witness.prior_state_sha256:
                stop_reason = "route-expectation-mismatch"
                mismatch = {"route": "before-state"}
                conflict = self._record_model_conflict(records[-1].sequence, "route-before-state")
                break
            if self._primitive_actions >= self._game.action_cap:
                stop_reason = "action-cap"
                break
            if name == "RESET" and self._level_gameplay_actions == 0:
                stop_reason = "action-unavailable"
                unavailable_action = name
                break
            if name != "RESET" and (
                self._terminal_reason == "reset-required"
                or name not in self._current.available_actions
            ):
                stop_reason = "action-unavailable"
                unavailable_action = name
                break
            if witness is None and self._prefix_coordinate_reuse(ArcAction(name, data), expected):
                stop_reason = "prefix-action-reuse"
                unavailable_action = name
                mismatch = {
                    "prefix_action_reuse": {
                        "level": self._current.levels_completed,
                        "action": name,
                        "position": {
                            key: value for key, value in self._position_key(ArcAction(name, data)) or ()
                        },
                        "requires": "current-level-cell-or-frame-evidence",
                    },
                }
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
            if witness is not None and (
                record.after_state_sha256 != witness.after_state_sha256
                or record.after_frame_sha256 != witness.after_frame_sha256
                or record.changed_cells != witness.changed_cells
                or record.levels_completed != witness.levels_completed
                or record.state != witness.state
            ):
                stop_reason = "route-expectation-mismatch"
                mismatch = {"route": "after-state"}
                conflict = self._record_model_conflict(record.sequence, "route-after-state")
                append_feedback(record, stop_reason)
                break
            if self._model_conflicts and self._model_conflicts[-1].startswith(f"sequence-{record.sequence}:"):
                stop_reason = "model-conflict"
                conflict = {"sequence": record.sequence, "reason": "model-conflict", "replan_required": True}
                append_feedback(record, stop_reason)
                break
            if mismatch is not None:
                stop_reason = "prediction-mismatch"
                conflict = self._record_model_conflict(record.sequence, "prediction-mismatch")
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
                this_action_pos = dict(plan[index].get("action", {}).get("data", {})) if index < len(plan) else {}
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
            "no_effect_hint": self._retrodict_no_effect_hint,
            "unexecuted_count": len(plan) - result.applied_count,
            "available_actions": list(self._current.available_actions),
            "invalid_action": unavailable_action,
            "retrodiction": {
                **self.retrodiction_status(),
            },
            "conflict": conflict,
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
            self._record_cognition()
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

    def _prefix_coordinate_reuse(
        self, action: ArcAction, expected: Mapping[str, object]
    ) -> bool:
        """Reject an ungrounded click copied from a replayed prior-level prefix."""

        if self._current.levels_completed <= 0 or action.name != "ACTION6":
            return False
        position = self._position_key(action)
        if position is None:
            return False
        prior_positions = self._prior_level_positions(self._current.levels_completed, action.name)
        if position not in prior_positions:
            return False
        return not self._visual_probe_distinguishes(expected)

    def _visual_probe_distinguishes(self, expected: Mapping[str, object]) -> bool:
        """Require a cell or frame change prediction for a reused prefix click."""

        if "cell" in expected:
            cell = cast(dict[str, int], expected["cell"])
            x, y = cell["x"], cell["y"]
            current = self._current.frame[-1]
            if y < len(current) and x < len(current[0]) and current[y][x] != cell["value"]:
                return True
        if "frame_sha256" in expected and expected["frame_sha256"] != digest(self._current.frame[-1]):
            return True
        return False

    def _prior_level_positions(
        self, level: int, action_name: str
    ) -> set[tuple[tuple[str, int], ...]]:
        """Return click positions used before the current level began."""

        if self._history is None or level <= 0:
            return set()
        positions: set[tuple[tuple[str, int], ...]] = set()
        records = self._history
        for index, record in enumerate(records):
            if record.action != action_name:
                continue
            action_level = record.levels_completed
            if index > 0 and records[index - 1].levels_completed < record.levels_completed:
                action_level -= 1
            if action_level >= level:
                continue
            position = self._position_key(ArcAction(record.action, record.data))
            if position is not None:
                positions.add(position)
        return positions

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
