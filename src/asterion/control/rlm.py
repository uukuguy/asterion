"""Provider-neutral, public-safe native RLM child lifecycle ledger."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from asterion.control.authority import AuthorityEnvelope
from asterion.control.protocol import OPAQUE_ID


class RlmError(ValueError):
    """Raised for a known RLM lifecycle boundary failure."""


_DIGEST = frozenset("0123456789abcdef")
_TERMINAL = frozenset({"completed", "failed", "cancelled"})


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _DIGEST for character in value)
    )


@dataclass(frozen=True, repr=False)
class RlmChildBinding:
    """Public child identity; native Prime identities never enter this record."""

    child_id: str
    parent_session_id: str
    authority_revision: int
    proposal_digest: str
    depth: int
    model_selector_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.child_id, str)
            or OPAQUE_ID.fullmatch(self.child_id) is None
            or not isinstance(self.parent_session_id, str)
            or OPAQUE_ID.fullmatch(self.parent_session_id) is None
            or isinstance(self.authority_revision, bool)
            or not isinstance(self.authority_revision, int)
            or self.authority_revision < 1
            or not _digest(self.proposal_digest)
            or isinstance(self.depth, bool)
            or not isinstance(self.depth, int)
            or self.depth < 0
            or not _digest(self.model_selector_digest)
        ):
            raise RlmError("RLM child binding is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "child_id": self.child_id,
                "parent_session_id": self.parent_session_id,
                "authority_revision": self.authority_revision,
                "proposal_digest": self.proposal_digest,
                "depth": self.depth,
                "model_selector_digest": self.model_selector_digest,
            }
        )


@dataclass(frozen=True, repr=False)
class RlmChildStatus:
    child_id: str
    status: Literal[
        "admitted", "started", "completed", "failed", "cancelled", "uncertain"
    ]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.child_id, str)
            or OPAQUE_ID.fullmatch(self.child_id) is None
            or self.status
            not in {"admitted", "started", "completed", "failed", "cancelled", "uncertain"}
        ):
            raise RlmError("RLM child status is invalid")


@dataclass
class _ChildEntry:
    binding: RlmChildBinding
    native_identity: str | None
    status: RlmChildStatus


class RlmChildService:
    """Monotonic host ledger for native provider-owned RLM child effects."""

    def __init__(
        self, authority: AuthorityEnvelope, *, private_root: Path | None = None
    ) -> None:
        if not isinstance(authority, AuthorityEnvelope) or (
            private_root is not None and not isinstance(private_root, Path)
        ):
            raise RlmError("RLM authority is invalid")
        self._authority = authority
        self._entries: dict[str, _ChildEntry] = {}
        self._private_root = private_root
        if private_root is not None:
            self._load()

    def admit(self, binding: RlmChildBinding) -> RlmChildStatus:
        if not isinstance(binding, RlmChildBinding):
            raise RlmError("RLM child admission is invalid")
        if binding.authority_revision != self._authority.revision:
            raise RlmError("RLM child authority is invalid")
        if binding.depth > self._authority.max_recursion_depth:
            raise RlmError("RLM child depth is unavailable")
        if "rlm.child.spawn" not in self._authority.allowed_operations:
            raise RlmError("RLM child operation is unavailable")
        current = self._entries.get(binding.child_id)
        if current is not None:
            if current.status.status == "uncertain":
                raise RlmError("RLM child is fenced")
            if current.status.status in _TERMINAL:
                raise RlmError("RLM child is terminal")
            if current.binding != binding:
                raise RlmError("RLM child identity conflicts")
            return current.status
        if sum(entry.status.status in {"admitted", "started"} for entry in self._entries.values()) >= self._authority.max_concurrent_children:
            raise RlmError("RLM child concurrency is unavailable")
        status = RlmChildStatus(binding.child_id, "admitted")
        self._entries[binding.child_id] = _ChildEntry(binding, None, status)
        self._persist()
        return status

    def record_started(
        self, binding: RlmChildBinding, *, native_identity: str
    ) -> RlmChildStatus:
        if not _native_identity(native_identity):
            raise RlmError("RLM child identity conflicts")
        entry = self._require(binding, None)
        if entry.status.status == "uncertain":
            raise RlmError("RLM child is fenced")
        if entry.status.status in _TERMINAL:
            raise RlmError("RLM child is terminal")
        if entry.native_identity is None:
            entry.native_identity = native_identity
        elif entry.native_identity != native_identity:
            raise RlmError("RLM child identity conflicts")
        entry.status = RlmChildStatus(binding.child_id, "started")
        self._persist()
        return entry.status

    def record_terminal(
        self,
        binding: RlmChildBinding,
        *,
        status: Literal["completed", "failed", "cancelled"],
        native_identity: str | None = None,
    ) -> RlmChildStatus:
        entry = self._require(binding, native_identity)
        if entry.status.status == "uncertain":
            raise RlmError("RLM child is fenced")
        if entry.status.status in _TERMINAL:
            if entry.status.status == status:
                return entry.status
            raise RlmError("RLM child is terminal")
        entry.status = RlmChildStatus(binding.child_id, status)
        self._persist()
        return entry.status

    def record_uncertain(self, binding: RlmChildBinding) -> RlmChildStatus:
        entry = self._require(binding, None)
        if entry.status.status in _TERMINAL:
            raise RlmError("RLM child is terminal")
        entry.status = RlmChildStatus(binding.child_id, "uncertain")
        self._persist()
        return entry.status

    def status(self, child_id: str) -> RlmChildStatus:
        try:
            return self._entries[child_id].status
        except KeyError:
            raise RlmError("RLM child is unknown") from None

    def public_registry(self) -> tuple[RlmChildStatus, ...]:
        return tuple(self._entries[child_id].status for child_id in sorted(self._entries))

    def _require(
        self, binding: RlmChildBinding, native_identity: str | None
    ) -> _ChildEntry:
        if not isinstance(binding, RlmChildBinding):
            raise RlmError("RLM child binding is invalid")
        try:
            entry = self._entries[binding.child_id]
        except KeyError:
            raise RlmError("RLM child is unknown") from None
        if entry.binding != binding:
            raise RlmError("RLM child identity conflicts")
        if native_identity is not None and entry.native_identity != native_identity:
            raise RlmError("RLM child identity conflicts")
        return entry

    def _load(self) -> None:
        assert self._private_root is not None
        path = self._private_root / "rlm-ledger.json"
        try:
            if not path.exists():
                return
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or set(value) != {"children"}:
                raise ValueError
            children = value["children"]
            if not isinstance(children, list):
                raise ValueError
            for item in children:
                if not isinstance(item, dict) or set(item) != {
                    "binding", "native_identity", "status"
                }:
                    raise ValueError
                binding = RlmChildBinding(**item["binding"])
                native_identity = item["native_identity"]
                status = RlmChildStatus(**item["status"])
                if (
                    native_identity is not None
                    and not _native_identity(native_identity)
                ) or status.child_id != binding.child_id or (
                    status.status != "admitted" and native_identity is None
                ):
                    raise ValueError
                if status.status in {"admitted", "started"}:
                    status = RlmChildStatus(binding.child_id, "uncertain")
                self._entries[binding.child_id] = _ChildEntry(
                    binding, native_identity, status
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            raise RlmError("RLM child recovery is invalid") from None

    def _persist(self) -> None:
        if self._private_root is None:
            return
        try:
            self._private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self._private_root.is_symlink():
                raise OSError
            children = [
                {
                    "binding": dict(entry.binding.to_mapping()),
                    "native_identity": entry.native_identity,
                    "status": {"child_id": entry.status.child_id, "status": entry.status.status},
                }
                for _, entry in sorted(self._entries.items())
            ]
            temporary = tempfile.NamedTemporaryFile(
                dir=self._private_root, delete=False, mode="w", encoding="utf-8"
            )
            try:
                json.dump({"children": children}, temporary, sort_keys=True, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary.close()
                os.chmod(temporary.name, 0o600)
                os.replace(temporary.name, self._private_root / "rlm-ledger.json")
            finally:
                if not temporary.closed:
                    temporary.close()
                if os.path.exists(temporary.name):
                    os.unlink(temporary.name)
        except OSError:
            raise RlmError("RLM child persistence is unavailable") from None


def _native_identity(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 4096
