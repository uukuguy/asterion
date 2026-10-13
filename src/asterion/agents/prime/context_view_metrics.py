"""Owned private numerical extension-hook measurements; never provider tokens."""
from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = 'asterion.prime-context-view-metrics/v1'
DIAGNOSTIC_VERSION = 'asterion.prime-context-view-metrics/v2'
MEASUREMENT = 'extension-hook-json-utf8'
_MAX_BYTES = 1024 * 1024
_MAX_SAMPLES = 1024
_MAX_INTEGER = (1 << 53) - 1
_FIELDS = frozenset({'requests', 'assistant_bytes', 'current_snapshot_bytes',
                     'tool_result_bytes', 'other_bytes', 'total_bytes',
                     'peak_total_bytes', 'cumulative_total_bytes',
                     'unmeasurable_requests'})
_STATUSES = frozenset({'unobserved', 'inactive', 'retained', 'unsafe-boundary',
                      'primary', 'primary-unavailable', 'projection-unavailable'})
_REASONS = frozenset({'none', 'archive-unavailable', 'session-mismatch',
                     'unsupported-context-edit', 'incomplete-interaction',
                     'checkpoint-mismatch', 'unreadable-message',
                     'visible-lineage-mismatch', 'projection-error'})


def _sample(value: object, *, diagnostics: bool = False) -> dict:
    fields = _FIELDS | {'projection_status', 'refusal_reason'} if diagnostics else _FIELDS
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    if any(type(value[k]) is not int or not 0 <= value[k] <= _MAX_INTEGER for k in _FIELDS):
        raise ValueError
    if diagnostics and (type(value['projection_status']) is not str
                        or value['projection_status'] not in _STATUSES
                        or type(value['refusal_reason']) is not str
                        or value['refusal_reason'] not in _REASONS):
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
            or value['version'] not in (VERSION, DIAGNOSTIC_VERSION) or value['measurement'] != MEASUREMENT
            or type(value['samples_truncated']) is not int
            or value['samples_truncated'] not in (0, 1)
            or type(value['samples']) is not list
            or len(value['samples']) > _MAX_SAMPLES):
        raise ValueError
    diagnostics = value['version'] == DIAGNOSTIC_VERSION
    latest = _sample(value['latest'], diagnostics=diagnostics)
    previous = None
    for raw in value['samples']:
        current = _sample(raw, diagnostics=diagnostics)
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

    _validate = staticmethod(_validate)

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
            value = self._validate(json.loads(body))
            return {'status': 'recorded', **value}
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            return {'status': 'unavailable'}

    def close(self) -> None:
        if self._descriptor >= 0:
            descriptor, self._descriptor = self._descriptor, -1
            os.close(descriptor)


_PREFIX_FIELDS = frozenset({'requests', 'input_bytes', 'previous_input_bytes',
                            'common_prefix_bytes', 'common_prefix_items', 'input_items',
                            'previous_input_items', 'system_changed', 'cache_key_changed',
                            'unmeasurable_requests', 'peak_input_bytes', 'tools_changed'})


def _prefix_sample(value: object) -> dict:
    if (type(value) is not dict or set(value) != _PREFIX_FIELDS
            or any(type(v) is not int or not 0 <= v <= _MAX_INTEGER for v in value.values())
            or value['system_changed'] not in (0, 1)
            or value['cache_key_changed'] not in (0, 1)
            or value['tools_changed'] not in (0, 1)
            or value['common_prefix_bytes'] > min(value['input_bytes'], value['previous_input_bytes'])
            or value['common_prefix_items'] > min(value['input_items'], value['previous_input_items'])
            or value['peak_input_bytes'] < value['input_bytes']
            or value['unmeasurable_requests'] > value['requests']):
        raise ValueError
    return value


def _validate_prefix(value: object) -> dict:
    if (type(value) is not dict or set(value) != {
            'version', 'measurement', 'latest', 'samples', 'samples_truncated'}
            or value['version'] != 'asterion.prime-provider-prefix-metrics/v1'
            or value['measurement'] != 'provider-hook-responses-input-json-utf8'
            or type(value['samples_truncated']) is not int
            or value['samples_truncated'] not in (0, 1)
            or type(value['samples']) is not list or len(value['samples']) > _MAX_SAMPLES):
        raise ValueError
    latest = _prefix_sample(value['latest'])
    previous = None
    for raw in value['samples']:
        current = _prefix_sample(raw)
        if previous is not None and (current['requests'] <= previous['requests']
                or current['peak_input_bytes'] < previous['peak_input_bytes']
                or current['unmeasurable_requests'] < previous['unmeasurable_requests']):
            raise ValueError
        previous = current
    if previous is not None and (latest['requests'] < previous['requests']
            or latest['peak_input_bytes'] < previous['peak_input_bytes']
            or latest['unmeasurable_requests'] < previous['unmeasurable_requests']):
        raise ValueError
    if not value['samples_truncated'] and (not value['samples'] or previous != latest):
        raise ValueError
    return value


class ProviderPrefixMetricsFile(ContextViewMetricsFile):
    """Owned numeric provider-hook prefix observations; no payload or hashes."""

    _validate = staticmethod(_validate_prefix)

    def __repr__(self) -> str:
        return '<ProviderPrefixMetricsFile redacted>'
