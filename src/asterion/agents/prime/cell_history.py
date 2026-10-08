"""Bounded, private computation records; reading never executes saved code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock


class CellHistoryError(ValueError):
    def __init__(self):
        super().__init__('Computation history unavailable')


class CellHistory:
    def __init__(self, workspace: Path, *, source_limit: int, output_limit: int,
                 max_records: int, max_bytes: int):
        self.root = workspace / 'cells'
        self.source_limit, self.output_limit = source_limit, output_limit
        self.max_records, self.max_bytes = max_records, max_bytes
        self.record_limit = 6 * (source_limit + output_limit) + 8192
        self._lock = RLock()
        self._items = None
        self._bytes = 0

    @staticmethod
    def _metadata(value):
        return {key: item for key, item in value.items() if key not in {'source', 'output'}}

    def _check_root(self):
        if self.root.parent.is_symlink() or self.root.is_symlink():
            raise CellHistoryError()

    def _load(self, cell_id):
        if type(cell_id) is not str or re.fullmatch(r'cell:[0-9a-f]{64}', cell_id) is None:
            raise CellHistoryError()
        self._check_root()
        descriptor = os.open(self.root / (cell_id[5:] + '.json'), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            raw = stream.read(self.record_limit + 1)
        if len(raw) > self.record_limit:
            raise CellHistoryError()
        value = json.loads(raw)
        if (type(value) is not dict or value.get('cell_id') != cell_id
                or type(value.get('ordinal')) is not int
                or type(value.get('source')) is not str
                or value.get('output') is not None and type(value['output']) is not str
                or len(value['source'].encode()) > self.source_limit
                or len((value.get('output') or '').encode()) > self.output_limit):
            raise CellHistoryError()
        return value

    def _initialize(self):
        self._check_root()
        if self._items is not None:
            return
        items = []
        size = 0
        if self.root.exists():
            for path in self.root.iterdir():
                if path.suffix != '.json':
                    continue
                if len(items) >= self.max_records:
                    raise CellHistoryError()
                value = self._load('cell:' + path.stem)
                items.append(self._metadata(value))
                size += path.stat().st_size
                if size > self.max_bytes:
                    raise CellHistoryError()
        items.sort(key=lambda item: item['ordinal'])
        if [item['ordinal'] for item in items] != list(range(len(items))):
            raise CellHistoryError()
        self._items, self._bytes = items, size

    def _write(self, value):
        self._check_root()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(encoded) > self.record_limit:
            raise CellHistoryError()
        path = self.root / (value['cell_id'][5:] + '.json')
        if path.is_symlink():
            raise CellHistoryError()
        previous = path.stat().st_size if path.exists() else 0
        if self._bytes - previous + len(encoded) > self.max_bytes:
            raise CellHistoryError()
        descriptor, temporary = tempfile.mkstemp(prefix='.cell-', dir=self.root)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._bytes += len(encoded) - previous
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            # Replace may have succeeded before a final fsync error. Reload the
            # actual directory on the next access, never reuse a stale catalog.
            self._items = None
            raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def begin(self, generation, call_id, source):
        with self._lock:
            self._initialize()
            if (len(self._items) >= self.max_records
                    or self._bytes + self.record_limit > self.max_bytes):
                raise CellHistoryError()
            cell_id = 'cell:' + hashlib.sha256(json.dumps([generation, call_id]).encode()).hexdigest()
            if any(item['cell_id'] == cell_id for item in self._items):
                raise CellHistoryError()
            value = dict(cell_id=cell_id, ordinal=len(self._items), generation=generation,
                         status='pending', source=source, source_bytes=len(source.encode()),
                         source_truncated=False, output=None, output_bytes=0,
                         output_available=False, output_truncated=False, export_ids=[])
            self._write(value)
            self._items.append(self._metadata(value))
            return cell_id

    def finish(self, cell_id, status, output=None, *, output_truncated=False, export_ids=()):
        with self._lock:
            self._initialize()
            value = self._load(cell_id)
            value.update(status=status, output=output, output_available=output is not None,
                         output_bytes=len(output.encode()) if output is not None else 0,
                         output_truncated=output_truncated, export_ids=list(export_ids))
            self._write(value)
            self._items[value['ordinal']] = self._metadata(value)

    def history(self, start=0, limit=16):
        with self._lock:
            if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 64:
                raise CellHistoryError()
            self._initialize()
            items = self._items[start:start + limit]
            return json.loads(json.dumps(dict(items=items, start=start, total=len(self._items),
                next_start=start + len(items) if start + len(items) < len(self._items) else None)))

    def read(self, cell_id, field='source', start=0, limit=4096):
        with self._lock:
            if (field not in {'source', 'output'} or type(start) is not int or start < 0
                    or type(limit) is not int or not 1 <= limit <= 16384):
                raise CellHistoryError()
            self._initialize()
            value = self._load(cell_id)
            if not any(item['cell_id'] == cell_id for item in self._items):
                raise CellHistoryError()
            content = value[field]
            length = len(content) if content is not None else 0
            text = content[start:start + limit] if content is not None else None
            return {**self._metadata(value), 'field': field, 'text': text, 'start': start,
                    'total_characters': length, 'next_start': start + len(text)
                    if text is not None and start + len(text) < length else None}
