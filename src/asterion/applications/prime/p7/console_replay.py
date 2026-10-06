"""Application-local, bounded asynchronous projections of explicit replay sources."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import threading


_SCHEMA = 'asterion.arc-agi3-p7-replay-manifest/v1'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_REVISION = re.compile(r'[0-9a-f]{64}\Z')
_MAX_FILE = 32 * 1024 * 1024
_MAX_PATHS = 8192
_CACHE_BYTES = 128 * 1024 * 1024
_PROJECTOR = 'asterion.arc-agi3-p7-replay-projector/v1'


def replay_fingerprint(root: Path) -> tuple:
    """Stat the explicit dependency closure; this does not authenticate evidence.

    Missing paths and directory membership are dependencies too. Read only
    bounded metadata to discover links, leaving all source admission to the
    ordinary snapshot reader. Never follow a link or enumerate sibling runs.
    """
    stamps = {}
    complete = set()

    def stamp(path):
        if len(stamps) >= _MAX_PATHS and str(path) not in stamps:
            raise ValueError('replay unavailable')
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('replay unavailable')
        try:
            value = path.lstat()
        except FileNotFoundError:
            stamps[str(path)] = None
            return None
        if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode)):
            raise ValueError('replay unavailable')
        stamps[str(path)] = ((value.st_mode, value.st_dev, value.st_ino) if stat.S_ISDIR(value.st_mode)
                            else (value.st_mode, value.st_size, value.st_mtime_ns,
                                  value.st_ctime_ns, value.st_dev, value.st_ino))
        return value

    def metadata(path):
        value = stamp(path)
        if value is None:
            return {}
        if not stat.S_ISREG(value.st_mode) or value.st_size > _MAX_FILE:
            raise ValueError('replay unavailable')
        try:
            result = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError, RecursionError):
            return {}
        return result if type(result) is dict else {}

    def tree(path, depth):
        value = stamp(path)
        if value is None or not stat.S_ISDIR(value.st_mode):
            return
        # These trees contain only selected run recordings/research evidence.
        children = sorted(path.iterdir(), key=lambda child: child.name)
        if len(children) > _MAX_PATHS:
            raise ValueError('replay unavailable')
        for child in children:
            child_stat = stamp(child)
            if child_stat and stat.S_ISDIR(child_stat.st_mode):
                if depth <= 0:
                    raise ValueError('replay unavailable')
                tree(child, depth - 1)

    def link(value, links):
        if value is None:
            return
        if type(value) is not str or not _ID.fullmatch(value):
            raise ValueError('replay unavailable')
        links.add(value)

    def visit(run, ancestors):
        if run.name in ancestors or len(ancestors) >= 8:
            raise ValueError('replay unavailable')
        if run.name in complete:
            return
        stamp(run)
        summary = metadata(run / 'summary.json')
        diagnostics = summary.get('diagnostics', {})
        links = set()
        if type(diagnostics) is dict:
            link(diagnostics.get('source_run_id'), links)
            link(diagnostics.get('recovered_from'), links)
            segments = diagnostics.get('route_sources', [])
            if type(segments) is not list or len(segments) > 2:
                raise ValueError('replay unavailable')
            for segment in segments:
                if type(segment) is dict:
                    link(segment.get('source_run_id'), links)
        trace = run / 'trace' / 'prime-trace.jsonl'
        value = stamp(trace)
        if value is not None:
            if not stat.S_ISREG(value.st_mode) or value.st_size > _MAX_FILE:
                raise ValueError('replay unavailable')
            with trace.open('rb') as stream:
                for _ in range(4096):
                    row = stream.readline(_MAX_FILE + 1)
                    if len(row) > _MAX_FILE:
                        raise ValueError('replay unavailable')
                    if not row:
                        break
                    if b'arc.run.context' not in row:
                        continue
                    try:
                        context = json.loads(row)
                    except (ValueError, UnicodeError, RecursionError):
                        continue
                    if (type(context) is dict and context.get('kind') == 'arc.run.context'
                            and type(context.get('payload')) is dict):
                        link(context['payload'].get('source_run_id'), links)
        stamp(run / 'trace')
        stamp(run / 'trace' / 'prime-trace.seal.json')
        stamp(run / 'console-events.jsonl')
        for directory in ('recordings', 'replay-recordings', 'prefix-replay-recordings'):
            tree(run / directory, 1)
        tree(run / 'research', 2)
        stamp(run.parent / f'cognition-live-{run.name}-cognition.jsonl')
        stamp(run.parent / f'semantic-events-{run.name}-cognition.json')
        launch = metadata(run.parent / 'launches' / (run.name + '.json'))
        if not summary:
            link(launch.get('source_run_id'), links)
        for source in sorted(links):
            visit(run.parent / source, (*ancestors, run.name))
        complete.add(run.name)

    visit(root, ())
    return tuple(sorted(stamps.items()))


def _loading(run_id):
    return {'schema': _SCHEMA, 'state': 'loading', 'run_id': run_id,
            'revision': None, 'run': None, 'levels': [], 'warnings': []}


def projection_revision(fingerprint: tuple, content_sha256: str | None = None) -> str:
    return sha256((_PROJECTOR + repr(fingerprint) + (content_sha256 or '')).encode('utf-8')).hexdigest()


def projection_manifest(snapshot: dict, revision: str) -> dict:
    return {'schema': _SCHEMA, 'state': 'ready', 'run_id': snapshot['run']['run_id'],
            'revision': revision, 'run': snapshot['run'], 'warnings': snapshot.get('warnings', []),
            'levels': [{'level': level['level'], 'status': level['status'],
                        'frame_count': len(level.get('frames', [])),
                        'action_count': len(level.get('actions', [])),
                        'has_cognition': level.get('cognition', {}).get('scope') != 'unavailable'
                                        and bool(level.get('cognition'))}
                       for level in snapshot['levels']]}


def projection_level(snapshot: dict, number: int, revision: str) -> dict:
    bucket = next((level for level in snapshot['levels'] if level['level'] == number), None)
    if bucket is None:
        raise ValueError('replay unavailable')
    selected = {decision['id'] for decision in bucket.get('decisions', [])}
    selected.update(action.get('decision_id') for action in bucket.get('actions', []))
    frames = {frame['id'] for frame in bucket.get('frames', [])}
    return {**snapshot, 'levels': [bucket], 'replay_revision': revision,
            'decisions': [decision for decision in snapshot.get('decisions', [])
                          if decision['id'] in selected or 'round_index' in decision],
            'process_events': [event for event in snapshot.get('process_events', [])
                               if event.get('level') == number or event.get('frame_id') in frames]}


def _weight(snapshot):
    # Grid cells are usually shared small integers, but every cell holds an
    # eight-byte list reference. Wire bytes also cover container/prose overhead.
    cells = sum(len(row) for level in snapshot['levels'] for frame in level.get('frames', [])
                for row in frame['grid'])
    encoded = len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode('utf-8'))
    return cells * 8 + encoded * 2


class ReplayProjectionCache:
    """One worker, one replaceable pending selection, and four bounded revisions."""

    def __init__(self, reader: Callable, games: set[str]):
        self._reader, self._games = reader, games
        self._condition = threading.Condition()
        self._ready = OrderedDict()
        self._failed = None
        self._active = None
        self._active_foreground = False
        self._pending = None
        self._pending_foreground = False
        self._worker = None
        self._closed = False
        self._bytes = 0
        self._prepared_rejected = OrderedDict()

    def manifest(self, path: Path) -> dict:
        fingerprint = replay_fingerprint(path)
        with self._condition:
            if self._closed:
                raise ValueError('replay unavailable')
        from .console_prepared import read_prepared_manifest
        prepared = read_prepared_manifest(path, fingerprint)
        if prepared is not None and prepared['run']['game_id'] in self._games:
            with self._condition:
                if self._closed:
                    raise ValueError('replay unavailable')
                rejected = self._prepared_rejected.get(path.name) == (fingerprint, prepared['revision'])
            if not rejected:
                return prepared
        with self._condition:
            if self._closed:
                raise ValueError('replay unavailable')
            cached = self._ready.get(path.name)
            if cached and cached[0] == fingerprint:
                self._ready.move_to_end(path.name)
                return deepcopy(cached[2])
            if cached:
                self._bytes -= self._ready.pop(path.name)[3]
            if self._failed == (path.name, fingerprint):
                self._failed = None
                raise ValueError('replay unavailable')
            request = (path, fingerprint)
            if self._active == request:
                self._active_foreground = True
                if self._pending is not None and not self._pending_foreground:
                    self._pending = None
            else:
                self._schedule(request, foreground=True)
            return _loading(path.name)

    def _schedule(self, request, *, foreground):
        """Called only under the scheduling condition; the queue has one slot."""
        self._pending, self._pending_foreground = request, foreground
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, name='p7-console-replay', daemon=True)
            self._worker.start()
        self._condition.notify()

    def prewarm(self, path: Path) -> bool:
        """Opportunistically project one sealed saved source at low priority.

        Summary flags only admit work to the queue. The normal reader must
        still prove sealed, verified replay evidence before warm publication.
        An active pure read cannot be interrupted; no second worker is created.
        """
        with self._condition:
            if self._closed or (self._pending is not None and self._pending_foreground):
                return False
        try:
            summary_path = path / 'summary.json'
            if (any(part.is_symlink() for part in (summary_path, *summary_path.parents))
                    or not summary_path.is_file() or summary_path.stat().st_size > _MAX_FILE):
                return False
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            if (type(summary) is not dict
                    or summary.get('schema') != 'asterion.prime.p7-live-private-summary/v1'
                    or summary.get('run_id') != path.name
                    or any(summary.get(key) is not True for key in ('sealed_trace', 'replay_verified', 'cleanup_complete'))
                    or type(summary.get('experiment')) is not dict
                    or summary['experiment'].get('game_id') not in self._games):
                return False
            fingerprint = replay_fingerprint(path)
            from .console_prepared import read_prepared_manifest
            if read_prepared_manifest(path, fingerprint) is not None:
                return False
        except (OSError, ValueError, UnicodeError, RecursionError):
            return False
        with self._condition:
            if self._closed or (self._pending is not None and self._pending_foreground):
                return False
            cached = self._ready.get(path.name)
            if (cached and cached[0] == fingerprint) or self._active == (path, fingerprint):
                return False
            self._schedule((path, fingerprint), foreground=False)
            return True

    def level(self, path: Path, number: int, revision: str) -> dict:
        if type(number) is not int or not 1 <= number <= 100 or type(revision) is not str or not _REVISION.fullmatch(revision):
            raise ValueError('replay unavailable')
        fingerprint = replay_fingerprint(path)
        with self._condition:
            if self._closed:
                raise ValueError('replay unavailable')
            rejected = self._prepared_rejected.get(path.name) == (fingerprint, revision)
        if not rejected:
            from .console_prepared import read_prepared_level, read_prepared_manifest
            prepared = read_prepared_level(path, fingerprint, number, revision)
            if prepared is not None and prepared['run']['game_id'] in self._games:
                with self._condition:
                    if self._closed:
                        raise ValueError('replay unavailable')
                return prepared
            manifest = read_prepared_manifest(path, fingerprint)
            if manifest is not None and manifest['revision'] != revision:
                raise ValueError('replay stale')
            if manifest is not None and manifest['revision'] == revision:
                with self._condition:
                    self._prepared_rejected[path.name] = (fingerprint, revision)
                    while len(self._prepared_rejected) > 4:
                        self._prepared_rejected.popitem(last=False)
        with self._condition:
            if self._closed:
                raise ValueError('replay unavailable')
            cached = self._ready.get(path.name)
            if not cached or cached[0] != fingerprint or cached[2]['revision'] != revision:
                raise ValueError('replay stale')
            self._ready.move_to_end(path.name)
            snapshot = cached[1]
        # Entries are immutable after publication; copy only the requested
        # projection outside the scheduling lock.
        return deepcopy(projection_level(snapshot, number, revision))

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                path, fingerprint = self._pending
                self._active, self._pending = self._pending, None
                self._active_foreground = self._pending_foreground
            try:
                snapshot = self._reader(path)
                with self._condition:
                    if self._closed:
                        return
                    foreground = self._active_foreground
                if (type(snapshot) is not dict or type(snapshot.get('run')) is not dict
                        or snapshot['run'].get('run_id') != path.name
                        or snapshot['run'].get('game_id') not in self._games
                        or type(snapshot.get('levels')) is not list):
                    raise ValueError('replay unavailable')
                if (not foreground and (snapshot['run'].get('sealed_trace') is not True
                        or snapshot['run'].get('replay_verified') is not True
                        or type(snapshot['run'].get('completed_level_count')) is not int
                        or snapshot['run']['completed_level_count'] < 1)):
                    raise ValueError('replay unavailable')
                from .console_prepared import publish_prepared
                prepared = publish_prepared(path, snapshot, fingerprint)
                weight = _weight(snapshot)
                if weight > _CACHE_BYTES:
                    raise ValueError('replay unavailable')
                revision = prepared['revision'] if prepared is not None else projection_revision(fingerprint)
                manifest = prepared if prepared is not None else projection_manifest(snapshot, revision)
                # Copy an injected reader's result outside the scheduling lock.
                snapshot, manifest = deepcopy(snapshot), deepcopy(manifest)
                after = replay_fingerprint(path)
                with self._condition:
                    if self._closed:
                        return
                    if after == fingerprint:
                        old = self._ready.pop(path.name, None)
                        if old:
                            self._bytes -= old[3]
                        while self._ready and (len(self._ready) >= 4 or self._bytes + weight > _CACHE_BYTES):
                            self._bytes -= self._ready.popitem(last=False)[1][3]
                        self._ready[path.name] = (fingerprint, snapshot, manifest, weight)
                        self._bytes += weight
                    elif self._pending is None:
                        self._pending = (path, after)
                        self._pending_foreground = self._active_foreground
            except Exception:
                with self._condition:
                    if not self._closed and self._active_foreground:
                        self._failed = (path.name, fingerprint)
            finally:
                with self._condition:
                    self._active = None
                    self._active_foreground = False

    def close(self) -> bool:
        with self._condition:
            self._closed = True
            self._pending = None
            self._ready.clear()
            self._prepared_rejected.clear()
            self._bytes = 0
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=60)
        return worker is None or not worker.is_alive()
