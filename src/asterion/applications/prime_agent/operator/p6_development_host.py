"""Provider-free trusted gate for the fixed P6 development refinement."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
import json
import re
from typing import Protocol

from asterion.applications.prime_agent.continual_improvement_acceptance import (
    continual_improvement_revision_sha256,
    continual_improvement_scope_sha256,
    continual_improvement_snapshot_sha256,
)
from asterion.control.harness import (
    HarnessCoordinator,
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessScope,
    harness_effect_digest,
)
from asterion.control.journal import JournalRecord, MemoryCanonicalJournal

from .p6_development_receipt import (
    P6DevelopmentReceipt,
    validate_p6_development_receipt,
)
from .p6_development_workload import (
    P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
    P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
    P6_DEVELOPMENT_MODEL_DIGEST,
    P6_DEVELOPMENT_ORACLE_DIGEST,
    P6_DEVELOPMENT_SCHEMA_DIGEST,
    P6_DEVELOPMENT_TASK_A_RESULT_SHA256,
    P6_DEVELOPMENT_WORKLOAD_DIGEST,
    p6_development_branch_facts,
)


_BASELINE_SOURCE = b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
_CANDIDATE_SOURCE = (
    b"def clamp(value, lower, upper):\n"
    b"    return min(max(value, lower), upper)\n"
)
_TASK_A_BYTES = b'{"passed":false}'
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PrimeP6DevelopmentHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 development host is unavailable")


class P6DevelopmentGateway(Protocol):
    def bind(self, *, model_hook: Callable[[object], Awaitable[dict[str, object]]], tool_hook: Callable[[object], Awaitable[dict[str, object]]]) -> None: ...
    async def open(self, **kwargs: object) -> None: ...
    async def prompt(self, prompt: str) -> Mapping[str, object]: ...
    def terminal_witness(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
    async def cancel(self) -> object: ...


class P6DevelopmentProvider(Protocol):
    async def __call__(self, body: bytes) -> bytes: ...
    def terminal_usage(self) -> object: ...
    async def close(self) -> None: ...


class P6DevelopmentWorker(Protocol):
    async def acquire(self) -> None: ...
    async def snapshot(self) -> object: ...
    async def execute_cell(self, cell: str) -> Mapping[str, object]: ...
    async def cleanup(self) -> None: ...


async def run_p6_development_lifecycle(
    *, gateway: P6DevelopmentGateway, provider: P6DevelopmentProvider,
    worker: P6DevelopmentWorker, run_id: str, session_id: str,
) -> P6DevelopmentReceipt:
    if not _inputs(gateway, provider, worker, run_id, session_id):
        raise PrimeP6DevelopmentHostError()
    opened = provider_closed = cleaned = False
    cancelled = False
    try:
        await worker.acquire()
        image_sha256 = _worker_digest(worker, "image_digest")
        container_sha256 = "sha256:" + _worker_daemon(worker)
        _initial_snapshot(await worker.snapshot())
        model_calls = tool_calls = 0

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            if type(payload) is not dict or model_calls >= 6:
                raise ValueError
            await provider(_canonical(payload))
            model_calls += 1
            return {}

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal tool_calls
            if (
                type(payload) is not dict or set(payload) != {"tool_call_id", "code"}
                or type(payload["tool_call_id"]) is not str or not payload["tool_call_id"]
                or type(payload["code"]) is not str or not payload["code"] or tool_calls >= 3
            ):
                raise ValueError
            tool_calls += 1
            result = await worker.execute_cell(payload["code"])
            if type(result) is not dict or result != {"cell_count": tool_calls}:
                raise ValueError
            return {"content": [{"type": "text", "text": "IPython cell completed"}], "details": {}, "isError": False}

        gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
        await gateway.open(run_id=run_id, session_id=session_id, generation=1)
        opened = True
        _completed(await gateway.prompt(_prompt(1)), 2, 1)
        _initial_snapshot(await worker.snapshot())
        _completed(await gateway.prompt(_prompt(2)), 4, 2)
        _candidate_snapshot(await worker.snapshot(), require_task_b=False)
        coordinator, baseline, proposal, candidate = _coordinator()
        candidate_revision = coordinator.apply(proposal)
        candidate_harness = coordinator.snapshot()
        _completed(await gateway.prompt(_prompt(3)), 6, 3)
        holdout_passed = _candidate_snapshot(await worker.snapshot(), require_task_b=True)
        if (model_calls, tool_calls) != (6, 3):
            raise ValueError
        _terminal_witness(gateway.terminal_witness(), run_id, session_id)
        outcome = "preserved" if holdout_passed else "rolled-back"
        branch = p6_development_branch_facts(outcome)
        rollback = None
        if not holdout_passed:
            rollback = coordinator.rollback(
                proposal_id="p6-rollback", authority_id="p6-host", authority_revision=1,
                target_revision_id=candidate_revision.revision_id,
                rationale_ref="p6-rollback", rationale_digest=branch["outcome_sha256"].removeprefix("sha256:"),
                expected_outcome_digest=branch["outcome_sha256"].removeprefix("sha256:"),
            )
        final_harness = coordinator.snapshot()
        await gateway.close()
        opened = False
        await provider.close()
        provider_closed = True
        usage_sha256 = _digest(_usage(provider.terminal_usage()))
        await worker.cleanup()
        cleaned = True
        receipt = P6DevelopmentReceipt(
            P6_DEVELOPMENT_WORKLOAD_DIGEST, P6_DEVELOPMENT_SCHEMA_DIGEST,
            P6_DEVELOPMENT_MODEL_DIGEST, P6_DEVELOPMENT_ORACLE_DIGEST,
            P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256, P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
            P6_DEVELOPMENT_TASK_A_RESULT_SHA256, branch["holdout_result_sha256"],
            branch["final_source_sha256"], branch["outcome_sha256"],
            _digest({"run": run_id}), _digest({"session": session_id}), container_sha256,
            image_sha256, usage_sha256, continual_improvement_scope_sha256(baseline.scope),
            continual_improvement_snapshot_sha256(baseline),
            continual_improvement_snapshot_sha256(candidate_harness),
            continual_improvement_snapshot_sha256(final_harness),
            "sha256:" + proposal.digest, continual_improvement_revision_sha256(candidate_revision),
            None if rollback is None else continual_improvement_revision_sha256(rollback),
            "project", ("ipython",), 3, 6, 3, 1, 1, branch["rollback_count"], outcome,
            True, True,
        )
        validate_p6_development_receipt(receipt)
        return receipt
    except asyncio.CancelledError:
        cancelled = True
    except BaseException:
        pass
    finally:
        if not cleaned:
            await _cleanup(gateway, provider, worker, opened, provider_closed)
    if cancelled:
        raise asyncio.CancelledError
    raise PrimeP6DevelopmentHostError()


def _coordinator() -> tuple[HarnessCoordinator, object, HarnessProposal, object]:
    scope = HarnessScope.project("p6-development")
    journal = MemoryCanonicalJournal("p6-development")
    first = journal.append(0, JournalRecord.system_bound(system_id="p6-development", system_version="1.0.0"))
    journal.append(first.position, JournalRecord.authority_bound(authority_id="p6-host", authority_revision=1))

    def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
        return HarnessEffectReceipt.succeeded(proposal, effect_digest=harness_effect_digest(proposal), result_entries=tuple(edit.replacement for edit in proposal.edits if edit.replacement is not None))

    coordinator = HarnessCoordinator(journal, scope, send)
    baseline = coordinator.snapshot()
    entry = HarnessEntryDescriptor("p6-candidate", "memory", _bare(P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256), "p6-candidate-body", _bare(P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256), None, _bare(P6_DEVELOPMENT_TASK_A_RESULT_SHA256), 1)
    proposal = HarnessProposal("p6-candidate", "p6-host", 1, scope, baseline.snapshot_id, (HarnessEdit.create(entry),), ("p6-task-a",), "p6-task-a", _bare(P6_DEVELOPMENT_TASK_A_RESULT_SHA256), _bare(P6_DEVELOPMENT_TASK_A_RESULT_SHA256))
    return coordinator, baseline, proposal, coordinator.snapshot()


def _initial_snapshot(value: object) -> None:
    if value != {"baseline.py": _BASELINE_SOURCE, "task-a.json": _TASK_A_BYTES} or _clamp_passes(_BASELINE_SOURCE):
        raise ValueError


def _candidate_snapshot(value: object, *, require_task_b: bool) -> bool:
    if type(value) is not dict or set(value) != {"candidate.py", "task-b.json"} or value.get("candidate.py") != _CANDIDATE_SOURCE or not _clamp_passes(_CANDIDATE_SOURCE):
        raise ValueError
    task_b = value["task-b.json"]
    if type(task_b) is not bytes:
        raise ValueError
    try:
        parsed = json.loads(task_b.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    if type(parsed) is not dict or set(parsed) != {"passed"} or type(parsed["passed"]) is not bool or _canonical(parsed) != task_b:
        raise ValueError
    return parsed["passed"] if require_task_b else True


def _clamp_passes(source: bytes) -> bool:
    if source != _CANDIDATE_SOURCE:
        return False
    try:
        tree = ast.parse(source.decode(), mode="exec")
        expr = tree.body[0].body[0].value
    except (AttributeError, SyntaxError, UnicodeError):
        return False
    if not (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "min" and not expr.keywords and len(expr.args) == 2):
        return False
    inner, upper = expr.args
    if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "max" and not inner.keywords and len(inner.args) == 2 and all(isinstance(item, ast.Name) for item in (*inner.args, upper))):
        return False
    if tuple(item.id for item in (*inner.args, upper)) != ("value", "lower", "upper"):
        return False

    def evaluate(node: ast.AST, values: Mapping[str, int]) -> int:
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            arguments = [evaluate(item, values) for item in node.args]
            return min(arguments) if node.func.id == "min" else max(arguments)
        raise ValueError

    try:
        return all(
            evaluate(expr, {"value": value, "lower": lower, "upper": upper})
            == min(max(value, lower), upper)
            for value, lower, upper in ((-4, -2, 3), (1, -2, 3), (4, -2, 3))
        )
    except (KeyError, ValueError):
        return False


def _completed(value: object, models: int, tools: int) -> None:
    if type(value) is not dict or value != {"lifecycle": "completed", "model_callback_count": models, "tool_callback_count": tools}:
        raise ValueError


def _terminal_witness(value: object, run_id: str, session_id: str) -> None:
    if not isinstance(value, Mapping) or value != {"identity": {"run_id": run_id, "session_id": session_id, "runtime_id": "prime.agent", "generation": 1}, "cumulative": {"model_callback_count": 6, "tool_callback_count": 3}}:
        raise ValueError


def _worker_daemon(worker: object) -> str:
    value = getattr(worker, "daemon_id", None)
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError
    return value


def _worker_digest(worker: object, name: str) -> str:
    value = getattr(worker, name, None)
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError
    return value


def _usage(value: object) -> dict[str, int]:
    fields = ("input_tokens", "output_tokens", "cost_microunits")
    if any(type(getattr(value, field, None)) is not int or getattr(value, field) < 0 for field in fields):
        raise ValueError
    return {field: getattr(value, field) for field in fields}


def _prompt(stage: int) -> str:
    return f"P6 stage {stage}: make exactly one completion-only ipython call."


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _bare(value: str) -> str:
    return value.removeprefix("sha256:")


def _inputs(gateway: object, provider: object, worker: object, run_id: object, session_id: object) -> bool:
    return all(type(value) is str and value for value in (run_id, session_id)) and all(callable(getattr(gateway, name, None)) for name in ("bind", "open", "prompt", "terminal_witness", "close", "cancel")) and all(callable(getattr(provider, name, None)) for name in ("__call__", "terminal_usage", "close")) and all(callable(getattr(worker, name, None)) for name in ("acquire", "snapshot", "execute_cell", "cleanup"))


async def _cleanup(gateway: object, provider: object, worker: object, opened: bool, provider_closed: bool) -> None:
    if opened:
        for name in ("cancel", "close"):
            try:
                await getattr(gateway, name)()
            except BaseException:
                pass
    if not provider_closed:
        try:
            await provider.close()
        except BaseException:
            pass
    try:
        await worker.cleanup()
    except BaseException:
        pass


__all__ = ("P6DevelopmentGateway", "P6DevelopmentProvider", "P6DevelopmentWorker", "PrimeP6DevelopmentHostError", "run_p6_development_lifecycle")
