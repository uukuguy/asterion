"""Provider-neutral continual-harness values and canonical identities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)
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


class HarnessTransportError(RuntimeError):
    """Marks transport loss after a durable harness effect start."""


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
    revision_id: str | None
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
            or (self.revision_id is not None and not _valid_id(self.revision_id))
            or not _nonnegative_int(self.sequence)
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


class HarnessEffectSender(Protocol):
    def __call__(self, proposal: HarnessProposal) -> HarnessEffectReceipt:
        """Apply one already admitted proposal and return a body-free receipt."""


class HarnessCancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool:
        """Return whether a new provider effect must not start."""


class HarnessPrivateRevisionStore(Protocol):
    """Host-private persistence for references forbidden from the journal."""

    def save_proposal(self, proposal: HarnessProposal) -> None:
        """Persist one exact proposal before its public journal record."""

    def load_proposal(self, proposal_digest: str) -> HarnessProposal:
        """Load an exact proposal by its canonical digest."""

    def save_snapshot(
        self,
        snapshot_id: str,
        entries: tuple[HarnessEntryDescriptor, ...],
    ) -> None:
        """Persist private descriptor references for one public snapshot."""

    def load_snapshot(self, snapshot_id: str) -> tuple[HarnessEntryDescriptor, ...]:
        """Load private descriptor references for one public snapshot."""


class MemoryHarnessPrivateRevisionStore:
    """In-memory reference store for injected host-private harness state."""

    def __init__(self) -> None:
        self._proposals: dict[str, HarnessProposal] = {}
        self._snapshots: dict[str, tuple[HarnessEntryDescriptor, ...]] = {}

    def save_proposal(self, proposal: HarnessProposal) -> None:
        if not isinstance(proposal, HarnessProposal):
            raise HarnessError("private revision proposal is invalid")
        existing = self._proposals.get(proposal.digest)
        if existing is not None and existing != proposal:
            raise HarnessError("private revision proposal conflicts")
        self._proposals[proposal.digest] = proposal

    def load_proposal(self, proposal_digest: str) -> HarnessProposal:
        try:
            return self._proposals[proposal_digest]
        except (KeyError, TypeError):
            raise HarnessError("private revision proposal is unavailable") from None

    def save_snapshot(
        self,
        snapshot_id: str,
        entries: tuple[HarnessEntryDescriptor, ...],
    ) -> None:
        if not _valid_id(snapshot_id) or any(
            not isinstance(item, HarnessEntryDescriptor) for item in entries
        ):
            raise HarnessError("private revision snapshot is invalid")
        copied = tuple(entries)
        existing = self._snapshots.get(snapshot_id)
        if existing is not None and existing != copied:
            raise HarnessError("private revision snapshot conflicts")
        self._snapshots[snapshot_id] = copied

    def load_snapshot(self, snapshot_id: str) -> tuple[HarnessEntryDescriptor, ...]:
        try:
            return self._snapshots[snapshot_id]
        except (KeyError, TypeError):
            raise HarnessError("private revision snapshot is unavailable") from None


class _NeverCancelled:
    cancelled = False


@dataclass(frozen=True)
class _PendingEffect:
    proposal: HarnessProposal
    revision_id: str
    sequence: int
    effect_digest: str
    rollback_revision_id: str | None


class HarnessCoordinator:
    """Own append-only harness revisions and persist before provider effects."""

    def __init__(
        self,
        journal: CanonicalJournal,
        scope: HarnessScope,
        effect_sender: HarnessEffectSender,
        cancellation_signal: HarnessCancellationSignal | None = None,
        private_store: HarnessPrivateRevisionStore | None = None,
    ) -> None:
        if (
            not isinstance(scope, HarnessScope)
            or not callable(effect_sender)
            or not isinstance(
                getattr(cancellation_signal or _NeverCancelled(), "cancelled", None),
                bool,
            )
        ):
            raise HarnessError("coordinator is invalid")
        self._journal = journal
        self._scope = scope
        self._effect_sender = effect_sender
        self._cancellation = cancellation_signal or _NeverCancelled()
        self._private_store = private_store or MemoryHarnessPrivateRevisionStore()
        self._history: list[HarnessRevision] = []
        self._admitted: _PendingEffect | None = None
        self._pending: _PendingEffect | None = None
        self._pending_activation: HarnessRevision | None = None
        self._snapshot = HarnessSnapshot(
            snapshot_id="snapshot-0",
            scope=scope,
            revision_id=None,
            sequence=0,
            entries=(),
            pending_status=None,
        )
        self._private_store.save_snapshot("snapshot-0", ())
        self._hydrate()

    def apply(self, proposal: HarnessProposal) -> HarnessRevision:
        return self._apply(proposal, rollback_revision_id=None)

    def rollback(
        self,
        *,
        proposal_id: str,
        authority_id: str,
        authority_revision: int,
        target_revision_id: str,
        rationale_ref: str,
        rationale_digest: str,
        expected_outcome_digest: str,
    ) -> HarnessRevision:
        target = next(
            (
                revision
                for revision in self._history
                if revision.revision_id == target_revision_id
            ),
            None,
        )
        if (
            target is None
            or target.status != "succeeded"
            or self._snapshot.revision_id != target_revision_id
            or target.scope != self._scope
        ):
            raise HarnessError("rollback is invalid")
        original = self._private_store.load_proposal(target.proposal_digest)
        before = {
            item.entry_id: item
            for item in self._private_store.load_snapshot(
                original.baseline_snapshot_id
            )
        }
        current = {item.entry_id: item for item in self._snapshot.entries}
        inverse: list[HarnessEdit] = []
        for edit in reversed(original.edits):
            if edit.action == "create":
                active = current.get(edit.entry_id)
                if active is None:
                    raise HarnessError("rollback conflicts with snapshot")
                inverse.append(
                    HarnessEdit.delete(
                        edit.entry_id,
                        expected_version=active.version,
                    )
                )
            elif edit.action == "update":
                active = current.get(edit.entry_id)
                prior = before.get(edit.entry_id)
                if active is None or prior is None:
                    raise HarnessError("rollback conflicts with snapshot")
                inverse.append(
                    HarnessEdit.update(
                        replace(prior, version=active.version + 1),
                        expected_version=active.version,
                    )
                )
            else:
                prior = before.get(edit.entry_id)
                if prior is None or edit.entry_id in current:
                    raise HarnessError("rollback conflicts with snapshot")
                inverse.append(HarnessEdit.create(replace(prior, version=1)))
        proposal = HarnessProposal(
            proposal_id=proposal_id,
            authority_id=authority_id,
            authority_revision=authority_revision,
            scope=self._scope,
            baseline_snapshot_id=self._snapshot.snapshot_id,
            edits=tuple(inverse),
            evidence_ids=original.evidence_ids,
            rationale_ref=rationale_ref,
            rationale_digest=rationale_digest,
            expected_outcome_digest=expected_outcome_digest,
        )
        return self._apply(proposal, rollback_revision_id=target_revision_id)

    def recover(self) -> HarnessSnapshot:
        if self._pending is not None:
            self._record_uncertain(self._pending)
        if self._pending_activation is not None:
            revision = self._pending_activation
            self._append(
                JournalRecord.harness_snapshot_activated(
                    scope=self._scope.to_mapping(),
                    revision_id=revision.revision_id,
                    sequence=revision.sequence,
                    snapshot_id=revision.result_snapshot_id,
                )
            )
            self._activate(revision)
        return self.snapshot()

    def snapshot(self) -> HarnessSnapshot:
        return self._snapshot

    def history(self) -> tuple[HarnessRevision, ...]:
        return tuple(self._history)

    def _apply(
        self,
        proposal: HarnessProposal,
        *,
        rollback_revision_id: str | None,
    ) -> HarnessRevision:
        self.recover()
        existing = next(
            (
                item
                for item in self._history
                if item.proposal_id == getattr(proposal, "proposal_id", None)
            ),
            None,
        )
        if existing is not None:
            if existing.proposal_digest != getattr(proposal, "digest", None):
                raise HarnessError("proposal replay conflicts")
            return existing
        admitted = self._admitted
        if admitted is not None and admitted.proposal.digest != getattr(
            proposal, "digest", None
        ):
            raise HarnessError("proposal replay conflicts")
        if (
            not isinstance(proposal, HarnessProposal)
            or proposal.scope != self._scope
            or proposal.baseline_snapshot_id != self._snapshot.snapshot_id
            or self._snapshot.pending_status is not None
            or not self._authority_matches(proposal)
        ):
            raise HarnessError("proposal conflicts with snapshot")
        result_entries = _apply_harness_edits(self._snapshot.entries, proposal.edits)
        if admitted is None:
            sequence = (self._history[-1].sequence if self._history else 0) + 1
            revision_id = _revision_id(self._scope, sequence, proposal.digest)
            effect_digest = harness_effect_digest(proposal)
            pending = _PendingEffect(
                proposal,
                revision_id,
                sequence,
                effect_digest,
                rollback_revision_id,
            )
            self._private_store.save_proposal(proposal)
            self._append(
                JournalRecord.harness_proposed(
                    scope=self._scope.to_mapping(),
                    proposal_id=proposal.proposal_id,
                    proposal_digest=proposal.digest,
                    authority_id=proposal.authority_id,
                    authority_revision=proposal.authority_revision,
                    baseline_snapshot_id=proposal.baseline_snapshot_id,
                    revision_id=revision_id,
                    sequence=sequence,
                    edit_count=len(proposal.edits),
                    evidence_count=len(proposal.evidence_ids),
                    rollback_revision_id=rollback_revision_id,
                )
            )
            self._admitted = pending
        else:
            pending = admitted
            sequence = pending.sequence
            revision_id = pending.revision_id
            effect_digest = pending.effect_digest
            if pending.rollback_revision_id != rollback_revision_id:
                raise HarnessError("proposal replay conflicts")
        self._append(
            JournalRecord.harness_effect_started(
                scope=self._scope.to_mapping(),
                proposal_id=proposal.proposal_id,
                proposal_digest=proposal.digest,
                revision_id=revision_id,
                sequence=sequence,
                effect_digest=effect_digest,
            )
        )
        self._admitted = None
        self._pending = pending
        if self._cancellation.cancelled:
            receipt = HarnessEffectReceipt.cancelled(
                proposal,
                effect_digest=effect_digest,
                result_entries=self._snapshot.entries,
            )
        else:
            try:
                receipt = self._effect_sender(proposal)
                self._validate_receipt(receipt, pending, result_entries)
            except HarnessTransportError:
                return self._record_uncertain(pending)
            except Exception:
                return self._record_uncertain(pending)
        if receipt.status == "uncertain":
            return self._record_uncertain(pending)
        snapshot_entries = result_entries if receipt.status == "succeeded" else self._snapshot.entries
        result_snapshot_id = (
            _snapshot_id(self._scope, sequence, snapshot_entries)
            if receipt.status == "succeeded"
            else self._snapshot.snapshot_id
        )
        self._private_store.save_snapshot(result_snapshot_id, snapshot_entries)
        revision = HarnessRevision(
            revision_id=revision_id,
            sequence=sequence,
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest,
            scope=self._scope,
            baseline_snapshot_id=proposal.baseline_snapshot_id,
            result_snapshot_id=result_snapshot_id,
            effect_digest=effect_digest,
            status=receipt.status,
            rollback_revision_id=rollback_revision_id,
            usage=receipt.usage,
        )
        self._append_terminal(revision, snapshot_entries)
        self._history.append(revision)
        self._pending = None
        self._admitted = None
        if revision.status == "succeeded":
            self._append(
                JournalRecord.harness_snapshot_activated(
                    scope=self._scope.to_mapping(),
                    revision_id=revision.revision_id,
                    sequence=revision.sequence,
                    snapshot_id=revision.result_snapshot_id,
                )
            )
            self._activate(revision)
        return revision

    def _validate_receipt(
        self,
        receipt: object,
        pending: _PendingEffect,
        expected_entries: tuple[HarnessEntryDescriptor, ...],
    ) -> None:
        if (
            not isinstance(receipt, HarnessEffectReceipt)
            or receipt.proposal_id != pending.proposal.proposal_id
            or receipt.proposal_digest != pending.proposal.digest
            or receipt.effect_digest != pending.effect_digest
            or (
                receipt.status == "succeeded"
                and receipt.result_entries != expected_entries
            )
            or (
                receipt.status in {"failed", "cancelled"}
                and receipt.result_entries not in {(), self._snapshot.entries}
            )
        ):
            raise HarnessError("effect receipt conflicts with proposal")

    def _append_terminal(
        self,
        revision: HarnessRevision,
        entries: tuple[HarnessEntryDescriptor, ...],
    ) -> None:
        self._append(
            JournalRecord.harness_effect_terminal(
                scope=self._scope.to_mapping(),
                proposal_id=revision.proposal_id,
                proposal_digest=revision.proposal_digest,
                revision_id=revision.revision_id,
                sequence=revision.sequence,
                effect_digest=revision.effect_digest,
                status=revision.status,
                result_snapshot_id=revision.result_snapshot_id,
                entries=tuple(item.to_public_mapping() for item in entries),
                usage=revision.usage,
            )
        )

    def _record_uncertain(self, pending: _PendingEffect) -> HarnessRevision:
        revision = HarnessRevision(
            revision_id=pending.revision_id,
            sequence=pending.sequence,
            proposal_id=pending.proposal.proposal_id,
            proposal_digest=pending.proposal.digest,
            scope=self._scope,
            baseline_snapshot_id=pending.proposal.baseline_snapshot_id,
            result_snapshot_id=self._snapshot.snapshot_id,
            effect_digest=pending.effect_digest,
            status="uncertain",
            rollback_revision_id=pending.rollback_revision_id,
            usage=_empty_usage(),
        )
        self._append(
            JournalRecord.harness_effect_uncertain(
                scope=self._scope.to_mapping(),
                proposal_id=revision.proposal_id,
                proposal_digest=revision.proposal_digest,
                revision_id=revision.revision_id,
                sequence=revision.sequence,
                effect_digest=revision.effect_digest,
            )
        )
        if not any(item.revision_id == revision.revision_id for item in self._history):
            self._history.append(revision)
        self._pending = None
        self._snapshot = replace(self._snapshot, pending_status="uncertain")
        return revision

    def _activate(self, revision: HarnessRevision) -> None:
        entries = self._private_store.load_snapshot(revision.result_snapshot_id)
        self._snapshot = HarnessSnapshot(
            snapshot_id=revision.result_snapshot_id,
            scope=self._scope,
            revision_id=revision.revision_id,
            sequence=revision.sequence,
            entries=entries,
            pending_status=None,
        )
        self._pending_activation = None

    def _append(self, record: JournalRecord) -> None:
        try:
            self._journal.append(self._journal.position, record)
        except JournalConflictError:
            raise HarnessError("harness journal conflicts") from None

    def _authority_matches(self, proposal: HarnessProposal) -> bool:
        authority_id: object = None
        authority_revision: object = None
        for entry in self._journal.replay(JournalCursor(0)):
            if entry.record.kind in {"authority.bound", "authority.revised"}:
                authority_id = entry.record.payload["authority_id"]
                authority_revision = entry.record.payload["authority_revision"]
        return (
            proposal.authority_id == authority_id
            and proposal.authority_revision == authority_revision
        )

    def _hydrate(self) -> None:
        records = tuple(
            entry.record
            for entry in self._journal.replay(JournalCursor(0))
            if entry.record.kind.startswith("harness.")
        )
        proposed: dict[str, Mapping[str, object]] = {}
        started: set[str] = set()
        completed: set[str] = set()
        expected_sequence = 1
        for record in records:
            payload = record.payload
            if payload["scope"] != self._scope.to_mapping():
                raise HarnessError("harness journal scope conflicts")
            revision_id = str(payload["revision_id"])
            if record.kind == "harness.proposed":
                if (
                    payload["sequence"] != expected_sequence
                    or revision_id in proposed
                    or self._admitted is not None
                    or self._pending is not None
                    or self._pending_activation is not None
                    or self._snapshot.pending_status is not None
                ):
                    raise HarnessError("harness journal sequence conflicts")
                proposed[revision_id] = payload
                proposal = self._private_store.load_proposal(
                    str(payload["proposal_digest"])
                )
                if (
                    proposal.proposal_id != payload["proposal_id"]
                    or proposal.scope != self._scope
                    or proposal.baseline_snapshot_id != payload["baseline_snapshot_id"]
                    or len(proposal.edits) != payload["edit_count"]
                    or len(proposal.evidence_ids) != payload["evidence_count"]
                ):
                    raise HarnessError("harness private proposal conflicts")
                self._admitted = _PendingEffect(
                    proposal=proposal,
                    revision_id=revision_id,
                    sequence=int(payload["sequence"]),
                    effect_digest=harness_effect_digest(proposal),
                    rollback_revision_id=(
                        None
                        if payload["rollback_revision_id"] is None
                        else str(payload["rollback_revision_id"])
                    ),
                )
                expected_sequence += 1
                continue
            source = proposed.get(revision_id)
            if source is None or any(
                payload[field] != source[field]
                for field in ("proposal_id", "proposal_digest", "sequence")
                if field in payload
            ):
                raise HarnessError("harness journal identity conflicts")
            proposal = self._private_store.load_proposal(str(source["proposal_digest"]))
            pending = _PendingEffect(
                proposal=proposal,
                revision_id=revision_id,
                sequence=int(source["sequence"]),
                effect_digest=harness_effect_digest(proposal),
                rollback_revision_id=(
                    None
                    if source["rollback_revision_id"] is None
                    else str(source["rollback_revision_id"])
                ),
            )
            if record.kind == "harness.effect-started":
                if revision_id in started or payload["effect_digest"] != pending.effect_digest:
                    raise HarnessError("harness journal effect conflicts")
                started.add(revision_id)
                self._admitted = None
                self._pending = pending
            elif record.kind == "harness.effect-uncertain":
                if revision_id not in started or revision_id in completed:
                    raise HarnessError("harness journal terminal conflicts")
                self._pending = pending
                self._record_uncertain_replay(pending)
                completed.add(revision_id)
            elif record.kind == "harness.effect-terminal":
                if revision_id not in started or revision_id in completed:
                    raise HarnessError("harness journal terminal conflicts")
                entries = self._private_store.load_snapshot(
                    str(payload["result_snapshot_id"])
                )
                if tuple(
                    dict(item.to_public_mapping()) for item in entries
                ) != tuple(dict(item) for item in payload["entries"]):
                    raise HarnessError("harness private snapshot conflicts")
                revision = HarnessRevision(
                    revision_id=revision_id,
                    sequence=int(source["sequence"]),
                    proposal_id=str(source["proposal_id"]),
                    proposal_digest=str(source["proposal_digest"]),
                    scope=self._scope,
                    baseline_snapshot_id=str(source["baseline_snapshot_id"]),
                    result_snapshot_id=str(payload["result_snapshot_id"]),
                    effect_digest=str(payload["effect_digest"]),
                    status=str(payload["status"]),
                    rollback_revision_id=pending.rollback_revision_id,
                    usage=payload["usage"],
                )
                self._history.append(revision)
                self._pending = None
                if revision.status == "succeeded":
                    self._pending_activation = revision
                completed.add(revision_id)
            elif record.kind == "harness.snapshot-activated":
                revision = next(
                    (item for item in self._history if item.revision_id == revision_id),
                    None,
                )
                if (
                    revision is None
                    or revision.status != "succeeded"
                    or payload["snapshot_id"] != revision.result_snapshot_id
                ):
                    raise HarnessError("harness journal activation conflicts")
                self._activate(revision)
        if self._pending is not None and self._pending.revision_id in completed:
            self._pending = None

    def _record_uncertain_replay(self, pending: _PendingEffect) -> None:
        revision = HarnessRevision(
            revision_id=pending.revision_id,
            sequence=pending.sequence,
            proposal_id=pending.proposal.proposal_id,
            proposal_digest=pending.proposal.digest,
            scope=self._scope,
            baseline_snapshot_id=pending.proposal.baseline_snapshot_id,
            result_snapshot_id=self._snapshot.snapshot_id,
            effect_digest=pending.effect_digest,
            status="uncertain",
            rollback_revision_id=pending.rollback_revision_id,
            usage=_empty_usage(),
        )
        self._history.append(revision)
        self._snapshot = replace(self._snapshot, pending_status="uncertain")
        self._pending = None


def harness_effect_digest(proposal: HarnessProposal) -> str:
    if not isinstance(proposal, HarnessProposal):
        raise HarnessError("effect identity is invalid")
    return hashlib.sha256(f"harness-effect:{proposal.digest}".encode("utf-8")).hexdigest()


def _revision_id(scope: HarnessScope, sequence: int, proposal_digest: str) -> str:
    source = f"{scope.digest}:{sequence}:{proposal_digest}".encode("utf-8")
    return "harness-revision-" + hashlib.sha256(source).hexdigest()[:32]


def _snapshot_id(
    scope: HarnessScope,
    sequence: int,
    entries: tuple[HarnessEntryDescriptor, ...],
) -> str:
    digest = _mapping_digest(
        {
            "entries": [item.to_public_mapping() for item in entries],
            "scope": scope.to_mapping(),
            "sequence": sequence,
        }
    )
    return "harness-snapshot-" + digest[:32]


def _apply_harness_edits(
    entries: tuple[HarnessEntryDescriptor, ...],
    edits: tuple[HarnessEdit, ...],
) -> tuple[HarnessEntryDescriptor, ...]:
    values = {item.entry_id: item for item in entries}
    for edit in edits:
        current = values.get(edit.entry_id)
        if edit.action == "create":
            if current is not None or edit.replacement is None:
                raise HarnessError("edit conflicts with snapshot")
            values[edit.entry_id] = edit.replacement
        elif edit.action == "update":
            if (
                current is None
                or current.version != edit.expected_version
                or edit.replacement is None
            ):
                raise HarnessError("edit conflicts with snapshot")
            values[edit.entry_id] = edit.replacement
        else:
            if current is None or current.version != edit.expected_version:
                raise HarnessError("edit conflicts with snapshot")
            del values[edit.entry_id]
    return tuple(values[key] for key in sorted(values))


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


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
