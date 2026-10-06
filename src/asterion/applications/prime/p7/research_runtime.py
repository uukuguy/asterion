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
from .experience import CellArchive
from .research_bridge import ResearchReadServer
from .score import digest
from .solver import Solver
from .solver_control import SolverControl


class _EvidenceBroker:
    """Retain the existing broker's dispatch and trace receipt boundary."""

    def __init__(self, broker, trace_client):
        self._broker, self._trace_client = broker, trace_client

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

    def act_checked(self, plan):
        start = len(self._broker.journal)
        try:
            result = self._broker.act_checked(plan)
        finally:
            self._trace_client._record_transitions(self._broker.journal[start:])
        self._trace_client._count("checked_plans")
        self._trace_client._count("matched_expectations", result["applied_count"])
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
                 deadline_seconds: float, event_sink, worker=None,
                 limits: KernelLimits | None = None, experience=None):
        self._closed = False
        self.cell_count = 0
        self._lost = False  # The application can rebuild a computation kernel.
        self._lock = threading.RLock()
        self._broker = _EvidenceBroker(broker, trace_client)
        self._sink = event_sink
        self._last_control = None
        self._experience = experience
        self._cell_archive = CellArchive(run_root)
        self.control = SolverControl(run_root, run_id, time.monotonic() + deadline_seconds)
        self._read_server = ResearchReadServer(
            context=lambda: self.solver.current_context(),
            history=self._broker.history,
            frame=self._broker.frame_at,
            artifact=lambda export_id: self.solver.artifact(export_id),
            experience=(lambda source, kind, start, limit, artifact_id:
                        experience.read(source, kind, start=start, limit=limit, artifact_id=artifact_id))
                       if experience is not None else None,
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
            )
            if experience is not None:
                experience.bind(run_root, self.solver.experience_event)
            self.poll()
        except BaseException:
            self._read_server.close()
            raise

    def _new_kernel(self, worker=None):
        return PersistentIpythonHost(
            worker=worker or SubprocessPythonWorker(), bootstrap=self._bootstrap,
            limits=self._limits,
            observer=self._kernel_event,
        )

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
        return result

    def current_context(self):
        return self.solver.current_context()

    def mark_experience_loaded(self):
        """Called by the operator after adding the prior to the actor prompt."""
        if self._experience is not None:
            self._experience.mark_loaded()

    def continuation_prompt(self, round_index):
        return (
            f"Continue research round {round_index} from the retained Prime workspace. "
            "Use the current WorldMap and evidence to compute progress or a useful probe. "
            "Submit real actions only with p7_execute_plan.\n"
            + json.dumps(self.current_context(), ensure_ascii=False, separators=(",", ":"))
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
