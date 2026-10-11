"""One provider-free story through Prime computation and the real P7 broker."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.console_events import ConsoleEventWriter, read_console_events
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from asterion.applications.prime.p7.solver_control import write_control_request
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_solver import draft


class _Signal:
    cancelled = False


class _TraceClient:
    def __init__(self):
        self.transitions = []

    def _record_transitions(self, values):
        self.transitions.extend(values)

    def _count(self, *args):
        pass


async def _wait_until(predicate, message):
    deadline = asyncio.get_running_loop().time() + 5
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.01)


class TestP7ResearchRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_p7_default_output_capacity_keeps_full_frame_bearing_route_print(self):
        from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch
        self.assertEqual(self.host._limits.max_output_bytes, 2 * 1024 * 1024)
        services = P7ToolDispatch(self.host, self.trace, run_id=self.run_id)
        self.assertEqual(getattr(services, 'bridge_output_bytes', None), self.host._limits.max_output_bytes)
        result = await self.host.execute('full-route-print',
            "routes = [{'action': 'ACTION1', 'frame': [[255]*64 for _ in range(64)]} for _ in range(32)]\n"
            "print(routes)\nprint('final-action-visible', len(routes), routes[-1]['action'])", _Signal())
        self.assertEqual(result.status, 'ok')
        envelope = json.loads(result.content[0]['text'])
        self.assertFalse(envelope['stdout_truncated'])
        self.assertIn('final-action-visible 32 ACTION1', envelope['stdout'])
        self.assertGreater(len(envelope['stdout'].encode()), 64 * 1024)

    async def test_maximal_observation_measurements_fit_runtime_and_historical_projection(self):
        import copy
        import random
        from unittest.mock import patch
        from tests.test_prime_p7_observation_boundary import DETECTOR, LIVE_RUN_ID
        from asterion.applications.prime.p7.score import canonical_bytes
        from asterion.applications.prime.p7.view_change import view_change
        rng = random.Random(29)
        board = [[rng.randrange(256) for _ in range(64)] for _ in range(64)]
        shifted = [[rng.randrange(256) for _ in range(64)] for _ in range(4)] + copy.deepcopy(board[:-4])
        measurement = view_change(board, shifted)
        class Engine(_Engine):
            def observe(self):
                value = super().observe()
                value['frame'] = [copy.deepcopy(board)]
                return value
        engine = Engine()
        broker = ArcBroker(engine=engine, action_profile='autonomous')
        run_id = LIVE_RUN_ID
        broker.bind_history(run_id)
        run_root = self.root / run_id
        run_root.mkdir()
        trace = _TraceClient()
        host = P7ResearchRuntime(broker=broker, trace_client=trace, run_root=run_root,
            run_id=run_id, deadline_seconds=30, event_sink=lambda *_: None, learner_profile='autonomous')
        self.addAsyncCleanup(host.close)
        cells = [{'x': x, 'y': y, 'value': (board[y][x] + 1) % 256}
                 for y in range(2) for x in range(64)]
        guards = [{'x': x, 'y': y, 'value': board[y][x]}
                  for y in range(2) for x in range(64)]
        plan = {'plan_id': 'bounded-optout', 'start': host.current_context()['observation_ref'],
                'steps': [{'action': {'name': 'ACTION1', 'data': {}}, 'before': {'cells': guards},
                           'expect': {'cells': cells, 'frame_sha256': 'sha256:' + '0' * 64,
                                      'state': 'NOT_FINISHED', 'levels_completed': 0}}
                          for _ in range(20)], 'stop_on_mismatch': False, 'stop_on_view_change': False}
        with patch(DETECTOR, return_value=measurement):
            result = host.method_call('execute_plan', plan, _Signal())
        self.assertEqual((result['applied_count'], result['stop_reason']), (20, 'executed'))
        self.assertEqual(len(trace.transitions), 20)
        self.assertFalse(result['environment_result_unknown'])
        self.assertFalse(result['processing_blocked'])
        historical = json.loads(result['tool_state_view']['replacement_text'])
        self.assertEqual(historical['feedback'], result['feedback'])
        self.assertEqual(historical['precondition_feedback'], result['precondition_feedback'])
        self.assertEqual(historical['budget']['primitive_actions'], 20)
        self.assertEqual(historical['observation_ref']['sequence'], 20)
        self.assertEqual(result['observation']['frame'], [board])
        self.assertNotIn('frame', historical['observation'])
        self.assertTrue(all(item['view_change']['measurement_fields_omitted'] > 0 for item in result['feedback']))
        self.assertNotIn('host_resource_snapshot', result)
        self.assertLessEqual(len(canonical_bytes(host.solver._plan_projection(
            host.solver._plans['bounded-optout']['result']))), 60 * 1024)

    async def test_observation_boundary_and_pixel_facts_survive_actor_and_historical_views(self):
        from unittest.mock import patch
        from tests.test_prime_p7_observation_boundary import CANDIDATE, DETECTOR
        from asterion.applications.prime.p7.actor_projection import decode_actor_frame
        self.host.solver.learner_profile = 'autonomous'
        self.host.set_memory_instructions('trusted research instruction')
        initial = self.host.current_context()
        plan = {'plan_id': 'view-boundary', 'start': initial['observation_ref'],
                'steps': [{'action': {'name': 'ACTION1', 'data': {}},
                           'expect': {'cells': [{'x': 0, 'y': 0, 'value': 1}]}},
                          {'action': {'name': 'ACTION1', 'data': {}},
                           'expect': {'cells': [{'x': 0, 'y': 0, 'value': 2}]}}]}
        with patch(DETECTOR, return_value=CANDIDATE):
            result = self.host.method_call('execute_plan', plan, _Signal())
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'observation-boundary'))
        self.assertFalse(result['environment_result_unknown'])
        self.assertFalse(result['processing_blocked'])
        frame = result['observation']['frame']
        self.assertEqual(decode_actor_frame(frame) if isinstance(frame, dict) else frame, [[[1, 1]]])
        self.assertEqual(len(self.trace.transitions), 1)
        self.assertEqual(self.broker.frame_at(1), [[1, 1]])
        archived_view = json.loads(result['tool_state_view']['replacement_text'])
        for name, value in (('actor', result), ('historical', archived_view)):
            with self.subTest(view=name):
                self.assertEqual(value['observation_boundary'], result['observation_boundary'])
                self.assertEqual(value['feedback'], result['feedback'])
                self.assertEqual(value['observation_ref']['sequence'], 1)
                self.assertEqual(value['budget']['primitive_actions'], 1)
                self.assertEqual(len(value['unexecuted_steps']), 1)
                self.assertEqual(value['feedback'][0]['view_change'].get('origin'), 'derived-pixel-measurement')
        self.assertNotIn('frame', archived_view['observation'])
        self.assertEqual(len(self.engine.calls), 1)

    async def test_unknown_action_remains_top_level_unknown_after_notes_reads(self):
        self.host.solver.learner_profile = 'autonomous'
        self.host.set_memory_instructions('trusted research')
        before = self.host.current_context()
        self.host.method_call('workspace', {'op': 'notes',
            'base_revision': before['workspace_revision'], 'observation_ref': before['observation_ref'],
            'text': 'retain known facts'}, _Signal())
        self.engine.raises_on = 1
        action = self.host.method_call('execute_plan', {'plan_id': 'unknown-effect',
            'start': before['observation_ref'], 'steps': [{'action': {'name': 'ACTION1', 'data': {}},
            'expect': {'cells': [{'x': 0, 'y': 0, 'value': 1}]}}]}, _Signal())
        self.assertEqual(action['stop_reason'], 'environment-result-unknown')
        current = self.host.current_context()
        self.assertTrue(current['environment_result_unknown'])
        # Isolate reply projection from the runtime stop requested by the unknown action.
        # The solver's read-only NOTES operations still expose real accepted records.
        self.host.poll = lambda: {'state': 'running'}
        for op in ('notes_read', 'notes_history'):
            with self.subTest(op=op):
                result = self.host.method_call('workspace', {'op': op}, _Signal())
                self.assertEqual(result['status'], 'ok')
                self.assertTrue(result.get('environment_result_unknown'))
                self.assertEqual(result.get('processing_blocked'), current['processing_blocked'])
                self.assertTrue(result['host_resource_snapshot']['environment_result_unknown'])
                self.assertIsNone(result['host_resource_snapshot']['current_level'])
                snapshot = json.loads(result['context_memory']['content'].split('\n\n', 1)[1])
                self.assertTrue(snapshot['environment_result_unknown'])
                self.assertNotIn('tool_state_view', result)
        self.assertEqual(len(self.engine.calls), 1)

    async def test_notes_receipt_uses_real_kernel_identity_and_refreshes_current_board(self):
        self.host.solver.learner_profile = 'notes'
        self.host.set_memory_instructions('trusted immutable instruction sentinel')
        signal = _Signal()
        before = self.host.current_context()
        noted = self.host.method_call('workspace', {
            'op': 'notes', 'base_revision': before['workspace_revision'],
            'observation_ref': before['observation_ref'], 'text': 'model private note sentinel',
        }, signal)
        self.assertEqual(noted['status'], 'noted')
        self.assertNotIn('notes', noted)
        memory = noted['context_memory']
        self.assertEqual(set(memory), {'version', 'revision', 'content', 'commit'})
        self.assertTrue(memory['commit'])
        instructions, serialized = memory['content'].split('\n\n', 1)
        self.assertEqual(instructions, 'trusted immutable instruction sentinel')
        initial = json.loads(serialized)
        self.assertEqual(initial['notes']['text'], 'model private note sentinel')
        self.assertEqual(initial['notes']['boundary']['kernel_generation'], self.host.kernel.generation)
        plan = {'plan_id': 'notes-action', 'start': before['observation_ref'],
                'workspace_revision': noted['workspace_revision'], 'goal': 'probe',
                'purpose': 'probe', 'assumptions': [],
                'steps': [{'action': {'name': 'ACTION1', 'data': {}},
                           'expect': {'cells': [{'x': 0, 'y': 0, 'value': 1}]}}]}
        result = self.host.method_call('execute_plan', plan, signal)
        self.assertEqual(result['applied_count'], 1)
        refreshed = result['context_memory']
        self.assertFalse(refreshed['commit'])
        self.assertEqual(refreshed['revision'], memory['revision'])
        current = json.loads(refreshed['content'].split('\n\n', 1)[1])
        self.assertEqual(current['observation_ref']['sequence'], 1)
        self.assertEqual(current['budget']['primitive_actions'], result['budget']['primitive_actions'])
        self.assertEqual(current['budget']['primitive_actions'], 1)
        self.assertEqual(current['budget']['scoring'], result['budget']['scoring'])
        self.assertEqual(current['budget']['scoring']['current_level']['paid_actions'], 1)
        self.assertEqual(current['notes']['observation_ref']['sequence'], 0)
        rejected = self.host.method_call('workspace', {
            'op': 'notes', 'base_revision': before['workspace_revision'],
            'observation_ref': before['observation_ref'], 'text': 'stale write',
        }, signal)
        self.assertEqual(rejected['status'], 'rejected')
        self.assertNotIn('context_memory', rejected)
        with self.assertRaises(ValueError):
            self.host.set_memory_instructions('changed instruction')

    async def test_initial_actor_v2_snapshot_and_continuation_deliver_score_facts(self):
        from asterion.applications.prime.p7.prompt import build_autonomous_prompt, initial_research_prompt
        from tests.test_prime_p7_score_planning import EXPECTED_BUDGET_SCOPE
        instructions = build_autonomous_prompt()
        initial = initial_research_prompt(self.host, instructions)
        expected = self.host.current_context()['budget']
        self.assertEqual(expected.get('scope'), EXPECTED_BUDGET_SCOPE)
        self.assertIn('scoring', expected)
        self.assertIn('budget.scoring', instructions)
        self.assertNotIn('整局满分100', instructions)
        actor = self.host.actor_context()
        delivered = json.loads(initial.split('Initial research context (authoritative observation):\n', 1)[1])
        result = self.host.method_call('workspace', {'op': 'read'}, _Signal())
        envelope = result['context_memory']
        self.assertEqual(envelope['version'], 'asterion.prime-context-memory/v2')
        self.assertIsNone(envelope['revision'])
        self.assertTrue(envelope['content'].startswith(instructions + '\n\n'))
        snapshot = json.loads(envelope['content'][len(instructions) + 2:])
        continuation = json.loads(self.host.continuation_prompt(1).split('\n', 1)[1])
        for name, context in (('actor', actor), ('initial', delivered),
                              ('v2-memory', snapshot), ('continuation', continuation)):
            with self.subTest(surface=name):
                budget = context['budget']
                self.assertEqual(budget['scope'], EXPECTED_BUDGET_SCOPE)
                self.assertEqual(set(budget), set(expected))
                dated = {'wall_time_remaining_seconds', 'time_snapshot'}
                self.assertEqual({k: v for k, v in budget.items() if k not in dated},
                                 {k: v for k, v in expected.items() if k not in dated})
                self.assertEqual(budget['time_snapshot']['deadline_monotonic'],
                                 expected['time_snapshot']['deadline_monotonic'])
                self.assertGreater(budget['time_snapshot']['sampled_at_monotonic'], 0)
                self.assertLessEqual(budget['time_snapshot']['sampled_at_monotonic'],
                                     budget['time_snapshot']['deadline_monotonic'])
                self.assertGreaterEqual(budget['wall_time_remaining_seconds'], 0)
        self.assertEqual(self.engine.calls, [])
        self.host.solver.learner_profile = 'autonomous'
        plan = {'plan_id': 'scope-action', 'start': actor['observation_ref'],
                'steps': [{'action': {'name': 'ACTION1', 'data': {}},
                           'expect': {'cells': [{'x': 0, 'y': 0, 'value': 1}]}}]}
        feedback = self.host.method_call('execute_plan', plan, _Signal())
        self.assertEqual(feedback['applied_count'], 1)
        refreshed = json.loads(feedback['context_memory']['content'][len(instructions) + 2:])
        continuation_after = json.loads(self.host.continuation_prompt(2).split('\n', 1)[1])
        for name, context in (('feedback', feedback), ('refreshed-memory', refreshed),
                              ('continuation-after', continuation_after)):
            with self.subTest(surface=name):
                self.assertEqual(context['budget']['scope'], EXPECTED_BUDGET_SCOPE)
                self.assertEqual(context['budget']['primitive_actions'], 1)
                self.assertEqual(context['budget']['scoring']['current_level']['paid_actions'], 1)

    async def test_cancel_after_durable_note_keeps_archive_without_cut_receipt(self):
        from unittest.mock import patch
        self.host.solver.learner_profile = 'notes'
        self.host.set_memory_instructions('trusted instructions')
        signal = _Signal()
        before = self.host.current_context()
        workspace = self.host.solver._workspace
        original = workspace._save_revision
        def cancel_after_commit(value):
            revision = original(value)
            signal.cancelled = True
            return revision
        with patch.object(workspace, '_save_revision', side_effect=cancel_after_commit):
            result = self.host.method_call('workspace', {
                'op': 'notes', 'base_revision': before['workspace_revision'],
                'observation_ref': before['observation_ref'], 'text': 'durable cancelled note',
            }, signal)
        self.assertEqual(result, {'status': 'rejected', 'reason': 'stopped'})
        self.assertEqual(self.host.current_context()['notes']['text'], 'durable cancelled note')
        self.assertEqual(self.engine.calls, [])

    async def test_oversized_context_snapshot_preserves_note_without_cut_receipt(self):
        self.host.solver.learner_profile = 'notes'
        self.host.set_memory_instructions('x' * (120 * 1024))
        before = self.host.current_context()
        result = self.host.method_call('workspace', {
            'op': 'notes', 'base_revision': before['workspace_revision'],
            'observation_ref': before['observation_ref'], 'text': 'n' * (16 * 1024),
        }, _Signal())
        self.assertEqual(result['status'], 'noted')
        self.assertNotIn('context_memory', result)
        self.assertEqual(self.host.current_context()['notes']['text'], 'n' * (16 * 1024))

    async def test_kernel_recovery_reuses_explicit_python_and_owner(self):
        import shlex
        import sys
        marker = self.root / 'wrapper-starts.txt'
        wrapper = self.root / 'trusted-research-python'
        wrapper.write_text('#!/bin/sh\n'
                           + 'printf "started\\n" >> ' + shlex.quote(str(marker)) + '\n'
                           + 'exec ' + shlex.quote(sys.executable) + ' "$@"\n')
        wrapper.chmod(0o700)
        host = P7ResearchRuntime(broker=self.broker, trace_client=self.trace,
            run_root=self.root, run_id=self.run_id, deadline_seconds=30,
            event_sink=lambda *_: None, python=wrapper)
        self.addAsyncCleanup(host.close)
        first = await host.execute('first-restricted-start', 'print(1)', _Signal())
        self.assertEqual(first.status, 'ok')
        lost = await host.execute('lose-restricted-worker', 'import os; os._exit(0)', _Signal())
        self.assertEqual(lost.status, 'error')
        restored = await host.execute('second-restricted-start', 'print(2)', _Signal())
        self.assertEqual(restored.status, 'ok')
        self.assertEqual(marker.read_text().splitlines(), ['started', 'started'])
        self.assertEqual(self.engine.calls, [])

    async def test_actor_revision_ack_does_not_repeat_context_and_read_stays_complete(self):
        value = draft()
        before = self.host.current_context()
        revised = self.host.method_call('workspace', {
            'op': 'revise', 'base_revision': before['workspace_revision'],
            **{key: value[key] for key in ('worldmap', 'task', 'evidence_sequences', 'correction')},
        }, _Signal())
        self.assertEqual(revised['status'], 'revised')
        for key in ('worldmap', 'model', 'task', 'reports', 'observation', 'experience'):
            self.assertNotIn(key, revised)
        self.assertEqual(revised['observation_ref'], before['observation_ref'])
        self.assertFalse(revised['needs_revision'])
        self.assertEqual(revised['correction'], value['correction'])
        current = self.host.current_context()
        read = self.host.method_call('workspace', {'op': 'read'}, _Signal())
        self.assertEqual(read['worldmap'], current['worldmap'])
        self.assertEqual(read['observation']['frame'], current['observation']['frame'])
        self.assertEqual(read['observation']['frame_delivery']['encoding'], 'raw')

    async def test_actor_context_and_continuation_keep_private_research_raw(self):
        self.assertTrue(callable(getattr(self.host, 'actor_context', None)))
        actor = self.host.actor_context()
        current = self.host.current_context()
        self.assertEqual(actor['observation_ref'], current['observation_ref'])
        self.assertIn('frame_delivery', actor['observation'])
        self.assertNotIn('frame_delivery', current['observation'])
        private = self.host._read_server.dispatch({'method': 'context', 'args': []})
        self.assertEqual(private['value']['observation'], current['observation'])
        self.assertNotIn('frame_delivery', private['value']['observation'])
        continuation = self.host.continuation_prompt(1)
        self.assertIn('p7_research.frame(sequence)', continuation)
        delivered = json.loads(continuation[continuation.index('\n') + 1:])
        self.assertEqual(delivered['observation'], actor['observation'])
        self.assertEqual(delivered['observation_ref'], actor['observation_ref'])

    async def test_animation_read_is_bound_to_exact_current_run_observation(self):
        reference = self.host.current_context()['observation_ref']
        result = self.host._read_server.dispatch({'method': 'animation', 'args': [reference, 0, 1]})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['value']['frames'], [[[0, 1]]])
        other = {**reference, 'run_id': 'other-attempt'}
        denied = self.host._read_server.dispatch({'method': 'animation', 'args': [other, 0, 1]})
        self.assertEqual(denied['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run_id = "research-story"
        self.root = Path(temporary.name) / self.run_id
        self.root.mkdir()
        self.engine = _Engine()
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history(self.run_id)
        self.trace = _TraceClient()
        self.writer = ConsoleEventWriter(self.root, self.run_id, self.broker.game.game_id)
        self.host = P7ResearchRuntime(
            broker=self.broker, trace_client=self.trace, run_root=self.root,
            run_id=self.run_id, deadline_seconds=30, event_sink=self.writer.append,
        )
        self.addAsyncCleanup(self.host.close)

    async def test_current_computation_reads_survive_kernel_loss_without_replay(self):
        source = "def learned_rule(x):\n    return x + 7\nprint('private-result')"
        result = await self.host.execute('learn-rule', source, _Signal())
        self.assertEqual(result.status, 'ok')
        record = self.host.kernel.cell_history()['items'][0]
        cell_id = record['cell_id']
        inspected = await self.host.execute('read-rule',
            "import inspect, p7_research as r\n"
            "print(inspect.getsource(learned_rule))\n"
            f"print(r.cell_read({cell_id!r})['text'])\n"
            f"print(r.cell_read({cell_id!r}, field='output')['text'])", _Signal())
        self.assertEqual(inspected.status, 'ok')
        output = json.loads(inspected.content[0]['text'])['stdout']
        self.assertIn('return x + 7', output)
        self.assertIn('private-result', output)
        await self.host.execute('failed-calculation', "raise ValueError('calculation-example')", _Signal())
        failed = self.host.kernel.cell_history()['items'][-1]
        self.assertIn('calculation-example', self.host.kernel.cell_read(failed['cell_id'], field='output')['text'])
        await self.host.execute('lose-kernel', 'import os; os._exit(0)', _Signal())
        recovered = await self.host.execute('read-after-recovery',
            "import p7_research as r\n"
            f"print(r.cell_read({cell_id!r})['text'])\n"
            "print('learned_rule' in globals())", _Signal())
        self.assertEqual(recovered.status, 'ok')
        output = json.loads(recovered.content[0]['text'])['stdout']
        self.assertIn(source, output)
        self.assertTrue(output.rstrip().endswith('False'))
        self.assertNotIn('private-result', json.dumps(self.host.actor_context()))
        self.assertEqual(self.engine.calls, [])

    async def test_failed_cell_research_is_inert_then_explicitly_reused_in_new_scope(self):
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.experience import load_experience
        from asterion.applications.prime.p7.private_trace import trace_identities_for

        source_code = 'def learned_move(value): return value + 2'
        result = await self.host.execute('call_old|fc_123', source_code, _Signal())
        self.assertEqual(result.status, 'ok')
        value = draft()
        value['correction']['changed'] = ['The earlier unit-step hypothesis failed.']
        self.host.method_call('workspace', {'op': 'revise',
            'base_revision': self.host.current_context()['workspace_revision'],
            **{key: value[key] for key in ('worldmap', 'task', 'evidence_sequences', 'correction')}}, _Signal())
        await self.host.close()
        (self.root / 'trace').mkdir()
        recorder = PrimeTraceRecorder(self.root / 'trace')
        recorder.append('arc.usage.reported', trace_identities_for('gpt-6.1-sol'),
                        {'input_tokens': 1, 'output_tokens': 1})
        run_root = (self.root.parent / 'next-attempt').resolve()
        run_root.mkdir()
        bundle = load_experience(self.root.parent.resolve(), game_id=self.broker.game.game_id,
            seed=self.broker.game.seed, win_levels=self.broker.game.win_levels,
            model_id='gpt-6.1-sol', current_run_id=run_root.name)
        engine = _Engine()
        broker = ArcBroker(engine=engine)
        broker.bind_history(run_root.name)
        host = P7ResearchRuntime(broker=broker, trace_client=_TraceClient(), run_root=run_root,
            run_id=run_root.name, deadline_seconds=30, event_sink=lambda *_: None, experience=bundle)
        self.addAsyncCleanup(host.close)
        self.assertTrue(host.current_context()['needs_revision'])
        self.assertEqual(host.current_context()['experience']['latest']['source_run_id'], self.run_id)
        audit_path = run_root / 'research' / 'experience-consumption.json'
        self.assertFalse(json.loads(audit_path.read_text())['loaded'])
        host.mark_experience_loaded()
        result = await host.execute('call_new|fc_456',
            "import p7_research\n"
            "assert 'learned_move' not in globals()\n"
            f"prior = p7_research.experience({self.run_id!r}, 'cells')['items'][0]\n"
            "exec(prior['source'])\n"
            "assert learned_move(40) == 42\n"
            "prime_workspace.export('reused-source', prior['source'])", _Signal())
        self.assertEqual(result.status, 'ok')
        eid = json.loads(result.content[0]['text'])['kernel_exports'][0]['export_id']
        value = draft([eid])
        value['correction']['changed'] = ['Retained prior code after checking it against the current task.']
        prepared = await host.execute('new-draft', f"prime_workspace.export('draft', {value!r})", _Signal())
        draft_id = json.loads(prepared.content[0]['text'])['kernel_exports'][0]['export_id']
        published = host.method_call('workspace', {'op': 'publish',
            'base_revision': host.current_context()['workspace_revision'], 'draft_export_id': draft_id}, _Signal())
        self.assertEqual(published['status'], 'published')
        self.assertFalse(host.current_context()['needs_revision'])
        audit = json.loads(audit_path.read_text())
        self.assertTrue(audit['loaded'])
        self.assertEqual(audit['reads'][0]['kind'], 'cells')
        self.assertTrue(audit['revisions'][-1]['program_reused'])
        self.assertEqual(audit['revisions'][-1]['workspace_revision'], published['workspace_revision'])
        self.assertEqual(engine.calls, [])

    async def test_program_export_publish_plan_and_real_counterexample(self):
        value = draft()
        code = (
            "import p7_research\n"
            "assert p7_research.context()['observation_ref']['sequence'] == 0\n"
            "import json\n"
            "def transition(position): return position + (1 if position == 0 else 8)\n"
            "position = 0; steps = []\n"
            "for _ in range(3):\n"
            "    position = transition(position)\n"
            "    steps.append({'action': {'name': 'ACTION1', 'data': {}}, 'expect': {'cells': [{'x': 0, 'y': 0, 'value': position % 16}]}})\n"
            "print(json.dumps(steps))\n"
            f"draft = {value!r}\n"
            "prime_workspace.export('draft', draft)\n"
        )
        result = await self.host.execute("cell-1", code, _Signal())
        self.assertEqual(result.status, "ok")
        metadata = json.loads(result.content[-1]["text"])
        export_id = metadata["kernel_exports"][0]["export_id"]
        context = self.host.current_context()
        published = self.host.method_call("workspace", {
            "op": "publish", "base_revision": context["workspace_revision"],
            "draft_export_id": export_id,
        }, _Signal())
        self.assertEqual(published["status"], "published")
        context = self.host.current_context()
        result = self.host.method_call("execute_plan", {
            "plan_id": "program-plan", "start": context["observation_ref"],
            "workspace_revision": context["workspace_revision"],
            "goal": "检验移动规律", "purpose": "probe", "assumptions": [],
            "steps": json.loads(metadata["stdout"]),
        }, _Signal())
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(len(self.trace.transitions), 2)
        self.assertEqual(len(self.engine.calls), 2)
        self.assertTrue(self.host.current_context()['needs_revision'])
        value['evidence_sequences'] = [0, 1, 2]
        value['correction']['changed'] = ['第二步反例否定位置相关步幅']
        revised = self.host.method_call('workspace', {
            'op': 'revise', 'base_revision': self.host.current_context()['workspace_revision'],
            **{key: value[key] for key in ('worldmap', 'task', 'evidence_sequences', 'correction')},
        }, _Signal())
        self.assertEqual(revised['status'], 'revised')
        self.assertFalse(self.host.current_context()['needs_revision'])
        rows = read_console_events(self.root, self.run_id, self.broker.game.game_id)
        kinds = [row["kind"] for row in rows]
        for kind in ("compute_task", "model_revision", "plan", "feedback"):
            self.assertIn(kind, kinds)
        self.assertNotIn("def transition", json.dumps(rows))

    async def test_pause_holds_next_model_round_until_same_run_resumes(self):
        current = self.host.current_context()
        write_control_request(self.root, run_id=self.run_id, command_id="pause-1",
                              request_sequence=1, operation="pause")
        pending = asyncio.create_task(self.host.admit_round(1, _Signal()))
        await asyncio.sleep(0.08)
        self.assertFalse(pending.done())
        self.assertEqual(self.host.control.snapshot()["state"], "paused")
        write_control_request(self.root, run_id=self.run_id, command_id="resume-1",
                              request_sequence=2, operation="resume")
        self.assertTrue(await asyncio.wait_for(pending, 1))
        self.assertEqual(self.host.current_context()["observation_ref"], current["observation_ref"])
        self.assertEqual(self.engine.calls, [])

    async def test_pause_finishes_cell_but_holds_its_response(self):
        pending = asyncio.create_task(self.host.execute(
            "pause-cell", "import time; time.sleep(0.15); retained = 7", _Signal()
        ))
        await _wait_until(lambda: self.host.cell_count == 1,
                          "kernel did not report cell_started within five seconds")
        write_control_request(self.root, run_id=self.run_id, command_id="pause-cell-1",
                              request_sequence=1, operation="pause")
        await _wait_until(
            lambda: self.host.control.snapshot()["state"] == "paused"
            and self.host.kernel.status()["execution_status"] == "ok",
            "running cell did not finish and settle the pause within five seconds",
        )
        self.assertFalse(pending.done())
        write_control_request(self.root, run_id=self.run_id, command_id="resume-cell-1",
                              request_sequence=2, operation="resume")
        self.assertEqual((await asyncio.wait_for(pending, 1)).status, "ok")

    async def test_kernel_loss_restores_only_checkpoint_and_requires_calibration(self):
        exported = await self.host.execute(
            'checkpoint-source',
            "prime_workspace.export('source', 'def restored_rule(value): return value + 1')\n"
            "prime_workspace.export('saved-state', {'position': 2})", _Signal(),
        )
        refs = {item['name']: item['export_id'] for item in json.loads(exported.content[0]['text'])['kernel_exports']}
        value = draft([refs['source']])
        prepared = await self.host.execute('checkpoint-draft',
            f"prime_workspace.export('draft', {value!r})", _Signal())
        draft_id = json.loads(prepared.content[0]['text'])['kernel_exports'][0]['export_id']
        published = self.host.method_call('workspace', {
            'op': 'publish', 'base_revision': self.host.current_context()['workspace_revision'],
            'draft_export_id': draft_id,
        }, _Signal())
        self.assertEqual(published['status'], 'published')
        saved = self.host.method_call('workspace', {
            'op': 'checkpoint', 'revision': self.host.current_context()['workspace_revision'],
            'state_export_id': refs['saved-state'], 'analyzed_through': 0,
        }, _Signal())
        self.assertEqual(saved['status'], 'checkpointed')
        previous_generation = self.host.kernel.generation
        lost = await self.host.execute('lose-computation', 'import os; os._exit(0)', _Signal())
        self.assertEqual(lost.status, 'error')
        restored = await self.host.execute('restored-computation',
            "print(restored_rule(41)); print(state['position'])", _Signal())
        self.assertEqual(restored.status, 'ok')
        self.assertEqual(json.loads(restored.content[0]['text'])['stdout'].split(), ['42', '2'])
        self.assertNotEqual(self.host.kernel.generation, previous_generation)
        self.assertTrue(self.host.current_context()['requires_calibration'])
        self.assertEqual(self.engine.calls, [])


class TestResearchOperatorBridge(unittest.TestCase):
    def test_persistent_loop_preserves_namespace_and_settled_errors(self):
        import socket
        from asterion.agents.prime._tool_bridge import ToolBridgeServer, PROTOCOL as _BRIDGE_PROTOCOL
        from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'bridge-story'
            root.mkdir()
            broker = ArcBroker(engine=_Engine())
            broker.bind_history('bridge-story')
            host = P7ResearchRuntime(
                broker=broker, trace_client=_TraceClient(), run_root=root,
                run_id='bridge-story', deadline_seconds=20,
                event_sink=lambda *_: None,
            )
            actor, server = socket.socketpair()
            actor.settimeout(10)
            bridge = ToolBridgeServer(server, P7ToolDispatch(host, _TraceClient(), run_id='bridge-story'))
            bridge.start()
            reader = actor.makefile('rb')
            try:
                def execute(call_id, code):
                    actor.sendall((json.dumps({
                        'protocol': _BRIDGE_PROTOCOL, 'type': 'execute',
                        'request_id': call_id, 'code': code,
                    }) + '\n').encode())
                    return json.loads(reader.readline())

                first = execute('first', 'retained = 41; print(retained)')
                self.assertEqual(first['status'], 'ok')
                large = execute('large', "print(chr(1) * (320 * 1024)); print('FINAL_ACTION')")
                self.assertEqual(large['status'], 'ok')
                metadata = json.loads(large['output'])
                self.assertFalse(metadata['stdout_truncated'])
                self.assertTrue(metadata['stdout'].endswith('FINAL_ACTION\n'))
                self.assertEqual(metadata['stdout'].count(chr(1)), 320 * 1024)
                failed = execute('bad', 'print(missing_name)')
                self.assertEqual(failed['status'], 'error')
                self.assertIn('NameError', failed['output'])
                final = execute('fixed', 'print(retained + 1)')
                self.assertEqual(final['status'], 'ok')
                self.assertEqual(json.loads(final['output'])['stdout'].strip(), '42')
            finally:
                reader.close()
                actor.close()
                bridge.close()
            self.assertTrue(bridge._host_closed)
            self.assertTrue(bridge._loop.is_closed())
            self.assertTrue(host.kernel.status()['closed'])
