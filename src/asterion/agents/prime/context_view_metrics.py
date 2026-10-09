"""Owned private numerical extension-hook measurements; never provider tokens."""
from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = 'asterion.prime-context-view-metrics/v1'
MEASUREMENT = 'extension-hook-json-utf8'
_MAX_BYTES = 1024 * 1024
_MAX_SAMPLES = 1024
_MAX_INTEGER = (1 << 53) - 1
_FIELDS = frozenset({'requests', 'assistant_bytes', 'current_snapshot_bytes',
                     'tool_result_bytes', 'other_bytes', 'total_bytes',
                     'peak_total_bytes', 'cumulative_total_bytes',
                     'unmeasurable_requests'})


def _sample(value: object) -> dict:
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError
    if any(type(v) is not int or not 0 <= v <= _MAX_INTEGER for v in value.values()):
        raise ValueError
    total = sum(value[k] for k in ('assistant_bytes', 'current_snapshot_bytes',
                                   'tool_result_bytes', 'other_bytes'))
    if (value['total_bytes'] != min(total, _MAX_INTEGER)
            or value['peak_total_bytes'] < value['total_bytes']
            or value['cumulative_total_bytes'] < value['peak_total_bytes']
            or value['unmeasurable_requests'] > value['requests']):
        raise ValueError
    return value


def _validate(value: object) -> dict:
    if (type(value) is not dict or set(value) != {
            'version', 'measurement', 'latest', 'samples', 'samples_truncated'}
            or value['version'] != VERSION or value['measurement'] != MEASUREMENT
            or type(value['samples_truncated']) is not int
            or value['samples_truncated'] not in (0, 1)
            or type(value['samples']) is not list
            or len(value['samples']) > _MAX_SAMPLES):
        raise ValueError
    latest = _sample(value['latest'])
    previous = None
    for raw in value['samples']:
        current = _sample(raw)
        if previous is not None and (current['requests'] <= previous['requests']
                or current['peak_total_bytes'] < previous['peak_total_bytes']
                or current['cumulative_total_bytes'] < previous['cumulative_total_bytes']
                or current['unmeasurable_requests'] < previous['unmeasurable_requests']):
            raise ValueError
        previous = current
    if previous is not None and (latest['requests'] < previous['requests']
            or latest['peak_total_bytes'] < previous['peak_total_bytes']
            or latest['cumulative_total_bytes'] < previous['cumulative_total_bytes']
            or latest['unmeasurable_requests'] < previous['unmeasurable_requests']):
        raise ValueError
    if not value['samples_truncated'] and (not value['samples'] or previous != latest):
        raise ValueError
    return value


class ContextViewMetricsFile:
    """One exclusive regular file, handed to a pinned extension by inherited FD."""

    def __init__(self, path: Path):
        self._descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL
                                   | getattr(os, 'O_NOFOLLOW', 0), 0o600)

    @property
    def descriptor(self) -> int:
        if self._descriptor < 0:
            raise ValueError('context metrics unavailable')
        return self._descriptor

    def __repr__(self) -> str:
        return '<ContextViewMetricsFile redacted>'

    def read(self) -> dict:
        """Read a finite closed numeric shape; malformed/partial writes stay body-free."""
        try:
            size = os.fstat(self.descriptor).st_size
            if size == 0:
                return {'status': 'not-recorded'}
            if size > _MAX_BYTES:
                raise ValueError
            body = os.pread(self.descriptor, _MAX_BYTES + 1, 0)
            if len(body) != size:
                raise ValueError
            value = _validate(json.loads(body))
            return {'status': 'recorded', **value}
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            return {'status': 'unavailable'}

    def close(self) -> None:
        if self._descriptor >= 0:
            descriptor, self._descriptor = self._descriptor, -1
            os.close(descriptor)
