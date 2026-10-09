"""Objective scoring room is evidence, never an execution allowance."""

from unittest import TestCase
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.game import ArcGameContract, P7GameSelection
from asterion.applications.prime.p7.prompt import build_autonomous_prompt
from asterion.applications.prime.p7.score import score_planning_facts


FIELDS = (
    'level_score_at_current_paid',
    'max_paid_actions_for_115',
    'additional_paid_actions_preserving_115',
)


def facts(baseline, paid, *, actions=None):
    selected = P7GameSelection('ls20-9607627b', 0, 6,
                              _metadata_baseline_actions=(baseline,) * 9,
                              _metadata_win_levels=9)
    rows = tuple(ArcTransition(index, action, 'before', 'after', 0)
                 for index, action in enumerate(actions or ['ACTION1'] * paid, 1))
    return score_planning_facts(selected, rows, primitive_actions=paid, levels_completed=0)


class TestP7ResourceScoring(TestCase):
    def test_zero_paid_has_scoring_room_but_no_conditional_score(self):
        value = facts(21, 0)
        current = value['current_level']
        self.assertEqual(current.get('max_paid_actions_for_115'), 19)
        self.assertEqual(current.get('additional_paid_actions_preserving_115'), 19)
        self.assertIn('level_score_at_current_paid', current)
        self.assertIsNone(current['level_score_at_current_paid'])
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
                    self.assertLessEqual(115 * threshold ** 2, 100 * baseline ** 2)
                    self.assertGreater(115 * (threshold + 1) ** 2, 100 * baseline ** 2)
                    if paid:
                        self.assertEqual(current['level_score_at_current_paid'] == '115.000000',
                                         paid == threshold)

    def test_conditional_score_and_additional_room_do_not_award_unfinished_level(self):
        for baseline, paid, score, threshold, additional in (
                (48, 42, '115.000000', 44, 2),
                (21, 25, '70.560000', 19, 0),
                (10, 10, '100.000000', 9, 0)):
            with self.subTest(baseline=baseline, paid=paid):
                value = facts(baseline, paid)
                self.assertEqual([value['current_level'].get(key) for key in FIELDS],
                                 [score, threshold, additional])
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

    def test_primary_prompt_explains_conditional_scoring_and_dated_resource_view(self):
        text = build_autonomous_prompt()
        for field in (*FIELDS, 'host_resource_snapshot', 'time_snapshot.status'):
            with self.subTest(field=field):
                self.assertIn(field, text)
        self.assertIn('条件分', text)
        self.assertIn('采样', text)

