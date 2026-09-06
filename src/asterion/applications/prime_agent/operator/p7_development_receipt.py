"""Frozen, redacted receipt for one finite P7 development episode."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Final, Literal

from .p7_development_workload import (
    P7_DEVELOPMENT_MODEL_DIGEST, P7_DEVELOPMENT_ORACLE_DIGEST,
    P7_DEVELOPMENT_RESOURCE_DIGEST, P7_DEVELOPMENT_SCHEMA_DIGEST,
    P7_DEVELOPMENT_WORKLOAD_DIGEST,
)


_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")


class P7DevelopmentReceiptError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 development receipt is invalid")


@dataclass(frozen=True, repr=False)
class P7DevelopmentReceipt:
    workload_sha256: str
    schema_sha256: str
    model_sha256: str
    oracle_sha256: str
    resource_sha256: str
    runtime_environment_sha256: str
    run_sha256: str
    session_sha256: str
    container_sha256: str
    image_sha256: str
    initial_observation_sha256: str
    action_chain_sha256: str
    terminal_sha256: str
    score_sha256: str
    replay_sha256: str
    usage_sha256: str
    broker_sha256: str
    cleanup_sha256: str
    tool_names: tuple[str, ...]
    game_count: int
    action_count: int
    broker_call_count: int
    observation_count: int
    status_count: int
    prompt_count: int
    provider_callback_count: int
    ipython_call_count: int
    terminal_reason: Literal["action-limit", "engine-terminal"]
    episode_closed: bool
    score_replayed: bool
    broker_quiescent: bool
    worker_destroyed: bool
    full_cleanup: bool

    def __repr__(self) -> str:
        return "P7DevelopmentReceipt(redacted)"


_FIELDS: Final = frozenset(P7DevelopmentReceipt.__dataclass_fields__)
_DIGEST_FIELDS: Final = tuple(name for name in _FIELDS if name.endswith("_sha256"))
_EXACT_COUNTS: Final = {"game_count": 1, "observation_count": 1, "status_count": 1, "prompt_count": 3, "provider_callback_count": 6, "ipython_call_count": 3}


def validate_p7_development_receipt(receipt: object) -> None:
    if (
        type(receipt) is not P7DevelopmentReceipt
        or frozenset(vars(receipt)) != _FIELDS
        or any(type(getattr(receipt, name)) is not str or _DIGEST.fullmatch(getattr(receipt, name)) is None for name in _DIGEST_FIELDS)
        or (receipt.workload_sha256, receipt.schema_sha256, receipt.model_sha256, receipt.oracle_sha256, receipt.resource_sha256) != (P7_DEVELOPMENT_WORKLOAD_DIGEST, P7_DEVELOPMENT_SCHEMA_DIGEST, P7_DEVELOPMENT_MODEL_DIGEST, P7_DEVELOPMENT_ORACLE_DIGEST, P7_DEVELOPMENT_RESOURCE_DIGEST)
        or receipt.tool_names != ("ipython",)
        or any(type(getattr(receipt, name)) is not int or getattr(receipt, name) != expected for name, expected in _EXACT_COUNTS.items())
        or type(receipt.action_count) is not int or not 1 <= receipt.action_count <= 4
        or type(receipt.broker_call_count) is not int or receipt.broker_call_count != receipt.action_count + 2
        or receipt.terminal_reason not in {"action-limit", "engine-terminal"}
        or receipt.terminal_reason == "action-limit" and receipt.action_count != 4
        or any(getattr(receipt, name) is not True for name in ("episode_closed", "score_replayed", "broker_quiescent", "worker_destroyed", "full_cleanup"))
    ):
        raise P7DevelopmentReceiptError()


def p7_development_public_trace_digest(receipt: object) -> str:
    """Return the sole public trace projection; the receipt remains opaque."""

    validate_p7_development_receipt(receipt)
    values = dict(vars(receipt))
    values["tool_names"] = list(receipt.tool_names)
    return "sha256:" + sha256(json.dumps({"format": "asterion.prime-p7-development-public-trace/v1", "receipt": values}, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


__all__ = ("P7DevelopmentReceipt", "P7DevelopmentReceiptError", "p7_development_public_trace_digest", "validate_p7_development_receipt")
