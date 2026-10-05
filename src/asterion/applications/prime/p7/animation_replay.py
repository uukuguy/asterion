"""Authenticated lineage for replaying nondeterministic intermediate animation."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .broker import ArcRunReceipt
from .live import read_trace_entries
from .private_trace import trace_identities_for
from .replay import observations_match
from .score import replay_sha256

KIND = "animation-replay"


def native_evidence(run: Path) -> tuple:
    """Read a normally settled, sealed native solve whose replay alone failed."""
    from .solutions import (
        _private_path,
        _transitions,
        _recording_identity,
        recorded_observations,
        _summary_matches,
    )

    summary = json.loads(_private_path(run, "summary.json").read_text())
    experiment = summary["experiment"]
    broker = summary["broker"]
    if (
        summary.get("schema") != "asterion.prime.p7-live-private-summary/v1"
        or summary.get("run_id") != run.name
        or summary.get("cleanup_complete") is not True
        or summary.get("replay_verified") is not False
        or summary.get("failure", {}).get("type") != "ArcBrokerError"
        or not summary.get("receipt")
        or summary.get("completed_prefix") is not None
        or experiment.get("prediction_variant") == "offline-replay"
        or broker.get("terminal_reason") not in {"level-completed", "game-won"}
        or broker.get("levels_completed") != experiment.get("target_level")
        or any(broker.get(key) != experiment.get(key) for key in ("game_id", "seed"))
    ):
        raise ValueError
    native = summary.get("diagnostics", {}).get("native_event_summary", [])
    if not native or native[-1].get("type") != "agent_settled":
        raise ValueError
    entries = read_trace_entries(_private_path(run, "trace"))
    seal = json.loads(_private_path(run, "trace", "prime-trace.seal.json").read_text())
    if (
        seal.get("entry_count") != len(entries)
        or seal.get("final_sha256") != entries[-1].sha256
        or any(
            dict(e.identities) != trace_identities_for(experiment["model"])
            for e in entries
        )
        or [dict(e.payload) for e in entries if e.kind == "arc.run.completed"]
        != [broker]
        or any(
            e.kind in {"arc.run.partial", "arc.run.failed", "arc.recovery.source"}
            for e in entries
        )
    ):
        raise ValueError
    contexts = [dict(e.payload) for e in entries if e.kind == "arc.run.context"]
    if (
        len(contexts) != 1
        or contexts[0].get("run_id") != run.name
        or contexts[0].get("model_id") != experiment["model"]
        or any(
            contexts[0].get(key) != broker.get(key)
            for key in ("game_id", "seed", "win_levels")
        )
        or contexts[0].get("target_level") != broker["levels_completed"]
    ):
        raise ValueError
    transitions = _transitions(entries)
    receipt = ArcRunReceipt(
        *(
            broker[key]
            for key in (
                "game_id",
                "seed",
                "primitive_actions",
                "levels_completed",
                "terminal_reason",
                "replay_sha256",
            )
        )
    )
    if (
        len(transitions) != receipt.primitive_actions
        or replay_sha256(transitions, terminal_reason=receipt.terminal_reason)
        != receipt.replay_sha256
        or not _summary_matches(
            summary,
            receipt.game_id,
            receipt.seed,
            broker["win_levels"],
            receipt.levels_completed,
            receipt.primitive_actions,
            receipt.terminal_reason,
            receipt.replay_sha256,
        )
        or _recording_identity(run, transitions)
        != (receipt.game_id, broker["win_levels"])
    ):
        raise ValueError
    observations = recorded_observations(
        run, transitions, receipt.game_id, broker["win_levels"]
    )
    if observations is None:
        raise ValueError
    paths = ["summary.json", "trace/prime-trace.jsonl", "trace/prime-trace.seal.json"]
    paths.extend(
        str(path.relative_to(run)) for path in (run / "recordings").glob("*/*.jsonl")
    )
    hashes = {
        name: sha256(_private_path(run, *name.split("/")).read_bytes()).hexdigest()
        for name in sorted(paths)
    }
    return summary, transitions, observations, receipt, hashes


def recovery_source(run: Path, summary: dict) -> tuple[Path, dict] | None:
    """Authorize attribution only after both original and new observations match."""
    from .solutions import _private_path, _transitions, recorded_observations
    from asterion.agents.prime.trace import _plain

    try:
        diagnostics = summary["diagnostics"]
        source_id = diagnostics["recovered_from"]
        if (
            diagnostics.get("recovery_kind") != KIND
            or diagnostics.get("execution_mode") != "offline-replay"
            or type(source_id) is not str
            or source_id == run.name
        ):
            return None
        source = _private_path(run.parent, source_id)
        original, old_transitions, old_observations, receipt, hashes = native_evidence(
            source
        )
        if (
            diagnostics.get("source_hashes") != hashes
            or diagnostics.get("source_receipt") != original["receipt"]
        ):
            return None
        experiment = summary["experiment"]
        if experiment.get("prediction_variant") != "offline-replay" or any(
            experiment.get(key) != original["experiment"].get(key)
            for key in ("game_id", "seed", "model", "target_level")
        ):
            return None
        entries = read_trace_entries(_private_path(run, "trace"))
        if any(
            dict(e.identities) != trace_identities_for(experiment["model"])
            for e in entries
        ):
            return None
        markers = [
            _plain(e.payload) for e in entries if e.kind == "arc.recovery.source"
        ]
        if markers != [{"source_run_id": source_id, "recovery_kind": KIND, **hashes}]:
            return None
        transitions = _transitions(entries)
        if len(transitions) != len(old_transitions) or any(
            (a.sequence, a.action, a.data, a.levels_completed)
            != (b.sequence, b.action, b.data, b.levels_completed)
            for a, b in zip(transitions, old_transitions)
        ):
            return None
        observations = recorded_observations(
            run, transitions, receipt.game_id, original["broker"]["win_levels"]
        )
        if observations is None or not all(
            observations_match(a, b) for a, b in zip(observations, old_observations)
        ):
            return None
        return source, original
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
