"""Asterion-owned transport for one Pi JSONL-RPC research run."""

from __future__ import annotations

import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO


_STDOUT_EOF = object()
FINAL_ANSWER_RECOVERY_PROMPT = (
    "Stop using tools. Based only on the evidence already gathered in this session, "
    "provide the requested final answer now as non-empty text."
)


_NODE_FAILURE = "compatible Node runtime is unavailable (Node >=20 required)"
_DCI_ENTRY_KEYS = {"id", "parentId", "timestamp", "type", "customType", "data"}
_DCI_STATE_KEYS = {
    "accumulatedOriginalToolCharacters",
    "truncatedResults",
    "compactionCount",
    "preservedTurns",
    "compactionPending",
    "summaryAttempts",
    "summarySuccesses",
    "consecutiveSummaryFailures",
    "summarySuppressed",
}
_DCI_NUMERIC_STATE_KEYS = _DCI_STATE_KEYS - {
    "compactionPending",
    "summarySuppressed",
    "preservedTurns",
}
_DCI_CUMULATIVE_KEYS = {
    "truncatedResults",
    "compactionCount",
    "summaryAttempts",
    "summarySuccesses",
}


def _node_major(version: str) -> int | None:
    value = version.strip()
    if not value.startswith("v"):
        return None
    major, separator, _rest = value[1:].partition(".")
    if not separator or not major.isdecimal():
        return None
    return int(major)


def _probe_node(candidate: str, environment: Mapping[str, str]) -> bool:
    try:
        result = subprocess.run(
            [candidate, "--version"],
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return False
    major = (
        _node_major(result.stdout)
        if result.returncode == 0 and isinstance(result.stdout, str)
        else None
    )
    return major is not None and major >= 20


def _nvm_node_candidates(environment: Mapping[str, str]) -> tuple[str, ...]:
    nvm_dir = Path(environment.get("NVM_DIR", str(Path.home() / ".nvm")))
    versions_dir = nvm_dir / "versions" / "node"
    try:
        entries = tuple(versions_dir.iterdir())
    except OSError:
        return ()
    candidates: list[tuple[tuple[int, ...], str]] = []
    for entry in entries:
        version = entry.name.removeprefix("v")
        parts = version.split(".")
        if len(parts) != 3 or not all(part.isdecimal() for part in parts):
            continue
        parsed = tuple(int(part) for part in parts)
        node = entry / "bin" / "node"
        if parsed[0] >= 20 and node.is_file() and os.access(node, os.X_OK):
            candidates.append((parsed, str(node)))
    return tuple(path for _version, path in sorted(candidates, reverse=True))


def resolve_node_bin(environment: Mapping[str, str] | None = None) -> str:
    """Resolve and verify a Node >=20 executable without invoking Pi."""

    resolved_environment = dict(os.environ if environment is None else environment)
    path_node = shutil.which("node", path=resolved_environment.get("PATH"))
    candidates = ((path_node,) if path_node is not None else ()) + _nvm_node_candidates(
        resolved_environment
    )
    for candidate in dict.fromkeys(candidates):
        if _probe_node(candidate, resolved_environment):
            return candidate
    raise RuntimeError(_NODE_FAILURE)


def _node_bin() -> str:
    """Return a verified Node executable; callers always use direct argv."""

    return resolve_node_bin(os.environ)


def _node_env(base: Mapping[str, str], node_bin: str | None = None) -> dict[str, str]:
    """Copy the inherited environment and optionally select a verified Node bin."""

    environment = dict(base)
    if node_bin is not None and Path(node_bin).parent != Path("."):
        node_dir = str(Path(node_bin).parent)
        current_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(
            value for value in (node_dir, current_path) if value
        )
    return environment


def ensure_built_pi_cli(package_dir: Path, *, node_bin: str | None = None) -> Path:
    """Return Pi's built CLI, building its checkout only when required."""

    dist_cli = Path(package_dir) / "dist" / "cli.js"
    if dist_cli.exists():
        return dist_cli
    pi_repo_root = Path(package_dir).parents[1]
    subprocess.run(
        ["npm", "run", "build"],
        cwd=pi_repo_root,
        env=_node_env(os.environ, node_bin),
        check=True,
    )
    if not dist_cli.exists():
        raise RuntimeError("Pi CLI build did not produce dist/cli.js")
    return dist_cli


def expand_extra_args(values: tuple[str, ...]) -> list[str]:
    """Split repeatable CLI arguments without ever involving a shell."""

    return [part for value in values for part in shlex.split(value)]


def build_pi_command(
    *,
    package_dir: Path,
    mode: str | None,
    provider: str | None,
    model: str | None,
    tools: str | None,
    no_session: bool,
    system_prompt_file: Path | None,
    append_system_prompt_file: Path | None,
    extra_args: list[str],
    messages: list[str] | None = None,
    node_bin: str | None = None,
) -> list[str]:
    """Build the Pi command as a literal argv list."""

    selected_node = _node_bin() if node_bin is None else node_bin
    command = [
        selected_node,
        str(ensure_built_pi_cli(package_dir, node_bin=selected_node)),
    ]
    if mode:
        command.extend(["--mode", mode])
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    if tools:
        command.extend(["--tools", tools])
    if system_prompt_file:
        command.extend(["--system-prompt", str(system_prompt_file)])
    if append_system_prompt_file:
        command.extend(["--append-system-prompt", str(append_system_prompt_file)])
    if no_session:
        command.append("--no-session")
    command.extend(extra_args)
    if messages:
        command.extend(messages)
    return command


def _pi_child_environment(
    *, agent_dir: Path, node_bin: str, node_max_old_space_size_mb: int | None
) -> dict[str, str]:
    environment = _node_env(os.environ, node_bin)
    environment["PI_CODING_AGENT_DIR"] = str(agent_dir)
    if node_max_old_space_size_mb is not None:
        heap_option = f"--max-old-space-size={node_max_old_space_size_mb}"
        current_options = environment.get("NODE_OPTIONS", "").strip()
        environment["NODE_OPTIONS"] = " ".join(
            value for value in (current_options, heap_option) if value
        )
    return environment


def validate_terminal_cwd(cwd: Path) -> Path:
    """Return one existing readable directory without following any symlink."""

    candidate = Path(cwd).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    absolute = Path(os.path.normpath(candidate))
    try:
        parts = absolute.parts
        current = Path(parts[0])
        for part in parts[1:]:
            current /= part
            if current.is_symlink():
                raise RuntimeError("Pi terminal cwd is unsafe")
        metadata = absolute.stat()
        if not absolute.is_dir():
            raise RuntimeError("Pi terminal cwd is unavailable")
        if metadata.st_mode & 0o444 == 0 or metadata.st_mode & 0o111 == 0:
            raise RuntimeError("Pi terminal cwd is unavailable")
        return absolute.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("Pi terminal cwd is unavailable") from error


def run_pi_terminal(
    *,
    package_dir: Path,
    cwd: Path,
    agent_dir: Path,
    provider: str | None,
    model: str | None,
    tools: str | None,
    system_prompt_file: Path | None,
    append_system_prompt_file: Path | None,
    thinking_level: str | None,
    extra_args: tuple[str, ...],
    node_max_old_space_size_mb: int | None,
    initial_question: str | None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Run Pi's interactive UI with session persistence and no artifacts."""

    terminal_stdin = sys.stdin if stdin is None else stdin
    terminal_stdout = sys.stdout if stdout is None else stdout
    if not terminal_stdin.isatty() or not terminal_stdout.isatty():
        raise RuntimeError("Pi terminal requires interactive stdin/stdout TTY")
    verified_cwd = validate_terminal_cwd(cwd)
    node_bin = resolve_node_bin(os.environ)
    literal_controls = (
        ["--thinking", thinking_level] if thinking_level is not None else []
    )
    command = build_pi_command(
        package_dir=package_dir,
        mode=None,
        provider=provider,
        model=model,
        tools=tools,
        no_session=False,
        system_prompt_file=system_prompt_file,
        append_system_prompt_file=append_system_prompt_file,
        extra_args=[*expand_extra_args(extra_args), *literal_controls],
        messages=[initial_question] if initial_question else None,
        node_bin=node_bin,
    )
    result = subprocess.run(
        command,
        cwd=verified_cwd,
        env=_pi_child_environment(
            agent_dir=agent_dir,
            node_bin=node_bin,
            node_max_old_space_size_mb=node_max_old_space_size_mb,
        ),
        check=False,
    )
    return result.returncode


def _validated_policy_state(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _DCI_STATE_KEYS:
        raise RuntimeError("Pi RPC get_entries shape is invalid")
    for key in _DCI_NUMERIC_STATE_KEYS:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise RuntimeError("Pi RPC get_entries shape is invalid")
    preserved_turns = value.get("preservedTurns")
    if not (
        preserved_turns is None
        or (
            not isinstance(preserved_turns, bool)
            and isinstance(preserved_turns, int)
            and preserved_turns >= 0
        )
    ):
        raise RuntimeError("Pi RPC get_entries shape is invalid")
    if not all(
        isinstance(value.get(key), bool)
        for key in ("compactionPending", "summarySuppressed")
    ):
        raise RuntimeError("Pi RPC get_entries shape is invalid")
    return dict(value)


def _validated_dci_entries(values: list[object]) -> tuple[dict[str, Any], ...]:
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    latest_counters: dict[str, int] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        custom_type = value.get("customType")
        if custom_type not in {"dci-context-telemetry", "dci-context-state"}:
            continue
        if set(value) != _DCI_ENTRY_KEYS or value.get("type") != "custom":
            raise RuntimeError("Pi RPC get_entries shape is invalid")
        entry_id = value.get("id")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or entry_id in seen_ids
            or not isinstance(value.get("timestamp"), str)
            or not value["timestamp"]
            or not (
                value.get("parentId") is None
                or isinstance(value.get("parentId"), str)
            )
        ):
            raise RuntimeError("Pi RPC get_entries shape is invalid")
        data = value.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Pi RPC get_entries shape is invalid")
        if custom_type == "dci-context-state":
            if set(data) != {"schema", "profile", "contractVersion", "state"}:
                raise RuntimeError("Pi RPC get_entries shape is invalid")
            if data.get("schema") != "dci.context-state/v2":
                raise RuntimeError("Pi RPC get_entries shape is invalid")
            state = _validated_policy_state(data.get("state"))
        else:
            expected = _DCI_STATE_KEYS | {
                "schema",
                "event",
                "profile",
                "contractVersion",
                "extensionVersion",
            }
            if set(data) != expected or data.get("schema") != "dci.context-telemetry/v2":
                raise RuntimeError("Pi RPC get_entries shape is invalid")
            state = _validated_policy_state(
                {key: data[key] for key in _DCI_STATE_KEYS}
            )
            for key in _DCI_CUMULATIVE_KEYS:
                current = state[key]
                prior = latest_counters.get(key, 0)
                if not isinstance(current, int) or current < prior:
                    raise RuntimeError("Pi RPC get_entries shape is invalid")
                latest_counters[key] = current
        if (
            data.get("profile") not in {
                "level0",
                "level1",
                "level2",
                "level3",
                "level4",
            }
            or data.get("contractVersion") != "dci.context-profile/v1"
            or (
                custom_type == "dci-context-telemetry"
                and (
                    not isinstance(data.get("event"), str)
                    or not data["event"]
                    or not isinstance(data.get("extensionVersion"), str)
                    or not data["extensionVersion"]
                )
            )
        ):
            raise RuntimeError("Pi RPC get_entries shape is invalid")
        seen_ids.add(entry_id)
        validated.append(dict(value))
    return tuple(validated)


class PiRpcClient:
    """Synchronous Pi JSONL-RPC lifecycle copied into the Asterion product boundary."""

    def __init__(
        self,
        *,
        package_dir: Path,
        cwd: Path,
        agent_dir: Path,
        provider: str | None,
        model: str | None,
        tools: str | None,
        show_tools: bool,
        system_prompt_file: Path | None,
        append_system_prompt_file: Path | None,
        extra_args: tuple[str, ...],
        literal_extra_args: tuple[str, ...],
        keep_session: bool,
        node_max_old_space_size_mb: int | None,
        stream_text: bool = True,
        inherited_fds: tuple[int, ...] = (),
        extension_path: Path | None = None,
        context_profile: str | None = None,
        context_contract: str | None = None,
        session_file: Path | None = None,
    ) -> None:
        context_identity = (extension_path, context_profile, context_contract)
        if any(value is not None for value in context_identity) and not all(
            value is not None for value in context_identity
        ):
            raise ValueError("Pi context extension identity is invalid")
        if extension_path is not None and (
            not isinstance(extension_path, Path) or not extension_path.is_absolute()
        ):
            raise ValueError("Pi context extension identity is invalid")
        if any(
            value is not None and (not isinstance(value, str) or not value)
            for value in (context_profile, context_contract)
        ):
            raise ValueError("Pi context extension identity is invalid")
        if session_file is not None and (
            not isinstance(session_file, Path) or not session_file.is_absolute()
        ):
            raise ValueError("Pi session identity is invalid")
        self.package_dir = Path(package_dir)
        self.cwd = Path(cwd)
        self.agent_dir = Path(agent_dir)
        self.provider = provider
        self.model = model
        self.tools = tools
        self.show_tools = show_tools
        self.system_prompt_file = system_prompt_file
        self.append_system_prompt_file = append_system_prompt_file
        self.extra_args = tuple(extra_args)
        self.literal_extra_args = tuple(literal_extra_args)
        self.keep_session = keep_session
        self.node_max_old_space_size_mb = node_max_old_space_size_mb
        self.stream_text = stream_text
        self.inherited_fds = tuple(inherited_fds)
        self.extension_path = extension_path
        self.context_profile = context_profile
        self.context_contract = context_contract
        self.session_file = session_file
        self.proc: subprocess.Popen[bytes] | None = None
        self.command: list[str] | None = None
        self.stderr_chunks: list[str] = []
        self._stdout_queue: queue.Queue[object] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._request_id = 0

    def _build_command(self, *, node_bin: str | None = None) -> list[str]:
        context_args: list[str] = []
        if self.extension_path is not None:
            assert self.context_profile is not None and self.context_contract is not None
            context_args.extend(
                [
                    "--extension",
                    str(self.extension_path),
                    "--dci-context-profile",
                    self.context_profile,
                    "--dci-context-contract",
                    self.context_contract,
                ]
            )
        if self.session_file is not None:
            context_args.extend(["--session", str(self.session_file)])
        return build_pi_command(
            package_dir=self.package_dir,
            mode="rpc",
            provider=self.provider,
            model=self.model,
            tools=self.tools,
            no_session=not self.keep_session,
            system_prompt_file=self.system_prompt_file,
            append_system_prompt_file=self.append_system_prompt_file,
            extra_args=[
                *expand_extra_args(self.extra_args),
                *self.literal_extra_args,
                *context_args,
            ],
            node_bin=node_bin,
        )

    def _child_environment(self, *, node_bin: str | None = None) -> dict[str, str]:
        """Build the Pi child environment without replacing inherited Node settings."""

        selected_node = "node" if node_bin is None else node_bin
        return _pi_child_environment(
            agent_dir=self.agent_dir,
            node_bin=selected_node,
            node_max_old_space_size_mb=self.node_max_old_space_size_mb,
        )

    def start(self) -> None:
        if self.proc is not None:
            raise RuntimeError("RPC client already started")
        node_bin = resolve_node_bin(os.environ)
        environment = self._child_environment(node_bin=node_bin)
        self.command = self._build_command(node_bin=node_bin)
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=self.inherited_fds,
        )
        self._stdout_queue = queue.Queue()
        self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for raw in self.proc.stdout:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._stdout_queue.put(RuntimeError("Pi RPC emitted invalid JSONL"))
                    return
                if not isinstance(payload, dict):
                    self._stdout_queue.put(
                        RuntimeError("Pi RPC emitted a non-object JSON value")
                    )
                    return
                self._stdout_queue.put(payload)
        finally:
            self._stdout_queue.put(_STDOUT_EOF)

    def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for raw in self.proc.stderr:
            self.stderr_chunks.append(raw.decode("utf-8", errors="replace"))

    def stop(self) -> None:
        if self.proc is None:
            return
        process = self.proc
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        finally:
            for thread in (self._stdout_thread, self._stderr_thread):
                if thread is not None:
                    thread.join(timeout=1)
            self._stdout_thread = None
            self._stderr_thread = None
            self.proc = None

    def _next_id(self) -> str:
        self._request_id += 1
        return f"py-{self._request_id}"

    def _send(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("RPC client is not running")
        self.proc.stdin.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )
        self.proc.stdin.flush()

    def _read_json_line(
        self, *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        try:
            item = self._stdout_queue.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise TimeoutError("Timed out waiting for an RPC event") from error
        if item is _STDOUT_EOF:
            raise RuntimeError("Pi RPC process exited unexpectedly")
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, dict):
            raise RuntimeError("Pi RPC queue returned an invalid event")
        return item

    def probe_protocol(
        self,
        *,
        timeout_seconds: float = 10.0,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id()
        self._send({"id": request_id, "type": "get_state"})
        deadline = time.monotonic() + timeout_seconds
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Pi RPC protocol probe was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Pi RPC protocol probe timed out")
            try:
                response = self._read_json_line(
                    timeout_seconds=(
                        remaining
                        if cancel_event is None
                        else min(0.1, remaining)
                    )
                )
            except TimeoutError:
                if cancel_event is not None and time.monotonic() < deadline:
                    continue
                raise RuntimeError("Pi RPC protocol probe timed out") from None
            if response.get("type") != "response" or response.get("id") != request_id:
                if on_event is not None:
                    on_event(response)
                continue
            state = response.get("data")
            if response.get("success") is not True or not isinstance(state, dict):
                raise RuntimeError("Pi RPC get_state failed")
            for field, expected in {
                "isStreaming": bool,
                "isCompacting": bool,
                "messageCount": int,
                "pendingMessageCount": int,
            }.items():
                value = state.get(field)
                if not isinstance(value, expected) or (
                    expected is int and isinstance(value, bool)
                ):
                    raise RuntimeError("Pi RPC get_state shape is invalid")
            return state

    def get_entries(
        self, *, since: str | None = None, timeout_seconds: float = 10.0
    ) -> tuple[dict[str, Any], ...]:
        """Return only closed, body-free DCI extension entries from Pi."""

        if since is not None and (not isinstance(since, str) or not since):
            raise ValueError("Pi RPC get_entries cursor is invalid")
        request_id = self._next_id()
        request: dict[str, Any] = {"id": request_id, "type": "get_entries"}
        if since is not None:
            request["since"] = since
        self._send(request)
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Pi RPC get_entries timed out")
            response = self._read_json_line(timeout_seconds=remaining)
            if response.get("type") != "response" or response.get("id") != request_id:
                continue
            if (
                response.get("command") != "get_entries"
                or response.get("success") is not True
            ):
                raise RuntimeError("Pi RPC get_entries failed")
            data = response.get("data")
            if not isinstance(data, dict) or set(data) != {"entries", "leafId"}:
                raise RuntimeError("Pi RPC get_entries shape is invalid")
            entries = data.get("entries")
            leaf_id = data.get("leafId")
            if not isinstance(entries, list) or not (
                leaf_id is None or isinstance(leaf_id, str)
            ):
                raise RuntimeError("Pi RPC get_entries shape is invalid")
            return _validated_dci_entries(entries)

    def prompt_and_wait(
        self,
        message: str,
        *,
        max_turns: int | None = None,
        timeout_seconds: float | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_event: threading.Event | None = None,
        recover_empty_final: bool = False,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("RPC prompt was cancelled")
        request_id = self._next_id()
        self._send({"id": request_id, "type": "prompt", "message": message})
        text_parts: list[str] = []
        prompt_ack = False
        turns = 0
        sent_abort = False
        settled = False
        terminal_assistant_error = False
        deadline = (
            time.monotonic() + timeout_seconds
            if timeout_seconds and timeout_seconds > 0
            else None
        )

        def abort() -> None:
            try:
                self._send({"id": self._next_id(), "type": "abort"})
            except (BrokenPipeError, RuntimeError):
                pass

        while True:
            if cancel_event is not None and cancel_event.is_set():
                abort()
                raise RuntimeError("RPC prompt was cancelled")
            try:
                remaining = (
                    None if deadline is None else max(0.0, deadline - time.monotonic())
                )
                poll_timeout = (
                    remaining
                    if cancel_event is None
                    else 0.1 if remaining is None else min(0.1, remaining)
                )
                event = self._read_json_line(timeout_seconds=poll_timeout)
            except TimeoutError as error:
                if cancel_event is not None and not cancel_event.is_set() and (
                    deadline is None or time.monotonic() < deadline
                ):
                    continue
                abort()
                raise RuntimeError(
                    f"RPC prompt timed out after {timeout_seconds:g} seconds"
                ) from error
            if on_event is not None:
                on_event(event)
            event_type = event.get("type")
            if event_type == "response":
                if event.get("id") == request_id:
                    if event.get("success") is not True:
                        raise RuntimeError("RPC prompt failed")
                    prompt_ack = True
                continue
            if event_type == "agent_start":
                text_parts = []
                terminal_assistant_error = False
                continue
            if event_type == "turn_start":
                turns += 1
                if max_turns is not None and turns > max_turns and not sent_abort:
                    self._send({"id": self._next_id(), "type": "abort"})
                    sent_abort = True
                    print(
                        f"[runner] Reached max_turns={max_turns}; sent RPC abort.",
                        file=sys.stderr,
                    )
                continue
            if event_type == "message_update":
                assistant_event = event.get("assistantMessageEvent", {})
                if (
                    isinstance(assistant_event, Mapping)
                    and assistant_event.get("type") == "text_delta"
                ):
                    delta = assistant_event.get("delta")
                    if isinstance(delta, str):
                        text_parts.append(delta)
                        if self.stream_text:
                            print(delta, end="", file=sys.stdout, flush=True)
                continue
            if event_type == "message_end":
                message_value = event.get("message")
                if (
                    isinstance(message_value, Mapping)
                    and message_value.get("role") == "assistant"
                    and message_value.get("stopReason") == "error"
                ):
                    terminal_assistant_error = True
                continue
            if event_type == "tool_execution_start" and self.show_tools:
                print(
                    f"[tool:start] {event.get('toolName', 'unknown')}", file=sys.stderr
                )
                continue
            if event_type == "tool_execution_end" and self.show_tools:
                error_state = "yes" if event.get("isError") else "no"
                print(
                    f"[tool:end] {event.get('toolName', 'unknown')} error={error_state}",
                    file=sys.stderr,
                )
                continue
            if event_type == "agent_end":
                if not prompt_ack:
                    raise RuntimeError(
                        "Received agent_end before prompt acknowledgement"
                    )
                if "willRetry" not in event:
                    break
                continue
            if event_type == "agent_settled":
                if not prompt_ack:
                    raise RuntimeError(
                        "Received agent_settled before prompt acknowledgement"
                    )
                settled = True
                break
        if terminal_assistant_error:
            raise RuntimeError("Pi provider returned an assistant error")
        if settled:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    abort()
                    raise RuntimeError("RPC prompt was cancelled")
                remaining = (
                    None if deadline is None else deadline - time.monotonic()
                )
                if remaining is not None and remaining <= 0:
                    abort()
                    raise RuntimeError(
                        f"RPC prompt timed out after {timeout_seconds:g} seconds"
                    )
                try:
                    state = self.probe_protocol(
                        timeout_seconds=(
                            10.0 if remaining is None else min(10.0, remaining)
                        ),
                        on_event=on_event,
                        cancel_event=cancel_event,
                    )
                except RuntimeError:
                    if cancel_event is not None and cancel_event.is_set():
                        abort()
                        raise RuntimeError("RPC prompt was cancelled") from None
                    if deadline is not None and time.monotonic() >= deadline:
                        abort()
                        raise RuntimeError(
                            f"RPC prompt timed out after {timeout_seconds:g} seconds"
                        ) from None
                    raise
                if not state["isCompacting"]:
                    break
                time.sleep(0.05)
            if (
                state["isStreaming"]
                or state["pendingMessageCount"] != 0
            ):
                raise RuntimeError(
                    "Pi RPC agent_settled postcondition failed: session is not idle"
                )
        final_text = "".join(text_parts)
        if recover_empty_final and not final_text.strip():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise RuntimeError(
                    f"RPC prompt timed out after {timeout_seconds:g} seconds"
                )
            return final_text + self.prompt_and_wait(
                FINAL_ANSWER_RECOVERY_PROMPT,
                max_turns=1,
                timeout_seconds=remaining,
                on_event=on_event,
                cancel_event=cancel_event,
            )
        return final_text

    def get_stderr(self) -> str:
        return "".join(self.stderr_chunks)
