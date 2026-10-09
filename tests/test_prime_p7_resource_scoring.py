"""Objective scoring room is evidence, never an execution allowance."""

from unittest import TestCase
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.game import ArcGameContract, P7GameSelection
from asterion.applications.prime.p7.prompt import build_autonomous_prompt
from asterion.applications.prime.p7.score import score_planning_facts


FIELDS = (
    'max_paid_actions_for_115',
    'additional_paid_actions_preserving_115',
    'paid_actions_exceeding_115',
    'max_paid_actions_for_100',
    'additional_paid_actions_preserving_100',
    'paid_actions_exceeding_100',
)


def facts(baseline, paid, *, actions=None):
    selected = P7GameSelection('ls20-9607627b', 0, 6,
                              _metadata_baseline_actions=(baseline,) * 9,
                              _metadata_win_levels=9)
    rows = tuple(ArcTransition(index, action, 'before', 'after', 0)
                 for index, action in enumerate(actions or ['ACTION1'] * paid, 1))
    return score_planning_facts(selected, rows, primitive_actions=paid, levels_completed=0)


class TestP7ResourceScoring(TestCase):
    def test_zero_paid_reports_both_remaining_action_counts(self):
        value = facts(21, 0)
        current = value['current_level']
        self.assertEqual(current.get('max_paid_actions_for_115'), 19)
        self.assertEqual(current.get('additional_paid_actions_preserving_115'), 19)
        self.assertEqual([current.get(key) for key in FIELDS], [19, 19, 0, 21, 21, 0])
        self.assertNotIn('level_score_at_current_paid', current)
        self.assertEqual(value['completed_levels'], [])
        self.assertEqual(value['full_game_score'], '0.000000')

    def test_integer_threshold_keeps_equality_and_loses_next_paid_action(self):
        for baseline, threshold in ((1, 0), (21, 19), (48, 44), (44, 41),
                                    (38, 35), (33, 30), (87, 81)):
            for paid in (threshold, threshold + 1):
                with self.subTest(baseline=baseline, paid=paid):
                    current = facts(baseline, paid)['current_level']
                    self.assertEqual(current.get('max_paid_actions_for_115'), threshold)
                    self.assertEqual(current.get('additional_paid_actions_preserving_115'), 0)
                    self.assertEqual(current.get('paid_actions_exceeding_115'), paid - threshold)
                    self.assertLessEqual(115 * threshold ** 2, 100 * baseline ** 2)
                    self.assertGreater(115 * (threshold + 1) ** 2, 100 * baseline ** 2)
                    self.assertNotIn('level_score_at_current_paid', current)

    def test_remaining_and_exceeded_distinguish_equality_without_awarding_unfinished_level(self):
        for baseline, paid, expected in (
                (48, 42, [44, 2, 0, 48, 6, 0]),
                (21, 25, [19, 0, 6, 21, 0, 4]),
                (10, 9, [9, 0, 0, 10, 1, 0]),
                (10, 10, [9, 0, 1, 10, 0, 0]),
                (10, 11, [9, 0, 2, 10, 0, 1])):
            with self.subTest(baseline=baseline, paid=paid):
                value = facts(baseline, paid)
                self.assertEqual([value['current_level'].get(key) for key in FIELDS],
                                 expected)
                self.assertNotIn('level_score_at_current_paid', value['current_level'])
                self.assertEqual(value['full_game_score'], '0.000000')
                self.assertNotIn('action_cap', value['current_level'])

    def test_probe_reset_and_undo_use_the_same_paid_ledger_and_copied_facts(self):
        value = facts(10, 3, actions=['ACTION1', 'RESET', 'ACTION7'])
        self.assertEqual(value['current_level'].get('additional_paid_actions_preserving_115'), 6)
        value['current_level']['paid_actions'] = 0
        value['current_level']['additional_paid_actions_preserving_115'] = 1000
        current = facts(10, 3, actions=['ACTION1', 'RESET', 'ACTION7'])['current_level']
        self.assertEqual(current['paid_actions'], 3)
        self.assertEqual(current['additional_paid_actions_preserving_115'], 6)
        self.assertEqual(current['additional_paid_actions_preserving_100'], 7)
        self.assertEqual(current['paid_actions_exceeding_115'], 0)
        self.assertEqual(current['paid_actions_exceeding_100'], 0)

    def test_unknown_baseline_and_unsettled_tail_do_not_invent_scoring_room(self):
        unknown = score_planning_facts(ArcGameContract('ls20-9607627b', 9), (),
                                       primitive_actions=0, levels_completed=0)
        self.assertEqual(unknown['accounting_status'], 'settled')
        for key in FIELDS:
            with self.subTest(field=key):
                self.assertIn(key, unknown['current_level'])
                self.assertIsNone(unknown['current_level'][key])
        selected = P7GameSelection('ls20-9607627b', 0, 6,
                                  _metadata_baseline_actions=(21,) * 9,
                                  _metadata_win_levels=9)
        unsettled = score_planning_facts(selected, (), primitive_actions=1, levels_completed=0)
        self.assertEqual(unsettled['accounting_status'], 'unavailable')
        self.assertIsNone(unsettled['current_level'])
        self.assertIsNone(unsettled['full_game_score'])

    def test_primary_guidance_consumes_generic_constant_without_editing_legacy_prompt(self):
        from asterion.applications.prime.p7 import prompt
        marker = 'generic resource tradeoff guidance sentinel'
        with patch.object(prompt, 'RESOURCE_AWARE_RESEARCH_GUIDANCE', marker, create=True):
            self.assertIn(marker, build_autonomous_prompt())
            self.assertNotIn(marker, prompt.P7_SOLVE_PROMPT)
            self.assertNotIn(marker, prompt.P7_NOTES_SOLVE_PROMPT)

    def test_primary_prompt_explains_direct_remaining_actions_and_dated_resource_view(self):
        text = build_autonomous_prompt()
        for field in (*FIELDS, 'host_resource_snapshot', 'time_snapshot.status'):
            with self.subTest(field=field):
                self.assertIn(field, text)
        self.assertNotIn('level_score_at_current_paid', text)
        self.assertIn('115分还剩', text)
        self.assertIn('100分还剩', text)
        self.assertIn('已超过', text)
        self.assertIn('不构成动作授权或执行停止条件', text)
        self.assertIn('采样', text)

