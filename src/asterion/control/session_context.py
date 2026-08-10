"""Closed provider-neutral contracts for persistent session context operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from asterion.control.protocol import IDENTIFIER, MEDIA_TYPE, OPAQUE_ID


SESSION_CONTEXT_PROTOCOL = "asterion.session-context/v1"
SESSION_CONTEXT_OPERATIONS = frozenset(
    {
        "session.attachment.bind",
        "session.branch.summarize",
        "session.clone",
        "session.compact",
        "session.continuation.delete",
        "session.continuation.resume",
        "session.describe",
        "session.fork",
        "session.label.set",
        "session.name.set",
        "session.tree.navigate",
        "session.tree.read",
    }
)
SESSION_CONTEXT_STATUSES = frozenset(
    {"succeeded", "rejected", "failed", "cancelled", "uncertain"}
)
SESSION_STATUS_CODES = frozenset(
    {
        "cancelled",
        "completed",
        "creating",
        "failed",
        "idle",
        "paused",
        "recovery-required",
        "running",
    }
)
SESSION_TREE_NODE_KINDS = frozenset(
    {"compaction", "custom", "input", "output", "summary", "system", "tool"}
)

_COMMAND_FIELDS = {
    "protocol", "command_id", "session_id", "generation",
    "authority_revision", "idempotency_key", "operation", "payload",
}
_RECEIPT_FIELDS = {
    "protocol", "receipt_id", "command_id", "session_id", "generation",
    "operation", "status", "reason_code", "payload",
}
_BUDGET_FIELDS = {
    "controller_tokens", "application_tokens", "child_tokens",
    "aggregate_tokens", "cost_micros", "deadline_ms",
}
_USAGE_FIELDS = _BUDGET_FIELDS - {"deadline_ms"}
MAX_SAFE_INTEGER = 9_007_199_254_740_991


class SessionContextProtocolError(ValueError):
    """Raised when a public session-context value is invalid."""


def validate_session_context_command(value: object) -> Mapping[str, object]:
    """Validate one closed host-to-provider command and return a snapshot."""

    command = _closed(value, _COMMAND_FIELDS, "session context command")
    _require_protocol(command)
    for field in ("command_id", "session_id", "idempotency_key"):
        _require_opaque(command.get(field), f"session context command {field}")
    _require_positive(command.get("generation"), "session context command generation")
    _require_positive(
        command.get("authority_revision"), "session context command authority revision"
    )
    operation = _require_operation(command.get("operation"))
    _validate_command_payload(operation, command.get("payload"))
    return _freeze_mapping(command)


def validate_session_context_receipt(value: object) -> Mapping[str, object]:
    """Validate one closed provider-to-host receipt and return a snapshot."""

    receipt = _closed(value, _RECEIPT_FIELDS, "session context receipt")
    _require_protocol(receipt)
    for field in ("receipt_id", "command_id", "session_id"):
        _require_opaque(receipt.get(field), f"session context receipt {field}")
    _require_positive(receipt.get("generation"), "session context receipt generation")
    operation = _require_operation(receipt.get("operation"))
    status = receipt.get("status")
    if not isinstance(status, str) or status not in SESSION_CONTEXT_STATUSES:
        raise SessionContextProtocolError("session context receipt status is invalid")
    _require_identifier(receipt.get("reason_code"), "session context receipt reason")
    payload = _closed(
        receipt.get("payload"), {"evidence_ref", "result"},
        "session context receipt payload",
    )
    evidence_ref = payload.get("evidence_ref")
    if evidence_ref is not None:
        _require_opaque(evidence_ref, "session context receipt evidence")
    result = payload.get("result")
    if status != "succeeded":
        if result is not None:
            raise SessionContextProtocolError("session context non-success result is invalid")
    else:
        _validate_success_result(operation, result)
    return _freeze_mapping(receipt)


@dataclass(frozen=True, repr=False)
class SessionContextCommand:
    """Immutable host-native session-context command."""

    command_id: str
    session_id: str
    generation: int
    authority_revision: int
    idempotency_key: str
    operation: str
    payload: Mapping[str, object]
    protocol: str = SESSION_CONTEXT_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_session_context_command(self._mapping())
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SessionContextCommand:
        snapshot = validate_session_context_command(value)
        payload = snapshot["payload"]
        generation = snapshot["generation"]
        authority_revision = snapshot["authority_revision"]
        assert isinstance(payload, Mapping)
        assert type(generation) is int
        assert type(authority_revision) is int
        return cls(
            protocol=str(snapshot["protocol"]),
            command_id=str(snapshot["command_id"]),
            session_id=str(snapshot["session_id"]),
            generation=generation,
            authority_revision=authority_revision,
            idempotency_key=str(snapshot["idempotency_key"]),
            operation=str(snapshot["operation"]),
            payload=payload,
        )

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol, "command_id": self.command_id,
            "session_id": self.session_id, "generation": self.generation,
            "authority_revision": self.authority_revision,
            "idempotency_key": self.idempotency_key,
            "operation": self.operation, "payload": _json_value(self.payload),
        }

    def to_mapping(self) -> Mapping[str, object]:
        value = self._mapping()
        validate_session_context_command(value)
        return value

    def __repr__(self) -> str:
        return (
            "SessionContextCommand("
            f"command_id={self.command_id!r}, operation={self.operation!r}, "
            "payload=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class SessionContextReceipt:
    """Immutable public-safe session-context receipt."""

    receipt_id: str
    command_id: str
    session_id: str
    generation: int
    operation: str
    status: str
    reason_code: str
    payload: Mapping[str, object]
    protocol: str = SESSION_CONTEXT_PROTOCOL

    def __post_init__(self) -> None:
        snapshot = validate_session_context_receipt(self._mapping())
        payload = snapshot["payload"]
        assert isinstance(payload, Mapping)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SessionContextReceipt:
        snapshot = validate_session_context_receipt(value)
        payload = snapshot["payload"]
        generation = snapshot["generation"]
        assert isinstance(payload, Mapping)
        assert type(generation) is int
        return cls(
            protocol=str(snapshot["protocol"]),
            receipt_id=str(snapshot["receipt_id"]),
            command_id=str(snapshot["command_id"]),
            session_id=str(snapshot["session_id"]),
            generation=generation,
            operation=str(snapshot["operation"]), status=str(snapshot["status"]),
            reason_code=str(snapshot["reason_code"]), payload=payload,
        )

    def _mapping(self) -> dict[str, object]:
        return {
            "protocol": self.protocol, "receipt_id": self.receipt_id,
            "command_id": self.command_id, "session_id": self.session_id,
            "generation": self.generation, "operation": self.operation,
            "status": self.status, "reason_code": self.reason_code,
            "payload": _json_value(self.payload),
        }

    def to_mapping(self) -> Mapping[str, object]:
        value = self._mapping()
        validate_session_context_receipt(value)
        return value

    def __repr__(self) -> str:
        return (
            "SessionContextReceipt("
            f"receipt_id={self.receipt_id!r}, operation={self.operation!r}, "
            f"status={self.status!r}, payload=<redacted>)"
        )


class SessionContextClient(Protocol):
    """Selected provider extension for closed session-context operations."""

    async def execute_session_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        """Execute one already admitted, durably recorded command."""
        ...

    async def cancel_session_context(self, command_id: str) -> None:
        """Request cancellation for one exact in-flight context command."""
        ...


def _validate_command_payload(operation: str, value: object) -> None:
    if operation == "session.describe":
        _closed(value, set(), "session describe payload")
        return
    if operation == "session.name.set":
        payload = _closed(value, {"name_ref"}, "session name payload")
        _require_opaque(payload.get("name_ref"), "session name reference")
        return
    if operation in {
        "session.clone", "session.continuation.delete",
        "session.continuation.resume", "session.tree.read",
    }:
        payload = _closed(value, {"continuation_id"}, f"{operation} payload")
        _require_opaque(payload.get("continuation_id"), f"{operation} continuation")
        return
    if operation == "session.tree.navigate":
        payload = _closed(
            value, {"continuation_id", "entry_id"}, "session tree navigate payload"
        )
        _require_continuation_entry(payload, operation)
        return
    if operation == "session.fork":
        payload = _closed(
            value, {"continuation_id", "entry_id", "position"},
            "session fork payload",
        )
        _require_continuation_entry(payload, operation)
        if payload.get("position") not in {"before", "at"}:
            raise SessionContextProtocolError("session fork position is invalid")
        return
    if operation in {"session.compact", "session.branch.summarize"}:
        fields = {"continuation_id", "instructions_ref", "budget"}
        if operation == "session.branch.summarize":
            fields.add("entry_id")
        payload = _closed(value, fields, f"{operation} payload")
        _require_opaque(payload.get("continuation_id"), f"{operation} continuation")
        if operation == "session.branch.summarize":
            _require_opaque(payload.get("entry_id"), f"{operation} entry")
        if payload.get("instructions_ref") is not None:
            _require_opaque(payload.get("instructions_ref"), f"{operation} instructions")
        _validate_budget(payload.get("budget"))
        return
    if operation == "session.label.set":
        payload = _closed(
            value, {"continuation_id", "entry_id", "label_ref"},
            "session label payload",
        )
        _require_continuation_entry(payload, operation)
        if payload.get("label_ref") is not None:
            _require_opaque(payload.get("label_ref"), "session label reference")
        return
    if operation == "session.attachment.bind":
        payload = _closed(
            value,
            {"input_id", "attachment_id", "body_ref", "media_type", "sha256", "size"},
            "session attachment payload",
        )
        for field in ("input_id", "attachment_id", "body_ref"):
            _require_opaque(payload.get(field), f"session attachment {field}")
        _require_media_type(payload.get("media_type"), "session attachment media type")
        _require_sha256(payload.get("sha256"), "session attachment digest")
        _require_nonnegative(payload.get("size"), "session attachment size")
        return
    raise SessionContextProtocolError("session context command operation is invalid")


def _validate_success_result(operation: str, value: object) -> None:
    if operation == "session.describe":
        result = _closed(
            value,
            {"continuation_id", "status", "context_tokens", "turns", "usage", "name_sha256"},
            "session describe result",
        )
        _require_opaque(result.get("continuation_id"), "session describe continuation")
        if result.get("status") not in SESSION_STATUS_CODES:
            raise SessionContextProtocolError("session describe status is invalid")
        _require_nonnegative(result.get("context_tokens"), "session describe context tokens")
        _require_nonnegative(result.get("turns"), "session describe turns")
        _validate_usage(result.get("usage"))
        _require_nullable_sha256(result.get("name_sha256"), "session describe name digest")
        return
    if operation == "session.name.set":
        result = _closed(value, {"continuation_id", "name_sha256"}, "session name result")
        _require_opaque(result.get("continuation_id"), "session name continuation")
        _require_sha256(result.get("name_sha256"), "session name digest")
        return
    if operation == "session.continuation.resume":
        result = _closed(
            value,
            {"previous_continuation_id", "current_continuation_id", "transition_sha256"},
            "session continuation resume result",
        )
        _require_transition(result)
        return
    if operation == "session.continuation.delete":
        result = _closed(
            value, {"continuation_id", "deletion_sha256"},
            "session continuation delete result",
        )
        _require_opaque(result.get("continuation_id"), "session delete continuation")
        _require_sha256(result.get("deletion_sha256"), "session deletion digest")
        return
    if operation == "session.tree.read":
        result = _closed(value, {"continuation_id", "nodes", "leaf_id"}, "session tree result")
        _require_opaque(result.get("continuation_id"), "session tree continuation")
        _validate_tree(result.get("nodes"), result.get("leaf_id"))
        return
    if operation == "session.tree.navigate":
        result = _closed(
            value,
            {"continuation_id", "previous_leaf_id", "current_leaf_id", "transition_sha256"},
            "session tree navigate result",
        )
        _require_opaque(result.get("continuation_id"), "session tree continuation")
        _require_nullable_opaque(result.get("previous_leaf_id"), "session tree previous leaf")
        _require_opaque(result.get("current_leaf_id"), "session tree current leaf")
        _require_sha256(result.get("transition_sha256"), "session tree transition")
        return
    if operation in {"session.fork", "session.clone"}:
        result = _closed(
            value,
            {"source_continuation_id", "new_continuation_id", "active_leaf_id", "transition_sha256"},
            f"{operation} result",
        )
        _require_transition(result)
        _require_nullable_opaque(result.get("active_leaf_id"), f"{operation} active leaf")
        return
    if operation == "session.compact":
        result = _closed(
            value,
            {"continuation_id", "covered_leaf_id", "before_context_tokens",
             "after_context_tokens", "summary_sha256", "usage"},
            "session compact result",
        )
        _require_opaque(result.get("continuation_id"), "session compact continuation")
        _require_opaque(result.get("covered_leaf_id"), "session compact covered leaf")
        _require_nonnegative(result.get("before_context_tokens"), "session compact before tokens")
        _require_nonnegative(result.get("after_context_tokens"), "session compact after tokens")
        _require_sha256(result.get("summary_sha256"), "session compact summary digest")
        _validate_usage(result.get("usage"))
        return
    if operation == "session.branch.summarize":
        result = _closed(
            value,
            {"continuation_id", "previous_leaf_id", "current_leaf_id", "summary_sha256", "usage"},
            "session branch summary result",
        )
        _require_opaque(result.get("continuation_id"), "session branch continuation")
        _require_nullable_opaque(result.get("previous_leaf_id"), "session branch previous leaf")
        _require_opaque(result.get("current_leaf_id"), "session branch current leaf")
        _require_sha256(result.get("summary_sha256"), "session branch summary digest")
        _validate_usage(result.get("usage"))
        return
    if operation == "session.label.set":
        result = _closed(value, {"continuation_id", "entry_id", "label_sha256"}, "session label result")
        _require_continuation_entry(result, operation)
        _require_nullable_sha256(result.get("label_sha256"), "session label digest")
        return
    if operation == "session.attachment.bind":
        result = _closed(
            value, {"input_id", "attachment_id", "media_type", "sha256", "size"},
            "session attachment result",
        )
        for field in ("input_id", "attachment_id"):
            _require_opaque(result.get(field), f"session attachment {field}")
        _require_media_type(result.get("media_type"), "session attachment media type")
        _require_sha256(result.get("sha256"), "session attachment digest")
        _require_nonnegative(result.get("size"), "session attachment size")
        return
    raise SessionContextProtocolError("session context receipt operation is invalid")


def _validate_tree(nodes_value: object, leaf_id: object) -> None:
    if not isinstance(nodes_value, list):
        raise SessionContextProtocolError("session tree nodes are invalid")
    entry_ids: list[str] = []
    parents: dict[str, str | None] = {}
    for value in nodes_value:
        node = _closed(
            value, {"entry_id", "parent_id", "kind", "label_sha256", "token_count"},
            "session tree node",
        )
        entry_id = node.get("entry_id")
        _require_opaque(entry_id, "session tree entry")
        assert isinstance(entry_id, str)
        parent_id = node.get("parent_id")
        if parent_id is not None:
            _require_opaque(parent_id, "session tree parent")
            assert isinstance(parent_id, str)
        if node.get("kind") not in SESSION_TREE_NODE_KINDS:
            raise SessionContextProtocolError("session tree node kind is invalid")
        _require_nullable_sha256(node.get("label_sha256"), "session tree label digest")
        _require_nonnegative(node.get("token_count"), "session tree token count")
        entry_ids.append(entry_id)
        parents[entry_id] = parent_id
    if entry_ids != sorted(set(entry_ids)):
        raise SessionContextProtocolError("session tree node identities are invalid")
    if entry_ids:
        if sum(parent is None for parent in parents.values()) != 1:
            raise SessionContextProtocolError("session tree roots are invalid")
        for entry_id in entry_ids:
            visited: set[str] = set()
            current: str | None = entry_id
            while current is not None:
                if current in visited or current not in parents:
                    raise SessionContextProtocolError("session tree parent is invalid")
                visited.add(current)
                current = parents[current]
    if leaf_id is None:
        if entry_ids:
            raise SessionContextProtocolError("session tree leaf is invalid")
    else:
        _require_opaque(leaf_id, "session tree leaf")
        if leaf_id not in parents:
            raise SessionContextProtocolError("session tree leaf is invalid")


def _validate_budget(value: object) -> None:
    budget = _closed(value, _BUDGET_FIELDS, "session context budget")
    for field in _BUDGET_FIELDS - {"deadline_ms"}:
        _require_nonnegative(budget.get(field), f"session context budget {field}")
    _require_positive(budget.get("deadline_ms"), "session context budget deadline")


def _validate_usage(value: object) -> None:
    usage = _closed(value, _USAGE_FIELDS, "session context usage")
    for field in _USAGE_FIELDS:
        _require_nonnegative(usage.get(field), f"session context usage {field}")


def _require_transition(value: Mapping[str, object]) -> None:
    if "source_continuation_id" in value:
        left, right = "source_continuation_id", "new_continuation_id"
    else:
        left, right = "previous_continuation_id", "current_continuation_id"
    _require_opaque(value.get(left), "session transition source")
    _require_opaque(value.get(right), "session transition target")
    _require_sha256(value.get("transition_sha256"), "session transition digest")


def _require_continuation_entry(value: Mapping[str, object], label: str) -> None:
    _require_opaque(value.get("continuation_id"), f"{label} continuation")
    _require_opaque(value.get("entry_id"), f"{label} entry")


def _require_operation(value: object) -> str:
    if not isinstance(value, str) or value not in SESSION_CONTEXT_OPERATIONS:
        raise SessionContextProtocolError("session context operation is invalid")
    return value


def _require_protocol(value: Mapping[str, object]) -> None:
    if value.get("protocol") != SESSION_CONTEXT_PROTOCOL:
        raise SessionContextProtocolError("session context protocol is invalid")


def _closed(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != fields
    ):
        raise SessionContextProtocolError(f"{label} fields are invalid")
    return value


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise SessionContextProtocolError(f"{label} is invalid")


def _require_opaque(value: object, label: str) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise SessionContextProtocolError(f"{label} is invalid")


def _require_nullable_opaque(value: object, label: str) -> None:
    if value is not None:
        _require_opaque(value, label)


def _require_positive(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_INTEGER
    ):
        raise SessionContextProtocolError(f"{label} is invalid")


def _require_nonnegative(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SAFE_INTEGER
    ):
        raise SessionContextProtocolError(f"{label} is invalid")


def _require_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str) or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SessionContextProtocolError(f"{label} is invalid")


def _require_nullable_sha256(value: object, label: str) -> None:
    if value is not None:
        _require_sha256(value, label)


def _require_media_type(value: object, label: str) -> None:
    if not isinstance(value, str) or MEDIA_TYPE.fullmatch(value) is None:
        raise SessionContextProtocolError(f"{label} is invalid")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
