"""Body-free verification for bounded dual-runtime DCI application evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from collections.abc import Mapping

from asterion.capabilities.dci_research.complete import complete_application_identity
from asterion.adapters.claude_code import ClaudeCodeProtocolAdapter
from asterion.runtime.protocol import ProtocolError, validate_event_stream


class DciDualRuntimeVerificationError(RuntimeError):
    """Safe failure for invalid private dual-runtime evidence."""


_AF330_SOURCE_PATHS = (
    "asterion/src/asterion/capabilities/dci_research/complete.py",
    "asterion/src/asterion/dci/application_executor.py",
    "asterion/src/asterion/dci/bridge.py",
    "asterion/src/asterion/dci/dual_runtime_verification.py",
    "asterion/src/asterion/runtime/defaults.py",
    "asterion/src/asterion/runtimes/claude_code.py",
)


def _private_file(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError:
        raise DciDualRuntimeVerificationError("private runtime evidence is unavailable") from None
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise DciDualRuntimeVerificationError("private runtime evidence is unsafe")
    return raw


def _document(path: Path) -> tuple[dict[str, object], bytes]:
    raw = _private_file(path)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise DciDualRuntimeVerificationError("private runtime evidence is invalid") from None
    if not isinstance(value, dict):
        raise DciDualRuntimeVerificationError("private runtime evidence is invalid")
    return value, raw


def _contained_path(value: object, corpus: Path) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (corpus / candidate).resolve()
    return resolved == corpus or resolved.is_relative_to(corpus)


def audit_restricted_pi_application(*, run_dir: Path, corpus_dir: Path) -> dict[str, object]:
    """Rehash and validate one real read/grep-only Pi complete-application run."""

    run_path = Path(run_dir)
    corpus_path = Path(corpus_dir)
    if run_path.is_symlink() or corpus_path.is_symlink():
        raise DciDualRuntimeVerificationError("runtime evidence boundary is invalid")
    run = run_path.resolve()
    corpus = corpus_path.resolve()
    if not run.is_dir() or not corpus.is_dir():
        raise DciDualRuntimeVerificationError("runtime evidence boundary is invalid")
    state, state_raw = _document(run / "state.json")
    request, request_raw = _document(run / "protocol/attempt-0001.request.json")
    evaluation, evaluation_raw = _document(run / "eval_result.json")
    events_raw = _private_file(run / "protocol/attempt-0001.events.jsonl")
    try:
        events = [json.loads(line) for line in events_raw.splitlines() if line]
    except (TypeError, ValueError):
        raise DciDualRuntimeVerificationError("private runtime evidence is invalid") from None
    if (
        state.get("status") != "completed"
        or state.get("tools") != "read,grep"
        or state.get("max_turns") != 4
        or request.get("requested_capabilities") != ["filesystem.read", "pi.tool.grep"]
        or evaluation.get("is_correct") is not True
    ):
        raise DciDualRuntimeVerificationError("restricted Pi contract did not complete")
    calls = [event for event in events if event.get("type") == "tool.call"]
    if not calls:
        raise DciDualRuntimeVerificationError("restricted Pi tool evidence is unavailable")
    tool_counts = {"read": 0, "grep": 0}
    error_count = 0
    for event in calls:
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("name") not in tool_counts:
            raise DciDualRuntimeVerificationError("restricted Pi tool surface was violated")
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict) or not _contained_path(arguments.get("path"), corpus):
            raise DciDualRuntimeVerificationError("restricted Pi corpus boundary was violated")
        tool_counts[str(payload["name"])] += 1
    for event in events:
        if event.get("type") == "tool.result" and event.get("payload", {}).get("is_error") is True:
            error_count += 1
    fingerprint = evaluation.get("judge_request_fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise DciDualRuntimeVerificationError("restricted Pi evaluation identity is invalid")
    artifacts = {
        "state.json": hashlib.sha256(state_raw).hexdigest(),
        "attempt-0001.request.json": hashlib.sha256(request_raw).hexdigest(),
        "attempt-0001.events.jsonl": hashlib.sha256(events_raw).hexdigest(),
        "eval_result.json": hashlib.sha256(evaluation_raw).hexdigest(),
    }
    return {
        "schema": "asterion.dci.dual-runtime-acceptance/v1",
        "runtime_id": "pi.reference",
        "status": "completed",
        "implementation_sha256": complete_application_identity(),
        "tools": tool_counts,
        "tool_call_count": sum(tool_counts.values()),
        "tool_error_count": error_count,
        "corpus_contained": True,
        "web_calls": 0,
        "subagent_calls": 0,
        "judge_request_fingerprint": fingerprint,
        "private_artifacts": artifacts,
        "full_dataset": False,
    }


def audit_restricted_claude_application(
    *, run_dir: Path, corpus_dir: Path
) -> dict[str, object]:
    """Rehash and validate one real Read/Grep/Glob-only Claude application run."""

    run_path = Path(run_dir)
    corpus_path = Path(corpus_dir)
    if run_path.is_symlink() or corpus_path.is_symlink():
        raise DciDualRuntimeVerificationError("runtime evidence boundary is invalid")
    run = run_path.resolve()
    corpus = corpus_path.resolve()
    if not run.is_dir() or not corpus.is_dir():
        raise DciDualRuntimeVerificationError("runtime evidence boundary is invalid")
    if stat.S_IMODE(run.stat().st_mode) != 0o700:
        raise DciDualRuntimeVerificationError("private runtime evidence is unsafe")
    request, request_raw = _document(run / "request.json")
    policy, policy_raw = _document(run / "runtime-policy.json")
    evaluation, evaluation_raw = _document(run / "eval_result.json")
    events_raw = _private_file(run / "events.jsonl")
    raw_events_raw = _private_file(run / "raw-events.jsonl")
    final_raw = _private_file(run / "final.txt")
    try:
        events = [json.loads(line) for line in events_raw.splitlines() if line]
        raw_events = [json.loads(line) for line in raw_events_raw.splitlines() if line]
    except (TypeError, ValueError):
        raise DciDualRuntimeVerificationError("private runtime evidence is invalid") from None
    request_capabilities = ["filesystem.read", "claude.tool.grep", "claude.tool.glob"]
    started_capabilities = ["claude.tool.glob", "claude.tool.grep", "filesystem.read"]
    tools = ["Read", "Grep", "Glob"]
    raw_tools = ["Glob", "Grep", "Read"]
    run_id = request.get("run_id")
    agent_provider = policy.get("agent_provider")
    agent_model = policy.get("agent_model")
    if (
        not isinstance(run_id, str)
        or not run_id
        or request.get("requested_capabilities") != request_capabilities
        or policy.get("runtime_cwd") != str(corpus)
        or agent_provider not in {"anthropic", "minimax", "minimax-cn"}
        or not isinstance(agent_model, str)
        or not agent_model
        or policy.get("tools") != tools
        or policy.get("allowed_tools") != tools
        or policy.get("max_turns") != 4
        or policy.get("permission_mode") != "dontAsk"
        or policy.get("strict_mcp") is not True
        or policy.get("mcp_servers") != {}
        or policy.get("safe_mode") is not True
        or policy.get("no_session_persistence") is not True
        or evaluation.get("is_correct") is not True
        or not events
        or events[-1].get("type") != "run.completed"
    ):
        raise DciDualRuntimeVerificationError("restricted Claude contract did not complete")
    init_events = [
        event
        for event in raw_events
        if isinstance(event, dict)
        and event.get("type") == "system"
        and event.get("subtype") == "init"
    ]
    result_events = [
        event
        for event in raw_events
        if isinstance(event, dict) and event.get("type") == "result"
    ]
    if len(init_events) != 1 or len(result_events) != 1:
        raise DciDualRuntimeVerificationError("restricted Claude raw stream is invalid")
    init = init_events[0]
    result_event = result_events[0]
    claude_code_version = init.get("claude_code_version")
    if (
        init.get("cwd") != str(corpus)
        or init.get("model") != agent_model
        or init.get("tools") != raw_tools
        or not isinstance(claude_code_version, str)
        or not claude_code_version
        or result_event.get("subtype") != "success"
        or result_event.get("is_error") is not False
    ):
        raise DciDualRuntimeVerificationError("restricted Claude raw identity is invalid")
    reprojected: list[dict[str, object]] = []
    adapter = ClaudeCodeProtocolAdapter(run_id=run_id, emit=reprojected.append)
    try:
        for raw_event in raw_events:
            if not isinstance(raw_event, dict):
                raise ProtocolError("raw event is not an object")
            adapter.consume(raw_event)
        validate_event_stream(events)
        validate_event_stream(reprojected)
    except (ProtocolError, TypeError, ValueError):
        raise DciDualRuntimeVerificationError("restricted Claude raw stream is invalid") from None
    if events != reprojected:
        raise DciDualRuntimeVerificationError("restricted Claude normalized evidence is invalid")
    settings = policy.get("settings")
    sandbox = settings.get("sandbox") if isinstance(settings, dict) else None
    if (
        not isinstance(sandbox, dict)
        or sandbox.get("enabled") is not True
        or sandbox.get("failIfUnavailable") is not True
        or sandbox.get("allowUnsandboxedCommands") is not False
    ):
        raise DciDualRuntimeVerificationError("restricted Claude sandbox was not enforced")
    started = [event for event in events if event.get("type") == "run.started"]
    if (
        len(started) != 1
        or started[0].get("payload", {}).get("capabilities") != started_capabilities
    ):
        raise DciDualRuntimeVerificationError("restricted Claude tool declaration is invalid")
    calls = [event for event in events if event.get("type") == "tool.call"]
    if not calls:
        raise DciDualRuntimeVerificationError("restricted Claude tool evidence is unavailable")
    tool_counts = {tool: 0 for tool in tools}
    for event in calls:
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("name") not in tool_counts:
            raise DciDualRuntimeVerificationError("restricted Claude tool surface was violated")
        arguments = payload.get("arguments")
        name = str(payload["name"])
        path_key = "file_path" if name == "Read" else "path"
        candidate = arguments.get(path_key, ".") if isinstance(arguments, dict) else None
        if not _contained_path(candidate, corpus):
            raise DciDualRuntimeVerificationError("restricted Claude corpus boundary was violated")
        tool_counts[name] += 1
    fingerprint = evaluation.get("judge_request_fingerprint")
    if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise DciDualRuntimeVerificationError("restricted Claude evaluation identity is invalid")
    artifacts = {
        "request.json": hashlib.sha256(request_raw).hexdigest(),
        "runtime-policy.json": hashlib.sha256(policy_raw).hexdigest(),
        "events.jsonl": hashlib.sha256(events_raw).hexdigest(),
        "raw-events.jsonl": hashlib.sha256(raw_events_raw).hexdigest(),
        "final.txt": hashlib.sha256(final_raw).hexdigest(),
        "eval_result.json": hashlib.sha256(evaluation_raw).hexdigest(),
    }
    return {
        "schema": "asterion.dci.dual-runtime-acceptance/v1",
        "runtime_id": "claude-code.reference",
        "status": "completed",
        "agent_provider": agent_provider,
        "agent_model": agent_model,
        "claude_code_version": claude_code_version,
        "agent_operations": len(result_events),
        "implementation_sha256": complete_application_identity(),
        "tools": tool_counts,
        "tool_call_count": sum(tool_counts.values()),
        "corpus_contained": True,
        "web_calls": 0,
        "subagent_calls": 0,
        "judge_request_fingerprint": fingerprint,
        "private_artifacts": artifacts,
        "full_dataset": False,
    }
def write_private_report(path: Path, report: dict[str, object]) -> str:
    """Atomically write one private report and return its digest."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    raw = json.dumps(report, sort_keys=True, indent=2).encode() + b"\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    return hashlib.sha256(raw).hexdigest()


def af330_source_identity(repo_root: Path) -> str:
    """Digest the reviewed AF-330 execution and verification source boundary."""

    root = Path(repo_root).resolve()
    digest = hashlib.sha256()
    for relative in _AF330_SOURCE_PATHS:
        path = root / relative
        try:
            metadata = path.lstat()
            raw = path.read_bytes()
        except OSError:
            raise DciDualRuntimeVerificationError("AF-330 source evidence is unavailable") from None
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise DciDualRuntimeVerificationError("AF-330 source evidence is unsafe")
        name = relative.encode()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def build_restricted_claude_record(
    report: Mapping[str, object],
    *,
    report_sha256: str,
    source_commit: str,
    source_sha256: str,
) -> dict[str, object]:
    """Build the closed body-free Climb record from one audited report."""

    if any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (report_sha256, source_sha256)
    ) or re.fullmatch(r"[0-9a-f]{7,40}", source_commit) is None:
        raise DciDualRuntimeVerificationError("AF-330 binding identity is invalid")
    copied = {
        key: report.get(key)
        for key in (
            "runtime_id",
            "status",
            "agent_provider",
            "agent_model",
            "claude_code_version",
            "agent_operations",
            "implementation_sha256",
            "tool_call_count",
            "tools",
            "corpus_contained",
            "web_calls",
            "subagent_calls",
            "judge_request_fingerprint",
            "full_dataset",
            "private_artifacts",
        )
    }
    return {
        "schema": "asterion.dci.climb-provider-evidence/v2",
        "work_package_id": "AF-330",
        "hypothesis_id": "AF-330-H-004",
        "source_commit": source_commit,
        "source_sha256": source_sha256,
        "report_sha256": report_sha256,
        "judge_operations": 1,
        **copied,
    }


def verify_restricted_claude_binding(
    *,
    repo_root: Path,
    run_dir: Path,
    corpus_dir: Path,
    report_path: Path,
    record_path: Path,
) -> dict[str, object]:
    """Re-audit retained evidence and bind it to reviewed source plus public record."""

    report, report_raw = _document(Path(report_path))
    audited = audit_restricted_claude_application(
        run_dir=Path(run_dir), corpus_dir=Path(corpus_dir)
    )
    if report != audited:
        raise DciDualRuntimeVerificationError("AF-330 private report does not match runtime evidence")
    report_sha256 = hashlib.sha256(report_raw).hexdigest()
    record, record_raw = _tracked_document(Path(record_path))
    source_commit = record.get("source_commit")
    if not isinstance(source_commit, str):
        raise DciDualRuntimeVerificationError("AF-330 tracked evidence is invalid")
    source_sha256 = af330_source_identity(repo_root)
    expected = build_restricted_claude_record(
        audited,
        report_sha256=report_sha256,
        source_commit=source_commit,
        source_sha256=source_sha256,
    )
    if record != expected:
        raise DciDualRuntimeVerificationError("AF-330 tracked evidence does not match private evidence")
    _verify_source_commit(Path(repo_root), source_commit)
    return {
        "schema": "asterion.dci.claude-terminal-binding/v1",
        "status": "verified",
        "source_commit": source_commit,
        "source_sha256": source_sha256,
        "implementation_sha256": audited["implementation_sha256"],
        "report_sha256": report_sha256,
        "record_sha256": hashlib.sha256(record_raw).hexdigest(),
    }


def _tracked_document(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, TypeError, ValueError):
        raise DciDualRuntimeVerificationError("AF-330 tracked evidence is unavailable") from None
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not isinstance(value, dict):
        raise DciDualRuntimeVerificationError("AF-330 tracked evidence is unsafe")
    return value, raw


def _verify_source_commit(repo_root: Path, source_commit: str) -> None:
    root = repo_root.resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "--verify", f"{source_commit}^{{commit}}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *_AF330_SOURCE_PATHS],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if revision.returncode != 0 or unchanged.returncode != 0:
        raise DciDualRuntimeVerificationError("AF-330 source commit does not match reviewed execution")
