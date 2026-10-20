"""Cross-generation model continuity against actual immutable checkpoint blobs."""

import asyncio
import contextlib
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p4 import live, live_entry, operator
from asterion.applications.prime.p4.runtime_binding import _P4RuntimeSession
from asterion.capabilities.prime_long_session_continuity_native.provider import (
    P4_INPUT_PRESET,
)
from asterion.runtime.host import RunRequest
from asterion.agents.prime import application
from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.live_model import bounded_text_limits


def _prime(root):
    limits = bounded_text_limits()
    context = PrimeOperatorContext(
        executable=Path("/fake/node"), entry=Path("/fake/pi"), cwd=root.absolute(),
        provider="deepseek", model="deepseek-flash", effort="off", environment={},
        task_deadline=TaskDeadline(deadline_monotonic=time.monotonic() + 120,
                                   deadline_epoch=time.time() + 120),
    )
    return prepare_prime_application(
        PrimeApplicationSpec("prime.test.p4", "1.0.0", "text-only"), context, authorization=limits,
    )


def _owned_session(session, usage):
    prompt = session.prompt
    close = session.close
    reaped = False

    async def measured_prompt(text, *, signal):
        usage.prompts += 1
        try:
            reply = await prompt(text, signal=signal)
        except BaseException:
            usage.blocked = usage.unknown_effect = True
            raise
        usage.input_tokens += reply.usage.input_tokens
        usage.output_tokens += reply.usage.output_tokens
        return reply

    async def owned_close():
        nonlocal reaped
        if reaped:
            return
        try:
            await close()
        except BaseException:
            usage.blocked = True
            raise
        reaped = True

    session.prompt = measured_prompt
    session.close = owned_close
    return session


_RPC_PRODUCER = r'''
import json, sys
def emit(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "abort":
        break
    if request["type"] == "get_state":
        emit({"type": "response", "id": request["id"], "command": "get_state", "success": True,
              "data": {"model": {"provider": "deepseek", "id": "deepseek-flash", "maxTokens": 512}}})
        continue
    if request["type"] != "prompt":
        continue
    task = json.loads(request["message"].split("TASK_JSON=", 1)[1])
    if "inputs" in task:
        answer = {"token": task["token"], "total": sum(task["inputs"])}
    else:
        answer = {"token": task["prior"]["token"], "prior_total": task["prior"]["total"],
                  "total": task["prior"]["total"] + task["increment"]}
    emit({"type": "response", "id": request["id"], "success": True})
    emit({"type": "agent_start"})
    emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(answer)}})
    emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": {"input": 100, "output": 30}}})
    emit({"type": "agent_end", "messages": []})
    emit({"type": "agent_settled"})
'''

_OPERATOR = r'''
import asyncio, json, os, sys, time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from asterion.agents.prime import _launch
from asterion.agents.prime.application import PrimeApplicationSpec, PrimeOperatorContext, prepare_prime_application
from asterion.agents.prime.deadline import TaskDeadline
from asterion.applications.prime.live_model import bounded_text_limits
from asterion.applications.prime.p4.live import run_live_round
from asterion.runtimes.pi_rpc import PiRpcSession, PiRpcConfig
processes = []
def rpc(config):
    native = PiRpcSession(PiRpcConfig(command=(sys.executable, "-I", sys.argv[3]),
        environment=config.environment, cwd=config.cwd, deadline_seconds=config.deadline_seconds))
    original = native.open
    async def open_session(*, signal):
        await original(signal=signal)
        processes.append(native.process)
    native.open = open_session
    return native
context = PrimeOperatorContext(executable=Path(sys.executable), entry=None,
    cwd=Path(sys.argv[2]).parent, provider="deepseek", model="deepseek-flash", effort="off",
    environment={}, task_deadline=TaskDeadline(deadline_monotonic=time.monotonic()+120,
                                               deadline_epoch=time.time()+120))
prime = prepare_prime_application(PrimeApplicationSpec("prime.test.p4", "1.0.0", "text-only"),
    context, authorization=bounded_text_limits())
with patch.object(_launch, "text_rpc", side_effect=rpc):
    result = asyncio.run(run_live_round(mode=sys.argv[1], private_root=Path(sys.argv[2]), prime=prime))
assert len(processes) == 1 and processes[0].poll() is not None
print(json.dumps({"result": asdict(result), "operator_pid": os.getpid(), "model_pid": processes[0].pid}))
'''


class Session:
    def __init__(self, mode, owner):
        self.mode, self.owner = mode, owner
        self.closed = False

    async def open(self, *, signal):
        self.owner.events.append("open:" + self.mode)

    async def prompt(self, text, *, signal):
        if self.owner.fail_prompt:
            raise RuntimeError("PRIVATE-TRANSIENT-MODEL-FAILURE")
        self.owner.prompts.append(text)
        task = json.loads(text.split("TASK_JSON=", 1)[1])
        if self.mode == "commit":
            value = {"token": task["token"], "total": sum(task["inputs"])}
        else:
            value = {"token": task["prior"]["token"],
                     "prior_total": task["prior"]["total"],
                     "total": task["prior"]["total"] + task["increment"]}
        if self.owner.bad_answer:
            value["total"] = -1
        return SimpleNamespace(
            text=json.dumps(value),
            usage=SimpleNamespace(input_tokens=100, output_tokens=30, cost_micros=66),
        )

    async def close(self):
        self.closed = True
        self.owner.events.append("close:" + self.mode)
        if self.owner.bad_close:
            raise RuntimeError("SECRET-CLOSE")


class TestP4Live(unittest.IsolatedAsyncioTestCase):
    def test_entry_accepts_owner_without_session_factory(self):
        import inspect
        from asterion.applications.prime.p4 import live
        entry = live.run_live_round
        self.assertNotIn("session_factory", inspect.signature(entry).parameters)
        self.assertIn("prime", inspect.signature(entry).parameters)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "store"
        self.sessions, self.events, self.prompts = [], [], []
        self.bad_answer = self.bad_close = False
        self.fail_prompt = False

    def factory(self, mode, cwd):
        session = Session(mode, self)
        self.sessions.append(session)
        return session

    async def run_round(self, mode, **kwargs):
        prime = _prime(Path(self.temp.name))
        def session(**material):
            return _owned_session(self.factory(mode, material["cwd"]), material["usage"])
        with patch.object(application, "LiveModelSession", side_effect=session):
            return await live.run_live_round(mode=mode, private_root=self.root, prime=prime, **kwargs)

    async def test_new_session_consumes_prior_artifact_through_composed_path(self):
        runs = []
        original_run = _P4RuntimeSession.run

        async def spy(self, request, *, signal=None):
            runs.append(request.input_text)
            async for event in original_run(self, request, signal=signal):
                yield event

        with patch.object(_P4RuntimeSession, "run", spy):
            commit = await self.run_round("commit")
            blobs = {path.name: path.read_bytes() for path in self.root.glob("transcript-*.blob")}
            recover = await self.run_round("recover")
        self.assertEqual(runs, [P4_INPUT_PRESET, P4_INPUT_PRESET])
        self.assertEqual((commit.status, recover.status), ("committed", "recovered"))
        self.assertEqual(recover.new_generation, 2)
        self.assertEqual(recover.prior_checkpoint_sha256, commit.checkpoint_sha256)
        self.assertNotEqual(commit.worker_identity_sha256, recover.worker_identity_sha256)
        self.assertEqual(recover.recovered_payload_sha256, commit.result_sha256)
        self.assertEqual(recover.model_call_count, 1)
        self.assertEqual(recover.cost_micros, 66)
        for name, content in blobs.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertIn(json.loads(content)["token"], self.prompts[-1])
        self.assertEqual(self.events, ["open:commit", "close:commit", "open:recover", "close:recover"])
        public = json.dumps(asdict(recover))
        self.assertNotIn(self.temp.name, public)
        self.assertNotIn("prior_total", public)

    async def test_saved_startup_and_binding_mismatch_reject_before_model(self):
        await self.run_round("commit")
        identity_path = self.root / "identity.json"
        original = identity_path.read_bytes()
        document = json.loads(original)
        for field in ("pi_command_sha256", "extension_binding_fingerprint"):
            with self.subTest(field=field):
                changed = dict(document)
                changed[field] = "f" * 64
                identity_path.write_text(json.dumps(changed))
                with self.assertRaises(live.P4LiveError):
                    await self.run_round("recover")
                self.assertEqual(len(self.sessions), 1)
                identity_path.write_bytes(original)

    async def test_direct_round_ignores_central_provider_composition(self):
        with (
            patch("asterion.applications.provider.compose_installed_provider", side_effect=AssertionError("central composition")),
            patch("asterion.applications.prime.inventory.prime_application_index", side_effect=AssertionError("central inventory")),
            patch("asterion.applications.prime.inventory.prime_release_application", side_effect=AssertionError("central lookup")),
        ):
            result = await self.run_round("commit")
        self.assertEqual(result.status, "committed")

    async def test_corrupt_committed_artifact_rejects_before_model(self):
        await self.run_round("commit")
        blob = next(self.root.glob("transcript-*.blob"))
        blob.write_bytes(b"SECRET-CORRUPTION")
        with self.assertRaises(live.P4LiveError) as caught:
            await self.run_round("recover")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(len(self.sessions), 1)

    async def test_wrong_answer_never_seals_checkpoint_and_closes(self):
        self.bad_answer = True
        with self.assertRaises(live.P4LiveError):
            await self.run_round("commit")
        self.assertTrue(self.sessions[0].closed)
        self.assertEqual(list(self.root.glob("transcript-*.blob")), [])

    async def test_close_failure_never_seals_successful_checkpoint(self):
        self.bad_close = True
        with self.assertRaises(live.P4LiveError):
            await self.run_round("commit")
        self.assertEqual(list(self.root.glob("transcript-*.blob")), [])

    async def test_third_invocation_cannot_replay_committed_recovery(self):
        await self.run_round("commit")
        await self.run_round("recover")
        with self.assertRaises(live.P4LiveError):
            await self.run_round("recover")
        self.assertEqual(len(self.sessions), 2)

    async def test_transient_recovery_failure_preserves_checkpoint_for_retry(self):
        committed = await self.run_round("commit")
        identity = (self.root / "identity.json").read_bytes()
        records = (self.root / "records.jsonl").read_bytes()
        blobs = {path.name: path.read_bytes() for path in self.root.glob("transcript-*.blob")}
        self.fail_prompt = True
        with self.assertRaises(live.P4LiveError):
            await self.run_round("recover")
        self.assertTrue(self.sessions[-1].closed)
        self.assertEqual((self.root / "identity.json").read_bytes(), identity)
        self.assertEqual((self.root / "records.jsonl").read_bytes(), records)
        self.fail_prompt = False
        recovered = await self.run_round("recover")
        self.assertEqual(recovered.prior_checkpoint_sha256, committed.checkpoint_sha256)
        self.assertEqual(recovered.new_generation, 2)
        for name, content in blobs.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    async def test_recovery_holds_prior_generation_lock_until_model_finishes(self):
        await self.run_round("commit")
        host = live.P4LiveHost(
            mode="recover", private_root=self.root, prime=_prime(Path(self.temp.name)),
        )
        try:
            self.assertEqual(operator._read_prior_identity(self.root).generation, 1)
            self.assertEqual(host.continuity.current_generation, 1)
            with self.assertRaises(live.P4LiveError):
                await self.run_round("recover")
            self.assertEqual(len(self.sessions), 1)
        finally:
            await host.close()
        recovered = await self.run_round("recover")
        self.assertEqual(recovered.new_generation, 2)

    async def test_cancelled_invocation_starts_no_session(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.run_round("commit", signal=SimpleNamespace(cancelled=True))
        self.assertEqual(self.sessions, [])

    async def test_runtime_reports_measured_tokens_instead_of_artifact_bytes(self):
        prime = _prime(Path(self.temp.name))
        def session(**material):
            return _owned_session(self.factory("commit", material["cwd"]), material["usage"])
        seam = patch.object(application, "LiveModelSession", side_effect=session)
        seam.start()
        self.addCleanup(seam.stop)
        host = live.P4LiveHost(mode="commit", private_root=self.root, prime=prime)
        try:
            runtime = _P4RuntimeSession(host, "commit")
            events = [event async for event in runtime.run(
                RunRequest(run_id="p4-usage", input_text=operator.P4_INPUT_PRESET,
                           requested_capabilities=("prime.tool.ipython",)),
                signal=SimpleNamespace(cancelled=False),
            )]
            usage = next(event for event in events if event.type == "usage.reported")
            self.assertEqual(dict(usage.payload), {"input_tokens": 100, "output_tokens": 30})
        finally:
            await host.close()

    async def test_separate_operator_and_rpc_processes_recover_only_from_disk(self):
        producer = Path(self.temp.name) / "rpc-producer.py"
        producer.write_text(_RPC_PRODUCER)

        async def invoke(mode):
            completed = await asyncio.to_thread(
                subprocess.run,
                (sys.executable, "-I", "-c", _OPERATOR, mode, str(self.root), str(producer)),
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

        committed = await invoke("commit")
        recovered = await invoke("recover")
        self.assertNotEqual(committed["operator_pid"], recovered["operator_pid"])
        self.assertNotEqual(committed["model_pid"], recovered["model_pid"])
        self.assertNotEqual(os.getpid(), recovered["operator_pid"])
        self.assertEqual(
            recovered["result"]["prior_checkpoint_sha256"],
            committed["result"]["checkpoint_sha256"],
        )
        self.assertEqual(recovered["result"]["new_generation"], 2)


class TestP4LiveEntry(unittest.TestCase):
    def test_invalid_launch_emits_only_public_failure(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
            status = live_entry.main()
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue()), {"status": "protocol-failure", "private_root_redacted": True})

    def test_finite_environment_resolves_launch_and_prints_receipt(self):
        output = io.StringIO()
        environment = {"ASTERION_PRIME_OPERATOR_ROOT": "/private/operator",
                       "ASTERION_PRIME_P4_PRIVATE_ROOT": "/private/new-store",
                       "ASTERION_PRIME_P4_MODE": "commit"}
        context = _prime(Path("/private/operator"))._operator
        with patch.dict(os.environ, environment, clear=True), patch.object(
            live_entry, "resolve_live_model_context", return_value=context
        ), patch.object(live_entry, "run_live_round", return_value=live.P4LiveResult(status="committed")) as run, contextlib.redirect_stdout(output):
            status = live_entry.main()
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args.kwargs["mode"], "commit")
        self.assertEqual(run.call_args.kwargs["private_root"], Path("/private/new-store"))
        self.assertNotIn("/private", output.getvalue())
