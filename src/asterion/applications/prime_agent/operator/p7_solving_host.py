"""Private orchestration boundary for one real P7 solving lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import json
import re
from typing import Protocol, cast

from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
    validate_prime_arc_agi_3_solve_receipt,
)
from asterion.services.presentation import (
    NOOP_HOST_PRESENTATION_SINK,
    HostPresentationSink,
)
from asterion.services.progress import HostProgressEvent, HostProgressReporter

from .p7_solving_broker_service import P7SolvingBrokerServiceError
from .p7_solving_prompt import P7_SOLVING_PROMPT, validate_p7_solving_prompt
from .p7_solving_renderer import (
    create_p7_solving_presentation,
    render_p7_solving_presentation,
)


_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCORE = re.compile(r"(?:0|[1-9][0-9]?|100)\.[0-9]{6}\Z")
_MODEL_FAILURE_CATEGORIES = frozenset({
    "callback-limit", "input-limit", "output-limit", "cost-limit", "deadline",
    "dns", "connect", "tls", "timeout", "http-4xx", "http-5xx", "response",
    "internal",
})


class PrimeP7SolvingHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 solving host is unavailable")


class P7SolvingGateway(Protocol):
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


class P7SolvingProvider(Protocol):
    async def __call__(self, body: bytes) -> bytes: ...
    def finalize(self) -> object: ...
    def callback_counts(self) -> dict[str, int]: ...
    def failure_category(self) -> str: ...
    async def close(self) -> None: ...


class P7SolvingWorker(Protocol):
    async def acquire(self, client: bytes) -> None: ...
    async def execute_cell(self, code: str) -> dict[str, object]: ...
    async def cleanup(self) -> None: ...


class P7SolvingBroker(Protocol):
    def start(self) -> bytes: ...
    def seal(self) -> dict[str, object]: ...
    def replay(self) -> dict[str, object]: ...
    def presentation(self) -> dict[str, object]: ...
    def close(self) -> None: ...


class P7SolvingReceiptStore:
    """Retain exactly one immutable receipt under its run/digest identity."""

    __slots__ = ("_entry",)

    def __init__(self) -> None:
        self._entry: tuple[str, str, PrimeArcAgi3SolveReceipt] | None = None

    def publish(self, receipt: object) -> None:
        try:
            validate_prime_arc_agi_3_solve_receipt(receipt)
            if self._entry is not None:
                raise ValueError
            typed = cast(PrimeArcAgi3SolveReceipt, receipt)
            self._entry = (typed.run_id, typed.receipt_sha256, typed)
        except BaseException:
            raise PrimeP7SolvingHostError() from None

    def get_receipt(
        self, *, run_id: str, receipt_sha256: str
    ) -> PrimeArcAgi3SolveReceipt:
        try:
            if (
                type(run_id) is not str
                or _RUN_ID.fullmatch(run_id) is None
                or type(receipt_sha256) is not str
                or _DIGEST.fullmatch(receipt_sha256) is None
                or self._entry is None
                or self._entry[:2] != (run_id, receipt_sha256)
            ):
                raise ValueError
            receipt = self._entry[2]
            validate_prime_arc_agi_3_solve_receipt(receipt)
            self._entry = None
            return receipt
        except BaseException:
            raise PrimeP7SolvingHostError() from None

    def __repr__(self) -> str:
        return "P7SolvingReceiptStore(redacted)"


async def run_p7_solving_lifecycle(
    *,
    gateway: P7SolvingGateway,
    provider: P7SolvingProvider,
    worker: P7SolvingWorker,
    broker: P7SolvingBroker,
    receipt_store: P7SolvingReceiptStore,
    run_id: str,
    session_id: str,
    prime_source_root: str = "/workspace",
    workspace: str = "/workspace",
    progress: HostProgressReporter | None = None,
    presentation: HostPresentationSink = NOOP_HOST_PRESENTATION_SINK,
) -> PrimeArcAgi3SolveReceipt:
    """Run one prompt and publish a receipt only after replay and cleanup close."""

    _emit(progress, "preflight", "started")
    try:
        _validate_inputs(
            gateway, provider, worker, broker, receipt_store, run_id, session_id,
            prime_source_root, workspace, presentation,
        )
        validate_p7_solving_prompt(P7_SOLVING_PROMPT)
    except BaseException:
        _emit(progress, "preflight", "failed")
        raise PrimeP7SolvingHostError() from None
    _emit(progress, "preflight", "succeeded")

    broker_started = worker_acquired = gateway_opened = False
    primary: BaseException | None = None
    receipt_values: tuple[int, str] | None = None
    solved_latched = False
    model_calls = tool_calls = executed_cells = 0
    active_phase: str | None = None
    validation_started = False

    try:
        _emit(progress, "worker", "started")
        active_phase = "worker"
        client = broker.start()
        broker_started = True
        if type(client) is not bytes or not client:
            raise ValueError
        await worker.acquire(client)
        worker_acquired = True
        _emit(progress, "worker", "succeeded")
        active_phase = None

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            _emit(progress, "model", "started")
            try:
                if type(payload) is not dict:
                    raise ValueError
                reply = _strict_json(await provider(_canonical(payload)))
                model_calls += 1
                _emit(progress, "model", "succeeded")
                return reply
            except BaseException:
                _emit(progress, "model", "failed")
                try:
                    presentation.write(
                        f"Model callback failed: {_provider_failure_category(provider)}"
                    )
                except BaseException:
                    pass
                raise

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal executed_cells, solved_latched, tool_calls
            _emit(progress, "tool", "started")
            stage = "payload"
            try:
                if (
                    type(payload) is not dict
                    or set(payload) != {"tool_call_id", "code"}
                    or type(payload["tool_call_id"]) is not str
                    or not payload["tool_call_id"]
                    or type(payload["code"]) is not str
                    or not payload["code"]
                ):
                    raise ValueError
                tool_calls += 1
                if solved_latched:
                    _emit(progress, "tool", "succeeded")
                    return {
                        "content": [{"type": "text", "text": "Level already solved; no cell executed"}],
                        "details": {"broker_terminal": "LEVEL_SOLVED"},
                        "isError": False,
                    }
                stage = "worker-execution"
                result = await worker.execute_cell(payload["code"])
                executed_cells += 1
                stage = "worker-result"
                normalized = _worker_result(result, executed_cells)
                terminal = "ACTIVE"
                stage = "broker-seal"
                try:
                    current = _seal(broker.seal(), require_completed=False)
                except P7SolvingBrokerServiceError:
                    current = None
                if current is not None and current["terminal_reason"] == "level-completed":
                    solved_latched = True
                    terminal = "LEVEL_SOLVED"
                elif current is not None:
                    terminal = "TERMINAL"
                _emit(progress, "tool", "succeeded")
                return {
                    "content": [{"type": "text", "text": normalized["output"] or "IPython cell completed"}],
                    "details": {"broker_terminal": terminal},
                    "isError": normalized["is_error"],
                }
            except BaseException:
                _emit(progress, "tool", "failed")
                try:
                    presentation.write(f"Tool callback failed at stage: {stage}")
                except BaseException:
                    pass
                raise

        gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
        _emit(progress, "gateway", "started")
        active_phase = "gateway"
        await gateway.open(
            run_id=run_id,
            session_id=session_id,
            generation=1,
            prime_source_root=prime_source_root,
            workspace=workspace,
        )
        gateway_opened = True
        result = await gateway.prompt(P7_SOLVING_PROMPT)
        _completed(result, model_calls, tool_calls)
        if not solved_latched:
            raise ValueError
        _emit(progress, "gateway", "succeeded")
        active_phase = None

        _emit(progress, "validation", "started")
        active_phase = "validation"
        validation_started = True
        provider_usage = _usage(provider.finalize())
        witness = _witness(gateway.terminal_witness(), run_id, session_id)
        counts = provider.callback_counts()
        if (
            type(counts) is not dict
            or set(counts) != {"normal", "summary"}
            or any(type(counts[name]) is not int or counts[name] < 0 for name in counts)
            or counts["normal"] + counts["summary"] != model_calls
            or witness["normal"] != counts["normal"]
            or witness["summary"] != counts["summary"]
            or witness["tools"] != tool_calls
            or witness["input_tokens"] != provider_usage["input_tokens"]
            or witness["output_tokens"] != provider_usage["output_tokens"]
        ):
            raise ValueError
        seal = _seal(broker.seal(), require_completed=True)
        replay = _replay(broker.replay(), seal)
        del replay
        raw_presentation = broker.presentation()
        if (
            raw_presentation.get("action_count") != seal["action_count"]
            or raw_presentation.get("levels_completed") != 1
            or raw_presentation.get("score") != seal["score"]
            or raw_presentation.get("terminal_reason") != "level-completed"
        ):
            raise ValueError
        local = create_p7_solving_presentation(
            raw_presentation,
            model_callback_count=model_calls,
            tool_callback_count=executed_cells,
        )
        render_p7_solving_presentation(local, presentation)
        receipt_values = cast(int, seal["action_count"]), cast(str, seal["score"])
    except BaseException as error:
        if active_phase is not None:
            _emit(progress, active_phase, "failed")
            active_phase = None
        primary = error if isinstance(error, (asyncio.CancelledError, PrimeP7SolvingHostError)) else PrimeP7SolvingHostError()

    cleanup_errors = await _cleanup(
        gateway=gateway,
        provider=provider,
        worker=worker,
        broker=broker,
        gateway_opened=gateway_opened,
        worker_acquired=worker_acquired,
        broker_started=broker_started,
        progress=progress,
    )
    if primary is not None:
        raise primary
    if cleanup_errors or receipt_values is None:
        raise PrimeP7SolvingHostError()
    try:
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id=run_id,
            completed_level_count=1,
            primitive_action_count=receipt_values[0],
            partial_game_score=receipt_values[1],
        )
        validate_prime_arc_agi_3_solve_receipt(receipt)
        receipt_store.publish(receipt)
        _emit(progress, "validation", "succeeded")
        return receipt
    except BaseException:
        if validation_started:
            _emit(progress, "validation", "failed")
        raise PrimeP7SolvingHostError() from None


def _validate_inputs(
    gateway: object,
    provider: object,
    worker: object,
    broker: object,
    receipt_store: object,
    run_id: object,
    session_id: object,
    prime_source_root: object,
    workspace: object,
    presentation: object,
) -> None:
    methods = (
        (gateway, ("bind", "open", "prompt", "terminal_witness", "close")),
        (provider, ("__call__", "finalize", "callback_counts", "close")),
        (worker, ("acquire", "execute_cell", "cleanup")),
        (broker, ("start", "seal", "replay", "presentation", "close")),
    )
    if (
        any(not all(callable(getattr(value, name, None)) for name in names) for value, names in methods)
        or type(receipt_store) is not P7SolvingReceiptStore
        or type(run_id) is not str
        or _RUN_ID.fullmatch(run_id) is None
        or type(session_id) is not str
        or _RUN_ID.fullmatch(session_id) is None
        or any(type(path) is not str or not path.startswith("/") or path.startswith("//") or "\x00" in path for path in (prime_source_root, workspace))
        or not callable(getattr(presentation, "write", None))
    ):
        raise ValueError


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _strict_json(value: object) -> dict[str, object]:
    if type(value) is not bytes or not value:
        raise ValueError
    parsed = json.loads(value.decode("utf-8", "strict"))
    if type(parsed) is not dict or _canonical(parsed) != value:
        raise ValueError
    return parsed


def _provider_failure_category(provider: object) -> str:
    try:
        method = getattr(provider, "failure_category", None)
        if not callable(method):
            return "internal"
        category = method()
    except BaseException:
        return "internal"
    return category if type(category) is str and category in _MODEL_FAILURE_CATEGORIES else "internal"


def _worker_result(value: object, cell_count: int) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"cell_count", "output", "is_error"}
        or value["cell_count"] != cell_count
        or type(value["cell_count"]) is not int
        or type(value["output"]) is not str
        or len(value["output"].encode("utf-8")) > 4096
        or type(value["is_error"]) is not bool
    ):
        raise ValueError
    return value


def _completed(value: object, model_calls: int, tool_calls: int) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "lifecycle", "normal_model_callback_count",
        "summary_model_callback_count", "tool_callback_count",
    }:
        raise ValueError
    normalized = dict(value)
    if (
        normalized["lifecycle"] != "completed"
        or any(type(normalized[name]) is not int or normalized[name] < 0 for name in normalized if name != "lifecycle")
        or normalized["normal_model_callback_count"] + normalized["summary_model_callback_count"] != model_calls
        or normalized["tool_callback_count"] != tool_calls
    ):
        raise ValueError


def _usage(value: object) -> dict[str, int]:
    names = ("input_tokens", "output_tokens", "cost_microunits")
    if any(type(getattr(value, name, None)) is not int or getattr(value, name) < 0 for name in names):
        raise ValueError
    return {name: getattr(value, name) for name in names}


def _witness(value: object, run_id: str, session_id: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"identity", "result", "cumulative"}:
        raise ValueError
    identity, result, cumulative = value["identity"], value["result"], value["cumulative"]
    if not isinstance(identity, Mapping) or dict(identity) != {
        "run_id": run_id, "session_id": session_id,
        "runtime_id": "prime.agent", "generation": 1,
    }:
        raise ValueError
    if not isinstance(result, Mapping) or set(result) != {"lifecycle", "usage", "assistant", "observations"} or result["lifecycle"] != "completed":
        raise ValueError
    usage, assistant, observations = result["usage"], result["assistant"], result["observations"]
    observation_fields = {
        "active_tool_names", "compact_count", "normal_model_callback_count",
        "summary_model_callback_count", "rlm_child_count", "tool_call_count",
        "solved_latched",
    }
    if (
        not isinstance(usage, Mapping)
        or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}
        or any(type(usage[name]) is not int or usage[name] < 0 for name in usage)
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
        or not isinstance(assistant, Mapping)
        or set(assistant) != {"completed", "stop_reason"}
        or assistant["completed"] is not True
        or assistant["stop_reason"] not in {"stop", "toolUse"}
        or not isinstance(observations, Mapping)
        or set(observations) != observation_fields
        or observations["active_tool_names"] != ["ipython"]
        or observations["solved_latched"] is not True
        or any(type(observations[name]) is not int or not 0 <= observations[name] <= 128 for name in observation_fields - {"active_tool_names", "solved_latched"})
        or not isinstance(cumulative, Mapping)
        or dict(cumulative) != {
            "normal_model_callback_count": observations["normal_model_callback_count"],
            "summary_model_callback_count": observations["summary_model_callback_count"],
            "tool_callback_count": observations["tool_call_count"],
        }
    ):
        raise ValueError
    return {
        "normal": cast(int, observations["normal_model_callback_count"]),
        "summary": cast(int, observations["summary_model_callback_count"]),
        "tools": cast(int, observations["tool_call_count"]),
        "input_tokens": cast(int, usage["input_tokens"]),
        "output_tokens": cast(int, usage["output_tokens"]),
    }


def _seal(value: object, *, require_completed: bool) -> dict[str, object]:
    fields = {
        "action_count", "levels_completed", "score", "score_sha256",
        "terminal_reason", "transcript_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value["action_count"]) is not int
        or not 1 <= value["action_count"] <= 500
        or type(value["levels_completed"]) is not int
        or value["levels_completed"] not in (0, 1)
        or type(value["score"]) is not str
        or _SCORE.fullmatch(value["score"]) is None
        or any(type(value[name]) is not str or _DIGEST.fullmatch(value[name]) is None for name in ("score_sha256", "transcript_sha256"))
        or value["terminal_reason"] not in {"action-cap", "engine-invalid", "level-completed"}
        or (value["terminal_reason"] == "level-completed") != (value["levels_completed"] == 1)
        or require_completed and value["terminal_reason"] != "level-completed"
    ):
        raise ValueError
    return value


def _replay(value: object, seal: dict[str, object]) -> dict[str, object]:
    fields = {
        "action_count", "levels_completed", "score", "score_sha256",
        "terminal_reason", "replay_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or any(value[name] != seal[name] for name in fields - {"replay_sha256"})
        or value["replay_sha256"] != seal["transcript_sha256"]
    ):
        raise ValueError
    return value


async def _cleanup(
    *, gateway: P7SolvingGateway, provider: P7SolvingProvider,
    worker: P7SolvingWorker, broker: P7SolvingBroker,
    gateway_opened: bool, worker_acquired: bool, broker_started: bool,
    progress: HostProgressReporter | None,
) -> tuple[BaseException, ...]:
    _emit(progress, "cleanup", "started")
    errors: list[BaseException] = []
    if gateway_opened:
        await _collect_cleanup(gateway.close, errors)
    await _collect_cleanup(provider.close, errors)
    if worker_acquired:
        await _collect_cleanup(worker.cleanup, errors)
    if broker_started:
        try:
            broker.close()
        except BaseException as error:
            errors.append(error)
    _emit(progress, "cleanup", "failed" if errors else "succeeded")
    return tuple(errors)


async def _collect_cleanup(
    operation: Callable[[], Awaitable[None]], errors: list[BaseException]
) -> None:
    try:
        task = asyncio.ensure_future(operation())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            errors.append(asyncio.CancelledError())
    except BaseException as error:
        errors.append(error)


def _emit(
    reporter: HostProgressReporter | None, component: str, state: str
) -> None:
    if reporter is None:
        return
    try:
        reporter.emit(HostProgressEvent(component, state))
    except BaseException:
        pass


__all__ = (
    "P7SolvingReceiptStore",
    "PrimeP7SolvingHostError",
    "run_p7_solving_lifecycle",
)
