"""Canonical local P7 scoring and content-safe evidence digests."""

from __future__ import annotations

from hashlib import sha256
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Protocol

from .game import ArcGameContract, DEFAULT_GAME, P7GameSelection


P7_GAME_ID = DEFAULT_GAME.game_id
P7_SEED = DEFAULT_GAME.seed
P7_ACTION_CAP = DEFAULT_GAME.action_cap
_SIX_PLACES = Decimal("0.000001")


def partial_game_score(action_count: int | tuple[int, ...], game: P7GameSelection) -> str:
    """Cumulative bounded score for the selected local target level."""

    if type(game) is not P7GameSelection:
        raise ValueError("P7 score inputs are invalid")
    if type(action_count) is int and action_count > 0:
        action_counts = (action_count,)
    elif (
        type(action_count) is tuple
        and action_count
        and all(type(count) is int and count > 0 for count in action_count)
    ):
        action_counts = action_count
    else:
        raise ValueError("P7 score inputs are invalid")
    if len(action_counts) != game.target_level:
        raise ValueError("P7 score inputs are invalid")

    return _format_score(_cumulative_score(action_counts, game.baseline_actions, game.win_levels))


def _format_score(value: Decimal) -> str:
    return format(value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP), ".6f")


def _level_score(baseline: int, paid_actions: int) -> Decimal:
    return min(Decimal(115), (Decimal(baseline) / Decimal(paid_actions)) ** 2 * Decimal(100))


def _completion_cap(levels_completed: int, win_levels: int) -> Decimal:
    return Decimal(levels_completed * (levels_completed + 1)) / Decimal(win_levels * (win_levels + 1)) * 100


def _cumulative_score(action_counts: tuple[int, ...], baselines: tuple[int, ...], win_levels: int) -> Decimal:
    weight_sum = win_levels * (win_levels + 1) // 2
    weighted_score = sum((_level_score(baselines[index], count) * (index + 1)
                          for index, count in enumerate(action_counts)), Decimal(0))
    return min(weighted_score / Decimal(weight_sum), _completion_cap(len(action_counts), win_levels))


def score_planning_facts(game: P7GameSelection | ArcGameContract, transitions: Iterable[_TransitionEvidence],
                         *, primitive_actions: int, levels_completed: int) -> dict:
    """Read paid costs from the settled journal without creating scoring state.

    A dispatched but unsettled action remains charged in the surrounding budget;
    its unknown level/result cannot supply a made-up score or current-level count.
    """
    baselines = game.baseline_actions if type(game) is P7GameSelection else None
    facts = {
        "objective": {"levels": game.win_levels, "score": "100.000000"},
        "win_levels": game.win_levels,
        "score_system": "p7-local-receipt",
        "baseline_actions": list(baselines) if baselines is not None else None,
        "formula": {
            "level": "q_i=min(115,100*(b_i/a_i)^2)",
            "game": "min(sum(i*q_i)/W,100*sum(completed i)/W); W=N*(N+1)/2",
            "full_score_condition": "all N levels completed and sum(i*q_i)>=100*W",
        },
        "accounting_status": "unavailable",
        "completed_levels": None,
        "current_level": None,
        "full_game_score": None,
        "completed_score_cap": None,
    }
    counts = []
    previous_sequence = previous_completion = completed = 0
    for transition in transitions:
        if (type(transition.sequence) is not int or transition.sequence != previous_sequence + 1
                or type(transition.levels_completed) is not int
                or not completed <= transition.levels_completed <= completed + 1):
            return facts
        previous_sequence = transition.sequence
        if transition.levels_completed > completed:
            counts.append(previous_sequence - previous_completion)
            previous_completion = previous_sequence
            completed = transition.levels_completed
    if (type(primitive_actions) is not int or type(levels_completed) is not int
            or previous_sequence != primitive_actions or completed != levels_completed
            or not 0 <= completed <= game.win_levels):
        return facts
    facts.update(
        accounting_status="settled",
        completed_levels=[{"level": index + 1, "paid_actions": count,
                           "baseline": baselines[index] if baselines is not None else None,
                           "level_score": _format_score(_level_score(baselines[index], count))
                                          if baselines is not None else None}
                          for index, count in enumerate(counts)],
        current_level=({"level": completed + 1, "paid_actions": primitive_actions - previous_completion,
                        "baseline": baselines[completed] if baselines is not None else None}
                       if completed < game.win_levels else None),
        full_game_score=(_format_score(_cumulative_score(tuple(counts), baselines, game.win_levels))
                         if baselines is not None else None),
        completed_score_cap=_format_score(_completion_cap(completed, game.win_levels)),
    )
    return facts


def canonical_bytes(value: object) -> bytes:
    """Encode public evidence deterministically and reject non-JSON values."""

    try:
        return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    except (TypeError, ValueError):
        raise ValueError("P7 evidence is invalid") from None


def digest(value: object) -> str:
    return "sha256:" + sha256(canonical_bytes(value)).hexdigest()


class _TransitionEvidence(Protocol):
    @property
    def action(self) -> str: ...

    @property
    def after_sha256(self) -> str: ...

    @property
    def before_sha256(self) -> str: ...

    @property
    def levels_completed(self) -> int: ...

    @property
    def sequence(self) -> int: ...

    @property
    def data(self) -> tuple[tuple[str, int], ...]: ...


def replay_sha256(
    transitions: Iterable[_TransitionEvidence], *, terminal_reason: str, uncertain_action: object = None
) -> str:
    """Digest only primitive actions and state hashes, never observations themselves."""

    rows = []
    for transition in transitions:
        try:
            row = {
                    "action": transition.action,
                    "after_sha256": transition.after_sha256,
                    "before_sha256": transition.before_sha256,
                    "levels_completed": transition.levels_completed,
                    "sequence": transition.sequence,
                }
            if transition.data:
                row["data"] = dict(transition.data)
            rows.append(row)
        except AttributeError:
            raise ValueError("P7 evidence is invalid") from None
    if uncertain_action is not None:
        rows.append({"action": uncertain_action, "outcome": "uncertain"})
    return digest({"terminal_reason": terminal_reason, "transitions": rows})


__all__ = ("P7_ACTION_CAP", "P7_GAME_ID", "P7_SEED", "canonical_bytes", "digest", "partial_game_score", "replay_sha256", "score_planning_facts")
