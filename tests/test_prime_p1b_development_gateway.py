"""Focused contract tests for the private P1-B development gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime_agent.operator.p1b_development_gateway import (
    PrimeP1BDevelopmentGateway,
    PrimeP1BDevelopmentGatewayError,
    _safe_witness,
)


_CHILD = r"""
const net=require("node:net"),s=new net.Socket({fd:+process.argv[2],readable:true,writable:true});
let b=Buffer.alloc(0),out=0,i,phase="open",models=0,tools=0,active;
const canon=v=>v===null||["string","boolean","number"].includes(typeof v)?JSON.stringify(v):Array.isArray(v)?"["+v.map(canon).join(",")+"]":"{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canon(v[k])).join(",")+"}";
function send(kind,request_id,payload){let x=Buffer.from(canon({protocol:"asterion.prime-p1-b-development-gateway/v1",...i,sequence:++out,request_id,kind,payload})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]));}
function model(){send("model.request","model-"+(models+1),{model:{},context:{},options:{}})}
function frame(f){i||=( {run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation});if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"||f.kind==="compact"){active=f.request_id;model()}else if(f.kind==="model.response"){models++;if(models===1||models===4){tools++;send("tool.request","tool-"+tools,{tool_call_id:"call-"+tools,code:"1+1"})}else if(phase==="open"){phase="compact";send("command.result",active,{result:{lifecycle:"completed"}})}else if(phase==="compact"){phase="prompt2";send("command.result",active,{result:{compact_called:true,succeeded:true,start_count:1,end_count:1,message_count_before:2,message_count_after:1,tokens_before:3,first_kept_entry_id_sha256:"sha256:"+"a".repeat(64)}})}else {phase="close";send("command.result",active,{result:{lifecycle:"completed"}})}}else if(f.kind==="tool.response")model();else if(f.kind==="cancel"){send("command.result",f.request_id,{result:{lifecycle:"cancelled"}})}else if(f.kind==="close"){send("command.result",f.request_id,{result:{lifecycle:"closed"}});s.end();}}
s.on("data",c=>{b=Buffer.concat([b,c]);while(b.length>=4&&b.length>=4+b.readUInt32BE()){let n=b.readUInt32BE(),f=JSON.parse(b.subarray(4,4+n));b=b.subarray(4+n);frame(f)}});
"""

_STALL_COMPACT_CHILD = _CHILD.replace(
    'else if(phase==="compact"){phase="prompt2";send("command.result",active,{result:{compact_called:true,succeeded:true,start_count:1,end_count:1,message_count_before:2,message_count_after:1,tokens_before:3,first_kept_entry_id_sha256:"sha256:"+"a".repeat(64)}})}',
    'else if(phase==="compact"){}',
)


class TestPrimeP1BDevelopmentGateway(unittest.IsolatedAsyncioTestCase):
    def test_witness_rejects_non_observed_compaction_counts(self) -> None:
        with self.assertRaises(ValueError):
            _safe_witness(
                {
                    "compact_called": True,
                    "succeeded": True,
                    "start_count": 0,
                    "end_count": 0,
                    "message_count_before": 2,
                    "message_count_after": 1,
                    "tokens_before": 3,
                    "first_kept_entry_id_sha256": "sha256:" + "a" * 64,
                }
            )

    async def test_fixed_two_prompt_flow_awaits_five_model_two_tool_callbacks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_CHILD, encoding="utf-8")
            calls: list[str] = []

            async def model(payload: object) -> object:
                calls.append("model")
                return {"role": "assistant", "content": []}

            async def tool(payload: object) -> object:
                calls.append("tool")
                return {"ok": True}

            gateway = PrimeP1BDevelopmentGateway(
                node_bin="node", entrypoint=entry, model_hook=model, tool_hook=tool
            )
            await gateway.open(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root=temporary,
                workspace=temporary,
            )
            self.assertEqual((await gateway.prompt("one"))["lifecycle"], "completed")
            witness = await gateway.compact()
            self.assertEqual(
                witness["first_kept_entry_id_sha256"], "sha256:" + "a" * 64
            )
            self.assertEqual((await gateway.prompt("two"))["lifecycle"], "completed")
            await gateway.close()
            self.assertEqual(
                calls, ["model", "tool", "model", "model", "model", "tool", "model"]
            )

    async def test_cancelling_active_compact_reaps_child_and_redacts_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_STALL_COMPACT_CHILD, encoding="utf-8")
            gateway = PrimeP1BDevelopmentGateway(
                node_bin="node",
                entrypoint=entry,
                model_hook=lambda _: {"role": "assistant"},
                tool_hook=lambda _: {},
            )
            await gateway.open(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root=temporary,
                workspace=temporary,
            )
            await gateway.prompt("one")
            task = asyncio.create_task(gateway.compact())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNone(gateway.child_pid)
            self.assertNotIn("SENTINEL", str(gateway))
            with self.assertRaises(PrimeP1BDevelopmentGatewayError):
                await gateway.close()
