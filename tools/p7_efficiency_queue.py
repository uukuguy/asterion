"""Policy for the operator-owned, single-writer P7 efficiency retry queue.

No process, ledger, or model is started here. The private two-slot coordinator
owns persistence and execution. A completed route remains usable throughout.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from asterion.applications.prime.p7.solutions import VerifiedPrefix, _truncate


def level_counts(prefix: VerifiedPrefix) -> tuple[int, ...]:
    counts = []
    previous = 0
    for level in range(1, prefix.levels_completed + 1):
        end = len(_truncate(prefix.transitions, level))
        if end <= previous:
            raise ValueError("Verified prefix lacks a level boundary")
        counts.append(end - previous)
        previous = end
    return tuple(counts)


def level_score(actual: int, baseline: int) -> Decimal:
    if type(actual) is not int or actual <= 0 or type(baseline) is not int or baseline <= 0:
        raise ValueError("Invalid efficiency inputs")
    return min(Decimal(115), Decimal(100) * (Decimal(baseline) / Decimal(actual)) ** 2)


def refresh_tasks(game: dict, row: dict, prefix: VerifiedPrefix | None) -> None:
    """Discover completed eligible levels; mutate only the caller's ledger row."""
    if prefix is None:
        return
    if prefix.game_id != game['game_id'] or prefix.seed != 0 or prefix.win_levels != game['win_levels']:
        raise ValueError("Efficiency source identity mismatch")
    tasks = row.setdefault('efficiency_redos', {})
    for level, actual in enumerate(level_counts(prefix), 1):
        baseline = game['baseline_actions'][level - 1]
        if actual >= baseline and level_score(actual, baseline) < 115:
            tasks.setdefault(str(level), {'level': level, 'seed': prefix.seed,
                'baseline': baseline, 'previous_actions': actual, 'status': 'pending',
                'detected_source_run_id': prefix.source_run_id, 'genuine_attempts': 0})


def _native_anchor(runs_root: Path, prefix: VerifiedPrefix) -> str | None:
    """Only a verified native full route can supply the fixed later-level tail."""
    import json
    from asterion.applications.prime.p7.route_composition import _source, composition_sources
    run = runs_root / prefix.source_run_id
    try:
        summary = json.loads((run / 'summary.json').read_text())
        if summary.get('diagnostics', {}).get('recovery_kind') == 'saved-route-composition':
            sources = composition_sources(run, summary)
            if sources is None:
                return None
            run = sources[-1][1]
        _, native, _, _ = _source(run)
        if native.levels_completed != native.win_levels:
            return None
        return run.name
    except (OSError, ValueError, KeyError, TypeError):
        return None


def next_task(game: dict, row: dict, prefix: VerifiedPrefix | None, *, runs_root: Path) -> dict | None:
    refresh_tasks(game, row, prefix)
    if prefix is None or prefix.levels_completed != prefix.win_levels:
        return None
    anchor = row.get('efficiency_anchor_run_id') or _native_anchor(runs_root, prefix)
    if anchor is None:
        return None
    row['efficiency_anchor_run_id'] = anchor
    counts = level_counts(prefix)
    for key, task in sorted(row.get('efficiency_redos', {}).items(), key=lambda item: int(item[0])):
        if task['status'] != 'pending' or task.get('genuine_attempts', 0):
            continue
        level = int(key)
        baseline = game['baseline_actions'][level - 1]
        actual = counts[level - 1]
        if actual < baseline or level_score(actual, baseline) >= 115:
            task['status'] = 'already-improved'
            continue
        task.update(previous_actions=actual, anchor_run_id=anchor)
        return dict(task)
    return None


def prepare_task(game: dict, task: dict, prefix: VerifiedPrefix) -> dict:
    level = task['level']
    baseline = game['baseline_actions'][level - 1]
    if (task.get('genuine_attempts', 0) != 0 or task['status'] != 'pending'
            or prefix.game_id != game['game_id'] or prefix.seed != task['seed']
            or prefix.levels_completed != game['win_levels'] or not 1 <= level <= game['win_levels']
            or task['baseline'] != baseline):
        raise ValueError('Efficiency task is unavailable')
    restored = len(_truncate(prefix.transitions, level - 1)) if level > 1 else 0
    if level > 1 and not restored:
        raise ValueError('Efficiency restoration boundary is unavailable')
    return {'target_level': level, 'start_level': level, 'restoration_actions': restored,
        'new_action_cap': baseline, 'effective_action_cap': restored + baseline,
        'source_run_id': prefix.source_run_id if level > 1 else None,
        'efficiency_task': dict(task)}


def finish_task(*, operator_root: Path, arc_root: Path, game: dict, task: dict,
                new_run_id: str, previous_prefix: VerifiedPrefix, expected_model_id: str) -> dict:
    """Admit only an SDK-verified improvement, preserving every saved later level.

    The coordinator separately classifies infrastructure failures before calling
    this function. An unfinished/no-improvement result consumes the single redo.
    """
    from asterion.applications.prime.p7.solutions import load_exact_prefix, load_resume_worldmap
    from tools.recover_prime_p7_trace_race import compose_saved_route
    runs = operator_root / '.asterion-private' / 'prime-p7-live'
    level = task['level']
    candidate = load_exact_prefix(arc_root, runs, new_run_id, game['game_id'], task['seed'],
                                  expected_model_id=expected_model_id)
    result = {'status': 'unfinished', 'run_id': new_run_id, 'level': level,
              'genuine_attempts': 1, 'admitted_run_id': None}
    if candidate is None or candidate.levels_completed < level:
        return result
    if candidate.levels_completed != level or load_resume_worldmap(runs / new_run_id, candidate) is None:
        raise ValueError('Efficiency witness scope or prior is unavailable')
    old_counts = level_counts(previous_prefix)
    new_counts = level_counts(candidate)
    baseline = game['baseline_actions'][level - 1]
    result.update(actual_actions=new_counts[-1], previous_actions=old_counts[level - 1],
                  level_score=str(level_score(new_counts[-1], baseline)))
    if new_counts[:-1] != old_counts[:level - 1]:
        raise ValueError('Efficiency witness changed restored levels')
    if level_score(new_counts[-1], baseline) <= level_score(old_counts[level - 1], baseline):
        result['status'] = 'no-improvement'
        return result
    admitted = runs / new_run_id if level == game['win_levels'] else compose_saved_route(
        operator_root=operator_root, arc_root=arc_root, source_run_id=new_run_id,
        suffix_run_id=task['anchor_run_id'], through_level=level)
    complete = load_exact_prefix(arc_root, runs, admitted.name, game['game_id'], task['seed'],
                                 expected_model_id=expected_model_id)
    if complete is None or complete.levels_completed != game['win_levels']:
        raise ValueError('Improved full route failed independent replay')
    expected = (*new_counts, *old_counts[level:])
    if level_counts(complete) != expected:
        raise ValueError('Improved route changed saved later levels')
    result.update(status='improved', admitted_run_id=admitted.name,
                  admitted_actions=len(complete.transitions), admitted_levels=complete.levels_completed)
    return result
