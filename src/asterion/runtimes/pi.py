"""Independent Agent Runtime Protocol client for the Pi JSONL RPC process."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path

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
    ) -> None:
        if not command:
            raise ValueError("Pi runtime command must not be empty")
        self._command = tuple(command)
        self._cwd = Path(cwd)
        self._capabilities = tuple(capabilities)
        self._env = dict(os.environ if env is None else env)
        self._running = False

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="pi.reference", capabilities=self._capabilities
        )

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

        validate_event_stream(emitted)
        for event in emitted:
            yield RunEvent.from_mapping(event)
