"""Freeform notes change learning admission, never environment authority."""

from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_solver import P7SolverFixture


class TestP7Notes(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.solver = Solver(
            broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id='run-1',
            attempt_id='attempt-1', event_sink=lambda kind, payload: self.events.append((kind, payload)),
            learner_profile='notes',
        )

    def request(self, text='NOTES private sentinel: one partial hypothesis and next experiment'):
        context = self.solver.current_context()
        return {'op': 'notes', 'base_revision': context['workspace_revision'],
                'observation_ref': context['observation_ref'], 'text': text}

    def test_freeform_notes_open_learning_gate_without_worldmap_or_action(self):
        before = self.solver.current_context()
        result = self.solver.workspace(self.request())
        self.assertEqual(result['status'], 'noted')
        current = self.solver.current_context()
        self.assertFalse(current['needs_revision'])
        self.assertEqual(current['worldmap'], before['worldmap'])
        self.assertEqual(current['task'], before['task'])
        self.assertIn('one partial hypothesis', current['notes']['text'])
        self.assertEqual(current['notes']['observation_ref'], before['observation_ref'])
        self.assertNotIn('NOTES private sentinel', str(self.events))
        self.assertEqual(self.engine.calls, [])
        current['notes']['text'] = 'mutated response'
        self.assertIn('one partial hypothesis', self.solver.current_context()['notes']['text'])
        self.assertEqual(self.solver.execute_plan(self.plan((1,)))['applied_count'], 1)

    def test_stale_or_foreign_request_and_failed_commit_leave_gate_and_pointer(self):
        valid = self.request()
        for changed in ({'base_revision': 'sha256:' + 'a' * 64},
                        {'observation_ref': {**valid['observation_ref'], 'run_id': 'foreign'}},
                        {'observation_ref': {**valid['observation_ref'], 'sequence': 1}},
                        {'observation_ref': {**valid['observation_ref'], 'sequence': False}},
                        {'observation_ref': {**valid['observation_ref'], 'level': True}},
                        {'text': ''}, {'scope': {'authority': 'forged'}}):
            with self.subTest(changed=changed):
                self.assertEqual(self.solver.workspace({**valid, **changed})['status'], 'rejected')
                self.assertEqual(self.solver.current_context()['workspace_revision'], valid['base_revision'])
                self.assertTrue(self.solver.current_context()['needs_revision'])
        from asterion.applications.prime.p7 import research
        original = research._atomic
        def fail_pointer(path, value):
            if path.name == 'current.json':
                raise OSError('private write failure')
            return original(path, value)
        with patch.object(research, '_atomic', side_effect=fail_pointer):
            self.assertEqual(self.solver.workspace(valid)['status'], 'rejected')
        self.assertEqual(self.solver.current_context()['workspace_revision'], valid['base_revision'])
        self.assertTrue(self.solver.current_context()['needs_revision'])
        self.assertEqual(self.engine.calls, [])

    def test_reset_level_and_kernel_boundaries_require_one_current_note(self):
        for boundary in ('reset', 'level', 'kernel'):
            with self.subTest(boundary=boundary):
                self.assertEqual(self.solver.workspace(self.request())['status'], 'noted')
                if boundary == 'reset':
                    initial = self.plan((1,))
                    initial['plan_id'] = 'before-reset'
                    self.assertEqual(self.solver.execute_plan(initial)['applied_count'], 1)
                old = self.request()
                if boundary == 'kernel':
                    self.kernel.generation += 1
                    self.solver.kernel_recovered()
                else:
                    plan = self.plan((len(self.engine.calls) + 1,))
                    plan['plan_id'] = boundary
                    if boundary == 'reset':
                        plan['steps'][0]['action']['name'] = 'RESET'
                    else:
                        self.engine.level_after = len(self.engine.calls) + 1
                        plan['steps'][0]['expect']['levels_completed'] = 1
                    self.assertEqual(self.solver.execute_plan(plan)['applied_count'], 1)
                self.assertEqual(self.solver.execute_plan({**self.plan((1,)), 'plan_id': 'blocked-' + boundary})['status'], 'rejected')
                # Kernel generation changes can preserve the exact board; the
                # application attaches the current generation on a fresh write.
                if boundary != 'kernel':
                    self.assertEqual(self.solver.workspace(old)['status'], 'rejected')
                self.assertEqual(self.solver.workspace(self.request())['status'], 'noted')
                self.assertFalse(self.solver.current_context()['requires_calibration'])

    def test_notes_do_not_bypass_pause_lost_kernel_or_legacy_semantic_gate(self):
        self.assertEqual(self.solver.workspace(self.request())['status'], 'noted')
        self.control.state = 'paused'
        self.assertEqual(self.solver.execute_plan(self.plan((1,)))['applied_count'], 0)
        self.control.state = 'running'
        self.kernel.lost = True
        self.assertEqual(self.solver.workspace(self.request())['status'], 'rejected')
        self.assertEqual(self.solver.execute_plan({**self.plan((1,)), 'plan_id': 'lost'})['status'], 'rejected')
        self.kernel.lost = False
        legacy = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name) / 'legacy', run_id='run-1',
            attempt_id='attempt-1', event_sink=lambda *_: None)
        context = legacy.current_context()
        result = legacy.workspace({**self.request(), 'base_revision': context['workspace_revision']})
        self.assertEqual(result['status'], 'noted')
        self.assertTrue(legacy.current_context()['needs_revision'])

    def test_notes_history_and_reopen_retain_only_committed_records(self):
        first = self.solver.workspace(self.request('first'))
        second = self.solver.workspace(self.request('second'))
        history = self.solver.workspace({'op': 'notes_history', 'start': 0, 'limit': 2})
        self.assertEqual([row['text'] for row in history['items']], ['second', 'first'])
        reopened = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id='run-1', attempt_id='attempt-1',
            event_sink=lambda *_: None, learner_profile='notes')
        self.assertEqual(reopened.current_context()['notes']['text'], 'second')
        self.assertTrue(reopened.current_context()['requires_calibration'])
        self.assertNotEqual(first['workspace_revision'], second['workspace_revision'])

    def test_legacy_model_updates_cannot_refresh_notes_after_mismatch(self):
        self.assertEqual(self.solver.workspace(self.request())['status'], 'noted')
        result = self.solver.execute_plan(self.plan((9,)))
        self.assertTrue(result['needs_revision'])
        self.assertEqual(self.revise()['status'], 'revised')
        self.assertTrue(self.solver.current_context()['needs_revision'])
        self.assertFalse(self.solver.current_context()['notes_current'])
        self.assertEqual(self.solver.execute_plan({**self.plan((2,)), 'plan_id': 'after-legacy'})['status'], 'rejected')
        self.assertEqual(self.solver.workspace(self.request())['status'], 'noted')
        self.assertEqual(self.solver.execute_plan({**self.plan((2,)), 'plan_id': 'after-notes'})['applied_count'], 1)

    def test_orphan_note_is_not_readable_from_accepted_history(self):
        first = self.solver.workspace(self.request('accepted'))
        record = self.solver._workspace.memory.save('orphan', parent_revision=first['notes_revision'])
        self.assertEqual(self.solver.workspace({'op': 'notes_read', 'revision': record['revision']})['status'], 'rejected')
        read = self.solver.workspace({'op': 'notes_read', 'revision': first['notes_revision']})
        self.assertEqual(read['notes']['text'], 'accepted')
        self.assertEqual([item['text'] for item in self.solver.workspace({'op': 'notes_history'})['items']], ['accepted'])

    def test_notes_keep_full_utf8_text_and_do_not_clear_unknown_environment(self):
        text = '\N{GRINNING FACE}' * 4096
        self.assertEqual(self.solver.workspace(self.request(text))['status'], 'noted')
        self.assertEqual(self.solver.current_context()['notes']['text'], text)
        previous = self.solver.current_context()['workspace_revision']
        for flag in ('_environment_uncertain', '_processing_blocked'):
            with self.subTest(flag=flag):
                setattr(self.solver, flag, True)
                self.assertEqual(self.solver.workspace(self.request('new note'))['status'], 'rejected')
                self.assertEqual(self.solver.current_context()['workspace_revision'], previous)
                setattr(self.solver, flag, False)
