"""Closed, public-safe progress reporting for injected host services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TextIO


HOST_PROGRESS_COMPONENTS = (
    "cleanup",
    "gateway",
    "image",
    "model",
    "preflight",
    "source",
    "tool",
    "validation",
    "worker",
)
HOST_PROGRESS_STATES = ("failed", "started", "succeeded")
_COMPONENT_LABELS = {value: value for value in HOST_PROGRESS_COMPONENTS}
_STATE_LABELS = {value: value for value in HOST_PROGRESS_STATES}
_MAX_TOTAL = 64


@dataclass(frozen=True, slots=True)
class HostProgressEvent:
    """One closed, non-sensitive host progress observation."""

    component: str
    state: str
    current: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.component) is not str
            or self.component not in _COMPONENT_LABELS
            or type(self.state) is not str
            or self.state not in _STATE_LABELS
            or (self.current is None) != (self.total is None)
        ):
            raise ValueError("host progress event is invalid")
        if self.current is not None and (
            type(self.current) is not int
            or type(self.total) is not int
            or not 1 <= self.current <= self.total <= _MAX_TOTAL
        ):
            raise ValueError("host progress event is invalid")


class HostProgressReporter(Protocol):
    """Receive a safe host progress observation."""

    def emit(self, event: HostProgressEvent) -> None: ...


class _NoopHostProgressReporter:
    def emit(self, event: HostProgressEvent) -> None:
        del event


NOOP_HOST_PROGRESS_REPORTER: HostProgressReporter = _NoopHostProgressReporter()


class TextHostProgressReporter:
    """Render closed progress metadata to a stream, containing write failures."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._enabled = True

    def emit(self, event: HostProgressEvent) -> None:
        if not self._enabled or type(event) is not HostProgressEvent:
            return
        try:
            component = _COMPONENT_LABELS[event.component]
            state = _STATE_LABELS[event.state]
            position = (
                ""
                if event.current is None
                else f" {event.current}/{event.total}"
            )
            self._stream.write(f"[host] {component}{position}: {state}\n")
        except Exception:
            self._enabled = False


class ContainedHostProgressReporter:
    """Isolate a reporter from host services and preserve cleanup progress."""

    def __init__(self, reporter: HostProgressReporter) -> None:
        self._reporter = reporter
        self._enabled = True
        self._failed = False
        self._terminal = False

    def emit(self, event: HostProgressEvent) -> None:
        if (
            not self._enabled
            or self._terminal
            or type(event) is not HostProgressEvent
            or (self._failed and event.component != "cleanup")
        ):
            return
        try:
            copied = HostProgressEvent(
                event.component, event.state, event.current, event.total
            )
            self._reporter.emit(copied)
        except Exception:
            self._enabled = False
            return
        if event.state == "failed":
            if event.component == "cleanup":
                self._terminal = True
            else:
                self._failed = True
