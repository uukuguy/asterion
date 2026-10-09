"""Provider-free dual-clock admission tests."""
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p7.solver_control import SolverControl


class TestTaskDeadline(unittest.TestCase):
    def test_snapshot_samples_each_clock_once_and_keeps_fixed_deadlines(self):
        calls = []
        now = {'mono': 10., 'wall': 100.}
        def clock(name):
            calls.append(name)
            return now[name]
        budget = TaskDeadline(deadline_monotonic=20., deadline_epoch=108.,
            monotonic_clock=lambda: clock('mono'), wall_clock=lambda: clock('wall'))
        first = budget.snapshot()
        self.assertEqual(calls, ['mono', 'wall'])
        self.assertEqual(first, {'status': 'available', 'sampled_at_monotonic': 10.,
            'sampled_at_epoch': 100., 'deadline_monotonic': 20., 'deadline_epoch': 108.,
            'remaining_seconds': 8.})
        first['deadline_epoch'] = 999.
        now.update(mono=13., wall=104.)
        second = budget.snapshot()
        self.assertEqual(second['remaining_seconds'], 4.)
        self.assertEqual(second['deadline_epoch'], 108.)
        self.assertEqual(len(calls), 4)
        now['wall'] = 109.
        self.assertEqual(budget.snapshot()['remaining_seconds'], 0.)
        now.update(mono=10., wall=100.)
        self.assertEqual(budget.snapshot()['remaining_seconds'], 0.)

    def test_unavailable_samples_expire_without_publishing_invalid_numbers(self):
        for value in (True, float('nan'), float('inf'), '10'):
            with self.subTest(value=value):
                budget = TaskDeadline(deadline_monotonic=20., deadline_epoch=110.,
                    monotonic_clock=lambda: value, wall_clock=lambda: 100.)
                snapshot = budget.snapshot()
                self.assertEqual(snapshot['status'], 'unavailable')
                self.assertIsNone(snapshot['sampled_at_monotonic'])
                self.assertIsNone(snapshot['sampled_at_epoch'])
                self.assertEqual(snapshot['remaining_seconds'], 0.)
                self.assertTrue(budget.expired())

    def test_either_clock_expires_permanently(self):
        for clock in ('wall', 'mono'):
            with self.subTest(clock=clock):
                now = {'wall': 100., 'mono': 10.}
                budget = TaskDeadline(deadline_monotonic=20., deadline_epoch=110.,
                                      monotonic_clock=lambda: now['mono'], wall_clock=lambda: now['wall'])
                self.assertEqual(budget.remaining_seconds(), 10.)
                now[clock] += 11.
                self.assertTrue(budget.expired())
                now.update(wall=100., mono=10.)
                self.assertTrue(budget.expired())
                self.assertEqual(budget.remaining_seconds(), 0.)

    def test_invalid_deadline_rejected(self):
        for value in (True, float('nan'), float('inf'), '10'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaskDeadline(deadline_monotonic=value, deadline_epoch=100.)

    def test_solver_control_stops_after_suspend_like_wall_jump(self):
        now = [100.]
        budget = TaskDeadline(deadline_monotonic=200., deadline_epoch=110.,
                              monotonic_clock=lambda: 100., wall_clock=lambda: now[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run-test'
            root.mkdir()
            control = SolverControl(root, root.name, 200., clock=lambda: 100., task_deadline=budget)
            self.assertTrue(control.action_allowed())
            now[0] = 111.
            self.assertFalse(control.enter('action'))
            self.assertEqual(control.snapshot()['reason'], 'deadline_expired')
            self.assertEqual(control.budget_snapshot()['wall_time_remaining_seconds'], 0.)

    def test_solver_control_samples_its_own_clock_and_task_clock_once(self):
        calls = []
        def clock(name, value):
            calls.append(name)
            return value
        task = TaskDeadline(deadline_monotonic=100., deadline_epoch=100.,
            monotonic_clock=lambda: clock('task-mono', 10.),
            wall_clock=lambda: clock('task-wall', 10.))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'separate-clocks'
            root.mkdir()
            control = SolverControl(root, root.name, 100.,
                clock=lambda: clock('control', 101.), task_deadline=task)
            snapshot = control.budget_snapshot()
            self.assertEqual(snapshot['wall_time_remaining_seconds'], 0.)
            self.assertCountEqual(calls, ['control', 'task-mono', 'task-wall'])
            self.assertEqual(snapshot['time_snapshot']['control_sampled_at_monotonic'], 101.)
            self.assertEqual(snapshot['time_snapshot']['sampled_at_monotonic'], 10.)
            self.assertEqual(control.snapshot()['reason'], 'deadline_expired')
