"""Operator-generated durable public replay projections, prepared at save time.

These are trusted derivatives under the same operator ownership as run evidence.
SHA checks detect incomplete publication/corruption; they grant no score,
execution, or adversarial authentication authority. Explicit source fingerprints
bind freshness, while the existing projector and partial-save proof admit writes.
"""

from __future__ import annotations

import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil

from .console_events import _payload, _PRIVATE, public_action_labels
from .console_replay import _paged_frame_member, projection_manifest, projection_level, projection_revision, replay_fingerprint
from .run_story.storage import publish_directory, write_atomic_file
from .processing_diagnostics import public_diagnostic


_SCHEMA = 'asterion.arc-agi3-p7-prepared-replay/v1'
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_MAX_META = 1024 * 1024
_MAX_LEVEL = 32 * 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_RUN_FIELDS = {'run_id', 'game_id', 'status', 'completed_level_count', 'seed', 'win_levels',
               'target_level', 'primitive_action_count', 'replay_verified', 'sealed_trace', 'model'}
_LEVEL_FIELDS = {'level', 'status', 'frames', 'actions', 'decisions', 'research_timeline',
                 'cognition_timeline', 'cognition', 'receipt'}
_FRAME_FIELDS = {'id', 'grid', 'timestamp', 'available_actions', 'event_sequence', 'state', 'levels_completed'}
_ACTION_FIELDS = {'id', 'name', 'before_frame', 'after_frame', 'data', 'levels_completed', 'changed_cells',
                  'trace_sequence', 'visual_observations', 'decision_id', 'source_action_sequence'}
_DECISION_FIELDS = {'id', 'source', 'goal', 'basis', 'expected', 'source_action_sequence', 'observation_sha256',
                    'action_ids', 'event_sequence', 'round_index', 'trace_sequence', 'prompt_signals', 'output_signals'}
_COGNITION_FIELDS = {'stable_description', 'scope', 'updates', 'world_map_facts', 'action_meanings',
    'frame_id', 'action_id', 'source_action_sequence', 'observation_sha256', 'cognition_revision',
    'event_sequence', 'cognition_narrative_zh', 'origin', 'provenance', 'session', 'action_labels', 'frame_index'}
_PRIVATE_FIELDS = {'prompt', 'answer', 'credentials', 'provider_payload', 'raw_output', 'path',
                   'environment', 'token', 'secret', 'api_key', 'password', 'authorization'}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True).encode('utf-8')


def _safe(path):
    return not any(part.is_symlink() for part in (path, *path.parents))


def _read(path, maximum):
    if not _safe(path) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('prepared replay unavailable')
    with path.open('rb') as stream:
        result = stream.read(maximum + 1)
    if len(result) > maximum:
        raise ValueError('prepared replay unavailable')
    return result


def _json(raw):
    return json.loads(raw)


def _count(value, maximum=10**9):
    return type(value) is int and 0 <= value <= maximum


def _identifier(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _hash(value):
    return type(value) is str and value.startswith('sha256:') and _HEX.fullmatch(value[7:]) is not None


def _provenance(value):
    if (type(value) is not dict or set(value) != {'run_id', 'event_sequence'}
            or not _identifier(value['run_id']) or not _count(value['event_sequence'])
            or value['event_sequence'] < 1):
        raise ValueError('prepared replay unavailable')


def _cognition(value):
    if (type(value) is not dict or set(value) - _COGNITION_FIELDS
            or value.get('scope') not in {'observation', 'final', 'unavailable'}):
        raise ValueError('prepared replay unavailable')
    for key in ('stable_description', 'cognition_narrative_zh'):
        if key in value:
            _prose(value[key])
    for key in ('source_action_sequence', 'cognition_revision', 'event_sequence'):
        if key in value and not _count(value[key]):
            raise ValueError('prepared replay unavailable')
    for key in ('frame_id', 'action_id', 'origin'):
        if key in value and value[key] is not None and not _identifier(value[key]):
            raise ValueError('prepared replay unavailable')
    if 'observation_sha256' in value and not _hash(value['observation_sha256']):
        raise ValueError('prepared replay unavailable')
    if 'provenance' in value:
        _provenance(value['provenance'])
    if 'action_labels' in value:
        if not _count(value.get('source_action_sequence')) or value['scope'] != 'observation':
            raise ValueError('prepared replay unavailable')
        # Authenticated restored conclusions keep evidence in the source run space.
        public_action_labels(value['action_labels'],
                             latest=10**9 if 'provenance' in value else value['source_action_sequence'])
    session = value.get('session', {})
    if (type(session) is not dict or set(session) - {'state', 'episode', 'episode_actions'}
            or any(not (_identifier(item) if key == 'state' else _count(item)) for key, item in session.items())):
        raise ValueError('prepared replay unavailable')
    facts = value.get('world_map_facts', {})
    if (type(facts) is not dict or set(facts) - {'conflicts', 'hypotheses', 'version', 'current_level', 'confirmed'}
            or any(not _count(item) for key, item in facts.items() if key != 'confirmed')):
        raise ValueError('prepared replay unavailable')
    confirmed = facts.get('confirmed', {})
    if (type(confirmed) is not dict or set(confirmed) - {'entities', 'mechanics', 'relations'}
            or any(not _count(item) for item in confirmed.values())):
        raise ValueError('prepared replay unavailable')
    updates = value.get('updates', [])
    if type(updates) is not list or len(updates) > 4096:
        raise ValueError('prepared replay unavailable')
    for update in updates:
        if (type(update) is not dict or set(update) != {'type', 'sequence', 'changes'}
                or not _identifier(update['type']) or not update['type'].startswith('cognition.')
                or not _count(update['sequence']) or type(update['changes']) is not list):
            raise ValueError('prepared replay unavailable')
        for change in update['changes']:
            if (type(change) is not dict or set(change) != {'id', 'kind', 'status', 'claim'}
                    or not _identifier(change['id']) or change['kind'] not in
                        {'game_type', 'object_role', 'control', 'rule', 'success_condition', 'strategy', 'unknown'}
                    or change['status'] not in {'certain', 'falsified', 'undetermined'}):
                raise ValueError('prepared replay unavailable')
            _prose(change['claim'])
    meanings = value.get('action_meanings', {})
    if type(meanings) is not dict or any(key not in {f'ACTION{i}' for i in range(1, 8)} for key in meanings):
        raise ValueError('prepared replay unavailable')
    for entries in meanings.values():
        if type(entries) is not list:
            raise ValueError('prepared replay unavailable')
        for entry in entries:
            if (type(entry) is not dict or set(entry) != {'status', 'claim'}
                    or entry['status'] not in {'certain', 'falsified', 'undetermined'}):
                raise ValueError('prepared replay unavailable')
            _prose(entry['claim'])


def _prose(value):
    if type(value) is not str or _PRIVATE.search(value):
        raise ValueError('prepared replay unavailable')


def _public(value, depth=0):
    """Reject private additions even when a descriptor was rewritten with them."""
    if depth > 32:
        raise ValueError('prepared replay unavailable')
    if type(value) is dict:
        if any(type(key) is not str or key.lower() in _PRIVATE_FIELDS for key in value):
            raise ValueError('prepared replay unavailable')
        for child in value.values():
            _public(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _public(child, depth + 1)
    elif type(value) is str:
        _prose(value)
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError('prepared replay unavailable')


def _manifest(value, run_id):
    fields = {'schema', 'state', 'run_id', 'revision', 'run', 'levels', 'warnings'}
    if type(value) is dict and value.get('schema') == 'asterion.arc-agi3-p7-replay-manifest/v2':
        fields.add('diagnostics')
    if (type(value) is not dict
            or set(value) != fields
            or value['schema'] not in {'asterion.arc-agi3-p7-replay-manifest/v1', 'asterion.arc-agi3-p7-replay-manifest/v2'}
            or value['state'] != 'ready' or value['run_id'] != run_id
            or type(value['revision']) is not str or not _HEX.fullmatch(value['revision'])
            or type(value['run']) is not dict or set(value['run']) != _RUN_FIELDS):
        raise ValueError('prepared replay unavailable')
    run = value['run']
    if (run['run_id'] != run_id or type(run['game_id']) is not str or not _ID.fullmatch(run['game_id'])
            or run['status'] not in {'successful', 'unsuccessful', 'incomplete'}
            or not _count(run['seed']) or not _count(run['win_levels'], 100) or run['win_levels'] < 1
            or not _count(run['completed_level_count'], run['win_levels']) or run['completed_level_count'] < 1
            or not _count(run['target_level'], run['win_levels']) or run['target_level'] < 1
            or not _count(run['primitive_action_count']) or run['sealed_trace'] is not True
            or type(run['replay_verified']) is not bool or type(run['model']) is not str or not _ID.fullmatch(run['model'])
            or type(value['levels']) is not list or len(value['levels']) != run['win_levels']
            or type(value['warnings']) is not list):
        raise ValueError('prepared replay unavailable')
    for index, level in enumerate(value['levels'], 1):
        if (type(level) is not dict or set(level) != {'level', 'status', 'frame_count', 'action_count', 'has_cognition'}
                or type(level['level']) is not int or level['level'] != index
                or level['status'] not in {'successful', 'unsuccessful', 'incomplete', 'not-run'}
                or type(level['frame_count']) is not int or level['frame_count'] < 0 or not _count(level['action_count'], 4096)
                or type(level['has_cognition']) is not bool):
            raise ValueError('prepared replay unavailable')
    for warning in value['warnings']:
        _prose(warning)
    if 'diagnostics' in value:
        if type(value['diagnostics']) is not list:
            raise ValueError('prepared replay unavailable')
        for diagnostic in value['diagnostics']:
            public_diagnostic(diagnostic)


def _events(events):
    if type(events) is not list or len(events) > 16384:
        raise ValueError('prepared replay unavailable')
    previous = 0
    required = {'event_sequence', 'kind', 'source_action_sequence', 'frame_id', 'level', 'payload'}
    for event in events:
        if (type(event) is not dict or not required <= set(event) or set(event) - (required | {'provenance', 'frame_index'})
                or type(event['payload']) is not dict or not _count(event['event_sequence'])
                or event['event_sequence'] <= previous or not _count(event['source_action_sequence'])
                or not _identifier(event['frame_id']) or not _count(event['level'], 100) or event['level'] < 1):
            raise ValueError('prepared replay unavailable')
        previous = event['event_sequence']
        if 'provenance' in event:
            _provenance(event['provenance'])
        if event.get('kind') == 'observation':
            if (set(event['payload']) != {'source_action_sequence', 'observation_sha256'}
                    or not _count(event['payload']['source_action_sequence'])
                    or not _hash(event['payload']['observation_sha256'])):
                raise ValueError('prepared replay unavailable')
        else:
            payload = event['payload']
            if event['kind'] == 'model_revision' and 'provenance' in event:
                if not _count(payload.get('source_action_sequence')):
                    raise ValueError('prepared replay unavailable')
                # Restoration rebases the display cursor, while evidence IDs
                # retain their authenticated source coordinates. Their native
                # inequality is inapplicable across these sequence spaces;
                # keep all payload fields and referenced counters bounded.
                payload = {**payload, 'source_action_sequence': 10**9}
            _payload(event.get('kind'), payload)


def _detail(value, manifest, number):
    fields = {'schema', 'generated_at', 'run', 'levels', 'decisions', 'process_events', 'warnings', 'replay_revision'}
    if type(value) is dict and value.get('schema') == 'asterion.arc-agi3-p7-console/v2':
        fields.add('diagnostics')
    if (type(value) is not dict or set(value) != fields
            or value['schema'] not in {'asterion.arc-agi3-p7-console/v1', 'asterion.arc-agi3-p7-console/v2'}
            or value.get('diagnostics', []) != manifest.get('diagnostics', [])
            or value['run'] != manifest['run'] or value['warnings'] != manifest['warnings']
            or value['replay_revision'] != manifest['revision']
            or type(value['generated_at']) is not str or type(value['levels']) is not list
            or len(value['levels']) != 1 or type(value['levels'][0]) is not dict):
        raise ValueError('prepared replay unavailable')
    bucket, metadata = value['levels'][0], manifest['levels'][number - 1]
    paged = 'frame_page' in bucket
    if (set(bucket) != _LEVEL_FIELDS | ({'frame_count', 'frame_index_offset', 'frame_page'} if paged else set())
            or type(bucket['level']) is not int or bucket['level'] != number
            or bucket['status'] != metadata['status'] or type(bucket['frames']) is not list
            or type(bucket['actions']) is not list or bucket.get('frame_count', len(bucket['frames'])) != metadata['frame_count']
            or len(bucket['actions']) != metadata['action_count']):
        raise ValueError('prepared replay unavailable')
    if paged:
        page = bucket['frame_page']
        if (type(page) is not dict or set(page) != {'start', 'limit', 'source_token'}
                or page['start'] != 0 or page['limit'] != 32
                or type(page['source_token']) is not str or not _HEX.fullmatch(page['source_token'])
                or len(bucket['frames']) not in {0, min(32, bucket['frame_count'])}
                or type(bucket['frame_index_offset']) is not int or bucket['frame_index_offset'] < 1):
            raise ValueError('prepared replay unavailable')
    frames = set()
    for frame in bucket['frames']:
        if (type(frame) is not dict or set(frame) != _FRAME_FIELDS | ({'index'} if paged else set())
                or type(frame['id']) is not str or frame['id'] in frames or not _ID.fullmatch(frame['id'])
                or type(frame['grid']) is not list or not 1 <= len(frame['grid']) <= 64):
            raise ValueError('prepared replay unavailable')
        frames.add(frame['id'])
        if paged and (type(frame['index']) is not int or not 0 <= frame['index'] < bucket['frame_count']
                      or frame['id'] != f"f{frame['index'] + bucket['frame_index_offset']:06d}"):
            raise ValueError('prepared replay unavailable')
        actions = frame['available_actions']
        if (type(frame['timestamp']) is not str or len(frame['timestamp']) > 64
                or type(actions) is not list or len(actions) > 7
                or any(type(action) is not str or action not in {f'ACTION{i}' for i in range(1, 8)} for action in actions)
                or actions != sorted(set(actions))
                or frame['state'] not in {'NOT_STARTED', 'NOT_FINISHED', 'WIN', 'GAME_OVER'}
                or not _count(frame['levels_completed'], manifest['run']['win_levels'])
                or frame['event_sequence'] is not None and not _count(frame['event_sequence'])):
            raise ValueError('prepared replay unavailable')
        width = len(frame['grid'][0]) if type(frame['grid'][0]) is list else 0
        if not 1 <= width <= 64 or any(type(row) is not list or len(row) != width
                or any(not _count(cell, 255) for cell in row) for row in frame['grid']):
            raise ValueError('prepared replay unavailable')
    for action in bucket['actions']:
        if (type(action) is not dict or set(action) != _ACTION_FIELDS | ({'before_frame_index', 'after_frame_index'} if paged else set())
                or not _identifier(action['id']) or not _identifier(action['before_frame'])
                or (not paged and action['after_frame'] not in frames) or action['name'] not in {'RESET', *(f'ACTION{i}' for i in range(1, 8))}
                or type(action['data']) is not dict or not _count(action['levels_completed'], 100)
                or not _count(action['changed_cells'], 4096)
                or any(action[key] is not None and not _count(action[key]) for key in ('trace_sequence', 'source_action_sequence'))
                or action['decision_id'] is not None and not _identifier(action['decision_id'])
                or type(action['visual_observations']) is not list):
            raise ValueError('prepared replay unavailable')
        if paged:
            for kind in ('before', 'after'):
                index = action[f'{kind}_frame_index']
                if (type(index) is not int or not 0 <= index < bucket['frame_count']
                        or action[f'{kind}_frame'] != f"f{index + bucket['frame_index_offset']:06d}"):
                    raise ValueError('prepared replay unavailable')
        if ((action['name'] == 'ACTION6' and (set(action['data']) != {'x', 'y'}
                or any(not _count(item, 63) for item in action['data'].values())))
                or (action['name'] != 'ACTION6' and action['data'] != {})):
            raise ValueError('prepared replay unavailable')
        for prose in action.get('visual_observations', []):
            _prose(prose)
    for decisions in (value['decisions'], bucket['decisions']):
        if type(decisions) is not list:
            raise ValueError('prepared replay unavailable')
        for decision in decisions:
            if (type(decision) is not dict or set(decision) - _DECISION_FIELDS
                    or not _identifier(decision.get('id')) or type(decision.get('action_ids')) is not list
                    or any(not _identifier(item) for item in decision['action_ids'])):
                raise ValueError('prepared replay unavailable')
            if 'round_index' in decision:
                if (set(decision) != {'id', 'round_index', 'trace_sequence', 'action_ids', 'prompt_signals', 'output_signals'}
                        or not _count(decision['round_index']) or not _count(decision['trace_sequence'])
                        or type(decision['prompt_signals']) is not list or type(decision['output_signals']) is not list
                        or any(type(item) is not str or item not in {'tool-guidance', 'mechanics-prior', 'state-guidance',
                            'application-state', 'completion-guidance'} for item in decision['prompt_signals'])
                        or any(type(item) is not str or item not in {'plan', 'observation', 'prior', 'action', 'progress'}
                               for item in decision['output_signals'])):
                    raise ValueError('prepared replay unavailable')
            elif (set(decision) != {'id', 'source', 'goal', 'basis', 'expected', 'source_action_sequence',
                    'observation_sha256', 'action_ids', 'event_sequence'} or decision['source'] != 'p7_decision'
                    or not _count(decision['source_action_sequence']) or not _hash(decision['observation_sha256'])
                    or not _count(decision['event_sequence'])):
                raise ValueError('prepared replay unavailable')
            for key in ('goal', 'basis', 'expected'):
                if key in decision:
                    _prose(decision[key])
    decisions = {decision['id'] for decision in value['decisions']}
    if any(action['decision_id'] is not None and action['decision_id'] not in decisions for action in bucket['actions']):
        raise ValueError('prepared replay unavailable')
    revisions = bucket['cognition_timeline']
    if type(revisions) is not list or type(bucket['cognition']) is not dict:
        raise ValueError('prepared replay unavailable')
    for cognition in [bucket['cognition'], *revisions]:
        _cognition(cognition)
    receipt = bucket['receipt']
    if receipt is not None:
        if (type(receipt) is not dict or set(receipt) != {'completed_level_count', 'primitive_action_count',
                'partial_game_score', 'scope', 'promotion'} or receipt['scope'] != 'p7-solving'
                or receipt['promotion'] != 'unpromoted' or not _count(receipt['completed_level_count'], 100)
                or not _count(receipt['primitive_action_count']) or type(receipt['partial_game_score']) is not str
                or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', receipt['partial_game_score']) is None):
            raise ValueError('prepared replay unavailable')
    _events(value['process_events'])
    _events(bucket['research_timeline'])
    if paged:
        entries = [bucket['cognition'], *revisions, *bucket['research_timeline'],
                   *(event for event in value['process_events'] if event['level'] == number)]
        for entry in entries:
            if 'frame_index' not in entry:
                continue
            index = entry['frame_index']
            if (type(index) is not int or not 0 <= index < bucket['frame_count']
                    or entry.get('frame_id') != f"f{index + bucket['frame_index_offset']:06d}"):
                raise ValueError('prepared replay unavailable')
    if any(event.get('level') != number and event.get('frame_id') not in frames
           and not _paged_frame_member(bucket, event.get('frame_id')) for event in value['process_events']):
        raise ValueError('prepared replay unavailable')
    _public(value)
    if metadata['has_cognition'] != (bucket['cognition'].get('scope') != 'unavailable' and bool(bucket['cognition'])):
        raise ValueError('prepared replay unavailable')


def _descriptor(value, maximum):
    if (type(value) is not dict or set(value) != {'sha256', 'size'}
            or type(value['sha256']) is not str or not _HEX.fullmatch(value['sha256'])
            or not _count(value['size'], maximum) or value['size'] < 1):
        raise ValueError('prepared replay unavailable')


def _checked(path, descriptor, maximum):
    _descriptor(descriptor, maximum)
    raw = _read(path, maximum)
    if len(raw) != descriptor['size'] or sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('prepared replay unavailable')
    return _json(raw)


def _load(root, fingerprint):
    base = root / 'console-prepared'
    index = _json(_read(base / 'current.json', _MAX_META))
    if (type(index) is not dict or set(index) != {'schema', 'run_id', 'source_revision', 'generation_sha256',
            'revision', 'manifest', 'levels', 'verification_kind'} or index['schema'] != _SCHEMA
            or index['run_id'] != root.name or index['source_revision'] != projection_revision(fingerprint)
            or type(index['generation_sha256']) is not str or not _HEX.fullmatch(index['generation_sha256'])
            or index['revision'] != projection_revision(fingerprint, index['generation_sha256'])
            or index['verification_kind'] not in {'full-replay', 'verified-prefix'}
            or type(index['levels']) is not list or not 1 <= len(index['levels']) <= 100):
        raise ValueError('prepared replay unavailable')
    directory = base / index['revision']
    manifest = _checked(directory / 'manifest.json', index['manifest'], _MAX_META)
    _manifest(manifest, root.name)
    if manifest['revision'] != index['revision'] or len(index['levels']) != len(manifest['levels']):
        raise ValueError('prepared replay unavailable')
    total = 0
    for number, level in enumerate(index['levels'], 1):
        if type(level) is not dict or set(level) != {'level', 'sha256', 'size'} or type(level['level']) is not int or level['level'] != number:
            raise ValueError('prepared replay unavailable')
        _descriptor({key: level[key] for key in ('sha256', 'size')}, _MAX_LEVEL)
        total += level['size']
    if total > _MAX_TOTAL:
        raise ValueError('prepared replay unavailable')
    return index, manifest, directory


def read_prepared_manifest(root: Path, fingerprint: tuple) -> dict | None:
    try:
        _, manifest, _ = _load(root, fingerprint)
        return manifest if replay_fingerprint(root) == fingerprint else None
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None


def read_prepared_level(root: Path, fingerprint: tuple, number: int, revision: str) -> dict | None:
    try:
        index, manifest, directory = _load(root, fingerprint)
        if revision != manifest['revision'] or not 1 <= number <= len(index['levels']):
            return None
        descriptor = {key: index['levels'][number - 1][key] for key in ('sha256', 'size')}
        detail = _checked(directory / f'level-{number:03d}.json', descriptor, _MAX_LEVEL)
        _detail(detail, manifest, number)
        return detail if replay_fingerprint(root) == fingerprint else None
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None


def publish_prepared(root: Path, snapshot: dict, fingerprint: tuple) -> dict | None:
    """Prepare immutable selected-level assets; publish only coherent admitted saves."""
    try:
        summary = _json(_read(root / 'summary.json', 32 * 1024 * 1024))
        run = snapshot['run']
        if (type(summary) is not dict or summary.get('run_id') != root.name or run.get('run_id') != root.name
                or run.get('sealed_trace') is not True or any(summary.get(key) is not True
                    for key in ('sealed_trace', 'replay_verified', 'cleanup_complete'))
                or type(summary.get('experiment')) is not dict
                or any(summary['experiment'].get(key) != run.get(key) for key in ('game_id', 'seed', 'model'))):
            return None
        verification = 'full-replay'
        if run.get('replay_verified') is not True:
            from .console_export import _verified_partial
            if not _verified_partial(root, summary, run):
                return None
            verification = 'verified-prefix'
        if replay_fingerprint(root) != fingerprint:
            return None
        # A new immutable generation can repair even byte-identical projections
        # after corruption, without rewriting a published revision's files.
        content = sha256(_encode(snapshot) + secrets.token_bytes(16)).hexdigest()
        revision = projection_revision(fingerprint, content)
        manifest = projection_manifest(snapshot, revision)
        _manifest(manifest, root.name)
        files = {'manifest.json': _encode(manifest)}
        descriptors = []
        for number in range(1, len(manifest['levels']) + 1):
            detail = projection_level(snapshot, number, revision)
            _detail(detail, manifest, number)
            raw = _encode(detail)
            if len(raw) > _MAX_LEVEL:
                return None
            files[f'level-{number:03d}.json'] = raw
            descriptors.append({'level': number, 'sha256': sha256(raw).hexdigest(), 'size': len(raw)})
        if sum(len(raw) for raw in files.values()) > _MAX_TOTAL:
            return None
        index = {'schema': _SCHEMA, 'run_id': root.name, 'source_revision': projection_revision(fingerprint),
                 'generation_sha256': content, 'revision': revision, 'verification_kind': verification,
                 'manifest': {'sha256': sha256(files['manifest.json']).hexdigest(), 'size': len(files['manifest.json'])},
                 'levels': descriptors}
        base = root / 'console-prepared'
        if not _safe(base):
            return None
        base.mkdir(mode=0o750, exist_ok=True)
        lock_path = base / '.publish.lock'
        if not _safe(lock_path):
            return None
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o640)
        with os.fdopen(descriptor, 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if replay_fingerprint(root) != fingerprint:
                return None
            previous = None
            try:
                old_index, old_manifest, old_directory = _load(root, fingerprint)
                # Reuse only a complete existing generation. This scan occurs
                # during saving, never in a manifest request.
                for item in old_index['levels']:
                    old_detail = _checked(old_directory / f"level-{item['level']:03d}.json",
                                          {key: item[key] for key in ('sha256', 'size')}, _MAX_LEVEL)
                    _detail(old_detail, old_manifest, item['level'])
                return old_manifest
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                try:
                    old = _json(_read(base / 'current.json', _MAX_META))
                    previous = old.get('revision') if type(old) is dict else None
                    if type(previous) is not str or not _HEX.fullmatch(previous):
                        previous = None
                except (OSError, ValueError, TypeError):
                    pass
            destination = base / revision
            created = not destination.exists()
            if destination.exists():
                # Never rewrite a published token, even in the extremely
                # unlikely case of an identical generation digest.
                for name, raw in files.items():
                    if _read(destination / name, _MAX_LEVEL) != raw:
                        return None
            else:
                publish_directory(destination, files)
            if replay_fingerprint(root) != fingerprint:
                if created and _safe(destination) and destination.is_dir():
                    shutil.rmtree(destination)
                return None
            write_atomic_file(base / 'current.json', _encode(index))
            keep = {revision, previous}
            for path in base.iterdir():
                if _HEX.fullmatch(path.name) and path.name not in keep and _safe(path) and path.is_dir():
                    shutil.rmtree(path)
            return manifest
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None
