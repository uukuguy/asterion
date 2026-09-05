"""Focused contracts for the private P2 development gateway."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile

from asterion.applications.prime_agent.operator.p2_development_gateway import (
    PrimeP2DevelopmentGateway,
)


_SYNC_CHILD = r'''
const net=require("node:net"),s=new net.Socket({fd:Number(process.argv[2]),readable:true,writable:true});
let b=Buffer.alloc(0),out=0,i,prompt;
function c(v){if(v===null||typeof v==="string"||typeof v==="boolean"||typeof v==="number")return JSON.stringify(v);if(Array.isArray(v))return "["+v.map(c).join(",")+"]";return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+c(v[k])).join(",")+"}";}
function send(kind,request_id,payload){let x=Buffer.from(c({protocol:"asterion.prime-p2-development-gateway/v1",...i,sequence:++out,request_id,kind,payload})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]));}
s.on("data",x=>{b=Buffer.concat([b,x]);while(b.length>=4&&b.length>=4+b.readUInt32BE()){let n=b.readUInt32BE(),f=JSON.parse(b.subarray(4,4+n));b=b.subarray(4+n);i||={run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation};if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"){prompt=f.request_id;send("model.request","model-1",{});}else if(f.kind==="model.response")send("command.result",prompt,{result:{lifecycle:"completed"}});else if(f.kind==="close"){send("command.result",f.request_id,{result:{lifecycle:"closed"}});s.end();}}});
'''


class TestPrimeP2DevelopmentGateway(unittest.TestCase):
    def test_gateway_is_a_distinct_p2_protocol(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_gateway import (
            PrimeP2DevelopmentGateway,
        )

        self.assertIn("P2Development", repr(PrimeP2DevelopmentGateway.__name__))

    def test_prompt_sync_dispatches_synchronous_callback_without_event_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_SYNC_CHILD, encoding="utf-8")
            calls: list[str] = []
            gateway = PrimeP2DevelopmentGateway(
                node_bin="node",
                entrypoint=entry,
                deadline_seconds=1,
                model_hook=lambda _: calls.append("model") or {"content": []},
            )
            gateway.open_sync(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root="/tmp/prime",
                workspace="/tmp/workspace",
            )
            self.assertEqual(gateway.prompt_sync("hello"), {"lifecycle": "completed"})
            self.assertEqual(calls, ["model"])
            gateway.close_sync()


class TestPrimeP2DevelopmentGatewayCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_open_cancellation_aborts_and_reaps_transport(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p2_development_gateway as subject,
        )

        gateway = object.__new__(subject.PrimeP2DevelopmentGateway)
        abort = Mock()
        blocked = asyncio.Event()

        async def pending(function, *args: object, **kwargs: object) -> None:
            if function == gateway.open_sync:
                await blocked.wait()
                return
            function(*args, **kwargs)

        with (
            patch.object(subject.asyncio, "to_thread", side_effect=pending),
            patch.object(
                subject.PrimeP2DevelopmentGateway,
                "_abort_active_prompt",
                abort,
            ),
        ):
            task = asyncio.create_task(
                gateway.open(
                    run_id="run",
                    session_id="session",
                    generation=1,
                    prime_source_root="/prime",
                    workspace="/workspace",
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        abort.assert_called_once_with()
