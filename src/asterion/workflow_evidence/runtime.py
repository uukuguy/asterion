"""Observe validated runtime calls without retaining their private content."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)

from asterion.workflow_evidence.collector import collect_workflow_evidence


class ObservedRuntimeClient:
    """Transparent runtime proxy that retains only safe observation records."""

    def __init__(self, runtime: AgentRuntimeClient) -> None:
        self._runtime = runtime
        self._records: list[Mapping[str, object]] = []
        self._failed_attempts: list[Mapping[str, object]] = []

    @property
    def manifest(self) -> RuntimeManifest:
        """Expose the wrapped runtime's exact manifest unchanged."""

        return self._runtime.manifest

    @property
    def records(self) -> tuple[Mapping[str, object], ...]:
        """Return immutable successful workflow evidence in call order."""

        return tuple(self._records)

    @property
    def failed_attempts(self) -> tuple[Mapping[str, object], ...]:
        """Return fixed-class observations for calls without a trusted graph."""

        return tuple(self._failed_attempts)

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        """Yield the wrapped stream unchanged, then record its safe projection."""

        events: list[Mapping[str, object]] = []
        input_digest = hashlib.sha256(request.input_text.encode("utf-8")).hexdigest()
        try:
            async for event in self._runtime.run(request, signal=signal):
                events.append(event.to_mapping())
                yield event
            evidence = collect_workflow_evidence(events, input_digest=input_digest)
        except BaseException:
            self._failed_attempts.append(
                MappingProxyType(
                    {
                        "schema": "asterion.workflow-observation/v1",
                        "run_id": request.run_id,
                        "input_digest": input_digest,
                        "status": "cancelled"
                        if signal is not None and signal.cancelled
                        else "failed",
                        "failure_class": "runtime-cancelled"
                        if signal is not None and signal.cancelled
                        else "runtime-invocation-failed",
                    }
                )
            )
            raise
        self._records.append(MappingProxyType(evidence))
