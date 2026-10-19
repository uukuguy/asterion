"""Bind a P1 worker snapshot to Prime's code-aware compaction summary."""

from __future__ import annotations

from asterion.agents.prime.code_summary import (
    CodeAwareSummary,
    CodeSummaryError,
    KernelBinding,
    build_code_aware_summary,
)
from asterion.applications.prime.p1.worker import P1InstrumentationSnapshot


def kernel_bindings(snapshot: P1InstrumentationSnapshot) -> tuple[KernelBinding, ...]:
    """Names the live kernel still defines, read from the worker observation."""

    if type(snapshot) is not P1InstrumentationSnapshot:
        raise CodeSummaryError()
    bindings: list[KernelBinding] = []
    seen: set[str] = set()

    def add(name: object, kind: str) -> None:
        if type(name) is not str or name in seen:
            return
        binding = KernelBinding(name, kind)
        seen.add(name)
        bindings.append(binding)

    for cell in snapshot.cells:
        if cell.status == "completed" and cell.class_name is not None:
            add(cell.class_name, "class")
            if type(cell.accumulator_id) is int:
                add("accumulator", "callable")
    for name in snapshot.seeded_symbols:
        add(name, "value")
    if not bindings:
        raise CodeSummaryError()
    return tuple(bindings)


def summarize_worker(
    snapshot: P1InstrumentationSnapshot, *, keep_recent_tokens: int
) -> CodeAwareSummary:
    """The summary ``P1OperatorResources.compact`` stores for the public receipt."""

    return build_code_aware_summary(
        kernel_bindings(snapshot), keep_recent_tokens=keep_recent_tokens
    )


__all__ = ("kernel_bindings", "summarize_worker")
