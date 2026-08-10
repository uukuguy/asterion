"""Validate the closed Prime parity inventory without executing providers."""

from __future__ import annotations

import argparse
import json
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from asterion.control.parity import (
    ParityLedgerError,
    evaluate_parity_claim,
    validate_parity_ledger,
)
try:
    from tools.setup_prime_agent import (
        LOCK_FORMAT,
        PrimeSetupError,
        verify_prime_checkout,
    )
except ModuleNotFoundError:  # Direct ``python tools/check_prime_parity.py``.
    from setup_prime_agent import (  # type: ignore[no-redef]
        LOCK_FORMAT,
        PrimeSetupError,
        verify_prime_checkout,
    )


PRIME_PROVIDER_ID = "asterion.prime-gateway"
MAX_EVIDENCE_FILE_BYTES = 2 * 1024 * 1024


class PrimeParityCheckError(RuntimeError):
    """Raised with a fixed, redacted message when source evidence is unsafe."""


@dataclass(frozen=True, repr=False)
class PrimeSourceEvidenceReport:
    source_commit: str
    feature_count: int
    evidence_record_count: int
    file_count: int
    anchor_count: int


def default_ledger_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json"
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


def verify_prime_source_evidence(
    ledger: Mapping[str, object],
    *,
    source_root: Path,
) -> PrimeSourceEvidenceReport:
    """Verify only explicitly declared source files at the pinned clean revision."""

    snapshot = validate_parity_ledger(ledger)
    baseline = _mapping(snapshot.get("baseline"))
    if baseline.get("artifact_lock") != LOCK_FORMAT:
        raise PrimeParityCheckError("Prime parity baseline is invalid")

    try:
        setup_report = verify_prime_checkout(source_root)
    except PrimeSetupError:
        raise PrimeParityCheckError(
            "Prime parity source checkout is invalid"
        ) from None
    if setup_report.source_commit != baseline.get("source_commit"):
        raise PrimeParityCheckError("Prime parity source revision is invalid")

    root = _exact_directory(source_root)
    features = _mapping_sequence(snapshot.get("features"))
    evidence_record_count = 0
    anchor_count = 0
    declared_paths: set[str] = set()
    for feature in features:
        evidence_records = _mapping_sequence(feature.get("prime_evidence"))
        evidence_record_count += len(evidence_records)
        for record in evidence_records:
            relative = record.get("path")
            anchors = record.get("anchors")
            if not isinstance(relative, str):
                raise PrimeParityCheckError("Prime parity source evidence is invalid")
            content = _read_declared_file(root, relative)
            if not isinstance(anchors, tuple) or any(
                not isinstance(anchor, str) or anchor not in content
                for anchor in anchors
            ):
                raise PrimeParityCheckError("Prime parity source evidence is invalid")
            declared_paths.add(relative)
            anchor_count += len(anchors)

    return PrimeSourceEvidenceReport(
        source_commit=setup_report.source_commit,
        feature_count=len(features),
        evidence_record_count=evidence_record_count,
        file_count=len(declared_paths),
        anchor_count=anchor_count,
    )


def _exact_directory(value: Path) -> Path:
    try:
        if not isinstance(value, Path) or value.is_symlink():
            raise OSError
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise OSError
        return root
    except (OSError, RuntimeError):
        raise PrimeParityCheckError(
            "Prime parity source checkout is invalid"
        ) from None


def _read_declared_file(root: Path, relative: str) -> str:
    try:
        source_path = PurePosixPath(relative)
        if (
            source_path.is_absolute()
            or source_path.parts[:1] != ("packages",)
            or any(part in {"", ".", ".."} for part in source_path.parts)
        ):
            raise OSError
        candidate = root
        for index, part in enumerate(source_path.parts):
            candidate /= part
            metadata = candidate.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise OSError
            if index < len(source_path.parts) - 1 and not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise OSError
        metadata = candidate.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_EVIDENCE_FILE_BYTES
        ):
            raise OSError
        return candidate.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        raise PrimeParityCheckError("Prime parity source evidence is invalid") from None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PrimeParityCheckError("Prime parity inventory is invalid")
    return value


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


def _claim_report(ledger: Mapping[str, object]) -> tuple[dict[str, object], int]:
    decision = evaluate_parity_claim(ledger, provider_id=PRIME_PROVIDER_ID)
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


def _write_report(report: Mapping[str, object]) -> None:
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--claim",
        required=True,
        choices=("inventory", "verified-system-parity"),
    )
    parser.add_argument("--source-root", type=Path)
    arguments = parser.parse_args(argv)
    try:
        ledger = load_prime_parity_ledger()
        source_verified = False
        if arguments.source_root is not None:
            verify_prime_source_evidence(
                ledger,
                source_root=arguments.source_root,
            )
            source_verified = True
        if arguments.claim == "inventory":
            _write_report(
                _inventory_report(ledger, source_verified=source_verified)
            )
            return 0
        report, exit_code = _claim_report(ledger)
        _write_report(report)
        return exit_code
    except (ParityLedgerError, PrimeParityCheckError):
        _write_report(
            {
                "application_operations": 0,
                "claim": arguments.claim,
                "provider_operations": 0,
                "reason_codes": ("inventory-invalid",),
                "status": "ERROR",
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
