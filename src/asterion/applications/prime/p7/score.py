"""Canonical, content-safe digests for one native P7 run."""

from __future__ import annotations

from hashlib import sha256
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Protocol

from .game import DEFAULT_GAME, P7GameSelection


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

    weight_sum = game.win_levels * (game.win_levels + 1) // 2
    completed_weight_sum = sum(range(1, len(action_counts) + 1))
    weighted_score = sum(
        min(
            Decimal(115),
            (Decimal(game.baseline_actions[index]) / Decimal(count)) ** 2
            * Decimal(100),
        )
        * Decimal(index + 1)
        for index, count in enumerate(action_counts)
    )
    score = min(
        weighted_score / Decimal(weight_sum),
        Decimal(completed_weight_sum) / Decimal(weight_sum) * Decimal(100),
    )
    return format(
        score.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP),
        ".6f",
    )


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


__all__ = ("P7_ACTION_CAP", "P7_GAME_ID", "P7_SEED", "canonical_bytes", "digest", "partial_game_score", "replay_sha256")
