"""Immutable, evidence-closed Pathlight diagnosis and proposal contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, TypeAlias, cast

from asterion.pathlight.protocol import PathlightError


FindingCategory: TypeAlias = Literal[
    "observed", "hypothesis", "not-comparable", "missing-evidence"
]
Confidence: TypeAlias = Literal["confirmed", "low", "medium", "high", "unknown"]

DIAGNOSIS_BUNDLE_SCHEMA = "asterion.pathlight-diagnosis/v1"
DIAGNOSIS_BUNDLE_FILENAME = "pathlight-diagnosis.json"
_MAX_DIAGNOSIS_BUNDLE_BYTES = 1_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINDING_CATEGORIES = frozenset({"observed", "hypothesis", "not-comparable", "missing-evidence"})
_CONFIDENCES = frozenset({"confirmed", "low", "medium", "high", "unknown"})
_FINDING_FIELDS = frozenset(
    {
        "category",
        "subject_sha256",
        "evidence_sha256s",
        "counterevidence_sha256s",
        "confidence",
        "finding_code_sha256",
        "finding_sha256",
    }
)
_PROPOSAL_FIELDS = frozenset(
    {
        "finding_sha256",
        "change_sha256",
        "scope_sha256",
        "success_criteria_sha256",
        "stop_criteria_sha256",
        "budget_sha256",
        "status",
        "requires_operator_authorization",
        "execution_authorized",
        "proposal_sha256",
    }
)
_BUNDLE_FIELDS = frozenset(
    {
        "schema",
        "experiment_bundle_sha256s",
        "evaluation_sha256s",
        "findings",
        "proposals",
        "bundle_sha256",
    }
)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError
    return value


def _require_sorted_unique_sha256s(value: object, *, nonempty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ValueError
    values = tuple(
        _require_sha256(item) for item in cast(list[object] | tuple[object, ...], value)
    )
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError
    if nonempty and not values:
        raise ValueError
    return values


def _require_finding_category(value: object) -> FindingCategory:
    if type(value) is not str or value not in _FINDING_CATEGORIES:
        raise ValueError
    return cast(FindingCategory, value)


def _require_confidence(value: object) -> Confidence:
    if type(value) is not str or value not in _CONFIDENCES:
        raise ValueError
    return cast(Confidence, value)


@dataclass(frozen=True, slots=True)
class Finding:
    """One content-addressed observation, hypothesis, or evidence gap."""

    category: FindingCategory
    subject_sha256: str
    evidence_sha256s: tuple[str, ...]
    counterevidence_sha256s: tuple[str, ...]
    confidence: Confidence
    finding_code_sha256: str
    finding_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            _require_finding_category(self.category)
            _require_sha256(self.subject_sha256)
            _require_sorted_unique_sha256s(self.evidence_sha256s, nonempty=True)
            _require_sorted_unique_sha256s(self.counterevidence_sha256s)
            _require_confidence(self.confidence)
            _require_sha256(self.finding_code_sha256)
        except Exception:
            raise PathlightError("Pathlight finding is invalid") from None
        object.__setattr__(self, "finding_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "category": self.category,
            "subject_sha256": self.subject_sha256,
            "evidence_sha256s": self.evidence_sha256s,
            "counterevidence_sha256s": self.counterevidence_sha256s,
            "confidence": self.confidence,
            "finding_code_sha256": self.finding_code_sha256,
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "finding_sha256": self.finding_sha256}


@dataclass(frozen=True, slots=True)
class Proposal:
    """A digest-only request that has no execution authority."""

    finding_sha256: str
    change_sha256: str
    scope_sha256: str
    success_criteria_sha256: str
    stop_criteria_sha256: str
    budget_sha256: str
    status: Literal["proposed"] = "proposed"
    requires_operator_authorization: bool = True
    execution_authorized: bool = False
    proposal_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            for value in (
                self.finding_sha256,
                self.change_sha256,
                self.scope_sha256,
                self.success_criteria_sha256,
                self.stop_criteria_sha256,
                self.budget_sha256,
            ):
                _require_sha256(value)
            if (
                type(self.status) is not str
                or self.status != "proposed"
                or self.requires_operator_authorization is not True
                or self.execution_authorized is not False
            ):
                raise ValueError
        except Exception:
            raise PathlightError("Pathlight proposal is invalid") from None
        object.__setattr__(self, "proposal_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "finding_sha256": self.finding_sha256,
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
        return {**self._unsigned_mapping(), "proposal_sha256": self.proposal_sha256}


def validate_finding(mapping: Mapping[str, object]) -> Finding:
    """Validate one exact public-safe finding mapping."""

    try:
        if type(mapping) is not dict or set(mapping) != _FINDING_FIELDS:
            raise ValueError
        finding = Finding(
            _require_finding_category(mapping["category"]),
            _require_sha256(mapping["subject_sha256"]),
            _json_sha256_tuple(mapping["evidence_sha256s"], nonempty=True),
            _json_sha256_tuple(mapping["counterevidence_sha256s"]),
            _require_confidence(mapping["confidence"]),
            _require_sha256(mapping["finding_code_sha256"]),
        )
        if not hmac.compare_digest(_require_sha256(mapping["finding_sha256"]), finding.finding_sha256):
            raise ValueError
        return finding
    except Exception:
        raise PathlightError("Pathlight finding is invalid") from None


def validate_proposal(mapping: Mapping[str, object]) -> Proposal:
    """Validate one exact non-executing proposal mapping."""

    try:
        if type(mapping) is not dict or set(mapping) != _PROPOSAL_FIELDS:
            raise ValueError
        proposal = Proposal(
            _require_sha256(mapping["finding_sha256"]),
            _require_sha256(mapping["change_sha256"]),
            _require_sha256(mapping["scope_sha256"]),
            _require_sha256(mapping["success_criteria_sha256"]),
            _require_sha256(mapping["stop_criteria_sha256"]),
            _require_sha256(mapping["budget_sha256"]),
            mapping["status"],  # type: ignore[arg-type]
            mapping["requires_operator_authorization"],  # type: ignore[arg-type]
            mapping["execution_authorized"],  # type: ignore[arg-type]
        )
        if not hmac.compare_digest(_require_sha256(mapping["proposal_sha256"]), proposal.proposal_sha256):
            raise ValueError
        return proposal
    except Exception:
        raise PathlightError("Pathlight proposal is invalid") from None


@dataclass(frozen=True, slots=True)
class DiagnosisBundle:
    """A canonical diagnosis closure over exact experiment and evaluation identities."""

    experiment_bundle_sha256s: tuple[str, ...]
    evaluation_sha256s: tuple[str, ...]
    findings: tuple[Finding, ...]
    proposals: tuple[Proposal, ...]
    bundle_sha256: str

    def __post_init__(self) -> None:
        values: tuple[tuple[str, ...], tuple[str, ...], tuple[Finding, ...], tuple[Proposal, ...]] | None = None
        try:
            values = _normalize_bundle_values(
                self.experiment_bundle_sha256s,
                self.evaluation_sha256s,
                self.findings,
                self.proposals,
                require_sorted=True,
            )
            _validate_closure(*values)
            if not hmac.compare_digest(
                _require_sha256(self.bundle_sha256), _canonical_digest(_bundle_document(*values))
            ):
                raise ValueError
        except Exception:
            values = None
        if values is None:
            raise PathlightError("Pathlight diagnosis bundle is invalid")
        for name, value in zip(
            ("experiment_bundle_sha256s", "evaluation_sha256s", "findings", "proposals"), values, strict=True
        ):
            object.__setattr__(self, name, value)

    @classmethod
    def build(
        cls,
        *,
        experiment_bundle_sha256s: Sequence[str],
        evaluation_sha256s: Sequence[str],
        findings: Sequence[Finding],
        proposals: Sequence[Proposal],
    ) -> DiagnosisBundle:
        """Build one canonical diagnosis after validating reference closure."""

        try:
            values = _normalize_bundle_values(
                experiment_bundle_sha256s, evaluation_sha256s, findings, proposals, require_sorted=False
            )
            _validate_closure(*values)
            return cls(*values, _canonical_digest(_bundle_document(*values)))
        except Exception:
            raise PathlightError("Pathlight diagnosis bundle is invalid") from None

    def to_mapping(self) -> dict[str, object]:
        return {**_bundle_document(self.experiment_bundle_sha256s, self.evaluation_sha256s, self.findings, self.proposals), "bundle_sha256": self.bundle_sha256}


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _normalize_bundle_values(
    experiment_bundle_sha256s: object,
    evaluation_sha256s: object,
    findings: object,
    proposals: object,
    *,
    require_sorted: bool,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[Finding, ...], tuple[Proposal, ...]]:
    if require_sorted:
        if any(type(value) is not tuple for value in (experiment_bundle_sha256s, evaluation_sha256s, findings, proposals)):
            raise ValueError
    elif any(not _is_sequence(value) for value in (experiment_bundle_sha256s, evaluation_sha256s, findings, proposals)):
        raise ValueError
    experiments = tuple(_require_sha256(value) for value in cast(Sequence[object], experiment_bundle_sha256s))
    evaluations = tuple(_require_sha256(value) for value in cast(Sequence[object], evaluation_sha256s))
    if not experiments or not evaluations or len(set(experiments)) != len(experiments) or len(set(evaluations)) != len(evaluations):
        raise ValueError
    normalized_findings = _normalize_values(findings, Finding, validate_finding, "finding_sha256", require_sorted)
    normalized_proposals = _normalize_values(proposals, Proposal, validate_proposal, "proposal_sha256", require_sorted)
    if require_sorted and (experiments != tuple(sorted(experiments)) or evaluations != tuple(sorted(evaluations))):
        raise ValueError
    return tuple(sorted(experiments)), tuple(sorted(evaluations)), cast(tuple[Finding, ...], normalized_findings), cast(tuple[Proposal, ...], normalized_proposals)


def _normalize_values(
    values: object,
    expected_type: type[object],
    validator: Callable[[Mapping[str, object]], object],
    identity: str,
    require_sorted: bool,
) -> tuple[object, ...]:
    if not _is_sequence(values):
        raise ValueError
    normalized: list[object] = []
    for value in cast(Sequence[object], values):
        if type(value) is not expected_type:
            raise ValueError
        mapping = cast(object, value).to_mapping()  # type: ignore[attr-defined]
        normalized.append(validator(mapping))
    identities = tuple(getattr(value, identity) for value in normalized)
    if len(identities) != len(set(identities)):
        raise ValueError
    ordered = tuple(sorted(normalized, key=lambda value: getattr(value, identity)))
    if require_sorted and tuple(normalized) != ordered:
        raise ValueError
    return ordered


def _validate_closure(
    experiment_bundle_sha256s: tuple[str, ...],
    evaluation_sha256s: tuple[str, ...],
    findings: tuple[Finding, ...],
    proposals: tuple[Proposal, ...],
) -> None:
    del experiment_bundle_sha256s
    evaluation_ids = set(evaluation_sha256s)
    finding_ids = {finding.finding_sha256 for finding in findings}
    observed_ids = {finding.finding_sha256 for finding in findings if finding.category == "observed"}
    for finding in findings:
        if finding.category == "observed":
            if any(value not in evaluation_ids for value in finding.evidence_sha256s + finding.counterevidence_sha256s):
                raise ValueError
        elif finding.category == "hypothesis":
            if not any(value in observed_ids for value in finding.evidence_sha256s):
                raise ValueError
            if any(value not in finding_ids for value in finding.evidence_sha256s + finding.counterevidence_sha256s):
                raise ValueError
        elif any(value not in evaluation_ids and value not in finding_ids for value in finding.evidence_sha256s + finding.counterevidence_sha256s):
            raise ValueError
    if any(proposal.finding_sha256 not in {finding.finding_sha256 for finding in findings if finding.category == "hypothesis"} for proposal in proposals):
        raise ValueError


def _bundle_document(
    experiment_bundle_sha256s: tuple[str, ...], evaluation_sha256s: tuple[str, ...], findings: tuple[Finding, ...], proposals: tuple[Proposal, ...]
) -> dict[str, object]:
    return {
        "schema": DIAGNOSIS_BUNDLE_SCHEMA,
        "experiment_bundle_sha256s": list(experiment_bundle_sha256s),
        "evaluation_sha256s": list(evaluation_sha256s),
        "findings": [finding.to_mapping() for finding in findings],
        "proposals": [proposal.to_mapping() for proposal in proposals],
    }


def _json_sha256_tuple(value: object, *, nonempty: bool = False) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise ValueError
    raw_values = cast(list[object] | tuple[object, ...], value)
    values = tuple(_require_sha256(item) for item in raw_values)
    if values != tuple(sorted(values)) or len(values) != len(set(values)) or (nonempty and not values):
        raise ValueError
    return values


def validate_diagnosis_bundle(mapping: Mapping[str, object]) -> DiagnosisBundle:
    """Validate one exact diagnosis document and its reference closure."""

    try:
        if type(mapping) is not dict or set(mapping) != _BUNDLE_FIELDS or mapping["schema"] != DIAGNOSIS_BUNDLE_SCHEMA:
            raise ValueError
        experiments = _json_sha256_tuple(mapping["experiment_bundle_sha256s"], nonempty=True)
        evaluations = _json_sha256_tuple(mapping["evaluation_sha256s"], nonempty=True)
        if type(mapping["findings"]) is not list or type(mapping["proposals"]) is not list:
            raise ValueError
        raw_findings = cast(list[object], mapping["findings"])
        raw_proposals = cast(list[object], mapping["proposals"])
        findings = tuple(validate_finding(_plain_mapping(value)) for value in raw_findings)
        proposals = tuple(validate_proposal(_plain_mapping(value)) for value in raw_proposals)
        bundle = DiagnosisBundle(experiments, evaluations, findings, proposals, _require_sha256(mapping["bundle_sha256"]))
        return bundle
    except Exception:
        raise PathlightError("Pathlight diagnosis bundle is invalid") from None


def _plain_mapping(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return value


def write_diagnosis_bundle(bundle: DiagnosisBundle, path: Path) -> None:
    """Exclusively write one private canonical diagnosis bundle."""

    encoded: bytes | None = None
    try:
        if type(bundle) is not DiagnosisBundle or not isinstance(path, Path) or path.name != DIAGNOSIS_BUNDLE_FILENAME:
            raise ValueError
        encoded = json.dumps(validate_diagnosis_bundle(bundle.to_mapping()).to_mapping(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        pass
    if encoded is None:
        raise PathlightError("Pathlight diagnosis target is invalid")
    directory_fd = -1
    descriptor = -1
    failure = False
    try:
        directory_fd = _open_parent_directory(path)
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _nofollow_flag(), 0o600, dir_fd=directory_fd)
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, encoded)
    except Exception:
        failure = True
    finally:
        for value in (descriptor, directory_fd):
            if value >= 0:
                try:
                    os.close(value)
                except Exception:
                    failure = True
    if failure:
        raise PathlightError("Pathlight diagnosis target is unavailable")


def read_diagnosis_bundle(path: Path) -> DiagnosisBundle:
    """Read one descriptor-verified private diagnosis bundle."""

    try:
        if not isinstance(path, Path) or path.name != DIAGNOSIS_BUNDLE_FILENAME:
            raise ValueError
        document = _read_diagnosis_document(path)
        if not isinstance(document, Mapping):
            raise ValueError
        return validate_diagnosis_bundle(document)
    except PathlightError:
        raise
    except Exception:
        raise PathlightError("Pathlight diagnosis source is invalid") from None


def _read_diagnosis_document(path: Path) -> object:
    directory_fd = -1
    source_fd = -1
    document: object | None = None
    failure = False
    try:
        directory_fd = _open_parent_directory(path)
        source_fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | _nofollow_flag(), dir_fd=directory_fd)
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > _MAX_DIAGNOSIS_BUNDLE_BYTES:
            raise OSError
        encoded = _read_bounded(source_fd, _MAX_DIAGNOSIS_BUNDLE_BYTES + 1)
        after = os.fstat(source_fd)
        if len(encoded) > _MAX_DIAGNOSIS_BUNDLE_BYTES or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or before.st_size != after.st_size or after.st_size != len(encoded):
            raise OSError
        document = json.loads(encoded.decode("utf-8"))
    except Exception:
        failure = True
    finally:
        for value in (source_fd, directory_fd):
            if value >= 0:
                try:
                    os.close(value)
                except Exception:
                    failure = True
    if failure or document is None:
        raise PathlightError("Pathlight diagnosis source is invalid")
    return document


def _nofollow_flag() -> int:
    flag = getattr(os, "O_NOFOLLOW", None)
    if type(flag) is not int:
        raise OSError
    return flag


def _open_parent_directory(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _nofollow_flag()
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:-1]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except Exception:
                pass
        raise


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = os.read(descriptor, min(65_536, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _write_all(descriptor: int, encoded: bytes) -> None:
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError
        remaining = remaining[written:]
