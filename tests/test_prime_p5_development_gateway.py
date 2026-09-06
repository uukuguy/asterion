"""Focused contracts for the private P5 development gateway."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime_agent.operator.p5_development_gateway import (
    PrimeP5DevelopmentGateway,
)


_CHILD = r'''
const net=require("node:net"),s=new net.Socket({fd:Number(process.argv[2]),readable:true,writable:true});let b=Buffer.alloc(0),o=0,i,p,q=0;
function c(v){if(v===null||typeof v!=="object")return JSON.stringify(v);if(Array.isArray(v))return "["+v.map(c).join(",")+"]";return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+c(v[k])).join(",")+"}"}function send(k,id,payload){let x=Buffer.from(c({protocol:"asterion.prime-p5-development-gateway/v1",...i,sequence:++o,request_id:id,kind:k,payload})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]))}s.on("data",x=>{b=Buffer.concat([b,x]);while(b.length>=4&&b.length>=4+b.readUInt32BE()){let n=b.readUInt32BE(),f=JSON.parse(b.subarray(4,4+n));b=b.subarray(4+n);i||={run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation};if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"){p=f.request_id;q++;send("model.request","model-"+f.sequence,{})}else if(f.kind==="model.response")send("command.result",p,{result:{lifecycle:"completed",usage:{input_tokens:q,output_tokens:q,total_tokens:q*2},assistant:{completed:true,stop_reason:"stop"},observations:{active_tool_names:["ipython"],compact_count:0,model_callback_count:q*2,rlm_child_count:0,tool_call_count:q}}});else if(f.kind==="feedback")send("command.result",f.request_id,{result:{}});else if(f.kind==="close"){send("command.result",f.request_id,{result:{lifecycle:"closed"}});s.end()}}});
'''


class TestPrimeP5DevelopmentGateway(unittest.TestCase):
    def test_forwards_python_feedback_between_same_session_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            entrypoint = Path(temporary) / "bridge.js"
            entrypoint.write_text(_CHILD, encoding="utf-8")
            gateway = PrimeP5DevelopmentGateway(
                node_bin="node", entrypoint=entrypoint, deadline_seconds=1,
                model_hook=lambda _: {"role": "assistant"},
            )
            gateway.open_sync(
                run_id="run-1", session_id="session-1", generation=1,
                prime_source_root="/tmp/prime", workspace="/tmp/workspace",
            )
            self.assertEqual(gateway.prompt_sync("prompt-1"), {"lifecycle": "completed", "model_callback_count": 2, "tool_callback_count": 1})
            gateway.feedback_sync("exact-feedback")
            self.assertEqual(gateway.prompt_sync("prompt-2"), {"lifecycle": "completed", "model_callback_count": 4, "tool_callback_count": 2})
            gateway.close_sync()
