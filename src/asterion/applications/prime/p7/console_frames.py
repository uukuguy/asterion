"""Application-owned replay frame bindings over the shared animation arena.

Descriptors contain one span per observation, never one record per animation
frame. Public tokens bind a selected run and level; they grant no game action.
"""
from bisect import bisect_right
from hashlib import sha256
import json
from pathlib import Path
import re

from .dynamic_evidence import AnimationFrames, EvidenceProcessingError
from .run_story.storage import write_atomic_file
from .score import canonical_bytes
from .processing_diagnostics import public_diagnostic

_TOKEN = re.compile(r'[0-9a-f]{64}\Z')
_PAGE_LIMIT = 32
_PAGE_BYTES = 1024 * 1024
_DESCRIPTOR_BYTES = 1024 * 1024


def _safe(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('replay frame unavailable')
    return path


class FrameStore:
    def __init__(self, root: Path, level: int):
        self.root, self.level = root, level
        self.spans, self.count = [], 0
        self.diagnostics = []

    def failure(self, error):
        value = (dict(error.diagnostic) if isinstance(error, EvidenceProcessingError) else
                 dict(code='derived-projection-failed', observed=None, limit=None, unit=None))
        value.update(diagnostic_id=f"{value['code']}:derived-failed:0", severity='warning',
                     stage='derived-failed', action_sequence=0, outcome_known=True,
                     durable=False, recovery='read-only-rebuild')
        self.diagnostics.append(public_diagnostic(value))

    def append_animation(self, frames, metadata, first_id):
        handle = AnimationFrames.capture(frames)
        try:
            reference = handle.persist(self.root / 'animation-evidence')
        except EvidenceProcessingError as error:
            self.failure(error)
            reference = handle.reference()
        self.spans.append(dict(start=self.count, count=len(handle), first_id=first_id,
                               animation_ref=reference, metadata=dict(metadata)))
        self.count += len(handle)

    def append(self, frame):
        self.append_animation([frame['grid']], {k: v for k, v in frame.items() if k not in {'id', 'grid'}},
                              int(frame['id'][1:]))

    def __len__(self):
        return self.count

    def finish(self):
        descriptor = dict(schema='asterion.arc-agi3-p7-replay-frames/v1', run_id=self.root.name,
                          level=self.level, frame_count=self.count, spans=self.spans)
        raw = canonical_bytes(descriptor)
        if len(raw) > _DESCRIPTOR_BYTES:
            raise EvidenceProcessingError('derived-projection-failed', stage='derived-failed',
                                          durable=True, observed=len(raw), limit=_DESCRIPTOR_BYTES,
                                          unit='bytes', recovery='read-only-rebuild')
        token = sha256(raw).hexdigest()
        try:
            directory = _safe(self.root / 'console-frame-evidence')
            directory.mkdir(parents=True, exist_ok=True)
            write_atomic_file(_safe(directory / (token + '.json')), raw)
        except (OSError, ValueError) as error:
            self.failure(error)
        return token


def frame_page(root, level, revision, token, start, limit):
    """Read a bounded page through a server-selected, content-bound descriptor."""
    if (type(token) is not str or not _TOKEN.fullmatch(token)
            or type(start) is not int or start < 0 or type(limit) is not int
            or not 1 <= limit <= _PAGE_LIMIT):
        raise ValueError('replay frame unavailable')
    if root.is_symlink():
        raise ValueError('replay frame unavailable')
    root = root.resolve()
    path = _safe(root / 'console-frame-evidence' / (token + '.json'))
    if not path.is_file() or path.stat().st_size > _DESCRIPTOR_BYTES:
        raise ValueError('replay frame unavailable')
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != token:
        raise ValueError('replay frame unavailable')
    value = json.loads(raw)
    if (value.get('schema') != 'asterion.arc-agi3-p7-replay-frames/v1'
            or value.get('run_id') != root.name or value.get('level') != level
            or type(value.get('frame_count')) is not int
            or not 0 <= start < value['frame_count'] or type(value.get('spans')) is not list):
        raise ValueError('replay frame unavailable')
    spans = value['spans']
    position = max(0, bisect_right([span['start'] for span in spans], start) - 1)
    frames, cells = [], 0
    for span in spans[position:]:
        end = min(span['start'] + span['count'], start + limit, value['frame_count'])
        if end <= start:
            continue
        handle = AnimationFrames.open(root / 'animation-evidence', span['animation_ref'], verify_full=False)
        for index in range(max(start, span['start']), end):
            grid = handle[index - span['start']]
            size = sum(len(row) for row in grid)
            if cells + size > 262144:
                break
            frame = dict(span['metadata'], id=f"f{span['first_id'] + index - span['start']:06d}",
                         index=index, grid=[list(row) for row in grid])
            frames.append(frame)
            cells += size
        if len(frames) >= limit or cells >= 262144:
            break
    result = dict(schema='asterion.arc-agi3-p7-replay-frame-page/v1', run_id=root.name,
                  level=level, replay_revision=revision, source_token=token,
                  frame_count=value['frame_count'], start=start, frames=frames)
    if len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()) > _PAGE_BYTES:
        raise ValueError('replay frame unavailable')
    return result
