"""One finite P2 inquiry on the operator's injected text model.

The default P2 preset stays a zero-token local retrieval. This entry asks the
prepared model for one query and one answer. The corpus scanner and the
fragment check stay in the application.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import time

from asterion.agents.prime.application import (
    PrimeApplicationSpec,
    prepare_prime_application,
)
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.live_model import (
    LiveModelReply,
    bounded_text_limits,
    resolve_live_model_context,
)
from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.inquiry import (
    P2InquiryError,
    run_model_inquiry,
)
from asterion.applications.prime.p2.program import P2ProgramError, interpret
from asterion.runtime.host import CancellationSignal


class P2LiveError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P2 live inquiry failed")


class _NeverCancelled:
    cancelled = False


@dataclass(frozen=True, slots=True)
class P2LiveResult:
    status: str
    provider: str
    model: str
    operation: str
    bounds: tuple[int, int]
    fragment_sha256: str
    notes_revision: str
    model_call_count: int
    input_tokens: int
    output_tokens: int
    cost_micros: int

    def __post_init__(self) -> None:
        if (
            self.status != "verified"
            or self.provider != "deepseek"
            or self.model != "deepseek-flash"
            or self.operation not in {"retrieve", "transform"}
            or type(self.bounds) is not tuple
            or len(self.bounds) != 2
            or self.model_call_count < 2
            or self.input_tokens <= 0
            or self.output_tokens < 0
            or self.cost_micros < 0
            or len(self.fragment_sha256) != 64
            or not self.notes_revision.startswith("sha256:")
        ):
            raise P2LiveError()


def _object(text: str) -> dict:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise P2LiveError()
            result[key] = value
        return result

    try:
        value = json.loads(body, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise P2LiveError() from None
    if type(value) is not dict:
        raise P2LiveError()
    return value


class _PromptInquiry:
    """Two model turns. A malformed reply gets one replacement ask."""

    def __init__(self, loop, prompt, signal: CancellationSignal, record_count: int):
        self._loop = loop
        self._prompt = prompt
        self._signal = signal
        self._records = record_count
        self.calls = 0
        self.usage: list[tuple[int, int, int]] = []

    def _complete(self, text: str) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self._prompt(text, signal=self._signal), self._loop
        )
        reply = future.result()
        if type(reply) is not LiveModelReply:
            raise P2LiveError()
        usage = reply.usage
        incoming, outgoing, cost = usage.input_tokens, usage.output_tokens, usage.cost_micros
        if (
            type(incoming) is not int
            or type(outgoing) is not int
            or type(cost) is not int
            or incoming < 0
            or outgoing < 0
            or cost < 0
            or incoming + outgoing == 0
        ):
            raise P2LiveError()
        self.calls += 1
        self.usage.append((incoming, outgoing, cost))
        return reply.text

    def _ask(self, text: str) -> dict:
        reply_text = text
        for _attempt in range(2):
            try:
                return _object(self._complete(reply_text))
            except P2LiveError:
                reply_text = (
                    text
                    + "\nThe previous reply was not one JSON object. "
                    + "Return only that JSON object."
                )
        raise P2InquiryError()

    def write_query(self, task: str) -> dict:
        prompt = (
            f"{task}\n\n"
            f"The corpus has {self._records} records, indexed from 0. "
            "Write one Python statement and no other text. "
            "Call retrieve(start, end) or transform(start, end, \"key\", ...). "
            "Bounds are a half-open interval and must select exactly one record. "
            "A legal reply is retrieve(0, 1). "
            "Use no tools, no imports, no attributes, and no other names."
        )
        reply_text = prompt
        for _attempt in range(2):
            try:
                return interpret(self._complete(reply_text), self._records)
            except P2ProgramError:
                reply_text = (
                    prompt
                    + "\nThe previous reply was not one legal statement. "
                    + "Return only that statement. Use no tools."
                )
        raise P2InquiryError()

    def write_answer(self, task: str, fragment: dict) -> dict:
        shown = {
            "operation": fragment.get("operation"),
            "bounds": fragment.get("bounds"),
            "records": fragment.get("records"),
            "fragment_sha256": fragment.get("fragment_sha256"),
        }
        encoded = json.dumps(shown, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return self._ask(
            f"{task}\n\n"
            "The host retrieved this fragment. Return only one JSON object "
            "with exactly the keys text and fragment_sha256. "
            "Copy fragment_sha256 exactly. text is a short answer about the fragment. "
            "Use no tools.\n"
            f"{encoded}"
        )


async def run_live_inquiry(
    *,
    service: P2ContextService,
    notes_root: Path,
    prompt,
    provider: str,
    model: str,
    signal: CancellationSignal | None = None,
) -> P2LiveResult:
    if service.record_count < 1:
        raise P2LiveError()
    active = signal if signal is not None else _NeverCancelled()
    loop = asyncio.get_running_loop()
    writer = _PromptInquiry(loop, prompt, active, service.record_count)
    verified = await asyncio.to_thread(
        run_model_inquiry, service=service, model=writer, notes_root=notes_root
    )
    return P2LiveResult(
        status=verified.status,
        provider=provider,
        model=model,
        operation=verified.operation,
        bounds=verified.bounds,
        fragment_sha256=verified.fragment_sha256,
        notes_revision=verified.notes_revision,
        model_call_count=writer.calls,
        input_tokens=sum(item[0] for item in writer.usage),
        output_tokens=sum(item[1] for item in writer.usage),
        cost_micros=sum(item[2] for item in writer.usage),
    )


async def run_operator_live(environment: dict[str, str]) -> P2LiveResult:
    root_text = environment.get("ASTERION_PRIME_OPERATOR_ROOT", "")
    corpus_text = environment.get("ASTERION_PRIME_P2_CORPUS", "")
    if not root_text or not corpus_text:
        raise P2LiveError()
    limits = bounded_text_limits()
    deadline = TaskDeadline(
        deadline_monotonic=time.monotonic() + limits.deadline_seconds,
        deadline_epoch=time.time() + limits.deadline_seconds,
    )
    context = resolve_live_model_context(Path(root_text), environment, task_deadline=deadline)
    service = P2ContextService(corpus_text)
    prime = prepare_prime_application(
        PrimeApplicationSpec("prime.programmatic-long-context", "1.0.0", "text-only"),
        context,
        authorization=limits,
    )
    notes = tempfile.TemporaryDirectory(prefix="asterion-p2-live-")
    try:
        view = prime.text_model(key="p2-inquiry", limits=limits)

        async def prompt(text: str, *, signal: CancellationSignal) -> LiveModelReply:
            return await view.prompt(text, signal=signal)

        return await run_live_inquiry(
            service=service,
            notes_root=Path(notes.name),
            prompt=prompt,
            provider=context.provider,
            model=context.model,
        )
    finally:
        cleanup = await prime.close()
        notes.cleanup()
        if not cleanup.complete:
            raise P2LiveError()


def main() -> int:
    try:
        result = asyncio.run(run_operator_live(dict(os.environ)))
    except BaseException:
        print('{"status":"protocol-failure"}', flush=True)
        return 2
    payload = {
        "status": result.status,
        "provider": result.provider,
        "model": result.model,
        "operation": result.operation,
        "bounds": [result.bounds[0], result.bounds[1]],
        "fragment_sha256": result.fragment_sha256,
        "notes_revision": result.notes_revision,
        "model_call_count": result.model_call_count,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_micros": result.cost_micros,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "P2LiveError",
    "P2LiveResult",
    "main",
    "run_live_inquiry",
    "run_operator_live",
)
