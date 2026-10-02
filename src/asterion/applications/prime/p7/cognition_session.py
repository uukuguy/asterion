"""Episode state machine for semantic P7 game cognition.

The session owns experiment lifecycle and audit events.  The semantic store
owns durable meaning; this module never turns a hypothesis into an executable
route or lets an LLM directly resolve a claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import uuid

from .semantic_cognition import CognitionError, SemanticCognitionStore


class CognitionSessionError(ValueError):
    """Invalid cognition operation or stale experiment binding."""


class CognitionPersistenceError(CognitionSessionError):
    """The private cognition event ledger could not be durably updated."""


_STATES = {"OBSERVE", "PROPOSE", "EXPERIMENT_SELECTED", "ACTION_EXECUTED", "ANALYZED", "SNAPSHOT", "READY", "STOPPED"}
_MAX_EVENTS = 512
_MAX_ACTIONS = 128
_OBSERVED_STATES = {"NOT_FINISHED", "GAME_OVER", "WIN"}
_MAX_EXPECTED_FRAME_BYTES = 64 * 1024
_MAX_EXPECTED_BYTES = 64 * 1024
_ANALYSIS_STATUS_ALIASES = {
    "certain": "certain",
    "confirmed": "certain",
    "supported": "certain",
    "falsified": "falsified",
    "refuted": "falsified",
    "contradicted": "falsified",
    "not_supported": "falsified",
    "undetermined": "undetermined",
    "still_undetermined": "undetermined",
    "supported_but_unconfirmed": "undetermined",
    "weakened_but_unconfirmed": "undetermined",
    "not_supported_but_unconfirmed": "undetermined",
    "partially_supported_but_unconfirmed": "undetermined",
}


def _normalize_analysis_status(value: object) -> str:
    if type(value) is not str:
        raise CognitionSessionError("invalid analysis status")
    normalized = _ANALYSIS_STATUS_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise CognitionSessionError("invalid analysis status")
    return normalized


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 2048:
        raise CognitionSessionError(f"invalid {name}")
    return value


def _digest(observation: Mapping[str, Any]) -> str:
    # Only bind an episode to an observation fingerprint; the raw observation
    # remains in the private runtime trace, never in cognition events.
    safe = {
        "frame": observation.get("frame"),
        "levels_completed": observation.get("levels_completed"),
        "state": observation.get("state"),
    }
    payload = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_frame(value: object) -> tuple[object, ...]:
    """Validate a concrete post-action frame prediction.

    A generic ``frame_changed`` predicate only proves that something changed.
    A concrete frame prediction is the smallest bounded observation that can
    support a semantic claim about which scene resulted from an action.
    """

    if not isinstance(value, (list, tuple)) or not value:
        raise CognitionSessionError("invalid expected frame")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(payload.encode("utf-8")) > _MAX_EXPECTED_FRAME_BYTES:
        raise CognitionSessionError("expected frame is too large")

    def check(node: object, *, nested: bool = False) -> object:
        if not isinstance(node, (list, tuple)) or not node:
            raise CognitionSessionError("invalid expected frame")
        result: list[object] = []
        for cell in node:
            if isinstance(cell, (list, tuple)):
                result.append(check(cell, nested=True))
            elif type(cell) is int and 0 <= cell <= 255:
                result.append(cell)
            else:
                raise CognitionSessionError("invalid expected frame cell")
        return tuple(result)

    return check(value)  # type: ignore[return-value]


class CognitionSession:
    """Bounded cognition episodes backed by one semantic level ledger."""

    def __init__(
        self,
        store: SemanticCognitionStore,
        *,
        session_id: str | None = None,
        max_actions_per_episode: int = 64,
        max_resets: int = 32,
        event_root: Path | None = None,
    ) -> None:
        if type(store) is not SemanticCognitionStore:
            raise CognitionSessionError("store is unavailable")
        if type(max_actions_per_episode) is not int or not 1 <= max_actions_per_episode <= _MAX_ACTIONS:
            raise CognitionSessionError("invalid action limit")
        if type(max_resets) is not int or not 0 <= max_resets <= _MAX_EVENTS:
            raise CognitionSessionError("invalid reset limit")
        sid = session_id or uuid.uuid4().hex
        if type(sid) is not str or not sid.isascii() or not 1 <= len(sid) <= 128:
            raise CognitionSessionError("invalid session id")
        self.store = store
        self.session_id = sid
        self.max_actions_per_episode = max_actions_per_episode
        self.max_resets = max_resets
        self._event_path = (event_root or store.path.parent) / f"semantic-events-{sid}.json"
        # The per-session event ledger is the durable source of truth.  This
        # companion JSONL stream is the operator-facing live log: it is a
        # stable path that can be tailed while a run is still in progress.
        # Each line contains the cognition event and any changed hypotheses.
        self._live_log_path = self._event_path.with_name(f"cognition-live-{sid}.jsonl")
        self._live_log_announced = False
        self._events: list[dict[str, Any]] = []
        self._sequence = 0
        self._episode = 0
        self._state = "OBSERVE"
        self._observation: Mapping[str, Any] | None = None
        self._before_digest: str | None = None
        self._pending: dict[str, Any] | None = None
        self._episode_actions = 0
        self._resets = 0
        self._analyzed = False
        self._logged_claims: dict[str, dict[str, Any]] = {}
        self._emit("cognition.session.started", {"session_id": sid})

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(json.dumps(self._events)))

    def _emit(self, event_type: str, payload: Mapping[str, Any] | None = None) -> None:
        if event_type not in {
            "cognition.session.started", "cognition.episode.started", "cognition.hypothesis.proposed",
            "cognition.experiment.selected", "cognition.action.executed", "cognition.observation.analyzed",
            "cognition.hypothesis.updated",
            "cognition.hypothesis.confirmed", "cognition.hypothesis.falsified", "cognition.hypothesis.remains_undetermined",
            "cognition.snapshot", "cognition.episode.reset", "cognition.ready_for_solve", "cognition.stopped",
        }:
            raise CognitionSessionError("invalid cognition event")
        self._sequence += 1
        event = {"sequence": self._sequence, "type": event_type, "session_id": self.session_id, "episode": self._episode}
        if payload:
            # Events contain semantic references only.  Coordinates, routes,
            # frames and arbitrary action payloads are deliberately excluded.
            event.update({key: value for key, value in payload.items() if key in {"count", "claim_ids", "question", "information_gain", "status", "explanation", "reason", "state", "action_name"}})
        self._events.append(event)
        self._events = self._events[-_MAX_EVENTS:]
        self._persist_events()
        claim_changes: list[dict[str, Any]] = []
        try:
            report = self.store.report()
            current_claims: dict[str, dict[str, Any]] = {}
            for group, claims in report.get("claims", {}).items():
                # The report also exposes an ``undetermined`` convenience
                # bucket; category buckets are the canonical one-per-id view.
                if group == "undetermined":
                    continue
                if not isinstance(claims, list):
                    continue
                for claim in claims:
                    if not isinstance(claim, Mapping) or type(claim.get("id")) is not str:
                        continue
                    if claim["id"] in current_claims:
                        continue
                    view = {
                        "id": claim["id"],
                        "kind": claim.get("kind"),
                        "subject": claim.get("subject"),
                        "claim": claim.get("claim"),
                        "reason": claim.get("reason"),
                        "falsifier": claim.get("falsifier"),
                        "context": claim.get("context"),
                        "status": claim.get("status"),
                        "confidence": claim.get("confidence"),
                        "evidence_count": claim.get("evidence_count", 0),
                        "support_count": claim.get("support_count", 0),
                        "counterexample_count": claim.get("counterexample_count", 0),
                        "next_test": claim.get("next_test"),
                    }
                    current_claims[claim["id"]] = view
                    if self._logged_claims.get(claim["id"]) != view:
                        claim_changes.append(view)
            self._logged_claims = current_claims
        except Exception:
            claim_changes = []
        # Operator-visible, body-free progress logging.  The durable event
        # file remains the source of truth; this stream makes a live run
        # diagnosable before its private summary is written.
        logged = dict(event)
        if claim_changes:
            # The live log is the complete operator record.  Transport
            # projections may be byte-bounded elsewhere, but this record must
            # not silently omit hypotheses when a proposal contains many.
            logged["claim_changes"] = claim_changes
        try:
            self._append_live_log(logged)
        except OSError as error:
            raise CognitionPersistenceError("cognition live log unavailable") from error
        print(
            "[p7-cognition] "
            + json.dumps(logged, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        for change in claim_changes:
            print(
                "[p7-cognition] hypothesis "
                + json.dumps(change, sort_keys=True, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )

    @property
    def live_log_path(self) -> Path:
        """Return the stable operator-facing JSONL cognition log path."""

        return self._live_log_path

    def _append_live_log(self, logged: Mapping[str, Any]) -> None:
        directory = self._live_log_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        with self._live_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(logged, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(self._live_log_path, 0o600)
        if not self._live_log_announced:
            print(
                "[p7-cognition] live-log "
                + json.dumps({"path": str(self._live_log_path), "session_id": self.session_id}, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
            self._live_log_announced = True

    def _persist_events(self) -> None:
        payload = json.dumps({"schema": "asterion.prime.p7-semantic-cognition-events/v1", "events": self._events}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        directory = self._event_path.parent
        descriptor = -1
        temporary = ""
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            descriptor, temporary = tempfile.mkstemp(prefix=".semantic-events-", dir=directory)
            with open(descriptor, "w", encoding="utf-8", closefd=True) as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._event_path)
            os.chmod(self._event_path, 0o600)
        except OSError:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                if temporary:
                    Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
            raise CognitionPersistenceError("cognition event persistence unavailable") from None

    def _require_observation(self, observation: Mapping[str, Any]) -> None:
        if not isinstance(observation, Mapping) or "frame" not in observation:
            raise CognitionSessionError("observation is unavailable")
        if type(observation.get("levels_completed")) is not int or type(observation.get("state")) is not str:
            raise CognitionSessionError("observation is unavailable")

    def start_episode(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        self._require_observation(observation)
        try:
            # Give every first observation a minimal semantic starting point.
            # These are high/medium-confidence questions only; the store keeps
            # them undetermined until an actual experiment supplies evidence.
            self.store.seed_bootstrap_claims()
        except CognitionError as exc:
            raise CognitionSessionError(str(exc)) from None
        self._episode += 1
        self._observation = dict(observation)
        self._before_digest = _digest(observation)
        self._state = "OBSERVE"
        self._pending = None
        self._episode_actions = 0
        self._analyzed = False
        self._emit("cognition.episode.started", {"state": self._state})
        # Semantic claims survive the session boundary in the exact
        # game/seed/level ledger. If that ledger already contains enough
        # confirmed knowledge, resume directly in solve testing so the next
        # run does not spend a fresh probe re-validating the same claims.
        if self._knowledge_ready():
            self._state = "READY"
            self._emit("cognition.ready_for_solve", {"state": self._state})
        return self.snapshot()

    def propose(self, proposal: Mapping[str, Any]) -> int:
        if self._observation is None or self._state not in {"OBSERVE", "ANALYZED", "SNAPSHOT", "READY"}:
            raise CognitionSessionError("proposal is not allowed")
        before = {
            claim["id"]: claim
            for values in self.store.report().get("claims", {}).values()
            if isinstance(values, list)
            for claim in values
            if isinstance(claim, Mapping)
        }
        try:
            count = self.store.propose(proposal)
        except CognitionError as exc:
            raise CognitionSessionError(str(exc)) from None
        self._state = "PROPOSE"
        self._emit("cognition.hypothesis.proposed", {"count": count})
        after = {
            claim["id"]: claim
            for values in self.store.report().get("claims", {}).values()
            if isinstance(values, list)
            for claim in values
            if isinstance(claim, Mapping)
        }
        updated = [
            claim_id for claim_id, claim in after.items()
            if claim_id in before and any(
                before[claim_id].get(field) != claim.get(field)
                for field in ("claim", "reason", "falsifier", "next_test", "confidence", "context")
            )
        ]
        if updated:
            self._emit("cognition.hypothesis.updated", {"claim_ids": sorted(updated), "count": len(updated)})
        return count

    def select_experiment(self, experiment: Mapping[str, Any]) -> dict[str, Any]:
        if self._observation is None or self._state not in {"OBSERVE", "PROPOSE", "ANALYZED", "SNAPSHOT", "READY"}:
            raise CognitionSessionError("experiment is not allowed")
        if not isinstance(experiment, Mapping):
            raise CognitionSessionError("experiment is unavailable")
        claim_ids = experiment.get("claim_ids")
        if not isinstance(claim_ids, Sequence) or isinstance(claim_ids, (str, bytes)) or not claim_ids:
            raise CognitionSessionError("experiment claim_ids are unavailable")
        report = self.store.report()
        known = {claim["id"] for claims in report["claims"].values() if isinstance(claims, list) for claim in claims}
        if any(type(item) is not str or item not in known for item in claim_ids):
            raise CognitionSessionError("experiment references an unknown claim")
        action = experiment.get("action")
        if not isinstance(action, Mapping) or type(action.get("name")) is not str or action["name"] == "RESET":
            raise CognitionSessionError("experiment action is unavailable")
        action_data = action.get("data", {})
        if not isinstance(action_data, Mapping) or any(type(key) is not str or type(value) is not int for key, value in action_data.items()):
            raise CognitionSessionError("experiment action data is unavailable")
        expected = experiment.get("expected")
        if not isinstance(expected, Mapping) or not expected:
            raise CognitionSessionError("experiment expected predicate is unavailable")
        try:
            encoded_expected = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            raise CognitionSessionError("experiment expected predicate is unavailable") from None
        if len(encoded_expected.encode("utf-8")) > _MAX_EXPECTED_BYTES:
            raise CognitionSessionError("experiment expected predicate is too large")
        if "frame_changed" in expected and type(expected["frame_changed"]) is not bool:
            raise CognitionSessionError("invalid frame predicate")
        if "levels_completed" in expected and type(expected["levels_completed"]) is not int:
            raise CognitionSessionError("invalid level predicate")
        if "state" in expected and (type(expected["state"]) is not str or expected["state"] not in _OBSERVED_STATES):
            raise CognitionSessionError("invalid state predicate")
        if "frame" in expected:
            expected = {"frame": _expected_frame(expected["frame"])}
        self._pending = {"claim_ids": tuple(claim_ids), "question": _text(experiment.get("question"), "question"), "information_gain": _text(experiment.get("information_gain"), "information_gain"), "action_name": action["name"], "action_data": tuple(sorted(action_data.items())), "expected": dict(expected), "before": self._before_digest, "episode": self._episode}
        self._state = "EXPERIMENT_SELECTED"
        self._analyzed = False
        self._emit("cognition.experiment.selected", self._pending)
        return {"state": self._state, "claim_ids": list(claim_ids), "action_name": action["name"], "execution_authority": "none"}

    def record_action(self, observation: Mapping[str, Any], *, action: Mapping[str, Any]) -> dict[str, Any]:
        if self._pending is None or self._state != "EXPERIMENT_SELECTED":
            raise CognitionSessionError("no selected experiment")
        self._require_observation(observation)
        if type(action.get("name")) is not str or action["name"] != self._pending["action_name"]:
            raise CognitionSessionError("action does not match experiment")
        actual_data = action.get("data", {})
        if not isinstance(actual_data, Mapping) or tuple(sorted(actual_data.items())) != self._pending["action_data"]:
            raise CognitionSessionError("action data does not match experiment")
        if self._episode_actions >= self.max_actions_per_episode:
            self.stop("episode-action-limit")
            raise CognitionSessionError("episode action limit")
        self._episode_actions += 1
        self._observation = dict(observation)
        after_digest = _digest(observation)
        self._state = "ACTION_EXECUTED"
        self._emit("cognition.action.executed", {"action_name": action["name"]})
        changed = after_digest != self._pending["before"]
        self._before_digest = after_digest
        return {"state": self._state, "changed": changed, "levels_completed": observation["levels_completed"]}

    def analyze(self, analysis: Mapping[str, Any]) -> dict[str, Any]:
        if self._pending is None or self._state != "ACTION_EXECUTED" or self._observation is None:
            raise CognitionSessionError("analysis is not allowed")
        if not isinstance(analysis, Mapping):
            raise CognitionSessionError("analysis is unavailable")
        if set(analysis) & {"action", "actions", "plan", "route", "command", "commands"}:
            raise CognitionSessionError("analysis cannot submit executable actions")
        results = analysis.get("results")
        if isinstance(results, Mapping):
            results = [results]
        # The cognition prompt asks the model to assess several hypotheses in
        # one observation.  Accept that semantic envelope explicitly and
        # normalize it into the durable per-claim result shape.  One probe may
        # therefore confirm or falsify multiple claims (for example, a moved
        # actor also supplies evidence about the space it entered).
        if results is None and "claim_assessments" in analysis:
            assessments = analysis.get("claim_assessments")
            if not isinstance(assessments, Sequence) or isinstance(assessments, (str, bytes)) or not assessments:
                raise CognitionSessionError("claim assessments are unavailable")
            normalized: list[dict[str, str]] = []
            for item in assessments:
                if not isinstance(item, Mapping):
                    raise CognitionSessionError("invalid claim assessment")
                claim_id = item.get("claim_id", item.get("id"))
                assessment = item.get("assessment", item.get("status", "undetermined"))
                if type(claim_id) is not str or type(assessment) is not str:
                    raise CognitionSessionError("invalid claim assessment")
                status = _normalize_analysis_status(assessment)
                explanation = item.get("reason", item.get("explanation", item.get("observation", "LLM analysis")))
                if not isinstance(explanation, str):
                    explanation = json.dumps(explanation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                normalized.append({"claim_id": claim_id, "status": status, "explanation": explanation})
            results = normalized
        if results is None:
            raw_ids = analysis.get("claim_ids", list(self._pending["claim_ids"]))
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)) or not raw_ids:
                raise CognitionSessionError("analysis claim_ids are unavailable")
            status = analysis.get("status")
            if status is None:
                status = analysis.get("result", analysis.get("outcome", "undetermined"))
            status = _normalize_analysis_status(status)
            detail_parts = []
            for key in ("interpretation", "assessment", "observation", "reason", "explanation", "outcome"):
                if key in analysis and analysis[key] is not None:
                    value = analysis[key]
                    if not isinstance(value, str):
                        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    detail_parts.append(f"{key}={value}")
            results = [{"claim_id": claim_id, "status": status, "explanation": "; ".join(detail_parts) or "LLM analysis"} for claim_id in raw_ids]
        if not isinstance(results, list) or not results:
            raise CognitionSessionError("analysis results are unavailable")
        allowed = set(self._pending["claim_ids"])
        normalized_results: list[dict[str, object]] = []
        seen_claim_ids: set[str] = set()
        for item in results:
            if not isinstance(item, Mapping) or type(item.get("claim_id")) is not str:
                raise CognitionSessionError("analysis references an unselected claim")
            claim_id = item["claim_id"]
            if claim_id not in allowed:
                raise CognitionSessionError("analysis references an unselected claim")
            if claim_id in seen_claim_ids:
                raise CognitionSessionError("analysis contains duplicate claim")
            seen_claim_ids.add(claim_id)
            normalized_results.append({
                "claim_id": claim_id,
                "status": _normalize_analysis_status(item.get("status", item.get("result"))),
                "explanation": _text(item.get("explanation"), "explanation"),
            })
        results = normalized_results
        evidence_ref = f"{self.session_id}/episode-{self._episode}/action-{self._episode_actions}"
        changed = _digest(self._observation) != self._pending["before"]
        predicate = self._pending["expected"]
        known_predicates = {"frame_changed", "levels_completed", "state", "frame"}
        is_known_predicate = len(predicate) == 1 and set(predicate).issubset(known_predicates)
        predicate_name = next(iter(predicate)) if is_known_predicate else "llm judgment"
        observed = None
        if is_known_predicate:
            observed = (
                changed if predicate_name == "frame_changed" else
                self._observation["levels_completed"] == predicate["levels_completed"] if predicate_name == "levels_completed" else
                self._observation["state"] == predicate["state"] if predicate_name == "state" else
                _expected_frame(self._observation["frame"]) == predicate["frame"]
            )
        report = self.store.report()
        claim_by_id = {
            claim["id"]: claim
            for values in report["claims"].values()
            if isinstance(values, list)
            for claim in values
        }
        resolutions: list[dict[str, str]] = []
        pending_events: list[tuple[str, str, str]] = []
        for item in results:
            status = item.get("status")
            explanation = item["explanation"]
            claim = claim_by_id.get(item["claim_id"])
            evidence_allowed = predicate_name == "llm judgment" or predicate_name == "frame"
            if predicate_name in {"levels_completed", "state"} and claim is not None:
                evidence_allowed = claim.get("kind") in {"success_condition", "rule"}
            evidence_explanation = (
                f"predicate={predicate_name}; observed={observed}; action_evidence={evidence_ref}; {explanation}"
            )
            if status == "certain":
                if (is_known_predicate and not observed) or not evidence_allowed:
                    pending_events.append(("cognition.hypothesis.remains_undetermined", item["claim_id"], explanation))
                    continue
                resolutions.append({"claim_id": item["claim_id"], "status": "certain", "evidence": evidence_ref, "explanation": evidence_explanation})
                pending_events.append(("cognition.hypothesis.confirmed", item["claim_id"], explanation))
            elif status == "falsified":
                if (is_known_predicate and observed) or not evidence_allowed:
                    pending_events.append(("cognition.hypothesis.remains_undetermined", item["claim_id"], explanation))
                    continue
                resolutions.append({"claim_id": item["claim_id"], "status": "falsified", "evidence": evidence_ref, "explanation": evidence_explanation})
                pending_events.append(("cognition.hypothesis.falsified", item["claim_id"], explanation))
            elif status == "undetermined":
                pending_events.append(("cognition.hypothesis.remains_undetermined", item["claim_id"], explanation))
            else:
                raise CognitionSessionError("invalid analysis status")
        try:
            self.store.resolve_many(resolutions)
        except CognitionError as exc:
            raise CognitionSessionError(str(exc)) from None
        for event_type, claim_id, explanation in pending_events:
            self._emit(event_type, {"claim_ids": [claim_id], "explanation": explanation})
        self._state = "ANALYZED"
        self._analyzed = True
        self._emit("cognition.observation.analyzed", {"state": self._state})
        return self.snapshot()

    def reset_episode(self) -> dict[str, Any]:
        if self._resets >= self.max_resets:
            self.stop("reset-limit")
            raise CognitionSessionError("reset limit")
        self._resets += 1
        self._pending = None
        self._before_digest = None
        self._observation = None
        self._episode_actions = 0
        self._analyzed = False
        self._state = "OBSERVE"
        self._emit("cognition.episode.reset", {"state": self._state})
        return self.snapshot()

    def ready_for_solve(self) -> dict[str, Any]:
        if not self._knowledge_ready():
            raise CognitionSessionError("cognition is not ready")
        self._state = "READY"
        self._emit("cognition.ready_for_solve", {"state": self._state})
        return self.snapshot()

    def _knowledge_ready(self) -> bool:
        """Return whether persisted semantics can safely start solve testing."""

        report = self.store.report()
        claims = [
            claim
            for values in report["claims"].values()
            if isinstance(values, list)
            for claim in values
            if isinstance(claim, Mapping)
        ]
        required_kinds = {
            "game_type",
            "object_role",
            "control",
            "success_condition",
            "strategy",
        }
        certain_kinds = {
            claim.get("kind")
            for claim in claims
            if claim.get("status") == "certain"
        }
        return required_kinds.issubset(certain_kinds)

    def stop(self, reason: str) -> dict[str, Any]:
        self._state = "STOPPED"
        self._emit("cognition.stopped", {"reason": _text(reason, "reason"), "state": self._state})
        return self.snapshot()

    def _validation_status(self) -> dict[str, Any]:
        """Describe whether another useful cognition experiment can run."""

        report = self.store.report()
        claims = [
            claim
            for values in report["claims"].values()
            if isinstance(values, list)
            for claim in values
            if isinstance(claim, Mapping)
        ]
        open_claims = [claim for claim in claims if claim.get("status") == "undetermined"]
        actionable = [
            claim["id"] for claim in open_claims
            if isinstance(claim.get("next_test"), str) and bool(claim["next_test"].strip())
        ]
        if self._knowledge_ready():
            return {"needed": False, "possible": False, "actionable_claim_ids": [], "reason": "knowledge-ready"}
        if self._state == "STOPPED":
            return {"needed": True, "possible": False, "actionable_claim_ids": actionable, "reason": "session-stopped"}
        if self._episode_actions >= self.max_actions_per_episode and self._resets >= self.max_resets:
            return {"needed": True, "possible": False, "actionable_claim_ids": actionable, "reason": "validation-budget-exhausted"}
        if not actionable:
            return {"needed": True, "possible": False, "actionable_claim_ids": [], "reason": "no-actionable-hypotheses"}
        return {"needed": True, "possible": True, "actionable_claim_ids": actionable, "reason": "actionable-hypotheses-remain"}

    def snapshot(self, *, emit_event: bool = True) -> dict[str, Any]:
        if type(emit_event) is not bool:
            raise CognitionSessionError("invalid snapshot mode")
        if emit_event:
            self._emit("cognition.snapshot", {"state": self._state})
        return {"state": self._state, "report": self.store.report(), "session": {"schema": "asterion.prime.p7-cognition-session/v1", "session_id": self.session_id, "episode": self._episode, "episode_actions": self._episode_actions, "resets": self._resets, "state": self._state, "pending": None if self._pending is None else {"claim_ids": list(self._pending["claim_ids"]), "question": self._pending["question"], "information_gain": self._pending["information_gain"], "action_name": self._pending["action_name"], "expected": dict(self._pending["expected"])}, "validation": self._validation_status()}, "events": list(self.events[-32:]), "execution_authority": "none"}


__all__ = ["CognitionPersistenceError", "CognitionSession", "CognitionSessionError"]
