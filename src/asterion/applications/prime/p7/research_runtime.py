"""Compose Prime computation with P7 evidence, plans and cooperative control.

This application adapter owns no model loop and no game engine. Research
workers receive only the read service; actor calls use the operator bridge.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from asterion.agents.prime.ipython import KernelBootstrap, KernelLimits, PersistentIpythonHost
from asterion.agents.prime.ipython_worker import SubprocessPythonWorker
from asterion.agents.prime.tools import PrimeToolResult

from .broker import ArcBrokerError
from .actor_projection import ACTOR_FRAME_INSTRUCTION, project_actor_context, project_actor_result
from .experience import CellArchive
from .research_bridge import ResearchReadServer
from .solver import Solver
from .solver_control import SolverControl
from asterion.agents.prime.continuation import AUTONOMOUS_RESEARCH_GUIDANCE


class _EvidenceBroker:
    """Retain the existing broker's dispatch and trace receipt boundary."""

    def __init__(self, broker, trace_client):
        self._broker, self._trace_client = broker, trace_client
        self._evidence_lock = threading.RLock()

    def __getattr__(self, name):
        return getattr(self._broker, name)

    def observe(self):
        try:
            return self._broker.observe()
        except ArcBrokerError:
            return self._broker.terminal_snapshot().observation

    def status(self):
        try:
            return self._broker.status()
        except ArcBrokerError:
            return self._broker.terminal_snapshot().status

    def act_checked(self, plan, *, probe_preparation: Mapping[str, object] | None = None):
        with self._evidence_lock:
            return self._act_checked(plan, probe_preparation=probe_preparation)

    def _act_checked(self, plan, *, probe_preparation: Mapping[str, object] | None = None):
        start = len(self._broker.journal)
        try:
            result = self._broker.act_checked(plan, probe_preparation=probe_preparation)
        finally:
            self._trace_client._record_transitions(self._broker.journal[start:])
        self._trace_client._count("checked_plans")
        self._trace_client._count("matched_expectations", sum(
            item.get('prediction_present', True) and item.get('stop_reason') == 'matched'
            for item in result.get('feedback', [])))
        self._trace_client._count("unexecuted_items", result["unexecuted_count"])
        if result["mismatch"] is not None:
            self._trace_client._count("mismatches")
        return result


class _KernelHandle:
    """Keep the research store bound to the current Prime kernel generation."""

    def __init__(self, owner):
        self._owner = owner

    def read_export(self, export_id):
        return self._owner.kernel.read_export(export_id)

    def status(self):
        return self._owner.kernel.status()

    @property
    def generation(self):
        return self._owner.kernel.generation

    @property
    def lost(self):
        return bool(self._owner.kernel.status()["lost"])


class _ResearchSignal:
    def __init__(self, owner, parent=None):
        self._owner, self._parent = owner, parent

    @property
    def cancelled(self):
        return (
            self._owner._closed
            or bool(getattr(self._parent, "cancelled", False))
            or self._owner.poll()["state"] == "stop_requested"
        )


class P7ResearchRuntime:
    """Thin application host over the generic Prime workspace."""

    def __init__(self, *, broker, trace_client, run_root: Path, run_id: str,
                 deadline_seconds: float, event_sink, worker=None, worker_factory=None,
                 deadline_monotonic: float | None = None,
                 limits: KernelLimits | None = None, experience=None,
                 learner_profile='legacy', task_deadline=None):
        if worker_factory is not None and not callable(worker_factory):
            raise ValueError("research worker factory unavailable")
        self._worker_factory = worker_factory or SubprocessPythonWorker
        self._closed = False
        self.cell_count = 0
        self._lost = False  # The application can rebuild a computation kernel.
        self._lock = threading.RLock()
        self._broker = _EvidenceBroker(broker, trace_client)
        self._sink = event_sink
        self._last_control = None
        self._experience = experience
        self._memory_instructions = None
        self._cell_archive = CellArchive(run_root)
        self.control = SolverControl(run_root, run_id, time.monotonic() + deadline_seconds
                                     if deadline_monotonic is None else deadline_monotonic,
                                     clock=time.monotonic, task_deadline=task_deadline)
        self._read_server = ResearchReadServer(
            context=lambda: self.solver.current_context(),
            history=self._broker.history,
            frame=self._broker.frame_at,
            artifact=lambda export_id: self.solver.artifact(export_id),
            experience=(lambda source, kind, start, limit, artifact_id:
                        experience.read(source, kind, start=start, limit=limit, artifact_id=artifact_id))
                       if experience is not None else None,
            animation=self._animation,
            transition=self._transition,
            cell_history=lambda start, limit: self.kernel.cell_history(start=start, limit=limit),
            cell_read=lambda cell_id, field, start, limit: self.kernel.cell_read(
                cell_id, field=field, start=start, limit=limit),
            diagnostic_sink=self._read_diagnostic,
        )
        try:
            module_source = self._read_server.start()
            self._bootstrap = KernelBootstrap(
                modules={"p7_research": module_source}, initial_data={},
                workspace=run_root / "research-kernel",
            )
            self._limits = limits or KernelLimits()
            self.kernel = self._new_kernel(worker)
            self.solver = Solver(
                broker=self._broker, kernel=_KernelHandle(self), control=self.control,
                workspace_root=run_root / "research", run_id=run_id,
                attempt_id=run_id, event_sink=event_sink, experience=experience,
                diagnostics=getattr(trace_client, 'processing_diagnostics', None),
                learner_profile=learner_profile,
            )
            if experience is not None:
                experience.bind(run_root, self.solver.experience_event)
            self.poll()
        except BaseException:
            self._read_server.close()
            raise

    def _new_kernel(self, worker=None):
        return PersistentIpythonHost(
            worker=worker if worker is not None else self._worker_factory(), bootstrap=self._bootstrap,
            limits=self._limits,
            observer=self._kernel_event,
        )

    def _read_diagnostic(self, value):
        if hasattr(self, 'solver'):
            diagnostic = self.solver.diagnostics.record(value)
            try:
                self._sink('diagnostic', diagnostic)
            except Exception:
                pass  # Independent private log/context/summary retain the fault.

    def _committed_observation(self, sequence):
        """Read only paired broker snapshots whose existing history is settled.

        The caller holds the same lock as the runtime action path. Engines with
        a write-ahead journal must also have acknowledged the transaction;
        advancing that journal proves earlier actions committed sequentially.
        """
        journal = self._broker.journal
        observations = self._broker.replay_observations
        records = tuple(self._broker._bound_history())
        if (type(sequence) is not int or sequence < 0 or sequence > len(journal)
                or sequence >= len(observations) or sequence >= len(records)):
            raise ValueError('observation evidence unavailable')
        observation, record = observations[sequence], records[sequence]
        expected_hash = (journal[sequence - 1].after_sha256 if sequence else
                         journal[0].before_sha256 if journal else
                         self._broker.observation_reference()['observation_sha256'])
        if (record.sequence != sequence or record.run_id != self.solver.run_id
                or record.after_state_sha256 != expected_hash
                or record.state != observation.state
                or record.levels_completed != observation.levels_completed):
            raise ValueError('observation evidence unavailable')
        if sequence:
            transition = journal[sequence - 1]
            if (transition.sequence != sequence or record.action != transition.action
                    or record.data != transition.data
                    or record.before_state_sha256 != transition.before_sha256
                    or records[sequence - 1].after_state_sha256 != transition.before_sha256):
                raise ValueError('transition evidence unavailable')
            transaction = getattr(self._broker._engine, 'action_journal', None)
            if transaction is not None:
                receipt = transaction.snapshot()
                if (type(receipt) is not dict or type(receipt.get('sequence')) is not int
                        or receipt['sequence'] < sequence):
                    raise ValueError('transition evidence unavailable')
                if receipt['sequence'] == sequence:
                    if (receipt.get('phase') != 'committed' or receipt.get('outcome_known') is not True
                            or receipt.get('action') != {'name': transition.action, 'data': dict(transition.data)}
                            or receipt.get('before', {}).get('observation_sha256') != transition.before_sha256
                            or receipt.get('observation_ref', {}).get('sequence') != sequence
                            or receipt.get('observation_ref', {}).get('observation_sha256') != transition.after_sha256):
                        raise ValueError('transition evidence unavailable')
        reference = {'run_id': self.solver.run_id, 'attempt_id': self.solver.attempt_id,
                     'level': min(observation.levels_completed + 1, self._broker.game.win_levels),
                     'sequence': sequence, 'observation_sha256': expected_hash}
        return observation, reference

    def _transition(self, sequence):
        if type(sequence) is not int or sequence < 1:
            raise ValueError('transition evidence unavailable')
        with self._broker._evidence_lock:
            after, after_reference = self._committed_observation(sequence)
            _, before_reference = self._committed_observation(sequence - 1)
            transition = self._broker.journal[sequence - 1]
            from .dynamic_evidence import AnimationFrames
            return {'sequence': sequence, 'action': transition.action, 'data': dict(transition.data),
                    'before_observation_ref': before_reference, 'after_observation_ref': after_reference,
                    'state': after.state, 'levels_completed': after.levels_completed,
                    'after_animation_ref': AnimationFrames.capture(after.frame).reference()}

    def _animation(self, reference, start, limit):
        if (type(reference) is not dict or set(reference) != {'run_id', 'attempt_id', 'level', 'sequence', 'observation_sha256'}
                or reference['run_id'] != self.solver.run_id or reference['attempt_id'] != self.solver.attempt_id
                or type(reference['sequence']) is not int or reference['sequence'] < 0
                or type(reference['level']) is not int or reference['level'] < 1):
            raise ValueError('animation reference unavailable')
        with self._broker._evidence_lock:
            observation, expected_reference = self._committed_observation(reference['sequence'])
            if reference != expected_reference:
                raise ValueError('animation reference unavailable')
            from .dynamic_evidence import AnimationFrames
            frames = AnimationFrames.capture(observation.frame)
            return {'observation_ref': expected_reference, 'animation_ref': frames.reference(), 'start': start,
                    'frames': [[list(row) for row in grid] for grid in frames.page(start, limit)]}

    def _kernel_event(self, kind, payload):
        if kind == "cell_started":
            self.cell_count += 1
        self.solver.kernel_event(kind, payload)

    def poll(self):
        with self._lock:
            position = len(self._broker.journal)
            observation_hash = self._broker.observation_reference()["observation_sha256"]
            status = self.control.poll(position, observation_hash)
            signature = (status["state"], status["command_id"], status["request_sequence"])
            if signature != self._last_control:
                self._last_control = signature
                context = self.solver.current_context()
                self._sink("run_control", {
                    "source_action_sequence": position, "observation_sha256": observation_hash,
                    "level": context["observation_ref"]["level"],
                    "workspace_revision": context["workspace_revision"],
                    "task_id": None, "origin": "operator",
                    **{key: status[key] for key in ("state", "command_id", "request_sequence", "reason")},
                })
            return status

    async def admit_round(self, round_index, signal):
        del round_index
        # Do not hold a model_round activity across its nested tool calls.
        # The bridge waits at the same boundary while the existing Pi loop owns
        # model generation; counting the whole round would deadlock pause.
        while not self._closed and not signal.cancelled:
            if self.solver.current_context()["processing_blocked"]:
                return False
            status = self.poll()
            if status["state"] == "running":
                return True
            if status["state"] == "stop_requested":
                return False
            await asyncio.sleep(0.05)
        return False

    async def _recover_kernel(self, signal):
        if not self.kernel.status()["lost"]:
            return
        checkpoint = self.solver.checkpoint()
        previous = self.kernel
        self.kernel = self._new_kernel()
        self.solver.kernel_recovered()
        try:
            if checkpoint is not None:
                sources = tuple(previous.read_export(ref) for ref in checkpoint["source_export_ids"])
                data = {}
                for field, name in (("state_export_id", "state"), ("frontier_export_id", "frontier")):
                    ref = checkpoint.get(field)
                    if ref is not None:
                        data[name] = previous.read_export(ref)
                await self.kernel.restore(sources, data, signal)
        except BaseException:
            await self.kernel.close()
            self.kernel = previous
            raise

    async def execute(self, call_id, code, signal):
        if not await self.admit_round(0, signal):
            return PrimeToolResult(call_id, "error", ({"type": "text", "text": "Research stopped."},))
        combined = _ResearchSignal(self, signal)
        if not self.control.enter("cell"):
            return PrimeToolResult(call_id, "error", ({"type": "text", "text": "Research is paused."},))
        try:
            await self._recover_kernel(combined)
            generation = self.kernel.generation
            self._cell_archive.started(call_id, generation, code)
            result = await self.kernel.execute(call_id, code, combined)
            export_ids = []
            for content in result.content:
                if content.get("type") == "text":
                    try:
                        metadata = json.loads(content["text"])
                        if type(metadata) is dict:
                            export_ids.extend(item["export_id"] for item in metadata.get("kernel_exports", [])
                                              if type(item) is dict and type(item.get("export_id")) is str)
                    except (ValueError, KeyError):
                        pass
            self._cell_archive.finished(call_id, generation, result.status, export_ids)
            # A lost read-only computation has no uncertain environment action.
            # Surface the loss as a recoverable tool error, with kernel metadata.
            if result.status == "uncertain":
                result = PrimeToolResult(result.call_id, "error", result.content)
        finally:
            self.control.leave("cell")
            self.poll()
        # Pi performs further model turns inside one RPC round. Withhold the
        # settled tool response during pause so that it cannot dispatch the
        # next model turn before the application admits it.
        await self.admit_round(0, signal)
        return result

    def method_call(self, method, params, signal):
        while not self._closed and not signal.cancelled:
            status = self.poll()
            if status["state"] == "running":
                break
            if status["state"] == "stop_requested":
                return {"status": "rejected", "reason": "stopped"}
            time.sleep(0.05)
        else:
            return {"status": "rejected", "reason": "stopped"}
        if method == "workspace" and isinstance(params, Mapping):
            result = self.solver.workspace(params.get("request", params))
        elif method == "execute_plan" and isinstance(params, Mapping):
            result = self.solver.execute_plan(params.get("plan", params))
        else:
            raise ValueError("research method unavailable")
        while not self._closed and not signal.cancelled:
            if self.poll()["state"] not in {"pause_requested", "paused"}:
                break
            time.sleep(0.05)
        if self._closed or signal.cancelled:
            return {'status': 'rejected', 'reason': 'stopped'}
        projected = project_actor_result(method, params, result)
        request = params.get('request', params) if isinstance(params, Mapping) else {}
        commit = method == 'workspace' and request.get('op') == 'notes' and result.get('status') == 'noted'
        if result.get('status') != 'rejected':
            memory = self._context_memory(commit=commit)
            if memory is not None:
                projected['context_memory'] = memory
        return projected

    def set_memory_instructions(self, prompt: str):
        """Capture the exact immutable operator guidance before initial state."""
        if (type(prompt) is not str or not prompt.strip()
                or len(prompt.encode('utf-8')) > 128 * 1024
                or (self._memory_instructions is not None and self._memory_instructions != prompt)):
            raise ValueError('research memory instructions unavailable')
        self._memory_instructions = prompt

    def _context_memory(self, *, commit):
        if self._memory_instructions is None:
            return None
        try:
            context = self.actor_context()
            notes = context.get('notes')
            if commit and notes is None:
                return None
            content = self._memory_instructions + '\n\n' + json.dumps(
                context, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            if len(content.encode('utf-8')) > 128 * 1024:
                return None
            return {'version': 'asterion.prime-context-memory/v2',
                    'revision': None if notes is None else notes['revision'], 'content': content, 'commit': commit}
        except (ValueError, TypeError, KeyError, OSError):
            # A failed view refresh cannot change the committed note or hide an
            # environment action result; absence leaves the model view uncut.
            return None

    def current_context(self):
        return self.solver.current_context()

    def actor_context(self):
        return project_actor_context(self.current_context())

    def mark_experience_loaded(self):
        """Called by the operator after adding the prior to the actor prompt."""
        if self._experience is not None:
            self._experience.mark_loaded()

    def continuation_prompt(self, round_index):
        return (
            f"Continue research round {round_index} from the retained Prime workspace. "
            "Use actual feedback and current research notes to choose your own next hypothesis, experiment, optional computation or useful action. "
            "A partial model or no-route search does not prove the task impossible. Retain useful free-form findings, assumptions and open questions in existing workspace revisions or accepted exports. "
            "Submit real actions only with p7_execute_plan. "
            + AUTONOMOUS_RESEARCH_GUIDANCE + " " + ACTOR_FRAME_INSTRUCTION + "\n"
            + json.dumps(self.actor_context(), ensure_ascii=False, separators=(",", ":"))
        )

    def request_stop(self):
        self.control.request("stop", "operator-stop")

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.control.request("stop", "operator-close")
        finally:
            try:
                await self.kernel.close()
            finally:
                await asyncio.to_thread(self._read_server.close)
