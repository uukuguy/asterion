"""Independent, lossless animation storage with bounded I/O buffers.

There is deliberately no animation-total quota. The SDK may already have
materialized a reply; this store removes downstream copies and retained arrays,
not that native peak. References describe evidence, never execution authority.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time

from .score import canonical_bytes

_CHUNK = 64 * 1024
_PAGE_CELLS = 262_144
_INDEX = struct.Struct('!QQQQ')  # byte offset, byte length, height, width
_SCHEMA = 'asterion.prime.p7-animation/v1'
_CODES = frozenset({'evidence-write-failed', 'evidence-read-failed', 'evidence-hash-failed',
                   'observation-validation-failed', 'engine-no-reply', 'engine-response-invalid',
                   'derived-projection-failed', 'evidence-cancelled', 'evidence-deadline-exceeded'})


class ArcBrokerError(RuntimeError):
    """Public-safe native broker failure."""


class EvidenceProcessingError(ArcBrokerError):
    """A safe processing failure whose action outcome classification is explicit."""
    def __init__(self, code, *, stage='validated-not-durable', action_sequence=0,
                 outcome_known=True, durable=False, observed=None, limit=None,
                 unit=None, recovery='stop-without-redispatch'):
        if code not in _CODES:
            raise ValueError('processing code unavailable')
        from .processing_diagnostics import public_diagnostic
        self.diagnostic = public_diagnostic(dict(
            diagnostic_id=f'{code}:{stage}:{action_sequence}', code=code, severity='error',
            stage=stage, action_sequence=action_sequence, outcome_known=outcome_known,
            durable=durable, observed=observed, limit=limit, unit=unit, recovery=recovery))
        self.stage, self.outcome_known, self.durable = stage, outcome_known, durable
        super().__init__("uncertain" if code == "engine-no-reply" else code)

    def at_action(self, sequence, *, stage=None, outcome_known=None, durable=None):
        values = {key: value for key, value in self.diagnostic.items()
                  if key not in {'diagnostic_id', 'severity', 'code'}}
        values['action_sequence'] = sequence
        if stage is not None:
            values['stage'] = stage
        if outcome_known is not None:
            values['outcome_known'] = outcome_known
        if durable is not None:
            values['durable'] = durable
        return type(self)(self.diagnostic['code'], **values)


def file_sha256(path: Path) -> str:
    result = sha256()
    with path.open('rb') as source:
        while data := source.read(_CHUNK):
            result.update(data)
    return result.hexdigest()


def _safe(root: Path) -> Path:
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError('animation evidence unavailable')
    return root


def _put_node(root, raw):
    token = sha256(raw).hexdigest()
    path = root / 'nodes' / token
    if not path.exists():
        with path.open('wb') as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
    return bytes.fromhex(token)


def _tree(root, source_path, check=lambda: None):
    """Build a Merkle tree using a disk frontier, not a growing Python list."""
    (root / 'nodes').mkdir(exist_ok=True)
    frontier = root / 'frontier'
    count = 0
    with source_path.open('rb') as source, frontier.open('wb') as index:
        while raw := source.read(_CHUNK):
            check()
            index.write(_put_node(root, b'L' + raw))
            count += 1
    if not count:
        raise ValueError('empty evidence unavailable')
    while count > 1:
        following = root / 'following'
        with frontier.open('rb') as source, following.open('wb') as target:
            while left := source.read(32):
                check()
                right = source.read(32) or left
                target.write(_put_node(root, b'N' + left + right))
        os.replace(following, frontier)
        count = (count + 1) // 2
    result = frontier.read_bytes().hex()
    frontier.unlink()
    return result


def _tree_page(root, token, size, number):
    pages = (size + _CHUNK - 1) // _CHUNK
    if not 0 <= number < pages:
        raise ValueError('evidence page unavailable')
    depth = (pages - 1).bit_length()
    for level in range(depth, -1, -1):
        path = _safe(root / 'nodes' / token)
        with path.open('rb') as source:
            raw = source.read(_CHUNK + 2)
        if sha256(raw).hexdigest() != token:
            raise ValueError('evidence checksum unavailable')
        if level:
            if len(raw) != 65 or raw[:1] != b'N':
                raise ValueError('evidence index unavailable')
            offset = 1 + 32 * ((number >> (level - 1)) & 1)
            token = raw[offset:offset + 32].hex()
        else:
            expected = min(_CHUNK, size - number * _CHUNK)
            if raw[:1] != b'L' or len(raw) != expected + 1:
                raise ValueError('evidence page unavailable')
            return raw[1:]
    raise ValueError('evidence page unavailable')


class _TemporaryArena:
    def __init__(self):
        self.name = tempfile.mkdtemp(prefix='asterion-animation-')

    def cleanup(self):
        shutil.rmtree(self.name, ignore_errors=True)


class AnimationFrames(Sequence):
    """Immutable sequence backed by canonical bytes and a fixed-record disk index.

    The index grows on disk, never as an in-memory descriptor array. Reads verify
    independently checksummed fixed-size chunks. A page's expansion budget is
    separate from the unrestricted evidence volume.
    """
    __slots__ = ('_root', '_temporary', '_reference', '_durable', '_cancelled', '_deadline')

    def __init__(self, root, reference, temporary=None, *, cancelled=None, deadline=None):
        self._root, self._temporary, self._reference = root, temporary, reference
        self._durable = temporary is None
        self._cancelled, self._deadline = cancelled, deadline

    def __del__(self):
        temporary = getattr(self, '_temporary', None)
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass  # process teardown cannot publish a new diagnostic

    @classmethod
    def capture(cls, frames: Iterable, *, cancelled=None, deadline=None):
        if type(frames) is cls:
            return frames
        validated = False
        def check():
            code = ('evidence-cancelled' if cancelled is not None and cancelled() else
                    'evidence-deadline-exceeded' if deadline is not None and time.monotonic() >= deadline else None)
            if code:
                raise EvidenceProcessingError(code, stage='validated-not-durable' if validated else 'reply-received-unvalidated', outcome_known=validated)
        check()
        try:
            temporary = _TemporaryArena()
        except OSError:
            raise EvidenceProcessingError('evidence-write-failed', stage='reply-received-unvalidated', outcome_known=False) from None
        root = Path(temporary.name).resolve()
        hasher, count, cells, offset = sha256(), 0, 0, 0
        try:
            with (root / 'frames').open('wb') as data, (root / 'index').open('wb') as index:
                def emit(value):
                    nonlocal offset
                    check()
                    # The writer has at most one fixed buffer plus the caller's
                    # row. No complete frame/animation JSON is constructed.
                    for start in range(0, len(value), _CHUNK):
                        part = value[start:start + _CHUNK]
                        data.write(part)
                        hasher.update(part)
                        offset += len(part)
                emit(b'[')
                dimensions = None
                for frame in frames:
                    if count:
                        emit(b',')
                    begin, height, width = offset, 0, None
                    emit(b'[')
                    for row in frame:
                        if hasattr(row, 'tolist'):
                            row = row.tolist()
                        if height:
                            emit(b',')
                        emit(b'[')
                        row_width, values = 0, []
                        for cell in row:
                            if type(cell) is not int or not 0 <= cell <= 255:
                                raise ValueError
                            values.append(cell)
                            if len(values) == 8192:
                                if row_width:
                                    emit(b',')
                                emit(canonical_bytes(values)[1:-1])
                                row_width += len(values)
                                values.clear()
                        if values:
                            if row_width:
                                emit(b',')
                            emit(canonical_bytes(values)[1:-1])
                            row_width += len(values)
                        if not row_width:
                            raise ValueError
                        if width is None:
                            width = row_width
                        elif width != row_width:
                            raise ValueError
                        emit(b']')
                        height += 1
                    if not height or not width:
                        raise ValueError
                    if dimensions is None:
                        dimensions = (height, width)
                    if dimensions != (height, width):
                        raise ValueError
                    emit(b']')
                    index.write(_INDEX.pack(begin, offset - begin, height, width))
                    count += 1
                    cells += height * width
                if not count:
                    raise ValueError
                validated = True
                emit(b']')
                for target in (data, index):
                    target.flush()
                    os.fsync(target.fileno())
            reference = dict(schema=_SCHEMA, sha256='sha256:' + hasher.hexdigest(),
                             frame_count=count, cell_count=cells, byte_count=offset,
                             index_sha256=file_sha256(root / 'index'),
                             frames_root_sha256=_tree(root, root / 'frames', check),
                             index_root_sha256=_tree(root, root / 'index', check))
            for name in ('frames', 'index'):
                (root / name).unlink()
            return cls(root, reference, temporary)
        except EvidenceProcessingError:
            temporary.cleanup()
            raise
        except (OSError, MemoryError):
            temporary.cleanup()
            raise EvidenceProcessingError('evidence-write-failed', stage='validated-not-durable' if validated else 'reply-received-unvalidated', outcome_known=validated) from None
        except (ValueError, TypeError):
            temporary.cleanup()
            raise EvidenceProcessingError('observation-validation-failed',
                                          stage='reply-received-invalid', outcome_known=False) from None

    @property
    def durable(self):
        return self._durable

    def reference(self):
        return dict(self._reference)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        # Copying an immutable handle must never duplicate temporary ownership.
        memo[id(self)] = self
        return self

    def __repr__(self):
        return f'AnimationFrames(frame_count={len(self)})'

    def __len__(self):
        return self._reference['frame_count']

    def _check_control(self):
        if self._cancelled is not None and self._cancelled():
            raise self._failure('evidence-cancelled')
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise self._failure('evidence-deadline-exceeded')

    def _failure(self, code, **measurements):
        return EvidenceProcessingError(code, stage='derived-failed',
                                       durable=self._durable, **measurements)

    def _record(self, number):
        self._check_control()
        if number < 0:
            number += len(self)
        if not 0 <= number < len(self):
            raise IndexError(number)
        try:
            offset = number * _INDEX.size
            raw = _tree_page(self._root, self._reference['index_root_sha256'],
                             len(self) * _INDEX.size, offset // _CHUNK)
            within = offset % _CHUNK
            result = _INDEX.unpack(raw[within:within + _INDEX.size])
            start, size, height, width = result
            if (not height or not width or not size or start < 1
                    or start + size >= self._reference['byte_count']
                    or height * width > self._reference['cell_count']):
                raise ValueError
            return result
        except (OSError, ValueError, struct.error):
            raise self._failure('evidence-read-failed') from None

    def _bytes(self, start=0, size=None):
        size = self._reference['byte_count'] - start if size is None else size
        end = start + size
        try:
            for number in range(start // _CHUNK, (end + _CHUNK - 1) // _CHUNK):
                self._check_control()
                block = _tree_page(self._root, self._reference['frames_root_sha256'],
                                   self._reference['byte_count'], number)
                left, right = max(0, start - number * _CHUNK), min(len(block), end - number * _CHUNK)
                yield block[left:right]
        except (OSError, ValueError, MemoryError):
            raise self._failure('evidence-read-failed') from None

    def canonical_chunks(self):
        """Yield the original JSON array bytes with bounded buffers."""
        yield from self._bytes()

    def __getitem__(self, number):
        if isinstance(number, slice):
            indices = range(*number.indices(len(self)))
            if len(indices) > 64:
                raise self._failure('derived-projection-failed',
                                              observed=len(indices), limit=64, unit='frames')
            cells = sum(self._record(index)[2] * self._record(index)[3] for index in indices)
            if cells > _PAGE_CELLS:
                raise self._failure('derived-projection-failed', observed=cells, limit=_PAGE_CELLS, unit='cells')
            return tuple(self[index] for index in indices)
        try:
            start, size, height, width = self._record(number)
            if height * width > _PAGE_CELLS:
                raise self._failure('derived-projection-failed',
                                              observed=height * width, limit=_PAGE_CELLS, unit='cells')
            frame = json.loads(b''.join(self._bytes(start, size)))
            return tuple(tuple(row) for row in frame)
        except (OSError, ValueError, struct.error):
            raise self._failure('evidence-read-failed') from None

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def __eq__(self, other):
        if not isinstance(other, Sequence) or len(self) != len(other):
            return False
        return all(left == right for left, right in zip(self, other))

    def page(self, start, limit=1):
        if type(start) is not int or type(limit) is not int or start < 0 or not 1 <= limit <= 64:
            raise ValueError('animation page unavailable')
        indices = range(start, min(start + limit, len(self)))
        cells = sum(self._record(index)[2] * self._record(index)[3] for index in indices)
        if cells > _PAGE_CELLS:
            raise self._failure('derived-projection-failed',
                                          observed=cells, limit=_PAGE_CELLS, unit='cells')
        return [self[index] for index in indices]

    def persist(self, root: Path, *, cancelled=None, deadline=None):
        """Commit an immutable object before its reference is published.

        The caller owns retention. Temporary captures are removed automatically
        when the last handle is released; committed objects are never GC'd here.
        """
        def check():
            if cancelled is not None and cancelled():
                raise EvidenceProcessingError('evidence-cancelled')
            if deadline is not None and time.monotonic() >= deadline:
                raise EvidenceProcessingError('evidence-deadline-exceeded')
        check()
        root = _safe(Path(root))
        target = root / self._reference['sha256'][7:]
        try:
            root.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with tempfile.TemporaryDirectory(prefix='.stage-', dir=root) as stage:
                    stage = Path(stage)
                    (stage / 'nodes').mkdir()
                    with os.scandir(self._root / 'nodes') as entries:
                        for entry in entries:
                            check()
                            with _safe(Path(entry.path)).open('rb') as source, (stage / 'nodes' / entry.name).open('wb') as dest:
                                shutil.copyfileobj(source, dest, _CHUNK)
                                dest.flush()
                                os.fsync(dest.fileno())
                    with (stage / 'manifest.json').open('wb') as dest:
                        dest.write(canonical_bytes(self._reference))
                        dest.flush()
                        os.fsync(dest.fileno())
                    for directory in (stage / 'nodes', stage):
                        fd = os.open(directory, os.O_RDONLY)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                    os.rename(stage, target)
                    fd = os.open(root, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            # Validate an existing object too; never adopt conflicting bytes.
            self.open(root, self._reference, verify_full=True, cancelled=cancelled, deadline=deadline)
            temporary = self._temporary
            self._root, self._temporary, self._durable = target, None, True
            if temporary is not None:
                temporary.cleanup()
            return self.reference()
        except (OSError, ValueError):
            raise EvidenceProcessingError('evidence-write-failed') from None

    @classmethod
    def open(cls, root: Path, reference, *, cancelled=None, deadline=None, verify_full=True):
        """Open only a caller-authenticated content reference under an owned root."""
        import re
        if (type(reference) is not dict or reference.get('schema') != _SCHEMA
                or type(reference.get('sha256')) is not str
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', reference['sha256'])):
            raise ValueError('animation reference unavailable')
        target = _safe(Path(root) / reference['sha256'][7:])
        try:
            manifest = _safe(target / 'manifest.json')
            if manifest.stat().st_size > 4096:
                raise ValueError
            value = json.loads(manifest.read_bytes())
            if value != reference or set(value) != {'schema', 'sha256', 'frame_count', 'cell_count', 'byte_count', 'index_sha256', 'frames_root_sha256', 'index_root_sha256'}:
                raise ValueError
            for key in ('frame_count', 'cell_count', 'byte_count'):
                if type(value[key]) is not int or value[key] < 1:
                    raise ValueError
            for key in ('index_sha256', 'frames_root_sha256', 'index_root_sha256'):
                if type(value[key]) is not str or not re.fullmatch(r'[0-9a-f]{64}', value[key]):
                    raise ValueError
            handle = cls(target, dict(value), cancelled=cancelled, deadline=deadline)
            # A caller-authenticated descriptor anchors the Merkle roots.
            # Paged consumers verify only touched nodes; full admission and
            # publication request the complete legacy byte hash explicitly.
            if verify_full:
                full = sha256()
                for chunk in handle.canonical_chunks():
                    full.update(chunk)
                if 'sha256:' + full.hexdigest() != value['sha256']:
                    raise ValueError
                index_hash = sha256()
                size = len(handle) * _INDEX.size
                for number in range((size + _CHUNK - 1) // _CHUNK):
                    index_hash.update(_tree_page(target, value['index_root_sha256'], size, number))
                if index_hash.hexdigest() != value['index_sha256']:
                    raise ValueError
            return handle
        except (OSError, ValueError, TypeError):
            raise EvidenceProcessingError('evidence-read-failed', stage='derived-failed', durable=True) from None


def observation_digest(projection: dict, frames) -> str:
    """Hash exactly legacy canonical JSON, substituting only its frame stream."""
    hasher = sha256()
    hasher.update(b'{')
    for index, key in enumerate(sorted(projection)):
        if index:
            hasher.update(b',')
        hasher.update(canonical_bytes(key))
        hasher.update(b':')
        if key == 'frame' and isinstance(frames, AnimationFrames):
            for chunk in frames.canonical_chunks():
                hasher.update(chunk)
        else:
            hasher.update(canonical_bytes(frames if key == 'frame' else projection[key]))
    hasher.update(b'}')
    return 'sha256:' + hasher.hexdigest()
