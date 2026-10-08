"""Provider-free dual-clock admission tests."""
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.p7.solver_control import SolverControl


class TestTaskDeadline(unittest.TestCase):
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
