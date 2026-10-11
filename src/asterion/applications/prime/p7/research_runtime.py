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

from asterion.agents.prime.ipython import KernelBootstrap, KernelLimits
from asterion.agents.prime._workspace_owner import WorkspaceOwner
from asterion.agents.prime.tools import PrimeToolResult

from .broker import ArcBrokerError
from .actor_projection import ACTOR_FRAME_INSTRUCTION, project_actor_context, project_actor_result
from .experience import CellArchive
from .research_bridge import ResearchReadServer
from .research_chain import P7ResearchChain
from .solver import Solver
from .solver_control import SolverControl
from .rollout_runtime import RolloutRuntime
from asterion.agents.prime.continuation import (
    AUTONOMOUS_RESEARCH_GUIDANCE, RESOURCE_AWARE_RESEARCH_GUIDANCE,
)


# P7 raw evidence pages carry full board pixels. Keep their ordinary Python
# representation readable; bulk display remains separately bounded and paged.
P7_KERNEL_MAX_OUTPUT_BYTES = 2 * 1024 * 1024


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
                 deadline_seconds: float | None, event_sink, workspace_owner=None, python=None,
                 deadline_monotonic: float | None = None,
                 limits: KernelLimits | None = None, experience=None,
                 learner_profile='legacy', task_deadline=None, auto_rollout=False):
        self._workspace_owner = workspace_owner or WorkspaceOwner()
        self._owns_workspace_owner = workspace_owner is None
        self._python = python
        self._closed = False
        self.cell_count = 0
        self._lost = False  # The application can rebuild a computation kernel.
        self._lock = threading.RLock()
        self._operation_lock = asyncio.Lock()
        self._auto_rollout_enabled = bool(auto_rollout)
        self._broker = _EvidenceBroker(broker, trace_client)
        self._sink = event_sink
        self._last_control = None
        self._experience = experience
        self._memory_instructions = None
        self._cell_archive = CellArchive(run_root)
        self.control = SolverControl(run_root, run_id,
                                     (None if deadline_seconds is None else time.monotonic() + deadline_seconds)
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
            rollout_trace=(lambda ref, section, start, limit:
                           self._rollouts.read_trace(ref, section, start, limit))
                          if auto_rollout else None,
        )
        try:
            module_source = self._read_server.start()
            self._bootstrap = KernelBootstrap(
                modules={"p7_research": module_source}, initial_data={},
                workspace=run_root / "research-kernel",
            )
            self._limits = limits or KernelLimits(max_output_bytes=P7_KERNEL_MAX_OUTPUT_BYTES)
            self.kernel = self._new_kernel()
            self.solver = Solver(
                broker=self._broker, kernel=_KernelHandle(self), control=self.control,
                workspace_root=run_root / "research", run_id=run_id,
                attempt_id=run_id, event_sink=event_sink, experience=experience,
                diagnostics=getattr(trace_client, 'processing_diagnostics', None),
                learner_profile=learner_profile,
            )
            self._rollouts = RolloutRuntime(self, run_root) if auto_rollout else None
            if self._rollouts is not None:
                self.solver.auto_evaluate = self._rollouts.evaluate
                self.solver.auto_observe = self._rollouts.record_feedback
            self._research_chain = None
            self._research_chain_faults = 0
            try:
                self._research_chain = P7ResearchChain(run_root=run_root, workspace=self.solver._workspace)
            except Exception:
                # Optional evidence indexing cannot prevent a research run.
                self._research_chain_faults += 1
            if experience is not None:
                experience.bind(run_root, self.solver.experience_event)
            self.poll()
        except BaseException:
            self._read_server.close()
            raise

    def _new_kernel(self):
        return self._workspace_owner.create_workspace(
            self._bootstrap, self._limits, python=self._python,
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
            if status['state'] == 'stop_requested' and callable(getattr(self, '_on_stop', None)):
                self._on_stop()
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
        sources, data = (), {}
        if checkpoint is not None:
            sources = tuple(previous.read_export(ref) for ref in checkpoint['source_export_ids'])
            for field, name in (('state_export_id', 'state'), ('frontier_export_id', 'frontier')):
                ref = checkpoint.get(field)
                if ref is not None:
                    data[name] = previous.read_export(ref)
        self.kernel = await self._workspace_owner.restore_workspace(previous, sources, data, signal)
        if self._rollouts is not None:
            await self._rollouts.invalidate(signal)
        self.solver.kernel_recovered()

    async def execute(self, call_id, code, signal):
        async with self._operation_lock:
            return await self._execute_cell(call_id, code, signal)

    async def _execute_cell(self, call_id, code, signal):
        if not await self.admit_round(0, signal):
            return PrimeToolResult(call_id, "error", ({"type": "text", "text": "Research stopped."},))
        combined = _ResearchSignal(self, signal)
        if not self.control.enter("cell"):
            return PrimeToolResult(call_id, "error", ({"type": "text", "text": "Research is paused."},))
        try:
            await self._recover_kernel(combined)
            generation = self.kernel.generation
            try:
                history_start = self.kernel.cell_history()['total']
            except Exception:
                history_start = None
            self._cell_archive.started(call_id, generation, code)
            try:
                result = await self.kernel.execute(call_id, code, combined)
            finally:
                self._observe_research('computation', self.kernel, history_start)
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
            if self._rollouts is not None and not self.kernel.status()['lost']:
                try:
                    history = self.kernel.cell_history(start=history_start, limit=1)
                    await self._rollouts.collect_actor_calls(combined, history['items'][0]['cell_id'])
                except Exception:
                    # Telemetry failure is explicit and supplies no proactive
                    # coverage; it cannot change a recorded computation outcome.
                    self._rollouts.telemetry_failed()
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
        return self._cell_resource_result(result)

    def _host_resource_snapshot(self, context=None):
        """Small current host facts; no workspace, pixels or policy decision."""
        if context is None:
            context = self.solver.current_context()
        if any(type(context[key]) is not bool for key in ('environment_result_unknown', 'processing_blocked')):
            raise ValueError('current resource certainty unavailable')
        budget = context['budget']
        scoring = budget['scoring']
        level = scoring['current_level']
        snapshot = {
            'origin': 'application-host',
            'observation_ref': context['observation_ref'],
            'environment_result_unknown': context['environment_result_unknown'],
            'processing_blocked': context['processing_blocked'],
            **{key: budget[key] for key in ('action_cap', 'primitive_actions', 'actions_remaining', 'target_level')},
            'levels_completed': context['observation']['levels_completed'],
            'win_levels': scoring['win_levels'],
            'time_snapshot': budget['time_snapshot'],
            'current_level': None if level is None else {key: level[key] for key in (
                'level', 'paid_actions', 'baseline',
                'max_paid_actions_for_115', 'additional_paid_actions_preserving_115', 'paid_actions_exceeding_115',
                'max_paid_actions_for_100', 'additional_paid_actions_preserving_100', 'paid_actions_exceeding_100')},
        }
        # Copy through the same finite JSON representation used on the bridge.
        text = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        return json.loads(text) if len(text.encode('utf-8')) <= 2048 else None

    def _cell_resource_result(self, result):
        """Enrich only the trusted first envelope when the original cap permits."""
        try:
            first = result.content[0]
            if first.get('type') != 'text':
                return result
            metadata = json.loads(first['text'])
            if (type(metadata) is not dict
                    or not {'execution_status', 'generation', 'stdout', 'kernel_exports'} <= metadata.keys()):
                return result
            snapshot = self._host_resource_snapshot()
            if snapshot is None:
                return result
            metadata['host_resource_snapshot'] = snapshot
            text = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            if len(text.encode('utf-8')) > self._limits.max_output_bytes:
                return result
            return PrimeToolResult(result.call_id, result.status,
                                   ({**first, 'text': text}, *result.content[1:]))
        except Exception:
            # Optional sampling must never erase a settled computation or error.
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
            request = params.get("request", params)
            result = self.solver.workspace(request)
            self._observe_research('workspace_result', result)
        elif method == "execute_plan" and isinstance(params, Mapping):
            plan = params.get("plan", params)
            journal_start = self._research_journal_position()
            result = self.solver.execute_plan(plan)
            self._observe_experiment(plan, result, journal_start)
        else:
            raise ValueError("research method unavailable")
        while not self._closed and not signal.cancelled:
            if self.poll()["state"] not in {"pause_requested", "paused"}:
                break
            time.sleep(0.05)
        if self._closed or signal.cancelled:
            return {'status': 'rejected', 'reason': 'stopped'}
        projected = project_actor_result(method, params, result)
        rollouts = getattr(self, '_rollouts', None)
        if rollouts is not None:
            projected['rollout_accounting'] = rollouts.snapshot()
        request = params.get('request', params) if isinstance(params, Mapping) else {}
        commit = method == 'workspace' and request.get('op') == 'notes' and result.get('status') == 'noted'
        try:
            current = self.solver.current_context()
        except Exception:
            current = None
        if result.get('status') != 'rejected':
            try:
                # Reuse a successful capture. If it failed, the independently
                # available optional memory view may still retain valid evidence.
                memory = self._context_memory(commit=commit, context=current)
            except Exception:
                memory = None  # An optional view failure cannot fence an accepted result.
            if memory is not None:
                projected['context_memory'] = memory
            try:
                certainty = {key: current[key] for key in ('environment_result_unknown', 'processing_blocked')}
                if any(type(value) is not bool for value in certainty.values()):
                    raise ValueError('current certainty unavailable')
            except Exception:
                certainty = {'environment_result_unknown': True, 'processing_blocked': True}
            # These are current solver facts, including after historical NOTES reads.
            # A successful capture is shared by memory, certainty and resources.
            projected.update(certainty)
        if current is not None:
            try:
                snapshot = self._host_resource_snapshot(current)
                if snapshot is not None:
                    # The original plan projection's cap still owns its space.
                    # Enrichment is lowest priority; never trim recorded evidence.
                    candidates = ({**result, 'host_resource_snapshot': snapshot},
                                  {key: value for key, value in projected.items() if key != 'context_memory'}
                                  | {'host_resource_snapshot': snapshot})
                    if all(len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                          separators=(',', ':')).encode('utf-8')) <= 60 * 1024
                           for value in candidates):
                        projected['host_resource_snapshot'] = snapshot
            except Exception:
                pass
        state_view = self._tool_state_view(method, projected)
        if state_view is not None:
            projected['tool_state_view'] = state_view
        if (getattr(self.solver, 'learner_profile', None) == 'autonomous'
                and not (method == 'workspace' and request.get('op') in {
                    'context_archive_list', 'context_archive_read'})):
            # Private adapter facts: native Prime binds these to the real tool
            # group and removes them from model text. No Pi cursor is invented.
            projected['context_interaction'] = self._context_interaction(result, current)
        return projected

    async def async_method_call(self, method, params, signal):
        """P7 actor actions run off-loop, so their kernel evaluations can await."""
        async with self._operation_lock:
            if self._rollouts is not None:
                self._rollouts.loop = asyncio.get_running_loop()
                self._rollouts.signal = signal
            task = asyncio.create_task(asyncio.to_thread(self.method_call, method, params, signal))
            try:
                result = await asyncio.shield(task)
                if self._rollouts is not None and result.get('stop_reason') in {'reset-applied', 'level-advanced'}:
                    try:
                        await self._rollouts.invalidate(_ResearchSignal(self, signal))
                    except Exception:
                        self._rollouts.telemetry_failed()
                return result
            except asyncio.CancelledError:
                self.request_stop()
                await asyncio.shield(task)
                raise
            finally:
                if self._rollouts is not None:
                    self._rollouts.loop = None
                    self._rollouts.signal = None

    @staticmethod
    def _context_interaction(result, context):
        """Describe settled evidence, without interpreting game meaning or text."""
        unknown = (not isinstance(context, Mapping)
                   or any(type(context.get(key)) is not bool or context[key]
                          for key in ('environment_result_unknown', 'processing_blocked'))
                   or any(result.get(key) is True
                          for key in ('environment_result_unknown', 'processing_blocked'))
                   or 'uncertain_step' in result
                   or result.get('stop_reason') in {'unknown', 'environment-result-unknown'})
        negative = (result.get('status') == 'rejected'
                    or result.get('stop_reason') in {
                        'prediction-mismatch', 'precondition-mismatch', 'processing-failed'})
        feedback = result.get('feedback')
        preconditions = result.get('precondition_feedback')
        negative = negative or any(
            isinstance(row, Mapping) and isinstance(row.get('differences'), list)
            and bool(row['differences']) for row in (feedback if type(feedback) is list else ())
        ) or any(isinstance(row, Mapping) and row.get('status') == 'mismatch'
                 for row in (preconditions if type(preconditions) is list else ()))
        return {'version': 'asterion.prime-context-interaction/v1',
                'effect': 'unknown' if unknown else 'settled',
                'feedback': 'negative' if negative else 'ordinary'}

    @staticmethod
    def _tool_state_view(method, projected):
        """Mark only settled action-board copies; retain every research result.

        The extension admits this closed proposal after binding its hash to the
        actual model-visible text. This view never changes the archived result.
        """
        if (method != 'execute_plan' or projected.get('status') != 'recorded'
                or projected.get('environment_result_unknown') is True
                or projected.get('processing_blocked') is True
                or 'uncertain_step' in projected
                or projected.get('stop_reason') in {'unknown', 'environment-result-unknown', 'processing-failed'}):
            return None
        observation = projected.get('observation')
        reference = projected.get('observation_ref')
        if (type(observation) is not dict or 'frame' not in observation
                or type(reference) is not dict
                or type(reference.get('run_id')) is not str
                or type(reference.get('attempt_id')) is not str
                or type(reference.get('sequence')) is not int):
            return None
        replacement = {key: value for key, value in projected.items()
                       if key not in {'context_memory', 'tool_state_view', 'observation'}}
        archived = {key: value for key, value in observation.items()
                    if key not in {'frame', 'frame_delivery', 'animation_ref'}}
        archived['frame_read'] = {'sequence': reference['sequence'],
                                  'read_api': 'p7_research.frame(sequence)'}
        if observation.get('animation_ref') is not None:
            archived['animation_read'] = {'observation_ref': reference,
                                          'read_api': 'p7_research.animation(observation_ref)'}
        replacement['observation'] = archived
        try:
            text = json.dumps(replacement, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            text_bytes = len(text.encode('utf-8'))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return None
        if text_bytes > 128 * 1024:
            return None
        return {'version': 'asterion.prime-tool-state-view/v1',
                'state_key': f"p7.board:{reference['run_id']}:{reference['attempt_id']}",
                'replacement_text': text}

    def set_memory_instructions(self, prompt: str):
        """Capture the exact immutable operator guidance before initial state."""
        if (type(prompt) is not str or not prompt.strip()
                or len(prompt.encode('utf-8')) > 128 * 1024
                or (self._memory_instructions is not None and self._memory_instructions != prompt)):
            raise ValueError('research memory instructions unavailable')
        self._memory_instructions = prompt

    def _context_memory(self, *, commit, context=None):
        if self._memory_instructions is None:
            return None
        try:
            context = self.actor_context() if context is None else project_actor_context(context)
            autonomous = context.get('learner_profile') == 'autonomous'
            if autonomous:
                # Complete workspace/model/history stay readable on demand.
                # The working baseline carries current facts, not legacy model
                # structures or an execution-log substitute for the notes.
                fields = {'workspace_revision', 'notes', 'notes_current', 'notes_boundary',
                          'learner_profile', 'observation', 'observation_ref', 'budget',
                          'lifecycle', 'environment_result_unknown', 'processing_blocked',
                          'checkpoint'}
                context = {key: value for key, value in context.items() if key in fields}
            notes = context.get('notes')
            if commit and notes is None:
                return None
            content = self._memory_instructions + '\n\n' + json.dumps(
                context, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            if len(content.encode('utf-8')) > 128 * 1024:
                return None
            return {'version': ('asterion.prime-context-memory/v3' if autonomous
                                else 'asterion.prime-context-memory/v2'),
                    'revision': None if notes is None else notes['revision'], 'content': content, 'commit': commit}
        except (ValueError, TypeError, KeyError, OSError):
            # A failed view refresh cannot change the committed note or hide an
            # environment action result; absence leaves the model view uncut.
            return None

    def current_context(self):
        return self.solver.current_context()

    def research_chain_summary(self):
        """Numeric coverage only; private research content stays under the run root."""
        faults = getattr(self, '_research_chain_faults', 0)
        chain = getattr(self, '_research_chain', None)
        if chain is not None:
            try:
                value = chain.summary()
                return {**value, 'unavailable_record_count': value['unavailable_record_count'] + faults}
            except Exception:
                faults = max(1, faults)
        return {'record_count': 0, 'omitted_record_count': 0,
                'omitted_reference_count': 0, 'unavailable_record_count': max(1, faults)}

    def _observe_research(self, method, *args):
        chain = getattr(self, '_research_chain', None)
        if chain is None:
            return
        try:
            getattr(chain, method)(*args)
        except Exception:
            self._research_chain_faults = getattr(self, '_research_chain_faults', 0) + 1

    def _research_journal_position(self):
        if getattr(self, '_research_chain', None) is None:
            return None
        try:
            return len(self._broker.journal)
        except Exception:
            self._research_chain_faults = getattr(self, '_research_chain_faults', 0) + 1
            return None

    def _observe_experiment(self, plan, result, journal_start):
        if getattr(self, '_research_chain', None) is None:
            return
        try:
            transitions = self._broker.journal[journal_start:] if journal_start is not None else ()
            self._observe_research('experiment', plan, result, transitions)
        except Exception:
            self._research_chain_faults = getattr(self, '_research_chain_faults', 0) + 1

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
            + AUTONOMOUS_RESEARCH_GUIDANCE + " " + RESOURCE_AWARE_RESEARCH_GUIDANCE
            + " " + ACTOR_FRAME_INSTRUCTION + "\n"
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
                if self._owns_workspace_owner:
                    await self._workspace_owner.close()
                else:
                    await self.kernel.close()
            finally:
                await asyncio.to_thread(self._read_server.close)
