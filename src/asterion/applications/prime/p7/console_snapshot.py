"""Bounded, public-safe replay projection of one possibly incomplete P7 run.

This reader deliberately does not provide the sealed run-story guarantee. Missing
or unaligned evidence remains visible, with fixed warnings rather than private
diagnostics. It never searches replay directories or reconstructs model prose.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceEntry, validate_trace
from asterion.applications.prime.p7.cognition_narrative import (
    color_label, describe_color_names_zh, render_stable_game_description_zh,
)
from asterion.applications.prime.p7.console_events import read_console_events
from asterion.applications.prime.p7.observation_state import ObservationState
from asterion.applications.prime.p7.score import digest
from asterion.capabilities.prime_arc_agi_3_solver import PrimeArcAgi3SolveReceipt


_MAX_FILE = 32 * 1024 * 1024
_MAX_ROWS = 4096
_MAX_FRAMES = 8192
_KINDS = {"game_type", "object_role", "control", "rule", "success_condition", "strategy"}
_STATUSES = {"certain", "falsified", "undetermined"}
_ACTIONS = {"RESET", *(f"ACTION{i}" for i in range(1, 8))}
_PROMPT_SIGNALS = {"tool-guidance", "mechanics-prior", "state-guidance", "application-state", "completion-guidance"}
_OUTPUT_SIGNALS = {"plan", "observation", "prior", "action", "progress"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z")
_PRIVATE_TEXT = re.compile(r"(?:https?://|(?<![A-Za-z0-9])/[A-Za-z0-9_.~+-]+(?:/|(?=\s|[。；，]|$))|[A-Za-z]:\\|\b(?:Bearer\s+|sk-[A-Za-z0-9]|api[_ -]?key\s*[:=]|password\s*[:=]|authorization\s*[:=]))", re.IGNORECASE)
_WARNINGS = {
    "console-events-invalid": "部分实时过程事件无效，仅保留可验证前缀。",
    "summary-missing": "运行摘要缺失或不可读取。",
    "recording-missing": "没有可验证的游戏录制。",
    "recording-ambiguous": "存在多份录制，无法确定本次游戏身份；未合并录制。",
    "recording-invalid": "部分录制格式或身份无效；没有跨缺口连接动作。",
    "evidence-bounded": "证据超过导出大小限制，仅保留允许范围内的数据。",
    "trace-missing": "没有可验证的过程轨迹；游戏录制仍可回放。",
    "trace-invalid": "部分过程轨迹无效，仅保留可验证前缀。",
    "trace-identity": "过程轨迹身份不一致；未用于动作或决策关联。",
    "trace-unsealed": "过程轨迹尚未完成封存，不能视为完整成功证据。",
    "action-unaligned": "部分录制动作没有唯一匹配的轨迹证据。",
    "decision-unaligned": "模型轮次只有审计信号，缺少可证明的动作或关卡关联。",
    "cognition-final": "稳定认知是运行结束时的规划背景快照，未与历史画面对齐。",
    "cognition-missing": "没有身份匹配的稳定认知。",
    "cognition-events-invalid": "部分认知事件格式或会话身份不匹配；未使用这些事件。",
    "restored-cognition-invalid": "恢复来源的认知证据不匹配或超过边界；未用于历史认知。",
    "receipt-missing": "没有经过核对的最终回执；录制进度不等于完整运行成功。",
}


def _integer(value: object, maximum: int = 10**9) -> int | None:
    return value if type(value) is int and 0 <= value <= maximum else None


def _identifier(value: object) -> str | None:
    return value if type(value) is str and _IDENTIFIER.fullmatch(value) else None


def _prose(value: object, limit: int = 600) -> str:
    if type(value) is not str or _PRIVATE_TEXT.search(value):
        return ""
    return " ".join("".join(c for c in value if c >= " " and c != "\x7f").split())[:limit]


def _visual_observations(before: list[list[int]], after: list[list[int]]) -> list[str]:
    """Describe measured pixels only; do not infer objects, rules or model beliefs."""
    def positions(grid):
        result = {}
        for y, row in enumerate(grid):
            for x, color in enumerate(row):
                result.setdefault(color, set()).add((x, y))
        return result

    old, new = positions(before), positions(after)
    area = sum(len(row) for row in before)
    movements, counts = [], []
    for color in sorted(old.keys() | new.keys()):
        start, end = old.get(color, set()), new.get(color, set())
        if start == end or max(len(start), len(end)) > area / 2:
            continue
        label = color_label(color) if 0 <= color < 16 else f"颜色编号{color}"
        if start and end and len(start) == len(end):
            dx = min(x for x, _ in end) - min(x for x, _ in start)
            dy = min(y for _, y in end) - min(y for _, y in start)
            if (dx or dy) and {(x + dx, y + dy) for x, y in start} == end:
                displacement = []
                if dx:
                    displacement.append(f"向{'右' if dx > 0 else '左'}{abs(dx)}格")
                if dy:
                    displacement.append(f"向{'下' if dy > 0 else '上'}{abs(dy)}格")
                movements.append(f"{label}像素整体{'、'.join(displacement)}；形状和数量不变。")
                continue
        if len(start) != len(end):
            counts.append(f"{label}像素数：{len(start)} → {len(end)}。")
        else:
            counts.append(f"{label}像素位置发生变化；数量仍为{len(end)}格。")
    return movements + counts or ["画面发生变化。" if before != after else "结算画面没有像素变化。"]


def _regular(path: Path) -> bool:
    return not any(part.is_symlink() for part in (path, *path.parents)) and path.is_file()


def _read(path: Path, warn: list[str], missing: str) -> str | None:
    try:
        if not _regular(path):
            raise OSError
        if path.stat().st_size > _MAX_FILE:
            warn.append("evidence-bounded")
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        warn.append(missing)
        return None


def _object(path: Path, warn: list[str], missing: str) -> dict:
    raw = _read(path, warn, missing)
    try:
        value = json.loads(raw) if raw is not None else None
    except (ValueError, RecursionError):
        value = None
    if not isinstance(value, dict):
        if raw is not None:
            warn.append(missing)
        return {}
    return value


def _rows(path: Path, warn: list[str], missing: str, invalid: str) -> list[dict | None]:
    raw = _read(path, warn, missing)
    if raw is None:
        return []
    result: list[dict | None] = []
    for index, line in enumerate(raw.splitlines()):
        if index >= _MAX_ROWS:
            warn.append("evidence-bounded")
            break
        try:
            value = json.loads(line)
        except (ValueError, RecursionError):
            value = None
        if not isinstance(value, dict):
            warn.append(invalid)
            result.append(None)
        else:
            result.append(value)
    return result


def _observation(row: dict | None) -> dict | None:
    if row is None or not isinstance(row.get("data"), dict):
        return None
    data = row["data"]
    action = data.get("action_input")
    layers = data.get("frame")
    available = data.get("available_actions")
    game_id = _identifier(data.get("game_id"))
    guid = _identifier(data.get("guid"))
    levels = _integer(data.get("levels_completed"), 100)
    wins = _integer(data.get("win_levels"), 100)
    state = data.get("state")
    timestamp = row.get("timestamp")
    if (not game_id or not guid or levels is None or not wins or levels > wins
        or type(state) is not str or state not in {"NOT_STARTED", "NOT_FINISHED", "WIN", "GAME_OVER"}
        or not isinstance(action, dict) or type(action.get("id")) is not str or action.get("id") not in _ACTIONS
        or not isinstance(action.get("data"), dict)
        or type(timestamp) is not str or len(timestamp) > 64
        or type(available) is not list or any(type(a) is not int or not 1 <= a <= 7 for a in available)
        or available != sorted(set(available))
        or type(layers) is not list or not 1 <= len(layers) <= 64):
        return None
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    for grid in layers:
        if (type(grid) is not list or len(grid) != 64
            or any(type(r) is not list or len(r) != 64
                   or any(type(c) is not int or not 0 <= c <= 255 for c in r) for r in grid)):
            return None
    coordinates = action["data"]
    if action["id"] == "ACTION6":
        if any(type(coordinates.get(k)) is not int or not 0 <= coordinates[k] <= 63 for k in ("x", "y")):
            return None
        coordinates = {k: coordinates[k] for k in ("x", "y")}
    else:
        coordinates = {}
    legacy = {"available_actions": [f"ACTION{i}" for i in available], "frame": layers,
              "levels_completed": levels, "state": state, "win_levels": wins}
    hashes = {digest(legacy)}
    try:
        unified = ObservationState.from_observation({**legacy, **{k: data[k] for k in
            ("hud", "timers", "resources", "entities", "relations", "events") if k in data}})
        hashes.add(digest(unified.to_projection()))
    except (TypeError, ValueError):
        pass
    return {
        "game_id": game_id, "guid": guid, "wins": wins, "levels": levels,
        "state": state, "timestamp": timestamp, "layers": layers,
        "available_actions": [f"ACTION{i}" for i in available],
        "action": action["id"], "data": coordinates,
        "hash": digest(legacy), "hashes": hashes,
    }


def _trace(root: Path, summary: dict, game: str | None, warn: list[str]) -> tuple[list[dict], bool]:
    rows = _rows(root / "trace" / "prime-trace.jsonl", warn, "trace-missing", "trace-invalid")
    previous = None
    identities = None
    retained: list[dict] = []
    for row in rows:
        if row is None:
            break
        required = {"sequence", "kind", "identities", "payload", "previous_sha256", "sha256"}
        if (set(row) != required or type(row["sequence"]) is not int
            or row["sequence"] != len(retained) + 1 or row["previous_sha256"] != previous
            or not isinstance(row["identities"], dict) or not isinstance(row["payload"], dict)
            or not _identifier(row["kind"])):
            warn.append("trace-invalid")
            break
        identity = row["identities"]
        model = summary.get("experiment", {}).get("model") if isinstance(summary.get("experiment"), dict) else None
        if (identity.get("application_id") != "prime.arc-agi-3-solving"
            or (identities is not None and identities != identity)
            or (model is not None and identity.get("model_id") != model)
            or ("run_id" in identity and identity["run_id"] != root.name)
            or ("game_id" in identity and identity["game_id"] != game)
            or (row["kind"] == "arc.run.completed" and "game_id" in row["payload"] and row["payload"]["game_id"] != game)):
            warn.append("trace-identity")
            return [], False
        try:
            canonical = json.dumps({k: row[k] for k in required - {"sha256"}}, sort_keys=True,
                                   separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, UnicodeError, RecursionError):
            warn.append("trace-invalid")
            break
        if len(canonical) > 64 * 1024 or row["sha256"] != "sha256:" + sha256(canonical).hexdigest():
            warn.append("trace-invalid")
            break
        retained.append(row)
        previous = row["sha256"]
        identities = identity
    sealed = False
    if retained and retained[-1]["kind"] == "trace.sealed" and len(retained) == len(rows):
        try:
            validate_trace(tuple(PrimeTraceEntry(**entry) for entry in retained))
            seal = _object(root / "trace" / "prime-trace.seal.json", warn, "trace-invalid")
            sealed = seal.get("entry_count") == len(retained) and seal.get("final_sha256") == retained[-1]["sha256"]
        except Exception:
            warn.append("trace-invalid")
    if not sealed:
        warn.append("trace-unsealed")
    return retained, sealed


def _claim(value: object) -> dict | None:
    if (not isinstance(value, dict) or not _identifier(value.get("id"))
        or type(value.get("kind")) is not str or value.get("kind") not in _KINDS
        or type(value.get("status")) is not str or value.get("status") not in _STATUSES):
        return None
    claim = {key: value[key] for key in ("id", "kind", "status")}
    claim["claim"] = _prose(value.get("claim"))
    claim["evidence_count"] = _integer(value.get("evidence_count")) or 0
    # Only these runtime references authorize a stable completion sentence.
    evidence = value.get("evidence", [])
    claim["evidence"] = [{"reference": e["reference"], "status": "certain"}
                         for e in evidence[:128] if isinstance(e, dict)
                         and e.get("status") == "certain"
                         and type(e.get("reference")) is str
                         and e.get("reference") in {"runtime.levels_completed", "runtime.WIN", "runtime.win"}] if isinstance(evidence, list) else []
    return claim


def _cognition(root: Path, diagnostics: dict, experiment: dict, game: str | None,
               wins: int | None, current_level: int | None, warn: list[str]) -> dict:
    unavailable = {"stable_description": "当前关卡没有可验证的稳定认知。", "scope": "unavailable", "updates": [], "world_map_facts": {}}
    projection = diagnostics.get("semantic_cognition")
    if not isinstance(projection, dict):
        warn.append("cognition-missing")
        return unavailable
    session = projection.get("cognition_session")
    expected_session = root.name + "-cognition"
    if (not isinstance(session, dict) or not isinstance(session.get("session"), dict)
        or session["session"].get("session_id") != expected_session
        or not isinstance(projection.get("semantic"), dict)):
        warn.append("cognition-missing")
        return unavailable
    semantic = projection["semantic"]
    scope = semantic.get("scope")
    if (not isinstance(scope, dict) or scope.get("game_id") != game
        or _integer(scope.get("level"), 100) is None or scope["level"] + 1 != current_level
        or _integer(scope.get("win_levels"), 100) != wins
        or type(scope.get("seed")) is not int or scope["seed"] != experiment.get("seed")):
        warn.append("cognition-missing")
        return unavailable
    groups = semantic.get("claims", {})
    sources = list(semantic.get("confirmed_knowledge", [])) if isinstance(semantic.get("confirmed_knowledge"), list) else []
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, list):
                sources.extend(group[:256])
    claims = {}
    for source in sources[:2048]:
        safe = _claim(source)
        if safe:
            claims[(safe["id"], safe["status"])] = safe
    description = render_stable_game_description_zh({"claims": {"certain": [c for c in claims.values() if c["status"] == "certain"]}})
    action_meanings: dict[str, list[dict]] = {}
    for claim in claims.values():
        if claim["kind"] != "control" or not claim["claim"]:
            continue
        # Only attach unambiguous per-action claims; group/range statements do
        # not identify each member's operation. Keep competing claims visible.
        names = set(re.findall(r"(?<![A-Za-z0-9_])ACTION[1-7](?![0-9])", claim["claim"]))
        if len(names) != 1 or re.search(r"ACTION[1-7]\s*[-/、到至]\s*[1-7]", claim["claim"]):
            continue
        name = next(iter(names))
        entry = {"status": claim["status"], "claim": describe_color_names_zh(claim["claim"])}
        if entry not in action_meanings.setdefault(name, []):
            action_meanings[name].append(entry)
    events = session.get("events", [])
    live_sibling = root.parent / f"cognition-live-{expected_session}.jsonl"
    sibling = root.parent / f"semantic-events-{expected_session}.json"
    if live_sibling.exists() or live_sibling.is_symlink():
        events = _rows(live_sibling, warn, "cognition-events-invalid", "cognition-events-invalid")
    elif sibling.exists() or sibling.is_symlink():
        event_document = _object(sibling, warn, "cognition-events-invalid")
        if event_document.get("schema") == "asterion.prime.p7-semantic-cognition-events/v1":
            events = event_document.get("events", [])
        else:
            events = []
            warn.append("cognition-events-invalid")
    updates = []
    if (not isinstance(events, list) or len(events) > _MAX_ROWS
        or any(not isinstance(e, dict) or e.get("session_id") != expected_session for e in events)):
        warn.append("cognition-events-invalid")
        events = []
    event_statuses = {"cognition.hypothesis.confirmed": "certain", "cognition.hypothesis.falsified": "falsified",
                      "cognition.hypothesis.remains_undetermined": "undetermined"}
    previous = 0
    for event in events:
        sequence = _integer(event.get("sequence"))
        if sequence is None or sequence <= previous:
            warn.append("cognition-events-invalid")
            break
        previous = sequence
        kind = event.get("type")
        if type(kind) is not str or not kind.startswith("cognition.") or not _identifier(kind):
            continue
        status = event_statuses.get(kind)
        changed_claims = event.get("claim_changes", [])
        changes = []
        if isinstance(changed_claims, list):
            for raw_claim in changed_claims[:256]:
                safe = _claim(raw_claim)
                if safe:
                    changes.append({**{key: safe[key] for key in ("id", "kind", "status")},
                                    "claim": describe_color_names_zh(safe["claim"])})
        ids = event.get("claim_ids", [])
        if status and isinstance(ids, list):
            for claim_id in ids[:256]:
                if not _identifier(claim_id) or any(c["id"] == claim_id and c["status"] == status for c in changes):
                    continue
                changes.append({"id": claim_id, "kind": "unknown", "status": status,
                                "claim": describe_color_names_zh(_prose(event.get("explanation")))})
        if changes:
            updates.append({"type": kind, "sequence": sequence, "changes": changes})
    raw_facts = diagnostics.get("world_model_facts", {})
    facts: dict[str, object] = {}
    if (isinstance(raw_facts, dict) and _integer(raw_facts.get("current_level"), 100) == scope["level"]):
        for key in ("conflicts", "hypotheses", "version", "current_level"):
            if _integer(raw_facts.get(key)) is not None:
                facts[key] = raw_facts[key]
        confirmed = raw_facts.get("confirmed")
        if isinstance(confirmed, dict):
            facts["confirmed"] = {k: confirmed[k] for k in ("entities", "mechanics", "relations") if _integer(confirmed.get(k)) is not None}
    warn.append("cognition-final")
    return {"stable_description": description, "scope": "final", "updates": updates,
            "world_map_facts": facts, "action_meanings": action_meanings}


def _receipt(summary: dict, run_id: str, completed: int, actions: int, warn: list[str]) -> dict | None:
    raw = summary.get("receipt")
    if isinstance(raw, dict) and raw:
        try:
            if raw.get("run_id", run_id) != run_id:
                raise ValueError
            expected = PrimeArcAgi3SolveReceipt.create(run_id=run_id, completed_level_count=completed,
                                                      primitive_action_count=actions, partial_game_score=raw.get("partial_game_score"))
            if (raw.get("completed_level_count") != completed or raw.get("primitive_action_count") != actions
                or raw.get("scope") != expected.scope or raw.get("promotion") != expected.promotion
                or raw.get("receipt_sha256") != expected.receipt_sha256.removeprefix("sha256:")):
                raise ValueError
            return {"completed_level_count": completed, "primitive_action_count": actions,
                    "partial_game_score": expected.partial_game_score, "scope": expected.scope, "promotion": expected.promotion}
        except (TypeError, ValueError):
            pass
    warn.append("receipt-missing")
    return None


def _completion_proof(summary: dict, trace: list[dict], game: str | None,
                      wins: int | None, completed: int, actions: list[dict]) -> bool:
    """Require one coherent completed run, rather than summary flag promotion."""
    completions = [entry["payload"] for entry in trace if entry["kind"] == "arc.run.completed"]
    trace_actions = [entry for entry in trace if entry["kind"] == "arc.action"]
    broker = summary.get("broker")
    experiment = summary.get("experiment", {})
    if (len(completions) != 1 or not isinstance(broker, dict) or not isinstance(experiment, dict)
        or not actions or len(trace_actions) != len(actions)
        or any(action["trace_sequence"] is None for action in actions)):
        return False
    completion = completions[0]
    for record in (completion, broker):
        if (_identifier(record.get("game_id")) != game
            or type(record.get("seed")) is not int or record["seed"] != experiment.get("seed")
            or _integer(record.get("win_levels"), 100) != wins
            or _integer(record.get("levels_completed"), 100) != completed
            or _integer(record.get("primitive_actions")) != len(actions)
            or type(record.get("replay_sha256")) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", record["replay_sha256"]) is None
            or record.get("terminal_reason") not in ("level-completed", "game-won")):
            return False
    return all(completion[key] == broker[key] for key in
               ("game_id", "seed", "win_levels", "levels_completed", "primitive_actions", "replay_sha256", "terminal_reason"))


def _source_observations(events: list[dict], warn: list[str]) -> tuple[list[dict], list[dict]]:
    """Use the source's own settled observations, never SDK row positions.

    A completed action/observation pair extends the prefix once. Later repeated
    pixels cannot change an earlier pair, and a gap cannot be bridged by pixels.
    """
    observations: list[dict] = []
    pending = None
    retained = []
    for event in events:
        payload = event['payload']
        if event['kind'] == 'action':
            if pending is not None or not observations or payload['sequence'] != len(observations):
                warn.append('console-events-invalid')
                break
            pending = payload
        elif event['kind'] == 'observation':
            sequence, raw = payload['source_action_sequence'], payload['observation']
            if sequence != len(observations):
                warn.append('console-events-invalid')
                break
            if observations:
                previous = observations[-1]
                if (pending is None or pending['sequence'] != sequence
                    or pending['before_sha256'] != previous['hash']
                    or pending['after_sha256'] != payload['observation_sha256']
                    or pending['levels_completed'] != raw['levels_completed']
                    or raw['win_levels'] != previous['wins']
                    or raw['levels_completed'] not in (previous['levels'], previous['levels'] + 1)
                    or (pending['action'] == 'RESET' and (raw['levels_completed'] != previous['levels'] or raw['state'] != 'NOT_FINISHED'))
                    or (len(raw['frame'][-1]), len(raw['frame'][-1][0])) != (len(previous['layers'][-1]), len(previous['layers'][-1][0]))):
                    warn.append('console-events-invalid')
                    break
            elif pending is not None or raw['levels_completed'] != 0 or raw['state'] != 'NOT_FINISHED':
                warn.append('console-events-invalid')
                break
            observations.append({
                'game_id': event['game_id'], 'wins': raw['win_levels'],
                'levels': raw['levels_completed'], 'state': raw['state'],
                'layers': raw['frame'], 'available_actions': raw['available_actions'],
                'timestamp': '', 'action': pending['action'] if pending else 'RESET',
                'data': pending.get('data', {}) if pending else {},
                'hash': payload['observation_sha256'], 'hashes': {payload['observation_sha256']},
                'source_action_sequence': sequence, 'source_action': pending,
                'event_sequence': event['sequence'],
            })
            pending = None
        retained.append(event)
    return observations, retained


def _restored_cognition_events(root: Path, summary: dict, trace: list[dict], current_events: list[dict],
                               seen: tuple[str, ...] = ()) -> list[dict]:
    """Read only explicitly linked, replay-identical historical actor beliefs."""
    diagnostics = summary.get('diagnostics', {})
    if not isinstance(diagnostics, dict) or diagnostics.get('execution_mode') != 'resumed':
        return []
    source_id = _identifier(diagnostics.get('source_run_id'))
    restored = _integer(diagnostics.get('restoration_actions'), _MAX_ROWS)
    if not source_id or not restored or source_id in (*seen, root.name) or len(seen) >= 8:
        raise ValueError('restored cognition unavailable')
    source = root.parent / source_id
    if source.is_symlink() or not source.is_dir():
        raise ValueError('restored cognition unavailable')
    warnings: list[str] = []
    prior = _object(source / 'summary.json', warnings, 'summary-missing')
    experiment = summary.get('experiment', {})
    prior_experiment = prior.get('experiment', {})
    if (prior.get('schema') != 'asterion.prime.p7-live-private-summary/v1'
        or prior.get('run_id') != source_id or prior.get('sealed_trace') is not True
        or prior.get('replay_verified') is not True
        or not isinstance(experiment, dict) or not isinstance(prior_experiment, dict)
        or not _identifier(experiment.get('model')) or _integer(experiment.get('seed')) is None
        or _integer(prior_experiment.get('seed')) is None
        or any(prior_experiment.get(key) != experiment.get(key) for key in ('game_id', 'model', 'seed'))):
        raise ValueError('restored cognition unavailable')
    game = experiment.get('game_id')
    prior_trace, sealed = _trace(source, prior, game, warnings)
    def prefix(entries, kind='arc.action'):
        actions = [entry['payload'] for entry in entries if entry['kind'] == kind]
        if len(actions) < restored or any(action.get('sequence') != index + 1 for index, action in enumerate(actions[:restored])):
            raise ValueError('restored cognition unavailable')
        return [{key: action.get(key, {} if key == 'data' else None) for key in
                 ('sequence', 'action', 'data', 'before_sha256', 'after_sha256', 'levels_completed')}
                for action in actions[:restored]]
    if not sealed or prefix(trace) != prefix(prior_trace) or prefix(trace) != prefix(current_events, 'action'):
        raise ValueError('restored cognition unavailable')
    events = read_console_events(source, source_id, game, warnings=warnings)
    observations, events = _source_observations(events, warnings)
    if warnings or len(observations) <= restored or prefix(events, 'action') != prefix(prior_trace):
        raise ValueError('restored cognition unavailable')
    inherited = _restored_cognition_events(source, prior, prior_trace, events, (*seen, root.name))
    retained = [event for event in inherited if event['payload']['source_action_sequence'] <= restored]
    for event in events:
        if event['kind'] not in {'model_revision', 'cognition'}:
            continue
        payload = event['payload']
        position = payload['source_action_sequence']
        if position > restored or position >= len(observations):
            continue
        observation = observations[position]
        if (payload['observation_sha256'] != observation['hash']
            or (event['kind'] == 'model_revision' and payload['level'] != min(observation['levels'] + 1, observation['wins']))):
            continue
        retained.append({**event, 'provenance': {'run_id': source_id, 'event_sequence': event['sequence']}})
    if len(retained) > _MAX_ROWS:
        raise ValueError('restored cognition unavailable')
    return retained


def build_console_snapshot(run_root: Path) -> dict[str, object]:
    """Project explicitly selected evidence without modifying it or running P7."""
    if not isinstance(run_root, Path) or run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("console evidence unavailable")
    # Canonicalize the operator-selected directory (macOS /var is an OS
    # symlink); evidence descendants themselves must remain regular files.
    root = run_root.resolve()
    if not _identifier(root.name):
        raise ValueError("console evidence unavailable")
    warn: list[str] = []
    summary = _object(root / "summary.json", warn, "summary-missing")
    if summary and (summary.get("schema") != "asterion.prime.p7-live-private-summary/v1" or summary.get("run_id") != root.name):
        raise ValueError("console evidence unavailable")
    experiment = summary.get("experiment", {})
    experiment = experiment if isinstance(experiment, dict) else {}
    game = _identifier(experiment.get("game_id"))
    wins = None
    observations: list[dict | None] = []
    directory = root / "recordings"
    recordings = sorted(directory.glob("*/*.jsonl")) if directory.is_dir() and not directory.is_symlink() else []
    if len(recordings) > 1:
        warn.append("recording-ambiguous")
    elif not recordings:
        warn.append("recording-missing")
    else:
        rows = _rows(recordings[0], warn, "recording-missing", "recording-invalid")
        observations = [_observation(row) for row in rows]
        valid = [o for o in observations if o]
        identities = {(o["game_id"], o["guid"], o["wins"]) for o in valid}
        if len(identities) > 1 or (valid and game is not None and valid[0]["game_id"] != game):
            observations = []
            warn.append("recording-invalid")
        elif valid:
            game, _, wins = valid[0]["game_id"], valid[0]["guid"], valid[0]["wins"]
        if any(o is None for o in observations):
            warn.append("recording-invalid")
    source_events = read_console_events(root, root.name, game, warnings=warn)
    if source_events and game is None:
        game = source_events[0]["game_id"]
    source_actions = [event["payload"] for event in source_events if event["kind"] == "action"]
    source_mode = any(event["kind"] == "observation" for event in source_events)
    if source_mode:
        observations, source_events = _source_observations(source_events, warn)
        if observations:
            wins = observations[0]["wins"]
            if "recording-missing" in warn:
                warn.remove("recording-missing")
    trace, sealed = _trace(root, summary, game, warn)
    try:
        restored_events = _restored_cognition_events(root, summary, trace, source_events)
    except (ValueError, OSError):
        restored_events = []
        warn.append('restored-cognition-invalid')
    if restored_events and source_mode:
        # Restored beliefs follow their settled observation and precede current
        # actor work at the restoration boundary. Keep original source IDs apart
        # from the merged display cursor; no runtime event is rewritten.
        def event_order(event):
            position = event['payload'].get('source_action_sequence', event['payload'].get('sequence', 0))
            rank = 1 if 'provenance' in event else 0 if event['kind'] in {'action', 'observation'} else 2
            return position, rank
        source_events = sorted([*restored_events, *source_events], key=event_order)
        source_events = [{**event, 'sequence': index,
                          'provenance': event.get('provenance', {'run_id': root.name, 'event_sequence': event['sequence']})}
                         for index, event in enumerate(source_events, 1)]
        observations, source_events = _source_observations(source_events, warn)
    trace_actions = [e for e in trace if e["kind"] == "arc.action"]
    levels: dict[int, dict] = {}

    def level(number: int) -> dict:
        if number not in levels:
            levels[number] = {"level": number, "status": "not-run", "frames": [], "actions": [], "decisions": [],
                              "research_timeline": [], "cognition_timeline": [], "cognition": {"stable_description": "当前关卡没有可验证的稳定认知。", "scope": "unavailable", "updates": [], "world_map_facts": {}}, "receipt": None}
        return levels[number]

    observation_positions: dict[int, dict] = {}
    action_positions: dict[int, dict] = {}
    source_aligned = True
    previous = None
    frame_count = 0
    action_count = 0
    completed = 0
    last_level = None
    for observation in observations:
        if observation is None:
            source_aligned = False
            previous = None
            continue
        if not source_mode and previous and observation["action"] == "RESET" and observation["hash"] == previous["hash"]:
            reset_recorded = source_aligned and any(
                action["sequence"] == action_count + 1 and action["action"] == "RESET"
                and action["before_sha256"] in previous["hashes"] and action["after_sha256"] in observation["hashes"]
                for action in source_actions)
            if not reset_recorded:
                continue
        if frame_count + len(observation["layers"]) > _MAX_FRAMES:
            warn.append("evidence-bounded")
            break
        action_level = previous["levels"] + 1 if previous else observation["levels"] + 1
        action_level = min(action_level, wins or 100)
        bucket = level(action_level)
        new_frames = []
        for grid in observation["layers"]:
            frame_count += 1
            new_frames.append({"id": f"f{frame_count:06d}", "grid": grid, "timestamp": observation["timestamp"],
                               "available_actions": observation["available_actions"],
                               "event_sequence": observation.get("event_sequence"),
                               "state": observation["state"], "levels_completed": observation["levels"]})
        bucket["frames"].extend(new_frames)
        if previous:
            action_count += 1
            if source_mode:
                source_match = observation["source_action"]
            else:
                # Legacy SDK rows lack source identity. Only a unique matching
                # transition can establish position; omitted rows stay ambiguous.
                source_matches = [action for action in source_actions
                                  if action["action"] == observation["action"]
                                  and action.get("data", {}) == observation["data"]
                                  and action["levels_completed"] == observation["levels"]
                                  and action["after_sha256"] in observation["hashes"]]
                source_match = source_matches[0] if len(source_matches) == 1 else None
            if (source_match is None or source_match["sequence"] != action_count
                or source_match["before_sha256"] not in previous["hashes"]):
                source_aligned = False
            matches = [e for e in trace_actions if e["payload"].get("action") == observation["action"]
                       and type(e["payload"].get("before_sha256")) is str and e["payload"]["before_sha256"] in previous["hashes"]
                       and type(e["payload"].get("after_sha256")) is str and e["payload"]["after_sha256"] in observation["hashes"]
                       and e["payload"].get("sequence") == action_count
                       and e["payload"].get("levels_completed") == observation["levels"]
                       and e["payload"].get("data", {}) == observation["data"]]
            matched = matches[0] if len(matches) == 1 else None
            if matched is None:
                warn.append("action-unaligned")
            changed = sum(a != b for row_a, row_b in zip(previous["layers"][-1], observation["layers"][-1], strict=True)
                          for a, b in zip(row_a, row_b, strict=True))
            bucket["actions"].append({"id": f"a{action_count:06d}", "name": observation["action"],
                                      "before_frame": previous["frame_id"], "after_frame": new_frames[-1]["id"],
                                      "data": observation["data"], "levels_completed": observation["levels"],
                                      "changed_cells": changed, "trace_sequence": matched["sequence"] if matched else None,
                                      "visual_observations": _visual_observations(previous["layers"][-1], observation["layers"][-1]),
                                      "decision_id": None, "source_action_sequence": (observation["source_action_sequence"] if source_mode else action_count) if source_aligned else None})
            if source_aligned:
                action_positions[action_count] = bucket["actions"][-1]
        elif observation["action"] != "RESET":
            source_aligned = False
            warn.append("recording-invalid")
        completed = observation["levels"]
        last_level = min(completed + 1, wins or 100)
        if completed >= action_level:
            bucket["status"] = "successful"
        if last_level != action_level:
            level(last_level)["frames"].append(new_frames[-1])
        observation["frame_id"] = new_frames[-1]["id"]
        if source_aligned:
            observation_positions[action_count] = observation
        previous = observation
    target = _integer(experiment.get("target_level"), 100) or 1
    for number in range(1, (wins or max(levels, default=target)) + 1):
        level(number)
    all_actions = [action for bucket in levels.values() for action in bucket["actions"]]
    completion_proof = _completion_proof(summary, trace, game, wins, completed, all_actions)
    receipt = _receipt(summary, root.name, completed, action_count, warn)
    if receipt and not completion_proof:
        receipt = None
        warn.append("receipt-missing")
    diagnostics = summary.get("diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    cognition = _cognition(root, diagnostics, experiment, game, wins, last_level, warn)
    if last_level is not None:
        level(last_level)["cognition"] = cognition
        if level(last_level)["status"] != "successful":
            level(last_level)["status"] = "unsuccessful" if previous and previous["state"] == "GAME_OVER" else "incomplete"
        if receipt and completed >= 1:
            level(min(completed, wins or 100))["receipt"] = receipt
    source_decisions = []
    process_events = []
    decisions_by_id = {}
    for event in source_events:
        payload = event["payload"]
        position = payload.get("source_action_sequence")
        observation = observation_positions.get(position)
        event_observation = observation_positions.get(payload.get('sequence')) if event['kind'] == 'action' else observation
        if event_observation:
            actual = action_positions.get(payload.get('sequence'))
            aligned = (payload.get('observation_sha256') in event_observation['hashes'] if event['kind'] != 'action'
                       else actual is not None and actual['name'] == payload['action']
                       and actual['data'] == payload.get('data', {})
                       and payload['after_sha256'] in event_observation['hashes'])
            number = min(event_observation['levels'] + 1, wins or 100)
            if aligned and (payload.get('level') is None or payload['level'] == number):
                public_payload = dict(payload)
                if event['kind'] == 'observation':
                    public_payload = {key: payload[key] for key in ('source_action_sequence', 'observation_sha256')}
                projected_event = {'event_sequence': event['sequence'], 'kind': event['kind'],
                                   'source_action_sequence': position if position is not None else payload.get('sequence'),
                                   'frame_id': event_observation['frame_id'], 'level': number,
                                   'payload': public_payload}
                if 'provenance' in event:
                    projected_event['provenance'] = event['provenance']
                process_events.append(projected_event)
                if event['kind'] in {'compute_task', 'model_revision', 'plan', 'feedback', 'run_control'}:
                    level(number)['research_timeline'].append(projected_event)
                if event['kind'] == 'model_revision':
                    action = action_positions.get(position)
                    revision = {'scope': 'observation', 'frame_id': event_observation['frame_id'],
                                'action_id': action['id'] if action else None,
                                'source_action_sequence': position, 'cognition_revision': event['sequence'],
                                'event_sequence': event['sequence'], 'stable_description': payload['description_zh'],
                                'cognition_narrative_zh': payload['correction_summary'], 'origin': 'actor'}
                    if 'provenance' in event:
                        revision['provenance'] = event['provenance']
                    level(number)['cognition_timeline'].append(revision)
                    level(number)['cognition'] = {**revision, 'updates': [], 'world_map_facts': {}}
        if event["kind"] == "decision":
            # A summary is public model output at one exact observed position.
            if not observation or payload["observation_sha256"] not in observation["hashes"] or payload["decision_id"] in decisions_by_id:
                continue
            decision = {"id": payload["decision_id"], "source": "p7_decision",
                        **{key: payload[key] for key in ("goal", "basis", "expected", "source_action_sequence", "observation_sha256")},
                        "action_ids": [], "event_sequence": event["sequence"]}
            decisions_by_id[decision["id"]] = decision
            source_decisions.append(decision)
            number = min(observation["levels"] + 1, wins or 100)
            level(number)["decisions"].append(decision)
        elif event["kind"] == "action":
            sequence = payload["sequence"]
            actual = action_positions.get(sequence)
            before, after = observation_positions.get(sequence - 1), observation_positions.get(sequence)
            decision = decisions_by_id.get(payload.get("decision_id"))
            if not actual or not before or not after:
                continue
            if (actual["name"] != payload["action"] or actual["data"] != payload.get("data", {})
                or actual["levels_completed"] != payload["levels_completed"]
                or payload["before_sha256"] not in before["hashes"] or payload["after_sha256"] not in after["hashes"]):
                continue
            if decision and event["sequence"] > decision["event_sequence"]:
                start = decision["source_action_sequence"]
                continuation = action_positions.get(sequence - 1)
                if sequence == start + 1 or (sequence > start + 1 and continuation and continuation["decision_id"] == decision["id"]):
                    actual["decision_id"] = decision["id"]
                    decision["action_ids"].append(actual["id"])
        elif event["kind"] == "cognition":
            if not observation or payload["observation_sha256"] not in observation["hashes"]:
                continue
            action = action_positions.get(position)
            revision = {**payload, "frame_id": observation["frame_id"], "action_id": action["id"] if action else None,
                        "scope": "observation", "event_sequence": event["sequence"]}
            if 'provenance' in event:
                revision['provenance'] = event['provenance']
            bucket = level(min(observation["levels"] + 1, wins or 100))
            bucket["cognition_timeline"].append(revision)
            bucket["cognition"] = {**revision, "updates": [], "world_map_facts": {}}
    if last_level is not None and level(last_level)["cognition"].get("scope") == "observation":
        # A current source revision replaces the legacy final/missing fallback.
        warn = [code for code in warn if code not in {"cognition-final", "cognition-missing"}]
    rounds = []
    for entry in trace:
        if entry["kind"] != "prime.model.round":
            continue
        payload = entry["payload"]
        index = _integer(payload.get("round_index"))
        if index is None:
            continue
        rounds.append({"id": f"d{entry['sequence']:06d}", "round_index": index,
                       "trace_sequence": entry["sequence"], "action_ids": [],
                       "prompt_signals": [s for s in payload.get("prompt_signals", []) if type(s) is str and s in _PROMPT_SIGNALS] if isinstance(payload.get("prompt_signals"), list) else [],
                       "output_signals": [s for s in payload.get("output_signals", []) if type(s) is str and s in _OUTPUT_SIGNALS] if isinstance(payload.get("output_signals"), list) else []})
    if rounds:
        # A single observed level is the only unambiguous level assignment. For
        # multi-level runs the run-level array keeps unaligned rounds visible.
        observed_levels = [item for item in levels.values() if item["frames"]]
        if len(observed_levels) == 1:
            observed_levels[0]["decisions"].extend(rounds)
        warn.append("decision-unaligned")
    replay_verified = (completion_proof and sealed and summary.get("sealed_trace") is True
                       and summary.get("replay_verified") is True)
    successful = receipt is not None and replay_verified and completed >= target
    status = "successful" if successful else "unsuccessful" if previous and previous["state"] == "GAME_OVER" else "incomplete"
    return {"schema": "asterion.arc-agi3-p7-console/v1", "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {"run_id": root.name, "game_id": game, "status": status, "completed_level_count": completed,
                    "seed": _integer(experiment.get("seed")),
                    "win_levels": wins, "target_level": target, "primitive_action_count": action_count,
                    "replay_verified": replay_verified, "sealed_trace": sealed,
                    "model": _identifier(experiment.get("model"))},
            "levels": [levels[n] for n in sorted(levels)], "decisions": source_decisions + rounds,
            "process_events": process_events,
            "warnings": [_WARNINGS[code] for code in dict.fromkeys(warn)]}


__all__ = ("build_console_snapshot",)
