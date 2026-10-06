"""Operator-owned save-time SDK replay certificates; display artifacts grant no authority.

Content hashes detect corruption and stale evidence under the existing same-UID
operator trust boundary. They are not a MAC or permission to execute a game.
Only verify_for_save performs a replay; certified submission readers never do.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
from hashlib import sha256
from importlib.metadata import distribution
import json
from pathlib import Path
import re
import tempfile

from .broker import ArcObservation, ArcRunReceipt, ArcTransition
from .console_manual_saves import SDK, game_identity
from .game import _read_catalog
from .replay import replay_arc_run
from .run_story.storage import write_atomic_file
from . import solutions

_SCHEMA = 'asterion.prime.p7-solution-certificate/v1'
_REGISTRY = 'asterion.prime.p7-solution-registry/v1'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z')
_MAX_FILE = 64 * 1024 * 1024
_VERIFIERS = ('solutions.py', 'solution_certificates.py', 'replay.py', 'score.py',
              'broker.py', 'game.py', 'observation_state.py', 'private_trace.py', 'live.py',
              'route_composition.py', 'animation_replay.py', 'dynamic_evidence.py',
              'recording_stream.py', 'legacy_verifier_profile.py', 'processing_diagnostics.py')


class SolutionCertificateError(ValueError):
    """Public-safe pending/stale status, without source contents or private paths."""


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return sha256(_bytes(value)).hexdigest()


def _safe(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('solution certificate unavailable')
    return path


def _file_hash(path, maximum=_MAX_FILE):
    _safe(path)
    if not path.is_file() or (maximum is not None and path.stat().st_size > maximum):
        raise ValueError('solution certificate unavailable')
    digest, size = sha256(), 0
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if maximum is not None and size > maximum:
                raise ValueError('solution certificate unavailable')
            digest.update(chunk)
    return digest.hexdigest()


def _json(path, maximum=2 * 1024 * 1024):
    _safe(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('solution certificate unavailable')
    with path.open('rb') as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('solution certificate unavailable')
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError('solution certificate unavailable')
    return value


def _sdk_identity():
    result = {}
    for name, version in SDK.items():
        installed = distribution(name)
        if installed.version != version or installed.files is None:
            raise ValueError('solution verifier unavailable')
        files = [item for item in installed.files
                 if (str(item).endswith(('.py', '.so', '.pyd', '.json', '.yaml', '.csv', '.npy'))
                 and item.parts[0] in {'arc_agi', 'arcengine'}) or item.name == 'METADATA']
        if not files or len(files) > 4096:
            raise ValueError('solution verifier unavailable')
        result[name] = {'version': version, 'contents': _digest([
            (str(item), _file_hash(Path(installed.locate_file(item))))
            for item in sorted(files, key=str)])}
    return result


def capture_verification_identity(arc_root: Path, game_id: str) -> str:
    root = Path(__file__).parent
    # UI, prompts, and unrelated package resources deliberately do not enter
    # this identity. Only the replay/admission implementation is versioned.
    verifier = {name: _file_hash(root / name) for name in _VERIFIERS}
    from asterion.agents.prime import trace
    verifier['trace.py'] = _file_hash(Path(trace.__file__))
    return _digest({'game': game_identity(arc_root, game_id),
                    'sdk': _sdk_identity(), 'verifier': verifier, 'format': _SCHEMA})


def compatible_legacy_identity(arc_root: Path, game_id: str) -> str:
    """Exact 0f4fb448 verifier profile with the *current exact* SDK/game identity.

    This only admits already-issued immutable certificates. New witnesses and
    writes always require capture_verification_identity; no SDK call is made.
    """
    from .legacy_verifier_profile import DEPLOYED_0F4FB448
    return _digest({'game': game_identity(arc_root, game_id), 'sdk': _sdk_identity(),
                    'verifier': DEPLOYED_0F4FB448, 'format': _SCHEMA})


@dataclass(frozen=True, slots=True)
class _ReplayWitness:
    transitions: tuple[ArcTransition, ...]
    receipt: ArcRunReceipt
    observations: tuple[ArcObservation, ...] | None
    verification_identity: str


def verify_for_save(arc_root, game, transitions, receipt, observations, engine_factory):
    """Execute the existing replay once; identity failure leaves certification pending."""
    try:
        before = capture_verification_identity(arc_root, game.game_id)
    except (OSError, ValueError, LookupError, ImportError):
        before = None
    actual = replay_arc_run(transitions, receipt, engine_factory, game=game, observations=observations)
    try:
        after = capture_verification_identity(arc_root, game.game_id) if before is not None else None
    except (OSError, ValueError, LookupError, ImportError):
        after = None
    witness = None if before is None or before != after else _ReplayWitness(transitions, actual, observations, before)
    return actual, witness


def _source_identity(run: Path, *, descriptor=False):
    """Hash explicit source evidence and recorded ancestors; derived output is excluded."""
    stamps, visiting, seen, files, directories = [], set(), set(), [], []
    parent = run.parent
    def visit(current, depth):
        if depth > 8 or current.name in visiting:
            raise ValueError('solution source unavailable')
        if current.name in seen:
            return
        if not _ID.fullmatch(current.name) or not _safe(current).is_dir():
            raise ValueError('solution source unavailable')
        visiting.add(current.name)
        paths = [current / 'summary.json', current / 'trace' / 'prime-trace.jsonl']
        seal = current / 'trace' / 'prime-trace.seal.json'
        if seal.exists() or seal.is_symlink():
            paths.append(seal)
        for name in ('recordings', 'replay-recordings'):
            directory = current / name
            if directory.exists() or directory.is_symlink():
                _safe(directory)
                sessions = list(directory.iterdir())
                if len(sessions) > 8:
                    raise ValueError('solution source unavailable')
                directories.append((str(directory.relative_to(parent)), sorted(item.name for item in sessions)))
                for session in sessions:
                    _safe(session)
                    if not session.is_dir():
                        raise ValueError('solution source unavailable')
                    recordings = list(session.glob('*.jsonl'))
                    if len(recordings) > 8:
                        raise ValueError('solution source unavailable')
                    directories.append((str(session.relative_to(parent)), sorted(item.name for item in recordings)))
                    paths.extend(recordings)
        research = current / 'research'
        if research.exists() or research.is_symlink():
            _safe(research)
            scopes = list(research.iterdir())
            if len(scopes) > 64:
                raise ValueError('solution source unavailable')
            directories.append((str(research.relative_to(parent)), sorted(item.name for item in scopes)))
            for scope in scopes:
                _safe(scope)
                pointer = scope / 'current.json'
                if scope.is_dir() and pointer.exists():
                    value = _json(pointer)
                    revision = value.get('revision')
                    if type(revision) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', revision):
                        raise ValueError('solution source unavailable')
                    paths.extend((pointer, scope / 'revisions' / (revision[7:] + '.json')))
        if len(paths) > 256:
            raise ValueError('solution source unavailable')
        for path in sorted(paths):
            # SDK recordings belong to the independent animation area. Hash
            # every byte with bounded reads; no aggregate evidence quota.
            animation = path.suffix == '.jsonl' and any(
                part in {'recordings', 'replay-recordings'} for part in path.relative_to(current).parts)
            digest = _file_hash(path, maximum=None if animation else _MAX_FILE)
            relative = str(path.relative_to(parent))
            stamps.append((relative, digest))
            stat = path.stat()
            files.append({'path': relative, 'size': stat.st_size,
                          'mtime_ns': stat.st_mtime_ns,
                          'small_sha256': digest if path.suffix == '.json' else None})
        summary = _json(current / 'summary.json')
        diagnostics = summary.get('diagnostics', {})
        links = []
        if type(diagnostics) is dict:
            links.extend(diagnostics.get(key) for key in ('source_run_id', 'recovered_from'))
            links.extend(item.get('source_run_id') for item in diagnostics.get('route_sources', []) if type(item) is dict)
        for line in (current / 'trace' / 'prime-trace.jsonl').read_text().splitlines():
            event = json.loads(line)
            if event.get('kind') == 'arc.run.context':
                links.append(event.get('payload', {}).get('source_run_id'))
        for link in sorted(set(value for value in links if value is not None)):
            if type(link) is not str or not _ID.fullmatch(link):
                raise ValueError('solution source unavailable')
            visit(parent / link, depth + 1)
        visiting.remove(current.name)
        seen.add(current.name)
    visit(run, 0)
    identity = _digest(stamps)
    return {'source_identity': identity, 'files': files,
            'directories': [list(item) for item in directories]} if descriptor else identity


def _metadata_matches(runs, value):
    """Check portable metadata without rereading old SDK grids.

    Small admission files are content-bound. Large historical evidence uses
    portable size/time change hints; selected winners always get full hashes.
    Device, inode and ctime differ across the operator host/guest shared mount.
    """
    try:
        if (type(value) is not dict or set(value) != {'source_identity', 'files', 'directories'}
                or type(value['files']) is not list or len(value['files']) > 2304
                or type(value['directories']) is not list or len(value['directories']) > 576):
            return False
        for item in value['files']:
            if type(item) is not dict or set(item) != {'path', 'size', 'mtime_ns', 'small_sha256'}:
                return False
            relative = Path(item['path'])
            if relative.is_absolute() or '..' in relative.parts:
                return False
            path = _safe(runs / relative)
            stat = path.stat()
            if stat.st_size != item['size']:
                return False
            if item['small_sha256'] is None and stat.st_mtime_ns != item['mtime_ns']:
                return False
            if item['small_sha256'] is not None and _file_hash(path) != item['small_sha256']:
                return False
        for relative, names in value['directories']:
            if (type(relative) is not str or Path(relative).is_absolute() or '..' in Path(relative).parts
                    or type(names) is not list or len(names) > 64
                    or any(type(name) is not str or '/' in name or name in ('.', '..') for name in names)):
                return False
            path = _safe(runs / relative)
            actual = sorted(item.name for item in path.iterdir() if path.name in ('research', 'recordings', 'replay-recordings')
                            or item.suffix == '.jsonl')
            if actual != names:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _record(prefix, receipt, source, identity, model):
    return {'schema': _SCHEMA, 'source_run_id': prefix.source_run_id, 'game_id': prefix.game_id,
            'seed': prefix.seed, 'win_levels': prefix.win_levels, 'levels_completed': prefix.levels_completed,
            'actions': len(prefix.transitions), 'terminal_reason': receipt.terminal_reason,
            'replay_sha256': prefix.replay_sha256, 'source_identity': source,
            'verification_identity': identity, 'model_id': model}


def _store(runs):
    root = _safe(runs / 'solution-certificates')
    root.mkdir(mode=0o700, exist_ok=True)
    for name in ('revisions', 'winners'):
        _safe(root / name).mkdir(mode=0o700, exist_ok=True)
    return root


def _pointer(root, game, model):
    if not _ID.fullmatch(game) or not _ID.fullmatch(model):
        raise ValueError('solution registry unavailable')
    return root / 'winners' / (game + '--' + model + '.json')


def _inventory(runs, candidates):
    return {prefix.source_run_id: _source_identity(runs / prefix.source_run_id, descriptor=True) for prefix in candidates}


def _check_certificate(root, prefix, receipt, source, identity, model, *, compatible_identities=()):
    # The registry chooses a token; certificates cannot select executable paths.
    pointer = _json(_pointer(root, prefix.game_id, model))
    winner = pointer.get('winner', {})
    if winner.get('source_run_id') != prefix.source_run_id:
        raise ValueError('solution certificate unavailable')
    token = winner.get('certificate')
    if type(token) is not str or not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ValueError('solution certificate unavailable')
    record = _json(root / 'revisions' / (token + '.json'))
    recorded_identity = record.get('verification_identity')
    if (recorded_identity not in (identity, *compatible_identities)
            or _digest(record) != token
            or record != _record(prefix, receipt, source, recorded_identity, model)):
        raise ValueError('solution certificate unavailable')
    return pointer


def publish_verified_save(arc_root: Path, run: Path, witness, *, expected_model_id: str):
    return _publish(arc_root, run, witness, expected_model_id=expected_model_id, legacy_inventory=False)


def _publish(arc_root, run, witness, *, expected_model_id, legacy_inventory):
    if type(witness) is not _ReplayWitness:
        raise ValueError('solution verification witness unavailable')
    before = _source_identity(run)
    evidence = solutions._read_one(arc_root, run, witness.receipt.game_id, witness.receipt.seed,
                                   None, expected_model_id, strict_model=True)
    if evidence is None:
        raise ValueError('solution source unavailable')
    prefix, receipt, _ = evidence
    if (prefix.transitions != witness.transitions or receipt != witness.receipt
            or prefix.observations != witness.observations
            or capture_verification_identity(arc_root, prefix.game_id) != witness.verification_identity):
        raise ValueError('solution verification witness stale')
    catalog = tuple(game for game in _read_catalog(arc_root) if game['game_id'] == prefix.game_id)
    summary = _json(run / 'summary.json')
    experiment = solutions.source_experiment(run, summary)
    if (type(experiment) is not dict or experiment.get('model') != expected_model_id
            or experiment.get('prediction_variant') != 'verified'
            or solutions.load_resume_worldmap(run, prefix) is None):
        raise ValueError('solution source not eligible')
    root = _store(run.parent)
    with _safe(root / 'registry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = _pointer(root, prefix.game_id, expected_model_id)
        old = _json(path) if path.exists() else None
        potential = set(_potential_sources(run.parent, catalog, expected_model_id)[prefix.game_id])
        if legacy_inventory:
            candidates = solutions.collect_roster_candidates(arc_root, run.parent, catalog,
                            expected_model_id=expected_model_id)[prefix.game_id]
            inventory = _inventory(run.parent, candidates)
            rejected = {source: _source_identity(run.parent / source, descriptor=True)
                        for source in potential - set(inventory)}
            winner = candidates[0]
            if winner.source_run_id != run.name:
                raise ValueError('solution migration winner changed')
        else:
            inventory = {} if old is None else dict(old.get('eligible_sources', {}))
            rejected = {} if old is None else dict(old.get('rejected_sources', {}))
            if potential != set(inventory) | set(rejected) | {run.name}:
                raise ValueError('solution registry has uncertified changes')
            for source, descriptor in {**inventory, **rejected}.items():
                if source != run.name and not _metadata_matches(run.parent, descriptor):
                    raise ValueError('solution registry has uncertified changes')
            inventory[run.name] = _source_identity(run, descriptor=True)
            rejected.pop(run.name, None)
            winner = prefix
            if old is not None:
                old_source = old['winner']['source_run_id']
                if old_source != run.name:
                    old_evidence = solutions._read_one(arc_root, run.parent / old_source, prefix.game_id,
                                              0, None, expected_model_id, strict_model=True)
                    if old_evidence is None:
                        raise ValueError('solution registry winner unavailable')
                    prior, prior_receipt, _ = old_evidence
                    _check_certificate(root, prior, prior_receipt, _source_identity(run.parent / old_source),
                                       witness.verification_identity, expected_model_id,
                                       compatible_identities=(compatible_legacy_identity(arc_root, prefix.game_id),))
                    if solutions.prefix_rank(prior, catalog[0]) < solutions.prefix_rank(prefix, catalog[0]):
                        winner = prior
        record = _record(prefix, receipt, before, witness.verification_identity, expected_model_id)
        token = _digest(record)
        revision = root / 'revisions' / (token + '.json')
        if revision.exists():
            if _json(revision) != record:
                raise ValueError('solution certificate corrupt')
        else:
            write_atomic_file(revision, _bytes(record))
        if winner.source_run_id == run.name:
            selected = {'source_run_id': run.name, 'certificate': token}
        else:
            selected = old['winner']
        if (_source_identity(run) != before
                or capture_verification_identity(arc_root, prefix.game_id) != witness.verification_identity):
            raise ValueError('solution source changed during certification')
        write_atomic_file(path, _bytes({'schema': _REGISTRY, 'game_id': prefix.game_id,
            'seed': 0, 'model_id': expected_model_id, 'winner': selected,
            'eligible_sources': inventory, 'rejected_sources': rejected}))
    return prefix


def _potential_sources(runs, catalog, model):
    """Metadata-only membership guard; never parse historical trace/recording rows."""
    from .score import digest
    metadata = {game['game_id']: game for game in catalog}
    result = {game: [] for game in metadata}
    children = list(_safe(runs).iterdir())
    if len(children) > 4096:
        raise ValueError('solution registry unavailable')
    def prior(current, seen=()):
        if current.name in seen or len(seen) > 8:
            return None
        summary = _json(current / 'summary.json', 1024 * 1024)
        experiment, diagnostics = summary.get('experiment'), summary.get('diagnostics', {})
        if type(experiment) is dict and experiment.get('prediction_variant') == 'verified':
            return current, experiment
        if type(diagnostics) is dict:
            links = [diagnostics.get('recovered_from')]
            links.extend(item.get('source_run_id') for item in diagnostics.get('route_sources', []) if type(item) is dict)
            for link in links:
                if type(link) is str and _ID.fullmatch(link):
                    value = prior(runs / link, (*seen, current.name))
                    if value is not None:
                        return value
        return None
    for run in children:
        try:
            if run.is_symlink() or not run.is_dir() or not (run / 'summary.json').is_file():
                continue
            summary = _json(run / 'summary.json', 1024 * 1024)
            if (summary.get('run_id') != run.name or any(summary.get(key) is not True
                    for key in ('sealed_trace', 'replay_verified', 'cleanup_complete'))):
                continue
            progress = summary.get('completed_prefix') or summary.get('broker') or {}
            if type(progress) is not dict or type(progress.get('levels_completed')) is not int or progress['levels_completed'] < 1:
                continue
            source = prior(run)
            if source is None:
                continue
            world_run, experiment = source
            game_id = experiment.get('game_id')
            if (type(game_id) is not str or game_id not in metadata or experiment.get('model') != model
                    or type(experiment.get('seed')) is not int or experiment['seed'] != 0):
                continue
            scope = {'game_id': game_id, 'seed': 0, 'win_levels': metadata[game_id]['win_levels'],
                     'run_id': world_run.name, 'attempt_id': world_run.name}
            if not _safe(world_run / 'research' / digest(scope)[7:] / 'current.json').is_file():
                continue
            result[game_id].append(run.name)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return result


def read_certified_roster(arc_root: Path, runs_root: Path, catalog: tuple[dict, ...], *, expected_model_id: str):
    try:
        return _read_certified_roster(arc_root, runs_root, catalog, expected_model_id=expected_model_id)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        raise SolutionCertificateError('saved solution certification pending or stale') from None


def _read_certified_roster(arc_root: Path, runs_root: Path, catalog: tuple[dict, ...], *, expected_model_id: str):
    """Use saved membership stamps and fully authenticate only selected winners."""
    potential = _potential_sources(runs_root, catalog, expected_model_id)
    root, selected = _safe(runs_root / 'solution-certificates'), []
    for metadata in sorted(catalog, key=lambda game: game['game_id']):
        game_id = metadata['game_id']
        path = _pointer(root, game_id, expected_model_id)
        pointer = _json(path) if path.exists() else None
        inventory = {} if pointer is None else pointer.get('eligible_sources', {})
        rejected = {} if pointer is None else pointer.get('rejected_sources', {})
        if type(inventory) is not dict or len(inventory) > 4096:
            raise ValueError('solution registry unavailable')
        if type(rejected) is not dict or len(rejected) + len(inventory) > 4096:
            raise ValueError('solution registry unavailable')
        for value in (*inventory.values(), *rejected.values()):
            if not _metadata_matches(runs_root, value):
                raise ValueError('solution registry source changed')
        if set(potential[game_id]) != set(inventory) | set(rejected):
            raise ValueError('solution certification pending')
        if pointer is None:
            continue
        source_id = pointer.get('winner', {}).get('source_run_id')
        if type(source_id) is not str or not _ID.fullmatch(source_id) or source_id not in inventory:
            raise ValueError('solution registry unavailable')
        run = runs_root / source_id
        evidence = solutions._read_one(arc_root, run, game_id, 0, None, expected_model_id, strict_model=True)
        if evidence is None:
            raise ValueError('solution certified source unavailable')
        prefix, receipt, _ = evidence
        identity = capture_verification_identity(arc_root, game_id)
        verified_pointer = _check_certificate(root, prefix, receipt, _source_identity(run), identity, expected_model_id,
            compatible_identities=(compatible_legacy_identity(arc_root, game_id),))
        if (verified_pointer != pointer or pointer != {'schema': _REGISTRY, 'game_id': game_id,
                'seed': 0, 'model_id': expected_model_id, 'winner': pointer.get('winner'),
                'eligible_sources': inventory, 'rejected_sources': rejected}
                or not _metadata_matches(runs_root, inventory[source_id])):
            raise ValueError('solution registry changed during read')
        selected.append(prefix)
    if _potential_sources(runs_root, catalog, expected_model_id) != potential:
        raise ValueError('solution registry membership changed during read')
    return tuple(selected)


def migrate_legacy_roster(arc_root: Path, runs_root: Path, catalog: tuple[dict, ...], *, expected_model_id: str):
    """Explicit finite local migration: one SDK replay per statically ranked game winner."""
    candidates = solutions.collect_roster_candidates(arc_root, runs_root, catalog, expected_model_id=expected_model_id)
    winners = tuple(values[0] for _, values in sorted(candidates.items()) if values)
    if len(catalog) > 25 or sum(len(prefix.transitions) for prefix in winners) > 38142:
        raise ValueError('solution migration bound exceeded')
    result = []
    for prefix in winners:
        run = runs_root / prefix.source_run_id
        evidence = solutions._read_one(arc_root, run, prefix.game_id, 0, None, expected_model_id, strict_model=True)
        if evidence is None:
            raise ValueError('solution migration source unavailable')
        _, receipt, game = evidence
        with tempfile.TemporaryDirectory(prefix='asterion-p7-certify-') as directory:
            _, witness = verify_for_save(arc_root, game, prefix.transitions, receipt, prefix.observations,
                                         lambda: solutions._fresh_engine(arc_root, game, Path(directory)))
        result.append(_publish(arc_root, run, witness, expected_model_id=expected_model_id, legacy_inventory=True))
    return tuple(result)
