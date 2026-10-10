"""Provider-free coordinator contract over real P1 resource owners."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, cast
import unittest
from unittest.mock import patch

from asterion.agents.prime.compaction_budget import (
    ModelPrice,
    quote_compaction_reservation,
)
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
from asterion.applications.prime.p1.runtime_binding import P1WorkerOwnerAdapter
from asterion.applications.prime.p1.worker import P1CellRequest
from asterion.runtimes.pi_extensions import PiExtensionBinding
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, PiRpcResult, PiRpcSession
from tests.test_asterion_prime_backend import FakeReusablePi
from tests.test_asterion_prime_context import LAUNCH
from tests.test_asterion_prime_p1_worker import (
    setup_cell,
    verification_cell,
    stage_two_cell,
)


class CodingPi(FakeReusablePi):
    """Only the provider/model edge is scripted; all coding runs in the worker."""

    async def prompt(self, prompt, *, signal, on_event):
        self.calls += 1
        worker = cast(Any, self).worker
        resources = cast(Any, self).resources
        code = (setup_cell(), verification_cell(), stage_two_cell())[self.calls - 1]
        call_id = f"cell-{self.calls}"
        events = []

        def emit(kind, payload):
            self.sequence += 1
            event = PiRpcEvent(self.sequence, kind, payload)
            events.append(event)
            on_event(event)

        emit("turn_start", {})
        emit(
            "tool_execution_start",
            {"toolCallId": call_id, "toolName": "ipython", "args": {"code": code}},
        )
        result = await worker.execute_cell(
            P1CellRequest(call_id, resources.active_turn_id, code)
        )
        emit(
            "tool_execution_end",
            {
                "toolCallId": call_id,
                "toolName": "ipython",
                "isError": result.status != "ok",
                "result": {"content": [{"type": "text", "text": result.output}]},
            },
        )
        emit(
            "message_end",
            {"message": {"role": "assistant", "usage": {"input": 3, "output": 2}}},
        )
        emit("agent_end", {})
        return PiRpcResult("SENTINEL_PRIVATE_MODEL_ANSWER", tuple(events), b"")

    async def compact(self, *, signal, on_event, custom_instructions=None):
        cast(Any, self).trace.append("compact.provider-call")
        cast(Any, self).compact_instructions = custom_instructions
        return await super().compact(
            signal=signal,
            on_event=on_event,
            custom_instructions=custom_instructions,
        )

    async def close(self):
        await super().close()
        cast(Any, self).trace.append("pi.close")


class TestP1Operator(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, *, aggregate_tokens: int = 64_000):
        from asterion.applications.prime.p1.operator import (
            P1OperatorResources, _COMPACTION_INSTRUCTIONS, _P1Services,
        )
        from asterion.agents.prime.application import (
            PrimeApplicationSpec, PrimeOperatorContext, PrimeBackendSpec,
            PrimeToolModuleArtifact, prepare_prime_application,
        )
        from asterion.agents.prime.deadline import TaskDeadline
        from asterion.agents.prime.tool_registry import CORE_TOOL_REGISTRY
        temporary = tempfile.TemporaryDirectory(prefix="asterion-p1-operator-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        extension = root / "extension.mjs"
        extension.write_text("export default function extension() {}\n")
        trace = []
        deadline = time.monotonic() + 20
        worker = P1WorkerProcess(deadline=time.monotonic() + 30)
        await worker.start()
        self.addAsyncCleanup(worker.close)
        owner = P1WorkerOwnerAdapter(worker)
        private = root / "private"
        private.mkdir(mode=0o700)
        limits = AsterionPrimeLimits(8, 4, 600_000)
        spec = PrimeBackendSpec("session-1", 1, private, "continuation-1", limits,
            aggregate_tokens, 500000, ModelPrice(1000000, 1000000), "authority-1",
            _COMPACTION_INSTRUCTIONS, compat_provider_id="prime-applications")
        application = prepare_prime_application(
            PrimeApplicationSpec("prime.ipython-coding", "1.0.0", "persistent-code-tools",
                tools=PrimeToolModuleArtifact(extension, CORE_TOOL_REGISTRY)),
            PrimeOperatorContext(Path('/usr/bin/true'), None, root, 'deepseek', 'deepseek-flash',
                'off', {}, TaskDeadline(deadline_monotonic=deadline, deadline_epoch=time.time()+20)),
            authorization=spec)
        self.addAsyncCleanup(application.close)
        services = _P1Services(worker, owner)
        def build(**kwargs):
            kwargs.pop('diagnostics', None)
            kwargs.pop('private_failure_sink', None)
            rpc = CodingPi(PiRpcConfig(**kwargs))
            rpc.stop = lambda: trace.append('pi.stop')
            rpc.worker, rpc.trace = worker, trace
            peer = socket.socket(fileno=os.dup(int(kwargs['environment']['ASTERION_PRIME_IPYTHON_CONTEXT_FD'])))
            peer.setblocking(False)
            rpc.peer = peer
            self.addCleanup(peer.close)
            rpc.tool_peer = socket.socket(fileno=os.dup(int(kwargs['environment']['ASTERION_PRIME_IPYTHON_FD'])))
            rpc.tool_peer.setblocking(False)
            self.addCleanup(rpc.tool_peer.close)
            return rpc
        original_witness = PrimeContextWitnessSession
        def witness(*args, **kwargs):
            kwargs['timeout_seconds'] = .2
            return original_witness(*args, **kwargs)
        with (patch('asterion.runtime.native_rpc.build_rpc_session', side_effect=build),
              patch('asterion.agents.prime.context.PrimeContextWitnessSession', side_effect=witness),
              patch('secrets.token_hex', return_value=LAUNCH)):
            attachment = await application.open_backend(spec=spec, services=services)
        rpc = application._persistent.rpc
        resources = P1OperatorResources(
            application=application, backend=attachment, worker=worker, worker_owner=owner,
            private_root=private, journal_root=root / "journal", run_id="p1-test",
            deadline=deadline, observe=trace.append)
        services.resources = resources
        rpc.resources = resources
        return resources, rpc, trace

    async def test_real_closed_loop_and_cleanup_precede_runner_terminal(self):
        for target in ('asterion.applications.discovery.list_application_providers',
                       'asterion.applications.discovery.load_application_provider',
                       'asterion.applications.prime.inventory.prime_release_application'):
            self.enterContext(patch(target, side_effect=AssertionError('central lookup')))
        resources, rpc, trace = await self.fixture()
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        events = []
        original_run = resources.runtime.run

        async def observe_runtime(_self, *args, **kwargs):
            async for event in original_run(*args, **kwargs):
                assert resources._cleanup is not None
                self.assertTrue(resources._cleanup.complete)
                events.append(event)
                yield event

        with patch.object(type(resources.runtime), "run", observe_runtime):
            result = await asyncio.wait_for(run_fixed_small_verification(resources), 10)
        self.assertEqual(result.status, "completed", trace)
        self.assertEqual(
            trace,
            [
                "backend.open",
                "host1.open",
                "runner.start",
                "stage1.setup.start",
                "stage1.setup.complete",
                "stage1.verify.start",
                "stage1.verify.complete",
                "stage1.oracle.start",
                "stage1.oracle.complete",
                "stage1.complete",
                "compact.admit",
                "compact.provider-call",
                "compact.persist",
                "host1.close",
                "journal.reopen",
                "host2.recover",
                "authority.sync",
                "resume.admit",
                "resume.persist",
                "stage2.release",
                "stage2.complete",
                "oracle.pass",
                "host2.close",
                "worker.close",
                "pi.stop",
                "pi.close",
                "backend.close",
                "runner.terminal",
            ],
        )
        self.assertEqual((rpc.calls, rpc.compacts, rpc.closes), (3, 1, 1))
        # The application's own instruction reached the RPC, and it is the
        # kernel note rather than a restatement of it anywhere in the operator.
        from asterion.agents.prime.summarization import SUMMARY_KERNEL_NOTE

        self.assertEqual(rpc.compact_instructions, SUMMARY_KERNEL_NOTE)
        self.assertFalse(resources.private_root.exists())
        assert resources.worker.cleanup_receipt is not None
        self.assertEqual(resources.worker.cleanup_receipt.reap_count, 1)
        assert resources.host is not None
        self.assertEqual(
            resources.host.snapshot().authority_usage.aggregate_tokens, 16_015
        )
        self.assertNotIn("SENTINEL_PRIVATE", repr(result))
        self.assertEqual(
            [event.type for event in events],
            [
                "run.started",
                "usage.reported",
                "usage.reported",
                "artifact.created",
                "run.completed",
            ],
        )
        self.assertEqual(events[-1].payload, {"status": "completed"})
        self.assertEqual([event.sequence for event in events], [1, 2, 3, 4, 5])

    async def test_rejected_and_authenticated_no_mutation_preserve_checkpoint(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification
        from asterion.control.session_context import SessionContextCommand

        for kind in ("pre-dispatch", "authenticated-no-mutation"):
            with self.subTest(kind=kind):
                resources, rpc, trace = await self.fixture()
                if kind == "pre-dispatch":
                    resources.authority = replace(
                        resources.authority,
                        allowed_operations=(
                            "session.continuation.resume",
                            "session.describe",
                        ),
                    )
                else:
                    original_open = resources.open

                    async def open_with_small_reservation():
                        await original_open()
                        assert resources.host is not None
                        manager = resources.host.session_context_manager
                        assert manager is not None
                        execute = manager.execute

                        async def small(command):
                            changed = command.to_mapping()
                            if command.operation == "session.compact":
                                changed["payload"]["budget"]["aggregate_tokens"] = 1
                                changed["payload"]["budget"]["controller_tokens"] = 1
                            return await execute(
                                SessionContextCommand.from_mapping(changed)
                            )

                        manager.execute = small

                    resources.open = open_with_small_reservation
                original_compact = resources.compact
                observed = []

                async def compact():
                    checkpoint = resources.application._backend_checkpoint()
                    assert checkpoint is not None
                    before = checkpoint
                    try:
                        return await original_compact()
                    finally:
                        checkpoint = resources.application._backend_checkpoint()
                        assert checkpoint is not None
                        after = checkpoint
                        observed.append(
                            (
                                before,
                                after,
                                resources.backend.snapshot().outstanding_effect,
                            )
                        )

                resources.compact = compact
                result = await run_fixed_small_verification(resources)
                self.assertEqual(result.status, "recovery-required")
                self.assertEqual(rpc.compacts, 0 if kind == "pre-dispatch" else 1)
                self.assertEqual(observed[0][0], observed[0][1])
                self.assertIsNone(observed[0][2])
                self.assertNotIn("stage2.release", trace)

    async def test_absolute_deadline_stops_before_compact(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()

        def observe(event):
            trace.append(event)
            if event == "stage1.complete":
                resources.coordination.deadline = time.monotonic() - 1

        resources.observe = observe
        result = await run_fixed_small_verification(resources)
        self.assertEqual(result.status, "budget-limited", trace)
        self.assertEqual(rpc.compacts, 0)

    async def test_real_backend_token_exhaustion_prevents_second_prompt(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture(aggregate_tokens=5)
        events = []
        original_run = resources.runtime.run

        async def observe_runtime(_self, *args, **kwargs):
            async for event in original_run(*args, **kwargs):
                events.append(event)
                yield event

        with patch.object(type(resources.runtime), "run", observe_runtime):
            result = await run_fixed_small_verification(resources)
        self.assertEqual(result.status, "budget-limited", trace)
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.compacts, 0)
        self.assertIsNone(resources.backend.snapshot().outstanding_effect)
        self.assertEqual(events[-1].payload["code"], "p1_budget_limited")

    async def test_private_bridge_accepts_only_an_active_turn(self):
        resources, rpc, trace = await self.fixture()
        child = rpc.tool_peer
        bridge = resources.application._persistent.bridge
        resources.active_turn_id = "setup-turn"
        request = {
            "protocol": "asterion.prime-ipython/v1",
            "request_id": "bridge-cell",
            "type": "execute",
            "code": setup_cell(),
        }
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(child, json.dumps(request).encode() + b"\n")
        response = json.loads(await asyncio.wait_for(loop.sock_recv(child, 4096), 2))
        self.assertEqual(response["status"], "ok")
        self.assertEqual(resources.worker.snapshot().cells[0].turn_id, "setup-turn")
        await resources.application.close()
        self.assertFalse(bridge._thread.is_alive())

    async def test_cancellation_at_each_coordination_barrier(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        barriers = (
            "runner.start",
            "stage1.complete",
            "compact.admit",
            "compact.persist",
            "host1.close",
            "journal.reopen",
            "host2.recover",
            "authority.sync",
            "resume.admit",
            "resume.persist",
            "stage2.release",
            "stage2.complete",
            "oracle.pass",
        )
        for barrier in barriers:
            with self.subTest(barrier=barrier):
                resources, rpc, trace = await self.fixture()

                def observe(event):
                    trace.append(event)
                    if event == barrier:
                        resources.coordination.request_stop("cancelled")

                resources.observe = observe
                result = await asyncio.wait_for(
                    run_fixed_small_verification(resources), 5
                )
                self.assertEqual(result.status, "cancelled", trace)
                self.assertIsNone(result.receipt_sha256)
                self.assertEqual(rpc.closes, 1)
                assert resources.worker.cleanup_receipt is not None
                self.assertEqual(resources.worker.cleanup_receipt.reap_count, 1)
                self.assertLess(
                    trace.index("backend.close"), trace.index("runner.terminal")
                )

    async def test_stage_two_is_not_released_on_reconstruction_or_compact_uncertainty(
        self,
    ):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        for fault in ("reconstruction", "malformed", "post-mutation"):
            with self.subTest(fault=fault):
                resources, rpc, trace = await self.fixture()
                if fault == "reconstruction":

                    async def reconstruct():
                        await resources.close_host()
                        raise OSError("SENTINEL_PRIVATE_RECOVERY_PATH")

                    resources.reconstruct = reconstruct
                elif fault == "malformed":
                    rpc.corrupt_compact = True
                else:
                    rpc.compact_native_overrides = {
                        "summary": "SENTINEL_PRIVATE_MUTATED_SUMMARY"
                    }
                result = await asyncio.wait_for(
                    run_fixed_small_verification(resources), 5
                )
                self.assertEqual(result.status, "recovery-required", trace)
                self.assertEqual(rpc.compacts, 1)
                self.assertNotIn("stage2.release", trace)
                if fault != "reconstruction":
                    self.assertEqual(resources.backend.snapshot().phase, "recovery-required")
                self.assertNotIn("SENTINEL_PRIVATE", repr(result))

    async def test_stage_two_failure_and_budget_stop_cleanup_once(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification
        from asterion.capabilities.prime_ipython_coding_native.host import (
            P1RuntimeHostError,
        )

        for classification in ("recovery-required", "budget-limited"):
            with self.subTest(classification=classification):
                resources, rpc, trace = await self.fixture()

                async def fail(**kwargs):
                    raise P1RuntimeHostError(cast(Any, classification))

                resources.execute_stage_two = fail
                result = await asyncio.wait_for(
                    run_fixed_small_verification(resources), 5
                )
                self.assertEqual(result.status, classification, trace)
                self.assertEqual(rpc.calls, 2)
                self.assertEqual(rpc.closes, 1)
                self.assertLess(
                    trace.index("backend.close"), trace.index("runner.terminal")
                )

    async def test_cleanup_failure_still_closes_pi_and_forbids_terminal(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()
        original = resources.worker.close

        async def fail_close():
            await original()
            raise OSError("SENTINEL_PRIVATE_CLEANUP")

        with patch.object(resources.worker, "close", fail_close):
            result = await asyncio.wait_for(run_fixed_small_verification(resources), 5)
        self.assertEqual(result.status, "protocol-failure")
        self.assertEqual(rpc.closes, 1)
        self.assertNotIn("runner.terminal", trace)
        self.assertIsNone(result.receipt_sha256)

    async def test_private_root_cleanup_failure_forbids_finalization(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()

        def fail_root():
            raise OSError("SENTINEL_PRIVATE_ROOT")

        resources._cleanup_root = fail_root
        result = await run_fixed_small_verification(resources)
        self.assertEqual(result.status, "protocol-failure")
        assert resources._cleanup is not None
        self.assertFalse(resources._cleanup.complete)
        self.assertNotIn("runner.terminal", trace)

    async def test_pi_close_failure_still_uses_independent_process_owner(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()

        async def fail_close():
            raise RuntimeError("SENTINEL_PRIVATE_CLOSE")

        cast(Any, rpc).close = fail_close
        result = await run_fixed_small_verification(resources)
        self.assertEqual(result.status, "protocol-failure")
        self.assertEqual(trace.count('pi.stop'), 1)
        self.assertFalse(resources.private_root.exists())
        self.assertNotIn("runner.terminal", trace)

    async def test_unresponsive_cleanup_and_runner_never_make_unbounded_awaits(self):
        from asterion.applications.prime.p1 import operator

        for owner in ("cleanup", "runner", "effect", "host-reconstruction"):
            with self.subTest(owner=owner):
                resources, rpc, trace = await self.fixture()
                entered = asyncio.Event()
                released = asyncio.Event()

                async def hang(*args, **kwargs):
                    entered.set()
                    while not released.is_set():
                        try:
                            await released.wait()
                        except asyncio.CancelledError:
                            pass
                    raise RuntimeError("SENTINEL_PRIVATE_HANG")

                original_cleanup = resources.close_in_owner_order
                if owner == "cleanup":
                    resources.close_in_owner_order = hang
                if owner == "effect":
                    cast(Any, rpc).prompt = hang
                original_close_host = resources.close_host
                if owner == "host-reconstruction":
                    resources.close_host = hang
                resources.coordination.deadline = (
                    time.monotonic() + 0.05
                    if owner != "cleanup"
                    else resources.coordination.deadline
                )
                with (
                    patch.object(operator, "_CLEANUP_SECONDS", 0.1),
                    patch.object(
                        operator,
                        "run_composed_application",
                        hang
                        if owner == "runner"
                        else operator.run_composed_application,
                    ),
                ):
                    task = asyncio.create_task(
                        operator.run_fixed_small_verification(resources)
                    )
                    try:
                        await entered.wait()
                        done, _ = await asyncio.wait((task,), timeout=1.5)
                        self.assertIn(
                            task, done, "operator exceeded bounded forced-stop deadline"
                        )
                        self.assertEqual(task.result().status, "protocol-failure")
                    finally:
                        released.set()
                        await asyncio.wait_for(task, 2)
                        resources.close_host = original_close_host
                        await original_cleanup()

    async def test_runner_early_exception_is_bounded_and_cleanup_precedes_cancel(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()

        async def fail(*args, **kwargs):
            raise RuntimeError("SENTINEL_PRIVATE_RUNNER")

        with patch(
            "asterion.applications.prime.p1.operator.run_composed_application", fail
        ):
            result = await asyncio.wait_for(run_fixed_small_verification(resources), 2)
        self.assertEqual(result.status, "protocol-failure")
        self.assertEqual(rpc.calls, 0)
        self.assertEqual(rpc.closes, 1)
        self.assertNotIn("runner.terminal", trace)

    async def test_active_effect_is_settled_before_host_close(self):
        from asterion.applications.prime.p1.operator import run_fixed_small_verification

        resources, rpc, trace = await self.fixture()
        entered = asyncio.Event()
        settled = asyncio.Event()

        async def prompt(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                settled.set()

        cast(Any, rpc).prompt = prompt
        original_close = resources.close_host

        async def close():
            self.assertTrue(settled.is_set())
            await original_close()

        resources.close_host = close
        task = asyncio.create_task(run_fixed_small_verification(resources))
        await entered.wait()
        task.cancel("SENTINEL_PRIVATE_CANCEL")
        result = await asyncio.wait_for(task, 3)
        self.assertEqual(result.status, "cancelled", trace)
        self.assertEqual(rpc.closes, 1)

    async def test_forced_pi_close_bypasses_an_active_command_lock(self):

        with tempfile.TemporaryDirectory() as temporary:
            rpc = PiRpcSession(
                PiRpcConfig(
                    command=(sys.executable, "-I", "-c", "import time; time.sleep(30)"),
                    cwd=Path(temporary),
                    environment={},
                    deadline_seconds=1,
                )
            )
            rpc.start()
            process = rpc.process
            try:
                async with rpc._command_lock:
                    from asterion.agents.prime import _launch
                    close = _launch.force_close_rpc
                    self.assertIsNotNone(
                        close, "forced close must bypass the command lock"
                    )
                    assert close is not None
                    await asyncio.wait_for(close(rpc), 0.5)
                assert process is not None
                self.assertIsNotNone(process.poll())
                self.assertIsNone(rpc.process)
            finally:
                rpc.stop()

    def test_launcher_has_no_tuning_arguments_and_rejects_source_import(self):
        from asterion.applications.prime.p1 import operator

        self.assertTrue(
            callable(getattr(operator, "main", None)), "installed launcher is missing"
        )

        for args in (["--model", "secret"], ["--cost", "1"], []):
            with self.subTest(args=args), patch("builtins.print") as printed:
                self.assertEqual(operator.main(args), 2)
                self.assertEqual(
                    printed.call_args.args, ('{"status":"preflight-rejected"}',)
                )

    def test_public_progress_exposes_only_closed_stage_labels(self):
        from asterion.applications.prime.p1 import operator

        self.assertTrue(
            callable(getattr(operator, "_public_progress", None)),
            "public-safe P1 progress reporter is missing",
        )
        output = io.StringIO()
        with patch.object(operator.sys, "stderr", output):
            operator._public_progress("runner.start")
            with self.assertRaises(operator.P1OperatorError):
                operator._public_progress("SENTINEL_PRIVATE_STAGE")

        self.assertEqual(output.getvalue(), '{"stage":"runner.start"}\n')
        self.assertNotIn("SENTINEL_PRIVATE", output.getvalue())

    def test_stubborn_host_owners_are_bounded_and_real_worker_is_reaped(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
import asyncio, json, sys, time
from pathlib import Path
from asterion.applications.prime.p1 import operator
from tests.test_asterion_prime_p1_operator import TestP1Operator
operator._CLEANUP_SECONDS = .5
completed = []
async def invoke():
    case = TestP1Operator()
    owned, rpc, trace = await case.fixture()
    Path(sys.argv[2]).write_text(str(owned.worker.identity.pid))
    original = owned.close_host
    async def stubborn(*args, **kwargs):
        while True:
            try: await asyncio.Event().wait()
            except asyncio.CancelledError: pass
    if sys.argv[1] == 'backend':
        owned.application._backend.close = stubborn
    if sys.argv[1] == 'effect':
        rpc.prompt = stubborn
        owned.coordination.deadline = time.monotonic() + .15
    def observe(label):
        trace.append(label)
        if sys.argv[1] == 'reconstruction' and label == 'compact.persist':
            owned.coordination.deadline = time.monotonic() + .05
    owned.observe = observe
    async def close():
        if (sys.argv[1] == 'reconstruction' and owned._host_number == 1) or owned._host_number == 2:
            while True:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: pass
        await original()
    owned.close_host = close
    result = await operator.run_fixed_small_verification(owned)
    assert result.status == 'protocol-failure'
    assert owned.worker._started_process.poll() is not None, 'worker still live'
    assert trace.count('pi.stop') == 1, 'Pi owner not reaped'
    assert owned.application._persistent.lease.closed, 'lease not closed'
    assert not owned.private_root.exists(), 'private root not removed'
    assert not owned._cleanup.complete, 'unclean host was claimed complete'
    assert 'runner.terminal' not in trace
    if sys.argv[1] == 'reconstruction':
        assert 'host2.recover' not in trace
        assert 'stage2.release' not in trace
    completed.append(True)
    return result
result = operator._run_operator(invoke)
assert completed == [True], 'owner assertions did not complete'
print(json.dumps({'status': result.status}))
raise SystemExit(1)
"""
        for boundary in ("reconstruction", "final", "backend", "effect"):
            with (
                self.subTest(boundary=boundary),
                tempfile.TemporaryDirectory() as temporary,
            ):
                pid_file = Path(temporary) / "worker-pid"
                try:
                    result = subprocess.run(
                        (sys.executable, "-c", program, boundary, str(pid_file)),
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(
                        json.loads(result.stdout), {"status": "protocol-failure"}
                    )
                except subprocess.TimeoutExpired:
                    self.fail("host owner prevented bounded process exit")
                finally:
                    if pid_file.exists():
                        import signal

                        try:
                            os.killpg(int(pid_file.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

class TestP1LaunchPreflight(unittest.TestCase):
    """The rebuilt native launch path fails closed on every operator input.

    The resource tests above construct the owners directly, so they cannot see
    this edge. These assertions cover the operator-owned boundary only: which
    values the preset must supply, and that a rejected preflight reports the
    fixed public status without starting a process.
    """

    def test_preflight_selects_core_artifact_and_ipython_allowlist(self) -> None:
        import asterion
        from asterion.applications.prime.p1 import operator

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            installed = base / "site-packages" / "asterion" / "__init__.py"
            installed.parent.mkdir(parents=True)
            installed.write_text("")
            root = base / "operator"
            root.mkdir()
            with (
                patch.object(asterion, "__file__", str(installed)),
                patch.object(operator.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")),
                patch.object(operator.live, "load_operator_environment", return_value={"DEEPSEEK_API_KEY": "sentinel-key"}) as load,
                patch.object(operator.live, "resolve_node", return_value=Path("/usr/bin/node")),
                patch.object(operator.live, "resolve_pi_entry", return_value=base / "pi.mjs"),
            ):
                preflight = operator._preflight({operator.live.OPERATOR_ROOT_ENV: str(root)})
                load.return_value = {}
                with self.assertRaises(operator.P1OperatorError):
                    operator._preflight({operator.live.OPERATOR_ROOT_ENV: str(root)})
            self.assertEqual(preflight.extension_path.name, "ipython-extension.mjs")
            self.assertEqual(preflight.executable, Path("/usr/bin/node"))
            self.assertEqual(preflight.entry, base / "pi.mjs")

    def test_resource_binding_injects_core_registry_before_any_model(self) -> None:
        from asterion.applications.prime.p1 import operator

        captured = []
        def reject(binding):
            captured.append(binding)
            raise ValueError("stop before worker effects")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "ipython-extension.mjs"
            extension.write_text("export default function register() {}")
            preflight = operator._Preflight(root, {}, Path(sys.executable), Path("/usr/bin/true"), None, "off", extension)
            with patch.object(PiExtensionBinding, "preflight", reject), self.assertRaises(operator.P1OperatorError):
                asyncio.run(operator._build_resources(preflight))
        self.assertEqual(len(captured), 1)
        self.assertEqual(json.loads(captured[0].environment.get("ASTERION_PRIME_IPYTHON_TOOL_REGISTRY", "null")), {
            "module_id": "prime.ipython", "capability_id": "prime.tool.ipython", "tool_names": ["ipython"],
        })

    def test_fixed_preset_values_agree_with_the_runtime_factory(self) -> None:
        from asterion.applications.prime.p1 import operator
        from asterion.applications.prime.p1.runtime_binding import P1_RUNTIME_OPTIONS
        self.assertEqual((operator._PROVIDER, operator._MODEL), ('deepseek', 'deepseek-flash'))
        self.assertEqual(operator._PRICE, ModelPrice(300000, 1200000))

        # The launch path builds the exact budget and limits the runtime factory
        # re-validates, so a drift between the two would reject every run at the
        # factory before it could start.
        self.assertEqual(
            P1_RUNTIME_OPTIONS["aggregate_tokens"], str(operator._AGGREGATE_TOKENS)
        )
        self.assertEqual(P1_RUNTIME_OPTIONS["cost_micros"], str(operator._COST_MICROS))
        self.assertEqual(
            P1_RUNTIME_OPTIONS["deadline_ms"],
            str(int(operator._DEADLINE_SECONDS * 1000)),
        )
        self.assertEqual(
            P1_RUNTIME_OPTIONS["max_callbacks"], str(operator._LIMITS.model_callbacks)
        )
        self.assertEqual(
            P1_RUNTIME_OPTIONS["max_tool_callbacks"],
            str(operator._LIMITS.tool_callbacks),
        )

    def test_fixed_price_reservation_stays_inside_the_public_cap(self) -> None:
        from asterion.applications.prime.p1 import operator

        self.assertIs(type(operator._PRICE), ModelPrice)
        quote = quote_compaction_reservation(
            branch_input_caps=operator._COMPACTION_INPUT_CAPS,
            branch_output_caps=operator._COMPACTION_OUTPUT_CAPS,
            price=operator._PRICE,
        )
        self.assertLessEqual(quote.reserved_tokens, 16_000)
        self.assertLessEqual(quote.cost_micro_units, 125_000)

    def test_asymmetric_branch_caps_fit_the_reservation(self) -> None:
        from asterion.applications.prime.p1 import operator

        # The live witness sends one large main request and one small turn-prefix
        # request. A symmetric per-branch cap refused the real shape even though
        # it reserves fewer tokens than the operator already reserved up front.
        quote = quote_compaction_reservation(
            branch_input_caps=(7_114, 1_041),
            branch_output_caps=operator._COMPACTION_OUTPUT_CAPS,
            price=operator._PRICE,
        )
        self.assertLessEqual(quote.reserved_tokens, 16_000)

    def test_a_single_branch_cannot_take_more_than_the_total_leaves(self) -> None:
        from asterion.applications.prime.p1 import operator

        for caps in ((16_000, 0), (9_449, 0)):
            with self.subTest(caps=caps):
                with self.assertRaises(ValueError):
                    quote_compaction_reservation(
                        branch_input_caps=caps,
                        branch_output_caps=operator._COMPACTION_OUTPUT_CAPS,
                        price=operator._PRICE,
                    )

    def test_the_total_reservation_remains_the_binding_limit(self) -> None:
        from asterion.applications.prime.p1 import operator

        # Each branch is within the per-branch cap, but together they exceed the
        # reservation: the total must still refuse.
        with self.assertRaises(ValueError):
            quote_compaction_reservation(
                branch_input_caps=(9_448, 9_448),
                branch_output_caps=operator._COMPACTION_OUTPUT_CAPS,
                price=operator._PRICE,
            )

    def test_source_tree_operator_root_is_refused_before_any_process(self) -> None:
        from asterion.applications.prime.p1 import operator

        repository = Path(__file__).resolve().parents[1]
        # An absent operator root and a source-tree operator root must both
        # fail closed: the second is the case where the running distribution is
        # installed inside the root and a source tree could execute in its place.
        for environment in ({}, {operator.live.OPERATOR_ROOT_ENV: str(repository)}):
            with self.subTest(keys=sorted(environment)):
                with self.assertRaises(operator.P1OperatorError):
                    operator._preflight(environment)

    def test_failed_interpreter_probe_is_reported_as_the_module_error(self) -> None:
        import asterion

        from asterion.applications.prime.p1 import operator

        # A probe that cannot run, or times out, must fail closed as the module's
        # own error rather than leaking the subprocess exception type.
        #
        # The source-execution guard rejects any operator root that does not hold
        # an installed distribution, so the running package must be made to look
        # installed under ``site-packages`` outside the root. Without that, the
        # guard rejects first, the patched probe is never called, and the
        # assertion below would pass for an unrelated reason. The call-count
        # assertion is what keeps this test from silently degrading that way.
        with tempfile.TemporaryDirectory(prefix="asterion-p1-preflight-") as temporary:
            base = Path(temporary)
            installed = base / "install" / "site-packages" / "asterion" / "__init__.py"
            installed.parent.mkdir(parents=True)
            installed.write_text("", encoding="utf-8")
            operator_root = base / "operator"
            operator_root.mkdir()
            environment = {operator.live.OPERATOR_ROOT_ENV: str(operator_root)}
            for error in (
                subprocess.CalledProcessError(1, "probe"),
                subprocess.TimeoutExpired("probe", 10),
            ):
                with self.subTest(error=type(error).__name__):
                    with (
                        patch.object(asterion, "__file__", str(installed)),
                        patch.object(
                            operator.subprocess, "run", side_effect=error
                        ) as probe,
                        self.assertRaises(operator.P1OperatorError),
                    ):
                        operator._preflight(environment)
                    probe.assert_called_once()

    def test_rejected_preflight_reports_the_fixed_public_status(self) -> None:
        from asterion.applications.prime.p1 import operator

        repository = Path(__file__).resolve().parents[1]
        stream = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {operator.live.OPERATOR_ROOT_ENV: str(repository)},
                clear=False,
            ),
            patch("sys.stdout", stream),
        ):
            self.assertEqual(operator.main([]), 2)
        self.assertEqual(json.loads(stream.getvalue()), {"status": "preflight-rejected"})


if __name__ == "__main__":
    unittest.main()
