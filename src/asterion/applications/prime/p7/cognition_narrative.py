"""Deterministic Chinese reading surface for advisory P7 cognition."""

from __future__ import annotations

from collections.abc import Mapping
import unicodedata

from .semantic_cognition import _certainty_claim

_KINDS = ("game_type", "object_role", "control", "success_condition", "rule", "strategy")
_KIND_LABELS = {
    "game_type": "游戏类型",
    "object_role": "画面物件",
    "control": "动作操作",
    "rule": "游戏规则",
    "success_condition": "过关条件",
    "strategy": "规划背景",
}
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
_KNOWN_CONFIRMED_CLAIMS_ZH = {
    "action1_up_current": "在当前关卡，ACTION1使颜色9横带向上移动四格。",
    "action2_down_current": "在当前开放区域，ACTION2使颜色9横带向下移动四格。",
    "action4_right_test": "在当前开放位置，ACTION4使颜色9横带向右移动四格。",
    "align_interact_goal": "当前规划将颜色9横带移到顶部结构附近，并测试ACTION5。",
    "ap2026_right": "ACTION4使颜色9横带向右移动四格。",
    "band-player": "9色横带是可控对象。其他彩色结构固定。它们的具体作用仍在确认。",
    "band-role-current": "9色横带是可控对象。其他彩色结构是固定结构或候选目标。",
    "cardinal-controls": "方向动作在目的地开放时使9色横带沿四格晶格移动。具体方向由当前画面确定。",
    "current-color9-actor": "9色横带是可控的玩家对象。4、6、11色结构是固定结构或目标。",
    "current-action1-up": "在当前关卡，ACTION1使颜色9横带向上移动四格。",
    "current-cardinal-controls": "四个方向动作在目的地开放时按四格晶格移动颜色9横带。",
    "current_band_actor": "颜色9的20×4横带是可控对象。其他颜色结构固定。",
    "current_up": "ACTION1在当前横带位置使横带向上移动四格。",
    "current-grid-band-game": "这是一个网格街机谜题。场景包含可移动的9色横带、12色场地和固定彩色结构。",
    "fresh-l0-move": "目的地开放时，ACTION1使9色横带向上移动四格。",
    "fresh-band-role": "20×4的9色横带是可控对象。其他彩色结构固定。",
    "fresh-color9-role": "9色横带是玩家控制的对象。",
    "fresh-cardinal-control": "四个方向动作在目的地开放时使颜色9横带沿四格晶格移动。",
    "l0-action4-right": "目的地开放时，ACTION4使颜色9横带向右移动四格。",
    "l0-band-actor": "20×4的9色横带是当前网格中的可移动玩家对象。",
    "l0-open-move": "在开放的12色区域，方向动作使颜色9横带移动四格。固定结构不变。",
    "l0_band_motion": "四个方向动作在目的地开放时使颜色9横带沿四格晶格移动。",
    "movement-lattice-current": "目的地开放时，方向动作使颜色9横带移动四格。固定结构保持不变。",
    "l0-target-alignment": "将横带向右移动，使横带覆盖顶部结构的列。然后向上移动。",
    "l0-upward-route": "向顶部彩色结构移动是当前最短路线。移动时避开阻挡重叠。",
    "l1-route-upward": "向顶部彩色结构移动是当前最短路线。移动时避开阻挡重叠。",
    "l1-action4-right-shift": "ACTION4在目的地开放时使颜色9横带向右移动四格。",
    "l1-controls": "ACTION1和ACTION2使横带垂直移动。ACTION3和ACTION4使横带水平移动。",
    "l1-cardinal-lattice": "在开放的颜色12区域，四个方向动作使颜色9横带沿四格晶格移动。固定图形不变。",
    "l1-player-role": "颜色9横带是可控对象。颜色4、6、11结构固定。",
    "l1_scene_band_puzzle": "当前关卡是64×64网格移动谜题。颜色9的20×4横带位于颜色12开放区域。颜色4、6、11结构固定。",
    "level1-action1-up-current": "在当前开放位置，ACTION1使颜色9横带向上移动四格。",
    "level1-action2-down": "在当前开放位置，ACTION2使颜色9横带向下移动四格。",
    "level1-action4-horizontal": "在当前开放区域，ACTION4使颜色9横带向右移动四格。",
    "l1-visual-band-control": "ACTION1到ACTION4在四格晶格上移动20×4的9色横带。",
    "l0_object_roles": "颜色12区域是可通行背景。颜色9横带是玩家对象。颜色4、6、11结构固定。",
    "prime26-bar-fourcell": "在12色开放区域，ACTION1和ACTION2使横带上下移动四格。ACTION3和ACTION4使横带左右移动四格。",
    "prime26-success-touch-target": "过关需要让可控横带接触彩色结构。单纯存活计时不能过关。",
    "prime26-role-color9-actor": "长条形的颜色9横带是可控对象。",
    "prime-right": "ACTION4在开放区域使颜色9横带向右移动四格。",
    "role-background-12": "颜色12区域是可通行背景。",
    "rule-action1-repeatable-up": "在记录的位置，ACTION1使横带向上移动三行。结算后坐标(12,13)为9色。",
    "rule-action2-repeatable-down": "在记录的位置，ACTION2使横带向下移动三行。结算后坐标(12,16)为9色。",
    "rule-action3-repeatable-left": "在记录的位置，ACTION3使横带向左移动四列。结算后坐标(8,16)为9色。",
    "l1_action4_right": "在当前开放位置，ACTION4使颜色9横带向右移动四格。",
    "session-cardinal-step": "方向动作在目的地开放时使颜色9横带移动四格。固定结构不变。",
    "session-band-role": "9色横带是可控对象。其他彩色结构是障碍或候选目标。",
    "session-controls": "四个方向动作控制颜色9横带移动。具体方向由当前画面确定。",
    "success-overlap-target": "过关条件是颜色9与4/6结构接触或重叠。",
    "witness_down": "ACTION2在当前开放区域使颜色9横带向下移动四格。",
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
    if field == "claim" and claim.get("status") == "certain" and isinstance(claim_id, str) and claim_id in _KNOWN_CONFIRMED_CLAIMS_ZH:
        return _KNOWN_CONFIRMED_CLAIMS_ZH[claim_id]
    if field == "claim" and isinstance(claim_id, str) and claim_id in _KNOWN_CLAIMS_ZH:
        text = _KNOWN_CLAIMS_ZH[claim_id]
        return _certainty_claim(text) if claim.get("status") == "certain" else text
    if field == "next_test" and isinstance(claim_id, str) and claim_id in _KNOWN_NEXT_TESTS_ZH:
        return _KNOWN_NEXT_TESTS_ZH[claim_id]
    return _prose(claim.get(field))


def _stable_claims(semantic: Mapping) -> list[Mapping]:
    confirmed = semantic.get("confirmed_knowledge")
    if not isinstance(confirmed, list) or not confirmed:
        groups = semantic.get("claims", {})
        confirmed = []
        if isinstance(groups, Mapping):
            for kind in (*_KINDS, "certain"):
                entries = groups.get(kind, [])
                if isinstance(entries, (list, tuple)):
                    confirmed.extend(
                        claim for claim in entries
                        if isinstance(claim, Mapping) and claim.get("status") == "certain"
                    )
    result: list[Mapping] = []
    seen: set[str] = set()
    for claim in confirmed:
        if not isinstance(claim, Mapping):
            continue
        text = _claim_prose(claim)
        key = " ".join(text.split())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(claim)
    return result


def _ste_sentence(value: str) -> str:
    """Keep the readable surface short: one subject and one action per line."""

    text = " ".join(value.replace("；", "。 ").split())
    if text.startswith("〔历史原文，尚未中文复述〕"):
        return ""
    if text and text[-1] not in "。！？":
        text += "。"
    return text


def render_stable_game_description_zh(semantic: object, *, max_bytes: int = 4096) -> str:
    """Compile confirmed claims into the short Chinese WorldMap description."""

    if not isinstance(semantic, Mapping):
        return "稳定游戏认知（规划背景）\n当前没有可用的已确认游戏规则。"
    stable = _stable_claims(semantic)
    lines = ["稳定游戏认知（规划背景）", "以下句子来自已确认观察。它们是当前规划的主要背景。"]
    if not stable:
        lines.append("当前没有可用的已确认游戏规则。")
        return "\n".join(lines)
    grouped: dict[str, list[str]] = {kind: [] for kind in _KINDS}
    rendered_count = 0
    for claim in stable:
        sentence = _ste_sentence(_claim_prose(claim))
        # A confirmed surface must not repeat tentative wording.  Keep that
        # wording in the underlying ledger until a deterministic translation
        # or a new observation makes it suitable for the stable description.
        if sentence and not any(marker in sentence for marker in ("可能", "也许", "或许")):
            grouped.setdefault(str(claim.get("kind")), []).append(sentence)
            rendered_count += 1
    for kind in _KINDS:
        sentences = grouped.get(kind, [])
        if not sentences:
            continue
        label = _KIND_LABELS.get(kind, "游戏认识")
        lines.append(f"{label}：" + " ".join(sentences[:4]))
    lines.append(f"已编入描述：{rendered_count} 条。其余证据保留在认知记录中。")
    result = "\n".join(lines)
    while len(result.encode()) > max_bytes and len(lines) > 3:
        lines.pop(-2)
        result = "\n".join(lines)
    return result


def _claim_label(claim: Mapping, status: str) -> str:
    """Describe evidence state without treating confidence as proof."""

    if status == "certain":
        return "已确认"
    if status == "falsified":
        return "已否定"
    if claim.get("kind") == "strategy":
        confidence = claim.get("confidence", 0.0)
        if type(confidence) in (int, float) and float(confidence) >= 0.75:
            return "工作策略（可用于规划）"
        return "开放策略（待调整）"
    confidence = claim.get("confidence", 0.0)
    if type(confidence) in (int, float) and float(confidence) >= 0.75:
        return "高置信工作假说（可用于规划）"
    return "开放假说（待证实）"


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
    coverage = semantic.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    review = semantic.get("hypothesis_review")
    review = review if isinstance(review, Mapping) else {}
    layers = semantic.get("cognition_layers")
    layers = layers if isinstance(layers, (list, tuple)) else []
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
    stable_description = render_stable_game_description_zh(semantic)
    for description_line in stable_description.splitlines():
        add(description_line)
    if layers:
        layer_labels = [
            _text(item.get("label"), 48)
            for item in layers
            if isinstance(item, Mapping) and _text(item.get("label"), 48)
        ]
        if layer_labels:
            add("认识层次：" + "、".join(layer_labels[:5]) + "。")
    landscape_count = coverage.get("landscape_claim_count")
    active_landscape_count = coverage.get("active_landscape_claim_count")
    archived_count = coverage.get("archived_claim_count")
    high_confidence = coverage.get("high_confidence_open_count")
    if type(landscape_count) is int or type(high_confidence) is int:
        count_text = str(landscape_count) if type(landscape_count) is int else "当前"
        active_text = str(active_landscape_count) if type(active_landscape_count) is int else count_text
        high_text = str(high_confidence) if type(high_confidence) is int else "若干"
        archive_hint = "完整记录仍可按需查询；" if type(archived_count) is int and archived_count > 0 else ""
        add(
            f"认识覆盖：全量记录 {count_text} 条游戏特定认知，当前工作集 {active_text} 条；"
            f"其中 {high_text} 条是高置信开放假说；"
            f"{archive_hint}它们可以先指导推理和规划，不要求逐条动作验证。"
        )
    duplicate_count = len(review.get("duplicate_candidates", [])) if isinstance(review.get("duplicate_candidates"), list) else 0
    scope_count = len(review.get("same_scope_candidates", [])) if isinstance(review.get("same_scope_candidates"), list) else 0
    exclusive_count = len(review.get("mutually_exclusive_candidates", [])) if isinstance(review.get("mutually_exclusive_candidates"), list) else 0
    if duplicate_count or scope_count or exclusive_count:
        add(
            f"假说整理：重复 {duplicate_count} 组、同类 {scope_count} 组、互斥候选 {exclusive_count} 组；"
            "只提出压缩线索，保留各自证据，不自动删除或合并。"
        )
    else:
        add("假说整理：当前未发现需要压缩或标记互斥的候选组。")
    if latest:
        add("最近反馈：" + latest)
    if recent_action:
        add("最近动作：" + recent_action)
    if state == "ACTION_EXECUTED":
        add("最新动作尚未分析，不能把预期当作已确认事实。")
    strategy_claims = [c for c in claims if c.get("kind") == "strategy"]
    if strategy_claims:
        add("当前规划建议：")
        strategy_limit = min(3, len(strategy_claims))
        for claim in strategy_claims[:strategy_limit]:
            add(f"工作策略（可用于规划）：{_claim_prose(claim)}")
    open_claims = [
        c for c in claims
        if c.get("status") == "undetermined" and c.get("kind") != "strategy"
    ]
    high_open = [c for c in open_claims if type(c.get("confidence")) in (int, float) and float(c.get("confidence")) >= 0.75]
    add(
        f"探索假说（辅助）：当前活动 {len(open_claims)} 条，高置信 {len(high_open)} 条；"
        "只用于补足未知，不作为已确认规则。"
    )
    if open_claims:
        recent_open = [c for c in open_claims if c.get("id") in recent_ids]
        non_bootstrap = [c for c in open_claims if not str(c.get("id", "")).startswith("bootstrap-")]
        unresolved = question or _claim_prose((recent_open or non_bootstrap or open_claims)[0])
        add("关键未决问题：" + unresolved)
    else:
        add("关键未决问题：当前没有待验证假说。")
    if not claims:
        context = _prose(semantic.get("natural_language_context"), 360)
        add("现有描述：" + context if context else "当前尚无游戏特定认知；先观察对象、动作和目标。")
    return "\n".join([*lines, footer])
