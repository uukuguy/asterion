"""Restricted non-interactive Claude Code protocol runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal as process_signal
import subprocess
import threading
import time
from asyncio import CancelledError
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from asterion.adapters.claude_code import (
    ClaudeCodeProtocolAdapter,
    map_claude_capabilities,
)
from asterion.runtime.protocol import (
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    ProtocolError,
    validate_event_stream,
    validate_run_request,
)
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)


class ClaudeCodeRuntimeClient:
    """Adapt the restricted Claude runner to the public runtime client contract."""

    def __init__(
        self,
        *,
        executable: str,
        cwd: Path,
        environment: Mapping[str, str],
        default_timeout_seconds: float | None = 30,
        max_turns: int = 4,
        tools: tuple[str, ...] = ("Read", "Grep", "Glob"),
        evidence_root: Path | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        reasoning: str | None = None,
        context_profile: str | None = None,
        run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._executable = executable
        self._cwd = Path(cwd)
        self._environment = dict(environment)
        if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
            raise ValueError("Claude Code max turns is invalid")
        self._default_timeout_seconds = default_timeout_seconds
        self._max_turns = max_turns
        if not tools or any(tool not in {"Read", "Grep", "Glob"} for tool in tools):
            raise ValueError("Claude Code tools are invalid")
        if reasoning not in {None, "low", "medium", "high"}:
            raise ValueError("Claude Code reasoning is invalid")
        if context_profile not in {None, "level3"}:
            raise ValueError("Claude Code context profile is invalid")
        self._tools = tuple(tools)
        self._evidence_root = Path(evidence_root) if evidence_root is not None else None
        self._agent_provider = agent_provider
        self._agent_model = agent_model
        self._reasoning = reasoning
        self._context_profile = context_profile
        self._run_process = run_process
        self._completed_runs: dict[str, Path] = {}

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="claude-code.reference",
            capabilities=("claude.tool.glob", "claude.tool.grep", "filesystem.read"),
        )

    def completed_run_dir(self, run_id: str) -> Path | None:
        """Return private evidence only for a completed run owned by this client."""

        return self._completed_runs.get(run_id)

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ):
        request.to_mapping()
        if signal is not None and signal.cancelled:
            raise ProtocolError("Claude Code runtime request was cancelled")
        timeout_seconds = (
            request.deadline_ms / 1000
            if request.deadline_ms is not None
            else self._default_timeout_seconds
        )
        try:
            if self._evidence_root is None:
                temporary = TemporaryDirectory(prefix="asterion-claude-")
                output_dir = Path(temporary.name)
            else:
                temporary = None
                self._evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._evidence_root.chmod(0o700)
                name = hashlib.sha256(request.run_id.encode()).hexdigest()
                output_dir = self._evidence_root / name
                output_dir.mkdir(mode=0o700)
            try:
                local_cancel = threading.Event()
                work = asyncio.create_task(
                    asyncio.to_thread(
                        run_claude_code,
                        prompt=request.input_text,
                        output_dir=output_dir,
                        cwd=self._cwd,
                        tools=list(self._tools),
                        timeout_seconds=timeout_seconds,
                        max_turns=self._max_turns,
                        executable=self._executable,
                        environment=self._environment,
                        agent_provider=self._agent_provider,
                        agent_model=self._agent_model,
                        reasoning=self._reasoning,
                        context_profile=self._context_profile,
                        run_process=self._run_process,
                        cancelled=lambda: local_cancel.is_set()
                        or (signal is not None and signal.cancelled),
                    )
                )
                try:
                    await asyncio.shield(work)
                except CancelledError:
                    local_cancel.set()
                    await _drain_cancelled_process(work)
                    raise ProtocolError("Claude Code runtime execution failed") from None
                mappings = [
                    {**json.loads(line), "run_id": request.run_id}
                    for line in (output_dir / "events.jsonl").read_text().splitlines()
                    if line
                ]
                validate_event_stream(mappings)
                if mappings[-1]["type"] != "run.completed":
                    raise ProtocolError("Claude Code runtime execution failed")
                if self._evidence_root is not None:
                    self._completed_runs[request.run_id] = output_dir
            finally:
                if temporary is not None:
                    temporary.cleanup()
        except (
            CancelledError,
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ):
            raise ProtocolError("Claude Code runtime execution failed") from None
        for mapping in mappings:
            yield RunEvent.from_mapping(mapping)


async def _drain_cancelled_process(work: asyncio.Task[object]) -> None:
    while not work.done():
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        try:
            await asyncio.shield(work)
        except CancelledError:
            continue
    try:
        work.result()
    except BaseException:
        pass


def build_claude_command(
    *,
    executable: str,
    tools: list[str],
    max_turns: int = 4,
    agent_model: str | None = None,
    reasoning: str | None = None,
    context_profile: str | None = None,
) -> list[str]:
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
        raise ValueError("Claude Code max turns is invalid")
    settings = _restricted_settings()
    command = [
        executable,
        "-p",
        "--safe-mode",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--no-chrome",
        "--max-turns",
        str(max_turns),
        "--settings",
        json.dumps(settings, sort_keys=True, separators=(",", ":")),
    ]
    if tools:
        joined = ",".join(tools)
        command.extend(["--tools", joined, "--allowedTools", joined])
    else:
        command.extend(["--tools", ""])
    if agent_model:
        command.extend(("--model", agent_model))
    if reasoning:
        command.extend(("--effort", reasoning))
    if context_profile:
        if context_profile != "level3":
            raise ValueError("Claude Code context profile is invalid")
        command.extend(
            (
                "--append-system-prompt",
                "DCI context profile level3 is active: cap tool results at 20000 "
                "characters; at 240000 context characters compact earlier context "
                "while retaining the 12 most recent turns.",
            )
        )
    return command


def _restricted_settings() -> dict[str, object]:
    return {
        "permissions": {
            "defaultMode": "dontAsk",
            "deny": ["Read(/**)", "Grep(/**)", "Glob(/**)"],
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {"denyRead": ["~/"], "allowRead": ["."]},
        },
    }


def _write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, value.encode())
    finally:
        os.close(descriptor)
    path.chmod(0o600)


def _write_json(path: Path, payload: object) -> None:
    _write_private(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def run_claude_code(
    *,
    prompt: str,
    output_dir: Path,
    cwd: Path,
    tools: list[str],
    timeout_seconds: float | None,
    max_turns: int = 4,
    executable: str = "claude",
    environment: Mapping[str, str] | None = None,
    agent_provider: str | None = None,
    agent_model: str | None = None,
    reasoning: str | None = None,
    context_profile: str | None = None,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run one Claude Code prompt and persist raw plus normalized artifacts.

    Claude Code authentication, gateway, cloud-provider, and proxy settings stay
    on the subprocess environment boundary. They are never copied into the
    protocol request, normalized events, or returned status.
    """

    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    run_id = f"claude-{output_dir.name or 'run'}"
    request: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "run_id": run_id,
        "input": {"text": prompt},
        "requested_capabilities": map_claude_capabilities(tools),
    }
    if timeout_seconds is not None and 0 < timeout_seconds * 1000 <= MAX_DEADLINE_MS:
        request["deadline_ms"] = max(1, int(round(timeout_seconds * 1000)))
    validate_run_request(request)
    _write_json(output_dir / "request.json", request)
    _write_json(
        output_dir / "runtime-policy.json",
        {
            "schema": "asterion.claude-code.restricted-policy/v1",
            "runtime_cwd": str(cwd.resolve()),
            "agent_provider": agent_provider,
            "agent_model": agent_model,
            "reasoning": reasoning,
            "context_profile": context_profile,
            "tools": tools,
            "allowed_tools": tools,
            "max_turns": max_turns,
            "permission_mode": "dontAsk",
            "strict_mcp": True,
            "mcp_servers": {},
            "safe_mode": True,
            "no_session_persistence": True,
            "settings": _restricted_settings(),
        },
    )

    process_environment = dict(os.environ if environment is None else environment)
    command = build_claude_command(
        executable=executable,
        tools=tools,
        max_turns=max_turns,
        agent_model=agent_model,
        reasoning=reasoning,
        context_profile=context_profile,
    )
    if run_process is subprocess.run:
        completed = _run_owned_process(
            command,
            cwd=cwd,
            environment=process_environment,
            input_text=prompt,
            timeout_seconds=timeout_seconds,
            cancelled=cancelled,
        )
    else:
        completed = run_process(
            command,
            cwd=cwd,
            env=process_environment,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    _write_private(output_dir / "raw-events.jsonl", completed.stdout)
    _write_private(output_dir / "stderr.txt", completed.stderr)
    if completed.returncode != 0:
        raise OSError("Claude Code process failed")

    events: list[dict[str, object]] = []
    events_path = output_dir / "events.jsonl"

    def emit(event: dict[str, object]) -> None:
        events.append(event)
        descriptor = os.open(events_path, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(descriptor, (json.dumps(event, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(descriptor)

    _write_private(events_path, "")
    adapter = ClaudeCodeProtocolAdapter(run_id=run_id, emit=emit)
    final_text = ""
    try:
        for line_number, line in enumerate(completed.stdout.splitlines(), start=1):
            if not line.strip():
                continue
            raw_event = json.loads(line)
            if not isinstance(raw_event, dict):
                raise ValueError(f"stream line {line_number} is not an object")
            if raw_event.get("type") == "result" and isinstance(
                raw_event.get("result"), str
            ):
                final_text = raw_event["result"]
            adapter.consume(raw_event)
        if not adapter.started:
            adapter.consume({"type": "system", "subtype": "init", "tools": tools})
        if not adapter.terminal:
            adapter.fail()
    except (json.JSONDecodeError, ValueError):
        if not adapter.started:
            adapter.consume({"type": "system", "subtype": "init", "tools": tools})
        if not adapter.terminal:
            adapter.fail()

    validate_event_stream(events)
    if events[-1]["type"] == "run.completed":
        _write_private(output_dir / "final.txt", final_text + ("\n" if final_text else ""))
        status = "completed"
    else:
        final_text = ""
        status = "failed"
    return {
        "status": status,
        "returncode": completed.returncode,
        "final_text": final_text,
        "output_dir": str(output_dir),
    }


def _run_owned_process(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    input_text: str,
    timeout_seconds: float | None,
    cancelled: Callable[[], bool] | None,
) -> subprocess.CompletedProcess[str]:
    """Run, cancel, and reap one directly owned Claude process."""

    if cancelled is not None and cancelled():
        raise CancelledError
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
    )
    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds is not None
        else None
    )
    pending_input: str | None = input_text
    try:
        while True:
            if cancelled is not None and cancelled():
                raise CancelledError
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            poll_seconds = 0.05 if remaining is None else min(0.05, remaining)
            try:
                stdout, stderr = process.communicate(
                    input=pending_input,
                    timeout=poll_seconds,
                )
                return subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired:
                pending_input = None
    except BaseException:
        _terminate_owned_process(process)
        raise


def _terminate_owned_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, process_signal.SIGTERM)
        elif process.poll() is None:
            process.terminate()
        process.communicate(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        if os.name != "nt":
            try:
                os.killpg(process.pid, process_signal.SIGKILL)
            except OSError:
                pass
        elif process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.communicate(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
