"""Deterministic, passive P7 execution diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    no_op_streak: int
    repeated_action_streak: int
    cycles: int
    deaths: int
    actions_since_progress: int
    contradicted_hypotheses: int
    experiment_information_gain: tuple[float, ...]


def _string(payload: Mapping[str, object], name: str) -> str | None:
    value = payload.get(name)
    return value if type(value) is str else None


def _truth(payload: Mapping[str, object], *names: str) -> bool:
    return any(payload.get(name) is True for name in names)


def _transition_noop(payload: Mapping[str, object]) -> bool:
    before = _string(payload, "before_sha256") or _string(payload, "before_state_digest")
    after = _string(payload, "after_sha256") or _string(payload, "after_state_digest")
    return _truth(payload, "no_op", "noop") or (before is not None and before == after)


def _progress(payload: Mapping[str, object], previous_level: int | None) -> tuple[bool, int | None]:
    level = payload.get("levels_completed")
    valid_level = level if type(level) is int and not isinstance(level, bool) and level >= 0 else None
    return _truth(payload, "progress", "level_progress") or (
        valid_level is not None and previous_level is not None and valid_level > previous_level
    ), valid_level if valid_level is not None else previous_level


def analyze_trace(entries: tuple[PrimeTraceEntry, ...]) -> DiagnosticReport:
    """Read trace evidence only; this function has no execution-side callbacks."""

    entries = validate_trace(entries)
    transitions = tuple(entry for entry in entries if entry.kind == "arc.action")
    maximum_noop = 0
    current_noop = 0
    maximum_action = 0
    current_action = 0
    previous_action: str | None = None
    states: set[str] = set()
    cycles = 0
    deaths = 0
    actions_since_progress = 0
    previous_level: int | None = None
    information_gain: list[float] = []
    for transition in transitions:
        payload = transition.payload
        action = _string(payload, "action")
        if action is not None and action == previous_action:
            current_action += 1
        else:
            current_action = 1 if action is not None else 0
        previous_action = action
        maximum_action = max(maximum_action, current_action)

        if _transition_noop(payload):
            current_noop += 1
        else:
            current_noop = 0
        maximum_noop = max(maximum_noop, current_noop)

        before = _string(payload, "before_sha256") or _string(payload, "before_state_digest")
        after = _string(payload, "after_sha256") or _string(payload, "after_state_digest")
        if before is not None:
            states.add(before)
        if after is not None:
            if after in states and after != before:
                cycles += 1
            states.add(after)
        if _truth(payload, "death", "resource_reset", "resource_loss"):
            deaths += 1
        progressed, previous_level = _progress(payload, previous_level)
        actions_since_progress = 0 if progressed else actions_since_progress + 1

        declared_gain = payload.get("information_gain")
        if type(declared_gain) is int and not isinstance(declared_gain, bool) and 0 <= declared_gain <= 1:
            information_gain.append(float(declared_gain))
        elif type(declared_gain) is float and math.isfinite(declared_gain) and 0.0 <= declared_gain <= 1.0:
            information_gain.append(declared_gain)
        else:
            information_gain.append(1.0 if after is not None and after != before else 0.0)

    deaths += sum(
        entry.kind in {"arc.death", "arc.resource_reset", "arc.resource_loss"}
        for entry in entries
        if entry.kind != "arc.action"
    )
    contradicted = sum(
        entry.kind == "hypothesis.contradicted"
        or (
            entry.kind.startswith("hypothesis.")
            and (_string(entry.payload, "status") == "contradicted" or _string(entry.payload, "hypothesis_status") == "contradicted")
        )
        for entry in entries
    )
    return DiagnosticReport(
        no_op_streak=maximum_noop,
        repeated_action_streak=maximum_action,
        cycles=cycles,
        deaths=deaths,
        actions_since_progress=actions_since_progress,
        contradicted_hypotheses=contradicted,
        experiment_information_gain=tuple(information_gain),
    )


__all__ = ("DiagnosticReport", "analyze_trace")
