"""P3 host lifecycle over an injected three-worker execution service."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Literal, Protocol

from .docker_worker import _LifecycleCallControl
from .p3_development_gateway import PrimeP3DevelopmentGateway
from .p3_development_sdk_provider import create_prime_p3_development_sdk_provider

from .p3_development_workload import (
    P3_AGGREGATE_BYTES,
    P3_DEVELOPMENT_WORKLOAD_DIGEST,
    P3_ROOT_PROMPT,
    P3_IMPLEMENTATION_PROMPT,
    P3_REVIEW_PROMPT,
    P3_FOLLOW_UP_PROMPT,
    validate_p3_aggregate_bytes,
    validate_p3_source_bytes,
    validate_p3_test_bytes,
)


class PrimeP3DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development host is unavailable")


class P3Gateway(Protocol):
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    async def cancel(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
    async def request_nested(
        self, kind: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]: ...


class P3ExecutionService(Protocol):
    async def start(self) -> None: ...
    async def execute(self, role: str, cell: str) -> None: ...
    async def read(self, name: str) -> bytes: ...
    async def cleanup(self) -> None: ...


@dataclass(frozen=True, repr=False)
class PrimeP3DevelopmentTrace:
    trace_sha256: str
    scope: Literal["p3-development"] = "p3-development"
    promotion: Literal["unpromoted"] = "unpromoted"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trace_sha256, str)
            or len(self.trace_sha256) != 71
            or not self.trace_sha256.startswith("sha256:")
        ):
            raise PrimeP3DevelopmentHostError()


async def run_prime_p3_development(
    *,
    image_digest: str,
    transport: object,
    operator_config: Mapping[str, object],
    node_bin: str,
    entrypoint: str,
    prime_source_root: str,
    run_id: str,
) -> PrimeP3DevelopmentTrace:
    """Run the fixed P3 graph through real provider, gateway, and workers."""
    opened = cleaned = False
    workers: tuple[object, ...] = ()
    control = _LifecycleCallControl(monotonic() + 180.0, None)
    try:
        if not all(isinstance(value, str) and value for value in (
            image_digest, node_bin, entrypoint, prime_source_root, run_id
        )) or not image_digest.startswith("sha256:") or len(image_digest) != 71:
            raise ValueError
        provider = create_prime_p3_development_sdk_provider(operator_config)
        calls = {"root": 0, "implementation": 0, "review": 0}
        tools = {"root": 0, "implementation": 0, "review": 0}
        tool_ids: set[str] = set()
        gateway: PrimeP3DevelopmentGateway | None = None

        async def model_hook(payload: object) -> object:
            if type(payload) is not dict or type(payload.get("role")) is not str:
                raise ValueError
            role = payload["role"]
            if role not in calls:
                raise ValueError
            request = {key: value for key, value in payload.items() if key != "role"}
            if set(request) != {"model", "context", "options"}:
                raise ValueError
            reply = await provider.callback(role, _canonical(request))
            value = json.loads(reply)
            if type(value) is not dict or value.get("role") != "assistant":
                raise ValueError
            calls[role] += 1
            return value

        async def tool_hook(payload: object) -> object:
            if (
                type(payload) is not dict
                or set(payload) != {"role", "tool_call_id", "code"}
                or payload.get("role") not in tools
                or type(payload.get("tool_call_id")) is not str
                or not payload["tool_call_id"]
                or payload["tool_call_id"] in tool_ids
                or type(payload.get("code")) is not str
                or not payload["code"]
            ):
                raise ValueError
            role = payload["role"]
            worker = next((item for item in workers if getattr(item, "role", item) == role), None)
            if worker is None:
                raise ValueError
            await transport.execute(worker, payload["code"], control)
            tool_ids.add(payload["tool_call_id"])
            tools[role] += 1
            return {"content": [{"text": "IPython cell completed", "type": "text"}], "details": {}, "isError": False}

        gateway = PrimeP3DevelopmentGateway(
            node_bin=node_bin, entrypoint=entrypoint, deadline_seconds=180,
            model_hook=model_hook, tool_hook=tool_hook,
        )
        session_id = "p3-" + run_id
        with TemporaryDirectory(prefix="asterion-prime-p3-") as workspace, TemporaryDirectory(prefix="asterion-prime-p3-rlm-") as socket_directory:
            server = await _open_rlm_server(Path(socket_directory), gateway)
            workers = await transport.create_workers(
                image_digest=image_digest, run_id=run_id, workspace=workspace,
                rlm_socket_directory=socket_directory, control=control,
            )
            if tuple(getattr(item, "role", item) for item in workers) != ("root", "implementation", "review"):
                raise ValueError
            await transport.start_workers(workers, control)
            # The bridge, rather than this host, owns child identity and recursion.
            # Root RPC is admitted only through its five closed bridge commands.
            await gateway.open(
                run_id=run_id, session_id=session_id, generation=1,
                prime_source_root=prime_source_root, workspace=workspace,
            )
            opened = True
            result = await gateway.prompt(P3_ROOT_PROMPT)
            observations = _observations(result)
            if calls != {"root": 4, "implementation": 2, "review": 4} or tools != {"root": 1, "implementation": 1, "review": 2}:
                raise ValueError
            usage = provider.terminal_usage()
            if not isinstance(usage, Mapping) or set(usage) != set(calls):
                raise ValueError
            source, tests, aggregate = await asyncio.gather(
                transport.read(workers[0], "solution.py", control),
                transport.read(workers[0], "test_solution.py", control),
                transport.read(workers[0], "aggregate.json", control),
            )
            validate_p3_source_bytes(source)
            validate_p3_test_bytes(tests)
            validate_p3_aggregate_bytes(aggregate)
            await gateway.close()
            opened = False
            server.close()
            await server.wait_closed()
            await transport.cleanup(workers, _LifecycleCallControl(monotonic() + 15.0, None))
            cleaned = True
        return PrimeP3DevelopmentTrace(
            "sha256:" + sha256(_canonical({
                "aggregate_sha256": sha256(P3_AGGREGATE_BYTES).hexdigest(),
                "observations": observations, "run_id": run_id,
                "session_id": session_id, "usage": usage,
                "workload": P3_DEVELOPMENT_WORKLOAD_DIGEST,
            })).hexdigest()
        )
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP3DevelopmentHostError() from None
    finally:
        if opened:
            try:
                await gateway.cancel()
                await gateway.close()
            except BaseException:
                pass
        if workers and not cleaned:
            try:
                await transport.cleanup(workers, _LifecycleCallControl(monotonic() + 15.0, None))
            except BaseException:
                pass


def _observations(result: object) -> dict[str, int]:
    if (
        type(result) is not dict
        or set(result) != {"lifecycle", "usage", "assistant", "observations"}
        or result["lifecycle"] != "completed"
    ):
        raise PrimeP3DevelopmentHostError()
    observed = result["observations"]
    expected = {
        "child_count": 2,
        "max_depth": 1,
        "model_callback_count": 10,
        "remaining_child_count": 0,
        "retained_follow_up_count": 1,
        "tool_call_count": 4,
    }
    if (
        type(observed) is not dict
        or observed != expected
        or result["assistant"] != {"completed": True, "stop_reason": "stop"}
    ):
        raise PrimeP3DevelopmentHostError()
    return expected


def _canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


async def _open_rlm_server(directory: Path, gateway: P3Gateway) -> asyncio.AbstractServer:
    """Expose exactly one root-only JSONL RLM request at a time."""
    child_ids: dict[str, str] = {}
    lock, step, poisoned = asyncio.Lock(), 0, False
    order = (("spawn", "implementation"), ("wait", "implementation"), ("spawn", "review"), ("wait", "review"), ("follow_up", None), ("delete", "implementation"), ("delete", "review"), ("list", None))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal step, poisoned
        try:
            async with lock:
                if poisoned:
                    raise ValueError
                raw = await reader.readuntil(b"\n")
            if not raw or len(raw) > 4096:
                raise ValueError
            request = json.loads(raw)
            if type(request) is not dict or type(request.get("kind")) is not str:
                raise ValueError
            kind = request["kind"]
            role_value = request.get("role")
            if step >= len(order) or (kind, role_value if kind not in {"follow_up", "list"} else None) != order[step]:
                poisoned = True
                raise ValueError
            if kind in {"spawn", "wait", "delete"}:
                if set(request) != {"kind", "role"} or request["role"] not in {"implementation", "review"}:
                    raise ValueError
                role = request["role"]
                if kind == "spawn":
                    result = await gateway.request_nested("rlm.spawn", {"role": role, "prompt": P3_IMPLEMENTATION_PROMPT if role == "implementation" else P3_REVIEW_PROMPT})
                    child_id = result.get("rlm_child_id")
                    if type(child_id) is not str or not child_id or role in child_ids:
                        raise ValueError
                    child_ids[role] = child_id
                else:
                    child_id = child_ids.get(role)
                    if child_id is None:
                        raise ValueError
                    result = await gateway.request_nested("rlm." + kind, {"child_id": child_id})
            elif kind == "follow_up":
                if set(request) != {"kind"} or "review" not in child_ids:
                    raise ValueError
                result = await gateway.request_nested("rlm.follow_up", {"child_id": child_ids["review"], "prompt": P3_FOLLOW_UP_PROMPT})
            elif kind == "list":
                if set(request) != {"kind"}:
                    raise ValueError
                result = await gateway.request_nested("rlm.list", {})
            else:
                raise ValueError
            if type(result) is not dict:
                raise ValueError
            step += 1
            safe = {"subagents": []} if kind == "list" else {"status": "completed"}
            writer.write(_canonical({"ok": True, "result": safe}) + b"\n")
            await writer.drain()
        except BaseException:
            poisoned = True
            writer.write(b'{"ok":false,"result":{}}\n')
            try:
                await writer.drain()
            except BaseException:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except BaseException:
                pass

    socket_path = directory / "rlm.sock"
    server = await asyncio.start_unix_server(handle, path=str(socket_path))
    os.chmod(socket_path, 0o600)
    if os.geteuid() == 0:
        os.chown(socket_path, 65534, 65534)
    return server


__all__ = (
    "P3ExecutionService",
    "P3Gateway",
    "PrimeP3DevelopmentHostError",
    "PrimeP3DevelopmentTrace",
    "run_prime_p3_development",
)
