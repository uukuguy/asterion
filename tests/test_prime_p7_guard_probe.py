"""Bounded grounded probes do not confuse untried clicks with failed actions."""
from __future__ import annotations

import unittest

from asterion.applications.prime.p7.broker import ArcAction, ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.game import P7GameSelection


class _NoEffectClickEngine:
    game_id = 'ls20-9607627b'
    seed = 0
    win_levels = 7

    def __init__(self):
        self.calls = []
        self.levels_completed = 0
        self.marker = 7
        self.advance_on_move = False

    def observe(self):
        return {'available_actions': ['ACTION1', 'ACTION6'],
                'frame': [[[self.marker for _ in range(64)] for _ in range(64)]],
                'levels_completed': self.levels_completed, 'state': 'NOT_FINISHED', 'win_levels': 7}

    def step(self, action, data=None):
        self.calls.append((action, data or {}))
        if action == 'ACTION1':
            if self.advance_on_move:
                self.levels_completed += 1
            else:
                self.marker = (self.marker + 1) % 16
        return self.observe()


class TestP7GuardProbe(unittest.TestCase):
    def setUp(self):
        self.engine = _NoEffectClickEngine()
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history('grounded-probe')
        for _ in range(3):
            self.broker.act((ArcAction('ACTION6', (('x', 1), ('y', 1))),))

    def plan(self, x=2, y=2, *, grounding='frame'):
        expect = ({'frame_sha256': digest(self.engine.observe()['frame'][-1])}
                  if grounding == 'frame' else {'cell': {'x': x, 'y': y, 'value': 7}})
        return [{'action': {'name': 'ACTION6', 'data': {'x': x, 'y': y}}, 'expect': expect}]

    def test_grounded_distinct_click_dispatches_once_after_other_click_no_effects(self):
        result = self.broker.act_checked(self.plan())
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['stop_reason'], 'observation-no-change')
        self.assertEqual(self.engine.calls[-1], ('ACTION6', {'x': 2, 'y': 2}))
        repeat = self.broker.act_checked(self.plan())
        self.assertEqual((repeat['applied_count'], repeat['stop_reason']), (0, 'REPLAN_REQUIRED'))
        self.assertEqual(len(self.engine.calls), 4)

    def test_matching_current_clicked_cell_is_grounding_without_invented_change(self):
        result = self.broker.act_checked(self.plan(3, 4, grounding='cell'))
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['feedback'][0]['no_effect'], True)

    def test_raw_new_payload_same_payload_and_multi_action_remain_guarded(self):
        for action in (ArcAction('ACTION6', (('x', 2), ('y', 2))),
                       ArcAction('ACTION6', (('x', 1), ('y', 1)))):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ArcBrokerError, 'REPLAN_REQUIRED'):
                    self.broker.act((action,))
        same = self.broker.act_checked(self.plan(1, 1))
        self.assertEqual(same['applied_count'], 0)
        batch = self.broker.act_checked(self.plan()+self.plan(4, 4))
        self.assertEqual(batch['applied_count'], 0)
        self.assertEqual(len(self.engine.calls), 3)

    def test_unrelated_cell_or_only_state_does_not_authorize_unknown_click(self):
        for expect in ({'cell': {'x': 0, 'y': 0, 'value': 7}},):
            with self.subTest(expect=expect):
                result = self.broker.act_checked([{'action': {'name': 'ACTION6', 'data': {'x': 2, 'y': 2}}, 'expect': expect}])
                self.assertEqual(result['applied_count'], 0)
        self.assertEqual(len(self.engine.calls), 3)

    def test_unknown_probe_allowance_is_finite_even_for_distinct_coordinates(self):
        for x in range(2, 34):
            result = self.broker.act_checked(self.plan(x, 2))
            self.assertEqual(result['applied_count'], 1)
        result = self.broker.act_checked(self.plan(34, 2))
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'REPLAN_REQUIRED'))
        self.assertEqual(len(self.engine.calls), 35)

    def test_observation_changes_do_not_reset_the_finite_probe_allowance(self):
        for x in range(2, 34):
            self.assertEqual(self.broker.act_checked(self.plan(x, 2))['applied_count'], 1)
            self.broker.act(('ACTION1',))
        result = self.broker.act_checked(self.plan(34, 2))
        self.assertEqual(result['applied_count'], 0)
        self.assertEqual(result['stop_reason'], 'REPLAN_REQUIRED')
        repeated = self.broker.act_checked(self.plan(2, 2))
        self.assertEqual(repeated['applied_count'], 0)

    def test_level_transition_clears_old_probe_allowance_and_payload_history(self):
        engine = _NoEffectClickEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection(engine.game_id, 0, 2))
        broker.bind_history('level-probe-reset')
        def checked(x):
            return [{'action': {'name': 'ACTION6', 'data': {'x': x, 'y': 2}},
                     'expect': {'frame_sha256': digest(engine.observe()['frame'][-1])}}]
        for _ in range(3):
            broker.act((ArcAction('ACTION6', (('x', 1), ('y', 1))),))
        for x in range(2, 34):
            self.assertEqual(broker.act_checked(checked(x))['applied_count'], 1)
        engine.advance_on_move = True
        broker.act(('ACTION1',))
        self.assertEqual(engine.levels_completed, 1)
        for _ in range(3):
            broker.act((ArcAction('ACTION6', (('x', 1), ('y', 1))),))
        self.assertEqual(broker.act_checked(checked(34))['applied_count'], 1)
