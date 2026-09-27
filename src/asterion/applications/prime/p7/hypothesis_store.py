"""Persistent-kernel hypothesis storage for P7 model runs.

Each (level, key) tuple holds a single value the model can write and
read across cells. The store lives in the IPython namespace (not in
the LLM context) so values survive compaction summaries — the model
sees a Goal / Progress / Next Steps compressed view but the values
themselves are still available through ``p7_hypothesis``.
"""

from __future__ import annotations

from typing import Any


class _HypothesisState:
    """Per-run hypothesis state. Single instance per ``ArcBroker``."""

    __slots__ = ("_store",)

    def __init__(self) -> None:
        self._store: dict[tuple[int, str], Any] = {}

    def getset(self, level: int, key: str, value: Any) -> Any:
        if value is _MISSING:
            return self._store.get((level, key))
        self._store[(level, key)] = value
        return value


_MISSING = object()


# Module-level singleton so that ``p7_hypothesis(level, key, value)`` from
# the worker module reaches the same store as ``broker.hypothesis(level,
# key, value)`` from the host side.
_state = _HypothesisState()


def hypothesis_store(level: int) -> _HypothesisState:
    """Return the per-level hypothesis view.

    The single store instance is shared across calls; ``level`` is part
    of the key, so callers always pass it through.
    """
    return _state
