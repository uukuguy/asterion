"""Selected-Prime translation for admitted continual-harness effects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.control.harness import (
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessSnapshot,
    HarnessTransportError,
    harness_effect_digest,
)
from asterion.control.protocol import OPAQUE_ID


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BASE_PROMPT_IDENTITIES = frozenset(
    {"base-prompt", "base-system-prompt", "system-prompt"}
)
_USAGE_FIELDS = frozenset(
    {
        "aggregate_tokens",
        "cost_micros",
        "model_credential_reads",
        "provider_operations",
    }
)


class PrimeHarnessError(RuntimeError):
    """Raised when selected-Prime harness translation fails closed."""


PrimeHarnessScope = Literal["local", "global"]


@dataclass(frozen=True, repr=False)
class PrimeHarnessEdit:
    action: Literal["create", "update", "delete"]
    entry_id: str
    expected_version: int | None
    kind: Literal["prompt", "memory", "skill", "subagent"] | None
    title_digest: str | None
    body_digest: str | None
    grouping_path_digest: str | None
    metadata_digest: str | None
    version: int | None
    body_text: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if not _valid_id(self.entry_id) or self.action not in {
            "create",
            "update",
            "delete",
        }:
            raise PrimeHarnessError("Prime harness effect is invalid")
        if self.action == "delete":
            valid = (
                _positive_int(self.expected_version)
                and self.kind is None
                and self.title_digest is None
                and self.body_digest is None
                and self.grouping_path_digest is None
                and self.metadata_digest is None
                and self.version is None
                and self.body_text is None
            )
        else:
            valid = (
                (self.action == "create" and self.expected_version is None)
                or (self.action == "update" and _positive_int(self.expected_version))
            ) and (
                self.kind in {"prompt", "memory", "skill", "subagent"}
                and _valid_digest(self.title_digest)
                and _valid_digest(self.body_digest)
                and (
                    self.grouping_path_digest is None
                    or _valid_digest(self.grouping_path_digest)
                )
                and _valid_digest(self.metadata_digest)
                and _positive_int(self.version)
                and isinstance(self.body_text, str)
            )
        if not valid:
            raise PrimeHarnessError("Prime harness effect is invalid")

    def __repr__(self) -> str:
        return (
            "PrimeHarnessEdit("
            f"action={self.action!r}, entry_id={self.entry_id!r}, "
            f"kind={self.kind!r}, version={self.version!r})"
        )

    def to_public_entry_mapping(self) -> Mapping[str, object]:
        if self.action == "delete":
            raise PrimeHarnessError("Prime harness effect is invalid")
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


@dataclass(frozen=True, repr=False)
class PrimeHarnessEffect:
    proposal_id: str
    proposal_digest: str
    effect_digest: str
    prime_scope: PrimeHarnessScope
    scope_digest: str
    edits: tuple[PrimeHarnessEdit, ...]

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.proposal_id)
            or not _valid_digest(self.proposal_digest)
            or not _valid_digest(self.effect_digest)
            or self.prime_scope not in {"local", "global"}
            or not _valid_digest(self.scope_digest)
            or not self.edits
            or any(not isinstance(item, PrimeHarnessEdit) for item in self.edits)
        ):
            raise PrimeHarnessError("Prime harness effect is invalid")

    def __repr__(self) -> str:
        return (
            "PrimeHarnessEffect("
            f"proposal_id={self.proposal_id!r}, "
            f"proposal_digest={self.proposal_digest!r}, "
            f"effect_digest={self.effect_digest!r}, "
            f"prime_scope={self.prime_scope!r}, scope_digest={self.scope_digest!r}, "
            f"edit_count={len(self.edits)})"
        )


@dataclass(frozen=True, repr=False)
class PrimeHarnessIpcReceipt:
    proposal_id: str
    proposal_digest: str
    effect_digest: str
    status: Literal["succeeded", "failed", "cancelled", "uncertain"]
    result_entries: tuple[Mapping[str, object], ...]
    usage: Mapping[str, int]

    def __post_init__(self) -> None:
        try:
            entries = tuple(
                MappingProxyType(dict(item)) for item in self.result_entries
            )
        except (TypeError, ValueError):
            raise PrimeHarnessError("Prime harness receipt is invalid") from None
        if (
            not _valid_id(self.proposal_id)
            or not _valid_digest(self.proposal_digest)
            or not _valid_digest(self.effect_digest)
            or self.status not in {"succeeded", "failed", "cancelled", "uncertain"}
            or not _valid_public_entries(entries)
        ):
            raise PrimeHarnessError("Prime harness receipt is invalid")
        object.__setattr__(self, "result_entries", entries)
        object.__setattr__(self, "usage", _freeze_usage(self.usage))

    def __repr__(self) -> str:
        return (
            "PrimeHarnessIpcReceipt("
            f"proposal_id={self.proposal_id!r}, status={self.status!r}, "
            f"result_count={len(self.result_entries)}, usage={dict(self.usage)!r})"
        )


class PrimeContinualHarnessClient(Protocol):
    def apply_harness_effect(
        self, effect: PrimeHarnessEffect
    ) -> PrimeHarnessIpcReceipt:
        """Apply one exact private effect without selecting or retrying it."""

    def read_harness_snapshot(
        self, scope: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Read one exact provider projection for reconciliation."""


class PrimePrivateHarnessBodies(Protocol):
    def resolve_text(self, private_ref: str) -> str:
        """Resolve one admitted body immediately before private IPC."""


class PrimeContinualHarnessService:
    """Translate admitted host edits to one exact Prime Gateway effect."""

    def __init__(self, client: PrimeContinualHarnessClient) -> None:
        if not callable(getattr(client, "apply_harness_effect", None)) or not callable(
            getattr(client, "read_harness_snapshot", None)
        ):
            raise PrimeHarnessError("Prime harness service is invalid")
        self._client = client

    def apply(
        self,
        proposal: HarnessProposal,
        bodies: PrimePrivateHarnessBodies,
    ) -> HarnessEffectReceipt:
        if not isinstance(proposal, HarnessProposal) or not callable(
            getattr(bodies, "resolve_text", None)
        ):
            raise PrimeHarnessError("Prime harness effect is invalid")
        edits = tuple(self._translate_edit(item, bodies) for item in proposal.edits)
        effect = PrimeHarnessEffect(
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest,
            effect_digest=harness_effect_digest(proposal),
            prime_scope="global" if proposal.scope.kind == "global" else "local",
            scope_digest=proposal.scope.digest,
            edits=edits,
        )
        try:
            receipt = self._client.apply_harness_effect(effect)
        except HarnessTransportError:
            raise
        except (ConnectionError, OSError, TimeoutError):
            raise HarnessTransportError("Prime harness transport failed") from None
        except Exception:
            raise PrimeHarnessError("Prime harness operation failed") from None
        if (
            not isinstance(receipt, PrimeHarnessIpcReceipt)
            or receipt.proposal_id != proposal.proposal_id
            or receipt.proposal_digest != proposal.digest
            or receipt.effect_digest != effect.effect_digest
        ):
            raise PrimeHarnessError("Prime harness receipt is invalid")
        result_entries = self._bind_public_results(proposal, receipt)
        return HarnessEffectReceipt(
            proposal_id=receipt.proposal_id,
            proposal_digest=receipt.proposal_digest,
            effect_digest=receipt.effect_digest,
            status=receipt.status,
            result_entries=result_entries,
            usage=receipt.usage,
        )

    def reconcile(
        self,
        proposal: HarnessProposal,
        snapshot: HarnessSnapshot,
    ) -> HarnessEffectReceipt:
        if (
            not isinstance(proposal, HarnessProposal)
            or not isinstance(snapshot, HarnessSnapshot)
            or proposal.scope != snapshot.scope
        ):
            raise PrimeHarnessError("Prime harness reconciliation is invalid")
        try:
            result = self._client.read_harness_snapshot(proposal.scope.to_mapping())
        except HarnessTransportError:
            raise
        except Exception:
            raise PrimeHarnessError("Prime harness reconciliation failed") from None
        if set(result) != {"scope_digest", "snapshot_id"} or (
            result["scope_digest"] != proposal.scope.digest
            or result["snapshot_id"] != snapshot.snapshot_id
        ):
            raise PrimeHarnessError("Prime harness reconciliation is invalid")
        return HarnessEffectReceipt.succeeded(
            proposal,
            effect_digest=harness_effect_digest(proposal),
            result_entries=snapshot.entries,
        )

    def _translate_edit(
        self,
        edit: HarnessEdit,
        bodies: PrimePrivateHarnessBodies,
    ) -> PrimeHarnessEdit:
        replacement = edit.replacement
        if replacement is None:
            return PrimeHarnessEdit(
                edit.action,
                edit.entry_id,
                edit.expected_version,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        if replacement.kind == "prompt" and replacement.entry_id in _BASE_PROMPT_IDENTITIES:
            raise PrimeHarnessError("Prime harness effect is invalid")
        try:
            body_text = bodies.resolve_text(replacement.body_ref)
        except Exception:
            raise PrimeHarnessError("Prime harness effect is invalid") from None
        if not isinstance(body_text, str):
            raise PrimeHarnessError("Prime harness effect is invalid")
        return PrimeHarnessEdit(
            edit.action,
            edit.entry_id,
            edit.expected_version,
            replacement.kind,
            replacement.title_digest,
            replacement.body_digest,
            replacement.grouping_path_digest,
            replacement.metadata_digest,
            replacement.version,
            body_text,
        )

    def _bind_public_results(
        self,
        proposal: HarnessProposal,
        receipt: PrimeHarnessIpcReceipt,
    ) -> tuple[HarnessEntryDescriptor, ...]:
        admitted = {
            item.replacement.entry_id: item.replacement
            for item in proposal.edits
            if item.replacement is not None
        }
        values: list[HarnessEntryDescriptor] = []
        for public in receipt.result_entries:
            entry_id = public.get("entry_id")
            descriptor = admitted.get(entry_id)
            if descriptor is None or dict(descriptor.to_public_mapping()) != dict(public):
                raise PrimeHarnessError("Prime harness receipt is invalid")
            values.append(descriptor)
        return tuple(sorted(values, key=lambda item: item.entry_id))


def _valid_public_entries(entries: tuple[Mapping[str, object], ...]) -> bool:
    entry_ids: list[str] = []
    expected = {
        "body_digest",
        "entry_id",
        "grouping_path_digest",
        "kind",
        "metadata_digest",
        "title_digest",
        "version",
    }
    for entry in entries:
        if (
            set(entry) != expected
            or not _valid_id(entry.get("entry_id"))
            or entry.get("kind") not in {"prompt", "memory", "skill", "subagent"}
            or not _valid_digest(entry.get("title_digest"))
            or not _valid_digest(entry.get("body_digest"))
            or not _valid_digest(entry.get("metadata_digest"))
            or (
                entry.get("grouping_path_digest") is not None
                and not _valid_digest(entry.get("grouping_path_digest"))
            )
            or not _positive_int(entry.get("version"))
        ):
            return False
        entry_ids.append(str(entry["entry_id"]))
    return entry_ids == sorted(set(entry_ids))


def _freeze_usage(value: object) -> Mapping[str, int]:
    if not isinstance(value, Mapping) or set(value) != _USAGE_FIELDS:
        raise PrimeHarnessError("Prime harness receipt is invalid")
    copied = dict(value)
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in copied.values()
    ):
        raise PrimeHarnessError("Prime harness receipt is invalid")
    return MappingProxyType(copied)


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0
