"""Trusted, provider-free gate for the fixed P6 development refinement."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
import json
import os
import re
from typing import Protocol

from asterion.applications.prime_agent.continual_improvement_acceptance import (
    continual_improvement_revision_sha256,
    continual_improvement_scope_sha256,
    continual_improvement_snapshot_sha256,
)
from asterion.control.harness import (
    HarnessCoordinator, HarnessEdit, HarnessEffectReceipt, HarnessEntryDescriptor,
    HarnessProposal, HarnessScope, harness_effect_digest,
)
from asterion.control.journal import JournalRecord, MemoryCanonicalJournal

from .p6_development_receipt import P6DevelopmentReceipt, validate_p6_development_receipt
from .p6_development_workload import (
    P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256, P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
    P6_DEVELOPMENT_MODEL_DIGEST, P6_DEVELOPMENT_ORACLE_DIGEST,
    P6_DEVELOPMENT_SCHEMA_DIGEST, P6_DEVELOPMENT_WORKLOAD_DIGEST,
)

_BASELINE_SOURCE = b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
_CANDIDATE_SOURCE = b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n"
_BAD_CANDIDATE_SOURCE = b"def clamp(value, lower, upper):\n    return max(value, lower)\n"
_TASK_A_CASES = ((-4, -2, 3),)
_HOLDOUT_CASES = ((4, -2, 3),)
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
    async def restore_baseline(self) -> None: ...
    async def cleanup(self) -> None: ...


async def run_p6_development_lifecycle(*, gateway: P6DevelopmentGateway, provider: P6DevelopmentProvider, worker: P6DevelopmentWorker, run_id: str, session_id: str, prime_source_root: str, workspace: str) -> P6DevelopmentReceipt:
    if not _inputs(gateway, provider, worker, run_id, session_id, prime_source_root, workspace):
        raise PrimeP6DevelopmentHostError()
    opened = provider_closed = cleaned = False
    cancelled = False
    try:
        await worker.acquire()
        image_sha256 = _worker_digest(worker, "image_digest")
        container_sha256 = "sha256:" + _worker_daemon(worker)
        _baseline_snapshot(await worker.snapshot())
        model_calls = tool_calls = 0

        async def model_hook(payload: object) -> dict[str, object]:
            nonlocal model_calls
            if type(payload) is not dict or model_calls >= 6:
                raise ValueError
            response = await provider(_canonical(payload))
            model_calls += 1
            return _provider_reply(response)

        async def tool_hook(payload: object) -> dict[str, object]:
            nonlocal tool_calls
            if type(payload) is not dict or set(payload) != {"tool_call_id", "code"} or type(payload["tool_call_id"]) is not str or not payload["tool_call_id"] or type(payload["code"]) is not str or not payload["code"] or tool_calls >= 3:
                raise ValueError
            tool_calls += 1
            result = await worker.execute_cell(payload["code"])
            if type(result) is not dict or result != {"cell_count": tool_calls}:
                raise ValueError
            return {"content": [{"type": "text", "text": "IPython cell completed"}], "details": {}, "isError": False}

        gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
        opened = True  # Own cleanup even when open reports after allocating resources.
        await gateway.open(run_id=run_id, session_id=session_id, generation=1, prime_source_root=prime_source_root, workspace=workspace)
        _completed(await gateway.prompt(_prompt(1, run_id, session_id)), 2, 1)
        task_a = _task_a_snapshot(await worker.snapshot(), run_id, session_id)
        _completed(await gateway.prompt(_prompt(2, run_id, session_id)), 4, 2)
        candidate = _candidate_snapshot(await worker.snapshot(), run_id, session_id)
        coordinator, baseline, proposal, body_store = _coordinator(run_id, candidate, task_a)
        candidate_revision = coordinator.apply(proposal)
        candidate_harness = coordinator.snapshot()
        selected = _selected_candidate(candidate_harness, body_store)
        if selected != candidate:
            raise ValueError
        _completed(await gateway.prompt(_prompt(3, run_id, session_id, "sha256:" + sha256(selected).hexdigest())), 6, 3)
        holdout_passed, holdout = _task_b_snapshot(await worker.snapshot(), run_id, session_id, selected)
        if (model_calls, tool_calls) != (6, 3):
            raise ValueError
        _terminal_witness(gateway.terminal_witness(), run_id, session_id)
        usage_sha256 = _digest(_usage(provider.terminal_usage()))
        rollback = None
        outcome = "preserved" if holdout_passed else "rolled-back"
        if not holdout_passed:
            rollback = coordinator.rollback(proposal_id="p6-rollback", authority_id="p6-host", authority_revision=1, target_revision_id=candidate_revision.revision_id, rationale_ref="p6-rollback", rationale_digest=_bare(_digest({"task_b": holdout})), expected_outcome_digest=_bare(_digest({"outcome": outcome})))
            body_store.clear()
            await worker.restore_baseline()
            _baseline_snapshot(await worker.snapshot())
        final_harness = coordinator.snapshot()
        await gateway.close()
        opened = False
        await provider.close()
        provider_closed = True
        await worker.cleanup()
        cleaned = True
        final_source = P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256 if holdout_passed else P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256
        receipt = P6DevelopmentReceipt(
            P6_DEVELOPMENT_WORKLOAD_DIGEST, P6_DEVELOPMENT_SCHEMA_DIGEST, P6_DEVELOPMENT_MODEL_DIGEST, P6_DEVELOPMENT_ORACLE_DIGEST,
            P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256, "sha256:" + sha256(selected).hexdigest(), _digest(task_a), _digest(holdout), final_source, _digest({"outcome": outcome}),
            _digest({"run": run_id}), _digest({"session": session_id}), container_sha256, image_sha256, usage_sha256,
            continual_improvement_scope_sha256(baseline.scope), continual_improvement_snapshot_sha256(baseline), continual_improvement_snapshot_sha256(candidate_harness), continual_improvement_snapshot_sha256(final_harness), "sha256:" + proposal.digest, continual_improvement_revision_sha256(candidate_revision), None if rollback is None else continual_improvement_revision_sha256(rollback),
            "project", ("ipython",), 3, 6, 3, 1, 1, 0 if holdout_passed else 1, outcome, True, True,
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
        raise asyncio.CancelledError()
    raise PrimeP6DevelopmentHostError()


def _coordinator(run_id: str, candidate: bytes, task_a: dict[str, object]) -> tuple[HarnessCoordinator, object, HarnessProposal, dict[str, bytes]]:
    scope = HarnessScope.project("p6-" + sha256(run_id.encode()).hexdigest()[:16])
    journal = MemoryCanonicalJournal(scope.scope_id or "p6")
    first = journal.append(0, JournalRecord.system_bound(system_id="p6-development", system_version="1.0.0"))
    journal.append(first.position, JournalRecord.authority_bound(authority_id="p6-host", authority_revision=1))
    def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
        return HarnessEffectReceipt.succeeded(proposal, effect_digest=harness_effect_digest(proposal), result_entries=tuple(edit.replacement for edit in proposal.edits if edit.replacement is not None))
    coordinator = HarnessCoordinator(journal, scope, send)
    baseline = coordinator.snapshot()
    body_ref = "p6-candidate-body"
    task_a_digest = _bare(_digest(task_a))
    candidate_digest = sha256(candidate).hexdigest()
    entry = HarnessEntryDescriptor("p6-candidate", "skill", candidate_digest, body_ref, candidate_digest, None, task_a_digest, 1)
    proposal = HarnessProposal("p6-candidate", "p6-host", 1, scope, baseline.snapshot_id, (HarnessEdit.create(entry),), ("p6-task-a",), "p6-task-a", task_a_digest, task_a_digest)
    return coordinator, baseline, proposal, {body_ref: candidate}


def _selected_candidate(snapshot: object, bodies: Mapping[str, bytes]) -> bytes:
    entries = getattr(snapshot, "entries", ())
    if len(entries) != 1:
        raise ValueError
    entry = entries[0]
    body = bodies.get(entry.body_ref)
    if entry.entry_id != "p6-candidate" or entry.kind != "skill" or body is None or entry.body_digest != sha256(body).hexdigest():
        raise ValueError
    return body


def _baseline_snapshot(value: object) -> None:
    if value != {"baseline.py": _BASELINE_SOURCE} or _clamp_passes(_BASELINE_SOURCE):
        raise ValueError


def _task_a_snapshot(value: object, run_id: str, session_id: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != {"baseline.py", "task-a.json"} or value["baseline.py"] != _BASELINE_SOURCE:
        raise ValueError
    return _artifact(value["task-a.json"], "clamp-task-a/v1", "task-a", run_id, session_id, _BASELINE_SOURCE)


def _candidate_snapshot(value: object, run_id: str, session_id: str) -> bytes:
    if type(value) is not dict or set(value) != {"baseline.py", "task-a.json", "candidate.py"} or value["baseline.py"] != _BASELINE_SOURCE or value["task-a.json"] != _task_a_artifact(run_id, session_id) or not _admitted_candidate(value["candidate.py"]):
        raise ValueError
    return value["candidate.py"]


def _task_b_snapshot(value: object, run_id: str, session_id: str, candidate: bytes) -> tuple[bool, dict[str, object]]:
    if type(value) is not dict or set(value) != {"baseline.py", "task-a.json", "candidate.py", "task-b.json"} or value["baseline.py"] != _BASELINE_SOURCE or value["task-a.json"] != _task_a_artifact(run_id, session_id) or value["candidate.py"] != candidate:
        raise ValueError
    artifact = _artifact(value["task-b.json"], "clamp-task-b/v1", "task-b", run_id, session_id, candidate)
    return artifact["passed"], artifact


def _artifact(raw: object, fixture: str, stage: str, run_id: str, session_id: str, source: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise ValueError
    try:
        item = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    expected = {"fixture", "inputs", "outputs", "passed", "run_id", "session_id", "source_sha256", "stage"}
    if type(item) is not dict or set(item) != expected or item["fixture"] != fixture or item["stage"] != stage or item["run_id"] != run_id or item["session_id"] != session_id or item["source_sha256"] != "sha256:" + sha256(source).hexdigest() or _canonical(item) != raw or type(item["passed"]) is not bool:
        raise ValueError
    inputs = item["inputs"]
    outputs = item["outputs"]
    cases = _TASK_A_CASES if stage == "task-a" else _HOLDOUT_CASES
    if not isinstance(inputs, list) or not isinstance(outputs, list) or inputs != [list(case) for case in cases] or len(outputs) != len(cases) or any(type(value) is not int for value in outputs):
        raise ValueError
    actual = [_evaluate_clamp(source, *case) for case in cases]
    expected_outputs = [min(max(*case[:2]), case[2]) for case in cases]
    if outputs != actual or item["passed"] != (actual == expected_outputs):
        raise ValueError
    return item


def _task_a_artifact(run_id: str, session_id: str) -> bytes:
    return _artifact_bytes("clamp-task-a/v1", "task-a", run_id, session_id, _BASELINE_SOURCE)


def _task_b_artifact(run_id: str, session_id: str, source: bytes = _CANDIDATE_SOURCE) -> bytes:
    return _artifact_bytes("clamp-task-b/v1", "task-b", run_id, session_id, source)


def _artifact_bytes(fixture: str, stage: str, run_id: str, session_id: str, source: bytes) -> bytes:
    cases = _TASK_A_CASES if stage == "task-a" else _HOLDOUT_CASES
    outputs = [_evaluate_clamp(source, *case) for case in cases]
    expected = [min(max(*case[:2]), case[2]) for case in cases]
    return _canonical({"fixture": fixture, "inputs": [list(case) for case in cases], "outputs": outputs, "passed": outputs == expected, "run_id": run_id, "session_id": session_id, "source_sha256": "sha256:" + sha256(source).hexdigest(), "stage": stage})


def _admitted_candidate(source: object) -> bool:
    return type(source) is bytes and source in {_CANDIDATE_SOURCE, _BAD_CANDIDATE_SOURCE} and _candidate_ast(source)


def _clamp_passes(source: bytes) -> bool:
    return _admitted_candidate(source) and all(_evaluate_clamp(source, *case) == min(max(*case[:2]), case[2]) for case in _HOLDOUT_CASES)


def _candidate_ast(source: bytes) -> bool:
    return source in {_CANDIDATE_SOURCE, _BAD_CANDIDATE_SOURCE}


def _evaluate_clamp(source: bytes, value: int, lower: int, upper: int) -> int:
    try:
        tree = ast.parse(source.decode(), mode="exec")
        function = tree.body[0]
        expr = function.body[0].value
    except (AttributeError, SyntaxError, UnicodeError):
        raise ValueError from None
    if not isinstance(function, ast.FunctionDef) or function.name != "clamp" or [arg.arg for arg in function.args.args] != ["value", "lower", "upper"] or not isinstance(expr, ast.Call):
        raise ValueError
    def evaluate(node: ast.AST) -> int:
        if isinstance(node, ast.Name) and node.id in {"value", "lower", "upper"}:
            return {"value": value, "lower": lower, "upper": upper}[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"min", "max"} and not node.keywords and len(node.args) == 2:
            parts = [evaluate(part) for part in node.args]
            return min(parts) if node.func.id == "min" else max(parts)
        raise ValueError
    return evaluate(expr)


def _provider_reply(response: object) -> dict[str, object]:
    if type(response) is not bytes:
        raise ValueError
    try:
        reply = json.loads(response.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    if type(reply) is not dict or _canonical(reply) != response:
        raise ValueError
    return reply


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


def _prompt(stage: int, run_id: str, session_id: str, candidate_sha256: str | None = None) -> str:
    prompts = {
        1: f"P6 stage 1: run_id {run_id}; session_id {session_id}; compute from /workspace/baseline.py and write canonical /workspace/task-a.json fixture clamp-task-a/v1 stage task-a inputs [[-4,-2,3]] with fixture, stage, run_id, session_id, source_sha256, inputs, outputs, passed. Use one completion-only IPython call that performs the write; no printing, inspection-only calls, subprocess, scope, authority, or rollback.",
        2: f"P6 stage 2: run_id {run_id}; session_id {session_id}; task A observed /workspace/baseline.py output -4 and expected -2. Write /workspace/candidate.py with exactly `return min(max(value, lower), upper)` in one completion-only IPython call; do not spend the call inspecting. No printing, subprocess, /workspace/task-b.json, scope, authority, or rollback.",
    }
    if stage == 3 and _DIGEST.fullmatch(candidate_sha256 or ""):
        return f"P6 stage 3: run_id {run_id}; session_id {session_id}; selected candidate digest is {candidate_sha256}; read /workspace/candidate.py and write canonical /workspace/task-b.json fixture clamp-task-b/v1 stage task-b inputs [[4,-2,3]] with fixture, stage, run_id, session_id, source_sha256, inputs, outputs, passed. Use one completion-only IPython call; no printing, inspection, subprocess, scope, authority, or rollback."
    if stage in prompts:
        return prompts[stage]
    raise ValueError


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _bare(value: str) -> str:
    return value.removeprefix("sha256:")


def _inputs(gateway: object, provider: object, worker: object, run_id: object, session_id: object, prime_source_root: object, workspace: object) -> bool:
    return all(type(value) is str and value for value in (run_id, session_id)) and all(type(value) is str and os.path.isabs(value) for value in (prime_source_root, workspace)) and all(callable(getattr(gateway, name, None)) for name in ("bind", "open", "prompt", "terminal_witness", "close", "cancel")) and all(callable(getattr(provider, name, None)) for name in ("__call__", "terminal_usage", "close")) and all(callable(getattr(worker, name, None)) for name in ("acquire", "snapshot", "execute_cell", "restore_baseline", "cleanup"))


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
