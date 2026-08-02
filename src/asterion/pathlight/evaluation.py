"""Versioned, public-safe Pathlight metric evaluation records."""

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
from typing import Literal

from asterion.pathlight.protocol import PathlightError


EVALUATION_BUNDLE_SCHEMA = "asterion.pathlight-evaluations/v1"
EVALUATION_BUNDLE_FILENAME = "pathlight-evaluations.json"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_METRIC_NAMES = frozenset(
    {
        "accuracy",
        "ndcg-at-10",
        "artifact-count",
        "content-length",
        "cost-microunits",
        "coverage",
        "duration-ns",
        "error-count",
        "evaluation-score",
        "failure-rate",
        "input-tokens",
        "output-tokens",
        "success-rate",
        "tool-call-count",
    }
)
METRIC_NAMES = _METRIC_NAMES
_UNITS = frozenset({"ratio", "count", "microunits", "tokens", "nanoseconds"})
_RECORD_FIELDS = frozenset(
    {
        "trace_sha256",
        "metric_contract_sha256",
        "dataset_snapshot_sha256",
        "scope_sha256",
        "value_microunits",
        "selected_count",
        "total_count",
        "status",
        "evaluation_sha256",
    }
)
_METRIC_CONTRACT_FIELDS = frozenset(
    {
        "metric_name",
        "unit",
        "higher_is_better",
        "contract_version",
        "metric_contract_sha256",
    }
)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PathlightError(f"Pathlight evaluation {field_name} is invalid")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PathlightError(f"Pathlight evaluation {field_name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class MetricContract:
    """A versioned definition of one supported public metric."""

    metric_name: str
    unit: str
    higher_is_better: bool
    contract_version: str
    metric_contract_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.metric_name) is not str or self.metric_name not in _METRIC_NAMES:
            raise PathlightError("Pathlight metric name is invalid")
        if type(self.unit) is not str or self.unit not in _UNITS:
            raise PathlightError("Pathlight metric unit is invalid")
        if not isinstance(self.higher_is_better, bool):
            raise PathlightError("Pathlight metric direction is invalid")
        if type(self.contract_version) is not str or _SEMVER.fullmatch(
            self.contract_version
        ) is None:
            raise PathlightError("Pathlight metric contract version is invalid")
        object.__setattr__(self, "metric_contract_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "contract_version": self.contract_version,
        }

    def to_mapping(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible metric contract."""

        return {**self._unsigned_mapping(), "metric_contract_sha256": self.metric_contract_sha256}


def validate_metric_contract(mapping: Mapping[str, object]) -> MetricContract:
    """Validate one exact metric contract mapping."""

    if not isinstance(mapping, Mapping) or set(mapping) != _METRIC_CONTRACT_FIELDS:
        raise PathlightError("Pathlight metric contract is invalid")
    contract = MetricContract(
        metric_name=mapping["metric_name"],  # type: ignore[arg-type]
        unit=mapping["unit"],  # type: ignore[arg-type]
        higher_is_better=mapping["higher_is_better"],  # type: ignore[arg-type]
        contract_version=mapping["contract_version"],  # type: ignore[arg-type]
    )
    supplied = _require_sha256(mapping["metric_contract_sha256"], "metric contract digest")
    if not hmac.compare_digest(supplied, contract.metric_contract_sha256):
        raise PathlightError("Pathlight metric contract digest mismatches")
    return contract


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """An immutable evaluation value bound to exact public identities."""

    trace_sha256: str
    metric_contract_sha256: str
    dataset_snapshot_sha256: str
    scope_sha256: str
    value_microunits: int | None
    selected_count: int
    total_count: int
    status: Literal["observed", "recovered", "missing"]
    evaluation_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.trace_sha256, "trace digest")
        _require_sha256(self.metric_contract_sha256, "metric contract digest")
        _require_sha256(self.dataset_snapshot_sha256, "dataset snapshot digest")
        _require_sha256(self.scope_sha256, "scope digest")
        selected_count = _require_nonnegative_int(self.selected_count, "selected count")
        total_count = _require_nonnegative_int(self.total_count, "total count")
        if selected_count > total_count:
            raise PathlightError("Pathlight evaluation coverage is invalid")
        if type(self.status) is not str or self.status not in {
            "observed",
            "recovered",
            "missing",
        }:
            raise PathlightError("Pathlight evaluation status is invalid")
        if self.status == "missing":
            if self.value_microunits is not None:
                raise PathlightError("Pathlight missing evaluation value is invalid")
        elif isinstance(self.value_microunits, bool) or not isinstance(self.value_microunits, int):
            raise PathlightError("Pathlight evaluation value is invalid")
        object.__setattr__(self, "evaluation_sha256", _canonical_digest(self._unsigned_mapping()))

    def _unsigned_mapping(self) -> dict[str, object]:
        return {
            "trace_sha256": self.trace_sha256,
            "metric_contract_sha256": self.metric_contract_sha256,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "scope_sha256": self.scope_sha256,
            "value_microunits": self.value_microunits,
            "selected_count": self.selected_count,
            "total_count": self.total_count,
            "status": self.status,
        }

    def to_mapping(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible evaluation record."""

        return {**self._unsigned_mapping(), "evaluation_sha256": self.evaluation_sha256}


@dataclass(frozen=True, slots=True)
class EvaluationComparison:
    """The exact comparability result for two evaluation records."""

    status: Literal["comparable", "not-comparable"]
    delta_microunits: int | None
    reasons: tuple[str, ...]

    @classmethod
    def comparable(
        cls, baseline: EvaluationRecord, candidate: EvaluationRecord
    ) -> EvaluationComparison:
        assert baseline.value_microunits is not None
        assert candidate.value_microunits is not None
        return cls("comparable", candidate.value_microunits - baseline.value_microunits, ())

    @classmethod
    def not_comparable(cls, reasons: Sequence[str]) -> EvaluationComparison:
        return cls("not-comparable", None, tuple(reasons))


@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    """A verified immutable collection of sorted evaluation records."""

    metric_contracts: tuple[MetricContract, ...]
    evaluations: tuple[EvaluationRecord, ...]
    bundle_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.metric_contracts, tuple) or any(
            not isinstance(contract, MetricContract) for contract in self.metric_contracts
        ):
            raise PathlightError("Pathlight evaluation bundle contracts are invalid")
        try:
            contracts = tuple(
                validate_metric_contract(contract.to_mapping())
                for contract in self.metric_contracts
            )
        except (PathlightError, TypeError, ValueError):
            raise PathlightError("Pathlight evaluation bundle contracts are invalid") from None
        object.__setattr__(self, "metric_contracts", contracts)
        contract_ids = tuple(
            contract.metric_contract_sha256 for contract in contracts
        )
        if contract_ids != tuple(sorted(contract_ids)) or len(set(contract_ids)) != len(contract_ids):
            raise PathlightError("Pathlight evaluation bundle contracts are invalid")
        if not isinstance(self.evaluations, tuple) or any(
            not isinstance(record, EvaluationRecord) for record in self.evaluations
        ):
            raise PathlightError("Pathlight evaluation bundle is invalid")
        try:
            evaluations = tuple(
                validate_evaluation_record(record.to_mapping())
                for record in self.evaluations
            )
        except (PathlightError, TypeError, ValueError):
            raise PathlightError("Pathlight evaluation bundle is invalid") from None
        object.__setattr__(self, "evaluations", evaluations)
        identities = tuple(record.evaluation_sha256 for record in evaluations)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise PathlightError("Pathlight evaluation bundle identities are invalid")
        if any(
            record.metric_contract_sha256 not in set(contract_ids)
            for record in evaluations
        ):
            raise PathlightError("Pathlight evaluation record contract is unresolved")
        supplied = _require_sha256(self.bundle_sha256, "bundle digest")
        expected = _canonical_digest(
            {
                "schema": EVALUATION_BUNDLE_SCHEMA,
                "metric_contracts": [
                    contract.to_mapping() for contract in self.metric_contracts
                ],
                "evaluations": [record.to_mapping() for record in self.evaluations],
            }
        )
        if not hmac.compare_digest(supplied, expected):
            raise PathlightError("Pathlight evaluation bundle digest mismatches")


def validate_evaluation_record(mapping: Mapping[str, object]) -> EvaluationRecord:
    """Validate one exact record mapping and return its frozen canonical value."""

    if not isinstance(mapping, Mapping) or set(mapping) != _RECORD_FIELDS:
        raise PathlightError("Pathlight evaluation record is invalid")
    record = EvaluationRecord(
        trace_sha256=_require_sha256(mapping["trace_sha256"], "trace digest"),
        metric_contract_sha256=_require_sha256(
            mapping["metric_contract_sha256"], "metric contract digest"
        ),
        dataset_snapshot_sha256=_require_sha256(
            mapping["dataset_snapshot_sha256"], "dataset snapshot digest"
        ),
        scope_sha256=_require_sha256(mapping["scope_sha256"], "scope digest"),
        value_microunits=mapping["value_microunits"],  # type: ignore[arg-type]
        selected_count=mapping["selected_count"],  # type: ignore[arg-type]
        total_count=mapping["total_count"],  # type: ignore[arg-type]
        status=mapping["status"],  # type: ignore[arg-type]
    )
    supplied = _require_sha256(mapping["evaluation_sha256"], "record digest")
    if not hmac.compare_digest(supplied, record.evaluation_sha256):
        raise PathlightError("Pathlight evaluation record digest mismatches")
    return record


def compare_evaluations(
    baseline: EvaluationRecord, candidate: EvaluationRecord
) -> EvaluationComparison:
    """Compare values only where their contract, snapshot, scope, and coverage match."""

    if not isinstance(baseline, EvaluationRecord) or not isinstance(candidate, EvaluationRecord):
        raise PathlightError("Pathlight evaluation comparison is invalid")
    reasons = _comparability_reasons(baseline, candidate)
    return (
        EvaluationComparison.not_comparable(reasons)
        if reasons
        else EvaluationComparison.comparable(baseline, candidate)
    )


def _comparability_reasons(
    baseline: EvaluationRecord, candidate: EvaluationRecord
) -> tuple[str, ...]:
    fields = (
        "metric_contract_sha256",
        "dataset_snapshot_sha256",
        "scope_sha256",
        "selected_count",
        "total_count",
    )
    reasons = tuple(field for field in fields if getattr(baseline, field) != getattr(candidate, field))
    if baseline.value_microunits is None:
        reasons += ("baseline.value_microunits",)
    if candidate.value_microunits is None:
        reasons += ("candidate.value_microunits",)
    return reasons


def write_evaluation_bundle(
    path: Path,
    records: Sequence[EvaluationRecord],
    metric_contracts: Sequence[MetricContract],
) -> None:
    """Exclusively write sorted, validated records to the one canonical filename."""

    if (
        path.name != EVALUATION_BUNDLE_FILENAME
        or not path.parent.is_dir()
        or path.exists()
        or path.is_symlink()
    ):
        raise PathlightError("Pathlight evaluation target is invalid")
    if any(not isinstance(record, EvaluationRecord) for record in records):
        raise PathlightError("Pathlight evaluation record is invalid")
    if any(not isinstance(contract, MetricContract) for contract in metric_contracts):
        raise PathlightError("Pathlight metric contract is invalid")
    contracts = tuple(
        sorted(
            (
                validate_metric_contract(contract.to_mapping())
                for contract in metric_contracts
            ),
            key=lambda contract: contract.metric_contract_sha256,
        )
    )
    if len({contract.metric_contract_sha256 for contract in contracts}) != len(contracts):
        raise PathlightError("Pathlight metric contract identity is duplicated")
    evaluations = tuple(
        sorted(
            (validate_evaluation_record(record.to_mapping()) for record in records),
            key=lambda record: record.evaluation_sha256,
        )
    )
    if len({record.evaluation_sha256 for record in evaluations}) != len(evaluations):
        raise PathlightError("Pathlight evaluation identity is duplicated")
    if any(
        record.metric_contract_sha256
        not in {contract.metric_contract_sha256 for contract in contracts}
        for record in evaluations
    ):
        raise PathlightError("Pathlight evaluation record contract is unresolved")
    document: dict[str, object] = {
        "schema": EVALUATION_BUNDLE_SCHEMA,
        "metric_contracts": [contract.to_mapping() for contract in contracts],
        "evaluations": [record.to_mapping() for record in evaluations],
    }
    document["bundle_sha256"] = _canonical_digest(document)
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    descriptor = -1
    failure: OSError | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
    except OSError as error:
        failure = error
    else:
        try:
            _write_all(descriptor, encoded)
        except OSError as error:
            failure = error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError as error:
                if failure is None:
                    failure = error
    if failure is not None:
        raise PathlightError("Pathlight evaluation target is unavailable") from failure


def _write_all(descriptor: int, encoded: bytes) -> None:
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Pathlight evaluation target write is incomplete")
        remaining = remaining[written:]


def read_evaluation_bundle(path: Path) -> EvaluationBundle:
    """Read one descriptor-verified canonical evaluation bundle."""

    if path.name != EVALUATION_BUNDLE_FILENAME:
        raise PathlightError("Pathlight evaluation source is invalid")
    return _validate_bundle(_read_bundle_document(path))


def _read_bundle_document(path: Path) -> object:
    directory_fd = -1
    source_fd = -1
    try:
        absolute = path.absolute()
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if not isinstance(nofollow, int):
            raise OSError("no-follow descriptor opening is unavailable")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        directory_fd = os.open(absolute.anchor, directory_flags)
        for component in absolute.parts[1:-1]:
            next_directory_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_directory_fd
        source_fd = os.open(path.name, os.O_RDONLY | nofollow, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise OSError("Pathlight evaluation source is not a regular file")
        with os.fdopen(source_fd, "rb") as source:
            source_fd = -1
            return json.loads(source.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PathlightError("Pathlight evaluation source is invalid") from error
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _validate_bundle(document: object) -> EvaluationBundle:
    if not isinstance(document, Mapping) or set(document) != {
        "schema",
        "metric_contracts",
        "evaluations",
        "bundle_sha256",
    }:
        raise PathlightError("Pathlight evaluation bundle is invalid")
    if (
        type(document["schema"]) is not str
        or document["schema"] != EVALUATION_BUNDLE_SCHEMA
    ):
        raise PathlightError("Pathlight evaluation bundle schema is invalid")
    contracts_value = document["metric_contracts"]
    evaluations_value = document["evaluations"]
    if not isinstance(contracts_value, list) or not isinstance(evaluations_value, list):
        raise PathlightError("Pathlight evaluation bundle evaluations are invalid")
    supplied = _require_sha256(document["bundle_sha256"], "bundle digest")
    expected = _canonical_digest(
        {
            "schema": document["schema"],
            "metric_contracts": contracts_value,
            "evaluations": evaluations_value,
        }
    )
    if not hmac.compare_digest(supplied, expected):
        raise PathlightError("Pathlight evaluation bundle digest mismatches")
    contracts = tuple(
        validate_metric_contract(item)
        for item in contracts_value
        if isinstance(item, Mapping)
    )
    if len(contracts) != len(contracts_value):
        raise PathlightError("Pathlight metric contract is invalid")
    records = tuple(validate_evaluation_record(item) for item in evaluations_value if isinstance(item, Mapping))
    if len(records) != len(evaluations_value):
        raise PathlightError("Pathlight evaluation record is invalid")
    return EvaluationBundle(contracts, records, supplied)
