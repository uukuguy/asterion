"""Dormant one-operation boundary for bounded Prime harness refinement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from asterion.control.harness import (
    HarnessCoordinator,
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessScope,
    harness_effect_digest,
)
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal, JournalRecord
from asterion.control.providers.prime.harness_parity_testing import (
    build_prime_harness_bounded_observation,
)


FORMAT = "asterion.prime-continual-harness-bounded/v1"
NATIVE_FORMAT = "asterion.prime-continual-harness-native/v1"
RECEIPT_NAME = "prime-continual-harness-bounded-receipt.json"
NATIVE_RECEIPT_NAME = "prime-continual-harness-native-receipt.json"
PRIVATE_RESULT_NAME = "prime-refinement-result.json"
EVIDENCE_IDS = tuple(f"evidence-input-{index}" for index in range(7))
AGGREGATE_TOKEN_LIMIT = 150_000
COST_LIMIT_MICROS = 500_000
DEADLINE_MS = 600_000


class PrimeContinualHarnessExperimentError(RuntimeError):
    """Fixed public-safe failure for the bounded continual-harness gate."""


def _sha256(value: object) -> str:
    serialized = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def admit_prime_refinement_result(
    result: Mapping[str, object],
    *,
    evidence_ids: Sequence[str] = EVIDENCE_IDS,
) -> dict[str, object]:
    """Admit one private native proposal and activate its digest-only snapshot."""

    try:
        evidence = tuple(evidence_ids)
        if evidence != EVIDENCE_IDS or not isinstance(result, Mapping):
            raise ValueError
        proposal_id = result["id"]
        summary = result["summary"]
        rationale = result["rationale"]
        expected = result["expectedOutcome"]
        applied = result["appliedEdits"]
        if (
            not all(isinstance(value, str) and value for value in (
                proposal_id,
                summary,
                rationale,
                expected,
            ))
            or result.get("scope") != "local"
            or type(applied) is not list
            or not applied
            or any(item not in rationale for item in evidence)
        ):
            raise ValueError

        descriptors: list[HarnessEntryDescriptor] = []
        for raw_edit in applied:
            if not isinstance(raw_edit, Mapping):
                raise ValueError
            after = raw_edit.get("after")
            if (
                raw_edit.get("action") != "create"
                or raw_edit.get("applied") is not True
                or not isinstance(after, Mapping)
                or raw_edit.get("id") != after.get("id")
                or raw_edit.get("kind") != after.get("kind")
            ):
                raise ValueError
            entry_id = after.get("id")
            kind = after.get("kind")
            title = after.get("title")
            body = after.get("content")
            grouping_path = after.get("path")
            version = after.get("version")
            if (
                not isinstance(entry_id, str)
                or not entry_id
                or kind not in {"prompt", "memory", "skill", "subagent"}
                or not isinstance(title, str)
                or not isinstance(body, str)
                or not isinstance(grouping_path, str)
                or not grouping_path
                or version != 1
            ):
                raise ValueError
            descriptors.append(
                HarnessEntryDescriptor(
                    entry_id=entry_id,
                    kind=kind,
                    title_digest=_sha256(title),
                    body_ref=f"private:{proposal_id}:{entry_id}",
                    body_digest=_sha256(body),
                    grouping_path_digest=_sha256(grouping_path),
                    metadata_digest=_sha256(after),
                    version=1,
                )
            )
        descriptors.sort(key=lambda item: item.entry_id)
        if len({item.entry_id for item in descriptors}) != len(descriptors):
            raise ValueError

        scope = HarnessScope.session("prime-continual-harness-bounded")
        proposal = HarnessProposal(
            proposal_id=proposal_id,
            authority_id="prime-continual-harness-bounded",
            authority_revision=1,
            scope=scope,
            baseline_snapshot_id="snapshot-0",
            edits=tuple(HarnessEdit.create(item) for item in descriptors),
            evidence_ids=evidence,
            rationale_ref=f"private:{proposal_id}:rationale",
            rationale_digest=_sha256(rationale),
            expected_outcome_digest=_sha256(expected),
        )
        journal = MemoryCanonicalJournal("prime-continual-harness-bounded")
        journal.append(
            0,
            JournalRecord.system_bound(
                system_id="prime-continual-harness-bounded",
                system_version="1.0.0",
            ),
        )
        journal.append(
            1,
            JournalRecord.authority_bound(
                authority_id="prime-continual-harness-bounded",
                authority_revision=1,
            ),
        )

        def effect_sender(candidate: HarnessProposal) -> HarnessEffectReceipt:
            return HarnessEffectReceipt.succeeded(
                candidate,
                effect_digest=harness_effect_digest(candidate),
                result_entries=tuple(descriptors),
                usage={
                    "aggregate_tokens": AGGREGATE_TOKEN_LIMIT,
                    "cost_micros": COST_LIMIT_MICROS,
                    "model_credential_reads": 1,
                    "provider_operations": 1,
                },
            )

        coordinator = HarnessCoordinator(journal, scope, effect_sender)
        revision = coordinator.apply(proposal)
        kinds = tuple(item.record.kind for item in journal.replay(JournalCursor(0)))
        if (
            revision.status != "succeeded"
            or coordinator.snapshot().revision_id != revision.revision_id
            or kinds[-4:] != (
                "harness.proposed",
                "harness.effect-started",
                "harness.effect-terminal",
                "harness.snapshot-activated",
            )
        ):
            raise ValueError
        return {
            "status": "PASS",
            "provider_operations": 1,
            "evidence_ids": list(evidence),
            "proposal_grounded": True,
            "host_admitted": True,
            "snapshot_activated": True,
            "usage": {
                "aggregate_tokens": AGGREGATE_TOKEN_LIMIT,
                "cost_micros": COST_LIMIT_MICROS,
            },
        }
    except (KeyError, TypeError, ValueError):
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness native result is invalid"
        ) from None


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
            (native_run_root / NATIVE_RECEIPT_NAME).read_text(
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


def _resolve_node_22(root: Path) -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("ASTERION_PRIME_NODE")
    if configured:
        candidates.append(Path(configured))
    try:
        completed = subprocess.run(
            (
                "npm",
                "exec",
                "--offline",
                "--yes",
                "--package=node@22",
                "--",
                "which",
                "node",
            ),
            cwd=root,
            env={
                key: value
                for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
                if (value := os.environ.get(key)) is not None
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            version = subprocess.run(
                (str(candidate), "--version"),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if version.returncode == 0 and version.stdout.startswith("v22."):
                return candidate.resolve(strict=True)
        except (OSError, subprocess.SubprocessError):
            continue
    raise PrimeContinualHarnessExperimentError(
        "Prime continual harness bounded runtime is unavailable"
    )


def _write_native_receipt(root: Path, report: Mapping[str, object]) -> Path:
    target = root / NATIVE_RECEIPT_NAME
    descriptor: int | None = None
    try:
        native = {
            **dict(_provider_report(report)),
            "failure_stage": "public-receipt-projection",
            "format": NATIVE_FORMAT,
        }
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(
                json.dumps(
                    native,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
        return target
    except (OSError, TypeError, ValueError):
        if descriptor is not None:
            os.close(descriptor)
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness native receipt is invalid"
        ) from None


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_authorized_bounded(source_root: Path, evidence_root: Path) -> Mapping[str, object]:
    """Run the one authorized native /refine call and project body-free evidence."""

    started = time.monotonic()
    daemon: subprocess.Popen[bytes] | None = None
    try:
        project_root = Path(__file__).resolve().parents[1]
        source = source_root.resolve(strict=True)
        if source_root.is_symlink() or not source.is_dir():
            raise ValueError
        if evidence_root.is_symlink():
            raise ValueError
        if evidence_root.exists():
            if not evidence_root.is_dir():
                raise ValueError
        else:
            evidence_root.mkdir(mode=0o700, parents=True)
        os.chmod(evidence_root, 0o700)
        native_root = evidence_root / "native"
        if native_root.is_symlink():
            raise ValueError
        if native_root.exists():
            if not native_root.is_dir():
                raise ValueError
        else:
            native_root.mkdir(mode=0o700)
        os.chmod(native_root, 0o700)

        try:
            from tools.prime_native_rlm_experiment import (
                native_rlm_model_selector_digest,
                resolve_native_rlm_model,
            )
            from tools.setup_prime_agent import (
                resolve_prime_harness_module,
                verify_prime_source,
            )
            from tools.verify_prime_loop import resolve_bounded_prime_environment
        except ModuleNotFoundError:
            from prime_native_rlm_experiment import (  # type: ignore[no-redef]
                native_rlm_model_selector_digest,
                resolve_native_rlm_model,
            )
            from setup_prime_agent import (  # type: ignore[no-redef]
                resolve_prime_harness_module,
                verify_prime_source,
            )
            from verify_prime_loop import (  # type: ignore[no-redef]
                resolve_bounded_prime_environment,
            )

        selection = resolve_native_rlm_model(os.environ)
        selector_digest = native_rlm_model_selector_digest(selection)
        native_receipt = native_root / NATIVE_RECEIPT_NAME
        public_receipt = evidence_root / RECEIPT_NAME
        if native_receipt.is_file() and not public_receipt.exists():
            receipt = recover_prime_continual_harness_bounded(
                native_root,
                evidence_root,
                model_selector_digest=selector_digest,
            )
            observation = build_prime_harness_bounded_observation(receipt)
            return {
                "status": "PASS",
                "evidence_id": observation.evidence_id,
                "provider_operations": observation.provider_operations,
                "model_credential_reads": observation.model_credential_reads,
                "usage": dict(receipt["usage"]),  # type: ignore[arg-type]
            }
        if native_receipt.exists() or public_receipt.exists():
            raise ValueError

        node = _resolve_node_22(project_root)
        verify_prime_source(source, node_executable=str(node))
        resolve_prime_harness_module(source)
        daemon_entry = source / "packages/coding-agent/dist/bundle/cli.js"
        fixture = (
            project_root
            / "tests/fixtures/prime_gateway/v1/real-prime-continual-harness-bounded.mjs"
        )
        if not daemon_entry.is_file() or not fixture.is_file():
            raise ValueError

        environment = dict(resolve_bounded_prime_environment())
        selection = resolve_native_rlm_model(environment)
        if native_rlm_model_selector_digest(selection) != selector_digest:
            raise ValueError
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-harness-", dir=str(native_root)
        ) as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            home = private_root / "home"
            agent_dir = private_root / "agent"
            session_dir = private_root / "sessions"
            workspace = private_root / "workspace"
            for directory in (home, agent_dir, session_dir, workspace):
                directory.mkdir(mode=0o700)
            socket_path = private_root / "prime.sock"
            result_path = native_root / PRIVATE_RESULT_NAME
            if result_path.exists() or result_path.is_symlink():
                raise ValueError
            environment["HOME"] = str(home)
            environment["PRIME_AGENT_CODING_AGENT_DIR"] = str(agent_dir)
            daemon = subprocess.Popen(
                (
                    str(node),
                    str(daemon_entry),
                    "--mode",
                    "daemon",
                    "--daemon-socket",
                    str(socket_path),
                ),
                cwd=source,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            daemon_deadline = time.monotonic() + 15
            while time.monotonic() < daemon_deadline:
                if socket_path.exists():
                    break
                if daemon.poll() is not None:
                    raise ValueError
                time.sleep(0.025)
            else:
                raise ValueError
            remaining = DEADLINE_MS / 1000 - (time.monotonic() - started)
            if remaining <= 1:
                raise ValueError
            completed = subprocess.run(
                (
                    str(node),
                    str(fixture),
                    str(socket_path),
                    str(source),
                    str(workspace),
                    str(agent_dir),
                    str(session_dir),
                    str(result_path),
                ),
                cwd=project_root,
                env=environment,
                check=False,
                capture_output=True,
                timeout=min(remaining, 580),
            )
            if completed.returncode != 0 or not result_path.is_file():
                raise ValueError
            raw = json.loads(result_path.read_text(encoding="utf-8"))
            report = admit_prime_refinement_result(raw, evidence_ids=EVIDENCE_IDS)

        _write_native_receipt(native_root, report)
        receipt = run_prime_continual_harness_bounded_probe(
            lambda: report,
            model_selector_digest=selector_digest,
            aggregate_token_limit=AGGREGATE_TOKEN_LIMIT,
            cost_limit_micros=COST_LIMIT_MICROS,
            deadline_ms=DEADLINE_MS,
        )
        write_prime_continual_harness_bounded_receipt(evidence_root, receipt)
        observation = build_prime_harness_bounded_observation(receipt)
        return {
            "status": "PASS",
            "evidence_id": observation.evidence_id,
            "provider_operations": observation.provider_operations,
            "model_credential_reads": observation.model_credential_reads,
            "usage": dict(receipt["usage"]),  # type: ignore[arg-type]
        }
    except Exception as error:
        if isinstance(error, PrimeContinualHarnessExperimentError):
            raise
        raise PrimeContinualHarnessExperimentError(
            "Prime continual harness bounded execution failed"
        ) from None
    finally:
        if daemon is not None:
            _stop_process(daemon)


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
