"""Deterministic Chinese reading surface for advisory P7 cognition."""

from __future__ import annotations

from collections.abc import Mapping
import unicodedata

_KINDS = ("game_type", "object_role", "control", "success_condition", "rule", "strategy")
_STATES = {
    "OBSERVE": "观察中", "PROPOSE": "已提出假设", "READY": "可尝试解题（不代表已理解全部规则）",
    "EXPERIMENT_SELECTED": "已选实验，等待动作", "ACTION_EXECUTED": "动作已执行，等待分析",
    "ANALYZED": "已分析反馈", "STOPPED": "已停止",
}
_KNOWN_CLAIMS_ZH = {
    "bootstrap-frame-semantics": "初始画面已经观察到，但物体、动作和规则尚未确定。",
    "bootstrap-discrete-actions": "游戏提供离散动作，可以通过比较动作前后的画面来判断效果。",
    "bootstrap-success-condition": "当前还不知道本关的过关条件。",
    "current-grid-band-game": "当前场景是网格街机谜题：9色横带可移动，背景以12色为主，其他彩色结构固定。",
    "band-player": "9色横带是可控对象，4、6、11色结构固定，可能是障碍或目标。",
    "band-role-current": "9色横带是可控对象，其他彩色结构固定，可能是障碍或目标。",
    "current-color9-actor": "9色横带是可控的玩家对象，4、6、11色结构是固定结构或目标。",
    "fresh-band-role": "20×4的9色横带是可控对象，其他彩色结构是固定目标或障碍。",
    "fresh-color9-role": "9色横带是玩家控制的对象。",
    "cardinal-controls": "四个方向动作会在目标开放时按四格晶格移动9色横带，具体方向仍需当前画面确认。",
    "l0-open-move": "在开放的12色区域，方向动作使9色横带移动四格，固定结构不变。",
    "movement-lattice-current": "方向动作会在目标开放时使9色横带移动四格，固定结构保持不变。",
    "current-cardinal-controls": "四个方向动作会使9色横带按四格晶格移动，ACTION1的具体方向仍需确认。",
    "control-action1-direction": "ACTION1可能是方向动作，或使9色横带按固定晶格步长向上移动。",
    "control-action2-distinct": "ACTION2与ACTION1产生不同的场景变化，可用于识别方向控制。",
    "fresh-action1-up": "开放时ACTION1可能使9色横带向上移动四格。",
    "fresh-l0-move": "开放时ACTION1可能使9色横带向上移动四个网格。",
    "current-stepwise-route": "先做一次移动探针，再沿最短晶格路线接近候选目标，并在每步检查过关状态。",
    "route-current": "沿最短方向路线接近最近的候选结构，每次移动后检查是否过关。",
    "fresh-game-grid-band": "这是一个网格移动谜题，9色横带在有界12色区域内移动，其他结构固定。",
    "fresh-grid-band-game": "这是一个网格移动谜题，9色横带位于12色区域，4、6、11色结构暂视为固定。",
    "fresh-l0-grid": "当前关卡包含可移动的20×4 9色横带和固定彩色结构。",
    "gt-bar-alignment-arcade": "场景类似横向对齐街机谜题：长条形对象需要与其他结构对齐。",
    "gt-grid-push-puzzle": "场景也可能是网格推移或对齐谜题，9色对象和其他颜色结构的角色仍待验证。",
    "session-controls": "四个方向动作会在可通行时按四格晶格移动9色横带，具体方向仍需当前画面验证。",
    "contact-goal-current": "横带到达或对齐目标结构时可能完成关卡，权威条件仍待验证。",
    "contact-success": "横带接触或对齐目标结构时可能完成关卡，权威条件仍待验证。",
}
_KNOWN_NEXT_TESTS_ZH = {
    "bootstrap-frame-semantics": "检查初始画面，再与一次受控动作后的画面对比。",
    "bootstrap-discrete-actions": "选择一个离散动作，比较动作前后的画面变化。",
    "bootstrap-success-condition": "测试一次有信息量的动作，并观察关卡和终止信号。",
}


def _text(value: object, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    clean = " ".join("".join(c if not unicodedata.category(c).startswith("C") else " " for c in value).split())
    return clean if len(clean) <= limit else clean[:limit] + "…"


def _prose(value: object, limit: int = 180) -> str:
    text = _text(value, limit)
    if text and not any("\u4e00" <= c <= "\u9fff" for c in text):
        return "〔历史原文，尚未中文复述〕" + text
    return text


def _claim_prose(claim: Mapping, field: str = "claim") -> str:
    claim_id = claim.get("id")
    if field == "claim" and isinstance(claim_id, str) and claim_id in _KNOWN_CLAIMS_ZH:
        return _KNOWN_CLAIMS_ZH[claim_id]
    if field == "next_test" and isinstance(claim_id, str) and claim_id in _KNOWN_NEXT_TESTS_ZH:
        return _KNOWN_NEXT_TESTS_ZH[claim_id]
    return _prose(claim.get(field))


def render_cognition_narrative_zh(
    semantic: object, cognition_session: object, *, max_bytes: int = 4096,
    complete: bool = False,
) -> str:
    """Render bounded evidence, uncertainty and feedback without granting authority.

    Existing prose is quoted, never automatically translated or reclassified.
    Only canonical kind buckets are read; status convenience buckets duplicate them.
    """
    if type(max_bytes) is not int or max_bytes < 256:
        raise ValueError("narrative budget must be at least 256 bytes")
    if type(complete) is not bool:
        raise ValueError("complete must be boolean")
    if not isinstance(semantic, Mapping) or semantic.get("status") == "unavailable":
        return "当前游戏认知\n认知刷新不可用；请先读取 p7_cognition。以当前观察为准，不沿用旧结论。"
    envelope = cognition_session if isinstance(cognition_session, Mapping) else {}
    session = envelope.get("session", envelope)
    session = session if isinstance(session, Mapping) else {}
    scope = semantic.get("scope")
    level = scope.get("level") if isinstance(scope, Mapping) else None
    title = "当前游戏认知" + (f"（第 {level + 1} 关）" if type(level) is int and level >= 0 else "")
    state = _text(session.get("state"), 32)
    lines = [title, "当前状态：" + _STATES.get(state, "尚未确定") + "。"]
    actions = session.get("episode_actions")
    if type(actions) is int:
        lines.append(f"本轮实验动作：{actions} 次；动作次数不代表过关进度。")
    events = envelope.get("events", [])
    events = events if isinstance(events, (list, tuple)) else []
    recent_ids: set[str] = set()
    latest = ""
    recent_action = ""
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        if not recent_action and event.get("type") == "cognition.action.executed":
            action_name = _text(event.get("action_name"), 32)
            changed = event.get("changed")
            if action_name:
                if changed is True:
                    recent_action = f"{action_name} 已执行，画面发生变化。"
                elif changed is False:
                    recent_action = f"{action_name} 已执行，画面没有变化。"
                else:
                    recent_action = f"{action_name} 已执行，等待比较动作前后画面。"
        ids = event.get("claim_ids", [])
        if isinstance(ids, (list, tuple)):
            recent_ids.update(i for i in ids if isinstance(i, str))
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        if not latest:
            latest = _prose(event.get("explanation"))
        if latest:
            break
    claims: list[Mapping] = []
    groups = semantic.get("claims", {})
    seen: set[str] = set()
    if isinstance(groups, Mapping):
        for kind in _KINDS:
            entries = groups.get(kind, [])
            if not isinstance(entries, (list, tuple)):
                continue
            for claim in entries:
                if isinstance(claim, Mapping) and isinstance(claim.get("id"), str) and claim["id"] not in seen:
                    seen.add(claim["id"])
                    claims.append(claim)
    # Stable kind order plus recent relevance; never promote a hypothesis here.
    claims.sort(key=lambda claim: claim["id"] not in recent_ids)
    pending = session.get("pending")
    question = _prose(pending.get("question")) if isinstance(pending, Mapping) else ""
    action = _text(pending.get("action_name"), 32) if isinstance(pending, Mapping) else ""
    next_test = question or next((_claim_prose(c, "next_test") for c in claims if c.get("status") == "undetermined" and c.get("next_test")), "")
    if not next_test:
        next_test = next((_claim_prose(c, "next_test") for c in claims if c.get("next_test")), "根据最新观察选择一个能区分假设的实验。")
    if action:
        next_test = f"已选 {action}；" + next_test
    footer = "下一步：" + next_test + "\n以上为认知记录，不能授权动作；过关以关卡数增加或 WIN 为准。"
    # Reserve the next-test and authority boundary before adding claim prose.
    while len(("\n".join(lines) + "\n" + footer).encode()) > max_bytes:
        next_test = next_test[:len(next_test) // 2]
        footer = "下一步：" + next_test + "\n动作以 broker 校验为准。"
        if not next_test:
            lines = [title]
    def add(line: str) -> None:
        if len(("\n".join([*lines, line, footer])).encode()) <= max_bytes:
            lines.append(line)
    if latest:
        add("最近反馈：" + latest)
    if recent_action:
        add("最近动作：" + recent_action)
    if state == "ACTION_EXECUTED":
        add("最新动作尚未分析，不能把预期当作已确认事实。")
    for status, label, count in (("certain", "已确认", 4), ("undetermined", "待验证", 4), ("falsified", "已否定", 2)):
        selected = [c for c in claims if c.get("status") == status]
        if not selected and status == "certain":
            add("已确认：暂无经证据支持的游戏规则。")
        visible = selected if complete else selected[:count]
        for claim in visible:
            add(f"{label}：{_claim_prose(claim)}")
    if not claims:
        context = _prose(semantic.get("natural_language_context"), 360)
        add("现有描述：" + context if context else "当前尚无游戏特定认知；先观察对象、动作和目标。")
    return "\n".join([*lines, footer])
