"""Focused contract tests for the private P1 development gateway."""

from __future__ import annotations

from pathlib import Path
import tempfile
import asyncio
import unittest

from asterion.applications.prime_agent.operator.p1_development_gateway import (
    PrimeP1DevelopmentGateway,
    PrimeP1DevelopmentGatewayError,
)


_CHILD = r'''
const net = require("node:net");
const s = new net.Socket({fd: Number(process.argv[2]), readable:true, writable:true});
let b = Buffer.alloc(0), out = 0, identity, models = 0, promptId;
function canon(v) { if (v === null || typeof v === "string" || typeof v === "boolean" || typeof v === "number") return JSON.stringify(v); if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]"; return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}"; }
function send(kind, request_id, payload) { const x = Buffer.from(canon({protocol:"asterion.prime-p1-development-gateway/v1", ...identity, sequence:++out, request_id, kind, payload})); const h = Buffer.alloc(4); h.writeUInt32BE(x.length); s.write(Buffer.concat([h,x])); }
function frame(x) { const f = JSON.parse(x.toString("utf8")); identity ||= {run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation}; if (f.kind === "open") send("ready",f.request_id,{}); else if (f.kind === "prompt") { promptId=f.request_id; send("model.request","model-1",{model:{},context:{},options:{}}); } else if (f.kind === "model.response") { if (++models === 1) send("tool.request","tool-1",{tool_call_id:"call-1",code:"1+1"}); else send("command.result",promptId,{result:{lifecycle:"completed"}}); } else if (f.kind === "tool.response") send("model.request","model-2",{model:{},context:{},options:{}}); else if (f.kind === "cancel") send("command.result",f.request_id,{result:{lifecycle:"cancelled"}}); else if (f.kind === "close") { send("command.result",f.request_id,{result:{lifecycle:"closed"}}); s.end(); } }
s.on("data", c => { b = Buffer.concat([b,c]); while (b.length >= 4 && b.length >= 4 + b.readUInt32BE()) { const n=b.readUInt32BE(); const x=b.subarray(4,4+n); b=b.subarray(4+n); frame(x); } });
'''

_STALLING_CHILD = r'''
const net = require("node:net");
const s = new net.Socket({fd: Number(process.argv[2]), readable:true, writable:true});
let b = Buffer.alloc(0), out = 0, identity;
function canon(v) { if (v === null || typeof v === "string" || typeof v === "boolean" || typeof v === "number") return JSON.stringify(v); if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]"; return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}"; }
function send(kind, request_id, payload) { const x = Buffer.from(canon({protocol:"asterion.prime-p1-development-gateway/v1", ...identity, sequence:++out, request_id, kind, payload})); const h = Buffer.alloc(4); h.writeUInt32BE(x.length); s.write(Buffer.concat([h,x])); }
s.on("data", c => { b=Buffer.concat([b,c]); while (b.length >= 4 && b.length >= 4+b.readUInt32BE()) { const n=b.readUInt32BE(), f=JSON.parse(b.subarray(4,4+n)); b=b.subarray(4+n); identity ||= {run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation}; if (f.kind === "open") send("ready",f.request_id,{}); } });
'''


class TestPrimeP1DevelopmentGateway(unittest.IsolatedAsyncioTestCase):
    def test_transport_canonical_json_rejects_floats_for_p1a_protocol(self) -> None:
        from asterion.applications.prime_agent.operator.development_gateway_transport import (
            DevelopmentGatewayTransportError,
            _canonical_json,
        )

        with self.assertRaises(DevelopmentGatewayTransportError):
            _canonical_json(1.5)

    async def test_prompt_dispatches_model_and_tool_then_closes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_CHILD, encoding="utf-8")
            seen: list[tuple[str, object]] = []

            async def model(payload: object) -> object:
                seen.append(("model", payload))
                return {"role": "assistant", "content": []}

            async def tool(payload: object) -> object:
                seen.append(("tool", payload))
                return {"ok": True}

            gateway = PrimeP1DevelopmentGateway(
                node_bin="node", entrypoint=entry, deadline_seconds=1,
                model_hook=model, tool_hook=tool,
            )
            await gateway.open(run_id="run-1", session_id="session-1", generation=1,
                               prime_source_root="/tmp/prime", workspace="/tmp/workspace")
            # The fixture emits two model callbacks and one tool callback before
            # the bridge's terminal result.
            result = await gateway.prompt("hello")
            self.assertEqual(result, {"lifecycle": "completed"})
            self.assertEqual([name for name, _ in seen], ["model", "tool", "model"])
            await gateway.close()

    async def test_timeout_reaps_and_redacts_child_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text("setInterval(() => {}, 1000);", encoding="utf-8")
            gateway = PrimeP1DevelopmentGateway(node_bin="node", entrypoint=entry, deadline_seconds=0.05)
            with self.assertRaises(PrimeP1DevelopmentGatewayError) as raised:
                await gateway.open(run_id="run-1", session_id="session-1", generation=1,
                                   prime_source_root="/tmp/SENTINEL_SECRET", workspace="/tmp/workspace")
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            self.assertIsNone(gateway.child_pid)

    async def test_cancelling_active_prompt_reaps_private_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_STALLING_CHILD, encoding="utf-8")
            gateway = PrimeP1DevelopmentGateway(node_bin="node", entrypoint=entry, deadline_seconds=10)
            await gateway.open(run_id="run-1", session_id="session-1", generation=1,
                               prime_source_root="/tmp/prime", workspace="/tmp/workspace")
            running = asyncio.create_task(gateway.prompt("hello"))
            await asyncio.sleep(0.02)
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
            self.assertIsNone(gateway.child_pid)


class TestPrimeP1DevelopmentGatewaySync(unittest.TestCase):
    def test_prompt_sync_dispatches_synchronous_callbacks_without_event_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_CHILD, encoding="utf-8")
            calls: list[str] = []
            gateway = PrimeP1DevelopmentGateway(
                node_bin="node",
                entrypoint=entry,
                deadline_seconds=1,
                model_hook=lambda _: calls.append("model") or {"content": []},
                tool_hook=lambda _: calls.append("tool") or {"ok": True},
            )
            gateway.open_sync(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root="/tmp/prime",
                workspace="/tmp/workspace",
            )
            self.assertEqual(gateway.prompt_sync("hello"), {"lifecycle": "completed"})
            self.assertEqual(calls, ["model", "tool", "model"])
            gateway.close_sync()


if __name__ == "__main__":
    unittest.main()
