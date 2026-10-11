"""Operator-owned, public-safe presentation of typed resource observations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
import json
import os
from pathlib import Path
from types import MappingProxyType

from asterion.services.diagnostics import DiagnosticSink, FailureDiagnostic, LimitDiagnostic

_CONFIGURATION = MappingProxyType({
    'witness-frame-limit': 'PrimeCompactionPolicy.max_frame_bytes',
    'summarization-material-limit': 'PrimeCompactionPolicy.max_material_bytes',
    'compaction-token-limit': 'PrimeCompactionPolicy.max_total_tokens',
    'compaction-cost-limit': 'SessionContextCommand.payload.budget.cost_micros',
    'compaction-input-bound-unavailable': 'PrimeCompactionPolicy.max_total_tokens',
    'prime-session-token-limit': 'PrimeBackendSpec.aggregate_tokens',
    'prime-session-cost-limit': 'PrimeBackendSpec.cost_micros',
    'prime-parent-token-limit': 'RemainingBudget.controller_tokens/aggregate_tokens',
    'prime-parent-cost-limit': 'RemainingBudget.cost_micros',
    'compaction-callback-limit': 'AsterionPrimeLimits.model_callbacks',
    'prime-model-callback-limit': 'AsterionPrimeLimits.model_callbacks',
    'prime-tool-callback-limit': 'AsterionPrimeLimits.tool_callbacks',
    'compaction-deadline': 'SessionContextCommand.payload.budget.deadline_ms',
    'prime-deadline': 'AsterionPrimeLimits.deadline_ms',
    'ipython-output-limit': 'KernelLimits.max_output_bytes',
})


def resource_alarm(diagnostic: FailureDiagnostic) -> dict[str, object] | None:
    """Return a closed projection; identifiers and exception bodies stay private."""
    if type(diagnostic) is not FailureDiagnostic:
        raise ValueError('failure diagnostic is invalid')
    limit = diagnostic.limit_diagnostic
    if limit is None:
        return None
    if type(limit) is not LimitDiagnostic:
        raise ValueError('limit diagnostic is invalid')
    # Revalidate exact records as FailureDiagnostic itself is intentionally a
    # legacy-compatible container, rather than a validation boundary.
    LimitDiagnostic(**asdict(limit))
    if (type(diagnostic.diagnostic_id) is not str or len(diagnostic.diagnostic_id) != 32
            or any(character not in '0123456789abcdef' for character in diagnostic.diagnostic_id)
            or type(diagnostic.subject_sha256) is not str or len(diagnostic.subject_sha256) != 64
            or any(character not in '0123456789abcdef' for character in diagnostic.subject_sha256)):
        raise ValueError('failure diagnostic is invalid')
    return _alarm_projection(diagnostic.diagnostic_id, limit)


def _alarm_projection(diagnostic_id: str, limit: LimitDiagnostic) -> dict[str, object] | None:
    if (type(diagnostic_id) is not str or len(diagnostic_id) != 32
            or any(character not in '0123456789abcdef' for character in diagnostic_id)):
        raise ValueError('failure diagnostic is invalid')
    configuration = _CONFIGURATION.get(limit.limit_code)
    if configuration is None:
        # Context memory/archive unit and capacity mapping is a separate scope.
        return None
    if limit.limit_code == 'compaction-token-limit' and limit.config_source == 'authority':
        configuration = 'SessionContextCommand.payload.budget.controller_tokens/aggregate_tokens'
    if limit.limit_code == 'prime-deadline' and limit.config_source == 'authority':
        configuration = 'RunRequest.deadline_ms'
    return {
        'type': 'resource-limit', 'diagnostic_id': diagnostic_id,
        'limit_code': limit.limit_code, 'configuration': configuration,
        'phase': limit.phase, 'observed': limit.observed, 'limit': limit.limit,
        'unit': limit.unit, 'measurement': limit.measurement,
        'config_source': limit.config_source, 'outcome': limit.action,
    }


_ALARM_FIELDS = frozenset({'type', 'diagnostic_id', 'limit_code', 'configuration',
    'phase', 'observed', 'limit', 'unit', 'measurement', 'config_source', 'outcome'})


def public_resource_alarms(value: object) -> list[dict[str, object]]:
    """Revalidate retained alarm evidence at a public serialization boundary."""
    if type(value) not in {list, tuple}:
        return []
    safe = []
    for item in value:
        if type(item) not in {dict, MappingProxyType} or set(item) != _ALARM_FIELDS:
            continue
        try:
            limit = LimitDiagnostic(item['limit_code'], item['phase'], item['outcome'],
                item['observed'], item['limit'], item['unit'], item['measurement'], item['config_source'])
            projected = _alarm_projection(item['diagnostic_id'], limit)
        except (ValueError, TypeError):
            continue
        if (projected is not None and type(item['type']) is str
                and item['type'] == 'resource-limit' and type(item['configuration']) is str
                and item['configuration'] == projected['configuration']):
            safe.append(projected)
    return safe


class ResourceAlarmSink:
    """Retain each operation/code once and isolate all optional delivery failures."""
    def __init__(self, path: Path, *, emit: Callable[[dict[str, object]], None],
                 downstream: DiagnosticSink | None = None) -> None:
        self._path = path
        self._emit = emit
        self._downstream = downstream
        self._records: dict[str, FailureDiagnostic] = {}
        self._alarms: list[Mapping[str, object]] = []
        self._seen: set[tuple[str, object]] = set()

    @property
    def alarms(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._alarms)

    def get(self, diagnostic_id: str) -> FailureDiagnostic:
        return self._records[diagnostic_id]

    def record(self, diagnostic: FailureDiagnostic) -> None:
        alarm = resource_alarm(diagnostic)
        self._records[diagnostic.diagnostic_id] = diagnostic
        if alarm is not None:
            key = (diagnostic.subject_sha256, alarm['limit_code'])
            if key in self._seen:
                return
            self._seen.add(key)
            self._alarms.append(MappingProxyType(dict(alarm)))
        if self._downstream is not None:
            try:
                self._downstream.record(diagnostic)
            except Exception:
                pass
        if alarm is None:
            return
        try:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                encoded = (json.dumps(alarm, allow_nan=False, sort_keys=True,
                                      separators=(',', ':')) + '\n').encode('utf-8')
                with os.fdopen(descriptor, 'ab', closefd=False) as stream:
                    stream.write(encoded)
            finally:
                os.close(descriptor)
        except Exception:
            pass
        try:
            self._emit(dict(alarm))
        except Exception:
            pass


__all__ = ('ResourceAlarmSink', 'resource_alarm', 'public_resource_alarms')
