"""Dormant one-operation boundary for bounded Prime harness refinement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


FORMAT = "asterion.prime-continual-harness-bounded/v1"
NATIVE_FORMAT = "asterion.prime-continual-harness-native/v1"
RECEIPT_NAME = "prime-continual-harness-bounded-receipt.json"


class PrimeContinualHarnessExperimentError(RuntimeError):
    """Fixed public-safe failure for the bounded continual-harness gate."""


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _provider_report(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "evidence_ids",
        "host_admitted",
        "proposal_grounded",
        "provider_operations",
        "snapshot_activated",
        "status",
        "usage",
    }:
        raise ValueError
    evidence = value["evidence_ids"]
    usage = value["usage"]
    if (
        value["status"] != "PASS"
        or value["provider_operations"] != 1
        or isinstance(value["provider_operations"], bool)
        or type(evidence) is not list
        or len(evidence) != 7
        or len(set(evidence)) != 7
        or any(not isinstance(item, str) or not item for item in evidence)
        or value["proposal_grounded"] is not True
        or value["host_admitted"] is not True
        or value["snapshot_activated"] is not True
        or not isinstance(usage, Mapping)
        or set(usage) != {"aggregate_tokens", "cost_micros"}
    ):
        raise ValueError
    return value


def _validate_receipt(receipt: object) -> Mapping[str, object]:
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "evidence_input_count",
        "format",
        "host_admitted",
        "limits",
        "model_credential_reads",
        "model_selector_digest",
        "proposal_grounded",
        "provider_operations",
        "snapshot_activated",
        "status",
        "usage",
    }:
        raise ValueError
    usage = receipt["usage"]
    limits = receipt["limits"]
    if (
        receipt["format"] != FORMAT
        or receipt["status"] != "PASS"
        or not _digest(receipt["model_selector_digest"])
        or receipt["provider_operations"] != 1
        or isinstance(receipt["provider_operations"], bool)
        or receipt["model_credential_reads"] != 1
        or isinstance(receipt["model_credential_reads"], bool)
        or receipt["evidence_input_count"] != 7
        or isinstance(receipt["evidence_input_count"], bool)
        or receipt["proposal_grounded"] is not True
        or receipt["host_admitted"] is not True
        or receipt["snapshot_activated"] is not True
        or not isinstance(usage, Mapping)
        or set(usage) != {"aggregate_tokens", "cost_micros"}
        or not isinstance(limits, Mapping)
        or set(limits) != {"aggregate_tokens", "cost_micros", "deadline_ms"}
        or not _positive(usage["aggregate_tokens"])
        or not isinstance(usage["cost_micros"], int)
        or isinstance(usage["cost_micros"], bool)
        or usage["cost_micros"] < 0
        or not all(_positive(limits[key]) for key in limits)
        or usage["aggregate_tokens"] > limits["aggregate_tokens"]
        or usage["cost_micros"] > limits["cost_micros"]
    ):
        raise ValueError
    return receipt


def run_prime_continual_harness_bounded_probe(
    provider_probe: Callable[[], Mapping[str, object]],
    *,
    model_selector_digest: str,
    aggregate_token_limit: int,
    cost_limit_micros: int,
    deadline_ms: int,
) -> dict[str, object]:
    """Invoke exactly one injected provider probe and reduce its closed result."""

    try:
        if (
            not callable(provider_probe)
            or not _digest(model_selector_digest)
            or not all(
                _positive(value)
                for value in (
                    aggregate_token_limit,
                    cost_limit_micros,
                    deadline_ms,
                )
            )
        ):
            raise ValueError
        report = _provider_report(provider_probe())
        usage = report["usage"]
        assert isinstance(usage, Mapping)
        receipt = {
            "format": FORMAT,
            "status": "PASS",
            "model_selector_digest": model_selector_digest,
            "provider_operations": 1,
            "model_credential_reads": 1,
            "evidence_input_count": 7,
            "proposal_grounded": True,
            "host_admitted": True,
            "snapshot_activated": True,
            "limits": {
                "aggregate_tokens": aggregate_token_limit,
                "cost_micros": cost_limit_micros,
                "deadline_ms": deadline_ms,
            },
            "usage": dict(usage),
        }
        return dict(_validate_receipt(receipt))
    except (AssertionError, KeyError, TypeError, ValueError):
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness bounded probe is invalid"
        ) from None


def write_prime_continual_harness_bounded_receipt(
    root: Path, receipt: Mapping[str, object]
) -> Path:
    """Write the safe receipt once with mode 0600 and no overwrite."""

    descriptor: int | None = None
    try:
        if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
            raise ValueError
        value = _validate_receipt(receipt)
        target = root / RECEIPT_NAME
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        serialized = json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(serialized + "\n")
        return target
    except (OSError, TypeError, ValueError):
        if descriptor is not None:
            os.close(descriptor)
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness bounded receipt is invalid"
        ) from None


def recover_prime_continual_harness_bounded(
    native_run_root: Path,
    private_evidence_root: Path,
    *,
    model_selector_digest: str,
) -> dict[str, object]:
    """Project one already-completed native receipt without another provider call."""

    try:
        if (
            not isinstance(native_run_root, Path)
            or native_run_root.is_symlink()
            or not native_run_root.is_dir()
        ):
            raise ValueError
        native = json.loads(
            (native_run_root / "prime-continual-harness-native-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(native, Mapping) or set(native) != {
            "evidence_ids",
            "failure_stage",
            "format",
            "host_admitted",
            "proposal_grounded",
            "provider_operations",
            "snapshot_activated",
            "status",
            "usage",
        }:
            raise ValueError
        if (
            native["format"] != NATIVE_FORMAT
            or native["failure_stage"] != "public-receipt-projection"
        ):
            raise ValueError
        report = {key: native[key] for key in native if key not in {"format", "failure_stage"}}
        receipt = run_prime_continual_harness_bounded_probe(
            lambda: report,
            model_selector_digest=model_selector_digest,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        write_prime_continual_harness_bounded_receipt(
            private_evidence_root, receipt
        )
        return receipt
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness bounded recovery is invalid"
        ) from None


def run_authorized_bounded(source_root: Path, evidence_root: Path) -> Mapping[str, object]:
    """Reserved integration seam; calling it requires the explicit CLI opt-in."""

    del source_root, evidence_root
    raise PrimeContinualHarnessExperimentError(
        "Prime continual harness bounded provider integration is unavailable"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-bounded-provider", action="store_true")
    parser.add_argument("--source-root", type=Path, default=Path("3th-party/prime-agent"))
    parser.add_argument("--private-evidence-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.authorized_bounded_provider:
        return 1
    try:
        result = run_authorized_bounded(args.source_root, args.private_evidence_root)
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        return 0
    except PrimeContinualHarnessExperimentError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
