from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest

from asterion.agents.prime.backend import PrimePromptRequest, PrimeSessionBackend
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.control.authority import RemainingBudget
from asterion.control.host import ControlCommand
from asterion.control.session_context import SessionContextCommand
from asterion.runtimes.pi_extensions import PiExtensionBinding
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession
from tests.test_asterion_prime_backend import FakeToolExecutor, digest
from tests.test_asterion_prime_context import LAUNCH, material


_REAL_RPC_CHILD = r"""
import json
import os
import socket
import struct
import sys

mode = sys.argv[1]
material_path = sys.argv[2]
witness = socket.socket(fileno=int(os.environ["ASTERION_PRIME_IPYTHON_WITNESS_FD"]))
with open(material_path, "r", encoding="utf-8") as stream:
    proposal_template, persisted_template = json.load(stream)

def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

def receive_frame():
    def exact(size):
        chunks = bytearray()
        while len(chunks) < size:
            chunk = witness.recv(size - len(chunks))
            if not chunk:
                raise EOFError
            chunks.extend(chunk)
        return bytes(chunks)
    size = struct.unpack("!I", exact(4))[0]
    return json.loads(exact(size))

def send_frame(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    witness.sendall(struct.pack("!I", len(raw)) + raw)

for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "prompt":
        emit({"type": "response", "id": request["id"], "success": True})
        emit({"type": "turn_start"})
        emit({
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": "answer-" + request["message"],
            },
        })
        emit({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "usage": {"input": 3, "output": 2},
            },
        })
        emit({"type": "agent_end"})
    elif request["type"] == "compact":
        emit({"type": "compaction_start", "reason": "manual"})
        arm = receive_frame()
        proposal = dict(proposal_template)
        persisted = dict(persisted_template)
        for frame in (proposal, persisted):
            frame["command_nonce"] = arm["command_nonce"]
            frame["authority_sha256"] = arm["authority_sha256"]
        send_frame(proposal)
        decision = receive_frame()
        if decision["status"] == "reject":
            assert mode == "rejected"
            emit({
                "type": "compaction_end",
                "reason": "manual",
                "aborted": True,
                "willRetry": False,
                "errorSeverity": "error",
            })
            emit({
                "type": "response",
                "id": request["id"],
                "command": "compact",
                "success": False,
                "error": "ARBITRARY-PRIVATE-COMPACTION-ERROR",
            })
        else:
            assert mode == "completed" and decision["status"] == "approve"
            send_frame(persisted)
            assert receive_frame()["phase"] == "ack"
            result = {
                "summary": "checkpoint",
                "firstKeptEntryId": "e1",
                "tokensBefore": 123456,
                "details": {"pid": os.getpid()},
            }
            emit({
                "type": "compaction_end",
                "reason": "manual",
                "result": result,
                "aborted": False,
                "willRetry": False,
            })
            emit({
                "type": "response",
                "id": request["id"],
                "command": "compact",
                "success": True,
                "data": result,
            })
    elif request["type"] == "abort":
        break
    else:
        raise AssertionError(request["type"])
"""


class TestPrimeBackendRealRpc(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.child = self.root / "controlled_rpc.py"
        self.child.write_text(_REAL_RPC_CHILD, encoding="utf-8")

    async def _backend(
        self, mode: str
    ) -> tuple[
        PrimeSessionBackend,
        PiRpcSession,
        socket.socket,
        PrimeBackendIdentity,
        FilePrimeSessionStore,
    ]:
        extension = self.root / f"extension-{mode}.mjs"
        extension.write_text(
            "export default function extension() {}\n", encoding="utf-8"
        )
        host, peer = socket.socketpair()
        host.setblocking(False)
        witness_fd_name = "ASTERION_PRIME_IPYTHON_WITNESS_FD"
        binding = PiExtensionBinding(
            "prime.ipython",
            extension,
            ("prime.tool.ipython",),
            (peer.fileno(),),
            {witness_fd_name: str(peer.fileno())},
        )
        lease = binding.preflight()
        peer.close()
        proposal, persisted = material()
        witness_material = self.root / f"witness-{mode}.json"
        witness_material.write_text(
            json.dumps([proposal, persisted], sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        command = (
            sys.executable,
            "-u",
            str(self.child),
            mode,
            str(witness_material),
            *lease.command_args(),
        )
        limits = AsterionPrimeLimits(8, 4, 5000)
        config = PiRpcConfig(
            command,
            self.root,
            dict(lease.environment),
            deadline_seconds=5,
            inherited_fds=lease.inherited_fds,
        )
        rpc = PiRpcSession(config)
        witness = PrimeContextWitnessSession(
            host,
            launch_nonce=LAUNCH,
            timeout_seconds=1,
            mark_uncertain=lambda: None,
        )
        private = self.root / f"private-{mode}"
        private.mkdir(mode=0o700)
        identity = PrimeBackendIdentity(
            "session-1",
            1,
            "prime-applications",
            "example.coding",
            "1.0.0",
            "asterion.prime",
            digest(command),
            binding.binding_fingerprint,
            "a" * 64,
            "continuation-1",
            private_root_identity(private),
            digest(
                {
                    **asdict(limits),
                    "aggregate_tokens": 64000,
                    "cost_micros": 500000,
                }
            ),
        )
        store = FilePrimeSessionStore(private, identity)
        backend = PrimeSessionBackend(
            identity=identity,
            store=store,
            rpc_session=rpc,
            extension_binding=binding,
            extension_lease=lease,
            approved_command=command,
            approved_environment=dict(lease.environment),
            limits=limits,
            aggregate_tokens=64000,
            cost_micros=500000,
            model_price=ModelPrice(1000000, 1000000),
            witness=witness,
            tool_executor=FakeToolExecutor(),
            authority_id="authority-1",
        )
        self.addAsyncCleanup(backend.close)
        backend.sync_authority_snapshot(
            RemainingBudget(64000, 64000, 0, 64000, 500000, 5000),
            authority_revision=1,
        )
        await backend.accept_control(
            ControlCommand(
                "create-1",
                "session-1",
                1,
                "session.create",
                {
                    "system_id": "example.coding",
                    "system_version": "1.0.0",
                    "goal_id": "goal-1",
                    "goal_ref": "goal-ref-1",
                },
            )
        )
        return backend, rpc, host, identity, store

    @staticmethod
    def _prompt(command_id: str, text: str) -> PrimePromptRequest:
        return PrimePromptRequest(command_id, "session-1", 1, text)

    @staticmethod
    def _compact(*, tokens: int) -> SessionContextCommand:
        return SessionContextCommand(
            "compact-1",
            "session-1",
            1,
            1,
            "compact-key",
            "session.compact",
            {
                "continuation_id": "continuation-1",
                "instructions_ref": None,
                "budget": {
                    "controller_tokens": tokens,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": tokens,
                    "cost_micros": 125000,
                    "deadline_ms": 5000,
                },
            },
        )

    async def test_prompt_compact_prompt_uses_one_real_process_and_cursor(self) -> None:
        backend, rpc, _host, identity, store = await self._backend("completed")
        attachment = backend.attach(identity)
        first = await attachment.execute_prompt(self._prompt("prompt-1", "stage-one"))
        assert rpc.process is not None
        process = rpc.process
        pid = process.pid

        compact = await attachment.execute_context(self._compact(tokens=16000))
        second = await attachment.execute_prompt(self._prompt("prompt-2", "stage-two"))

        self.assertEqual(
            (first.status, compact.status, second.status),
            ("completed", "succeeded", "completed"),
        )
        self.assertIs(rpc.process, process)
        self.assertEqual(rpc.process.pid, pid)
        events = attachment.replay_events()
        self.assertEqual(
            tuple(event.cursor for event in events), tuple(range(1, len(events) + 1))
        )
        self.assertIsNotNone(store.recover_checkpoint())

    async def test_rejected_real_compact_preserves_checkpoint_and_reuses_process(
        self,
    ) -> None:
        backend, rpc, _host, identity, store = await self._backend("rejected")
        attachment = backend.attach(identity)
        await attachment.execute_prompt(self._prompt("prompt-1", "stage-one"))
        before = store.recover_checkpoint()
        assert before is not None and rpc.process is not None
        process = rpc.process

        rejected = await attachment.execute_context(self._compact(tokens=1))

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(store.recover_checkpoint(), before)
        backend.attach(identity)
        resumed = await attachment.execute_context(
            SessionContextCommand(
                "resume-1",
                "session-1",
                1,
                1,
                "resume-key",
                "session.continuation.resume",
                {"continuation_id": "continuation-1"},
            )
        )
        continued = await attachment.execute_prompt(
            self._prompt("prompt-2", "stage-two")
        )
        self.assertEqual((resumed.status, continued.status), ("succeeded", "completed"))
        self.assertIs(rpc.process, process)
        events = attachment.replay_events()
        self.assertEqual(
            tuple(event.cursor for event in events), tuple(range(1, len(events) + 1))
        )
        self.assertNotIn(
            "ARBITRARY-PRIVATE-COMPACTION-ERROR",
            repr((rejected, events, backend.snapshot())),
        )


if __name__ == "__main__":
    unittest.main()
