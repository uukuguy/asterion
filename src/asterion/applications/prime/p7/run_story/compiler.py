"""Deterministically compile private P7 evidence into safe process data."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping

from .evidence import read_run_evidence
from .model import FrameFact, RunEvidence, SCHEMA, canonical_json
from .storage import digest_bytes, publish_directory, rebuild_catalog, safe_id


@dataclass(frozen=True, slots=True)
class CompiledBundle:
    run_root: Path
    bundle_sha256: str
    artifact: Mapping[str, object]


def _jsonl(values: list[dict[str, object]]) -> bytes:
    return b"".join(canonical_json(value) for value in values)


def _frame_record(frame: FrameFact) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "frame_index": frame.index,
        "timestamp": frame.timestamp,
        "state": frame.state,
        "levels_completed": frame.levels_completed,
        "shape": [64, 64],
        "sha256": frame.sha256,
        "grid": [list(row) for row in frame.grid],
    }


def _diff(
    before: FrameFact, after: FrameFact, *, action_index: int
) -> dict[str, object]:
    changes = [
        {"row": row, "column": column, "before": old, "after": new}
        for row, (left, right) in enumerate(zip(before.grid, after.grid, strict=True))
        for column, (old, new) in enumerate(zip(left, right, strict=True))
        if old != new
    ]
    rows = [int(item["row"]) for item in changes]
    columns = [int(item["column"]) for item in changes]
    return {
        "schema": SCHEMA,
        "action_index": action_index,
        "before_frame": before.index,
        "after_frame": after.index,
        "changed_cell_count": len(changes),
        "bounding_box": None
        if not changes
        else [min(rows), min(columns), max(rows), max(columns)],
        "changes": changes,
    }


def _bundle_files(evidence: RunEvidence) -> dict[str, bytes]:
    diffs = [
        _diff(
            evidence.frames[frame_index - 1],
            evidence.frames[frame_index],
            action_index=action.index,
        )
        for action in evidence.actions
        for frame_index in range(action.before_frame + 1, action.after_frame + 1)
    ]
    action_diffs = {
        action.index: _diff(
            evidence.frames[action.before_frame],
            evidence.frames[action.after_frame],
            action_index=action.index,
        )
        for action in evidence.actions
    }
    run = {
        "schema": SCHEMA,
        "application_id": evidence.identities["application_id"],
        "runtime_id": evidence.identities["runtime_id"],
        "reasoning_id": evidence.identities["reasoning_id"],
        "model_id": evidence.identities["model_id"],
        "game_id": evidence.game_id,
        "run_id": evidence.run_id,
        "level": 1,
        "terminal_reason": evidence.terminal_reason,
        "levels_completed": evidence.levels_completed,
        "score": evidence.score,
        "action_count": len(evidence.actions),
        "action_limit": evidence.action_limit,
        "frame_count": len(evidence.frames),
        "reasoning_cell_count": evidence.worker_cell_count,
        "verification": evidence.verification,
        "replay_verified": evidence.replay_verified,
        "sealed_trace": evidence.sealed_trace,
        "elapsed_seconds": None,
        "usage": None if evidence.usage is None else dict(evidence.usage),
        "source_evidence": dict(evidence.source_digests),
    }
    actions = [
        {
            "schema": SCHEMA,
            "action_index": action.index,
            "action": action.name,
            "before_frame": action.before_frame,
            "after_frame": action.after_frame,
            "before_sha256": action.before_sha256,
            "after_sha256": action.after_sha256,
            "levels_completed": action.levels_completed,
            "changed_cell_count": action_diffs[action.index]["changed_cell_count"],
            "classification": "no-op"
            if action_diffs[action.index]["changed_cell_count"] == 0
            else "productive",
        }
        for action in evidence.actions
    ]
    reasoning = [
        {
            "schema": SCHEMA,
            "cell_index": cell.index,
            "status": "error" if cell.is_error else "ok",
            "code_sha256": cell.code_sha256,
            "output_sha256": cell.output_sha256,
            "purpose": "inspection",
        }
        for cell in evidence.reasoning_cells
    ]
    changed = [
        int(action_diffs[action.index]["changed_cell_count"])
        for action in evidence.actions
    ]
    metrics = {
        "schema": SCHEMA,
        "action_count": len(actions),
        "productive_action_count": sum(
            item["classification"] == "productive" for item in actions
        ),
        "no_op_action_count": sum(item["classification"] == "no-op" for item in actions),
        "changed_cell_min": min(changed, default=0),
        "changed_cell_max": max(changed, default=0),
        "completion_action": len(actions) if evidence.levels_completed else None,
        "reasoning_cell_count": len(reasoning),
        "usage": None if evidence.usage is None else dict(evidence.usage),
    }
    return {
        "data/run.json": canonical_json(run),
        "data/actions.jsonl": _jsonl(actions),
        "data/frames.jsonl": _jsonl([_frame_record(frame) for frame in evidence.frames]),
        "data/diffs.jsonl": _jsonl(diffs),
        "data/reasoning-index.jsonl": _jsonl(reasoning),
        "data/metrics.json": canonical_json(metrics),
    }


def compile_run(run_root: Path, artifact_root: Path) -> CompiledBundle:
    """Create or validate one immutable normalized bundle."""

    evidence = read_run_evidence(run_root)
    files = _bundle_files(evidence)
    bound_files = {
        name: {
            "media_type": "application/x-ndjson" if name.endswith(".jsonl") else "application/json",
            "sha256": digest_bytes(value),
        }
        for name, value in sorted(files.items())
    }
    identity = {
        "schema": SCHEMA,
        "game_id": evidence.game_id,
        "run_id": evidence.run_id,
        "verification": evidence.verification,
        "files": bound_files,
    }
    bundle_sha256 = "sha256:" + sha256(canonical_json(identity)).hexdigest()
    artifact = {**identity, "bundle_sha256": bundle_sha256}
    destination = (
        artifact_root
        / "games"
        / safe_id(evidence.game_id)
        / "runs"
        / safe_id(evidence.run_id)
    )
    publish_directory(
        destination, {**files, "artifact.json": canonical_json(artifact)}
    )
    rebuild_catalog(artifact_root)
    return CompiledBundle(
        destination,
        bundle_sha256,
        MappingProxyType(artifact),
    )


__all__ = ("CompiledBundle", "compile_run")
