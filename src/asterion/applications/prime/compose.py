"""P4 process handoff that resumes the P1 kernel in a new process.

The commit process executes one setup cell, seals the cell and the kernel-object
identity through the P4 continuity store, and exits. The recover process is a new
P1 worker. It replays that sealed cell and accepts the resume only when the
object identity matches exactly and the worker identity does not.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import sys
import time

from asterion.agents.prime.application import (
    PrimeApplication,
    PrimeApplicationSpec,
    PrimeTextLimits,
    prepare_prime_application,
)
from asterion.agents.prime.deadline import TaskDeadline
from asterion.agents.prime.store import FilePrimeSessionStore
from asterion.applications.prime.live_model import (
    bounded_text_limits,
    resolve_live_model_context,
)
from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
from asterion.applications.prime.p1.worker import P1CellRequest, digest
from asterion.applications.prime.p4 import operator
from asterion.runtime.host import CancellationSignal


KERNEL_OBJECTS = ("AffineAccumulator", "accumulator")
_PROMPT = (
    "Write one Python cell for the persistent kernel. Define class "
    "AffineAccumulator whose __init__(self, multiplier, offset) stores those "
    "two attributes and whose __call__(self, value) returns "
    "multiplier * value + offset. Then assign "
    "accumulator = AffineAccumulator(input_tuple[0], input_tuple[1]). "
    "Use no imports, no base classes, and no dunder names except __init__ "
    "and __call__. Return only the cell."
)


class ComposeError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P1 kernel handoff failed")


class _Open:
    cancelled = False


@dataclass(frozen=True, slots=True)
class ComposeReceipt:
    status: str
    continuation_id: str
    generation: int
    prior_checkpoint_sha256: str
    receipt_sha256: str
    resumed_kernel_objects: tuple[str, ...]
    kernel_object_identity: str
    identity_match: str
    commit_worker_identity_sha256: str
    resume_worker_identity_sha256: str
    model_call_count: int
    input_tokens: int
    output_tokens: int
    cost_micros: int


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _cell(text: object) -> str:
    if type(text) is not str:
        raise ComposeError()
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
    try:
        encoded = body.encode("utf-8")
    except UnicodeError:
        raise ComposeError() from None
    if not body or len(encoded) > 16_384 or "class AffineAccumulator" not in body:
        raise ComposeError()
    return body


def _object_identity(observation) -> str:
    if (
        observation.status != "completed"
        or observation.class_name != "AffineAccumulator"
        or type(observation.accumulator_id) is not int
        or observation.callable_probe != (40, 58)
    ):
        raise ComposeError()
    return digest(
        {
            "callable_probe": [40, 58],
            "class_name": "AffineAccumulator",
            "names": list(KERNEL_OBJECTS),
        }
    )


async def _observe(code: str) -> tuple[str, str]:
    worker = P1WorkerProcess(deadline=time.monotonic() + 30)
    failed = False
    try:
        await worker.start()
        receipt = await worker.execute_cell(
            P1CellRequest("compose-setup", "compose-turn", code)
        )
        if receipt.status != "ok":
            raise ComposeError()
        observation = worker.snapshot().cells[-1]
        return _object_identity(observation), worker.snapshot().identity.sha256()
    except ComposeError:
        failed = True
        raise
    except Exception:
        failed = True
        raise ComposeError() from None
    finally:
        try:
            await worker.close()
        except Exception:
            if not failed:
                raise ComposeError() from None


def _usage_numbers(ask) -> tuple[int, int, int]:
    usage = getattr(ask, "usage", None)
    if usage is None:
        return (0, 0, 0)
    values = []
    for name in ("input_tokens", "output_tokens", "cost_micros"):
        value = usage[name] if isinstance(usage, dict) else getattr(usage, name)
        if type(value) is not int or value < 0:
            raise ComposeError()
        values.append(value)
    return (values[0], values[1], values[2])


async def run_kernel_handoff(
    *, private_root: Path, ask, signal: CancellationSignal | None = None
) -> ComposeReceipt:
    """Commit one P1 kernel, then resume it in a new process through P4."""

    active = signal if signal is not None else _Open()
    if active.cancelled or not isinstance(private_root, Path):
        raise ComposeError()
    private_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    code = _cell(await ask(_PROMPT, active))
    if active.cancelled:
        raise asyncio.CancelledError()
    input_tokens, output_tokens, cost_micros = _usage_numbers(ask)
    commit_identity, commit_worker = await _observe(code)
    catalog = {
        "cell_sha256": digest(code),
        "kernel_object_identity": commit_identity,
        "resumed_kernel_objects": list(KERNEL_OBJECTS),
        "source": code,
    }
    if digest(code) != catalog["cell_sha256"]:
        raise ComposeError()
    transcript = _canonical(catalog)
    session_id = "compose-" + secrets.token_hex(8)
    continuation_id = "compose-cont-" + secrets.token_hex(8)
    identity = operator._build_identity(
        private_root=private_root,
        generation=1,
        continuation_id=continuation_id,
        worker_sha=commit_worker,
        session_id=session_id,
    )
    store = FilePrimeSessionStore(private_root, identity)
    try:
        committed = operator._seal_commit_checkpoint(
            store=store,
            worker_sha=commit_worker,
            prior_checkpoint_sha=None,
            run_id="compose-commit-" + secrets.token_hex(8),
            transcript=transcript,
            usage={
                "identity_match": "strict",
                "kernel_object_identity": commit_identity,
                "result_sha256": commit_identity,
                "resumed_kernel_objects": list(KERNEL_OBJECTS),
            },
            continuation_id=continuation_id,
        )
    finally:
        store.close()

    resume_identity, resume_worker = await _observe(code)
    if resume_identity != commit_identity or resume_worker == commit_worker:
        raise ComposeError()
    recovered_identity = operator._build_identity(
        private_root=private_root,
        generation=2,
        continuation_id=continuation_id,
        worker_sha=resume_worker,
        session_id=session_id,
    )
    resumed = FilePrimeSessionStore.open_continued(private_root, recovered_identity)
    try:
        prior = resumed.recover_checkpoint()
        previous = resumed.continued_from
        if (
            prior is None
            or previous is None
            or prior.checkpoint.digest != committed.digest
            or prior.transcript != transcript
            or resumed.identity.continuation_id != continuation_id
            or previous.worker_identity_sha256 != commit_worker
        ):
            raise ComposeError()
        loaded = json.loads(prior.transcript)
        if (
            loaded.get("kernel_object_identity") != resume_identity
            or loaded.get("resumed_kernel_objects") != list(KERNEL_OBJECTS)
            or loaded.get("cell_sha256") != digest(loaded.get("source", ""))
            or loaded.get("source") != code
        ):
            raise ComposeError()
        sealed = operator._seal_commit_checkpoint(
            store=resumed,
            worker_sha=resume_worker,
            prior_checkpoint_sha=committed.digest,
            run_id="compose-resume-" + secrets.token_hex(8),
            transcript=transcript,
            usage={
                "identity_match": "strict",
                "input_tokens": input_tokens,
                "kernel_object_identity": resume_identity,
                "model_call_count": 1,
                "output_tokens": output_tokens,
                "result_sha256": resume_identity,
                "resumed_kernel_objects": list(KERNEL_OBJECTS),
            },
            continuation_id=continuation_id,
        )
    finally:
        resumed.close()
    return ComposeReceipt(
        status="completed",
        continuation_id=continuation_id,
        generation=2,
        prior_checkpoint_sha256=committed.digest,
        receipt_sha256=sealed.digest,
        resumed_kernel_objects=KERNEL_OBJECTS,
        kernel_object_identity=resume_identity,
        identity_match="strict",
        commit_worker_identity_sha256=commit_worker,
        resume_worker_identity_sha256=resume_worker,
        model_call_count=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micros=cost_micros,
    )


class _ModelAsk:
    def __init__(self, prime: PrimeApplication, limits: PrimeTextLimits) -> None:
        self._prime = prime
        self._limits = limits
        self.usage = None

    async def __call__(self, prompt: str, signal: CancellationSignal):
        reply = await self._prime.text_once(
            key="compose", text=prompt, limits=self._limits, signal=signal
        )
        self.usage = reply.usage
        return reply.text


async def run_operator_live(environment: dict[str, str]) -> ComposeReceipt:
    root_text = environment.get("ASTERION_PRIME_OPERATOR_ROOT", "")
    private_text = environment.get("ASTERION_PRIME_COMPOSE_PRIVATE_ROOT", "")
    if not root_text or not private_text:
        raise ComposeError()
    base = Path(private_text).resolve()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_root = base / ("handoff-" + secrets.token_hex(8))
    limits = bounded_text_limits()
    deadline = TaskDeadline(
        deadline_monotonic=time.monotonic() + limits.deadline_seconds,
        deadline_epoch=time.time() + limits.deadline_seconds,
    )
    context = resolve_live_model_context(
        Path(root_text), environment, task_deadline=deadline
    )
    prime = prepare_prime_application(
        PrimeApplicationSpec("prime.bounded-autonomy", "1.0.0", "text-only"),
        context,
        authorization=limits,
    )
    try:
        return await run_kernel_handoff(
            private_root=private_root, ask=_ModelAsk(prime, limits)
        )
    finally:
        async with asyncio.timeout(5):
            cleanup = await prime.close()
        if not cleanup.complete:
            raise ComposeError()


def main() -> int:
    try:
        result = asyncio.run(run_operator_live(dict(os.environ)))
    except BaseException:
        print('{"status":"unavailable"}')
        return 2
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.stdout.flush()
    raise SystemExit(main())
