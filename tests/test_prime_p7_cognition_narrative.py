from __future__ import annotations

import copy
import unittest

from asterion.applications.prime.p7.cognition_narrative import (
    render_cognition_narrative_zh,
    render_stable_game_description_zh,
)


class TestCognitionNarrative(unittest.TestCase):
    def test_renders_evidence_separately_from_hypotheses_and_recent_feedback(self):
        confirmed = {"id": "move", "kind": "control", "claim": "ACTION1 使横条向上移动。", "status": "certain", "next_test": "检验边界是否阻挡移动。"}
        pending = {"id": "goal", "kind": "success_condition", "claim": "接触色块可能过关。", "status": "undetermined", "next_test": "观察接触后关卡数是否增加。"}
        semantic = {"scope": {"level": 0}, "claims": {"control": [confirmed], "success_condition": [pending], "certain": [confirmed], "undetermined": [pending]}}
        session = {"session": {"state": "ANALYZED", "episode_actions": 2}, "events": [{"type": "cognition.action.executed", "action_name": "ACTION1", "changed": True}, {"type": "cognition.hypothesis.confirmed", "claim_ids": ["move"], "explanation": "横条上移，关卡没有增加。"}]}
        before = copy.deepcopy((semantic, session))
        result = render_cognition_narrative_zh(semantic, session)
        self.assertTrue(result.startswith("当前游戏认知"))
        self.assertIn("第 1 关", result)
        self.assertIn("已确认", result)
        self.assertIn("探索假说（辅助）", result)
        self.assertIn("横条上移，关卡没有增加", result)
        self.assertIn("最近动作：ACTION1 已执行，画面发生变化", result)
        self.assertIn("下一步", result)
        self.assertEqual(result.count("ACTION1 使横条向上移动。"), 1)
        self.assertEqual((semantic, session), before)

    def test_bounds_unicode_and_marks_missing_cognition(self):
        self.assertIn("认知刷新不可用", render_cognition_narrative_zh(None, None))
        report = {"claims": {"rule": [{"id": str(i), "status": "undetermined", "claim": "长文本" * 800, "next_test": "待验证" * 800} for i in range(40)]}}
        for limit in (512, 1024, 4096):
            with self.subTest(limit=limit):
                result = render_cognition_narrative_zh(report, None, max_bytes=limit)
                self.assertLessEqual(len(result.encode()), limit)
                self.assertIn("下一步", result)

    def test_english_history_is_not_presented_as_translation(self):
        result = render_cognition_narrative_zh({"natural_language_context": "The bar moves."}, None)
        self.assertIn("历史原文", result)
        self.assertIn("The bar moves.", result)

    def test_complete_mode_keeps_stable_description_compact(self):
        claims = [
            {"id": f"certain-{index}", "kind": "control", "claim": f"已确认规则{index}", "status": "certain"}
            for index in range(5)
        ] + [
            {"id": f"open-{index}", "kind": "strategy", "claim": f"待验证假设{index}", "status": "undetermined"}
            for index in range(5)
        ]
        result = render_cognition_narrative_zh(
            {
                "scope": {"level": 0},
                "claims": {"control": claims[:5], "strategy": claims[5:]},
                "confirmed_knowledge": claims[:5],
            },
            None,
            max_bytes=8192,
            complete=True,
        )
        self.assertIn("稳定游戏认知（规划背景）", result)
        self.assertIn("动作操作：", result)
        self.assertIn("已编入描述：5 条", result)
        self.assertIn("探索假说（辅助）", result)
        self.assertNotIn("待验证假设4", result)

    def test_stable_game_knowledge_is_primary_and_hypotheses_are_compact(self):
        stable = [
            {"id": "scene", "kind": "game_type", "claim": "这是网格移动谜题。", "status": "certain"},
            {"id": "move", "kind": "control", "claim": "ACTION2使横带向下移动四格。", "status": "certain"},
            {"id": "goal", "kind": "success_condition", "claim": "过关条件尚未完全确定。", "status": "certain"},
            {"id": "fresh-action1-up", "kind": "control", "claim": "ACTION1 moves the bar upward.", "status": "certain"},
        ]
        hypotheses = [
            {"id": f"open-{index}", "kind": "success_condition", "claim": f"待验证假设{index}", "status": "undetermined"}
            for index in range(20)
        ]
        result = render_cognition_narrative_zh(
            {
                "scope": {"level": 0},
                "claims": {"game_type": [stable[0]], "control": [stable[1]], "success_condition": [stable[2], *hypotheses]},
                "confirmed_knowledge": stable,
                "coverage": {"landscape_claim_count": 23, "active_landscape_claim_count": 23},
            },
            {"session": {"state": "READY"}},
            max_bytes=8192,
            complete=True,
        )
        self.assertLess(result.index("稳定游戏认知（规划背景）"), result.index("探索假说（辅助）"))
        self.assertIn("游戏类型：这是网格移动谜题。", result)
        self.assertIn("动作操作：ACTION2使横带向下移动四格。", result)
        self.assertNotIn("开放时ACTION1可能", result)
        self.assertIn("关键未决问题：", result)
        self.assertNotIn("待验证假设19", result)

    def test_stable_knowledge_is_compiled_into_a_short_worldmap_description(self):
        semantic = {
            "confirmed_knowledge": [
                {"id": "current-grid-band-game", "kind": "game_type", "claim": "English source", "status": "certain"},
                {"id": "current-color9-actor", "kind": "object_role", "claim": "English source", "status": "certain"},
                {"id": "action2_down_current", "kind": "control", "claim": "ACTION2使颜色9横带向下移动四格。", "status": "certain"},
                {"id": "prime26-success-touch-target", "kind": "success_condition", "claim": "English source", "status": "certain"},
            ]
        }
        description = render_stable_game_description_zh(semantic)
        self.assertTrue(description.startswith("稳定游戏认知（规划背景）"))
        self.assertIn("游戏类型：", description)
        self.assertIn("画面物件：", description)
        self.assertIn("动作操作：", description)
        self.assertIn("过关条件：", description)
        self.assertIn("ACTION2使颜色9横带向下移动四格", description)
        self.assertNotIn("可能", description)
        self.assertNotIn("历史原文", description)
        narrative = render_cognition_narrative_zh(semantic, {"session": {"state": "READY"}})
        self.assertNotIn("当前尚无游戏特定认知", narrative)

    def test_high_confidence_open_claims_and_hypothesis_review_are_explicit(self):
        semantic = {
            "scope": {"level": 0},
            "claims": {
                "control": [{"id": "move", "kind": "control", "claim": "ACTION1 moves right.", "status": "undetermined", "confidence": 0.9}],
            },
            "hypothesis_review": {
                "compression_needed": True,
                "duplicate_candidates": [{"claim_ids": ["move", "move-copy"]}],
                "same_scope_candidates": [],
                "mutually_exclusive_candidates": [],
            },
            "coverage": {"landscape_claim_count": 1, "covered_kinds": ["control"], "missing_kinds": ["game_type"]},
        }
        result = render_cognition_narrative_zh(semantic, {"session": {"state": "READY"}})
        self.assertIn("探索假说（辅助）：当前活动 1 条，高置信 1 条", result)
        self.assertIn("假说整理", result)
        self.assertIn("认识覆盖", result)
        self.assertIn("不要求逐条动作验证", result)

    def test_strategy_is_rendered_as_guidance_not_as_fact_hypothesis(self):
        result = render_cognition_narrative_zh(
            {"claims": {"strategy": [{
                "id": "route", "kind": "strategy", "claim": "先验证方向，再走短路线。",
                "status": "undetermined", "confidence": 0.8,
            }]}},
            None,
        )
        self.assertIn("当前规划建议：", result)
        self.assertIn("工作策略（可用于规划）", result)
        self.assertNotIn("工作假说（可用于规划）", result)


class TestNarrativeDelivery(unittest.TestCase):
    def test_initial_context_places_narrative_before_structured_state(self):
        from asterion.applications.prime.p7.operator import _initial_game_context
        class Client:
            def observe(self):
                return {"frame": [[[1]]], "state": "NOT_FINISHED", "available_actions": ["ACTION1"]}
            def status(self):
                return {"primitive_actions": 0}
            def cognition(self):
                return {"semantic": {"natural_language_context": "这是格子游戏，目标尚未确定。"}}
        context = _initial_game_context(Client(), include_prior=False)
        self.assertTrue(context.startswith("## 当前游戏认知（中文）"))
        self.assertIn("这是格子游戏", context)

    def test_action_and_cognition_responses_refresh_narrative_without_query(self):
        import tempfile
        from pathlib import Path
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.semantic_cognition import SemanticCognitionStore
        from tests.test_prime_p7_native_broker import _Engine
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = _Engine()
            (root / "trace").mkdir()
            recorder = PrimeTraceRecorder(root / "trace")
            broker = ArcBroker(engine=engine, semantic_cognition_store=SemanticCognitionStore(root, engine.game_id, engine.seed, engine.win_levels, level=0))
            broker.bind_history("narrative-delivery")
            client = _P7BrokerClient(broker, recorder)
            before = client.observe()
            self.assertIn("cognition_narrative_zh", before)
            proposal = client.cognition_update({"op": "propose", "proposal": {"claims": [{"id": "move", "kind": "control", "subject": "ACTION1", "claim": "ACTION1 可能改变画面。", "reason": "它是可用动作。", "falsifier": "画面不变。", "next_test": "执行一次 ACTION1 并比较。"}]}})
            self.assertIn("ACTION1 可能改变画面", proposal["cognition_narrative_zh"])
            selected = client.cognition_update({"op": "select_experiment", "experiment": {"claim_ids": ["move"], "question": "画面是否改变？", "information_gain": "区分有效动作。", "action": {"name": "ACTION1"}, "expected": {"cell": {"x": 0, "y": 0, "value": 1}}}})
            self.assertIn("已选 ACTION1", selected["cognition_narrative_zh"])
            action = client.act_checked([{"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}}])
            self.assertIn("动作已执行，等待分析", action["cognition_narrative_zh"])
            self.assertNotEqual(action["cognition_narrative_zh"], before["cognition_narrative_zh"])
            self.assertIn("cognition_narrative_zh", client.cognition())
            recorder.close()

    def test_narrative_survives_large_primary_response_and_background_failure(self):
        from asterion.applications.prime.p7.operator import _P7BrokerClient, _json_bytes, _P7_RESPONSE_BUDGET_BYTES, _P7_RESPONSE_HEADROOM_BYTES
        class Broker:
            def planning_background(self):
                raise RuntimeError("private sentinel")
        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        result = client._attach_planning_background({"frame": "x" * 57000})
        self.assertIn("认知刷新不可用", result["cognition_narrative_zh"])
        self.assertNotIn("private sentinel", str(result))
        self.assertLessEqual(_json_bytes(result), _P7_RESPONSE_BUDGET_BYTES - _P7_RESPONSE_HEADROOM_BYTES)

    def test_prompts_require_chinese_and_no_redundant_refresh_queries(self):
        from asterion.applications.prime.p7.prompt import build_strategy_prompt
        for strategy in ("replay", "explore", "cognition"):
            prompt = build_strategy_prompt(None, strategy)
            self.assertIn("请用中文", prompt)
            self.assertIn("cognition_narrative_zh", prompt)
            self.assertIn("id`、`kind`", prompt)
            self.assertIn("expected_result", prompt)
            self.assertIn("expected_distinguishing_result", prompt)
            self.assertIn("不要使用", prompt)
            self.assertIn("`supports`", prompt)
            self.assertNotIn("and again after every action or cognition update", prompt)
