"""Research entry points are usable without a compulsory note transaction."""
import json
import unittest

from asterion.applications.prime.p7 import prompt
from asterion.applications.prime.p7.research_bridge import ResearchReadServer
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime


class TestAutonomousResearchInterface(unittest.TestCase):
    def test_public_prompts_do_not_include_unverified_death_risk_experiment(self):
        for text in (prompt.build_autonomous_prompt(), prompt.build_notes_prompt(),
                     prompt.P7_SOLVE_PROMPT):
            with self.subTest(prompt=text[:32]):
                self.assertNotIn('游戏可能存在导致死亡或 GAME_OVER 的危险', text)

    def test_death_risk_experiment_is_appended_only_at_research_entry(self):
        from asterion.applications.prime.p7 import operator
        append = getattr(operator, '_append_research_experiment', None)
        self.assertTrue(callable(append))
        experiment = prompt.P7_DEATH_RISK_EXPERIMENT_PROMPT + '\n\n' + prompt.P7_ROLLOUT_EXPERIMENT_PROMPT
        for mode in ('research', 'autonomy', 'solve', 'witness', 'cognition', 'sweep', None):
            with self.subTest(mode=mode):
                environment = {} if mode is None else {'ASTERION_PRIME_P7_RUN_MODE': mode}
                text = append('selected application guidance', environment)
                if mode == 'research':
                    self.assertTrue(text.startswith('selected application guidance\n\n' + experiment))
                    self.assertIn('asterion_p7_context_capacity', text)
                elif mode in ('solve', 'sweep', None):
                    self.assertEqual(text, 'selected application guidance\n\n' + prompt.P7_AUTO_ROLLOUT_INSTRUCTION)
                    self.assertNotIn(experiment, text)
                else:
                    self.assertEqual(text, 'selected application guidance')

    def test_rollout_experiment_keeps_public_guidance_and_authority_unchanged(self):
        experiment = getattr(prompt, 'P7_ROLLOUT_EXPERIMENT_PROMPT', '')
        self.assertIn('replay_deaths', experiment)
        self.assertIn('evaluate_candidates', experiment)
        self.assertIn('未知不等于安全', experiment)
        self.assertIn('不是安全证书', experiment)
        for text in (prompt.build_autonomous_prompt(), prompt.build_notes_prompt(), prompt.P7_SOLVE_PROMPT):
            self.assertNotIn('replay_deaths', text)

    def test_public_prompt_excludes_display_experiment_and_retains_pixel_evidence_guidance(self):
        text = prompt.build_autonomous_prompt()
        self.assertNotIn('向模型展示时用 print(r.display', text)
        self.assertNotIn('不要直接打印整个带棋盘的历史或路线列表', text)
        self.assertIn('stdout 超限时 worker 已丢弃的尾部不在档案中', text)
        self.assertIn('需要区分形状或核对坐标时，可用完整局部像素检查压缩表示', text)
        self.assertIn('r.frame() 返回当前完整二维数值像素', text)
        self.assertIn('r.patches(windows,sequence=None)', text)
        self.assertIn('不要直接打印整个带棋盘的历史或路线列表',
                      prompt.P7_DISPLAY_EXPERIMENT_PROMPT)

    def test_trusted_current_state_exists_before_first_note(self):
        host = P7ResearchRuntime.__new__(P7ResearchRuntime)
        host._memory_instructions = 'trusted task'
        host.actor_context = lambda: {'notes': None, 'observation_ref': {'sequence': 0}}
        result = host._context_memory(commit=False)
        self.assertEqual(result['version'], 'asterion.prime-context-memory/v2')
        self.assertIsNone(result['revision'])
        self.assertFalse(result['commit'])
        self.assertEqual(json.loads(result['content'].split('\n\n', 1)[1])['observation_ref']['sequence'], 0)

    def test_read_module_import_current_geometry_and_diff_work_without_actions(self):
        frames = [[[4, 4], [1, 0]], [[4, 2], [1, 0]]]
        server = ResearchReadServer(context=lambda: {'observation_ref': {'sequence': 1}},
            frame=lambda seq: frames[seq], history=lambda *args: [], artifact=lambda ref: {})
        self.addCleanup(server.close)
        namespace = {}
        exec(server.start(), namespace)
        self.assertTrue(callable(namespace['display']))
        self.assertEqual(namespace['frame'](), frames[1])
        self.assertEqual(namespace['current']()['observation_ref']['sequence'], 1)
        self.assertIn('text', namespace['render']())
        self.assertEqual(namespace['diff'](0)['changed_cell_count'], 1)
        self.assertTrue(namespace['geometry']()['components'])
        self.assertEqual(server.dispatch({'method': 'act', 'args': []})['status'], 'rejected')

    def test_prompt_has_executable_import_and_optional_research(self):
        text = prompt.build_autonomous_prompt()
        self.assertIn('import p7_research as r', text)
        self.assertIn('r.render()', text)
        self.assertIn('stop_on_mismatch', text)
        self.assertNotIn('needs_revision=true', text)

    def test_prompt_delivers_action_interface_prior_with_observation_and_reset_limits(self):
        text = prompt.build_autonomous_prompt()
        for fragment in ('接口先验（不是游戏机制保证）',
                         'ACTION1=上', 'ACTION2=下', 'ACTION3=左', 'ACTION4=右',
                         'ACTION5 通常用于交互、选择等', 'ACTION6 为点击', 'x 是列、y 是行',
                         'ACTION7 为撤销', '通常回退最近一步或此前可撤销状态',
                         '用于修错，不保证精确回退范围', 'RESET 重新开始当前关，与撤销不同',
                         'GAME_OVER 后只能 RESET', '以当前观察的 available_actions 为准',
                         '具体效果用实际反馈修正', '撤销与 RESET 均计费', '不退还已计费'):
            with self.subTest(interface_fact=fragment):
                self.assertTrue(fragment in text, f'missing action-interface fact: {fragment}')

    def test_prompt_requests_strategy_reports_before_paid_actions_and_on_changes(self):
        text = prompt.build_autonomous_prompt()
        for fragment in ('开局先依据自动提供的初始画面、目标和115/100剩余评分空间',
                         '判断现有证据是否足以行动，并选择推进路线与探索投入',
                         '不要默认“先试一下”', '若选择付费探针，事先说明',
                         '为何值得消耗有限步数、什么结果会改变路线选择',
                         '已有信息足够时直接推进，不为确认而重复试探',
                         '不以“未知很多”代替策略判断', '必要时可免费观察或计算',
                         '在首个付费动作前',
                         '选择的游戏策略、依据、预期付费动作代价及主要不确定性',
                         '无法估计时写未知及原因', '实质改变时，在下一批行动前',
                         '策略未变不重复报告', '不改变宿主动作准入或额度',
                         'p7_workspace({op:\'notes\''):
            with self.subTest(requirement=fragment):
                self.assertTrue(fragment in text, f'missing strategy-report requirement: {fragment}')
        self.assertNotIn('写笔记不是行动前置条件', text)
        self.assertNotIn('开局可先免费观察或计算', text)
        self.assertIn('策略和表述形式由你选择', text)
        self.assertIn('日常笔记更新时机由你决定', text)

    def test_prompt_uses_existing_goal_for_concise_action_group_reason(self):
        text = prompt.build_autonomous_prompt()
        for fragment in ('每次提交 p7_execute_plan', 'goal 字段用1–2个短句',
                         '做什么、为何选择这组动作', '实际观察或预期效果',
                         '不为每步重复说明，不额外调用 NOTES',
                         "goal:'这组动作的目的和选择依据'", '主动句', '每句一个判断'):
            with self.subTest(requirement=fragment):
                self.assertTrue(fragment in text, f'missing action-reason requirement: {fragment}')
        self.assertNotIn('80%', text)

    def test_prompt_compares_scoring_room_to_probe_and_progress_cost_without_a_gate(self):
        text = prompt.build_autonomous_prompt()
        for fragment in ('每组付费动作前，对照当前关 additional_paid_actions_preserving_115 和 additional_paid_actions_preserving_100',
                         '已有证据支持的剩余路线估计', '路线代价未知就保持未知',
                         '不为填写估计数字追加查询或计算', '预计接近或超过某条评分空间时',
                         '付费探针能改进后续选择的信息收益', '已知推进、失败或逆转的动作代价',
                         '评分空间或最新有效时间采样显示余量变紧',
                         '已有证据足以支持有价值行动时，优先积极推进',
                         '减少不会改变路线选择的付费试探',
                         '能改变路线选择或避免高代价失败、逆转的必要验证仍可做',
                         '无需消除全部未知后才行动',
                         '评分空间紧不自动要求冒险或低风险方案',
                         '两条余量均为0或已超额时，仍以取得实际得分和通关为目标',
                         '评分空间实质影响本次选择时', '未影响时无需重复两条步数'):
            with self.subTest(requirement=fragment):
                self.assertTrue(fragment in text, f'missing scoring-tradeoff requirement: {fragment}')


class TestOperatorTaskBudget(unittest.TestCase):
    def test_guest_wall_origin_expires_despite_stalled_monotonic_clock(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from asterion.applications.prime.p7 import operator
        wall = [1000.0]
        with patch.object(operator.time, 'monotonic', return_value=100.0), \
             patch.object(operator.time, 'time', side_effect=lambda: wall[0]):
            budget = operator._task_budget({'ASTERION_PRIME_P7_RUN_MODE': 'witness',
                operator._WITNESS_EPOCH_ENV: '1000'}, 1000, 900)
            settlement = operator._settlement_budget(budget)
            signal = operator._WitnessDeadlineSignal(SimpleNamespace(cancelled=False), budget)
            self.assertFalse(signal.cancelled)
            wall[0] = 1900
            self.assertTrue(signal.cancelled)
            self.assertFalse(settlement.expired())
            wall[0] = 2080
            self.assertTrue(settlement.expired())
            wall[0] = 1000
            self.assertTrue(signal.cancelled)

    def test_restricted_budget_rejects_absent_or_expired_wall_origin(self):
        from unittest.mock import patch
        from asterion.applications.prime.p7 import operator
        with patch.object(operator.time, 'monotonic', return_value=100.0), \
             patch.object(operator.time, 'time', return_value=2000.0):
            for value in (None, 'nan', '3000', '1000'):
                env = {'ASTERION_PRIME_P7_RUN_MODE': 'witness'}
                if value is not None:
                    env[operator._WITNESS_EPOCH_ENV] = value
                with self.subTest(value=value), self.assertRaises(operator.P7OperatorError):
                    operator._task_budget(env, 1000, 900)


class TestAutonomousRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_real_kernel_import_then_unpredicted_action_refreshes_trusted_state(self):
        import tempfile
        from pathlib import Path
        from asterion.applications.prime.p7.broker import ArcBroker
        from tests.test_prime_p7_native_broker import _Engine
        from tests.test_prime_p7_research_runtime import _TraceClient, _Signal
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / 'run-autonomous'
        root.mkdir()
        engine = _Engine()
        broker = ArcBroker(engine=engine, action_profile='autonomous')
        broker.bind_history(root.name)
        host = P7ResearchRuntime(broker=broker, trace_client=_TraceClient(), run_root=root,
            run_id=root.name, deadline_seconds=30, event_sink=lambda *_: None,
            learner_profile='autonomous')
        self.addAsyncCleanup(host.close)
        host.set_memory_instructions(prompt.build_autonomous_prompt())
        code = 'import p7_research as r\nassert r.frame() == [[0, 1]]\nprint(r.render()["text"])'
        computed = await host.execute('read-first', code, _Signal())
        self.assertEqual(computed.status, 'ok')
        result = host.method_call('execute_plan', {
            'plan_id': 'first-direct-action', 'start': host.current_context()['observation_ref'],
            'steps': [{'action': {'name': 'ACTION1', 'data': {}}}],
        }, _Signal())
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['stop_reason'], 'executed')
        self.assertFalse(result['feedback'][0]['prediction_present'])
        memory = result['context_memory']
        self.assertIsNone(memory['revision'])
        current = json.loads(memory['content'].split('\n\n')[-1])
        self.assertEqual(current['observation_ref']['sequence'], 1)
        # A transport failure after a possible effect remains inspectable.
        from asterion.applications.prime.p7.action_journal import ActionJournal
        engine.action_journal = ActionJournal(root / 'action-journal', {'run_id': root.name})
        def lost_reply(*args):
            raise RuntimeError('engine reply lost')
        engine.step = lost_reply
        uncertain = host.method_call('execute_plan', {
            'plan_id': 'unknown-action', 'start': host.current_context()['observation_ref'],
            'steps': [{'action': {'name': 'ACTION1', 'data': {}}}],
        }, _Signal())
        self.assertEqual(uncertain['stop_reason'], 'environment-result-unknown')
        self.assertTrue(host.current_context()['environment_result_unknown'])
        self.assertTrue(engine.action_journal.has_unresolved)
        self.assertEqual(host.current_context()['observation_ref']['sequence'], 1)

