"""Independent Agent Runtime Protocol client for the Pi JSONL RPC process."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import json
import os
import secrets
import signal as process_signal
import stat
import sys
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from asterion.adapters.pi import PiProtocolAdapter
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError, validate_event_stream


_MAX_STDOUT_LINE_BYTES = 64 * 1024
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_EVENT_COUNT = 2048
_MAX_FINAL_TEXT_BYTES = 1024 * 1024
_PROCESS_EXIT_SECONDS = 1.0
_PIPE_DRAIN_SECONDS = 0.5
_SECURE_EVIDENCE_AVAILABLE = (
    sys.platform in {"darwin", "linux"}
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.listdir in os.supports_fd
    and os.mkdir in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.unlink in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd
)


@dataclass(frozen=True)
class _RuntimeSnapshot:
    events: tuple[dict[str, object], ...]
    final_text: str


@dataclass
class _StagedEvidence:
    name: str
    target: str
    published: bool = False


class PiRuntimeClient:
    """Run one request in a fresh explicitly configured Pi RPC process."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        capabilities: tuple[str, ...],
        env: Mapping[str, str] | None = None,
        max_turns: int = 4,
        evidence_root: Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        tools: tuple[str, ...] = (),
        context_profile: str | None = None,
    ) -> None:
        if not command:
            raise ValueError("Pi runtime command must not be empty")
        self._command = tuple(command)
        self._cwd = Path(cwd)
        self._capabilities = tuple(capabilities)
        self._env = dict(os.environ if env is None else env)
        if (
            isinstance(max_turns, bool)
            or not isinstance(max_turns, int)
            or max_turns <= 0
        ):
            raise ValueError("Pi runtime max turns is invalid")
        self._max_turns = max_turns
        self._evidence_root = (
            Path(evidence_root) if evidence_root is not None else None
        )
        self._completed_runs: dict[str, Path] = {}
        self._completed_run_identities: dict[
            str, tuple[tuple[int, int], tuple[int, int]]
        ] = {}
        self._provider = provider
        self._model = model
        self._tools = tuple(tools)
        self._context_profile = context_profile
        self._running = False

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="pi.reference", capabilities=self._capabilities
        )

    def completed_run_dir(self, run_id: str) -> Path | None:
        """Return private evidence only for a completed run owned by this client."""

        path = self._completed_runs.get(run_id)
        identities = self._completed_run_identities.get(run_id)
        if path is None or identities is None or self._evidence_root is None:
            return None
        try:
            root = os.stat(self._evidence_root, follow_symlinks=False)
            output = os.stat(path, follow_symlinks=False)
        except OSError:
            return None
        if (
            not stat.S_ISDIR(root.st_mode)
            or not stat.S_ISDIR(output.st_mode)
            or (root.st_dev, root.st_ino) != identities[0]
            or (output.st_dev, output.st_ino) != identities[1]
        ):
            return None
        return path

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        request.to_mapping()
        if any(
            capability not in self._capabilities
            for capability in request.requested_capabilities
        ):
            raise ProtocolError("Pi runtime capability is unavailable")
        if signal is not None and signal.cancelled:
            raise ProtocolError("Pi runtime request was cancelled before invocation")
        if self._running:
            raise ProtocolError("Pi runtime already has an active request")
        if request.run_id in self._completed_runs:
            raise ProtocolError("Pi runtime run ID is already completed")

        self._running = True
        staged: _StagedEvidence | None = None
        root_context = (
            _pin_evidence_root(self._evidence_root, create=True)
            if self._evidence_root is not None
            else nullcontext(None)
        )
        try:
            with root_context as root:
                try:
                    snapshot = await _collect_runtime_snapshot(
                        command=self._command,
                        cwd=self._cwd,
                        environment=self._env,
                        capabilities=self._capabilities,
                        max_turns=self._max_turns,
                        request=request,
                        signal=signal,
                    )
                    validate_event_stream(snapshot.events)
                    if snapshot.events[-1]["type"] != "run.completed":
                        raise ProtocolError("Pi runtime execution failed")
                    for mapping in snapshot.events:
                        yield RunEvent.from_mapping(mapping)

                    if root is not None:
                        root_fd, root_identity = root
                        _assert_pinned_root(
                            self._evidence_root, root_fd, root_identity
                        )
                        staged = _stage_evidence(
                            root_fd,
                            request.run_id,
                            final_text=snapshot.final_text,
                            events=snapshot.events,
                        )
                        _assert_pinned_root(
                            self._evidence_root, root_fd, root_identity
                        )
                        target_identity = _publish_evidence(root_fd, staged)
                        try:
                            _assert_pinned_root(
                                self._evidence_root, root_fd, root_identity
                            )
                        except ProtocolError:
                            _cleanup_evidence(root_fd, staged.target)
                            staged.published = False
                            raise
                        assert self._evidence_root is not None
                        self._completed_runs[request.run_id] = (
                            self._evidence_root / staged.target
                        )
                        self._completed_run_identities[request.run_id] = (
                            root_identity,
                            target_identity,
                        )
                finally:
                    if (
                        root is not None
                        and staged is not None
                        and not staged.published
                    ):
                        try:
                            _cleanup_evidence(root[0], staged.name)
                        except OSError:
                            pass
        except ProtocolError:
            raise
        except (OSError, TypeError, ValueError):
            raise ProtocolError("Pi runtime execution failed") from None
        finally:
            self._running = False


async def _collect_runtime_snapshot(
    *,
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    capabilities: tuple[str, ...],
    max_turns: int,
    request: RunRequest,
    signal: CancellationSignal | None,
) -> _RuntimeSnapshot:
    emitted: list[dict[str, object]] = []
    adapter = PiProtocolAdapter(
        run_id=request.run_id,
        capabilities=list(request.requested_capabilities),
        emit=emitted.append,
    )
    adapter.start()
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
    except (OSError, ValueError):
        raise ProtocolError("Pi runtime process failed to start") from None

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_task = asyncio.create_task(
        _drain_capped(process.stderr, _MAX_STDERR_BYTES)
    )
    graceful = False
    final_text = ""
    try:
        payload = {
            "id": "asterion-1",
            "type": "prompt",
            "message": request.input_text,
        }
        process.stdin.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )
        await asyncio.wait_for(process.stdin.drain(), timeout=0.5)
        acknowledged = False
        assistant_error = False
        answer_parts: list[str] = []
        answer_bytes = 0
        attempt_event_start = len(emitted)
        turns = 0
        event_count = 0
        stdout_bytes = 0
        deadline = (
            asyncio.get_running_loop().time() + request.deadline_ms / 1000
            if request.deadline_ms is not None
            else None
        )
        while True:
            if (
                deadline is not None
                and asyncio.get_running_loop().time() >= deadline
            ):
                raise ProtocolError("Pi runtime request deadline expired")
            if signal is not None and signal.cancelled:
                await _send_abort(process)
                raise ProtocolError("Pi runtime request was cancelled")
            try:
                raw = await asyncio.wait_for(
                    process.stdout.readline(), timeout=0.05
                )
            except TimeoutError:
                continue
            except (ValueError, asyncio.LimitOverrunError):
                raise ProtocolError("Pi runtime output limit exceeded") from None
            if not raw:
                raise ProtocolError("Pi runtime process ended before completion")
            event_count += 1
            stdout_bytes += len(raw)
            if (
                len(raw) > _MAX_STDOUT_LINE_BYTES
                or stdout_bytes > _MAX_STDOUT_BYTES
                or event_count > _MAX_EVENT_COUNT
            ):
                raise ProtocolError("Pi runtime output limit exceeded")
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ProtocolError("Pi runtime emitted invalid JSONL") from None
            if not isinstance(event, dict):
                raise ProtocolError("Pi runtime emitted an invalid JSONL object")

            event_type = event.get("type")
            if event_type == "response" and event.get("id") == "asterion-1":
                if event.get("success") is not True:
                    raise ProtocolError("Pi runtime rejected the request")
                acknowledged = True
                continue
            if event_type == "agent_start":
                answer_parts = []
                answer_bytes = 0
                assistant_error = False
                attempt_event_start = len(emitted)
                adapter.consume(event)
                continue
            if event_type == "turn_start":
                turns += 1
                if turns > max_turns:
                    await _send_abort(process)
                    raise ProtocolError("Pi runtime turn limit exceeded")
                adapter.consume(event)
                continue
            if event_type == "message_update":
                delta = _assistant_delta(event)
                if delta is not None:
                    answer_bytes += len(delta.encode())
                    if answer_bytes > _MAX_FINAL_TEXT_BYTES:
                        raise ProtocolError("Pi runtime output limit exceeded")
                    answer_parts.append(delta)
                adapter.consume(event)
                continue
            if event_type == "message_end":
                message = event.get("message")
                if isinstance(message, Mapping) and message.get("role") == "assistant":
                    if message.get("stopReason") == "error":
                        assistant_error = True
                    if not "".join(answer_parts).strip():
                        recovered = _assistant_message_text(message)
                        if recovered:
                            recovered_bytes = len(recovered.encode())
                            if recovered_bytes > _MAX_FINAL_TEXT_BYTES:
                                raise ProtocolError("Pi runtime output limit exceeded")
                            answer_parts = [recovered]
                            answer_bytes = recovered_bytes
                adapter.consume(event)
                continue
            if event_type in {"agent_end", "agent_settled"}:
                if not acknowledged:
                    raise ProtocolError(
                        "Pi runtime completed before acknowledgement"
                    )
                if event_type == "agent_end" and "willRetry" in event:
                    del emitted[attempt_event_start:]
                    adapter.sequence = len(emitted)
                    adapter.tool_calls.clear()
                    adapter.tool_results.clear()
                    continue
                if assistant_error:
                    raise ProtocolError("Pi runtime provider execution failed")
                final_text = "".join(answer_parts)
                if not final_text.strip():
                    raise ProtocolError("Pi runtime answer is unavailable")
                if not any(item.get("type") == "text.delta" for item in emitted):
                    adapter.consume(
                        {
                            "type": "message_update",
                            "assistantMessageEvent": {
                                "type": "text_delta",
                                "delta": final_text,
                            },
                        }
                    )
                adapter.complete(
                    artifact={
                        "artifact_id": "final-answer",
                        "kind": "answer",
                        "media_type": "text/plain",
                        "uri": "final.txt",
                    }
                )
                graceful = True
                break
            adapter.consume(event)
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        raise ProtocolError("Pi runtime execution failed") from None
    finally:
        returncode = await _finalize_process_uninterruptibly(
            process, stderr_task, graceful=graceful
        )

    if returncode != 0:
        raise ProtocolError("Pi runtime execution failed")
    return _RuntimeSnapshot(tuple(emitted), final_text)


def _assistant_delta(event: Mapping[str, object]) -> str | None:
    value = event.get("assistantMessageEvent")
    if (
        isinstance(value, Mapping)
        and value.get("type") == "text_delta"
        and isinstance(value.get("delta"), str)
    ):
        return value["delta"]
    return None


def _assistant_message_text(message: Mapping[str, object]) -> str:
    direct = message.get("text")
    if isinstance(direct, str):
        return direct
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if (
            isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            parts.append(block["text"])
    return "".join(parts)


async def _send_abort(process: asyncio.subprocess.Process) -> None:
    if process.stdin is None or process.stdin.is_closing():
        return
    try:
        process.stdin.write(b'{"id":"asterion-abort","type":"abort"}\n')
        await asyncio.wait_for(process.stdin.drain(), timeout=0.1)
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        pass


async def _drain_capped(
    stream: asyncio.StreamReader, limit: int
) -> bytes:
    retained = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return bytes(retained)
        remaining = limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])


async def _finalize_process_uninterruptibly(
    process: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
    *,
    graceful: bool,
) -> int | None:
    finalizer = asyncio.create_task(
        _finalize_owned_process(process, stderr_task, graceful=graceful)
    )
    interrupted = False
    while not finalizer.done():
        try:
            await asyncio.shield(finalizer)
        except asyncio.CancelledError:
            interrupted = True
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
    result = finalizer.result()
    if interrupted:
        raise asyncio.CancelledError
    return result


async def _finalize_owned_process(
    process: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
    *,
    graceful: bool,
) -> int | None:
    if process.stdin is not None and not process.stdin.is_closing():
        process.stdin.close()
    if not graceful:
        _signal_process_group(process, process_signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_EXIT_SECONDS)
    except TimeoutError:
        _signal_process_group(process, process_signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=_PROCESS_EXIT_SECONDS)
        except TimeoutError:
            _signal_process_group(process, process_signal.SIGKILL)
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=_PROCESS_EXIT_SECONDS
                )
            except TimeoutError:
                pass

    if os.name != "nt":
        _signal_process_group(process, process_signal.SIGTERM)
    try:
        await asyncio.wait_for(
            asyncio.shield(stderr_task), timeout=_PIPE_DRAIN_SECONDS
        )
    except TimeoutError:
        _signal_process_group(process, process_signal.SIGKILL)
        try:
            await asyncio.wait_for(
                asyncio.shield(stderr_task), timeout=_PIPE_DRAIN_SECONDS
            )
        except TimeoutError:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
    return process.returncode


def _signal_process_group(
    process: asyncio.subprocess.Process, signal_number: int
) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal_number)
        elif process.returncode is None:
            if signal_number == process_signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
    except (OSError, ProcessLookupError):
        pass


def prepare_pi_evidence_root(path: Path) -> Path:
    """Create and validate one exact private evidence root without following links."""

    value = _canonical_absolute_path(path)
    try:
        with _pin_evidence_root(value, create=True):
            pass
    except (OSError, ProtocolError, ValueError):
        raise ValueError("Pi reference runtime configuration is invalid") from None
    return value


def _canonical_absolute_path(path: Path) -> Path:
    value = Path(path)
    if (
        not value.is_absolute()
        or any(part in {"", ".", ".."} for part in value.parts[1:])
        or str(value.resolve(strict=False)) != str(value)
    ):
        raise ValueError("Pi path is not canonical")
    return value


@contextmanager
def _pin_evidence_root(
    path: Path | None, *, create: bool
) -> Iterator[tuple[int, tuple[int, int]]]:
    if path is None or not _SECURE_EVIDENCE_AVAILABLE:
        raise ProtocolError("Pi runtime evidence is unavailable")
    try:
        value = _canonical_absolute_path(path)
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        current = os.open("/", flags)
        try:
            components = value.parts[1:]
            for index, component in enumerate(components):
                final = index == len(components) - 1
                try:
                    next_fd = os.open(component, flags, dir_fd=current)
                except OSError as error:
                    if (
                        create
                        and final
                        and error.errno == errno.ENOENT
                    ):
                        os.mkdir(component, 0o700, dir_fd=current)
                        next_fd = os.open(component, flags, dir_fd=current)
                    else:
                        raise
                os.close(current)
                current = next_fd
            details = os.fstat(current)
            if (
                not stat.S_ISDIR(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o700
                or (
                    hasattr(os, "getuid")
                    and details.st_uid != os.getuid()
                )
            ):
                raise OSError("invalid evidence root")
            identity = (details.st_dev, details.st_ino)
            _assert_pinned_root(value, current, identity)
            yield current, identity
        finally:
            os.close(current)
    except (OSError, ValueError):
        raise ProtocolError("Pi runtime evidence is unavailable") from None


def _assert_pinned_root(
    path: Path | None,
    root_fd: int,
    identity: tuple[int, int],
) -> None:
    if path is None:
        raise ProtocolError("Pi runtime evidence is unavailable")
    try:
        details = os.stat(path, follow_symlinks=False)
        pinned = os.fstat(root_fd)
    except OSError:
        raise ProtocolError("Pi runtime evidence is unavailable") from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or (details.st_dev, details.st_ino) != identity
        or (pinned.st_dev, pinned.st_ino) != identity
    ):
        raise ProtocolError("Pi runtime evidence is unavailable")


def _stage_evidence(
    root_fd: int,
    run_id: str,
    *,
    final_text: str,
    events: Sequence[Mapping[str, object]],
) -> _StagedEvidence:
    staged = _StagedEvidence(
        name=f".pending-{secrets.token_hex(16)}",
        target=hashlib.sha256(run_id.encode()).hexdigest(),
    )
    directory_fd = -1
    try:
        _ensure_missing(root_fd, staged.target)
        os.mkdir(staged.name, 0o700, dir_fd=root_fd)
        directory_fd = _open_directory_at(root_fd, staged.name)
        _write_private_at(directory_fd, "final.txt", final_text.encode())
        raw_events = bytearray()
        for event in events:
            raw_events.extend(
                (
                    json.dumps(
                        dict(event),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode()
            )
            if len(raw_events) > _MAX_STDOUT_BYTES:
                raise OSError("evidence limit exceeded")
        _write_private_at(directory_fd, "events.jsonl", bytes(raw_events))
        os.fsync(directory_fd)
        return staged
    except (OSError, TypeError, ValueError):
        _cleanup_evidence(root_fd, staged.name)
        raise ProtocolError("Pi runtime evidence is unavailable") from None
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _publish_evidence(
    root_fd: int, staged: _StagedEvidence
) -> tuple[int, int]:
    _validate_staged_evidence(root_fd, staged.name)
    if _rename_exclusive(
        root_fd, staged.name, root_fd, staged.target
    ):
        try:
            os.fsync(root_fd)
            details = os.stat(
                staged.target, dir_fd=root_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o700
            ):
                raise OSError("invalid published evidence")
            staged.published = True
            return details.st_dev, details.st_ino
        except OSError:
            _cleanup_evidence(root_fd, staged.target)
            raise ProtocolError("Pi runtime evidence is unavailable") from None

    target_fd = -1
    stage_fd = -1
    target_created = False
    try:
        _ensure_missing(root_fd, staged.target)
        os.mkdir(staged.target, 0o700, dir_fd=root_fd)
        target_created = True
        stage_fd = _open_directory_at(root_fd, staged.name)
        target_fd = _open_directory_at(root_fd, staged.target)
        for name in ("events.jsonl", "final.txt"):
            os.rename(
                name,
                name,
                src_dir_fd=stage_fd,
                dst_dir_fd=target_fd,
            )
        os.fsync(target_fd)
        os.rmdir(staged.name, dir_fd=root_fd)
        os.fsync(root_fd)
        details = os.stat(
            staged.target, dir_fd=root_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISDIR(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise OSError("invalid published evidence")
        staged.published = True
        return details.st_dev, details.st_ino
    except OSError:
        if target_created:
            _cleanup_evidence(root_fd, staged.target)
        raise ProtocolError("Pi runtime evidence is unavailable") from None
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if stage_fd >= 0:
            os.close(stage_fd)


def _validate_staged_evidence(root_fd: int, name: str) -> None:
    directory_fd = -1
    try:
        directory_fd = _open_directory_at(root_fd, name)
        if sorted(os.listdir(directory_fd)) != ["events.jsonl", "final.txt"]:
            raise OSError("invalid staged evidence")
        for child in ("events.jsonl", "final.txt"):
            details = os.stat(
                child, dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                raise OSError("invalid staged evidence")
    except OSError:
        raise ProtocolError("Pi runtime evidence is unavailable") from None
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _rename_exclusive(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> bool:
    library = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flag = 0x00000004
    elif sys.platform == "linux":
        function = getattr(library, "renameat2", None)
        flag = 0x1
    else:
        return False
    if function is None:
        return False
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        source_fd,
        encoded_source,
        destination_fd,
        encoded_destination,
        flag,
    )
    if result == 0:
        return True
    error = ctypes.get_errno()
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        return False
    raise OSError(error, "exclusive evidence publication failed")


def _open_directory_at(parent_fd: int, name: str) -> int:
    return os.open(
        name,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )


def _write_private_at(directory_fd: int, name: str, value: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(value)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_missing(directory_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise OSError("evidence destination exists")


def _cleanup_evidence(root_fd: int, name: str) -> None:
    directory_fd = -1
    try:
        directory_fd = _open_directory_at(root_fd, name)
    except OSError:
        return
    try:
        for child in ("events.jsonl", "final.txt"):
            try:
                os.unlink(child, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)
    try:
        os.rmdir(name, dir_fd=root_fd)
    except FileNotFoundError:
        pass
