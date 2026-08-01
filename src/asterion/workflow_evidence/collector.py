"""Build a public-safe workflow summary from one validated runtime event stream."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from asterion.runtime.host import parse_event_stream


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class WorkflowEvidenceError(ValueError):
    """Raised when workflow evidence is unsafe or inconsistent."""


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise WorkflowEvidenceError("workflow evidence digest is invalid")
    return value


def collect_workflow_evidence(
    events: Iterable[Mapping[str, object]],
    *,
    input_digest: str,
    artifact_digests: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return a content-safe summary for one complete runtime event stream.

    The runtime protocol is validated before information is projected.  Raw text,
    tool arguments, tool output and artifact URIs never appear in the result.
    """

    input_digest = _digest(input_digest)
    expected_artifacts = {
        key: _digest(value)
        for key, value in (artifact_digests or {}).items()
        if isinstance(key, str) and key
    }
    if len(expected_artifacts) != len(artifact_digests or {}):
        raise WorkflowEvidenceError("workflow evidence artifact identity is invalid")

    try:
        stream = parse_event_stream(events)
    except (TypeError, ValueError) as error:
        raise WorkflowEvidenceError("workflow evidence runtime stream is invalid") from error

    tool_calls: dict[str, str] = {}
    tools: dict[str, list[int]] = {}
    artifacts: list[dict[str, str]] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    terminal_status: str | None = None
    for event in stream:
        payload = event.payload
        if event.type == "tool.call":
            call_id = str(payload["call_id"])
            name = str(payload["name"])
            tool_calls[call_id] = name
            tools.setdefault(name, [0, 0])[0] += 1
        elif event.type == "tool.result":
            name = tool_calls[str(payload["call_id"])]
            tools[name][1] += int(bool(payload["is_error"]))
        elif event.type == "usage.reported":
            usage["input_tokens"] += int(payload["input_tokens"])
            usage["output_tokens"] += int(payload["output_tokens"])
        elif event.type == "artifact.created":
            artifact = payload["artifact"]
            assert isinstance(artifact, Mapping)
            artifact_id = str(artifact["artifact_id"])
            sha256 = artifact.get("sha256")
            if sha256 is None:
                continue
            sha256 = _digest(sha256)
            if artifact_id in expected_artifacts and expected_artifacts[artifact_id] != sha256:
                raise WorkflowEvidenceError("workflow evidence artifact digest mismatches")
            artifacts.append({"artifact_id": artifact_id, "sha256": sha256})
        elif event.type == "run.completed":
            terminal_status = str(payload["status"])
        elif event.type == "run.failed":
            terminal_status = "failed"

    if terminal_status is None:
        raise WorkflowEvidenceError("workflow evidence terminal status is missing")
    return {
        "schema": "asterion.workflow-evidence/v1",
        "run_id": stream[0].run_id,
        "input_digest": input_digest,
        "terminal_status": terminal_status,
        "tools": [
            {"name": name, "calls": totals[0], "errors": totals[1]}
            for name, totals in sorted(tools.items())
        ],
        "usage": usage,
        "artifacts": sorted(artifacts, key=lambda artifact: artifact["artifact_id"]),
    }
