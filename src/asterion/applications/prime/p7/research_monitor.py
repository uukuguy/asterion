"""Content-safe scalar research telemetry, independent of model response timing."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import threading
import time

from .run_story.model import RunStoryError
from .run_story.storage import write_atomic_file


class ResearchMonitor:
    """Publish trusted counters without retaining native event bodies."""

    def __init__(self, root: Path, run_id: str, broker, owner, *, clock=time.monotonic):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,159}', run_id):
            raise ValueError('research monitor identity invalid')
        self._path = Path(root) / 'research-status.json'
        self._broker, self._owner, self._clock = broker, owner, clock
        self._lock = threading.RLock()
        self._started = clock()
        self._record = dict(schema='asterion.prime.p7-research-status/v1', mode='research',
            run_id=run_id, started_at_epoch=time.time(), updated_at_epoch=time.time(),
            elapsed_seconds=0., model_callbacks=0, tool_callbacks=0, input_tokens=0,
            output_tokens=0, primitive_actions=0, resets=0, levels_completed=0,
            phase='running', stop_requested=False, cleanup_complete=False)
        self.sample()

    def event(self, kind, payload):
        if kind == 'usage.reported':
            with self._lock:
                for name in ('input_tokens', 'output_tokens'):
                    value = payload.get(name)
                    if type(value) is int and value >= 0:
                        self._record[name] += value
        self.sample()

    def sample(self, *, stop_requested=False, phase=None):
        with self._lock:
            if self._record['phase'] == 'closed':
                return
            self._record['updated_at_epoch'] = time.time()
            self._record['elapsed_seconds'] = max(0., self._clock() - self._started)
            self._record['stop_requested'] |= bool(stop_requested)
            if phase is not None:
                if phase not in {'running', 'settling'}:
                    raise ValueError('research monitor phase invalid')
                self._record['phase'] = phase
            try:
                counters = self._owner.runtime_observation()
                if not isinstance(counters, dict):
                    counters = {}
            except Exception:
                counters = {}
            for name in ('model_callbacks', 'tool_callbacks'):
                value = counters.get(name)
                if type(value) is int and value >= 0:
                    self._record[name] = max(self._record[name], value)
            try:
                try:
                    status = self._broker.status()
                except Exception:
                    status = self._broker.terminal_snapshot().status
                for name in ('primitive_actions', 'levels_completed'):
                    value = getattr(status, name, None)
                    if type(value) is int and value >= 0:
                        self._record[name] = max(self._record[name], value)
                self._record['resets'] = max(self._record['resets'], sum(
                    item.action == 'RESET' for item in self._broker.journal))
            except Exception:
                pass  # Optional accounting never grants authority or hides effects.
            self._write()

    def _write(self):
        try:
            write_atomic_file(self._path, json.dumps(self._record, allow_nan=False,
                sort_keys=True, separators=(',', ':')).encode())
        except (OSError, ValueError, RunStoryError):
            pass

    async def heartbeat(self, stopped, signal, control):
        while not stopped.is_set():
            try:
                stop = bool(signal.cancelled) or control.poll()['state'] == 'stop_requested'
            except Exception:
                stop = bool(signal.cancelled)
            if stop and callable(getattr(control, '_on_stop', None)):
                control._on_stop()
            self.sample(stop_requested=stop)
            try:
                await asyncio.wait_for(stopped.wait(), timeout=1.)
            except TimeoutError:
                pass

    def finish(self, *, cleanup_complete, stop_requested=False):
        with self._lock:
            self.sample(stop_requested=stop_requested, phase='settling')
            self._record['phase'] = 'closed'
            self._record['cleanup_complete'] = bool(cleanup_complete)
            self._write()
