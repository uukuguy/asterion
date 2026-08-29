"""One-call bounded Prime autonomy probe with body-free evidence reduction."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from asterion.control.journal import MemoryCanonicalJournal, JournalRecord
from asterion.control.long_running import (
    HeartbeatSpec,
    LongRunningCoordinator,
    LongRunningReceipt,
    ScheduleSpec,
)
from asterion.control.providers.prime.parity_testing import (
    PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS,
    build_prime_long_running_bounded_observation,
)


class PrimeLongRunningExperimentError(RuntimeError):
    """Raised with a fixed public-safe bounded-probe failure."""


class _Cancellation:
    cancelled = False


class _Processes:
    def __init__(self) -> None:
        self._by_controller: dict[str, set[str]] = {}

    def add(self, controller_id: str, process_id: str) -> None:
        self._by_controller.setdefault(controller_id, set()).add(process_id)

    def evict_controller(self, controller_id: str) -> None:
        self._by_controller.pop(controller_id, None)

    def owned_process_ids(self) -> tuple[str, ...]:
        return tuple(sorted({
            process_id
            for process_ids in self._by_controller.values()
            for process_id in process_ids
        }))


def _host_quiescence_checks() -> tuple[str, str]:
    now_ms = 0
    journal = MemoryCanonicalJournal("prime-long-running-bounded")
    journal.append(
        0,
        JournalRecord.system_bound(
            system_id="prime-long-running-bounded",
            system_version="1.0.0",
        ),
    )
    journal.append(
        1,
        JournalRecord.authority_bound(
            authority_id="prime-long-running-bounded",
            authority_revision=1,
        ),
    )
    processes = _Processes()
    coordinator = LongRunningCoordinator(
        journal=journal,
        clock_ms=lambda: now_ms,
        effect_sender=LongRunningReceipt.succeeded,
        cancellation_signal=_Cancellation(),
        process_observer=processes,
    )
    coordinator.register_heartbeat(
        HeartbeatSpec("bounded-heartbeat", "user", None, 60_000)
    )
    coordinator.register_schedule(
        ScheduleSpec.once("bounded-schedule", 60_000)
    )
    coordinator.retain_controller("bounded-controller", until_ms=120_000)
    processes.add("bounded-controller", "bounded-process")
    now_ms = 60_000
    receipts = coordinator.advance()
    if (
        len(receipts) != 2
        or any(receipt.status != "succeeded" for receipt in receipts)
        or {receipt.source_kind for receipt in receipts}
        != {"heartbeat", "schedule"}
    ):
        raise PrimeLongRunningExperimentError("Prime long-running bounded probe is invalid")
    history_size = len(coordinator.snapshot().history)
    coordinator.close()
    now_ms = 86_400_000
    if coordinator.advance() or len(coordinator.snapshot().history) != history_size:
        raise PrimeLongRunningExperimentError("Prime long-running bounded probe is invalid")
    if coordinator.audit_orphans().owned_process_count != 0:
        raise PrimeLongRunningExperimentError("Prime long-running bounded probe is invalid")
    return (
        "bounded-heartbeat-schedule-quiescence-passed",
        "bounded-orphan-audit-passed",
    )


def run_prime_long_running_bounded_probe(
    provider_probe: Callable[[], Mapping[str, object]],
    *,
    model_selector_digest: str,
    aggregate_token_limit: int,
    cost_limit_micros: int,
    deadline_ms: int,
) -> dict[str, object]:
    """Execute one provider probe, then reduce exact host-owned safety facts."""

    try:
        limits = (aggregate_token_limit, cost_limit_micros, deadline_ms)
        if (
            not callable(provider_probe)
            or not isinstance(model_selector_digest, str)
            or len(model_selector_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in model_selector_digest
            )
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in limits
            )
        ):
            raise ValueError
        report = provider_probe()
        if not isinstance(report, Mapping) or set(report) != {
            "provider_operations",
            "status",
            "terminal",
            "usage",
        }:
            raise ValueError
        usage = report["usage"]
        if (
            report["status"] != "PASS"
            or report["terminal"] != "completed"
            or report["provider_operations"] != 1
            or isinstance(report["provider_operations"], bool)
            or not isinstance(usage, Mapping)
            or set(usage) != {"aggregate_tokens", "cost_micros"}
        ):
            raise ValueError
        aggregate_tokens = usage["aggregate_tokens"]
        cost_micros = usage["cost_micros"]
        if (
            isinstance(aggregate_tokens, bool)
            or not isinstance(aggregate_tokens, int)
            or aggregate_tokens < 1
            or aggregate_tokens > aggregate_token_limit
            or isinstance(cost_micros, bool)
            or not isinstance(cost_micros, int)
            or cost_micros < 0
            or cost_micros > cost_limit_micros
        ):
            raise ValueError
        host_checks = _host_quiescence_checks()
        checks = (
            "bounded-autonomous-goal-completed-passed",
            *host_checks,
        )
        if checks != PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS:
            raise ValueError
        return {
            "format": "asterion.prime-long-running-bounded-receipt/v1",
            "status": "PASS",
            "terminal": "completed",
            "checks": list(checks),
            "provider_operations": 1,
            "model_credential_reads": 1,
            "model_selector_digest": model_selector_digest,
            "usage": {
                "aggregate_tokens": aggregate_tokens,
                "cost_micros": cost_micros,
            },
            "limits": {
                "aggregate_tokens": aggregate_token_limit,
                "cost_micros": cost_limit_micros,
                "deadline_ms": deadline_ms,
            },
        }
    except (KeyError, PrimeLongRunningExperimentError, TypeError, ValueError):
        raise PrimeLongRunningExperimentError(
            "Prime long-running bounded probe is invalid"
        ) from None


def write_prime_long_running_bounded_receipt(
    root: Path,
    receipt: Mapping[str, object],
) -> Path:
    """Atomically persist the one validated body-free receipt."""

    try:
        if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
            raise ValueError
        build_prime_long_running_bounded_observation(receipt)
        serialized = json.dumps(
            receipt,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        descriptor, temporary = tempfile.mkstemp(
            prefix=".prime-long-running-",
            dir=root,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(serialized)
                handle.write("\n")
            target = root / "prime-long-running-bounded-receipt.json"
            os.replace(temporary, target)
            return target
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, TypeError, ValueError):
        raise PrimeLongRunningExperimentError(
            "Prime long-running bounded receipt is invalid"
        ) from None


def _read_exact_json(path: Path, keys: set[str]) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError
    return value


def recover_prime_long_running_bounded(
    native_run_root: Path,
    private_evidence_root: Path,
    *,
    model_selector_digest: str,
) -> dict[str, object]:
    """Recover only a completed provider run that failed at receipt projection."""

    try:
        if (
            not isinstance(native_run_root, Path)
            or not native_run_root.is_dir()
            or native_run_root.is_symlink()
            or not isinstance(private_evidence_root, Path)
        ):
            raise ValueError
        native = _read_exact_json(
            native_run_root / "native-rlm-experiment-receipt.json",
            {
                "authority_id",
                "authority_revision",
                "budget_limited",
                "cancelled",
                "checkpoint_recovered",
                "child_deleted",
                "child_started",
                "configuration_digest",
                "detach_attached",
                "format",
                "message_delivered",
                "status",
                "terminal",
                "usage",
            },
        )
        model = _read_exact_json(
            native_run_root / "native-rlm-model-evidence.json",
            {
                "child_model_selected",
                "configuration_digest",
                "format",
                "generated_program_admitted",
                "recursion_depth_limited",
                "status",
            },
        )
        bounded = _read_exact_json(
            native_run_root / "bounded-loop-receipt.json",
            {"causal_digests", "status", "terminal", "usage"},
        )
        external = _read_exact_json(
            native_run_root / "native-rlm-external-limit.json",
            {"failure_class", "format", "stage", "status"},
        )
        configuration_digest = native["configuration_digest"]
        causal_digests = bounded["causal_digests"]
        if (
            native["format"] != "asterion.prime-native-rlm-receipt/v1"
            or native["status"] != "PASS"
            or native["terminal"] != "completed"
            or native["authority_revision"] != 1
            or isinstance(native["authority_revision"], bool)
            or not isinstance(native["authority_id"], str)
            or not native["authority_id"]
            or not isinstance(configuration_digest, str)
            or len(configuration_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in configuration_digest
            )
            or any(
                native[key] is not True
                for key in (
                    "budget_limited",
                    "cancelled",
                    "checkpoint_recovered",
                    "child_deleted",
                    "child_started",
                    "detach_attached",
                    "message_delivered",
                )
            )
            or model["format"]
            != "asterion.prime-native-rlm-model-evidence/v1"
            or model["configuration_digest"] != configuration_digest
            or model["status"] != "PASS"
            or any(
                model[key] is not True
                for key in (
                    "child_model_selected",
                    "generated_program_admitted",
                    "recursion_depth_limited",
                )
            )
            or bounded["status"] != "PASS"
            or bounded["terminal"] != "completed"
            or not isinstance(causal_digests, Mapping)
            or set(causal_digests) != {
                "application.invoke",
                "budget.probe",
                "checkpoint.create",
                "child.spawn",
                "session.cancel",
            }
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    character not in "0123456789abcdef" for character in value
                )
                for value in causal_digests.values()
            )
            or external
            != {
                "failure_class": "observation_unclassified",
                "format": "asterion.prime-native-rlm-external-limit/v1",
                "stage": "receipt",
                "status": "External-limited",
            }
        ):
            raise ValueError
        try:
            from tools.verify_prime_loop import _native_rlm_public_usage
        except ModuleNotFoundError:
            from verify_prime_loop import _native_rlm_public_usage  # type: ignore[no-redef]
        usage = _native_rlm_public_usage(native["usage"])
        bounded_usage = bounded["usage"]
        if (
            not isinstance(bounded_usage, Mapping)
            or set(bounded_usage) != {"aggregate_tokens"}
            or bounded_usage["aggregate_tokens"] != usage["aggregate_tokens"]
        ):
            raise ValueError
        receipt = run_prime_long_running_bounded_probe(
            lambda: {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 1,
                "usage": usage,
            },
            model_selector_digest=model_selector_digest,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        write_prime_long_running_bounded_receipt(
            private_evidence_root,
            receipt,
        )
        observation = build_prime_long_running_bounded_observation(receipt)
        return {
            "status": "PASS",
            "evidence_id": observation.evidence_id,
            "provider_operations": observation.provider_operations,
            "model_credential_reads": observation.model_credential_reads,
            "usage": usage,
        }
    except Exception as error:
        if isinstance(error, PrimeLongRunningExperimentError):
            raise
        raise PrimeLongRunningExperimentError(
            "Prime long-running bounded recovery did not complete"
        ) from None


def run_authorized_prime_long_running_bounded(
    source_root: Path,
    private_evidence_root: Path,
) -> dict[str, object]:
    """Run the existing pinned native autonomy probe exactly once."""

    try:
        if not isinstance(source_root, Path) or not isinstance(
            private_evidence_root, Path
        ):
            raise ValueError
        private_evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (
            not private_evidence_root.is_dir()
            or private_evidence_root.is_symlink()
        ):
            raise ValueError
        private_evidence_root.chmod(0o700)
        native_root = private_evidence_root / "native-rlm"
        native_root.mkdir(mode=0o700, exist_ok=True)
        if not native_root.is_dir() or native_root.is_symlink():
            raise ValueError
        native_root.chmod(0o700)
        try:
            from tools.prime_native_rlm_experiment import (
                native_rlm_model_selector_digest,
                resolve_native_rlm_model,
            )
            from tools.verify_prime_loop import (
                _native_rlm_bounded_external_limit,
                resolve_bounded_prime_environment,
            )
        except ModuleNotFoundError:
            from prime_native_rlm_experiment import (  # type: ignore[no-redef]
                native_rlm_model_selector_digest,
                resolve_native_rlm_model,
            )
            from verify_prime_loop import (  # type: ignore[no-redef]
                _native_rlm_bounded_external_limit,
                resolve_bounded_prime_environment,
            )
        environment = resolve_bounded_prime_environment()
        selection = resolve_native_rlm_model(environment)

        def provider_probe() -> Mapping[str, object]:
            report = _native_rlm_bounded_external_limit(
                source_root,
                None,
                500_000,
                native_root,
            )
            usage = report.get("usage")
            return {
                "status": report.get("status"),
                "terminal": report.get("terminal"),
                "provider_operations": report.get("provider_operations"),
                "usage": usage,
            }

        receipt = run_prime_long_running_bounded_probe(
            provider_probe,
            model_selector_digest=native_rlm_model_selector_digest(selection),
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        write_prime_long_running_bounded_receipt(
            private_evidence_root,
            receipt,
        )
        observation = build_prime_long_running_bounded_observation(receipt)
        return {
            "status": "PASS",
            "evidence_id": observation.evidence_id,
            "provider_operations": observation.provider_operations,
            "model_credential_reads": observation.model_credential_reads,
            "usage": dict(receipt["usage"]),  # type: ignore[arg-type]
        }
    except Exception as error:
        if isinstance(error, PrimeLongRunningExperimentError):
            raise
        raise PrimeLongRunningExperimentError(
            "Prime long-running bounded execution did not complete"
        ) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicitly authorized bounded Prime long-running probe."
    )
    parser.add_argument("--authorized-bounded-provider", action="store_true")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--private-evidence-root",
        type=Path,
        default=Path(".asterion-private/prime-long-running"),
    )
    args = parser.parse_args(argv)
    if not args.authorized_bounded_provider:
        print(
            "Prime long-running bounded execution requires explicit opt-in",
            file=sys.stderr,
        )
        return 1
    try:
        report = run_authorized_prime_long_running_bounded(
            args.source_root,
            args.private_evidence_root,
        )
    except PrimeLongRunningExperimentError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
