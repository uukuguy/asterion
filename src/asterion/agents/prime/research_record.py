"""Private bounded relationships between statements and actual research evidence.

Applications assign meaning to opaque references. Chronology does not establish
causal support, validate a statement, or reconstruct unexpressed model reasoning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from .memory import _bytes, _copy, _hash

_VERSION = 'asterion.prime-research-record/v1'
_MAX_RECORDS = 256
_MAX_REFS = 64
_MAX_FILE = 8 * 1024 * 1024
_MAX_RECORD = 128 * 1024


class ResearchRecordStore:
    """A passive relationship index; referenced source bodies remain elsewhere."""

    def __init__(self, *, path: Path, scope):
        self.path = Path(path)
        self._scope = _copy(scope)
        self._lock = RLock()
        self._check_path()
        self._value = dict(version=_VERSION, scope=self._scope, records=[],
                           omitted_records=0, omitted_refs=0)
        if self.path.exists():
            with self.path.open('rb') as stream:
                raw = stream.read(_MAX_FILE + 1)
            if len(raw) > _MAX_FILE:
                raise ValueError('research record unavailable')
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                raise ValueError('research record unavailable') from None
            if (type(value) is not dict or set(value) != set(self._value)
                    or value['version'] != _VERSION or value['scope'] != self._scope
                    or type(value['records']) is not list or len(value['records']) > _MAX_RECORDS
                    or any(type(value[key]) is not int or value[key] < 0
                           for key in ('omitted_records', 'omitted_refs'))):
                raise ValueError('research record unavailable')
            previous, keys = None, set()
            for record in value['records']:
                if type(record) is not dict:
                    raise ValueError('research record unavailable')
                body = {key: child for key, child in record.items() if key != 'record_id'}
                if (set(record) != {'record_id', 'key', 'kind', 'origin', 'statement',
                                   'evidence_refs', 'links', 'interpretation', 'causal_support'}
                        or record['record_id'] != _hash(body)
                        or type(record['key']) is not str
                        or record['key'] in keys
                        or type(record['origin']) is not str
                        or record['origin'] not in {'model_statement', 'behavioral_evidence'}
                        or record['interpretation'] != 'unclassified' or record['causal_support'] != 'unknown'
                        or type(record['evidence_refs']) is not list or len(record['evidence_refs']) > _MAX_REFS
                        or record['links'] != ([] if previous is None else
                            [{'relation': 'observed_after', 'record_id': previous}])
                        or len(_bytes(record)) > _MAX_RECORD):
                    raise ValueError('research record unavailable')
                keys.add(record['key'])
                previous = record['record_id']
            self._value = value

    def _check_path(self):
        if self.path.is_symlink() or any(parent.is_symlink() for parent in self.path.parents):
            raise ValueError('research record unavailable')

    def _save(self, value):
        self._check_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _bytes(value)
        if len(encoded) > _MAX_FILE:
            raise ValueError('research record exceeds limit')
        descriptor, temporary = tempfile.mkstemp(prefix='.research-record-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self._value = value

    def append(self, *, key, kind, origin, statement=None, evidence_refs=()):
        """Attach observed references, with only a temporal edge to the prior entry."""
        with self._lock:
            if (type(key) is not str or not key or len(key) > 256
                    or type(kind) is not str or not kind or len(kind) > 64
                    or origin not in {'model_statement', 'behavioral_evidence'}):
                raise ValueError('research record invalid')
            if any(record['key'] == key for record in self._value['records']):
                return
            value = _copy(self._value, limit=_MAX_FILE)
            if len(value['records']) >= _MAX_RECORDS:
                value['omitted_records'] += 1
                self._save(value)
                return
            refs = _copy(evidence_refs, limit=_MAX_RECORD)
            if type(refs) is not list:
                raise ValueError('research record references invalid')
            previous = value['records'][-1]['record_id'] if value['records'] else None
            body = dict(key=key, kind=kind, origin=origin,
                        statement=_copy(statement, limit=64 * 1024), evidence_refs=refs[:_MAX_REFS],
                        links=[] if previous is None else [{'relation': 'observed_after', 'record_id': previous}],
                        interpretation='unclassified', causal_support='unknown')
            record = dict(record_id=_hash(body), **body)
            if len(_bytes(record)) > _MAX_RECORD or len(_bytes(value)) + len(_bytes(record)) > _MAX_FILE - 1024:
                value['omitted_records'] += 1
            else:
                value['omitted_refs'] += max(0, len(refs) - _MAX_REFS)
                value['records'].append(record)
            self._save(value)

    def summary(self):
        with self._lock:
            return dict(record_count=len(self._value['records']),
                        omitted_record_count=self._value['omitted_records'],
                        omitted_reference_count=self._value['omitted_refs'])
