"""Trusted finite lifecycle for the fixed, unpromoted P7 episode."""
# ruff: noqa: E701, E702

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
import json
import re
from typing import Protocol

from .p7_development_receipt import (
    P7DevelopmentReceipt,
    p7_development_public_trace_digest,
    validate_p7_development_receipt,
)
from .p7_development_workload import (
    P7_DEVELOPMENT_MODEL_DIGEST,
    P7_DEVELOPMENT_ORACLE_DIGEST,
    P7_DEVELOPMENT_RESOURCE_DIGEST,
    P7_DEVELOPMENT_SCHEMA_DIGEST,
    P7_DEVELOPMENT_WORKLOAD_DIGEST,
)
from .p7_runtime_lock import P7DevelopmentRuntimeSet
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PrimeP7DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 development host is unavailable")


class P7DevelopmentGateway(Protocol):
    def bind(
        self,
        *,
        model_hook: Callable[[object], Awaitable[dict[str, object]]],
        tool_hook: Callable[[object], Awaitable[dict[str, object]]],
    ) -> None: ...
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    def terminal_witness(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
    async def cancel(self) -> object: ...


class P7DevelopmentProvider(Protocol):
    async def __call__(self, body: bytes) -> bytes: ...
    def terminal_usage(self) -> object: ...
    async def close(self) -> None: ...


class P7DevelopmentWorker(Protocol):
    async def acquire(self, client: bytes, broker_mount: str = "/broker") -> None: ...
    async def snapshot(self) -> object: ...
    async def execute_cell(self, cell: str) -> Mapping[str, object]: ...
    async def cleanup(self) -> None: ...


class P7DevelopmentBroker(Protocol):
    def start(self, *, client_socket_path: str = "/broker/model.sock") -> bytes: ...
    def seal(self) -> Mapping[str, object]: ...
    def replay(self) -> Mapping[str, object]: ...
    def close(self) -> None: ...


class PrimeP7DevelopmentTrace:
    __slots__ = ("_digest",)

    def __init__(self, digest: str) -> None:
        if _DIGEST.fullmatch(digest) is None:
            raise PrimeP7DevelopmentHostError()
        self._digest = digest

    @property
    def trace_sha256(self) -> str:
        return self._digest

    def __repr__(self) -> str:
        return "PrimeP7DevelopmentTrace(redacted)"


async def run_p7_development_lifecycle(
    *,
    gateway: P7DevelopmentGateway,
    provider: P7DevelopmentProvider,
    worker: P7DevelopmentWorker,
    broker: P7DevelopmentBroker,
    run_id: str,
    session_id: str,
    prime_source_root: str,
    workspace: str = "/workspace",
    runtime: P7DevelopmentRuntimeSet,
) -> PrimeP7DevelopmentTrace:
    if not _inputs(
        gateway,
        provider,
        worker,
        broker,
        run_id,
        session_id,
        prime_source_root,
        workspace,
        runtime,
    ):
        raise PrimeP7DevelopmentHostError()
    opened = provider_closed = worker_cleaned = broker_closed = False
    cancelled = False
    try:
        client = broker.start(client_socket_path="/broker/model.sock")
        if type(client) is not bytes or not client:
            raise ValueError
        await worker.acquire(client, "/broker")
        _worker_identity(worker)
        calls = tools = 0

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal calls
            if type(payload) is not dict or calls >= 6:
                raise ValueError
            body = _canonical(payload)
            calls += 1
            return _reply(await provider(body))

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal tools
            if (
                type(payload) is not dict
                or set(payload) != {"tool_call_id", "code"}
                or type(payload["tool_call_id"]) is not str
                or not payload["tool_call_id"]
                or type(payload["code"]) is not str
                or not payload["code"]
                or tools >= 3
            ):
                raise ValueError
            tools += 1
            result = await worker.execute_cell(payload["code"])
            if result != {"cell_count": tools}:
                raise ValueError
            return {
                "content": [{"type": "text", "text": "IPython cell completed"}],
                "details": {},
                "isError": False,
            }

        gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
        opened = True
        await gateway.open(
            run_id=run_id,
            session_id=session_id,
            generation=1,
            prime_source_root=prime_source_root,
            workspace=workspace,
        )
        _completed(await gateway.prompt(_prompt(1, run_id, session_id)), 2, 1)
        initial = _stage(await worker.snapshot(), "initial.json")
        _initial(initial)
        _completed(await gateway.prompt(_prompt(2, run_id, session_id)), 4, 2)
        actions = _stage(await worker.snapshot(), "actions.json")
        action_rows = _actions(actions)
        _completed(await gateway.prompt(_prompt(3, run_id, session_id)), 6, 3)
        status = _stage(await worker.snapshot(), "status.json")
        terminal = _status(status)
        if calls != 6 or tools != 3:
            raise ValueError
        usage = _usage(provider.terminal_usage())
        _witness(gateway.terminal_witness(), run_id, session_id, usage)
        seal, replay = broker.seal(), broker.replay()
        _broker(seal, replay, initial, actions, status)
        await gateway.close()
        opened = False
        await provider.close()
        provider_closed = True
        await worker.cleanup()
        worker_cleaned = True
        broker.close()
        broker_closed = True
        receipt = _receipt(
            run_id,
            session_id,
            worker,
            initial,
            actions,
            status,
            seal,
            replay,
            usage,
            len(action_rows),
            terminal,
            runtime,
        )
        validate_p7_development_receipt(receipt)
        return PrimeP7DevelopmentTrace(p7_development_public_trace_digest(receipt))
    except asyncio.CancelledError:
        cancelled = True
    except BaseException:
        pass
    finally:
        if not (worker_cleaned and broker_closed):
            await _cleanup(
                gateway,
                provider,
                worker,
                broker,
                opened,
                provider_closed,
                worker_cleaned,
                broker_closed,
            )
    if cancelled:
        raise asyncio.CancelledError()
    raise PrimeP7DevelopmentHostError()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _prompt(stage: int, run_id: str, session_id: str) -> str:
    canonical = "Serialize with json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8') and Path(path).write_bytes(...)."
    instructions = {
        1: "In one IPython cell import json, Path from pathlib, and p7_client; call result = p7_client.observe(); set value = {\"observation\": result[\"observation\"]}; write only canonical JSON bytes to /workspace/initial.json. " + canonical,
        2: "In one IPython cell import json, Path from pathlib, and p7_client; call p7_client.act(1) exactly four times; set value to a list of four {\"action_id\": 1, \"observation\": result[\"observation\"]} rows in call order; write only canonical JSON bytes to /workspace/actions.json. " + canonical,
        3: "In one IPython cell import json, Path from pathlib, and p7_client; set value = p7_client.status(); write only canonical JSON bytes to /workspace/status.json. " + canonical,
    }
    try:
        return instructions[stage] + " Episode identity: " + _canonical({"run_id": run_id, "session_id": session_id}).decode("ascii")
    except KeyError:
        raise ValueError from None


def _inputs(*values: object) -> bool:
    if len(values) != 9:
        return False
    gateway, provider, worker, broker, run_id, session_id, prime_source_root, workspace, runtime = values
    return (
        all(value is not None for value in (gateway, provider, worker, broker))
        and all(type(value) is str and value for value in (run_id, session_id))
        and all(type(value) is str and value.startswith("/") for value in (prime_source_root, workspace))
        and type(runtime) is P7DevelopmentRuntimeSet
        and _DIGEST.fullmatch(runtime.runtime_sha256) is not None
    )


def _reply(raw: object) -> dict[str, object]:
    if type(raw) is not bytes:
        raise ValueError
    value = json.loads(raw.decode("utf-8", "strict"))
    if type(value) is not dict:
        raise ValueError
    return value


def _completed(value: object, callbacks: int, tools: int) -> None:
    if value != {
        "lifecycle": "completed",
        "model_callback_count": callbacks,
        "tool_callback_count": tools,
    }:
        raise ValueError


def _stage(value: object, name: str) -> bytes:
    if type(value) is not dict or any(
        type(k) is not str or type(v) is not bytes for k, v in value.items()
    ):
        raise ValueError
    matches = [v for k, v in value.items() if k == name or k == "/workspace/" + name]
    if len(matches) != 1:
        raise ValueError
    return matches[0]


def _json(raw: bytes) -> object:
    value = json.loads(raw.decode("utf-8", "strict"))
    if _canonical(value) != raw:
        raise ValueError
    return value


def _initial(raw: bytes) -> None:
    value = _json(raw)
    if type(value) is not dict or set(value) != {"observation"}:
        raise ValueError


def _actions(raw: bytes) -> list[object]:
    value = _json(raw)
    if (
        type(value) is not list
        or len(value) != 4
        or any(
            type(row) is not dict
            or set(row) != {"action_id", "observation"}
            or row["action_id"] != 1
            for row in value
        )
    ):
        raise ValueError
    return value


def _status(raw: bytes) -> dict[str, object]:
    value = _json(raw)
    if (
        type(value) is not dict
        or set(value) != {"terminal", "terminal_reason"}
        or type(value["terminal"]) is not bool
        or value["terminal_reason"] not in {"action-limit", "engine-terminal"}
        or value["terminal"] != (value["terminal_reason"] == "engine-terminal")
    ):
        raise ValueError
    return value


def _usage(value: object) -> dict[str, int]:
    fields = ("input_tokens", "output_tokens", "cost_microunits")
    if any(type(getattr(value, key, None)) is not int or getattr(value, key) < 0 for key in fields):
        raise ValueError
    return {key: getattr(value, key) for key in fields}


def _witness(value: object, run_id: str, session_id: str, provider_usage: Mapping[str, int]) -> None:
    if not isinstance(value, Mapping) or set(value) != {"identity", "result", "cumulative"}:
        raise ValueError
    identity, result, cumulative = value["identity"], value["result"], value["cumulative"]
    if (
        not isinstance(identity, Mapping)
        or dict(identity) != {"run_id": run_id, "session_id": session_id, "runtime_id": "prime.agent", "generation": 1}
        or type(identity["generation"]) is not int
        or not isinstance(cumulative, Mapping)
        or dict(cumulative) != {"model_callback_count": 6, "tool_callback_count": 3}
        or any(type(cumulative[key]) is not int for key in cumulative)
        or not isinstance(result, Mapping)
        or set(result) != {"lifecycle", "usage", "assistant", "observations"}
        or result["lifecycle"] != "completed"
    ):
        raise ValueError
    usage, assistant, observations = result["usage"], result["assistant"], result["observations"]
    if (
        not isinstance(usage, Mapping)
        or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}
        or any(type(usage[key]) is not int or usage[key] < 0 for key in usage)
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
        or usage["input_tokens"] != provider_usage["input_tokens"]
        or usage["output_tokens"] != provider_usage["output_tokens"]
        or not isinstance(assistant, Mapping)
        or dict(assistant) != {"completed": True, "stop_reason": "stop"}
        or type(assistant["completed"]) is not bool
        or not isinstance(observations, Mapping)
        or dict(observations) != {"active_tool_names": ["ipython"], "compact_count": 0, "model_callback_count": 6, "rlm_child_count": 0, "tool_call_count": 3}
        or any(type(observations[key]) is not int for key in ("compact_count", "model_callback_count", "rlm_child_count", "tool_call_count"))
    ):
        raise ValueError


def _broker(seal: object, replay: object, initial: bytes, actions: bytes, status: bytes) -> None:
    if (
        type(seal) is not dict
        or type(replay) is not dict
        or set(seal) != {"transcript_sha256", "score_sha256", "initial_sha256", "actions_sha256", "status_sha256", "terminal_reason", "action_count"}
        or set(replay) != {"replay_sha256", "score_sha256", "initial_sha256", "actions_sha256", "status_sha256", "terminal_reason", "action_count"}
        or seal["transcript_sha256"] != replay["replay_sha256"]
        or seal["score_sha256"] != replay["score_sha256"]
        or any(seal[key] != replay[key] for key in ("initial_sha256", "actions_sha256", "status_sha256"))
        or (seal["initial_sha256"], seal["actions_sha256"], seal["status_sha256"]) != (_bytes_digest(initial), _bytes_digest(actions), _bytes_digest(status))
        or seal["terminal_reason"] != replay["terminal_reason"]
        or seal["action_count"] != replay["action_count"]
        or seal["action_count"] != len(_actions(actions))
        or seal["terminal_reason"] != _status(status)["terminal_reason"]
        or type(seal["transcript_sha256"]) is not str
        or _DIGEST.fullmatch(seal["transcript_sha256"]) is None
        or type(seal["score_sha256"]) is not str
        or _DIGEST.fullmatch(seal["score_sha256"]) is None
        or any(type(seal[key]) is not str or _DIGEST.fullmatch(seal[key]) is None for key in ("initial_sha256", "actions_sha256", "status_sha256"))
    ):
        raise ValueError


def _worker_identity(worker: object) -> None:
    if _DIGEST.fullmatch(getattr(worker, "image_digest", "")) is None:
        raise ValueError
    daemon = getattr(worker, "daemon_id", "")
    if type(daemon) is not str or re.fullmatch(r"[0-9a-f]{64}", daemon) is None:
        raise ValueError


def _receipt(
    run_id: str,
    session_id: str,
    worker: object,
    initial: bytes,
    actions: bytes,
    status: bytes,
    seal: Mapping[str, object],
    replay: Mapping[str, object],
    usage: dict[str, int],
    action_count: int,
    terminal: Mapping[str, object],
    runtime: P7DevelopmentRuntimeSet,
) -> P7DevelopmentReceipt:
    if type(runtime) is not P7DevelopmentRuntimeSet or _DIGEST.fullmatch(runtime.runtime_sha256) is None:
        raise ValueError
    transcript = seal["transcript_sha256"]
    assert type(transcript) is str
    return P7DevelopmentReceipt(
        P7_DEVELOPMENT_WORKLOAD_DIGEST,
        P7_DEVELOPMENT_SCHEMA_DIGEST,
        P7_DEVELOPMENT_MODEL_DIGEST,
        P7_DEVELOPMENT_ORACLE_DIGEST,
        P7_DEVELOPMENT_RESOURCE_DIGEST,
        runtime.runtime_sha256,
        _digest({"run": run_id}),
        _digest({"session": session_id}),
        _digest({"container": worker.daemon_id}),
        getattr(worker, "image_digest"),
        _bytes_digest(initial),
        _bytes_digest(actions),
        _bytes_digest(status),
        seal["score_sha256"],
        replay["replay_sha256"],
        _digest(usage),
        transcript,
        _digest({"broker_quiescent": True, "worker_destroyed": True}),
        ("ipython",),
        1,
        action_count,
        action_count + 2,
        1,
        1,
        3,
        6,
        3,
        terminal["terminal_reason"],
        True,
        True,
        True,
        True,
        True,
    )


async def _cleanup(
    gateway: object,
    provider: object,
    worker: object,
    broker: object,
    opened: bool,
    provider_closed: bool,
    worker_cleaned: bool,
    broker_closed: bool,
) -> None:
    if opened:
        try:
            await gateway.close()
        except BaseException:
            pass
    if not provider_closed:
        try:
            await provider.close()
        except BaseException:
            pass
    if not worker_cleaned:
        try:
            await worker.cleanup()
        except BaseException:
            pass
    if not broker_closed:
        try:
            broker.close()
        except BaseException:
            pass


__all__ = (
    "P7DevelopmentBroker",
    "P7DevelopmentGateway",
    "P7DevelopmentProvider",
    "P7DevelopmentWorker",
    "PrimeP7DevelopmentHostError",
    "PrimeP7DevelopmentTrace",
    "run_p7_development_lifecycle",
)
