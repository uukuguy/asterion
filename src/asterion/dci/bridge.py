"""Explicit projection from native Asterion DCI runs to package outputs."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import threading
from pathlib import Path
from typing import Protocol

from asterion.dci.run import DciRunRequest, DciRunResult
from asterion.packages.execution import PackageExecutionResult
from asterion.runtime.protocol import validate_event_stream


class DciRunExecutor(Protocol):
    """Narrow native DCI executor boundary reserved for application integration."""

    def run(
        self,
        request: DciRunRequest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> DciRunResult: ...


def project_dci_run(result: DciRunResult) -> PackageExecutionResult:
    """Project verified native artifacts without exposing answer or diagnostic bodies."""

    if result.status != "completed" or result.events[-1].type != "run.completed":
        raise ValueError("native DCI run is not completed")
    event_mappings = [event.to_mapping() for event in result.events]
    validate_event_stream(event_mappings)
    final_artifact = next(
        (
            event.payload.get("artifact")
            for event in result.events
            if event.type == "artifact.created"
        ),
        None,
    )
    if not isinstance(final_artifact, dict) or final_artifact.get("uri") != "final.txt":
        raise ValueError("native DCI final artifact is invalid")
    value = {
        "answer_artifact_uri": "final.txt",
        "conversation_artifact_uri": "conversation.json",
        "events_artifact_uri": "events.jsonl",
        "latest_model_context_artifact_uri": "latest_model_context.json",
        "protocol_artifact_uri": "protocol/",
        "state_artifact_uri": "state.json",
    }
    if _has_valid_evaluation(result.output_dir):
        value["evaluation_artifact_uri"] = "eval_result.json"
    context_policy = _context_policy_projection(result.output_dir)
    if context_policy is not None:
        value["context_policy_artifact_uri"] = "context-policy.json"
        value["context_policy"] = context_policy
    return PackageExecutionResult(
        events=(
            {"type": "research.completed", "payload": {"status": "completed"}},
        ),
        artifacts=(
            {
                "artifact_id": "dci-research-result",
                "media_type": "application/vnd.dci.research+json",
                "value": value,
            },
        ),
    )


def _has_valid_evaluation(output_dir: Path) -> bool:
    try:
        value = json.loads((output_dir / "eval_result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and isinstance(value.get("is_correct"), bool)


def _context_policy_projection(output_dir: Path) -> dict[str, object] | None:
    try:
        state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("context_policy") is None:
        return None
    reference = state.get("context_policy")
    if (
        not isinstance(reference, dict)
        or set(reference) != {"artifact", "sha256", "public_summary"}
        or reference.get("artifact") != "context-policy.json"
        or re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256"))) is None
    ):
        raise ValueError("native DCI context policy is invalid")
    path = output_dir / "context-policy.json"
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("native DCI context policy is invalid") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or hashlib.sha256(raw).hexdigest() != reference["sha256"]
    ):
        raise ValueError("native DCI context policy is invalid")
    summary = reference.get("public_summary")
    expected = {
        "schema",
        "profile",
        "contract_version",
        "extension_version",
        "extension_sha256",
        "truncated_results",
        "compactions",
        "preserved_turns",
        "summary_attempts",
        "summary_successes",
        "summary_suppressed",
    }
    if (
        not isinstance(summary, dict)
        or set(summary) != expected
        or summary.get("schema") != "dci.context-policy-evidence/v2"
        or summary.get("profile")
        not in {"level0", "level1", "level2", "level3", "level4"}
        or summary.get("contract_version") != "dci.context-profile/v1"
        or not isinstance(summary.get("extension_version"), str)
        or not summary["extension_version"]
        or re.fullmatch(r"[0-9a-f]{64}", str(summary.get("extension_sha256")))
        is None
        or any(
            isinstance(summary.get(key), bool)
            or not isinstance(summary.get(key), int)
            or summary[key] < 0
            for key in (
                "truncated_results",
                "compactions",
                "summary_attempts",
                "summary_successes",
            )
        )
        or not (
            summary.get("preserved_turns") is None
            or (
                not isinstance(summary.get("preserved_turns"), bool)
                and isinstance(summary.get("preserved_turns"), int)
                and summary["preserved_turns"] >= 0
            )
        )
        or not isinstance(summary.get("summary_suppressed"), bool)
    ):
        raise ValueError("native DCI context policy is invalid")
    return dict(summary)
