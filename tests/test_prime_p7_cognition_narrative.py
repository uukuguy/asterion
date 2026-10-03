from __future__ import annotations

import copy
import unittest

from asterion.applications.prime.p7.cognition_narrative import render_cognition_narrative_zh


class TestCognitionNarrative(unittest.TestCase):
    def test_renders_evidence_separately_from_hypotheses_and_recent_feedback(self):
        confirmed = {"id": "move", "kind": "control", "claim": "ACTION1 使横条向上移动。", "status": "certain", "next_test": "检验边界是否阻挡移动。"}
        pending = {"id": "goal", "kind": "success_condition", "claim": "接触色块可能过关。", "status": "undetermined", "next_test": "观察接触后关卡数是否增加。"}
        semantic = {"scope": {"level": 0}, "claims": {"control": [confirmed], "success_condition": [pending], "certain": [confirmed], "undetermined": [pending]}}
        session = {"session": {"state": "ANALYZED", "episode_actions": 2}, "events": [{"type": "cognition.hypothesis.confirmed", "claim_ids": ["move"], "explanation": "横条上移，关卡没有增加。"}]}
        before = copy.deepcopy((semantic, session))
        result = render_cognition_narrative_zh(semantic, session)
        self.assertTrue(result.startswith("当前游戏认知"))
        self.assertIn("第 1 关", result)
        self.assertIn("已确认", result)
        self.assertIn("待验证", result)
        self.assertIn("横条上移，关卡没有增加", result)
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
