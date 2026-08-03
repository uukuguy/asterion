"""Provider-free, content-addressed Pathlight interoperability contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Sequence, TypeAlias, cast

from asterion.pathlight.evaluation import METRIC_NAMES
from asterion.pathlight._private_file import (
    PrivateFileError,
    read_private_file,
    write_private_file,
)
from asterion.pathlight.protocol import PathlightError


Connector: TypeAlias = Literal["opik"]
ExportEventKind: TypeAlias = Literal[
    "trace.upsert",
    "span.upsert",
    "thread.upsert",
    "dataset.upsert",
    "experiment.upsert",
    "case-trial.upsert",
    "evaluation.upsert",
    "trial-history.upsert",
    "proposal.observe",
    "decision.observe",
]
ReceiptStatus: TypeAlias = Literal[
    "delivered", "retryable-failure", "terminal-failure"
]
FailureCategory: TypeAlias = Literal[
    "authentication", "rate-limit", "network", "mapping", "service"
]
ObservationKind: TypeAlias = Literal[
    "feedback", "experiment-analysis", "optimization-suggestion"
]
SafeScalar: TypeAlias = str | int | bool | None

EXPORT_ENVELOPE_SCHEMA = "asterion.pathlight-export-envelope/v1"
EXPORT_RECEIPT_SCHEMA = "asterion.pathlight-export-receipt/v1"
EXTERNAL_OBSERVATION_SCHEMA = "asterion.pathlight-external-observation/v1"
PROPOSAL_CANDIDATE_SCHEMA = "asterion.pathlight-proposal-candidate/v1"
EXPORT_BATCH_SCHEMA = "asterion.pathlight-export-batch/v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_CONNECTORS = frozenset({"opik"})
_EVENT_KINDS = frozenset(
    {
        "trace.upsert",
        "span.upsert",
        "thread.upsert",
        "dataset.upsert",
        "experiment.upsert",
        "case-trial.upsert",
        "evaluation.upsert",
        "trial-history.upsert",
        "proposal.observe",
        "decision.observe",
    }
)
_RECEIPT_STATUSES = frozenset(
    {"delivered", "retryable-failure", "terminal-failure"}
)
_FAILURE_CATEGORIES = frozenset(
    {"authentication", "rate-limit", "network", "mapping", "service"}
)
_OBSERVATION_KINDS = frozenset(
    {"feedback", "experiment-analysis", "optimization-suggestion"}
)
_SAFE_INTEGER_FIELDS = frozenset(
    {
        "attempt",
        "duration_ns",
        "error_count",
        "input_tokens",
        "output_tokens",
        "selected_count",
        "sequence",
        "tool_call_count",
        "total_count",
        "value_microunits",
    }
)
_SAFE_BOOLEAN_FIELDS = frozenset(
    {"execution_authorized", "requires_operator_authorization"}
)
_SAFE_STRING_VALUES = frozenset(
    {
        "accepted",
        "cancelled",
        "completed",
        "failed",
        "inconclusive",
        "missing",
        "observed",
        "proposed",
        "recovered",
        "rejected",
        "trace",
        "span",
        "thread",
        "experiment",
        "case-trial",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema",
        "connector",
        "mapping_version",
        "event_kind",
        "local_object_sha256",
        "payload",
        "idempotency_key",
        "envelope_sha256",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "envelope_sha256",
        "connector",
        "status",
        "attempt",
        "external_object_sha256",
        "failure_category",
        "receipt_sha256",
    }
)
_OBSERVATION_FIELDS = frozenset(
    {
        "schema",
        "connector",
        "connector_identity_sha256",
        "mapping_version",
        "local_subject_sha256",
        "external_event_sha256",
        "observation_kind",
        "payload",
        "observation_sha256",
    }
)
_CANDIDATE_FIELDS = frozenset(
    {
        "schema",
        "external_observation_sha256",
        "change_sha256",
        "scope_sha256",
        "success_criteria_sha256",
        "stop_criteria_sha256",
        "budget_sha256",
        "status",
        "requires_operator_authorization",
        "execution_authorized",
        "proposal_candidate_sha256",
    }
)
_BATCH_FIELDS = frozenset({"schema", "envelopes", "batch_sha256"})
_MAX_INTEROP_BYTES = 4_000_000


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _semver(value: object) -> str:
    if type(value) is not str or _SEMVER.fullmatch(value) is None:
        raise ValueError
    return value


def _connector(value: object) -> Connector:
    if type(value) is not str or value not in _CONNECTORS:
        raise ValueError
    return cast(Connector, value)


def _event_kind(value: object) -> ExportEventKind:
    if type(value) is not str or value not in _EVENT_KINDS:
        raise ValueError
    return cast(ExportEventKind, value)


def _safe_payload(value: object) -> MappingProxyType[str, SafeScalar]:
    if type(value) is not dict:
        raise ValueError
    copied: dict[str, SafeScalar] = {}
    for key in sorted(value):
        item = value[key]
        if type(key) is not str:
            raise ValueError
        if key.endswith("_sha256"):
            copied[key] = _sha256(item)
        elif key in _SAFE_INTEGER_FIELDS:
            if type(item) is not int or item < 0:
                raise ValueError
            copied[key] = item
        elif key in _SAFE_BOOLEAN_FIELDS:
            if type(item) is not bool:
                raise ValueError
            copied[key] = item
        elif key == "metric_name":
            if type(item) is not str or item not in METRIC_NAMES:
                raise ValueError
            copied[key] = item
        elif key.endswith("_version"):
            copied[key] = _semver(item)
        elif key in {"status", "kind", "evidence_state"}:
            if type(item) is not str or item not in _SAFE_STRING_VALUES:
                raise ValueError
            copied[key] = item
        else:
            raise ValueError
    return MappingProxyType(copied)


def _payload_mapping(value: Mapping[str, SafeScalar]) -> dict[str, SafeScalar]:
    return {key: value[key] for key in sorted(value)}


@dataclass(frozen=True, slots=True)
class ExportEnvelope:
    """One immutable, safe mirror event for an optional external connector."""

    connector: Connector
    mapping_version: str
    event_kind: ExportEventKind
    local_object_sha256: str
    payload: Mapping[str, SafeScalar]
    idempotency_key: str = field(init=False)
    envelope_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _connector(self.connector)
            _semver(self.mapping_version)
            _event_kind(self.event_kind)
            _sha256(self.local_object_sha256)
            payload = _safe_payload(self.payload)
        except Exception:
            raise PathlightError("Pathlight export envelope is invalid") from None
        object.__setattr__(self, "payload", payload)
        identity = _digest(self._unsigned_mapping())
        object.__setattr__(self, "idempotency_key", identity)
        object.__setattr__(self, "envelope_sha256", identity)

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": EXPORT_ENVELOPE_SCHEMA,
            "connector": self.connector,
            "mapping_version": self.mapping_version,
            "event_kind": self.event_kind,
            "local_object_sha256": self.local_object_sha256,
            "payload": _payload_mapping(self.payload),
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "idempotency_key": self.idempotency_key,
            "envelope_sha256": self.envelope_sha256,
        }


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """A delivery result that cannot mutate the local authoritative object."""

    envelope_sha256: str
    connector: Connector
    status: ReceiptStatus
    attempt: int
    external_object_sha256: str | None
    failure_category: FailureCategory | None
    receipt_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _sha256(self.envelope_sha256)
            _connector(self.connector)
            if (
                type(self.status) is not str
                or self.status not in _RECEIPT_STATUSES
                or type(self.attempt) is not int
                or self.attempt < 1
            ):
                raise ValueError
            if self.status == "delivered":
                _sha256(self.external_object_sha256)
                if self.failure_category is not None:
                    raise ValueError
            elif (
                self.external_object_sha256 is not None
                or type(self.failure_category) is not str
                or self.failure_category not in _FAILURE_CATEGORIES
            ):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight export receipt is invalid") from None
        object.__setattr__(self, "receipt_sha256", _digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": EXPORT_RECEIPT_SCHEMA,
            "envelope_sha256": self.envelope_sha256,
            "connector": self.connector,
            "status": self.status,
            "attempt": self.attempt,
            "external_object_sha256": self.external_object_sha256,
            "failure_category": self.failure_category,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "receipt_sha256": self.receipt_sha256}


@dataclass(frozen=True, slots=True)
class ExternalObservation:
    """A digest-bound external observation with no local truth authority."""

    connector: Connector
    connector_identity_sha256: str
    mapping_version: str
    local_subject_sha256: str
    external_event_sha256: str
    observation_kind: ObservationKind
    payload: Mapping[str, SafeScalar]
    observation_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _connector(self.connector)
            _sha256(self.connector_identity_sha256)
            _semver(self.mapping_version)
            _sha256(self.local_subject_sha256)
            _sha256(self.external_event_sha256)
            if (
                type(self.observation_kind) is not str
                or self.observation_kind not in _OBSERVATION_KINDS
            ):
                raise ValueError
            payload = _safe_payload(self.payload)
        except Exception:
            raise PathlightError("Pathlight external observation is invalid") from None
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "observation_sha256", _digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_OBSERVATION_SCHEMA,
            "connector": self.connector,
            "connector_identity_sha256": self.connector_identity_sha256,
            "mapping_version": self.mapping_version,
            "local_subject_sha256": self.local_subject_sha256,
            "external_event_sha256": self.external_event_sha256,
            "observation_kind": self.observation_kind,
            "payload": _payload_mapping(self.payload),
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "observation_sha256": self.observation_sha256,
        }


@dataclass(frozen=True, slots=True)
class ProposalCandidate:
    """An imported optimization suggestion that can never authorize execution."""

    external_observation_sha256: str
    change_sha256: str
    scope_sha256: str
    success_criteria_sha256: str
    stop_criteria_sha256: str
    budget_sha256: str
    status: Literal["candidate"] = "candidate"
    requires_operator_authorization: bool = True
    execution_authorized: bool = False
    proposal_candidate_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in (
                self.external_observation_sha256,
                self.change_sha256,
                self.scope_sha256,
                self.success_criteria_sha256,
                self.stop_criteria_sha256,
                self.budget_sha256,
            ):
                _sha256(value)
            if (
                self.status != "candidate"
                or self.requires_operator_authorization is not True
                or self.execution_authorized is not False
            ):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight proposal candidate is invalid") from None
        object.__setattr__(
            self, "proposal_candidate_sha256", _digest(self._unsigned_mapping())
        )

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": PROPOSAL_CANDIDATE_SCHEMA,
            "external_observation_sha256": self.external_observation_sha256,
            "change_sha256": self.change_sha256,
            "scope_sha256": self.scope_sha256,
            "success_criteria_sha256": self.success_criteria_sha256,
            "stop_criteria_sha256": self.stop_criteria_sha256,
            "budget_sha256": self.budget_sha256,
            "status": self.status,
            "requires_operator_authorization": self.requires_operator_authorization,
            "execution_authorized": self.execution_authorized,
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self._unsigned_mapping(),
            "proposal_candidate_sha256": self.proposal_candidate_sha256,
        }


@dataclass(frozen=True, slots=True)
class ExportBatch:
    """A sorted immutable collection ready for operator-owned delivery."""

    envelopes: tuple[ExportEnvelope, ...]
    batch_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            if type(self.envelopes) is not tuple or not self.envelopes:
                raise ValueError
            copied = tuple(
                validate_export_envelope(item.to_mapping()) for item in self.envelopes
            )
            identities = tuple(item.envelope_sha256 for item in copied)
            if identities != tuple(sorted(identities)) or len(identities) != len(
                set(identities)
            ):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight export batch is invalid") from None
        object.__setattr__(self, "envelopes", copied)
        object.__setattr__(self, "batch_sha256", _digest(self._unsigned_mapping()))

    @property
    def filename(self) -> str:
        return f"batch-{self.batch_sha256}.json"

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "schema": EXPORT_BATCH_SCHEMA,
            "envelopes": [item.to_mapping() for item in self.envelopes],
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "batch_sha256": self.batch_sha256}


def validate_export_envelope(mapping: Mapping[str, object]) -> ExportEnvelope:
    try:
        if type(mapping) is not dict or set(mapping) != _ENVELOPE_FIELDS:
            raise ValueError
        if mapping["schema"] != EXPORT_ENVELOPE_SCHEMA:
            raise ValueError
        envelope = ExportEnvelope(
            _connector(mapping["connector"]),
            _semver(mapping["mapping_version"]),
            _event_kind(mapping["event_kind"]),
            _sha256(mapping["local_object_sha256"]),
            mapping["payload"],  # type: ignore[arg-type]
        )
        if not hmac.compare_digest(
            _sha256(mapping["idempotency_key"]), envelope.idempotency_key
        ) or not hmac.compare_digest(
            _sha256(mapping["envelope_sha256"]), envelope.envelope_sha256
        ):
            raise ValueError
        return envelope
    except Exception:
        raise PathlightError("Pathlight export envelope is invalid") from None


def validate_export_receipt(mapping: Mapping[str, object]) -> ExportReceipt:
    try:
        if type(mapping) is not dict or set(mapping) != _RECEIPT_FIELDS:
            raise ValueError
        if mapping["schema"] != EXPORT_RECEIPT_SCHEMA:
            raise ValueError
        receipt = ExportReceipt(
            _sha256(mapping["envelope_sha256"]),
            _connector(mapping["connector"]),
            mapping["status"],  # type: ignore[arg-type]
            mapping["attempt"],  # type: ignore[arg-type]
            mapping["external_object_sha256"],  # type: ignore[arg-type]
            mapping["failure_category"],  # type: ignore[arg-type]
        )
        if not hmac.compare_digest(
            _sha256(mapping["receipt_sha256"]), receipt.receipt_sha256
        ):
            raise ValueError
        return receipt
    except Exception:
        raise PathlightError("Pathlight export receipt is invalid") from None


def validate_external_observation(mapping: Mapping[str, object]) -> ExternalObservation:
    try:
        if type(mapping) is not dict or set(mapping) != _OBSERVATION_FIELDS:
            raise ValueError
        if mapping["schema"] != EXTERNAL_OBSERVATION_SCHEMA:
            raise ValueError
        observation = ExternalObservation(
            _connector(mapping["connector"]),
            _sha256(mapping["connector_identity_sha256"]),
            _semver(mapping["mapping_version"]),
            _sha256(mapping["local_subject_sha256"]),
            _sha256(mapping["external_event_sha256"]),
            mapping["observation_kind"],  # type: ignore[arg-type]
            mapping["payload"],  # type: ignore[arg-type]
        )
        if not hmac.compare_digest(
            _sha256(mapping["observation_sha256"]), observation.observation_sha256
        ):
            raise ValueError
        return observation
    except Exception:
        raise PathlightError("Pathlight external observation is invalid") from None


def validate_proposal_candidate(mapping: Mapping[str, object]) -> ProposalCandidate:
    try:
        if type(mapping) is not dict or set(mapping) != _CANDIDATE_FIELDS:
            raise ValueError
        if mapping["schema"] != PROPOSAL_CANDIDATE_SCHEMA:
            raise ValueError
        candidate = ProposalCandidate(
            _sha256(mapping["external_observation_sha256"]),
            _sha256(mapping["change_sha256"]),
            _sha256(mapping["scope_sha256"]),
            _sha256(mapping["success_criteria_sha256"]),
            _sha256(mapping["stop_criteria_sha256"]),
            _sha256(mapping["budget_sha256"]),
            mapping["status"],  # type: ignore[arg-type]
            mapping["requires_operator_authorization"],  # type: ignore[arg-type]
            mapping["execution_authorized"],  # type: ignore[arg-type]
        )
        if not hmac.compare_digest(
            _sha256(mapping["proposal_candidate_sha256"]),
            candidate.proposal_candidate_sha256,
        ):
            raise ValueError
        return candidate
    except Exception:
        raise PathlightError("Pathlight proposal candidate is invalid") from None


def validate_export_batch(mapping: Mapping[str, object]) -> ExportBatch:
    try:
        if type(mapping) is not dict or set(mapping) != _BATCH_FIELDS:
            raise ValueError
        if mapping["schema"] != EXPORT_BATCH_SCHEMA or type(mapping["envelopes"]) is not list:
            raise ValueError
        batch = ExportBatch(
            tuple(validate_export_envelope(item) for item in mapping["envelopes"])
        )
        if not hmac.compare_digest(
            _sha256(mapping["batch_sha256"]), batch.batch_sha256
        ):
            raise ValueError
        return batch
    except Exception:
        raise PathlightError("Pathlight export batch is invalid") from None


def write_export_batch(
    root: Path, envelopes: Sequence[ExportEnvelope]
) -> ExportBatch:
    """Write one deterministic private batch without contacting its connector."""

    try:
        _operator_root(root)
        if type(envelopes) not in {tuple, list} or not envelopes:
            raise ValueError
        by_identity: dict[str, ExportEnvelope] = {}
        for value in envelopes:
            if type(value) is not ExportEnvelope:
                raise ValueError
            copied = validate_export_envelope(value.to_mapping())
            previous = by_identity.get(copied.idempotency_key)
            if previous is not None and not hmac.compare_digest(
                _canonical_bytes(previous.to_mapping()),
                _canonical_bytes(copied.to_mapping()),
            ):
                raise ValueError
            by_identity[copied.idempotency_key] = copied
        batch = ExportBatch(
            tuple(sorted(by_identity.values(), key=lambda item: item.envelope_sha256))
        )
        target = root / batch.filename
        encoded = _canonical_bytes(batch.to_mapping())
        if target.exists() or target.is_symlink():
            if not hmac.compare_digest(
                read_private_file(target, _MAX_INTEROP_BYTES), encoded
            ):
                raise ValueError
            return read_export_batch(target)
        try:
            write_private_file(target, encoded)
        except PrivateFileError:
            if not hmac.compare_digest(
                read_private_file(target, _MAX_INTEROP_BYTES), encoded
            ):
                raise
        return read_export_batch(target)
    except Exception:
        raise PathlightError("Pathlight export batch could not be written") from None


def read_export_batch(path: Path) -> ExportBatch:
    """Read and validate one exact private export batch."""

    try:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.is_symlink()
            or re.fullmatch(r"batch-[0-9a-f]{64}\.json", path.name) is None
        ):
            raise ValueError
        raw = read_private_file(path, _MAX_INTEROP_BYTES)
        mapping = json.loads(raw)
        batch = validate_export_batch(mapping)
        if path.name != batch.filename or not hmac.compare_digest(
            raw, _canonical_bytes(batch.to_mapping())
        ):
            raise ValueError
        return batch
    except Exception:
        raise PathlightError("Pathlight export batch is invalid") from None


def record_export_receipt(root: Path, receipt: ExportReceipt) -> ExportReceipt:
    """Append one monotonic delivery result for a single immutable envelope."""

    try:
        _operator_root(root)
        if type(receipt) is not ExportReceipt:
            raise ValueError
        receipt = validate_export_receipt(receipt.to_mapping())
        previous = tuple(
            item
            for item in read_export_receipts(root)
            if item.envelope_sha256 == receipt.envelope_sha256
        )
        if (
            receipt.attempt != len(previous) + 1
            or previous
            and previous[-1].status in {"delivered", "terminal-failure"}
        ):
            raise ValueError
        target = root / (
            f"receipt-{receipt.envelope_sha256}-{receipt.attempt:06d}.json"
        )
        write_private_file(target, _canonical_bytes(receipt.to_mapping()))
        observed = validate_export_receipt(
            json.loads(read_private_file(target, _MAX_INTEROP_BYTES))
        )
        if observed != receipt:
            raise ValueError
        return observed
    except Exception:
        raise PathlightError("Pathlight export receipt could not be recorded") from None


def read_export_receipts(root: Path) -> tuple[ExportReceipt, ...]:
    """Read the exact private receipt ledger in envelope/attempt order."""

    try:
        _operator_root(root)
        values: list[ExportReceipt] = []
        expected: dict[str, int] = {}
        terminal: set[str] = set()
        for path in sorted(root.glob("receipt-*.json")):
            if path.is_symlink() or re.fullmatch(
                r"receipt-[0-9a-f]{64}-[0-9]{6}\.json", path.name
            ) is None:
                raise ValueError
            receipt = validate_export_receipt(
                json.loads(read_private_file(path, _MAX_INTEROP_BYTES))
            )
            if path.name != (
                f"receipt-{receipt.envelope_sha256}-{receipt.attempt:06d}.json"
            ):
                raise ValueError
            next_attempt = expected.get(receipt.envelope_sha256, 1)
            if receipt.attempt != next_attempt or receipt.envelope_sha256 in terminal:
                raise ValueError
            expected[receipt.envelope_sha256] = next_attempt + 1
            if receipt.status in {"delivered", "terminal-failure"}:
                terminal.add(receipt.envelope_sha256)
            values.append(receipt)
        return tuple(values)
    except Exception:
        raise PathlightError("Pathlight export receipt ledger is invalid") from None


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _operator_root(root: Path) -> None:
    if not isinstance(root, Path) or not root.is_absolute() or root != root.resolve():
        raise ValueError
    metadata = os.stat(root, follow_symlinks=False)
    if (
        root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError
