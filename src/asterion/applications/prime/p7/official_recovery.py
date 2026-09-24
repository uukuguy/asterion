"""GET-only recovery of a previously confirmed normal official closure.

The public archive corroborates a private lifecycle record; it cannot establish
normal closure by itself. No SDK, credentials, game or model host is loaded.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import urllib.request

from .official import OfficialError
from .official_result import OfficialGameResult, OfficialReceipt

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', re.ASCII)
_LIMIT = 2 * 1024 * 1024


def _id(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError
    return value


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError
    return float(value)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _load(data: bytes) -> dict:
    if len(data) > _LIMIT:
        raise ValueError
    value = json.loads(data, object_pairs_hook=_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
        raise ValueError
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError


def _fetch(card_id: str) -> bytes:
    request = urllib.request.Request(
        'https://arcprize.org/api/v3/scorecards/' + _id(card_id),
        headers={'Accept': 'application/json'}, method='GET')
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
        return response.read(_LIMIT + 1)


def _directory(path: Path) -> int:
    """Walk using no-follow descriptors, preserving the directory for publication."""
    if '..' in path.parts:
        raise ValueError
    path = path.absolute()
    if (path.name != 'official-recovery.json' or len(path.parts) < 5
            or path.parts[-4:-2] != ('.asterion-private', 'prime-p7-official')):
        raise ValueError
    _id(path.parent.name)
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _record(directory: int) -> dict:
    descriptor = os.open('official-recovery.json', os.O_RDONLY | os.O_NOFOLLOW,
                         dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError
        value = _load(stream.read(_LIMIT + 1))
    if (value.get('schema') != 'asterion.prime.p7-official-recovery/v1'
            or value.get('status') != 'recovery-required'
            or value.get('normal_close_confirmed') is not True
            or value.get('aborted') is not False
            or value.get('unattempted_game_ids') != []):
        raise ValueError
    _id(value['card_id'])
    for key in ('game_ids', 'selected_game_ids'):
        ids = value[key]
        if type(ids) is not list or not ids or ids != sorted({_id(v) for v in ids}):
            raise ValueError
    if not set(value['selected_game_ids']).issubset(value['game_ids']):
        raise ValueError
    guids = value['guids']
    if (type(guids) is not dict or set(guids) != set(value['selected_game_ids'])
            or any(type(v) is not str or not v for v in guids.values())):
        raise ValueError
    return value


def _validate(record: dict, card: dict) -> OfficialReceipt:
    """Apply official_result row invariants directly to archive JSON.

    Recovery additionally requires the complete catalog, one run per row,
    nonnegative scores and explicit reset counts. This archive evidence must
    corroborate the original lifecycle record without fabricating an SDK session.
    """
    if card.get('card_id') != record['card_id'] or card.get('competition_mode') is not True:
        raise ValueError
    rows = card['environments']
    if type(rows) is not list:
        raise ValueError
    selected = set(record['selected_game_ids'])
    seen = set()
    games = {}
    for row in rows:
        game = _id(row['id'])
        if game in seen or game not in record['game_ids']:
            raise ValueError
        seen.add(game)
        runs = row['runs']
        if type(runs) is not list or len(runs) != 1:
            raise ValueError
        run = runs[0]
        if run.get('id') not in (None, game):
            raise ValueError
        guid = run['guid']
        if type(guid) is not str or not guid:
            raise ValueError
        score = _number(run['score'])
        actions, levels, resets = (_count(run[k]) for k in ('actions', 'levels_completed', 'resets'))
        state = run['state']
        completed = run['completed']
        if (state not in ('WIN', 'GAME_OVER', 'NOT_PLAYED', 'NOT_FINISHED')
                or type(completed) is not bool or completed != (state == 'WIN')
                or (state == 'WIN' and levels == 0)
                or (state == 'NOT_PLAYED' and levels != 0)):
            raise ValueError
        if game not in selected:
            if (state != 'NOT_FINISHED' or completed
                    or score != 0 or actions != 0 or levels != 0 or resets != 0):
                raise ValueError
        else:
            if guid != record['guids'][game]:
                raise ValueError
            games[game] = OfficialGameResult(game, score, state, completed, levels, actions)
    if seen != set(record['game_ids']) or set(games) != selected:
        raise ValueError
    ordered = tuple(games[game] for game in record['selected_game_ids'])
    score = _number(card['score'])
    catalog_count, selected_count = len(seen), len(selected)
    skipped = catalog_count - selected_count
    digest = sha256(_json(dict(card_id=record['card_id'], competition_mode=True,
                              score=score, games=[asdict(g) for g in ordered],
                              catalog_count=catalog_count, selected_count=selected_count,
                              played_runs=selected_count, skipped_count=skipped,
                              guids=record['guids'])).encode()).hexdigest()
    return OfficialReceipt(record['card_id'], score, ordered, digest,
                           catalog_count, selected_count, selected_count, skipped)


def _publish(directory: int, receipt: OfficialReceipt) -> None:
    temporary = '.recovery-' + secrets.token_hex(12)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(_json(receipt.to_dict()) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and cannot replace an existing entry.
        os.link(temporary, 'official-receipt.json', src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False)
        os.fsync(directory)
    finally:
        os.unlink(temporary, dir_fd=directory)


def recover_official_receipt(recovery_path: Path | str) -> OfficialReceipt:
    """Recover one existing card, issuing only one bounded, unauthenticated GET."""
    directory = None
    try:
        directory = _directory(Path(recovery_path))
        record = _record(directory)
        # Reject occupied receipt names before any HTTP, including dangling links.
        try:
            os.stat('official-receipt.json', dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError
        receipt = _validate(record, _load(_fetch(record['card_id'])))
        _publish(directory, receipt)
        return receipt
    except Exception:
        raise OfficialError('official recovery unavailable') from None
    finally:
        if directory is not None:
            os.close(directory)
