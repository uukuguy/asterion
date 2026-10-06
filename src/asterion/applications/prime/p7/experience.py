"""Bounded, inert research from exact-identity attempts, independent of routes.

Hash integrity is provenance, never an environment result or execution grant.
All mutable state here is private to the consuming run; sources remain read-only.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from threading import RLock

from asterion.agents.prime.trace import PrimeTraceError, _entry_digest
from .console_events import read_console_events
from .private_trace import trace_identities_for
from .research import _atomic, copy_json, export_hash, identifier, task, worldmap
from .score import canonical_bytes, digest
from .dynamic_evidence import AnimationFrames

_MAX_FILE = 32 * 1024 * 1024
_MAX_ROWS = 16384
_MAX_RUNS = 4096
_MAX_TOTAL = 64 * 1024 * 1024


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('experience unavailable')


def _bytes(path: Path, cap: int = 1024 * 1024) -> bytes:
    _safe(path)
    if not path.is_file() or path.stat().st_size > cap:
        raise ValueError('experience unavailable')
    with path.open('rb') as stream:
        value = stream.read(cap + 1)
    if len(value) > cap:
        raise ValueError('experience unavailable')
    return value


def _json(path: Path, cap: int = 1024 * 1024) -> dict:
    value = json.loads(_bytes(path, cap))
    if type(value) is not dict:
        raise ValueError('experience unavailable')
    return value


def _hash(value: object) -> bool:
    return (type(value) is str and len(value) == 71 and value.startswith('sha256:')
            and all(c in '0123456789abcdef' for c in value[7:]))


def _trace(path: Path, model_id: str) -> tuple[list[dict], int]:
    raw = _bytes(path, _MAX_FILE)
    rows, previous, consumed = [], None, 0
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'):
            break
        if len(rows) >= _MAX_ROWS or len(line) > 65536:
            raise ValueError('experience trace exceeds limit')
        row = json.loads(line)
        if (type(row) is not dict or set(row) != {'sequence', 'kind', 'identities', 'payload', 'previous_sha256', 'sha256'}
                or type(row['sequence']) is not int or row['sequence'] != len(rows) + 1
                or row['identities'] != trace_identities_for(model_id)
                or row['previous_sha256'] != previous
                or _entry_digest(row['sequence'], row['kind'], row['identities'], row['payload'], previous) != row['sha256']):
            raise ValueError('experience trace invalid')
        rows.append(row)
        previous = row['sha256']
        consumed += len(line)
    if not rows:
        raise ValueError('experience identity unavailable')
    return rows, consumed


class CellArchive:
    """Persist source before execution; absent completion remains unknown."""
    def __init__(self, run_root: Path):
        self.run_id = identifier(run_root.name)
        if run_root.is_symlink():
            raise ValueError('experience archive unavailable')
        # The operator supplies this root; canonicalize macOS /var before
        # validating every application-owned child against symlink traversal.
        run_root = run_root.resolve()
        self.root = run_root / 'research' / 'cells'
        _safe(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._records = {}
        self._bytes = 0
        self.omitted = 0

    def started(self, call_id: str, generation: str, source: str) -> None:
        if (type(source) is not str or len(source.encode('utf-8')) > 16 * 1024
                or len(self._records) >= 256 or self._bytes + len(source.encode('utf-8')) > 4 * 1024 * 1024):
            self.omitted += 1
            _atomic(self.root / 'omitted.json', {'run_id': self.run_id, 'omitted': self.omitted})
            return
        if type(call_id) is not str or not call_id or len(call_id) > 256:
            self.omitted += 1
            return
        key = digest({'call_id': call_id, 'generation': generation})[7:]
        if key in self._records:
            return
        record = {'run_id': self.run_id, 'call_id': call_id, 'generation': generation,
                  'source': source, 'source_sha256': digest(source), 'status': 'unknown',
                  'export_ids': [], 'ordinal': len(self._records)}
        self._records[key] = record
        self._bytes += len(source.encode('utf-8'))
        _atomic(self.root / (key + '.json'), {'record': record, 'sha256': digest(record)})

    def finished(self, call_id: str, generation: str, status: str, export_ids: list[str]) -> None:
        key = digest({'call_id': call_id, 'generation': generation})[7:]
        if key not in self._records:
            return
        record = self._records[key]
        record['status'] = status if status in {'ok', 'error', 'uncertain', 'interrupted'} else 'unknown'
        record['export_ids'] = [eid for eid in export_ids if _hash(eid)][:16]
        _atomic(self.root / (key + '.json'), {'record': record, 'sha256': digest(record)})


class _Source:
    def __init__(self, run: Path, *, game_id: str, seed: int, win_levels: int, model_id: str):
        _safe(run)
        identifier(run.name)
        self.run = run
        self.files = []
        self.byte_count = 0
        self.scope = dict(game_id=game_id, seed=seed, win_levels=win_levels,
                          run_id=run.name, attempt_id=run.name)
        research = run / 'research' / digest(self.scope)[7:]
        current = _json(research / 'current.json')
        if (set(current) != {'scope', 'revision'} or current['scope'] != self.scope or not _hash(current['revision'])
                or type(current['scope'].get('seed')) is not int or type(current['scope'].get('win_levels')) is not int):
            raise ValueError('experience scope invalid')
        self.revision = current['revision']
        summary = {}
        if (run / 'summary.json').exists():
            summary = _json(run / 'summary.json')
            experiment = summary.get('experiment', {})
            if (summary.get('run_id') != run.name or experiment.get('game_id') != game_id
                    or type(experiment.get('seed')) is not int or experiment['seed'] != seed
                    or experiment.get('model') != model_id or experiment.get('prediction_variant') != 'verified'):
                raise ValueError('experience summary identity invalid')
        rows, trace_size = _trace(run / 'trace' / 'prime-trace.jsonl', model_id)
        self._pin(run / 'trace' / 'prime-trace.jsonl', trace_size)
        self.trace_head = rows[-1]['sha256']
        self.history = []
        for row in rows:
            if row['kind'] == 'arc.action':
                payload = row['payload']
                if (type(payload.get('sequence')) is not int or payload['sequence'] != len(self.history) + 1
                        or not _hash(payload.get('before_sha256')) or not _hash(payload.get('after_sha256'))):
                    raise ValueError('experience action invalid')
                self.history.append(copy_json(payload))
        sealed = False
        seal_path = run / 'trace' / 'prime-trace.seal.json'
        if seal_path.exists():
            seal = _json(seal_path)
            if seal.get('entry_count') != len(rows) or seal.get('final_sha256') != self.trace_head:
                raise ValueError('experience seal invalid')
            sealed = True
            self._pin(seal_path)
        outcome = 'unknown'
        if summary.get('failure'):
            outcome = 'interrupted'
        elif summary.get('reason') in {'completed', 'success'}:
            outcome = 'completed'
        elif summary and summary.get('reason'):
            outcome = 'failed'
        self.trust = {'integrity': 'checked', 'trace_status': ('sealed_replayed' if sealed and summary.get('replay_verified') is True
                     else 'sealed_unreplayed' if sealed else 'unsealed_prefix'), 'outcome': outcome}
        terminal_rows = [row['payload'] for row in rows if row['kind'] in {'arc.run.completed', 'arc.run.partial', 'arc.run.failed'}]
        for terminal in terminal_rows:
            if (terminal.get('game_id') == game_id and terminal.get('seed') == seed
                    and terminal.get('win_levels') == win_levels
                    and terminal.get('levels_completed') == win_levels
                    and terminal.get('primitive_actions') == len(self.history)
                    and self.history and self.history[-1]['levels_completed'] == win_levels):
                self.trust['outcome'] = 'completed'
        self.research = []
        self.artifacts = {}
        revision = self.revision
        seen = set()
        while revision is not None:
            if not _hash(revision) or revision in seen or len(seen) >= _MAX_ROWS:
                raise ValueError('experience revision ancestry invalid')
            seen.add(revision)
            path = research / 'revisions' / (revision[7:] + '.json')
            snapshot = _json(path)
            if (set(snapshot) != {'scope', 'parent_revision', 'worldmap', 'task', 'model', 'reports', 'evidence_sequences', 'correction'}
                    or snapshot.get('scope') != self.scope or digest(snapshot) != revision):
                raise ValueError('experience revision invalid')
            worldmap(snapshot['worldmap'])
            task(snapshot['task'])
            correction = snapshot['correction']
            if (type(correction) is not dict or not {'changed', 'retained'} <= set(correction)
                    or not set(correction) <= {'changed', 'retained', 'counterexample_sequence'}
                    or any(type(correction[k]) is not list or len(correction[k]) > 32
                           or any(type(v) is not str or len(v) > 600 for v in correction[k]) for k in ('changed', 'retained'))
                    or ('counterexample_sequence' in correction and
                        (type(correction['counterexample_sequence']) is not int or correction['counterexample_sequence'] < 0))
                    or type(snapshot['evidence_sequences']) is not list or len(snapshot['evidence_sequences']) > 128
                    or any(type(seq) is not int or seq < 0 for seq in snapshot['evidence_sequences'])):
                raise ValueError('experience research metadata invalid')
            self._pin(path)
            self.research.append({'source_run_id': run.name, 'source_revision': revision, **snapshot})
            model = snapshot.get('model', {})
            refs = [(eid, 'text') for eid in model.get('source_export_ids', [])]
            if model.get('state_export_id'):
                refs.append((model['state_export_id'], 'json'))
            refs.extend((report['export_id'], 'json') for report in snapshot.get('reports', []))
            for eid, kind in refs:
                self._artifact(research, eid, kind)
            revision = snapshot.get('parent_revision')
        checkpoint_path = research / 'checkpoint.json'
        if checkpoint_path.exists():
            checkpoint = _json(checkpoint_path)
            if checkpoint.get('scope') != self.scope or checkpoint.get('revision') not in seen:
                raise ValueError('experience checkpoint invalid')
            for eid in checkpoint.get('source_export_ids', []):
                self._artifact(research, eid, 'text')
            for key in ('state_export_id', 'frontier_export_id'):
                if checkpoint.get(key):
                    self._artifact(research, checkpoint[key], 'json')
            self._pin(checkpoint_path)
        self.frames = {}
        self.animations = {}
        self.feedback = []
        console = run / 'console-events.jsonl'
        if console.exists():
            _safe(console)
            if console.is_file():
                warnings = []
                events = read_console_events(run, run.name, game_id, warnings=warnings)
                self._pin(console, console.stat().st_size, animation=True)
                hashes = {item['sequence']: item['after_sha256'] for item in self.history}
                if self.history:
                    hashes[0] = self.history[0]['before_sha256']
                for event in events:
                    payload = event['payload']
                    seq = payload.get('source_action_sequence')
                    anchored = type(seq) is int and hashes.get(seq) == payload.get('observation_sha256')
                    if anchored and event['kind'] == 'observation':
                        from .broker import read_observation
                        if payload.get('evidence_ref') is not None:
                            observation = read_observation(run / 'animation-evidence', payload['evidence_ref'],
                                expected_scope={'run_id': run.name, 'game_id': game_id, 'seed': seed, 'sequence': seq},
                                expected_sha256=hashes[seq])
                            frames = observation.frame
                        else:
                            frames = AnimationFrames.capture(payload['observation']['frame'])
                        self.animations[seq] = frames
                        safe = {**payload, 'observation': {**payload['observation'],
                            'frame': [[list(row) for row in frames[-1]]]}}
                        safe['animation_ref'] = frames.reference()
                        safe['animation_paged'] = len(frames) > 1
                        self.frames[seq] = copy_json(safe)
                    elif anchored and event['kind'] == 'feedback':
                        self.feedback.append(copy_json(payload))
        self.cells = []
        self.omitted_cells = 0
        cell_root = run / 'research' / 'cells'
        if cell_root.exists():
            _safe(cell_root)
            paths = sorted(cell_root.iterdir())
            if len(paths) > 257:
                raise ValueError('experience cells exceed limit')
            for path in paths:
                if path.name == 'omitted.json':
                    omitted = _json(path)
                    if (set(omitted) != {'run_id', 'omitted'} or omitted['run_id'] != run.name
                            or type(omitted['omitted']) is not int or omitted['omitted'] < 0):
                        raise ValueError('experience cell omission invalid')
                    self.omitted_cells = omitted['omitted']
                    self._pin(path)
                    continue
                stored = _json(path, 128 * 1024)
                record = stored.get('record', {})
                if (stored.get('sha256') != digest(record) or record.get('run_id') != run.name
                        or type(record.get('source')) is not str or digest(record['source']) != record.get('source_sha256')
                        or len(record['source'].encode('utf-8')) > 16 * 1024):
                    raise ValueError('experience cell invalid')
                self._pin(path)
                self.cells.append(record)
            self.cells.sort(key=lambda cell: cell['ordinal'])
        # Older traces may contain exact tool arguments. Empty/redacted arguments
        # are missing source, not recoverable Python; never reconstruct stdout.
        if not self.cells:
            for row in rows:
                p = row['payload']
                args = p.get('arguments', {})
                if row['kind'] == 'tool.call' and p.get('name') == 'ipython' and type(args) is dict and type(args.get('code')) is str:
                    code = args['code']
                    if len(code.encode('utf-8')) <= 16 * 1024 and len(self.cells) < 256:
                        self.cells.append({'run_id': run.name, 'call_id': p.get('call_id'), 'source': code,
                                           'source_sha256': digest(code), 'status': 'unknown', 'export_ids': [],
                                           'ordinal': len(self.cells), 'origin': 'private-trace'})
        self.worker_cells = summary.get('diagnostics', {}).get('worker_cell_count', 0)
        if type(self.worker_cells) is not int or self.worker_cells < 0:
            self.worker_cells = 0

    def _pin(self, path: Path, length: int | None = None, *, animation=False) -> None:
        _safe(path)
        prefix = length is not None
        size = path.stat().st_size if length is None else length
        hasher, consumed = sha256(), 0
        with path.open('rb') as stream:
            while consumed < size:
                data = stream.read(min(65536, size - consumed))
                if not data:
                    raise ValueError('experience source changed')
                hasher.update(data)
                consumed += len(data)
        self.files.append((path, size, hasher.hexdigest(), prefix))
        # Legacy console bodies carry animation bytes. Their original hash is
        # pinned in full, but animation volume is outside research metadata quotas.
        if not animation:
            self.byte_count += size
        if self.byte_count > _MAX_TOTAL:
            raise ValueError('experience source exceeds total limit')

    def _artifact(self, research: Path, eid: str, kind: str) -> None:
        if eid in self.artifacts:
            if self.artifacts[eid]['kind'] != kind:
                raise ValueError('experience export kind invalid')
            return
        if not _hash(eid):
            raise ValueError('experience export invalid')
        path = research / 'artifacts' / (eid[7:] + '.json')
        record = _json(path)
        if (set(record) != {'scope', 'export_id', 'name', 'kind', 'value', 'source_call_id'}
                or record['scope'] != self.scope or record['export_id'] != eid
                or record['kind'] != kind or export_hash(record) != eid):
            raise ValueError('experience export invalid')
        self._pin(path)
        self.artifacts[eid] = record

    def check(self) -> None:
        for path, length, expected, prefix in self.files:
            _safe(path)
            if not prefix and path.stat().st_size != length:
                raise ValueError('experience source changed')
            hasher, consumed = sha256(), 0
            with path.open('rb') as stream:
                while consumed < length:
                    data = stream.read(min(65536, length - consumed))
                    if not data:
                        raise ValueError('experience source changed')
                    hasher.update(data)
                    consumed += len(data)
            if hasher.hexdigest() != expected:
                raise ValueError('experience source changed')

    def metadata(self) -> dict:
        unresolved = sorted({seq for revision in self.research for seq in revision.get('evidence_sequences', [])
                             if type(seq) is not int or seq < 0 or seq > len(self.history)}, key=str)
        return {'source_run_id': self.run.name, 'source_revision': self.revision, 'trace_head_sha256': self.trace_head,
                **self.trust, 'action_count': len(self.history), 'revision_count': len(self.research),
                'export_count': len(self.artifacts), 'cell_source_count': len(self.cells),
                'missing_cell_source_count': max(self.omitted_cells, self.worker_cells - len(self.cells)),
                'unresolved_evidence_sequences': unresolved[:128]}


class ExperienceBundle:
    def __init__(self, *, current_run_id: str, sources: list[_Source], rejected: int = 0, truncated: bool = False):
        self.run_id = current_run_id
        self.sources = {source.run.name: source for source in sources}
        self._rejected, self._truncated = rejected, truncated
        self._root = None
        self._lock = RLock()
        self._sink = None
        self._audit = {'run_id': current_run_id, 'loaded': False, 'loaded_source_ids': [],
                       'context_sha256': None, 'reads': [], 'revisions': [], 'omitted_reads': 0, 'omitted_revisions': 0}

    def context(self) -> dict:
        sources = list(self.sources.values())
        latest = sources[0] if sources else None
        value = {'advisory_only': True, 'requires_current_evidence': True,
                 'available_count': len(sources), 'rejected_count': self._rejected,
                 'sources': [source.metadata() for source in sources[:12]],
                 'omitted_source_count': max(0, len(sources) - 12), 'truncated': self._truncated or len(sources) > 12,
                 'latest': None,
                 'read_api': 'p7_research.experience(source_run_id, kind, start=0, limit=32, artifact_id=None); kind=index|research|history|frame|artifact|cells; index uses empty source_run_id. Historical evidence is advisory; source code is inert.'}
        if latest:
            snapshot = latest.research[0]
            value['latest'] = {**latest.metadata(), 'worldmap': snapshot['worldmap'], 'task': snapshot['task'],
                               'correction': snapshot['correction'], 'feedback': latest.feedback[-3:],
                               'exports': [{'export_id': eid, 'kind': record['kind'], 'name': record['name']}
                                           for eid, record in list(latest.artifacts.items())[:16]]}
        if len(canonical_bytes(value)) > 16 * 1024 and latest:
            value['truncated'] = True
            prior = value['latest']
            prior['worldmap'] = copy_json(prior['worldmap'])
            prior['worldmap']['description_zh'] = prior['worldmap']['description_zh'][:1500]
            prior['worldmap']['state_summary'] = prior['worldmap']['state_summary'][:300]
            for key in ('rules', 'unknowns', 'competing_hypotheses'):
                prior['worldmap'][key] = [v[:200] for v in prior['worldmap'][key][:6]]
            prior['task'] = {'goal': prior['task']['goal'][:300], 'question': prior['task']['question'][:300]}
            prior['correction'] = {key: [v[:200] for v in prior['correction'].get(key, [])[:6]] for key in ('changed', 'retained')}
            prior['feedback'] = prior['feedback'][-1:]
            value['sources'] = value['sources'][:4]
            value['omitted_source_count'] = max(0, len(sources) - 4)
        if len(canonical_bytes(value)) > 16 * 1024:
            value['latest']['feedback'] = []
            value['latest']['exports'] = value['latest']['exports'][:4]
            value['sources'] = value['sources'][:1]
            value['omitted_source_count'] = max(0, len(sources) - 1)
        return copy_json(value, limit=16 * 1024)

    def bind(self, run_root: Path, event_sink=None) -> None:
        if run_root.name != self.run_id:
            raise ValueError('experience consumer identity invalid')
        _safe(run_root)
        self._root = run_root / 'research'
        _safe(self._root)
        self._root.mkdir(exist_ok=True)
        self._sink = event_sink
        manifest = {'run_id': self.run_id, 'sources': [source.metadata() for source in self.sources.values()],
                    'rejected_count': self._rejected, 'truncated': self._truncated}
        _atomic(self._root / 'experience-manifest.json', manifest)
        self._save()

    def _save(self) -> None:
        if self._root is not None:
            _atomic(self._root / 'experience-consumption.json', self._audit)

    def _event(self, message: str) -> None:
        if self._sink is not None:
            self._sink(message)

    def mark_loaded(self) -> None:
        with self._lock:
            for source in self.sources.values():
                source.check()
            context = self.context()
            self._audit['loaded'] = bool(context['latest'])
            self._audit['context_sha256'] = digest(context)
            self._audit['loaded_source_ids'] = [context['latest']['source_run_id']] if context['latest'] else []
            self._save()
            if context['latest']:
                prior = context['latest']
                self._event(f'历史经验已载入：{prior["source_run_id"]}；可用来源 {context["available_count"]}；'
                            f'完整性 {prior["integrity"]}，轨迹 {prior["trace_status"]}，结果 {prior["outcome"]}；'
                            f'源码候选 {prior["cell_source_count"]}，缺失 {prior["missing_cell_source_count"]}，'
                            f'导出 {prior["export_count"]}；仅作待复核先验，尚未认定程序复用。')
            else:
                self._event('历史经验可用来源 0；本轮从当前观察建立研究。')

    def read(self, source_run_id: str, kind: str, *, start: int = 0, limit: int = 32, artifact_id: str | None = None) -> dict:
        with self._lock:
            if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 32:
                raise ValueError('experience query invalid')
            if kind == 'index' and source_run_id == '':
                items = [source.metadata() for source in self.sources.values()]
                return copy_json({'items': items[start:start + limit], 'total': len(items), 'advisory_only': True})
            if source_run_id not in self.sources or kind not in {'research', 'history', 'frame', 'animation', 'artifact', 'cells'}:
                raise ValueError('experience source unavailable')
            source = self.sources[source_run_id]
            source.check()
            if kind == 'research':
                items = source.research
            elif kind == 'history':
                items = [{**item, 'observation': source.frames.get(item['sequence']),
                          'feedback': [f for f in source.feedback if f['source_action_sequence'] == item['sequence']]}
                         for item in source.history]
            elif kind == 'frame':
                items = [source.frames[start]] if start in source.frames else []
            elif kind == 'animation':
                # The artifact anchor is the exact original observation hash;
                # it selects only an already authenticated historical observation.
                matches = [sequence for sequence, value in source.frames.items()
                           if value['observation_sha256'] == artifact_id]
                if len(matches) != 1:
                    raise ValueError('experience animation unavailable')
                sequence = matches[0]
                frames = source.animations[sequence]
                items = [{'source_action_sequence': sequence, 'observation_sha256': artifact_id,
                          'animation_ref': frames.reference(), 'start': start,
                          'frames': [[list(row) for row in grid] for grid in frames.page(start, limit)]}]
            elif kind == 'cells':
                items = source.cells
            else:
                if artifact_id is None:
                    items = [{'export_id': eid, 'kind': record['kind'], 'name': record['name']}
                             for eid, record in source.artifacts.items()]
                elif artifact_id in source.artifacts:
                    items = [source.artifacts[artifact_id]]
                else:
                    raise ValueError('experience export unavailable')
            selected = items if kind in {'frame', 'animation'} or artifact_id is not None else items[start:start + limit]
            response = {'source_run_id': source_run_id, 'source_revision': source.revision,
                        **source.trust, 'advisory_only': True, 'inert': True, 'items': selected,
                        'total': len(items), 'truncated': len(selected) < len(items)}
            while len(canonical_bytes(response)) > 900 * 1024 and response['items']:
                response['items'] = response['items'][:-1]
                response['truncated'] = True
            result = copy_json(response)
            record = {'source_run_id': source_run_id, 'source_revision': source.revision,
                      'kind': kind, 'start': start, 'count': len(result['items']),
                      'artifact_id': artifact_id, 'result_sha256': digest(result)}
            if len(self._audit['reads']) < 1024:
                self._audit['reads'].append(record)
            else:
                self._audit['omitted_reads'] += 1
            self._save()
            self._event(f'历史经验已读取：{source_run_id}；{kind}，{len(result["items"])} 项。')
            return result

    def record_revision(self, revision: str, correction: dict, exports: list[dict]) -> None:
        with self._lock:
            if not self.sources:
                return
            # This links observed access to a later revision, without claiming
            # psychological adoption or execution of a historical program.
            consulted = sorted(set(self._audit['loaded_source_ids']) | {read['source_run_id'] for read in self._audit['reads']})
            matches = []
            for exported in exports:
                if exported.get('kind') != 'text':
                    continue
                for read in self._audit['reads']:
                    source = self.sources[read['source_run_id']]
                    prior = []
                    if read['kind'] == 'cells':
                        prior = source.cells[read['start']:read['start'] + read['count']]
                    elif read['kind'] == 'artifact' and read['artifact_id'] in source.artifacts:
                        item = source.artifacts[read['artifact_id']]
                        if item['kind'] == 'text':
                            prior = [{'source': item['value'], 'source_sha256': digest(item['value'])}]
                    for old in prior:
                        if exported.get('value') == old['source']:
                            matches.append({'source_run_id': source.run.name, 'source_sha256': old['source_sha256'],
                                            'export_id': exported['export_id']})
            record = {'workspace_revision': revision, 'source_run_ids': consulted,
                      'correction': copy_json(correction), 'program_reused': bool(matches), 'program_matches': matches[:32]}
            if len(self._audit['revisions']) < 256:
                self._audit['revisions'].append(record)
            else:
                self._audit['omitted_revisions'] += 1
            self._save()
            self._event(f'历史经验已关联本轮修订：{revision}；参考来源 {len(consulted)}；'
                        + ('已读历史程序与本轮发布源码一致，程序来源复用已核对。' if matches
                           else '尚无已读历史程序与本轮发布源码匹配的证据。'))


def load_experience(runs_root: Path, *, game_id: str, seed: int, win_levels: int,
                    model_id: str, current_run_id: str, pinned_source_run_id: str | None = None) -> ExperienceBundle:
    identifier(game_id)
    identifier(current_run_id)
    trace_identities_for(model_id)
    if pinned_source_run_id is not None:
        identifier(pinned_source_run_id)
    if type(seed) is not int or type(win_levels) is not int or win_levels < 1:
        raise ValueError('experience scope invalid')
    sources, rejected, truncated, total = [], 0, False, 0
    _safe(runs_root)
    if runs_root.is_dir():
        candidates = sorted(runs_root.iterdir(), key=lambda path: path.name, reverse=True)
        truncated = len(candidates) > _MAX_RUNS
        for run in candidates[:_MAX_RUNS]:
            if run.name == current_run_id or not run.is_dir():
                continue
            try:
                if len(sources) >= 8 and run.name != pinned_source_run_id:
                    truncated = True
                    continue
                source = _Source(run, game_id=game_id, seed=seed, win_levels=win_levels, model_id=model_id)
                if total + source.byte_count > _MAX_TOTAL:
                    truncated = True
                    break
                sources.append(source)
                total += source.byte_count
            except (OSError, ValueError, TypeError, KeyError, RecursionError, PrimeTraceError):
                rejected += 1
    return ExperienceBundle(current_run_id=current_run_id, sources=sources, rejected=rejected, truncated=truncated)
