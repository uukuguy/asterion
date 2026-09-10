"""Provider-free coordinator contract over real P1 resource owners."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import shutil
import sys
import tempfile
import time
from typing import Any, cast
import unittest
from unittest.mock import patch

from asterion.agents.prime.backend import PrimeSessionBackend
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
from asterion.applications.prime.p1.runtime_binding import P1WorkerOwnerAdapter
from asterion.applications.prime.p1.worker import P1CellRequest, digest
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

    async def compact(self, *, signal, on_event):
        cast(Any, self).trace.append("compact.provider-call")
        return await super().compact(signal=signal, on_event=on_event)

    async def close(self):
        await super().close()
        cast(Any, self).trace.append("pi.close")


class TestP1Operator(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, *, aggregate_tokens: int = 64_000):
        self.assertIsNotNone(
            importlib.util.find_spec("asterion.applications.prime.p1.operator"),
            "native P1 operator coordinator is missing",
        )
        from asterion.applications.prime.p1.operator import P1OperatorResources

        temporary = tempfile.TemporaryDirectory(prefix="asterion-p1-operator-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        extension = root / "extension.mjs"
        extension.write_text("export default function extension() {}\n")
        trace = []
        worker = P1WorkerProcess(deadline=time.monotonic() + 30)
        await worker.start()
        self.addAsyncCleanup(worker.close)
        owner = P1WorkerOwnerAdapter(worker)
        binding = PiExtensionBinding(
            "prime.ipython", extension, ("prime.tool.ipython",), (), {}
        )
        lease = binding.preflight()
        config = PiRpcConfig(
            command=("pi", "--mode", "rpc", *lease.command_args()),
            cwd=root,
            environment=dict(lease.environment),
            inherited_fds=lease.inherited_fds,
            deadline_seconds=600,
        )
        rpc = CodingPi(config)
        cast(Any, rpc).worker = worker
        cast(Any, rpc).trace = trace
        channel, peer = socket.socketpair()
        peer.setblocking(False)
        self.addCleanup(peer.close)
        cast(Any, rpc).peer = peer
        witness = PrimeContextWitnessSession(
            channel,
            launch_nonce=LAUNCH,
            timeout_seconds=0.2,
            mark_uncertain=lambda: None,
        )
        private = root / "private"
        private.mkdir(mode=0o700)
        limits = AsterionPrimeLimits(8, 4, 600_000)
        identity = PrimeBackendIdentity(
            "session-1",
            1,
            "prime-applications",
            "prime.ipython-coding",
            "1.0.0",
            "asterion.prime",
            digest(config.command),
            binding.binding_fingerprint,
            worker.identity_sha256,
            "continuation-1",
            private_root_identity(private),
            digest(
                {
                    **asdict(limits),
                    "aggregate_tokens": aggregate_tokens,
                    "cost_micros": 500_000,
                }
            ),
        )
        store = FilePrimeSessionStore(private, identity)
        backend = PrimeSessionBackend(
            identity=identity,
            store=store,
            rpc_session=cast(PiRpcSession, rpc),
            extension_binding=binding,
            extension_lease=lease,
            approved_command=config.command,
            limits=limits,
            aggregate_tokens=aggregate_tokens,
            cost_micros=500_000,
            model_price=ModelPrice(1_000_000, 1_000_000),
            witness=witness,
            tool_executor=owner,
            authority_id="authority-1",
        )
        self.addAsyncCleanup(backend.close)
        resources = P1OperatorResources(
            backend=backend,
            store=store,
            worker=worker,
            worker_owner=owner,
            extension_lease=lease,
            private_root=private,
            journal_root=root / "journal",
            run_id="p1-test",
            deadline=time.monotonic() + 20,
            observe=trace.append,
            close_pi=rpc.close,
            close_witness=witness.close,
        )
        cast(Any, rpc).resources = resources
        return resources, rpc, trace

    async def test_real_closed_loop_and_cleanup_precede_runner_terminal(self):
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
                "pi.close",
                "backend.close",
                "runner.terminal",
            ],
        )
        self.assertEqual((rpc.calls, rpc.compacts, rpc.closes), (3, 1, 1))
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
                    checkpoint = resources.store.recover_checkpoint()
                    assert checkpoint is not None
                    before = checkpoint.checkpoint
                    try:
                        return await original_compact()
                    finally:
                        checkpoint = resources.store.recover_checkpoint()
                        assert checkpoint is not None
                        after = checkpoint.checkpoint
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
        self.assertIsNone(resources.backend._outstanding)
        self.assertEqual(events[-1].payload["code"], "p1_budget_limited")

    async def test_private_bridge_accepts_only_an_active_turn(self):
        from asterion.applications.prime.p1.operator import _P1Bridge

        resources, rpc, trace = await self.fixture()
        host, child = socket.socketpair()
        child.setblocking(False)
        bridge = _P1Bridge(host, resources)
        self.addAsyncCleanup(bridge.close)
        self.addCleanup(child.close)
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
        await bridge.close()
        self.assertTrue(bridge._task.done())

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
                    self.assertEqual(resources.backend._phase, "recovery-required")
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
        self.assertEqual(rpc.closes, 1)
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

    def test_make_worker_path_is_normalized_before_fixed_path_comparison(self):
        import asterion
        from asterion.applications.prime.p1 import operator

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = parent / "checkout"
            root.mkdir()
            installed = parent / "site-packages/asterion"
            installed.mkdir(parents=True)
            package = installed / "__init__.py"
            package.write_text("")
            worker = parent / "external-prime/arc-agi-3/venv/bin/python"
            worker.parent.mkdir(parents=True)
            worker.write_text("")
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(root),
                "ASTERION_PRIME_WORKER_PYTHON": str(
                    root / "../external-prime/arc-agi-3/venv/bin/python"
                ),
            }
            with (
                patch.object(asterion, "__file__", str(package)),
                patch.object(
                    operator.subprocess,
                    "run",
                    side_effect=RuntimeError("probe reached"),
                ) as probe,
            ):
                with self.assertRaises(Exception):
                    operator._preflight(environment)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(probe.call_args.args[0][0], str(worker))

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
        from asterion.applications.prime.p1 import operator

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
                    close = getattr(operator, "_force_close_pi", None)
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

    def test_live_command_uses_a_locked_existing_main_entry(self):
        from asterion.applications.prime.p1 import operator

        self.assertTrue(
            callable(getattr(operator, "_pi_command", None)),
            "locked main command factory is missing",
        )
        root = Path(__file__).resolve().parents[1]
        source = (root / "3th-party/prime-agent").resolve()
        lock = json.loads(
            (
                root
                / "packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json"
            ).read_text()
        )
        command = operator._pi_command(
            Path("/usr/bin/node"), source, ("--extension", "/private/extension.mjs")
        )
        self.assertTrue((source / "packages/coding-agent/dist/main.js").is_file())
        self.assertIn("packages/coding-agent/dist/main.js", lock["files"])
        self.assertIn(str(source / "packages/coding-agent/dist/main.js"), command)
        self.assertEqual(command.count("--provider"), 1)
        self.assertNotIn("rpc-entry.js", repr(command))

    def test_locked_price_and_prepare_probe_does_not_enter_verifier_cli(self):
        from asterion.applications.prime.p1.operator import _PRICE_PROBE

        root = Path(__file__).resolve().parents[1]
        selected_node = shutil.which("node")
        assert selected_node is not None
        node = str(Path(selected_node).resolve())
        result = subprocess.run(
            (
                node,
                "--input-type=module",
                "--eval",
                _PRICE_PROBE,
                node,
                str(root / "tools/build_asterion_prime_compaction_lock.mjs"),
                str((root / "3th-party/prime-agent").resolve()),
                str(
                    root
                    / "packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json"
                ),
                str(
                    root
                    / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
                ),
            ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "input": 140000,
                "output": 280000,
                "agent_dir_variable": "PRIME_AGENT_CODING_AGENT_DIR",
            },
        )
        self.assertEqual(result.stderr, "")

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

    def test_launcher_exits_with_a_stubborn_coroutine_in_an_isolated_process(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
import asyncio
from asterion.applications.prime.p1 import operator
operator._CLEANUP_SECONDS = .1
operator._preflight = lambda environment: None
async def build(_): return None
operator._build_resources = build
async def stubborn():
    while True:
        try: await asyncio.Event().wait()
        except asyncio.CancelledError: pass
async def run(_):
    asyncio.create_task(stubborn())
    await asyncio.sleep(0)
    return operator.P1PublicResult('p1-fault', 'protocol-failure')
operator.run_fixed_small_verification = run
raise SystemExit(operator.main([]))
"""
        try:
            result = subprocess.run(
                (sys.executable, "-c", program),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("launcher hung while cancelling a stubborn coroutine")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "protocol-failure")
        self.assertNotIn("completed", result.stdout)
        self.assertNotIn("artifact", result.stdout)
        self.assertEqual(result.stderr, "")

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
        owned.backend.close = stubborn
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
    assert trace.count('pi.close') == 1, 'Pi owner not closed'
    assert owned.extension_lease.closed, 'lease not closed'
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

    def test_launcher_does_not_join_a_stubborn_default_executor_thread(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
import asyncio, threading
from asterion.applications.prime.p1 import operator
operator._CLEANUP_SECONDS = .1
operator._preflight = lambda environment: None
async def build(_): return None
operator._build_resources = build
async def run(_):
    asyncio.get_running_loop().run_in_executor(None, threading.Event().wait)
    await asyncio.sleep(0)
    return operator.P1PublicResult('p1-fault', 'protocol-failure')
operator.run_fixed_small_verification = run
if hasattr(operator, '_entrypoint'): operator._entrypoint()
else: raise SystemExit(operator.main([]))
"""
        try:
            result = subprocess.run(
                (sys.executable, "-c", program),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("launcher joined a stubborn default-executor thread at exit")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "protocol-failure")
        self.assertEqual(result.stderr, "")


class TestP1OperatorInstalled(unittest.TestCase):
    def test_installed_operator_and_closed_loop_use_shared_mount_wheel(self):
        root = Path(__file__).resolve().parents[1]
        with (
            tempfile.TemporaryDirectory(
                prefix=".asterion-prime-p1-wheel.", dir=root
            ) as built,
            tempfile.TemporaryDirectory(prefix="asterion-p1-installed-") as cwd,
        ):
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                ("uv", "build", "--wheel", "--out-dir", built),
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wheels = tuple(Path(built).glob("asterion-*.whl"))
            self.assertEqual(len(wheels), 1)
            self.assertTrue(wheels[0].is_relative_to(root))
            program = r"""
import asyncio, shutil, sys, unittest
from pathlib import Path
from importlib import metadata, resources
import asterion
from asterion.applications.prime.p1 import operator, coordination
source = Path(sys.argv[1])
assert not Path(asterion.__file__).is_relative_to(source)
site = Path(asterion.__file__).parent.parent
assert Path(operator.__file__).is_relative_to(site)
assert Path(coordination.__file__).is_relative_to(site)
assert Path(str(resources.files('asterion'))).is_relative_to(site)
distribution = metadata.distribution('asterion')
assert Path(str(distribution.locate_file(''))).is_relative_to(site)
entry = next(x for x in distribution.entry_points if x.group == 'asterion.application_index' and x.name == 'prime.ipython-coding__1.0.0')
assert entry.value == 'asterion.applications.prime:create_provider'
assert not any(name.startswith('asterion.applications.prime_agent') for name in sys.modules)
async def construction_only():
    from asterion.agents.prime.compaction_budget import ModelPrice
    from asterion.runtimes.pi_extensions import PiExtensionDependencies
    base = Path(str(resources.files('asterion.applications.prime'))) / 'resources'
    node = Path(shutil.which('node')).resolve()
    dependencies = PiExtensionDependencies(
        base / 'pi-compaction-verifier.mjs', (source / '3th-party/prime-agent').resolve(),
        base / 'pi-compaction-lock.json',
        Path(str(resources.files('asterion.control.providers.prime'))) / 'resources/prime-artifact-lock.json',
        node, {name: 'string' if name in {'summarizationSystemPrompt', 'turnPrefixPrompt'} else 'function' for name in ('buildSessionContext', 'buildSummarizationPrompt', 'convertToLlm', 'prepareCompaction', 'serializeConversation', 'summarizationSystemPrompt', 'turnPrefixPrompt')},
    )
    preflight = operator._Preflight(source, Path(sys.executable), node, (source / '3th-party/prime-agent').resolve(), base / 'ipython-extension.mjs', dependencies, ModelPrice(140000, 280000), {'LANG':'C.UTF-8', 'P1_AGENT_DIR_VARIABLE':'PRIME_AGENT_CODING_AGENT_DIR'})
    owned = await operator._build_resources(preflight)
    assert not owned.backend._opened
    assert owned.backend.kernel.model_callbacks == 0
    await owned.open()
    cleanup = await owned.close_in_owner_order()
    assert cleanup.complete
    assert not owned.private_root.parent.exists()
asyncio.run(construction_only())
sys.path.append(str(source))
from tests.test_asterion_prime_p1_operator import TestP1Operator
result = unittest.TextTestRunner().run(unittest.TestSuite([TestP1Operator('test_real_closed_loop_and_cleanup_precede_runner_terminal')]))
raise SystemExit(0 if result.wasSuccessful() else 1)
"""
            checked = subprocess.run(
                (
                    "uv",
                    "run",
                    "--isolated",
                    "--with",
                    str(wheels[0]),
                    "--with",
                    "ipython==9.17.1",
                    "python",
                    "-I",
                    "-c",
                    program,
                    str(root),
                ),
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
