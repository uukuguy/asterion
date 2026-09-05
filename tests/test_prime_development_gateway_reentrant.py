"""Re-entrancy and failure contracts for development gateway transport."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime_agent.operator.development_gateway_transport import (
    DevelopmentGatewayTransport,
    DevelopmentGatewayTransportError,
)


_CHILD = r'''
const net = require("node:net");
const s = new net.Socket({fd:Number(process.argv[2]), readable:true, writable:true});
let b=Buffer.alloc(0), out=0, identity, promptId, mode="MODE";
function canon(v){if(v===null||typeof v==="string"||typeof v==="boolean"||typeof v==="number")return JSON.stringify(v);if(Array.isArray(v))return "["+v.map(canon).join(",")+"]";return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canon(v[k])).join(",")+"}";}
function send(kind,request_id,payload){let x=Buffer.from(canon({protocol:"test.reentrant/v1",...identity,sequence:++out,request_id,kind,payload})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]));}
function frame(f){identity ||= {run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation};if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"){promptId=f.request_id;send("tool.request","tool-1",{});}else if(f.kind==="rlm.spawn"){if(mode==="cancel"){}else if(mode==="unknown")send("command.result","other-1",{result:{status:"spawned"}});else send("model.request","model-1",{});}else if(f.kind==="model.response"){send("command.result","nested-1",{result:{status:"spawned"}});if(mode==="duplicate")send("command.result","nested-1",{result:{status:"spawned"}});}else if(f.kind==="tool.response")send("command.result",promptId,{result:{lifecycle:"completed"}});}
s.on("data",c=>{b=Buffer.concat([b,c]);while(b.length>=4&&b.length>=4+b.readUInt32BE()){let n=b.readUInt32BE(),f=JSON.parse(b.subarray(4,4+n));b=b.subarray(4+n);frame(f);}});
'''


class TestDevelopmentGatewayTransportReentrant(unittest.IsolatedAsyncioTestCase):
    async def test_tool_hook_can_await_nested_command_while_reader_handles_model(self) -> None:
        async with self._gateway("normal") as gateway:
            async def tool_hook(_: Mapping[str, object]) -> object:
                nested = await gateway.request_nested(
                    "rlm.spawn", {"role": "implementation"}
                )
                return {"content": [{"type": "text", "text": nested["status"]}]}

            gateway._tool_hook = tool_hook
            self.assertEqual(
                await self._prompt(gateway), {"lifecycle": "completed"}
            )

    async def test_unlisted_nested_kind_closes_transport(self) -> None:
        async with self._gateway("normal") as gateway:
            with self.assertRaises(DevelopmentGatewayTransportError):
                await gateway.request_nested("not.allowed", {})
            self.assertIsNone(gateway.child_pid)

    async def test_duplicate_nested_result_closes_transport(self) -> None:
        async with self._gateway("duplicate") as gateway:
            gateway._tool_hook = self._nested_tool(gateway)
            with self.assertRaises(DevelopmentGatewayTransportError):
                await self._prompt(gateway)
            self.assertIsNone(gateway.child_pid)

    async def test_unknown_nested_result_closes_transport(self) -> None:
        async with self._gateway("unknown") as gateway:
            gateway._tool_hook = self._nested_tool(gateway)
            with self.assertRaises(DevelopmentGatewayTransportError):
                await self._prompt(gateway)
            self.assertIsNone(gateway.child_pid)

    async def test_callback_exception_closes_transport(self) -> None:
        async with self._gateway("callback-error") as gateway:
            def fail(_: Mapping[str, object]) -> object:
                raise RuntimeError("private callback detail")

            gateway._tool_hook = fail
            with self.assertRaises(DevelopmentGatewayTransportError):
                await self._prompt(gateway)
            self.assertIsNone(gateway.child_pid)

    async def test_cancelled_nested_command_closes_transport(self) -> None:
        async with self._gateway("cancel") as gateway:
            async def cancelled(_: Mapping[str, object]) -> object:
                task = asyncio.create_task(gateway.request_nested("rlm.spawn", {}))
                await asyncio.sleep(0.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                return {}

            gateway._tool_hook = cancelled
            with self.assertRaises(DevelopmentGatewayTransportError):
                await self._prompt(gateway)
            self.assertIsNone(gateway.child_pid)

    def _nested_tool(self, gateway: DevelopmentGatewayTransport):
        async def tool(_: Mapping[str, object]) -> object:
            await gateway.request_nested("rlm.spawn", {})
            return {}

        return tool

    async def _prompt(self, gateway: DevelopmentGatewayTransport) -> Mapping[str, object]:
        frame = await asyncio.to_thread(
            gateway._receive_until,
            gateway._send("prompt", "prompt-1", {"prompt": "fixed"}),
            {"command.result"},
        )
        payload = frame["payload"]
        self.assertIsInstance(payload, dict)
        result = payload["result"]
        self.assertIsInstance(result, dict)
        return result

    class _GatewayContext:
        def __init__(self, owner: "TestDevelopmentGatewayTransportReentrant", mode: str) -> None:
            self._owner, self._mode = owner, mode
            self.gateway: DevelopmentGatewayTransport | None = None
            self.temporary: tempfile.TemporaryDirectory[str] | None = None

        async def __aenter__(self) -> DevelopmentGatewayTransport:
            self.temporary = tempfile.TemporaryDirectory()
            entry = Path(self.temporary.name) / "bridge.js"
            entry.write_text(_CHILD.replace("MODE", self._mode), encoding="utf-8")
            self.gateway = DevelopmentGatewayTransport(
                protocol="test.reentrant/v1",
                default_entrypoint=entry,
                model_hook=lambda _: {"role": "assistant"},
                tool_hook=lambda _: {},
                node_bin="node",
                entrypoint=entry,
                deadline_seconds=1,
                nested_command_kinds=frozenset(("rlm.spawn",)),
            )
            self.gateway._event_loop = asyncio.get_running_loop()
            self.gateway._set_identity(run_id="run-1", session_id="session-1", generation=1)
            self.gateway._launch()
            await asyncio.to_thread(
                self.gateway._receive_until,
                self.gateway._send("open", "open-1", {}),
                {"ready"},
            )
            return self.gateway

        async def __aexit__(self, *_: object) -> None:
            if self.gateway is not None:
                self.gateway._fail_transport()
            if self.temporary is not None:
                self.temporary.cleanup()

    def _gateway(self, mode: str) -> _GatewayContext:
        return self._GatewayContext(self, mode)


if __name__ == "__main__":
    unittest.main()
