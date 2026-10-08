"""Actor score facts preserve original autonomy and local accounting."""
from pathlib import Path
import unittest

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import ArcGameContract, P7GameSelection
from asterion.applications.prime.p7.prompt import build_autonomous_prompt
from asterion.applications.prime.p7.score import partial_game_score
from tests.test_prime_p7_solver import P7SolverFixture
from tests.test_prime_p7_native_broker import _Engine


def game(target=6, levels=9):
    return P7GameSelection('ls20-9607627b', 0, target,
                           _metadata_baseline_actions=(10,) * levels,
                           _metadata_win_levels=levels)


class _ScoreEngine(_Engine):
    def observe(self):
        value = super().observe()
        value['available_actions'].append('ACTION7')
        return value


class TestP7ScorePlanning(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.engine = _ScoreEngine(win_levels=9)
        self.broker = ArcBroker(engine=self.engine, game=game(), action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver.broker = self.broker
        self.solver.learner_profile = 'autonomous'

    def minimal(self, name, steps=None):
        return {'plan_id': name, 'start': self.solver.current_context()['observation_ref'],
                'steps': steps or [{'action': {'name': 'ACTION1', 'data': {}}}]}

    def scoring(self):
        budget = self.solver.current_context()['budget']
        self.assertIn('scoring', budget)
        return budget['scoring']

    def test_full_game_objective_and_all_baselines_do_not_extend_stop_boundary(self):
        facts = self.scoring()
        self.assertEqual(facts['objective'], {'levels': 9, 'score': '100.000000'})
        self.assertEqual(facts['baseline_actions'], [10] * 9)
        self.assertEqual(facts['completed_levels'], [])
        self.assertEqual(facts['current_level'], {'level': 1, 'paid_actions': 0, 'baseline': 10})
        self.assertEqual(facts['full_game_score'], '0.000000')
        self.assertEqual(self.solver.current_context()['budget']['target_level'], 6)
        facts['baseline_actions'][0] = 1
        self.assertEqual(self.scoring()['baseline_actions'], [10] * 9)
        self.assertEqual(self.engine.calls, [])
        from asterion.applications.prime.p7.actor_projection import project_actor_context
        self.assertEqual(project_actor_context(self.solver.current_context())['budget']['scoring'], self.scoring())
        # Test the existing sixth-level stop using a real sequential prefix.
        for level in range(6):
            self.engine.level_after = len(self.engine.calls) + 1
            self.assertEqual(self.solver.execute_plan(self.minimal(str(level)))['applied_count'], 1)
        self.assertEqual(self.solver.execute_plan(self.minimal('after-stop'))['applied_count'], 0)
        self.assertEqual(len(self.engine.calls), 6)
        self.assertEqual(self.scoring()['full_game_score'], '46.666667')
        self.assertEqual(self.scoring()['objective']['score'], '100.000000')

    def test_paid_failed_probe_reset_and_undo_accumulate_until_completion(self):
        self.solver.execute_plan(self.minimal('failed-prediction', steps=[{
            'action': {'name': 'ACTION1', 'data': {}}, 'expect': {'state': 'WIN'}}]))
        self.solver.execute_plan(self.minimal('reset', steps=[{'action': {'name': 'RESET', 'data': {}}}]))
        self.solver.execute_plan(self.minimal('undo', steps=[{'action': {'name': 'ACTION7', 'data': {}}}]))
        self.assertEqual(self.scoring()['current_level']['paid_actions'], 3)
        self.assertEqual(self.scoring()['full_game_score'], '0.000000')
        self.engine.level_after = 4
        feedback = self.solver.execute_plan(self.minimal('complete'))
        facts = feedback['budget']['scoring']
        self.assertEqual(facts, self.scoring())
        self.assertEqual(facts['completed_levels'], [{'level': 1, 'paid_actions': 4, 'baseline': 10,
                                                     'level_score': '115.000000'}])
        self.assertEqual(facts['current_level']['paid_actions'], 0)
        self.assertEqual(facts['full_game_score'], partial_game_score(4, game(target=1)))
        # A new projection/controller sees the same paid prefix, not a new counter.
        from asterion.applications.prime.p7.solver import Solver
        reconstructed = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id='run-1', attempt_id='attempt-1',
            event_sink=lambda *args: None, learner_profile='autonomous')
        self.assertEqual(reconstructed.current_context()['budget']['scoring'], facts)
        self.solver.execute_plan(self.minimal('next'))
        self.assertEqual(self.scoring()['current_level']['paid_actions'], 1)
        self.assertEqual(self.scoring()['completed_levels'], facts['completed_levels'])

    def test_baseline_reference_level_cap_and_completed_weight_use_same_formula(self):
        self.engine.level_after = 10
        self.solver.execute_plan(self.minimal('ten-paid', steps=[
            {'action': {'name': 'ACTION1', 'data': {}}} for _ in range(10)]))
        facts = self.scoring()
        self.assertEqual(facts['completed_levels'][0]['level_score'], '100.000000')
        self.assertEqual(facts['full_game_score'], '2.222222')
        self.assertEqual(facts['completed_score_cap'], '2.222222')

    def test_baseline_unavailable_and_unsettled_action_do_not_invent_scores(self):
        self.broker = ArcBroker(engine=self.engine, game=ArcGameContract(self.engine.game_id, 9),
                                action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver.broker = self.broker
        facts = self.scoring()
        self.assertIsNone(facts['baseline_actions'])
        self.assertIsNone(facts['current_level']['baseline'])
        self.assertIsNone(facts['full_game_score'])
        self.assertEqual(facts['accounting_status'], 'settled')
        self.engine.raises_on = 1
        result = self.solver.execute_plan(self.minimal('unknown'))
        facts = result['budget']['scoring']
        self.assertEqual(result['applied_count'], 0)
        self.assertTrue(self.solver.current_context()['environment_result_unknown'])
        self.assertEqual(result['budget']['primitive_actions'], 1)
        self.assertEqual(facts['accounting_status'], 'unavailable')
        self.assertIsNone(facts['full_game_score'])
        self.assertIsNone(facts['current_level'])

    def test_autonomous_prompt_adds_score_facts_without_changing_original_goal(self):
        prompt = build_autonomous_prompt()
        intro, facts, remainder = prompt.split('\n\n', 2)
        self.assertEqual(intro, '你是 P7 主解题者。依据真实画面自主理解游戏、验证想法、规划行动，直到达到 budget.target_level。兼顾过关与动作效率。自行决定何时观察、推理、编程、实验或更新认识。应用自动附加的 observation_ref、available_actions 和 budget 是当前执行依据。')
        for fragment in ('计分事实：budget.scoring', 'N', 'b_i', 'a_i',
                         'q_i=min(115,100*(b_i/a_i)^2)', 'W=N*(N+1)/2',
                         'min(sum(i*q_i)/W,100*sum(已完成关i)/W)',
                         '未完成关贡献为0', '初始化 RESET 不计费', '撤销',
                         'RESET 不清零', 'baseline 是100分参考', 'null 表示未知'):
            with self.subTest(fact=fragment):
                self.assertIn(fragment, facts)
        for fragment in ('争取', '优化', '自行权衡', '不要', '须', '必须', '硬限'):
            with self.subTest(behavior=fragment):
                self.assertNotIn(fragment, facts)
        self.assertTrue(remainder.startswith('工具：ipython(code)、p7_workspace(request)、p7_execute_plan(plan)。'))
        for fragment in ('完整通关', '整局满分100', '稳定目标', '执行停止边界'):
            self.assertNotIn(fragment, prompt)
        self.assertIn('固定总预算覆盖研究和行动，续跑、恢复和暂停不会续期。结果不确定时执行暂停，保存下来的证据用于核实；模型文字不能代替真实通关证据。达到目标后停止行动。', prompt)


class TestP7ScoreFormula(unittest.TestCase):
    def test_full_game_level_cap_and_below_baseline_scores_match_canonical_receipt(self):
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.score import score_planning_facts
        selected = game(target=9)
        for paid, level_score, full_score in ((1, '115.000000', '100.000000'),
                                             (10, '100.000000', '100.000000'),
                                             (20, '25.000000', '25.000000')):
            with self.subTest(paid=paid):
                rows = tuple(ArcTransition(i, 'ACTION1', 'before', 'after', i // paid)
                             for i in range(1, paid * 9 + 1))
                facts = score_planning_facts(selected, rows, primitive_actions=len(rows), levels_completed=9)
                self.assertEqual(facts['completed_levels'][-1]['level_score'], level_score)
                self.assertEqual(facts['full_game_score'], full_score)
                self.assertEqual(facts['full_game_score'], partial_game_score((paid,) * 9, selected))
                self.assertIsNone(facts['current_level'])
                self.assertEqual(facts['completed_score_cap'], '100.000000')

    def test_higher_weight_surplus_can_compensate_an_over_baseline_level(self):
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.score import score_planning_facts
        selected = game(target=9)
        counts = (20,) + (1,) * 8
        rows = []
        for level, paid in enumerate(counts):
            for step in range(paid):
                rows.append(ArcTransition(len(rows) + 1, 'ACTION1', 'before', 'after',
                                          level + (step == paid - 1)))
        facts = score_planning_facts(selected, rows, primitive_actions=len(rows), levels_completed=9)
        self.assertEqual(facts['completed_levels'][0]['level_score'], '25.000000')
        self.assertEqual(facts['full_game_score'], '100.000000')
        self.assertEqual(facts['full_game_score'], partial_game_score(counts, selected))
