"""Application-only live campaign hints; recordings never establish liveness."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess


_RUN = re.compile(r'p7-live-[0-9]{14}-[0-9a-f]{24}\Z')
_UNIT = re.compile(r'asterion-p7-[0-9a-f]{32}\.service\Z')
_MAX_BYTES = 64 * 1024
_MAX_ACTIVE_GUESTS = 4


def _safe(path):
    return not any(part.is_symlink() for part in (path, *path.parents))


def _pid(value):
    return type(value) is int and 1 <= value <= 2**31 - 1


def live_make_processes(pids: tuple[int, ...]) -> dict:
    """One bounded local process query, never a shell or a global process scan."""
    if not pids or len(pids) > _MAX_ACTIVE_GUESTS or any(not _pid(pid) for pid in pids):
        return {}
    try:
        result = subprocess.run(['ps', '-p', ','.join(str(pid) for pid in pids),
                                 '-o', 'pid=,pgid=,args='],
                                capture_output=True, text=True, timeout=2, check=False)
        if result.returncode not in {0, 1} or len(result.stdout) > 32 * 1024:
            return {}
        output = {}
        for line in result.stdout.splitlines():
            fields = line.split(None, 2)
            if len(fields) != 3:
                return {}
            pid, pgid = int(fields[0]), int(fields[1])
            if pid not in pids or pid in output or not _pid(pgid):
                return {}
            output[pid] = {'pgid': pgid, 'command': fields[2]}
        return output
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def campaign_solving(runs_root: Path, games: set[str], live_units: frozenset[str] | None,
                     *, process_reader=None) -> dict[str, str]:
    """Return only game/run IDs corroborated by Make and an active running unit."""
    if not live_units:
        return {}
    path = runs_root / 'launches' / 'parallel-campaign-state.json'
    try:
        if not _safe(path):
            return {}
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES:
                return {}
            raw = source.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return {}
        state = json.loads(raw)
        if (type(state) is not dict or state.get('stop') is True
                or type(state.get('active')) is not list or len(state['active']) > _MAX_ACTIVE_GUESTS):
            return {}
        candidates = []
        for entry in state['active']:
            if (type(entry) is not dict or entry.get('game') not in games
                    or type(entry.get('run_id')) is not str or not _RUN.fullmatch(entry['run_id'])
                    or type(entry.get('unit')) is not str or not _UNIT.fullmatch(entry['unit'])
                    or entry['unit'] not in live_units or not _pid(entry.get('host_make_pid'))
                    or not _pid(entry.get('host_make_pgid'))
                    or entry.get('host_make_pgid') != entry['host_make_pid']
                    or type(entry.get('args')) is not list or not 2 <= len(entry['args']) <= 32
                    or any(type(arg) is not str or len(arg) > 4096 for arg in entry['args'])
                    or entry['args'][:2] != ['make', 'asterion-prime-p7-level-witness']):
                continue
            args = entry['args']
            if ([arg for arg in args if arg.startswith('GAME=')] != [f"GAME={entry['game']}"]
                    or [arg for arg in args if arg.startswith('ASTERION_PRIME_P7_ATTEMPT_UNIT=')]
                    != [f"ASTERION_PRIME_P7_ATTEMPT_UNIT={entry['unit']}"]):
                continue
            run = runs_root / entry['run_id']
            if not _safe(run) or not run.is_dir() or (run / 'summary.json').exists() or (run / 'summary.json').is_symlink():
                continue
            candidates.append(entry)
        pids = tuple(sorted({entry['host_make_pid'] for entry in candidates}))
        processes = (process_reader or live_make_processes)(pids) if pids else {}
        output, ambiguous = {}, set()
        for entry in candidates:
            if (sum(other['unit'] == entry['unit'] for other in candidates) != 1
                    or sum(other['host_make_pid'] == entry['host_make_pid'] for other in candidates) != 1):
                continue
            process = processes.get(entry['host_make_pid'])
            if type(process) is not dict or process.get('pgid') != entry['host_make_pgid']:
                continue
            command = process.get('command')
            if type(command) is not str:
                continue
            executable, _, arguments = command.partition(' ')
            if Path(executable).name != 'make' or arguments != ' '.join(entry['args'][1:]):
                continue
            game = entry['game']
            if game in output:
                ambiguous.add(game)
            output[game] = entry['run_id']
        return {game: run for game, run in output.items() if game not in ambiguous}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {}
