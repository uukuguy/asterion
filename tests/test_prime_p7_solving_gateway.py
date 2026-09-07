from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


_CHILD = r'''const net=require("node:net"),fd=Number(process.argv[2]),s=new net.Socket({fd,readable:true,writable:true});let b=Buffer.alloc(0),out=0,id;
function c(v){if(v===null||typeof v!=="object")return JSON.stringify(v);if(Array.isArray(v))return`[${v.map(c).join(",")}]`;return`{${Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+c(v[k])).join(",")}}`}
function send(k,r,p){let x=Buffer.from(c({protocol:"asterion.prime-p7-solving-gateway/v1",...id,sequence:++out,request_id:r,kind:k,payload:p})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]))}
s.on("data",x=>{b=Buffer.concat([b,x]);while(b.length>=4){let n=b.readUInt32BE();if(b.length<n+4)return;let f=JSON.parse(b.subarray(4,n+4));b=b.subarray(n+4);id={run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation};if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"){send("compaction.accepted","compact-1",{replaced_messages:[{role:"user",content:[{type:"text",text:"solve"}]}],replacement_messages:[{role:"user",content:[{type:"text",text:"summary"}]}],summary_spans:[{kind:"history",transcript:"[User]: solve",previous_summary:null}]});send("command.result",f.request_id,{result:{lifecycle:"completed",usage:{input_tokens:9,output_tokens:4,total_tokens:13},assistant:{completed:true,stop_reason:"toolUse"},observations:{active_tool_names:["ipython"],compact_count:1,normal_model_callback_count:3,summary_model_callback_count:2,rlm_child_count:0,tool_call_count:4,solved_latched:true}}})}else if(f.kind==="cancel")send("command.result",f.request_id,{result:{lifecycle:"cancelled"}});else if(f.kind==="close"){send("command.result",f.request_id,{result:{lifecycle:"closed"}});s.end()}}});'''


class TestPrimeP7SolvingGateway(unittest.IsolatedAsyncioTestCase):
    async def test_frame_request_callback_token_cost_deadline_cancel_and_redaction_boundary(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_gateway import PrimeP7SolvingGateway, PrimeP7SolvingGatewayError
        from asterion.applications.prime_agent.operator import p7_solving_sdk_provider as subject
        with tempfile.TemporaryDirectory() as temporary:
            entrypoint = Path(temporary) / "bridge.js"
            entrypoint.write_text(_CHILD, encoding="utf-8")
            class Provider:
                def __init__(self) -> None:
                    self.transitions = []

                def __call__(self, _: object) -> object:
                    return {}

                def accept_compaction(self, **transition: object) -> None:
                    self.transitions.append(transition)

            provider = Provider()
            gateway = PrimeP7SolvingGateway(node_bin="node", entrypoint=entrypoint, deadline_seconds=5)
            gateway.bind(model_hook=provider, tool_hook=lambda _: {})
            await gateway.open(run_id="run", session_id="session", generation=1, prime_source_root="/tmp/prime", workspace="/tmp/workspace")
            result = await gateway.prompt("solve")
            self.assertEqual(result, {"lifecycle": "completed", "normal_model_callback_count": 3, "summary_model_callback_count": 2, "tool_callback_count": 4})
            self.assertEqual(provider.transitions, [{
                "replaced_messages": [{"role": "user", "content": [{"type": "text", "text": "solve"}]}],
                "replacement_messages": [{"role": "user", "content": [{"type": "text", "text": "summary"}]}],
                "summary_spans": [{"kind": "history", "transcript": "[User]: solve", "previous_summary": None}],
            }])
            witness = gateway.terminal_witness()
            self.assertEqual(dict(witness["cumulative"]), {"normal_model_callback_count": 3, "summary_model_callback_count": 2, "tool_callback_count": 4})
            await gateway.close()
            self.assertNotIn(temporary, repr(gateway))
            oversized = PrimeP7SolvingGateway(node_bin="node", entrypoint=entrypoint)
            oversized.bind(model_hook=lambda _: {}, tool_hook=lambda _: {})
            with self.assertRaises(PrimeP7SolvingGatewayError):
                oversized.open_sync(run_id="run", session_id="session", generation=1, prime_source_root="/" + "x" * 16777216, workspace="/tmp")
            self.assertIsNone(oversized.child_pid)
        provider = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "SENTINEL_SECRET", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        self.assertEqual(subject.P7_SOLVING_PROVIDER_REQUEST_BYTES, 8388608)
        self.assertEqual(subject.P7_SOLVING_PROVIDER_CALLBACK_LIMIT, 128)
        self.assertEqual(subject.P7_SOLVING_PROVIDER_INPUT_LIMIT, 2000000)
        self.assertEqual(subject.P7_SOLVING_PROVIDER_OUTPUT_LIMIT, 200000)
        self.assertEqual(subject.P7_SOLVING_PROVIDER_COST_LIMIT, 5000000)
        self.assertEqual(subject.P7_SOLVING_PROVIDER_DEADLINE_SECONDS, 3600)
        with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
            await provider(b"x" * (8388608 + 1))
        self.assertIsNone(provider._child_pid)
        from tests.test_prime_p7_solving_sdk_provider import _normal, _text_reply
        large = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        large_body = _normal([{"role": "user", "content": "x" * (140 * 1024)}])
        self.assertGreater(len(large_body), 128 * 1024)
        with mock.patch.object(subject, "_post_chat_completion", return_value=_text_reply("bounded")):
            await large(large_body)
        large.finalize()
        from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerTokenUsage
        for field, value in (("_calls", 128), ("_deadline", time.monotonic() - 1)):
            capped = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
            setattr(capped, field, value)
            with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
                await capped(_normal([{"role": "user", "content": "solve"}]))
            self.assertIsNone(capped._child_pid)
        for usage in (
            PrimeModelBrokerTokenUsage(2000000, 0, 0),
            PrimeModelBrokerTokenUsage(0, 200000, 0),
            PrimeModelBrokerTokenUsage(0, 0, 4961000),
        ):
            capped = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
            capped._provisional = usage
            with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
                await capped(_normal([{"role": "user", "content": "solve"}]))
            self.assertIsNone(capped._child_pid)
        with mock.patch.object(subject, "_post_chat_completion", side_effect=lambda *_: time.sleep(10)):
            active = asyncio.create_task(provider(_normal([{"role": "user", "content": "solve"}])))
            for _ in range(100):
                if provider._child_pid is not None:
                    break
                await asyncio.sleep(0.01)
            pid = provider._child_pid
            active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await active
        self.assertIsNone(provider._child_pid)
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        self.assertNotIn("SENTINEL_SECRET", repr(provider))


if __name__ == "__main__":
    unittest.main()
