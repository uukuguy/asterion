"""Canonical, content-safe digests for one native P7 run."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Protocol


P7_GAME_ID = "ls20-9607627b"
P7_SEED = 0
P7_ACTION_CAP = 500


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


def replay_sha256(
    transitions: Iterable[_TransitionEvidence], *, terminal_reason: str, uncertain_action: object = None
) -> str:
    """Digest only primitive actions and state hashes, never observations themselves."""

    rows = []
    for transition in transitions:
        try:
            rows.append(
                {
                    "action": transition.action,
                    "after_sha256": transition.after_sha256,
                    "before_sha256": transition.before_sha256,
                    "levels_completed": transition.levels_completed,
                    "sequence": transition.sequence,
                }
            )
        except AttributeError:
            raise ValueError("P7 evidence is invalid") from None
    if uncertain_action is not None:
        rows.append({"action": uncertain_action, "outcome": "uncertain"})
    return digest({"terminal_reason": terminal_reason, "transitions": rows})


__all__ = ("P7_ACTION_CAP", "P7_GAME_ID", "P7_SEED", "canonical_bytes", "digest", "replay_sha256")
