"""Provider-neutral continual-harness values and canonical identities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from asterion.control.protocol import OPAQUE_ID


HarnessScopeKind = Literal["session", "project", "global"]
HarnessEntryKind = Literal["prompt", "memory", "skill", "subagent"]
HarnessEditAction = Literal["create", "update", "delete"]
HarnessTerminalStatus = Literal["succeeded", "failed", "cancelled", "uncertain"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_KINDS = frozenset({"prompt", "memory", "skill", "subagent"})
_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "uncertain"}
)
_USAGE_FIELDS = frozenset(
    {
        "aggregate_tokens",
        "cost_micros",
        "model_credential_reads",
        "provider_operations",
    }
)


class HarnessError(ValueError):
    """Raised when a continual-harness value is invalid."""


@dataclass(frozen=True)
class HarnessScope:
    kind: HarnessScopeKind
    scope_id: str | None

    def __post_init__(self) -> None:
        if self.kind in {"session", "project"}:
            valid = _valid_id(self.scope_id)
        elif self.kind == "global":
            valid = self.scope_id is None
        else:
            valid = False
        if not valid:
            raise HarnessError("scope is invalid")

    @classmethod
    def session(cls, scope_id: str) -> HarnessScope:
        return cls("session", scope_id)

    @classmethod
    def project(cls, scope_id: str) -> HarnessScope:
        return cls("project", scope_id)

    @classmethod
    def global_scope(cls) -> HarnessScope:
        return cls("global", None)

    @property
    def key(self) -> str:
        if self.kind == "global":
            return "global"
        return f"{self.kind}:{self.scope_id}"

    @property
    def digest(self) -> str:
        return _mapping_digest(self.to_mapping())

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType({"kind": self.kind, "scope_id": self.scope_id})


@dataclass(frozen=True, repr=False)
class HarnessEntryDescriptor:
    entry_id: str
    kind: HarnessEntryKind
    title_digest: str
    body_ref: str
    body_digest: str
    grouping_path_digest: str | None
    metadata_digest: str
    version: int

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.entry_id)
            or self.kind not in _ENTRY_KINDS
            or not _valid_digest(self.title_digest)
            or not _valid_id(self.body_ref)
            or not _valid_digest(self.body_digest)
            or (
                self.grouping_path_digest is not None
                and not _valid_digest(self.grouping_path_digest)
            )
            or not _valid_digest(self.metadata_digest)
            or not _positive_int(self.version)
        ):
            raise HarnessError("entry descriptor is invalid")

    def __repr__(self) -> str:
        return (
            "HarnessEntryDescriptor("
            f"entry_id={self.entry_id!r}, kind={self.kind!r}, "
            f"body_digest={self.body_digest!r}, version={self.version})"
        )

    def to_public_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "body_digest": self.body_digest,
                "entry_id": self.entry_id,
                "grouping_path_digest": self.grouping_path_digest,
                "kind": self.kind,
                "metadata_digest": self.metadata_digest,
                "title_digest": self.title_digest,
                "version": self.version,
            }
        )


@dataclass(frozen=True)
class HarnessEdit:
    action: HarnessEditAction
    entry_id: str
    expected_version: int | None
    replacement: HarnessEntryDescriptor | None

    def __post_init__(self) -> None:
        if not _valid_id(self.entry_id):
            raise HarnessError("edit is invalid")
        if self.action == "create":
            valid = (
                self.expected_version is None
                and isinstance(self.replacement, HarnessEntryDescriptor)
                and self.replacement.entry_id == self.entry_id
                and self.replacement.version == 1
            )
        elif self.action == "update":
            valid = (
                _positive_int(self.expected_version)
                and isinstance(self.replacement, HarnessEntryDescriptor)
                and self.replacement.entry_id == self.entry_id
                and self.replacement.version == self.expected_version + 1
            )
        elif self.action == "delete":
            valid = _positive_int(self.expected_version) and self.replacement is None
        else:
            valid = False
        if not valid:
            raise HarnessError("edit is invalid")

    @classmethod
    def create(cls, replacement: HarnessEntryDescriptor) -> HarnessEdit:
        if not isinstance(replacement, HarnessEntryDescriptor):
            raise HarnessError("edit is invalid")
        return cls("create", replacement.entry_id, None, replacement)

    @classmethod
    def update(
        cls,
        replacement: HarnessEntryDescriptor,
        *,
        expected_version: int,
    ) -> HarnessEdit:
        if not isinstance(replacement, HarnessEntryDescriptor):
            raise HarnessError("edit is invalid")
        return cls("update", replacement.entry_id, expected_version, replacement)

    @classmethod
    def delete(cls, entry_id: str, *, expected_version: int) -> HarnessEdit:
        return cls("delete", entry_id, expected_version, None)

    def to_public_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "action": self.action,
                "entry_id": self.entry_id,
                "expected_version": self.expected_version,
                "replacement": (
                    None
                    if self.replacement is None
                    else self.replacement.to_public_mapping()
                ),
            }
        )


@dataclass(frozen=True, repr=False)
class HarnessProposal:
    proposal_id: str
    authority_id: str
    authority_revision: int
    scope: HarnessScope
    baseline_snapshot_id: str
    edits: tuple[HarnessEdit, ...]
    evidence_ids: tuple[str, ...]
    rationale_ref: str
    rationale_digest: str
    expected_outcome_digest: str

    def __post_init__(self) -> None:
        try:
            edits = tuple(self.edits)
            evidence_ids = tuple(self.evidence_ids)
        except TypeError:
            raise HarnessError("proposal is invalid") from None
        if (
            not _valid_id(self.proposal_id)
            or not _valid_id(self.authority_id)
            or not _positive_int(self.authority_revision)
            or not isinstance(self.scope, HarnessScope)
            or not _valid_id(self.baseline_snapshot_id)
            or not edits
            or any(not isinstance(item, HarnessEdit) for item in edits)
            or len({item.entry_id for item in edits}) != len(edits)
            or not evidence_ids
            or not _sorted_unique_ids(evidence_ids)
            or not _valid_id(self.rationale_ref)
            or not _valid_digest(self.rationale_digest)
            or not _valid_digest(self.expected_outcome_digest)
        ):
            raise HarnessError("proposal is invalid")
        object.__setattr__(self, "edits", edits)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def __repr__(self) -> str:
        return (
            "HarnessProposal("
            f"proposal_id={self.proposal_id!r}, authority_id={self.authority_id!r}, "
            f"authority_revision={self.authority_revision}, scope={self.scope!r}, "
            f"baseline_snapshot_id={self.baseline_snapshot_id!r}, "
            f"edit_count={len(self.edits)}, evidence_count={len(self.evidence_ids)}, "
            f"digest={self.digest!r})"
        )

    @property
    def digest(self) -> str:
        return _mapping_digest(
            {
                "authority_id": self.authority_id,
                "authority_revision": self.authority_revision,
                "baseline_snapshot_id": self.baseline_snapshot_id,
                "edits": [dict(item.to_public_mapping()) for item in self.edits],
                "evidence_ids": list(self.evidence_ids),
                "expected_outcome_digest": self.expected_outcome_digest,
                "proposal_id": self.proposal_id,
                "rationale_digest": self.rationale_digest,
                "scope": dict(self.scope.to_mapping()),
            }
        )


@dataclass(frozen=True)
class HarnessRevision:
    revision_id: str
    sequence: int
    proposal_id: str
    proposal_digest: str
    scope: HarnessScope
    baseline_snapshot_id: str
    result_snapshot_id: str
    effect_digest: str
    status: HarnessTerminalStatus
    rollback_revision_id: str | None
    usage: Mapping[str, int]

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.revision_id)
            or not _positive_int(self.sequence)
            or not _valid_id(self.proposal_id)
            or not _valid_digest(self.proposal_digest)
            or not isinstance(self.scope, HarnessScope)
            or not _valid_id(self.baseline_snapshot_id)
            or not _valid_id(self.result_snapshot_id)
            or not _valid_digest(self.effect_digest)
            or self.status not in _TERMINAL_STATUSES
            or (
                self.rollback_revision_id is not None
                and not _valid_id(self.rollback_revision_id)
            )
        ):
            raise HarnessError("revision is invalid")
        object.__setattr__(self, "usage", _freeze_usage(self.usage, "revision"))


@dataclass(frozen=True)
class HarnessSnapshot:
    snapshot_id: str
    scope: HarnessScope
    revision_id: str
    sequence: int
    entries: tuple[HarnessEntryDescriptor, ...]
    pending_status: Literal["uncertain"] | None

    def __post_init__(self) -> None:
        try:
            entries = tuple(sorted(self.entries, key=lambda item: item.entry_id))
        except (AttributeError, TypeError):
            raise HarnessError("snapshot is invalid") from None
        if (
            not _valid_id(self.snapshot_id)
            or not isinstance(self.scope, HarnessScope)
            or not _valid_id(self.revision_id)
            or not _positive_int(self.sequence)
            or any(not isinstance(item, HarnessEntryDescriptor) for item in entries)
            or len({item.entry_id for item in entries}) != len(entries)
            or self.pending_status not in {None, "uncertain"}
        ):
            raise HarnessError("snapshot is invalid")
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True, repr=False)
class HarnessEffectReceipt:
    proposal_id: str
    proposal_digest: str
    effect_digest: str
    status: HarnessTerminalStatus
    result_entries: tuple[HarnessEntryDescriptor, ...]
    usage: Mapping[str, int]

    def __post_init__(self) -> None:
        try:
            entries = tuple(sorted(self.result_entries, key=lambda item: item.entry_id))
        except (AttributeError, TypeError):
            raise HarnessError("effect receipt is invalid") from None
        if (
            not _valid_id(self.proposal_id)
            or not _valid_digest(self.proposal_digest)
            or not _valid_digest(self.effect_digest)
            or self.status not in _TERMINAL_STATUSES
            or any(not isinstance(item, HarnessEntryDescriptor) for item in entries)
            or len({item.entry_id for item in entries}) != len(entries)
        ):
            raise HarnessError("effect receipt is invalid")
        object.__setattr__(self, "result_entries", entries)
        object.__setattr__(self, "usage", _freeze_usage(self.usage, "effect receipt"))

    def __repr__(self) -> str:
        return (
            "HarnessEffectReceipt("
            f"proposal_id={self.proposal_id!r}, proposal_digest={self.proposal_digest!r}, "
            f"effect_digest={self.effect_digest!r}, status={self.status!r}, "
            f"result_count={len(self.result_entries)}, usage={dict(self.usage)!r})"
        )

    @classmethod
    def succeeded(
        cls,
        proposal: HarnessProposal,
        *,
        effect_digest: str,
        result_entries: Sequence[HarnessEntryDescriptor] = (),
        usage: Mapping[str, int] | None = None,
    ) -> HarnessEffectReceipt:
        return cls._from_proposal(
            proposal,
            effect_digest=effect_digest,
            status="succeeded",
            result_entries=result_entries,
            usage=usage,
        )

    @classmethod
    def failed(
        cls,
        proposal: HarnessProposal,
        *,
        effect_digest: str,
        result_entries: Sequence[HarnessEntryDescriptor] = (),
        usage: Mapping[str, int] | None = None,
    ) -> HarnessEffectReceipt:
        return cls._from_proposal(
            proposal,
            effect_digest=effect_digest,
            status="failed",
            result_entries=result_entries,
            usage=usage,
        )

    @classmethod
    def cancelled(
        cls,
        proposal: HarnessProposal,
        *,
        effect_digest: str,
        result_entries: Sequence[HarnessEntryDescriptor] = (),
        usage: Mapping[str, int] | None = None,
    ) -> HarnessEffectReceipt:
        return cls._from_proposal(
            proposal,
            effect_digest=effect_digest,
            status="cancelled",
            result_entries=result_entries,
            usage=usage,
        )

    @classmethod
    def uncertain(
        cls,
        proposal: HarnessProposal,
        *,
        effect_digest: str,
        result_entries: Sequence[HarnessEntryDescriptor] = (),
        usage: Mapping[str, int] | None = None,
    ) -> HarnessEffectReceipt:
        return cls._from_proposal(
            proposal,
            effect_digest=effect_digest,
            status="uncertain",
            result_entries=result_entries,
            usage=usage,
        )

    @classmethod
    def _from_proposal(
        cls,
        proposal: HarnessProposal,
        *,
        effect_digest: str,
        status: HarnessTerminalStatus,
        result_entries: Sequence[HarnessEntryDescriptor],
        usage: Mapping[str, int] | None,
    ) -> HarnessEffectReceipt:
        if not isinstance(proposal, HarnessProposal):
            raise HarnessError("effect receipt is invalid")
        return cls(
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest,
            effect_digest=effect_digest,
            status=status,
            result_entries=tuple(result_entries),
            usage=_empty_usage() if usage is None else usage,
        )


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _sorted_unique_ids(values: tuple[object, ...]) -> bool:
    return (
        all(_valid_id(value) for value in values)
        and values == tuple(sorted(set(values)))
    )


def _empty_usage() -> dict[str, int]:
    return {key: 0 for key in sorted(_USAGE_FIELDS)}


def _freeze_usage(value: object, label: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping) or set(value) != _USAGE_FIELDS:
        raise HarnessError(f"{label} is invalid")
    copied = dict(value)
    if any(
        not isinstance(key, str)
        or isinstance(item, bool)
        or not isinstance(item, int)
        or item < 0
        for key, item in copied.items()
    ):
        raise HarnessError(f"{label} is invalid")
    return MappingProxyType(copied)


def _mapping_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
