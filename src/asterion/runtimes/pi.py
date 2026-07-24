"""Independent Agent Runtime Protocol client for the Pi JSONL RPC process."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from asterion.adapters.pi import PiProtocolAdapter
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtime.protocol import ProtocolError, validate_event_stream


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

        return self._completed_runs.get(run_id)

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

        emitted: list[dict[str, object]] = []
        adapter = PiProtocolAdapter(
            run_id=request.run_id,
            capabilities=list(request.requested_capabilities),
            emit=emitted.append,
        )
        adapter.start()
        self._running = True
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=self._cwd,
                env=self._env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError):
            self._running = False
            raise ProtocolError("Pi runtime process failed to start") from None
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stderr_task = asyncio.create_task(process.stderr.read())
        try:
            payload = {
                "id": "asterion-1",
                "type": "prompt",
                "message": request.input_text,
            }
            process.stdin.write(
                (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            )
            await process.stdin.drain()
            acknowledged = False
            turns = 0
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
                    process.terminate()
                    raise ProtocolError("Pi runtime request deadline expired")
                if signal is not None and signal.cancelled:
                    try:
                        process.stdin.write(
                            b'{"id":"asterion-abort","type":"abort"}\n'
                        )
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    process.terminate()
                    raise ProtocolError("Pi runtime request was cancelled")
                try:
                    raw = await asyncio.wait_for(
                        process.stdout.readline(), timeout=0.05
                    )
                except TimeoutError:
                    continue
                if not raw:
                    raise ProtocolError("Pi runtime process ended before completion")
                try:
                    event = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ProtocolError("Pi runtime emitted invalid JSONL") from None
                if not isinstance(event, dict):
                    raise ProtocolError("Pi runtime emitted an invalid JSONL object")
                if event.get("type") == "response" and event.get("id") == "asterion-1":
                    if event.get("success") is not True:
                        raise ProtocolError("Pi runtime rejected the request")
                    acknowledged = True
                    continue
                if event.get("type") == "agent_end":
                    if not acknowledged:
                        raise ProtocolError("Pi runtime completed before acknowledgement")
                    adapter.complete(
                        artifact={
                            "artifact_id": "final-answer",
                            "kind": "answer",
                            "media_type": "text/plain",
                            "uri": "final.txt",
                        }
                    )
                    break
                if event.get("type") == "message_end":
                    message = event.get("message")
                    if isinstance(message, Mapping) and message.get("role") == "assistant":
                        turns += 1
                        if turns > self._max_turns:
                            process.terminate()
                            raise ProtocolError("Pi runtime turn limit exceeded")
                adapter.consume(event)
        except (BrokenPipeError, ProtocolError):
            raise ProtocolError("Pi runtime execution failed") from None
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            await stderr_task
            self._running = False

        if process.returncode != 0:
            raise ProtocolError("Pi runtime execution failed")
        validate_event_stream(emitted)
        if emitted[-1]["type"] != "run.completed":
            raise ProtocolError("Pi runtime execution failed")
        final_text = "".join(
            str(payload["text"])
            for event in emitted
            if event.get("type") == "text.delta"
            and isinstance((payload := event.get("payload")), Mapping)
            and isinstance(payload.get("text"), str)
        )
        if not final_text:
            raise ProtocolError("Pi runtime execution failed")
        if self._evidence_root is not None:
            output_dir = _persist_completed_run(
                self._evidence_root,
                request.run_id,
                final_text=final_text,
                events=emitted,
            )
            self._completed_runs[request.run_id] = output_dir
        for event in emitted:
            yield RunEvent.from_mapping(event)


def _write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, value.encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o600)


def _persist_completed_run(
    evidence_root: Path,
    run_id: str,
    *,
    final_text: str,
    events: Sequence[Mapping[str, object]],
) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_root.chmod(0o700)
    output_dir = evidence_root / hashlib.sha256(run_id.encode()).hexdigest()
    if output_dir.exists():
        raise ProtocolError("Pi runtime evidence is unavailable")
    try:
        with TemporaryDirectory(prefix=".pending-", dir=evidence_root) as temporary:
            pending = Path(temporary)
            pending.chmod(0o700)
            _write_private(pending / "final.txt", final_text)
            _write_private(
                pending / "events.jsonl",
                "".join(
                    json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n"
                    for event in events
                ),
            )
            pending.replace(output_dir)
    except OSError:
        raise ProtocolError("Pi runtime evidence is unavailable") from None
    return output_dir
