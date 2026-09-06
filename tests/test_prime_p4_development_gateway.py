"""Focused contract tests for the private P4 inherited-FD gateway."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest


_CHILD = r"""
const net=require("node:net"),s=new net.Socket({fd:+process.argv[2],readable:true,writable:true});
let b=Buffer.alloc(0),out=0,i,phase="open",models=0,tools=0,active;
const c=v=>v===null||["string","boolean","number"].includes(typeof v)?JSON.stringify(v):Array.isArray(v)?"["+v.map(c).join(",")+"]":"{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+c(v[k])).join(",")+"}";
function send(kind,request_id,payload){const x=Buffer.from(c({protocol:"asterion.prime-p4-development-gateway/v1",...i,sequence:++out,request_id,kind,payload})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]));}
const candidate={active_session_id:"active-1",session_id:"native-1",cursor:{generation:"gen-1",sequence:7},transcript_sha256:"sha256:"+"a".repeat(64),tree_sha256:"sha256:"+"b".repeat(64),artifact_sha256:"sha256:"+"c".repeat(64),settled_model_callback_count:2,settled_tool_callback_count:1};
function model(){send("model.request","model-"+(models+1),{model:{},context:{},options:{}})}
function done(){if(phase==="prompt1"){phase="recover";send("command.result",active,{result:{checkpoint_candidate:candidate}})}else if(phase==="compact"){phase="prompt2";send("command.result",active,{result:{compact_called:true,succeeded:true,start_count:1,end_count:1,new_entry_count:1,active_path_sha256:"sha256:"+"d".repeat(64),first_kept_entry_id_sha256:"sha256:"+"e".repeat(64),tokens_before:3}})}else {phase="close";send("command.result",active,{result:{lifecycle:"completed",model_callback_count:5,tool_callback_count:2}})}}
function frame(f){i||={run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation}; if(f.kind==="open")send("ready",f.request_id,{});else if(f.kind==="prompt"){phase=phase==="open"?"prompt1":"prompt2";active=f.request_id;model()}else if(f.kind==="model.response"){models++;if(models===1||models===4){tools++;send("tool.request","tool-"+tools,{tool_call_id:"call-"+tools,code:"private"})}else done()}else if(f.kind==="tool.response")model();else if(f.kind==="recover"){phase="compact";send("command.result",f.request_id,{result:{active_session_id:"active-1",session_id:"native-1",from_cursor:candidate.cursor,to_cursor:candidate.cursor,snapshot_cursor:candidate.cursor}})}else if(f.kind==="compact"){active=f.request_id;model()}else if(f.kind==="cancel"){send("command.result",f.request_id,{result:{lifecycle:"cancelled"}})}else if(f.kind==="close"){send("command.result",f.request_id,{result:{lifecycle:"closed",model_callback_count:5,tool_callback_count:2,active_session_id_sha256:"sha256:"+"a".repeat(64),session_id_sha256:"sha256:"+"b".repeat(64),cursor_sha256:"sha256:"+"c".repeat(64)}});s.end();}}
s.on("data",x=>{b=Buffer.concat([b,x]);while(b.length>=4&&b.length>=4+b.readUInt32BE()){const n=b.readUInt32BE(),f=JSON.parse(b.subarray(4,4+n));b=b.subarray(4+n);frame(f)}});
"""

_BAD_IDENTITY_CHILD = _CHILD.replace(
    "...i,sequence:++out", "...i,generation:i.generation+1,sequence:++out"
)
_BAD_CURSOR_CHILD = _CHILD.replace(
    "to_cursor:candidate.cursor,snapshot_cursor:candidate.cursor",
    'to_cursor:{generation:"gen-1",sequence:8},snapshot_cursor:{generation:"gen-1",sequence:8}',
)


class TestPrimeP4DevelopmentGateway(unittest.IsolatedAsyncioTestCase):
    async def test_runs_fixed_p4_flow_with_private_checkpoint_readback(self) -> None:
        from asterion.applications.prime_agent.operator.p4_development_gateway import (
            PrimeP4DevelopmentGateway,
        )

        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_CHILD, encoding="utf-8")
            callbacks: list[str] = []
            gateway = PrimeP4DevelopmentGateway(
                node_bin="node",
                entrypoint=entry,
                model_hook=lambda _: callbacks.append("model") or {"role": "assistant"},
                tool_hook=lambda _: callbacks.append("tool") or {"ok": True},
            )
            await gateway.open(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root=temporary,
                workspace=temporary,
            )
            first = await gateway.prompt("private-first")
            self.assertEqual(first["checkpoint_candidate"]["cursor"]["sequence"], 7)
            recovered = await gateway.recover()
            self.assertEqual(recovered["to_cursor"]["sequence"], 7)
            await gateway.compact()
            await gateway.prompt("private-second")
            await gateway.close()
            self.assertEqual(
                callbacks, ["model", "tool", "model", "model", "model", "tool", "model"]
            )
            self.assertIsNone(gateway.child_pid)

    async def test_rejects_identity_drift_before_native_effect(self) -> None:
        from asterion.applications.prime_agent.operator.p4_development_gateway import (
            PrimeP4DevelopmentGateway,
            PrimeP4DevelopmentGatewayError,
        )

        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_BAD_IDENTITY_CHILD, encoding="utf-8")
            gateway = PrimeP4DevelopmentGateway(node_bin="node", entrypoint=entry)
            with self.assertRaises(PrimeP4DevelopmentGatewayError):
                await gateway.open(
                    run_id="run-1",
                    session_id="session-1",
                    generation=1,
                    prime_source_root=temporary,
                    workspace=temporary,
                )
            self.assertIsNone(gateway.child_pid)

    async def test_rejects_cursor_drift_before_compact(self) -> None:
        from asterion.applications.prime_agent.operator.p4_development_gateway import (
            PrimeP4DevelopmentGateway,
            PrimeP4DevelopmentGatewayError,
        )

        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_BAD_CURSOR_CHILD, encoding="utf-8")
            gateway = PrimeP4DevelopmentGateway(
                node_bin="node",
                entrypoint=entry,
                model_hook=lambda _: {"role": "assistant"},
                tool_hook=lambda _: {"ok": True},
            )
            await gateway.open(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root=temporary,
                workspace=temporary,
            )
            await gateway.prompt("private-first")
            with self.assertRaises(PrimeP4DevelopmentGatewayError):
                await gateway.recover()
            self.assertIsNone(gateway.child_pid)

    async def test_cancel_reaps_child(self) -> None:
        from asterion.applications.prime_agent.operator.p4_development_gateway import (
            PrimeP4DevelopmentGateway,
        )

        with tempfile.TemporaryDirectory() as temporary:
            entry = Path(temporary) / "bridge.js"
            entry.write_text(_CHILD, encoding="utf-8")
            gateway = PrimeP4DevelopmentGateway(
                node_bin="node", entrypoint=entry, deadline_seconds=10
            )
            await gateway.open(
                run_id="run-1",
                session_id="session-1",
                generation=1,
                prime_source_root=temporary,
                workspace=temporary,
            )
            self.assertEqual(await gateway.cancel(), {"lifecycle": "cancelled"})
            self.assertIsNone(gateway.child_pid)


if __name__ == "__main__":
    unittest.main()
