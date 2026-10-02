"""Persistent semantic game cognition for the P7 exploration pipeline.

The store is the durable contract between cognition episodes.  It keeps
language-level hypotheses about one exact game level and deliberately has no
planner or execution authority.  An LLM may propose hypotheses, while only
the program may resolve them from recorded evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCHEMA = "asterion.prime.p7-semantic-cognition/v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_KINDS = (
    "game_type",
    "object_role",
    "control",
    "success_condition",
    "rule",
    "strategy",
)
_STATUSES = ("undetermined", "certain", "falsified")
_MAX_FILE_BYTES = 256 * 1024
_MAX_RECORDS = 128
_MAX_CLAIMS = 256
_MAX_EVIDENCE = 64
_MAX_TEXT = 2048

# Every fresh cognition episode starts with a small, program-seeded set of
# semantic questions.  These are intentionally hypotheses (rather than facts):
# seeing a frame and receiving primitive action names gives the learner a place
# to start, but does not identify object roles, action effects, or the goal.
# Keep this contract free of routes and coordinates so the bootstrap cannot
# smuggle a solution into the experience ledger.
_BOOTSTRAP_CLAIMS: tuple[dict[str, str | float], ...] = (
    {
        "id": "bootstrap-frame-semantics",
        "kind": "game_type",
        "subject": "initial-observation",
        "claim": "The initial observation depicts a game scene whose semantic elements are not yet identified.",
        "reason": "A frame is available at the start of a cognition episode, but its objects and rules are unknown.",
        "falsifier": "Repeated observations provide no stable game scene or cannot be interpreted as game state.",
        "next_test": "Inspect the initial frame and compare it with the frame after one controlled primitive action.",
        "confidence": 0.8,
    },
    {
        "id": "bootstrap-discrete-actions",
        "kind": "control",
        "subject": "primitive-action-interface",
        "claim": "The game can be investigated through discrete primitive actions whose effects are not yet known.",
        "reason": "The runtime exposes named primitive actions, while their meanings and effects still require testing.",
        "falsifier": "The available inputs are not discrete game actions or no action produces an observable game effect.",
        "next_test": "Select one primitive action and compare the resulting observation with the prior frame.",
        "confidence": 0.75,
    },
    {
        "id": "bootstrap-success-condition",
        "kind": "success_condition",
        "subject": "level-success",
        "claim": "The level's puzzle success condition is currently unknown.",
        "reason": "No puzzle-level completion cause has been observed at episode start.",
        "falsifier": "A known observable event already establishes how the puzzle reaches success.",
        "next_test": "Observe level and terminal signals while testing an information-bearing interaction.",
        "confidence": 0.95,
    },
)


class CognitionError(ValueError):
    """Raised when a cognition proposal or persisted contract is invalid."""


def _text(value: object, name: str, *, required: bool = True) -> str:
    if type(value) is not str:
        raise CognitionError(f"{name} must be text")
    if required and not value.strip():
        raise CognitionError(f"{name} must not be empty")
    if len(value) > _MAX_TEXT:
        raise CognitionError(f"{name} exceeds size cap")
    return value


def _id(value: object, name: str) -> str:
    value = _text(value, name)
    if _ID.fullmatch(value) is None:
        raise CognitionError(f"invalid {name}")
    return value


def _int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise CognitionError(f"invalid {name}")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _empty_state() -> dict[str, Any]:
    return {"schema": SCHEMA, "records": {}}


def _identity(game_id: str, seed: int, win_levels: int, level: int) -> tuple[str, dict[str, Any]]:
    game_id = _id(game_id, "game_id")
    seed = _int(seed, "seed")
    win_levels = _int(win_levels, "win_levels", minimum=1)
    level = _int(level, "level")
    if level >= win_levels:
        raise CognitionError("level must be below win_levels")
    identity = {
        "game_id": game_id,
        "seed": seed,
        "win_levels": win_levels,
        "level": level,
    }
    return f"{game_id}|{seed}|{win_levels}|{level}", identity


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _claim_view(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Return the public claim projection, including evidence counters."""

    evidence = claim.get("evidence", [])
    support_count = sum(item.get("status") == "certain" for item in evidence)
    counter_count = sum(item.get("status") == "falsified" for item in evidence)
    result = {
        "id": claim["id"],
        "kind": claim["kind"],
        "subject": claim["subject"],
        "claim": claim["claim"],
        "reason": claim["reason"],
        "falsifier": claim["falsifier"],
        "next_test": claim["next_test"],
        "confidence": claim.get("confidence", 0.5),
        "status": claim["status"],
        "evidence_count": len(evidence),
        "support_count": support_count,
        "counterexample_count": counter_count,
        "evidence": _copy(evidence),
    }
    if claim.get("context"):
        result["context"] = claim["context"]
    return result


class SemanticCognitionStore:
    """Bounded, atomic persistence for one exact game-level cognition ledger."""

    def __init__(
        self,
        root: Path,
        game_id: str,
        seed: int,
        win_levels: int,
        *,
        level: int,
    ) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise CognitionError("root must be an absolute path")
        key, identity = _identity(game_id, seed, win_levels, level)
        self._path = root / ".asterion-private" / "prime-p7-live" / "semantic-cognition.json"
        self._key = key
        self._identity = identity
        self._state = self._load()
        record = self._state["records"].get(key)
        if not isinstance(record, dict) or record.get("identity") != identity:
            record = {
                "identity": identity,
                "claims": {},
                "protocol": None,
            }
            self._state["records"][key] = record

    @property
    def path(self) -> Path:
        return self._path

    @property
    def identity(self) -> dict[str, Any]:
        return _copy(self._identity)

    def _load(self) -> dict[str, Any]:
        try:
            if not self._path.is_file() or self._path.stat().st_size > _MAX_FILE_BYTES:
                return _empty_state()
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
                return _empty_state()
            records = raw.get("records")
            if not isinstance(records, dict) or len(records) > _MAX_RECORDS:
                return _empty_state()
            # Keep only records with the narrow shape we write.  Invalid or
            # hand-edited persistence never grants authority or leaks data.
            clean: dict[str, Any] = {}
            for key, record in records.items():
                if type(key) is not str or not isinstance(record, dict):
                    continue
                identity = record.get("identity")
                claims = record.get("claims")
                if not isinstance(identity, dict) or not isinstance(claims, dict):
                    continue
                if set(identity) != {"game_id", "seed", "win_levels", "level"}:
                    continue
                try:
                    expected_key, expected_identity = _identity(
                        identity["game_id"], identity["seed"], identity["win_levels"], identity["level"]
                    )
                except CognitionError:
                    continue
                if key != expected_key or identity != expected_identity or len(claims) > _MAX_CLAIMS:
                    continue
                clean_claims: dict[str, Any] = {}
                for claim_id, claim in claims.items():
                    if type(claim_id) is not str or not isinstance(claim, dict):
                        continue
                    try:
                        normalized = self._normalize_claim(claim, require_undetermined=False)
                    except CognitionError:
                        continue
                    if normalized["id"] == claim_id:
                        clean_claims[claim_id] = normalized
                protocol = self._normalize_protocol(record.get("protocol"))
                clean[key] = {"identity": expected_identity, "claims": clean_claims, "protocol": protocol}
            return {"schema": SCHEMA, "records": clean}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return _empty_state()

    def _record(self) -> dict[str, Any]:
        return self._state["records"][self._key]

    def _persist(self) -> None:
        payload = _canonical(self._state)
        encoded = payload.encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise CognitionError("semantic cognition store exceeds size cap")
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".semantic-cognition-", dir=directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _normalize_claim(value: Mapping[str, Any], *, require_undetermined: bool) -> dict[str, Any]:
        allowed = {"id", "kind", "subject", "claim", "reason", "falsifier", "next_test", "context", "status", "evidence", "confidence"}
        unknown = set(value) - allowed
        if unknown:
            raise CognitionError(f"unsupported cognition fields: {sorted(unknown)!r}")
        claim_id = _id(value.get("id"), "claim id")
        kind = value.get("kind")
        if kind not in _KINDS:
            raise CognitionError("invalid cognition kind")
        status = value.get("status", "undetermined")
        if status not in _STATUSES or (require_undetermined and status != "undetermined"):
            raise CognitionError("LLM proposals must remain undetermined")
        confidence = value.get("confidence", 0.5)
        if type(confidence) not in (int, float) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise CognitionError("confidence must be a finite number between 0 and 1")
        result = {
            "id": claim_id,
            "kind": kind,
            "subject": _text(value.get("subject"), "subject"),
            "claim": _text(value.get("claim"), "claim"),
            "reason": _text(value.get("reason"), "reason"),
            "falsifier": _text(value.get("falsifier"), "falsifier"),
            "next_test": _text(value.get("next_test"), "next_test"),
            # Confidence ranks a hypothesis for attention; it never changes
            # the three-state evidence contract or grants execution authority.
            "confidence": float(confidence),
            "status": status,
            "evidence": [],
        }
        if "context" in value:
            result["context"] = _text(value["context"], "context", required=False)
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > _MAX_EVIDENCE:
            raise CognitionError("invalid cognition evidence")
        for item in evidence:
            if not isinstance(item, Mapping) or set(item) - {"reference", "explanation", "status"}:
                raise CognitionError("invalid cognition evidence entry")
            item_status = item.get("status")
            if item_status not in ("certain", "falsified"):
                raise CognitionError("invalid cognition evidence status")
            result["evidence"].append({
                "reference": _text(item.get("reference"), "evidence reference"),
                "explanation": _text(item.get("explanation"), "evidence explanation"),
                "status": item_status,
            })
        # A resolved claim is a program-owned conclusion.  Loading a hand
        # edited record must never turn a bare ``status`` field into
        # authority, and the evidence must actually support that conclusion.
        # An undetermined claim has no resolved evidence by definition.
        if status == "undetermined" and result["evidence"]:
            raise CognitionError("undetermined cognition claims cannot carry resolved evidence")
        if status in {"certain", "falsified"} and not any(
            item["status"] == status for item in result["evidence"]
        ):
            raise CognitionError("resolved cognition claims require matching evidence")
        return result

    @staticmethod
    def _normalize_protocol(value: object) -> dict[str, Any] | None:
        """Keep only the program-owned protocol completion observation."""

        if value is None:
            return None
        if not isinstance(value, Mapping):
            return None
        if set(value) - {"status", "claim", "subject", "level_completed", "evidence"}:
            return None
        if value.get("status") != "certain" or value.get("subject") != "protocol.level_completion":
            return None
        try:
            normalized: dict[str, Any] = {
                "status": "certain",
                "claim": _text(value.get("claim"), "protocol claim"),
                "subject": "protocol.level_completion",
                "evidence": [],
            }
            if "level_completed" in value:
                normalized["level_completed"] = _int(value["level_completed"], "level_completed")
            evidence = value.get("evidence", [])
            if not isinstance(evidence, list) or len(evidence) > _MAX_EVIDENCE:
                return None
            if not evidence:
                return None
            seen_references: set[str] = set()
            for item in evidence:
                if not isinstance(item, Mapping) or set(item) != {"reference", "explanation", "status"}:
                    return None
                if item.get("status") != "certain":
                    return None
                try:
                    reference = _text(item.get("reference"), "protocol evidence reference")
                    explanation = _text(item.get("explanation"), "protocol evidence explanation")
                except CognitionError:
                    return None
                # Protocol certainty can only be established by an observation
                # emitted by the runtime.  User supplied labels such as
                # ``manual`` or ``fake`` never grant protocol authority.
                if not reference.startswith("runtime.") or reference in seen_references:
                    return None
                seen_references.add(reference)
                normalized["evidence"].append({
                    "reference": reference,
                    "explanation": explanation,
                    "status": "certain",
                })
            return normalized
        except CognitionError:
            return None

    def propose(self, proposal: Mapping[str, Any]) -> int:
        """Accept LLM hypotheses; no proposal can grant certainty or authority."""

        if not isinstance(proposal, Mapping) or "claims" not in proposal:
            raise CognitionError("proposal must contain claims")
        claims = proposal["claims"]
        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            raise CognitionError("claims must be a sequence")
        record = self._record()
        if len(claims) + len(record["claims"]) > _MAX_CLAIMS:
            raise CognitionError("too many cognition claims")
        staged = _copy(record["claims"])
        accepted = 0
        updated = 0
        for item in claims:
            if not isinstance(item, Mapping):
                raise CognitionError("claim must be an object")
            if "evidence" in item:
                raise CognitionError("LLM proposals cannot supply evidence")
            normalized = self._normalize_claim(item, require_undetermined=True)
            claim_id = normalized["id"]
            existing = staged.get(claim_id)
            if existing is not None:
                if any(existing.get(field) != normalized.get(field) for field in ("kind", "subject")):
                    raise CognitionError("claim id is already bound to another claim")
                if existing.get("status") in {"certain", "falsified"}:
                    if any(existing.get(field) != normalized.get(field) for field in ("claim", "reason", "falsifier", "next_test", "confidence", "context")):
                        raise CognitionError("resolved cognition claims cannot be rewritten")
                    continue
                mutable = ("claim", "reason", "falsifier", "next_test", "confidence", "context")
                if any(existing.get(field) != normalized.get(field) for field in mutable):
                    for field in mutable:
                        if field in normalized:
                            existing[field] = normalized[field]
                    updated += 1
                continue
            staged[claim_id] = normalized
            accepted += 1
        if accepted or updated:
            record["claims"] = staged
            self._persist()
        return accepted + updated

    def seed_bootstrap_claims(self) -> int:
        """Seed the minimum unknown game model for a new cognition episode.

        The claims are persisted through the same LLM proposal validator, so
        they remain ``undetermined`` and cannot carry evidence or authority.
        Calling this for every episode is safe: stable claim ids make the
        operation idempotent, while any later evidence remains untouched.
        """

        record = self._record()
        missing: list[dict[str, str | float]] = []
        for claim in _BOOTSTRAP_CLAIMS:
            existing = record["claims"].get(claim["id"])
            if existing is None:
                missing.append(dict(claim))
                continue
            if any(
                existing.get(field) != claim[field]
                for field in ("kind", "subject", "claim", "reason", "falsifier", "next_test", "confidence")
            ):
                raise CognitionError("bootstrap claim id is already bound to another claim")
        if not missing:
            return 0
        return self.propose({"claims": missing})

    def resolve(self, claim_id: str, *, status: str, evidence: str, explanation: str) -> dict[str, Any]:
        """Resolve one hypothesis using program-owned evidence."""

        claim_id = _id(claim_id, "claim id")
        if status not in {"certain", "falsified"}:
            raise CognitionError("program resolution requires certain or falsified")
        evidence = _text(evidence, "evidence reference")
        explanation = _text(explanation, "evidence explanation")
        record = self._record()
        claim = record["claims"].get(claim_id)
        if not isinstance(claim, dict):
            raise CognitionError("unknown cognition claim")
        if claim.get("status") == "falsified" and status == "certain":
            raise CognitionError("falsified claims cannot be revived")
        if len(claim.get("evidence", [])) >= _MAX_EVIDENCE:
            raise CognitionError("claim evidence exceeds cap")
        if any(item.get("reference") == evidence for item in claim.get("evidence", [])):
            raise CognitionError("duplicate cognition evidence reference")
        claim.setdefault("evidence", []).append({
            "reference": evidence,
            "explanation": explanation,
            "status": status,
        })
        claim["status"] = status
        self._persist()
        return _claim_view(claim)

    def seed_protocol_claims(self, *, level_completed: int) -> None:
        """Record the runtime's protocol-level completion observation."""

        completed = _int(level_completed, "level_completed")
        record = self._record()
        protocol = record.get("protocol")
        if not isinstance(protocol, dict):
            protocol = {
                "status": "certain",
                "claim": "The runtime reports level completion through levels_completed.",
                "subject": "protocol.level_completion",
                "evidence": [],
            }
        protocol["evidence"] = list(protocol.get("evidence", []))[-(_MAX_EVIDENCE - 1):]
        reference = "runtime.levels_completed"
        if not any(item.get("reference") == reference for item in protocol["evidence"]):
            protocol["evidence"].append({
                "reference": reference,
                "explanation": f"The runtime reported levels_completed={completed}.",
                "status": "certain",
            })
        protocol["level_completed"] = max(int(protocol.get("level_completed", 0)), completed)
        record["protocol"] = protocol
        self._persist()

    def _context(self, claims: list[dict[str, Any]]) -> str:
        confirmed = [item["claim"] for item in claims if item["status"] == "certain"]
        open_claims = [item["claim"] for item in claims if item["status"] == "undetermined"]
        rejected = [item["claim"] for item in claims if item["status"] == "falsified"]
        pieces = [f"Semantic understanding for level {self._identity['level']} is being built."]
        if confirmed:
            pieces.append("Confirmed: " + "; ".join(confirmed[:4]) + ".")
        if open_claims:
            pieces.append("Open hypotheses: " + "; ".join(open_claims[:4]) + ".")
        if rejected:
            pieces.append("Rejected hypotheses: " + "; ".join(rejected[:4]) + ".")
        return " ".join(pieces)

    def report(self) -> dict[str, Any]:
        """Return the natural-language-friendly cognition contract."""

        record = self._record()
        views = [_claim_view(item) for item in record["claims"].values()]
        views.sort(key=lambda item: item["id"])
        by_kind = {kind: [item for item in views if item["kind"] == kind] for kind in _KINDS}
        by_status = {status: [item for item in views if item["status"] == status] for status in _STATUSES}
        protocol = _copy(record.get("protocol"))
        if protocol is None:
            protocol = {
                "status": "undetermined",
                "claim": "The runtime completion protocol has not been observed.",
                "subject": "protocol.level_completion",
                "evidence": [],
            }
        protocol["evidence_count"] = len(protocol.get("evidence", []))
        puzzle = by_kind["success_condition"]
        context = self._context(views)
        report: dict[str, Any] = {
            "schema": SCHEMA,
            "scope": _copy(self._identity),
            "execution_authority": "none",
            "context": context,
            "natural_language_context": context,
            "claims": {**by_kind, **by_status},
            "success_condition": {"protocol": protocol, "puzzle": puzzle},
            "evidence_counts": {
                "total": sum(item["evidence_count"] for item in views) + protocol["evidence_count"],
                "support": sum(item["support_count"] for item in views) + protocol["evidence_count"],
                "counterexample": sum(item["counterexample_count"] for item in views),
            },
        }
        for kind in _KINDS:
            if kind != "success_condition":
                report[kind] = by_kind[kind]
        return report


__all__ = ["CognitionError", "SCHEMA", "SemanticCognitionStore"]
