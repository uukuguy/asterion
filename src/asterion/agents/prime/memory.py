"""Private, immutable research text; the application owns the active pointer."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import secrets


_HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
_MAX_TEXT_BYTES = 16 * 1024
_MAX_RECORD_BYTES = 128 * 1024
_MAX_HISTORY = 16384


def _bytes(value):
    try:
        return json.dumps(value, allow_nan=False, ensure_ascii=False,
                          separators=(',', ':'), sort_keys=True).encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        raise ValueError('research memory invalid') from None


def _copy(value, *, limit=64 * 1024):
    def thaw(item, depth=0):
        if depth > 32:
            raise ValueError('research memory invalid')
        if isinstance(item, Mapping):
            if any(type(key) is not str for key in item):
                raise ValueError('research memory invalid')
            return {key: thaw(child, depth + 1) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(child, depth + 1) for child in item]
        if item is None or type(item) in (str, int, float, bool):
            return item
        raise ValueError('research memory invalid')
    result = thaw(value)
    if len(_bytes(result)) > limit:
        raise ValueError('research memory exceeds limit')
    return result


def _hash(value):
    return 'sha256:' + hashlib.sha256(_bytes(value)).hexdigest()


def _revision(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ValueError('research memory revision invalid')
    return value


class ResearchMemoryStore:
    """Content-addressed documents with opaque, application-attached metadata.

    Saving creates a document only. Applications commit a reference separately;
    history starts from that accepted reference and ignores orphan documents.
    """

    def __init__(self, *, root: Path, scope):
        self.root = Path(root)
        self._scope = _copy(scope)
        if self.root.is_symlink() or self.root.parent.is_symlink():
            raise ValueError('research memory root invalid')
        self.root.mkdir(parents=True, exist_ok=True)
        self._revisions = self.root / 'revisions'
        if self._revisions.is_symlink():
            raise ValueError('research memory root invalid')
        self._revisions.mkdir(exist_ok=True)

    def save(self, text, *, parent_revision=None, evidence_refs=()):
        if type(text) is not str or not text.strip():
            raise ValueError('research memory text invalid')
        try:
            size = len(text.encode('utf-8'))
        except UnicodeError:
            raise ValueError('research memory text invalid') from None
        if size > _MAX_TEXT_BYTES:
            raise ValueError('research memory text exceeds limit')
        if parent_revision is not None:
            self.read(parent_revision)
        refs = _copy(evidence_refs, limit=16 * 1024)
        if type(refs) is not list or len(refs) > 128:
            raise ValueError('research memory evidence invalid')
        record = {'parent_revision': parent_revision, 'scope': _copy(self._scope),
                  'text': text, 'evidence_refs': refs}
        revision = _hash(record)
        path = self._revisions / (revision[7:] + '.json')
        encoded = _bytes(record)
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ValueError('research memory exceeds limit')
        if path.exists() or path.is_symlink():
            return self.read(revision)
        temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {'revision': revision, **_copy(record, limit=_MAX_RECORD_BYTES)}

    def read(self, revision):
        revision = _revision(revision)
        path = self._revisions / (revision[7:] + '.json')
        if (self.root.is_symlink() or self._revisions.is_symlink() or path.is_symlink()
                or not path.is_file() or path.stat().st_size > _MAX_RECORD_BYTES):
            raise ValueError('research memory unavailable')
        try:
            record = json.loads(path.read_bytes())
        except (ValueError, UnicodeError):
            raise ValueError('research memory corrupt') from None
        if (type(record) is not dict
                or set(record) != {'parent_revision', 'scope', 'text', 'evidence_refs'}
                or _bytes(record['scope']) != _bytes(self._scope) or _hash(record) != revision
                or type(record['text']) is not str or not record['text'].strip()
                or len(record['text'].encode('utf-8')) > _MAX_TEXT_BYTES
                or type(record['evidence_refs']) is not list or len(record['evidence_refs']) > 128):
            raise ValueError('research memory corrupt')
        if record['parent_revision'] is not None:
            _revision(record['parent_revision'])
        _copy(record['scope'])
        _copy(record['evidence_refs'], limit=16 * 1024)
        return {'revision': revision, **_copy(record, limit=_MAX_RECORD_BYTES)}

    def history(self, revision, *, start=0, limit=16):
        if (type(start) is not int or not 0 <= start < _MAX_HISTORY
                or type(limit) is not int or not 1 <= limit <= 32):
            raise ValueError('research memory history invalid')
        rows, seen, index = [], set(), 0
        while revision is not None and index < start + limit:
            if revision in seen or len(seen) >= _MAX_HISTORY:
                raise ValueError('research memory ancestry invalid')
            seen.add(revision)
            record = self.read(revision)
            if index >= start:
                rows.append(record)
            revision = record['parent_revision']
            index += 1
        return {'items': rows, 'start': start, 'next_start': start + len(rows),
                'has_more': revision is not None}
