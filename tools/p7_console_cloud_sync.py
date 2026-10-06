#!/usr/bin/env python3
"""Push-ready P7 public projections; never reads runner evidence or credentials.

Example: python tools/p7_console_cloud_sync.py --spool /private/cloud-spool --once
Upload separately with the cloud app's upload.mjs --spool argument, or provide
--uploader-script to run it after each complete capture (token stays in env).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


class SyncError(Exception):
    """Closed public error code; underlying responses and paths are not logged."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, raw):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SyncError('source-redirect-rejected')


class HTTPSource:
    def __init__(self, source, timeout=20):
        parsed = urllib.parse.urlsplit(source)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise SyncError('source-must-be-local-http')
        self.source, self.timeout = source.rstrip('/'), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, route):
        try:
            with self.opener.open(self.source + route, timeout=self.timeout) as response:
                value = json.load(response)
                if response.status not in {200, 202} or not isinstance(value, dict):
                    raise SyncError('source-response-invalid')
                return value
        except urllib.error.HTTPError as error:
            raise SyncError('source-changed' if error.code == 409 else 'source-unavailable') from None
        except (OSError, ValueError):
            raise SyncError('source-unavailable') from None


class Capture:
    def __init__(self, spool, fetch):
        self.spool, self.fetch = Path(spool), fetch
        (self.spool / 'objects').mkdir(parents=True, exist_ok=True)
        self.cache = None
        self.completed = {}
        self.previews = None
        try:
            value = json.loads((self.spool / 'index.json').read_bytes())
            if (value.get('schema') == 'asterion.p7.cloud-index/v1'
                    and hashlib.sha256(canonical(value['routes'])).hexdigest() == value['generation']):
                self.cache = value
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def read_cached(self, route):
        if not self.cache or route not in self.cache['routes']:
            return None
        entry = self.cache['routes'][route]
        try:
            raw = gzip.decompress((self.spool / 'objects' / (entry['sha256'] + '.json.gz')).read_bytes())
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                return None
            return json.loads(raw)
        except (OSError, ValueError, KeyError):
            return None

    def put(self, routes, route, value):
        raw = canonical(value)
        digest = hashlib.sha256(raw).hexdigest()
        compressed = gzip.compress(raw, mtime=0)
        path = self.spool / 'objects' / (digest + '.json.gz')
        if not path.exists():
            atomic(path, compressed)
        elif path.read_bytes() != compressed:
            raise SyncError('spool-object-invalid')
        routes[route] = dict(sha256=digest, blobPath=f'p7-console/objects/{digest}.json.gz',
                             contentType='application/json', bytes=len(raw),
                             compressedBytes=len(compressed))
        return value

    def get(self, routes, route):
        return self.put(routes, route, self.fetch(route))

    @staticmethod
    def selected(overview):
        result = {}
        for game in overview['games']:
            for key in ('best_run_id', 'resume_run_id', 'active_run_id', 'solving_run_id', 'recording_run_id'):
                run = game.get(key)
                if run:
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', run):
                        raise SyncError('source-identity-invalid')
                    result[run] = game['game_id']
        return result

    def replay(self, routes, run_id, game_id):
        prefix = f'/api/replay/{run_id}'
        route = prefix + '/manifest'
        manifest = self.get(routes, route)
        if manifest.get('state') == 'loading':
            return None
        if (manifest.get('state') != 'ready' or manifest.get('run_id') != run_id
                or manifest.get('run', {}).get('game_id') != game_id
                or not re.fullmatch('[0-9a-f]{64}', manifest.get('revision', ''))):
            raise SyncError('source-manifest-invalid')
        previous = self.read_cached(route)
        previous_routes = (self.cache or {}).get('routes', {})
        if run_id in self.completed:
            previous, previous_routes = self.completed[run_id]
        if previous == manifest:
            for key, value in previous_routes.items():
                if key.startswith(prefix + '/levels/'):
                    if not (self.spool / 'objects' / (value['sha256'] + '.json.gz')).is_file():
                        raise SyncError('spool-object-missing')
                    routes[key] = value
            return manifest['run']
        revision = manifest['revision']
        for level in manifest['levels']:
            number, total = level['level'], level['frame_count']
            path = f'{prefix}/levels/{number}/{revision}'
            detail = self.get(routes, path)
            if (detail.get('replay_revision') != revision or detail.get('run') != manifest['run']
                    or len(detail.get('levels', [])) != 1):
                raise SyncError('source-changed')
            bucket = detail['levels'][0]
            if bucket.get('level') != number or bucket.get('frame_count', len(bucket.get('frames', []))) != total:
                raise SyncError('source-detail-invalid')
            cursor = bucket.get('frame_page')
            if cursor is None:
                if len(bucket.get('frames', [])) != total:
                    raise SyncError('source-detail-invalid')
                continue
            token = cursor.get('source_token', '')
            if not re.fullmatch('[0-9a-f]{64}', token):
                raise SyncError('source-frame-binding-invalid')
            # Keep only four in-flight pages, irrespective of animation length.
            with ThreadPoolExecutor(max_workers=4) as pool:
                for batch in range(0, total, 128):
                    jobs = [(start, f'{path}/frames/{token}/{start}/32')
                            for start in range(batch, min(total, batch + 128), 32)]
                    pending = [(start, page_path, pool.submit(self.fetch, page_path))
                               for start, page_path in jobs]
                    for start, page_path, future in pending:
                        page = future.result()
                        expected = dict(run_id=run_id, level=number, replay_revision=revision,
                                        source_token=token, frame_count=total, start=start)
                        if (any(page.get(key) != value for key, value in expected.items())
                                or len(page.get('frames', [])) != min(32, total - start)
                                or [frame.get('index') for frame in page['frames']] != list(range(start, min(total, start + 32)))):
                            raise SyncError('source-changed')
                        self.put(routes, page_path, page)
        after = self.fetch(route)
        if after != manifest:
            raise SyncError('source-changed')
        self.completed[run_id] = (manifest, {key: value for key, value in routes.items()
                                             if key.startswith(prefix + '/')})
        return manifest['run']

    def once(self):
        # Revision-bound URLs remain valid for browsers holding an older manifest.
        routes = {path: entry for path, entry in (self.cache or {}).get('routes', {}).items()
                  if re.fullmatch(r'/api/replay/[A-Za-z0-9_-]+/levels/[1-9][0-9]*/[0-9a-f]{64}(?:/frames/[0-9a-f]{64}/[0-9]+/32)?', path)}
        games = self.get(routes, '/api/games')
        overview = self.get(routes, '/api/overview')
        self.get(routes, '/api/state')
        preview_routes = (self.cache or {}).get('routes', {})
        reuse_previews = self.read_cached('/api/games') == games
        if self.previews and self.previews[0] == games:
            reuse_previews, preview_routes = True, self.previews[1]
        for game in games['games']:
            game_id = game['game_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', game_id):
                raise SyncError('source-identity-invalid')
            for level in range(1, game['win_levels'] + 1):
                path = f'/api/preview/{game_id}/{level}'
                if reuse_previews and path in preview_routes:
                    routes[path] = preview_routes[path]
                else:
                    self.get(routes, path)
                if level == 1:
                    routes[f'/api/preview/{game_id}'] = routes[path]
        self.previews = (games, {path: entry for path, entry in routes.items() if path.startswith('/api/preview/')})
        runs, unavailable = [], []
        required = {game.get(key) for game in overview['games'] for key in ('best_run_id', 'resume_run_id')}
        selected = self.selected(overview)
        for run_id, game_id in sorted(selected.items()):
            try:
                run = self.replay(routes, run_id, game_id)
                if run is None:
                    unavailable.append(run_id)
                    if run_id in required:
                        raise SyncError('saved-replay-not-ready')
            except SyncError:
                if run_id in required:
                    raise
                unavailable.append(run_id)
                prefix = f'/api/replay/{run_id}/'
                # Drop partial current-generation routes; retain only complete prior data.
                routes = {path: entry for path, entry in routes.items() if not path.startswith(prefix)}
                previous_routes = (self.cache or {}).get('routes', {})
                if run_id in self.completed:
                    previous_routes = self.completed[run_id][1]
                routes.update({path: entry for path, entry in previous_routes.items() if path.startswith(prefix)})
                run = None
            if run:
                runs.append({key: run[key] for key in ('run_id', 'game_id', 'status')})
        if self.selected(self.fetch('/api/overview')) != selected:
            raise SyncError('source-changed')
        # Same public three-field list, scoped to the captured saved/current runs.
        self.put(routes, '/api/runs', {'runs': runs})
        result = dict(schema='asterion.p7.cloud-index/v1', capturedAt=now(),
                      generation=hashlib.sha256(canonical(routes)).hexdigest(), routes=routes,
                      stats=dict(games=len(games['games']), previews=sum(g['win_levels'] for g in games['games']),
                                 readyRuns=len(runs), unavailableCurrentRuns=sorted(set(unavailable)), framePages=sum('/frames/' in path for path in routes),
                                 uncompressedBytes=sum(v['bytes'] for v in routes.values()),
                                 compressedBytes=sum(v['compressedBytes'] for v in routes.values())))
        atomic(self.spool / 'index.json', canonical(result))
        self.cache = result
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:57515')
    parser.add_argument('--spool', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--uploader-script', type=Path)
    args = parser.parse_args()
    if args.interval < 1 or not 0 < args.timeout <= 20:
        parser.error('interval must be >=1 and timeout must be in (0,20]')
    args.spool.mkdir(parents=True, exist_ok=True)
    with (args.spool / '.sync.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"failed","code":"publisher-already-running"}', flush=True)
            return 1
        capture = Capture(args.spool, HTTPSource(args.source, args.timeout))
        while True:
            started = time.monotonic()
            status = dict(status='failed', capture='failed', upload='not-attempted', observedAt=now())
            atomic(args.spool / 'sync-status.json', canonical({**status, 'status': 'capturing', 'capture': 'running'}))
            try:
                for attempt in range(3):
                    try:
                        result = capture.once()
                        break
                    except SyncError as error:
                        if str(error) != 'source-changed' or attempt == 2:
                            raise
                status['capture'] = 'ready'
                status['generation'] = result['generation']
                if args.uploader_script:
                    completed = subprocess.run(['node', str(args.uploader_script), '--spool', str(args.spool)],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    status['upload'] = 'failed' if completed.returncode else 'ready'
                    if completed.returncode:
                        raise SyncError('upload-failed')
                status.update(status='ready', observedAt=now(), **result['stats'])
            except SyncError as error:
                status['code'] = str(error)
            except (OSError, ValueError, KeyError, TypeError):
                status['code'] = 'capture-failed'
            atomic(args.spool / 'sync-status.json', canonical(status))
            print(json.dumps(status, separators=(',', ':')), flush=True)
            if not args.watch:
                return 0 if status['status'] == 'ready' else 1
            time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == '__main__':
    raise SystemExit(main())
