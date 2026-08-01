"""Build a public-safe workflow summary from one validated runtime event stream."""

from __future__ import annotations

import hashlib
import hmac
import json
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


def _graph_digest(graph: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical_digest(value: object, *, error: str) -> str:
    try:
        rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkflowEvidenceError(error) from exc
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def validate_workflow_evidence(evidence: Mapping[str, object]) -> None:
    """Reject evidence whose identity, safe shape, or integrity digest is invalid."""

    if not isinstance(evidence, Mapping):
        raise WorkflowEvidenceError("workflow evidence must be an object")
    graph = dict(evidence)
    graph_sha256 = _digest(graph.pop("graph_sha256", None))
    if graph.get("schema") != "asterion.workflow-evidence/v1":
        raise WorkflowEvidenceError("workflow evidence schema is invalid")
    if not isinstance(graph.get("run_id"), str) or not graph["run_id"]:
        raise WorkflowEvidenceError("workflow evidence run identity is invalid")
    _digest(graph.get("input_digest"))
    if graph.get("terminal_status") not in {"completed", "cancelled", "failed"}:
        raise WorkflowEvidenceError("workflow evidence terminal status is invalid")
    if not isinstance(graph.get("tools"), list) or not isinstance(graph.get("artifacts"), list):
        raise WorkflowEvidenceError("workflow evidence collections are invalid")
    if not isinstance(graph.get("usage"), Mapping):
        raise WorkflowEvidenceError("workflow evidence usage is invalid")
    if not hmac.compare_digest(graph_sha256, _graph_digest(graph)):
        raise WorkflowEvidenceError("workflow evidence digest mismatches")


def compare_workflow_evidence(
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    baseline_scope: Mapping[str, object],
    candidate_scope: Mapping[str, object],
) -> dict[str, object]:
    """Compare two verified workflow summaries only when their scopes match.

    Scope content is never returned.  Its digest makes a comparison auditable
    while preventing public reports from exposing case identities or settings.
    """

    validate_workflow_evidence(baseline)
    validate_workflow_evidence(candidate)
    baseline_scope_sha256 = _canonical_digest(
        baseline_scope, error="workflow comparison baseline scope is invalid"
    )
    candidate_scope_sha256 = _canonical_digest(
        candidate_scope, error="workflow comparison candidate scope is invalid"
    )
    common = {
        "schema": "asterion.workflow-comparison/v1",
        "baseline_graph_sha256": baseline["graph_sha256"],
        "candidate_graph_sha256": candidate["graph_sha256"],
    }
    if not hmac.compare_digest(baseline_scope_sha256, candidate_scope_sha256):
        return {
            **common,
            "status": "not-comparable",
            "reasons": ["scope-identity-mismatch"],
            "baseline_scope_sha256": baseline_scope_sha256,
            "candidate_scope_sha256": candidate_scope_sha256,
        }

    baseline_usage = baseline["usage"]
    candidate_usage = candidate["usage"]
    assert isinstance(baseline_usage, Mapping)
    assert isinstance(candidate_usage, Mapping)
    usage_delta: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens"):
        before = baseline_usage.get(name)
        after = candidate_usage.get(name)
        if isinstance(before, bool) or not isinstance(before, int) or before < 0:
            raise WorkflowEvidenceError("workflow comparison baseline usage is invalid")
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise WorkflowEvidenceError("workflow comparison candidate usage is invalid")
        usage_delta[name] = after - before
    return {
        **common,
        "status": "comparable",
        "scope_sha256": baseline_scope_sha256,
        "terminal_status_changed": baseline["terminal_status"] != candidate["terminal_status"],
        "usage_delta": usage_delta,
    }


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
    graph: dict[str, object] = {
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
    graph["graph_sha256"] = _graph_digest(graph)
    return graph
