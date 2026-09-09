"""Public, neutral differential projections of sealed P7 traces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import cast

from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace

from .diagnostics import analyze_trace


_ACTION = re.compile(r"ACTION[1-7]\Z")
_DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_OUTCOME = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")


@dataclass(frozen=True, slots=True)
class DifferentialReport:
    schema: str
    left: Mapping[str, object]
    right: Mapping[str, object]
    deltas: Mapping[str, object]


def _safe_identity(identities: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = identities.get(name)
        if type(value) is str and re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", value):
            return value
    return None


def _safe_digest(payload: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if type(value) is str and _DIGEST.fullmatch(value):
            return value
    return None


def _normalise(entries: tuple[PrimeTraceEntry, ...]) -> Mapping[str, object]:
    entries = validate_trace(entries)
    diagnostics = analyze_trace(entries)
    identities = entries[0].identities if entries else {}
    actions: list[str] = []
    state_digests: list[str] = []
    hypothesis_markers = 0
    replan_markers = 0
    outcome: str | None = None
    for entry in entries:
        if entry.kind == "arc.action":
            action = entry.payload.get("action")
            if type(action) is str and _ACTION.fullmatch(action):
                actions.append(action)
            state = _safe_digest(entry.payload, "after_sha256", "after_state_digest")
            if state is not None:
                state_digests.append(state)
        if entry.kind.startswith("hypothesis."):
            hypothesis_markers += 1
        if entry.kind.startswith("replan.") or entry.kind == "session.replanned":
            replan_markers += 1
        if entry.kind in {"session.terminal", "arc.terminal"}:
            candidate = entry.payload.get("outcome")
            if type(candidate) is str and _OUTCOME.fullmatch(candidate):
                outcome = candidate
    failure_markers = tuple(
        name
        for name, present in (
            ("no-op", diagnostics.no_op_streak > 0),
            ("cycle", diagnostics.cycles > 0),
            ("death", diagnostics.deaths > 0),
            ("resource-loss", diagnostics.deaths > 0),
        )
        if present
    )
    return {
        "action_count": len(actions),
        "actions": tuple(actions),
        "entry_count": len(entries),
        "failure_markers": failure_markers,
        "hypothesis_markers": hypothesis_markers,
        "model_id": _safe_identity(identities, "model_id", "model"),
        "outcome": outcome,
        "reasoning_id": _safe_identity(identities, "reasoning_id", "reasoning"),
        "replan_markers": replan_markers,
        "state_digests": tuple(state_digests),
    }


def compare_runs(
    left: tuple[PrimeTraceEntry, ...], right: tuple[PrimeTraceEntry, ...]
) -> DifferentialReport:
    """Compare observations without deciding whether either run should have stopped."""

    left_summary = _normalise(left)
    right_summary = _normalise(right)
    deltas = {
        "action_count": cast(int, right_summary["action_count"]) - cast(int, left_summary["action_count"]),
        "actions_equal": right_summary["actions"] == left_summary["actions"],
        "hypothesis_markers": cast(int, right_summary["hypothesis_markers"])
        - cast(int, left_summary["hypothesis_markers"]),
        "model_identity_equal": right_summary["model_id"] == left_summary["model_id"],
        "outcome_equal": right_summary["outcome"] == left_summary["outcome"],
        "reasoning_identity_equal": right_summary["reasoning_id"] == left_summary["reasoning_id"],
        "replan_markers": cast(int, right_summary["replan_markers"])
        - cast(int, left_summary["replan_markers"]),
        "state_digests_equal": right_summary["state_digests"] == left_summary["state_digests"],
    }
    return DifferentialReport(
        schema="asterion.prime.p7-differential/v1",
        left=left_summary,
        right=right_summary,
        deltas=deltas,
    )


__all__ = ("DifferentialReport", "compare_runs")
