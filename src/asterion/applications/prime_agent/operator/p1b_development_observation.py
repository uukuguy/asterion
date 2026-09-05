"""Private, in-memory stage observation for one P1-B development run."""

from __future__ import annotations

from dataclasses import dataclass


_STAGES = frozenset({
    "worker.acquire", "worker.snapshot0", "gateway.open", "gateway.prompt0",
    "gateway.compact", "gateway.prompt1", "provider.callback", "worker.cell",
    "provider.usage", "worker.finish", "worker.snapshot1", "oracle", "trace",
    "gateway.close", "provider.close", "worker.cleanup",
})
_LANES = frozenset({"work", "cleanup"})
_STATES = frozenset({
    "started", "succeeded", "failed", "failed-dns", "failed-connect",
    "failed-tls", "failed-timeout", "failed-http-4xx", "failed-http-5xx",
    "failed-response",
})
_INDEX_LIMITS = {
    "provider.callback": range(5),
    "worker.cell": range(2),
    "oracle": range(2),
}
_MAX_EVENTS = 128


@dataclass(frozen=True, slots=True, repr=False)
class _P1BObservationEvent:
    stage: str
    lane: str
    state: str
    index: int | None

    def __repr__(self) -> str:
        return "_P1BObservationEvent(redacted)"


@dataclass(frozen=True, slots=True, repr=False)
class _P1BObservationSnapshot:
    events: tuple[_P1BObservationEvent, ...]
    first_work_failure: _P1BObservationEvent | None
    cleanup_failures: tuple[_P1BObservationEvent, ...]
    observation_invalid: bool

    def __repr__(self) -> str:
        return "_P1BObservationSnapshot(redacted)"


class _P1BObservation:
    """Never-raising recorder for fixed, non-sensitive execution stages."""

    __slots__ = ("_cleanup_failures", "_events", "_first_work_failure", "_invalid")

    def __init__(self) -> None:
        self._events: list[_P1BObservationEvent] = []
        self._first_work_failure: _P1BObservationEvent | None = None
        self._cleanup_failures: list[_P1BObservationEvent] = []
        self._invalid = False

    def record(
        self, stage: str, *, lane: str = "work", state: str = "started", index: int | None = None,
    ) -> None:
        try:
            if (
                type(stage) is not str or stage not in _STAGES
                or type(lane) is not str or lane not in _LANES
                or type(state) is not str or state not in _STATES
                or not self._valid_index(stage, index)
                or len(self._events) >= _MAX_EVENTS
            ):
                self._invalid = True
                return
            event = _P1BObservationEvent(stage, lane, state, index)
            self._events.append(event)
            if state.startswith("failed"):
                if lane == "work" and self._first_work_failure is None:
                    self._first_work_failure = event
                elif lane == "cleanup":
                    self._cleanup_failures.append(event)
        except BaseException:
            self._invalid = True

    def snapshot(self) -> _P1BObservationSnapshot:
        try:
            return _P1BObservationSnapshot(
                tuple(self._events), self._first_work_failure,
                tuple(self._cleanup_failures), self._invalid,
            )
        except BaseException:
            return _P1BObservationSnapshot((), None, (), True)

    @staticmethod
    def _valid_index(stage: str, index: int | None) -> bool:
        allowed = _INDEX_LIMITS.get(stage)
        return (
            index in allowed if allowed is not None and type(index) is int else
            allowed is None and index is None
        )
