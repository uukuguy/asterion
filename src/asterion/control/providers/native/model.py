"""Immutable native controller journal values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlEvent
from asterion.control.protocol import (
    ACTION_RESOLUTIONS,
    CONTROL_EVENT_TYPES,
    IDENTIFIER,
    OPAQUE_ID,
    SEMANTIC_VERSION,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


NATIVE_JOURNAL_VERSION = "asterion.native-journal/v1"
NATIVE_RECORD_KINDS = frozenset(
    {
        "session.bound",
        "authority.synced",
        "command.committed",
        "turn.started",
        "turn.committed",
        "turn.recovery-required",
        "checkpoint.committed",
    }
)


@dataclass(frozen=True, repr=False)
class NativeRecord:
    record_id: str
    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_opaque_id(self.record_id, "native record identity")
        if self.kind not in NATIVE_RECORD_KINDS:
            raise ValueError("native record kind is invalid")
        if not isinstance(self.payload, Mapping):
            raise ValueError("native record payload is invalid")
        frozen = _freeze_mapping(self.payload)
        _assert_json_value(frozen, "native record payload")
        object.__setattr__(self, "payload", frozen)

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "record_id": self.record_id,
                "kind": self.kind,
                "payload": _json_value(self.payload),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def __repr__(self) -> str:
        return (
            f"NativeRecord(record_id={self.record_id!r}, "
            f"kind={self.kind!r}, digest={self.digest!r})"
        )


@dataclass(frozen=True, repr=False)
class NativeEntry:
    position: int
    previous_digest: str | None
    record: NativeRecord

    def __post_init__(self) -> None:
        _require_positive_integer(self.position, "native entry position")
        if self.previous_digest is not None:
            _require_sha256(self.previous_digest, "native entry predecessor")
        if not isinstance(self.record, NativeRecord):
            raise ValueError("native entry record is invalid")

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "position": self.position,
                "previous_digest": self.previous_digest,
                "record": {
                    "record_id": self.record.record_id,
                    "kind": self.record.kind,
                    "payload": _json_value(self.record.payload),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def __repr__(self) -> str:
        return (
            f"NativeEntry(position={self.position!r}, "
            f"previous_digest={self.previous_digest!r}, digest={self.digest!r})"
        )


@dataclass(frozen=True, repr=False)
class NativeEventDraft:
    type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.type not in CONTROL_EVENT_TYPES:
            raise ValueError("native event draft type is invalid")
        if not isinstance(self.payload, Mapping):
            raise ValueError("native event draft payload is invalid")
        frozen = _freeze_mapping(self.payload)
        _assert_json_value(frozen, "native event draft payload")
        object.__setattr__(self, "payload", frozen)

    def __repr__(self) -> str:
        return f"NativeEventDraft(type={self.type!r}, payload=<redacted>)"


@dataclass(frozen=True, repr=False)
class NativeInputReference:
    input_id: str
    delivery: str
    content_ref: str
    command_digest: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.input_id, "native input identity")
        if self.delivery not in {"direct", "steer", "follow_up"}:
            raise ValueError("native input delivery is invalid")
        _require_opaque_id(self.content_ref, "native input content reference")
        _require_sha256(self.command_digest, "native input command digest")

    def __repr__(self) -> str:
        return (
            f"NativeInputReference(input_id={self.input_id!r}, "
            f"delivery={self.delivery!r}, content_ref=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class NativeActionResultReference:
    action_id: str
    resolution: str
    reason_code: str
    receipt_ref: str | None
    command_digest: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.action_id, "native action result identity")
        if self.resolution not in ACTION_RESOLUTIONS:
            raise ValueError("native action result resolution is invalid")
        _require_identifier(self.reason_code, "native action result reason")
        if self.receipt_ref is not None:
            _require_opaque_id(self.receipt_ref, "native action result receipt")
        if self.resolution == "succeeded" and self.receipt_ref is None:
            raise ValueError("native succeeded action result receipt is missing")
        if self.resolution in {"admitted", "rejected"} and self.receipt_ref is not None:
            raise ValueError("native admission action result receipt is invalid")
        _require_sha256(self.command_digest, "native action result command digest")

    def __repr__(self) -> str:
        return (
            f"NativeActionResultReference(action_id={self.action_id!r}, "
            f"resolution={self.resolution!r}, receipt_ref=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class NativeTurnRequest:
    turn_id: str
    session_id: str
    generation: int
    authority_revision: int
    causal_command_ids: tuple[str, ...]
    inputs: tuple[NativeInputReference, ...]
    action_results: tuple[NativeActionResultReference, ...]
    budget: RemainingBudget

    def __post_init__(self) -> None:
        _require_opaque_id(self.turn_id, "native turn identity")
        _require_opaque_id(self.session_id, "native turn session")
        _require_positive_integer(self.generation, "native turn generation")
        _require_positive_integer(
            self.authority_revision, "native turn authority revision"
        )
        command_ids = tuple(self.causal_command_ids)
        if (
            any(
                not isinstance(item, str) or OPAQUE_ID.fullmatch(item) is None
                for item in command_ids
            )
            or not is_sorted_unique_scalar_strings(list(command_ids))
        ):
            raise ValueError("native turn causal commands are invalid")
        inputs = tuple(self.inputs)
        if any(not isinstance(item, NativeInputReference) for item in inputs):
            raise ValueError("native turn inputs are invalid")
        action_results = tuple(self.action_results)
        if any(
            not isinstance(item, NativeActionResultReference) for item in action_results
        ):
            raise ValueError("native turn action results are invalid")
        if not isinstance(self.budget, RemainingBudget):
            raise ValueError("native turn budget is invalid")
        object.__setattr__(self, "causal_command_ids", command_ids)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "action_results", action_results)

    def __repr__(self) -> str:
        return (
            f"NativeTurnRequest(turn_id={self.turn_id!r}, "
            f"session_id={self.session_id!r}, generation={self.generation!r})"
        )


@dataclass(frozen=True, repr=False)
class NativeTurnResult:
    turn_id: str
    events: tuple[NativeEventDraft, ...]
    usage: BudgetUsage

    def __post_init__(self) -> None:
        _require_opaque_id(self.turn_id, "native turn result identity")
        events = tuple(self.events)
        if any(not isinstance(item, NativeEventDraft) for item in events):
            raise ValueError("native turn result events are invalid")
        if not isinstance(self.usage, BudgetUsage):
            raise ValueError("native turn result usage is invalid")
        object.__setattr__(self, "events", events)

    def __repr__(self) -> str:
        return f"NativeTurnResult(turn_id={self.turn_id!r}, usage=<redacted>)"


@dataclass(frozen=True, repr=False)
class NativeCapsuleMetadata:
    capsule_id: str
    capsule_digest: str
    control_plane_id: str
    control_plane_version: str
    checkpoint_version: str
    covered_position: int
    covered_sequence: int
    storage_ref: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.capsule_id, "native capsule identity")
        _require_sha256(self.capsule_digest, "native capsule digest")
        _require_identifier(
            self.control_plane_id, "native capsule control plane identity"
        )
        _require_version(
            self.control_plane_version, "native capsule control plane version"
        )
        _require_version(self.checkpoint_version, "native capsule checkpoint version")
        _require_positive_integer(self.covered_position, "native capsule position")
        _require_positive_integer(self.covered_sequence, "native capsule sequence")
        _require_opaque_id(self.storage_ref, "native capsule storage reference")

    def __repr__(self) -> str:
        return (
            f"NativeCapsuleMetadata(capsule_id={self.capsule_id!r}, "
            f"capsule_digest={self.capsule_digest!r}, "
            f"covered_position={self.covered_position!r}, "
            f"covered_sequence={self.covered_sequence!r})"
        )


@dataclass(frozen=True)
class NativeControllerState:
    provider_id: str | None
    provider_version: str | None
    checkpoint_version: str | None
    system_id: str | None
    system_version: str | None
    session_id: str | None
    generation: int | None
    lifecycle: str
    goal_id: str | None
    goal_status: str | None
    authority_id: str | None
    authority_revision: int | None
    budget_authority_revision: int | None
    remaining_budget: RemainingBudget | None
    command_digests: Mapping[str, str]
    pending_inputs: tuple[NativeInputReference, ...]
    pending_action_results: tuple[NativeActionResultReference, ...]
    pending_turn: NativeTurnRequest | None
    committed_turn_digests: Mapping[str, str]
    recovery_required_turn_ids: tuple[str, ...]
    fenced_turn_ids: tuple[str, ...]
    action_statuses: Mapping[str, str]
    action_receipt_refs: Mapping[str, str | None]
    usage: BudgetUsage
    events: tuple[ControlEvent, ...]
    next_sequence: int
    checkpoint: NativeCapsuleMetadata | None
    terminal_event_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "command_digests", MappingProxyType(dict(self.command_digests))
        )
        object.__setattr__(
            self,
            "committed_turn_digests",
            MappingProxyType(dict(self.committed_turn_digests)),
        )
        object.__setattr__(
            self, "action_statuses", MappingProxyType(dict(self.action_statuses))
        )
        object.__setattr__(
            self,
            "action_receipt_refs",
            MappingProxyType(dict(self.action_receipt_refs)),
        )
        object.__setattr__(self, "pending_inputs", tuple(self.pending_inputs))
        object.__setattr__(
            self, "pending_action_results", tuple(self.pending_action_results)
        )
        object.__setattr__(
            self, "recovery_required_turn_ids", tuple(self.recovery_required_turn_ids)
        )
        object.__setattr__(self, "fenced_turn_ids", tuple(self.fenced_turn_ids))
        object.__setattr__(self, "events", tuple(self.events))

    @classmethod
    def empty(cls) -> NativeControllerState:
        return cls(
            provider_id=None,
            provider_version=None,
            checkpoint_version=None,
            system_id=None,
            system_version=None,
            session_id=None,
            generation=None,
            lifecycle="empty",
            goal_id=None,
            goal_status=None,
            authority_id=None,
            authority_revision=None,
            budget_authority_revision=None,
            remaining_budget=None,
            command_digests={},
            pending_inputs=(),
            pending_action_results=(),
            pending_turn=None,
            committed_turn_digests={},
            recovery_required_turn_ids=(),
            fenced_turn_ids=(),
            action_statuses={},
            action_receipt_refs={},
            usage=BudgetUsage.zero(),
            events=(),
            next_sequence=1,
            checkpoint=None,
            terminal_event_id=None,
        )


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not all(isinstance(key, str) for key in value):
        raise ValueError("native mapping keys are invalid")
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _assert_json_value(value: object, label: str) -> None:
    try:
        json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        raise ValueError(f"{label} is not canonical JSON") from None


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _require_opaque_id(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _require_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is invalid")


def _require_version(value: object, label: str) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} is invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} is invalid")
