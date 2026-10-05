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


class TestP7ResearchRuntime(unittest.IsolatedAsyncioTestCase):
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
        await asyncio.sleep(0.08)
        write_control_request(self.root, run_id=self.run_id, command_id="pause-cell-1",
                              request_sequence=1, operation="pause")
        await asyncio.sleep(0.25)
        self.assertFalse(pending.done())
        self.assertEqual(self.host.control.snapshot()["state"], "paused")
        self.assertEqual(self.host.kernel.status()["execution_status"], "ok")
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
        from asterion.applications.prime.p7.operator import _IpythonBridgeServer, _BRIDGE_PROTOCOL

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
            bridge = _IpythonBridgeServer(server, host, _TraceClient())
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
