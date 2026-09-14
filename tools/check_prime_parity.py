"""Validate the closed Prime parity inventory without executing providers."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from asterion.control.parity import (
    ParityLedgerError,
    evaluate_parity_claim,
    validate_parity_ledger,
)


class PrimeParityCheckError(RuntimeError):
    """Raised with a fixed, redacted message when source evidence is unsafe."""


class PrimeParitySelectionError(RuntimeError):
    """Raised without rendering invalid command-line selection values."""


def default_ledger_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/prime-parity/v1/native-only.json"
    )


def load_prime_parity_ledger(
    path: Path | None = None,
) -> Mapping[str, object]:
    """Load and validate the exact development inventory."""

    try:
        value = json.loads((path or default_ledger_path()).read_text(encoding="utf-8"))
        return validate_parity_ledger(value)
    except (OSError, json.JSONDecodeError, ParityLedgerError):
        raise PrimeParityCheckError("Prime parity inventory is invalid") from None


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PrimeParityCheckError("Prime parity inventory is invalid")
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise PrimeParityCheckError("Prime parity inventory is invalid")
    return tuple(item for item in items if isinstance(item, Mapping))


def _inventory_report(
    ledger: Mapping[str, object],
    *,
    source_verified: bool,
) -> dict[str, object]:
    features = _mapping_sequence(ledger.get("features"))
    scenarios = _mapping_sequence(ledger.get("scenarios"))
    mandatory_count = sum(
        feature.get("disposition") == "mandatory" for feature in features
    )
    return {
        "application_operations": 0,
        "claim": "inventory",
        "excluded_feature_count": len(features) - mandatory_count,
        "feature_count": len(features),
        "ledger_id": ledger["ledger_id"],
        "mandatory_feature_count": mandatory_count,
        "provider_operations": 0,
        "scenario_count": len(scenarios),
        "source_verified": source_verified,
        "status": "PASS",
    }


def _claim_report(
    ledger: Mapping[str, object],
    *,
    provider_id: str,
) -> tuple[dict[str, object], int]:
    decision = evaluate_parity_claim(ledger, provider_id=provider_id)
    status = "PASS" if decision.eligible else "BLOCKED"
    report: dict[str, object] = {
        "application_operations": 0,
        "blocking_feature_count": len(decision.blocking_feature_ids),
        "blocking_feature_ids": decision.blocking_feature_ids,
        "claim": "verified-system-parity",
        "excluded_feature_count": len(decision.excluded_feature_ids),
        "passed_feature_count": len(decision.passed_feature_ids),
        "provider_operations": 0,
        "reason_codes": decision.reason_codes,
        "status": status,
    }
    return report, 0 if decision.eligible else 1


def _feature_claim_report(
    ledger: Mapping[str, object],
    *,
    provider_id: str,
    domain_id: str | None,
    feature_selection: str | None,
) -> tuple[dict[str, object], int]:
    if (domain_id is None) == (feature_selection is None):
        raise PrimeParitySelectionError("Prime parity selection is invalid")
    providers = ledger.get("providers")
    if not isinstance(providers, tuple) or provider_id not in providers:
        raise PrimeParitySelectionError("Prime parity selection is invalid")
    features = _mapping_sequence(ledger.get("features"))
    mandatory = {
        str(feature["feature_id"]): feature
        for feature in features
        if feature.get("disposition") == "mandatory"
    }
    selection_kind: str
    selection_id: str | None = None
    if domain_id is not None:
        selected = tuple(
            feature_id
            for feature_id, feature in mandatory.items()
            if feature.get("domain_id") == domain_id
        )
        if not selected:
            raise PrimeParitySelectionError("Prime parity selection is invalid")
        selection_kind = "domain"
        selection_id = domain_id
    else:
        assert feature_selection is not None
        requested = tuple(feature_selection.split(","))
        if (
            not requested
            or any(not item or item not in mandatory for item in requested)
            or len(requested) != len(set(requested))
        ):
            raise PrimeParitySelectionError("Prime parity selection is invalid")
        selected = tuple(sorted(requested))
        selection_kind = "features"

    decision = evaluate_parity_claim(ledger, provider_id=provider_id)
    passed_set = set(decision.passed_feature_ids)
    blocking_set = set(decision.blocking_feature_ids)
    passed = tuple(feature_id for feature_id in selected if feature_id in passed_set)
    blocking = tuple(
        feature_id for feature_id in selected if feature_id in blocking_set
    )
    if len(passed) + len(blocking) != len(selected):
        raise PrimeParitySelectionError("Prime parity selection is invalid")
    blocking_statuses: set[str] = set()
    for feature_id in blocking:
        provider_results = tuple(
            result
            for result in _mapping_sequence(
                mandatory[feature_id].get("provider_results")
            )
            if result.get("provider_id") == provider_id
        )
        if len(provider_results) != 1:
            raise PrimeParitySelectionError("Prime parity selection is invalid")
        blocking_statuses.add(str(provider_results[0]["status"]))
    status = "PASS" if not blocking else "BLOCKED"
    report: dict[str, object] = {
        "application_operations": 0,
        "blocking_feature_count": len(blocking),
        "blocking_feature_ids": blocking,
        "claim": "feature-parity",
        "passed_feature_count": len(passed),
        "provider_operations": 0,
        "reason_codes": tuple(
            f"result-{result_status}"
            for result_status in sorted(blocking_statuses)
        ),
        "selected_feature_count": len(selected),
        "selected_feature_ids": selected,
        "selection_kind": selection_kind,
        "status": status,
    }
    if selection_id is not None:
        report["selection_id"] = selection_id
    return report, 0 if not blocking else 1


def _write_report(report: Mapping[str, object]) -> None:
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--claim",
        choices=("inventory", "verified-system-parity"),
    )
    parser.add_argument("--domain")
    parser.add_argument("--features")
    parser.add_argument("--provider", default="asterion.native")
    arguments = parser.parse_args(argv)
    try:
        ledger = load_prime_parity_ledger()
        source_verified = False
        if arguments.claim == "inventory":
            if arguments.domain is not None or arguments.features is not None:
                raise PrimeParitySelectionError(
                    "Prime parity selection is invalid"
                )
            _write_report(
                _inventory_report(ledger, source_verified=source_verified)
            )
            return 0
        if arguments.claim == "verified-system-parity":
            if arguments.domain is not None or arguments.features is not None:
                raise PrimeParitySelectionError(
                    "Prime parity selection is invalid"
                )
            report, exit_code = _claim_report(
                ledger,
                provider_id=arguments.provider,
            )
        elif arguments.claim is None:
            report, exit_code = _feature_claim_report(
                ledger,
                provider_id=arguments.provider,
                domain_id=arguments.domain,
                feature_selection=arguments.features,
            )
        else:
            raise PrimeParitySelectionError("Prime parity selection is invalid")
        _write_report(report)
        return exit_code
    except PrimeParitySelectionError:
        _write_report(
            {
                "application_operations": 0,
                "claim": "feature-parity",
                "provider_operations": 0,
                "reason_codes": ("selection-invalid",),
                "status": "ERROR",
            }
        )
        return 2
    except (ParityLedgerError, PrimeParityCheckError):
        _write_report(
            {
                "application_operations": 0,
                "claim": arguments.claim or "feature-parity",
                "provider_operations": 0,
                "reason_codes": ("inventory-invalid",),
                "status": "ERROR",
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
