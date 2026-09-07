from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
from typing import cast
import unittest
from unittest import mock


def _model() -> dict[str, object]:
    suffix = "00000000-0000-4000-8000-000000000001"
    provider = f"asterion-p7-solving-{suffix}"
    model = f"p7-solving-{suffix}"
    return {"api": provider, "baseUrl": "http://127.0.0.1:0", "contextWindow": 131072,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "input": ["text"],
            "maxTokens": 4096, "name": model, "provider": provider, "reasoning": False, "id": model}


def _normal(messages: list[dict[str, object]]) -> bytes:
    from asterion.applications.prime_agent.operator.p7_solving_sdk_provider import _canonical_json
    model = _model()
    return _canonical_json({"model": model, "context": {"systemPrompt": "system", "messages": messages, "tools": [{"name": "ipython", "description": "Persistent IPython; outputs and state persist.", "parameters": {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}}]},
                            "options": {"apiKey": "in-memory-solving-provider", "maxRetries": 0, "maxRetryDelayMs": 60000, "model": model, "serviceTier": "default", "sessionId": "session", "signal": {}, "toolExecution": "parallel", "transport": "auto"}}).encode()


def _summary(text: str, max_tokens: int = 4096) -> bytes:
    from asterion.applications.prime_agent.operator.p7_solving_sdk_provider import _canonical_json
    return _canonical_json({"model": _model(), "context": {"systemPrompt": "summarize", "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}]},
                            "options": {"apiKey": "in-memory-solving-provider", "maxTokens": max_tokens, "signal": {}}}).encode()


def _summary_prompt(messages: list[dict[str, object]], *, turn_prefix: bool) -> str:
    rendered: list[str] = []
    for message in messages:
        content = cast(list[dict[str, object]], message["content"])
        if message["role"] == "user":
            rendered.append("[User]: " + "".join(cast(str, part["text"]) for part in content))
        elif message["role"] == "assistant":
            calls = [part for part in content if part["type"] == "toolCall"]
            rendered.append("[Assistant tool calls]: " + "; ".join(
                f'{call["name"]}(code={json.dumps(cast(dict[str, object], call["arguments"])["code"])})' for call in calls
            ))
        else:
            rendered.append("[Tool result]: " + "".join(cast(str, part["text"]) for part in content))
    suffix = "This is the PREFIX of a turn that was too large to keep." if turn_prefix else "Summarize the conversation above."
    return "<conversation>\n" + "\n\n".join(rendered) + f"\n</conversation>\n\n{suffix}"


def _summary_transcript(source: str) -> str:
    return source.split("<conversation>\n", 1)[1].split("\n</conversation>", 1)[0]


def _compaction_replacement(history: str, turn_prefix: str) -> list[dict[str, object]]:
    merged = f"{history}\n\n---\n\n**Turn Context (split turn):**\n\n{turn_prefix}"
    return [{"role": "user", "content": [{"type": "text", "text": "The conversation history before this point was compacted into the following summary:\n\n<summary>\n" + merged + "\n</summary>"}]}]


def _tool_reply(call_id: str, code: str) -> dict[str, object]:
    return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "ipython", "arguments": json.dumps({"code": code}, separators=(",", ":"))}}]}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def _text_reply(text: str) -> dict[str, object]:
    return {"choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": None}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


async def _accept_compaction_through_gateway(
    provider: object,
    *,
    replaced_messages: list[dict[str, object]],
    replacement_messages: list[dict[str, object]],
    summary_spans: list[dict[str, object]],
) -> None:
    from asterion.applications.prime_agent.operator.p7_solving_gateway import PrimeP7SolvingGateway

    payload = json.dumps(
        {
            "replaced_messages": replaced_messages,
            "replacement_messages": replacement_messages,
            "summary_spans": summary_spans,
        },
        separators=(",", ":"),
    )
    child = f'''const net=require("node:net"),fd=Number(process.argv[2]),s=new net.Socket({{fd,readable:true,writable:true}});let b=Buffer.alloc(0),out=0,id,p={payload};
function c(v){{if(v===null||typeof v!=="object")return JSON.stringify(v);if(Array.isArray(v))return`[${{v.map(c).join(",")}}]`;return`{{${{Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+c(v[k])).join(",")}}}}`}}
function send(k,r,p){{let x=Buffer.from(c({{protocol:"asterion.prime-p7-solving-gateway/v1",...id,sequence:++out,request_id:r,kind:k,payload:p}})),h=Buffer.alloc(4);h.writeUInt32BE(x.length);s.write(Buffer.concat([h,x]))}}
s.on("data",x=>{{b=Buffer.concat([b,x]);while(b.length>=4){{let n=b.readUInt32BE();if(b.length<n+4)return;let f=JSON.parse(b.subarray(4,n+4));b=b.subarray(n+4);id={{run_id:f.run_id,session_id:f.session_id,runtime_id:f.runtime_id,generation:f.generation}};if(f.kind==="open")send("ready",f.request_id,{{}});else if(f.kind==="prompt"){{send("compaction.accepted","compact-1",p);send("command.result",f.request_id,{{result:{{lifecycle:"completed",usage:{{input_tokens:1,output_tokens:0,total_tokens:1}},assistant:{{completed:true,stop_reason:"toolUse"}},observations:{{active_tool_names:["ipython"],compact_count:1,normal_model_callback_count:1,summary_model_callback_count:1,rlm_child_count:0,tool_call_count:1,solved_latched:true}}}}}})}}else if(f.kind==="close"){{send("command.result",f.request_id,{{result:{{lifecycle:"closed"}}}});s.end()}}}}}});'''
    with tempfile.TemporaryDirectory() as temporary:
        entrypoint = Path(temporary) / "bridge.js"
        entrypoint.write_text(child, encoding="utf-8")
        gateway = PrimeP7SolvingGateway(node_bin="node", entrypoint=entrypoint, deadline_seconds=5)
        gateway.bind(model_hook=provider, tool_hook=lambda _: {})
        await gateway.open(
            run_id="run",
            session_id="session",
            generation=1,
            prime_source_root="/tmp/prime",
            workspace="/tmp/workspace",
        )
        await gateway.prompt("accept compaction")
        await gateway.close()


class TestP7SolvingSdkProvider(unittest.IsolatedAsyncioTestCase):
    async def test_compaction_summaries_serialize_finalize_and_dynamic_history_is_exact(self) -> None:
        from asterion.applications.prime_agent.operator import p7_solving_sdk_provider as subject
        provider = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "SENTINEL_SECRET", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        messages: list[dict[str, object]] = [{"role": "user", "content": [{"type": "text", "text": "solve"}]}]
        calls = 0
        def post(_config: object, payload: dict[str, object], _timeout: object) -> object:
            nonlocal calls
            calls += 1
            if "tools" not in payload:
                self.assertNotIn("tool_choice", payload)
                import time
                time.sleep(0.1)
                return _text_reply("summary-one" if "[User]: solve" in json.dumps(payload) else "summary-two")
            self.assertEqual(payload["tool_choice"], "auto")
            self.assertEqual(payload["temperature"], 0)
            return _tool_reply(f"call-{calls}", f"step_{calls}()")
        with mock.patch.object(subject, "_post_chat_completion", side_effect=post):
            for index in range(4):
                answer = json.loads(await provider(_normal(messages)))
                call = answer["content"][-1]
                messages += [answer, {"role": "toolResult", "toolCallId": call["id"], "toolName": "ipython", "content": [{"type": "text", "text": f"result-{index}"}], "isError": False}]
            one = asyncio.create_task(provider(_summary(_summary_prompt(messages[:3], turn_prefix=False))))
            two = asyncio.create_task(provider(_summary(_summary_prompt(messages[3:5], turn_prefix=True))))
            for _ in range(100):
                if provider._inflight == 2:
                    break
                await asyncio.sleep(0.001)
            with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
                provider.finalize()
            summaries = [json.loads(value) for value in await asyncio.gather(one, two)]
            replacement = _compaction_replacement(
                summaries[0]["content"][0]["text"], summaries[1]["content"][0]["text"]
            )
            retained = messages[5:]
            history_source = _summary_prompt(messages[:3], turn_prefix=False)
            turn_source = _summary_prompt(messages[3:5], turn_prefix=True)
            await _accept_compaction_through_gateway(
                provider,
                replaced_messages=messages,
                replacement_messages=replacement + retained,
                summary_spans=[
                    {"kind": "history", "transcript": _summary_transcript(history_source), "previous_summary": None},
                    {"kind": "turn-prefix", "transcript": _summary_transcript(turn_source), "previous_summary": None},
                ],
            )
            tampered = replacement + [*retained[:-1], {**retained[-1], "isError": True}]
            with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
                await provider(_normal(tampered))
            final = json.loads(await provider(_normal(replacement + retained)))
            self.assertEqual(final["stopReason"], "toolUse")
        usage = provider.finalize()
        self.assertEqual(provider.callback_counts(), {"normal": 5, "summary": 2})
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.cost_microunits), (65, 41, 273434))
        with self.assertRaises(subject.PrimeP7SolvingSdkProviderError):
            provider.finalize()
        self.assertNotIn("SENTINEL_SECRET", repr(provider))
        idle = subject.create_prime_p7_solving_sdk_provider({"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        idle_usage = idle.finalize()
        self.assertEqual((idle_usage.input_tokens, idle_usage.output_tokens, idle_usage.cost_microunits), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
