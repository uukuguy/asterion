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


def render_cognition_narrative_zh(
    semantic: object, cognition_session: object, *, max_bytes: int = 4096,
) -> str:
    """Render bounded evidence, uncertainty and feedback without granting authority.

    Existing prose is quoted, never automatically translated or reclassified.
    Only canonical kind buckets are read; status convenience buckets duplicate them.
    """
    if type(max_bytes) is not int or max_bytes < 256:
        raise ValueError("narrative budget must be at least 256 bytes")
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
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        if not latest:
            latest = _prose(event.get("explanation"))
        ids = event.get("claim_ids", [])
        if isinstance(ids, (list, tuple)):
            recent_ids.update(i for i in ids if isinstance(i, str))
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
    next_test = question or next((_prose(c.get("next_test")) for c in claims if c.get("status") == "undetermined" and c.get("next_test")), "")
    if not next_test:
        next_test = next((_prose(c.get("next_test")) for c in claims if c.get("next_test")), "根据最新观察选择一个能区分假设的实验。")
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
    if state == "ACTION_EXECUTED":
        add("最新动作尚未分析，不能把预期当作已确认事实。")
    for status, label, count in (("certain", "已确认", 4), ("undetermined", "待验证", 4), ("falsified", "已否定", 2)):
        selected = [c for c in claims if c.get("status") == status]
        if not selected and status == "certain":
            add("已确认：暂无经证据支持的游戏规则。")
        for claim in selected[:count]:
            add(f"{label}：{_prose(claim.get('claim'))}")
        if len(selected) > count:
            add(f"{label}另有 {len(selected) - count} 条；完整记录可按需查询。")
    if not claims:
        context = _prose(semantic.get("natural_language_context"), 360)
        add("现有描述：" + context if context else "当前尚无游戏特定认知；先观察对象、动作和目标。")
    return "\n".join([*lines, footer])
