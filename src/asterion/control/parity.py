"""Closed, provider-neutral metadata for functional parity verification."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType

PARITY_LEDGER_FORMAT = "asterion.parity-ledger/v1"

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_COMPATIBILITY_ID = re.compile(r"^[a-z][a-z0-9.-]*/v[1-9][0-9]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_FORBIDDEN_KEY_FRAGMENTS = frozenset(
    {
        "credential",
        "environment",
        "executable",
        "prompt_body",
        "provider_payload",
        "raw_output",
        "secret",
        "socket",
        "token_value",
        "transcript",
    }
)

_TOP_FIELDS = {
    "format",
    "ledger_id",
    "baseline",
    "providers",
    "features",
    "scenarios",
    "evidence",
}
_BASELINE_FIELDS = {"artifact_lock", "source_commit"}
_MANDATORY_FEATURE_FIELDS = {
    "feature_id",
    "domain_id",
    "disposition",
    "description",
    "prime_evidence",
    "asterion_entrypoint",
    "primary_scenario_id",
    "compatibility_impacts",
    "provider_results",
}
_EXCLUDED_FEATURE_FIELDS = {
    "feature_id",
    "domain_id",
    "disposition",
    "description",
    "prime_evidence",
    "compatibility_impacts",
    "exclusion_reason_code",
}
_SOURCE_EVIDENCE_FIELDS = {"path", "anchors"}
_PROVIDER_RESULT_FIELDS = {"provider_id", "status", "evidence_ids"}
_SCENARIO_FIELDS = {
    "scenario_id",
    "feature_ids",
    "boundary",
    "deterministic",
    "fault_ids",
    "assertion_ids",
}
_EVIDENCE_FIELDS = {
    "evidence_id",
    "provider_id",
    "boundary",
    "status",
    "command_id",
    "baseline_commit",
    "feature_ids",
    "scenario_ids",
}

_RESULT_STATUSES = frozenset(
    {
        "missing",
        "implemented",
        "provider-free-pass",
        "bounded-pass",
        "external-limited",
    }
)
_EVIDENCE_STATUSES = frozenset(
    {"pass", "failed", "external-limited", "not-run"}
)
_BOUNDARIES = frozenset(
    {"provider-free", "real-prime-provider-free", "bounded-provider"}
)
_APPROVED_EXCLUSIONS = {
    "excluded.hidden-reasoning-identity": "private-hidden-reasoning",
    "excluded.tui-pixel-identity": "nonfunctional-pixel-identity",
}


class ParityLedgerError(ValueError):
    """Raised when parity verification metadata is invalid."""


@dataclass(frozen=True)
class ParityClaimReport:
    """Provider claim decision derived without running or authorizing work."""

    provider_id: str
    eligible: bool
    passed_feature_ids: tuple[str, ...]
    blocking_feature_ids: tuple[str, ...]
    excluded_feature_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


def validate_parity_ledger(value: object) -> Mapping[str, object]:
    """Return a recursively immutable, canonical parity ledger snapshot."""

    _reject_forbidden_keys(value)
    ledger = _closed_mapping(value, _TOP_FIELDS, "parity ledger")
    if ledger.get("format") != PARITY_LEDGER_FORMAT:
        raise ParityLedgerError("parity ledger format is invalid")
    _require_identifier(ledger.get("ledger_id"), "parity ledger identity")

    baseline = _closed_mapping(
        ledger.get("baseline"), _BASELINE_FIELDS, "parity baseline"
    )
    artifact_lock = baseline.get("artifact_lock")
    if (
        not isinstance(artifact_lock, str)
        or _COMPATIBILITY_ID.fullmatch(artifact_lock) is None
    ):
        raise ParityLedgerError("parity baseline artifact lock is invalid")
    source_commit = baseline.get("source_commit")
    if not isinstance(source_commit, str) or _COMMIT.fullmatch(source_commit) is None:
        raise ParityLedgerError("parity baseline source commit is invalid")

    providers = _require_sorted_identifiers(
        ledger.get("providers"), "parity providers", nonempty=True
    )
    features = _validate_features(ledger.get("features"), providers)
    scenarios = _validate_scenarios(ledger.get("scenarios"))
    evidence = _validate_evidence(ledger.get("evidence"), providers)
    _validate_references(
        features,
        scenarios,
        evidence,
        providers=providers,
        source_commit=source_commit,
    )
    return _freeze_mapping(ledger)


def evaluate_parity_claim(
    ledger: Mapping[str, object],
    *,
    provider_id: str,
) -> ParityClaimReport:
    """Evaluate a provider without executing it or granting authority."""

    snapshot = validate_parity_ledger(ledger)
    providers = _string_tuple(snapshot["providers"])
    features = _mapping_tuple(snapshot["features"])
    mandatory = tuple(
        feature for feature in features if feature["disposition"] == "mandatory"
    )
    excluded = tuple(
        str(feature["feature_id"])
        for feature in features
        if feature["disposition"] == "excluded"
    )
    if provider_id not in providers:
        return ParityClaimReport(
            provider_id=provider_id,
            eligible=False,
            passed_feature_ids=(),
            blocking_feature_ids=tuple(
                str(feature["feature_id"]) for feature in mandatory
            ),
            excluded_feature_ids=excluded,
            reason_codes=("provider-unknown",),
        )

    passed: list[str] = []
    blocking: list[str] = []
    reasons: set[str] = set()
    for feature in mandatory:
        results = _mapping_tuple(feature["provider_results"])
        result = next(
            item for item in results if item["provider_id"] == provider_id
        )
        status = str(result["status"])
        feature_id = str(feature["feature_id"])
        if status in {"provider-free-pass", "bounded-pass"}:
            passed.append(feature_id)
        else:
            blocking.append(feature_id)
            reasons.add(f"result-{status}")
    return ParityClaimReport(
        provider_id=provider_id,
        eligible=not blocking,
        passed_feature_ids=tuple(passed),
        blocking_feature_ids=tuple(blocking),
        excluded_feature_ids=excluded,
        reason_codes=tuple(sorted(reasons)),
    )


def _validate_features(
    value: object, providers: tuple[str, ...]
) -> tuple[Mapping[str, object], ...]:
    items = _mapping_list(value, "parity features", nonempty=True)
    identities: list[str] = []
    mandatory_count = 0
    for item in items:
        disposition = item.get("disposition")
        if disposition == "mandatory":
            feature = _closed_mapping(
                item, _MANDATORY_FEATURE_FIELDS, "mandatory parity feature"
            )
            _validate_mandatory_feature(feature, providers)
            mandatory_count += 1
        elif disposition == "excluded":
            feature = _closed_mapping(
                item, _EXCLUDED_FEATURE_FIELDS, "excluded parity feature"
            )
            _validate_excluded_feature(feature)
        else:
            raise ParityLedgerError("parity feature disposition is invalid")
        feature_id = _require_identifier(
            feature.get("feature_id"), "parity feature identity"
        )
        _require_identifier(feature.get("domain_id"), "parity feature domain")
        _require_description(feature.get("description"), "parity feature description")
        _validate_source_evidence(feature.get("prime_evidence"))
        _require_sorted_identifiers(
            feature.get("compatibility_impacts"),
            "parity feature compatibility impacts",
        )
        identities.append(feature_id)
    if identities != sorted(set(identities)):
        raise ParityLedgerError("parity features must be sorted and unique")
    if mandatory_count == 0:
        raise ParityLedgerError("parity ledger requires a mandatory feature")
    return items


def _validate_mandatory_feature(
    feature: Mapping[str, object], providers: tuple[str, ...]
) -> None:
    _require_identifier(
        feature.get("asterion_entrypoint"), "parity feature entry point"
    )
    _require_identifier(
        feature.get("primary_scenario_id"), "parity feature primary scenario"
    )
    results = _mapping_list(
        feature.get("provider_results"),
        "parity feature provider results",
        nonempty=True,
    )
    result_providers: list[str] = []
    for result in results:
        item = _closed_mapping(
            result, _PROVIDER_RESULT_FIELDS, "parity provider result"
        )
        provider_id = _require_identifier(
            item.get("provider_id"), "parity result provider"
        )
        status = item.get("status")
        if status not in _RESULT_STATUSES:
            raise ParityLedgerError("parity result status is invalid")
        evidence_ids = _require_sorted_identifiers(
            item.get("evidence_ids"), "parity result evidence identities"
        )
        if status in {"missing", "implemented"} and evidence_ids:
            raise ParityLedgerError("non-evidenced parity result has evidence")
        if status in {
            "provider-free-pass",
            "bounded-pass",
            "external-limited",
        } and not evidence_ids:
            raise ParityLedgerError("evidenced parity result lacks evidence")
        result_providers.append(provider_id)
    if tuple(result_providers) != providers:
        raise ParityLedgerError("parity result providers must match ledger providers")


def _validate_excluded_feature(feature: Mapping[str, object]) -> None:
    feature_id = _require_identifier(
        feature.get("feature_id"), "parity exclusion identity"
    )
    reason_code = _require_identifier(
        feature.get("exclusion_reason_code"), "parity exclusion reason"
    )
    if (
        feature.get("domain_id") != "excluded.nonfunctional"
        or _APPROVED_EXCLUSIONS.get(feature_id) != reason_code
    ):
        raise ParityLedgerError("parity exclusion is not approved")


def _validate_source_evidence(value: object) -> None:
    items = _mapping_list(value, "Prime source evidence", nonempty=True)
    paths: list[str] = []
    for item in items:
        evidence = _closed_mapping(
            item, _SOURCE_EVIDENCE_FIELDS, "Prime source evidence"
        )
        path = evidence.get("path")
        if not isinstance(path, str) or not _safe_prime_source_path(path):
            raise ParityLedgerError("Prime source evidence path is invalid")
        anchors = evidence.get("anchors")
        if type(anchors) not in {list, tuple}:
            raise ParityLedgerError("Prime source evidence anchors are invalid")
        assert isinstance(anchors, Sequence)
        if (
            not anchors
            or any(not isinstance(anchor, str) or not anchor for anchor in anchors)
            or tuple(anchors) != tuple(sorted(set(anchors)))
        ):
            raise ParityLedgerError("Prime source evidence anchors are invalid")
        paths.append(path)
    if paths != sorted(set(paths)):
        raise ParityLedgerError("Prime source evidence paths must be sorted and unique")


def _validate_scenarios(value: object) -> tuple[Mapping[str, object], ...]:
    items = _mapping_list(value, "parity scenarios")
    identities: list[str] = []
    for item in items:
        scenario = _closed_mapping(item, _SCENARIO_FIELDS, "parity scenario")
        identities.append(
            _require_identifier(
                scenario.get("scenario_id"), "parity scenario identity"
            )
        )
        _require_sorted_identifiers(
            scenario.get("feature_ids"), "parity scenario features", nonempty=True
        )
        if scenario.get("boundary") not in _BOUNDARIES:
            raise ParityLedgerError("parity scenario boundary is invalid")
        if scenario.get("deterministic") is not True:
            raise ParityLedgerError("parity scenario must be deterministic")
        _require_sorted_identifiers(
            scenario.get("fault_ids"), "parity scenario faults"
        )
        _require_sorted_identifiers(
            scenario.get("assertion_ids"),
            "parity scenario assertions",
            nonempty=True,
        )
    if identities != sorted(set(identities)):
        raise ParityLedgerError("parity scenarios must be sorted and unique")
    return items


def _validate_evidence(
    value: object, providers: tuple[str, ...]
) -> tuple[Mapping[str, object], ...]:
    items = _mapping_list(value, "parity evidence")
    identities: list[str] = []
    for item in items:
        evidence = _closed_mapping(item, _EVIDENCE_FIELDS, "parity evidence")
        identities.append(
            _require_identifier(
                evidence.get("evidence_id"), "parity evidence identity"
            )
        )
        provider_id = _require_identifier(
            evidence.get("provider_id"), "parity evidence provider"
        )
        if provider_id not in providers:
            raise ParityLedgerError("parity evidence provider is not declared")
        if evidence.get("boundary") not in _BOUNDARIES:
            raise ParityLedgerError("parity evidence boundary is invalid")
        if evidence.get("status") not in _EVIDENCE_STATUSES:
            raise ParityLedgerError("parity evidence status is invalid")
        _require_identifier(evidence.get("command_id"), "parity evidence command")
        baseline_commit = evidence.get("baseline_commit")
        if (
            not isinstance(baseline_commit, str)
            or _COMMIT.fullmatch(baseline_commit) is None
        ):
            raise ParityLedgerError("parity evidence baseline is invalid")
        _require_sorted_identifiers(
            evidence.get("feature_ids"), "parity evidence features", nonempty=True
        )
        _require_sorted_identifiers(
            evidence.get("scenario_ids"), "parity evidence scenarios", nonempty=True
        )
    if identities != sorted(set(identities)):
        raise ParityLedgerError("parity evidence must be sorted and unique")
    return items


def _validate_references(
    features: tuple[Mapping[str, object], ...],
    scenarios: tuple[Mapping[str, object], ...],
    evidence: tuple[Mapping[str, object], ...],
    *,
    providers: tuple[str, ...],
    source_commit: str,
) -> None:
    feature_by_id = {str(item["feature_id"]): item for item in features}
    mandatory_by_id = {
        feature_id: item
        for feature_id, item in feature_by_id.items()
        if item["disposition"] == "mandatory"
    }
    scenario_by_id = {str(item["scenario_id"]): item for item in scenarios}
    evidence_by_id = {str(item["evidence_id"]): item for item in evidence}

    primary_scenarios: list[str] = []
    for feature_id, feature in mandatory_by_id.items():
        scenario_id = str(feature["primary_scenario_id"])
        if scenario_id != f"prime-parity.{feature_id}":
            raise ParityLedgerError("parity feature primary scenario identity is invalid")
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None or feature_id not in _string_tuple(
            scenario["feature_ids"]
        ):
            raise ParityLedgerError("parity feature primary scenario is unresolved")
        primary_scenarios.append(scenario_id)
    if len(primary_scenarios) != len(set(primary_scenarios)):
        raise ParityLedgerError("parity primary scenarios must be unique")

    for scenario in scenarios:
        if any(
            feature_id not in mandatory_by_id
            for feature_id in _string_tuple(scenario["feature_ids"])
        ):
            raise ParityLedgerError("parity scenario feature reference is unresolved")

    for record in evidence:
        if record["baseline_commit"] != source_commit:
            raise ParityLedgerError("parity evidence baseline does not match")
        if any(
            feature_id not in mandatory_by_id
            for feature_id in _string_tuple(record["feature_ids"])
        ):
            raise ParityLedgerError("parity evidence feature reference is unresolved")
        if any(
            scenario_id not in scenario_by_id
            for scenario_id in _string_tuple(record["scenario_ids"])
        ):
            raise ParityLedgerError("parity evidence scenario reference is unresolved")

    for feature_id, feature in mandatory_by_id.items():
        scenario_id = str(feature["primary_scenario_id"])
        scenario = scenario_by_id[scenario_id]
        for result in _mapping_tuple(feature["provider_results"]):
            if result["provider_id"] not in providers:
                raise ParityLedgerError("parity result provider is unresolved")
            _validate_result_evidence(
                result,
                feature_id=feature_id,
                scenario_id=scenario_id,
                required_boundary=str(scenario["boundary"]),
                evidence_by_id=evidence_by_id,
            )


def _validate_result_evidence(
    result: Mapping[str, object],
    *,
    feature_id: str,
    scenario_id: str,
    required_boundary: str,
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    status = str(result["status"])
    if status in {"missing", "implemented"}:
        return
    records: list[Mapping[str, object]] = []
    for evidence_id in _string_tuple(result["evidence_ids"]):
        record = evidence_by_id.get(evidence_id)
        if record is None:
            raise ParityLedgerError("parity result evidence reference is unresolved")
        if (
            record["provider_id"] != result["provider_id"]
            or feature_id not in _string_tuple(record["feature_ids"])
            or scenario_id not in _string_tuple(record["scenario_ids"])
        ):
            raise ParityLedgerError("parity result evidence coverage is invalid")
        records.append(record)
    if status == "external-limited":
        if any(record["status"] != "external-limited" for record in records):
            raise ParityLedgerError("external-limited parity evidence is invalid")
        return
    if any(record["status"] != "pass" for record in records):
        raise ParityLedgerError("passing parity result evidence is invalid")
    if status == "bounded-pass":
        allowed_boundaries = {"bounded-provider"}
    elif required_boundary == "provider-free":
        allowed_boundaries = set(_BOUNDARIES)
    elif required_boundary == "real-prime-provider-free":
        allowed_boundaries = {"real-prime-provider-free", "bounded-provider"}
    else:
        allowed_boundaries = set()
    if not records or any(
        str(record["boundary"]) not in allowed_boundaries for record in records
    ):
        raise ParityLedgerError("parity result evidence boundary is insufficient")


def _reject_forbidden_keys(value: object) -> None:
    if type(value) in {dict, _MAPPING_PROXY_TYPE}:
        assert isinstance(value, Mapping)
        for key, item in value.items():
            if not isinstance(key, str):
                raise ParityLedgerError("parity metadata key is invalid")
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise ParityLedgerError("parity metadata contains a forbidden field")
            _reject_forbidden_keys(item)
    elif type(value) in {list, tuple}:
        assert isinstance(value, Sequence)
        for item in value:
            _reject_forbidden_keys(item)
    elif isinstance(value, Mapping) or (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        raise ParityLedgerError("parity metadata container is invalid")


def _closed_mapping(
    value: object, fields: set[str], label: str
) -> Mapping[str, object]:
    if (
        type(value) not in {dict, _MAPPING_PROXY_TYPE}
        or not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != fields
    ):
        raise ParityLedgerError(f"{label} fields are invalid")
    return value


def _mapping_list(
    value: object, label: str, *, nonempty: bool = False
) -> tuple[Mapping[str, object], ...]:
    if (
        type(value) not in {list, tuple}
        or not isinstance(value, Sequence)
        or (nonempty and not value)
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise ParityLedgerError(f"{label} are invalid")
    return tuple(value)  # type: ignore[arg-type]


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ParityLedgerError(f"{label} is invalid")
    return value


def _require_description(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ParityLedgerError(f"{label} is invalid")


def _require_sorted_identifiers(
    value: object,
    label: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if (
        type(value) not in {list, tuple}
        or not isinstance(value, Sequence)
        or (nonempty and not value)
    ):
        raise ParityLedgerError(f"{label} must be sorted and unique")
    items = tuple(value)
    if any(
        not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None
        for item in items
    ):
        raise ParityLedgerError(f"{label} must be sorted and unique")
    identifiers = tuple(item for item in items if isinstance(item, str))
    if identifiers != tuple(sorted(set(identifiers))):
        raise ParityLedgerError(f"{label} must be sorted and unique")
    return identifiers


def _safe_prime_source_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        value == path.as_posix()
        and not path.is_absolute()
        and len(path.parts) >= 2
        and path.parts[0] == "packages"
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _mapping_tuple(value: object) -> tuple[Mapping[str, object], ...]:
    if (
        type(value) not in {list, tuple}
        or not isinstance(value, Sequence)
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise ParityLedgerError("validated parity mapping sequence is invalid")
    return tuple(value)  # type: ignore[arg-type]


def _string_tuple(value: object) -> tuple[str, ...]:
    if (
        type(value) not in {list, tuple}
        or not isinstance(value, Sequence)
        or any(not isinstance(item, str) for item in value)
    ):
        raise ParityLedgerError("validated parity identity sequence is invalid")
    return tuple(value)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if type(value) in {dict, _MAPPING_PROXY_TYPE}:
        assert isinstance(value, Mapping)
        return _freeze_mapping(value)
    if type(value) in {list, tuple}:
        assert isinstance(value, Sequence)
        return tuple(_freeze(item) for item in value)
    return value
