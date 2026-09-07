import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { createConnection, createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const PROTOCOL = "asterion.prime-p7-solving-gateway/v1";
const identity = { run_id: "run-1", session_id: "session-1", runtime_id: "prime.agent", generation: 1 };
function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function framed(value) {
  const body = Buffer.from(canonical(value)); const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length); return Buffer.concat([header, body]);
}
async function readFrame(socket, state) {
  while (state.buffer.length < 4) state.buffer = Buffer.concat([state.buffer, await once(socket, "data").then(([x]) => x)]);
  const size = state.buffer.readUInt32BE();
  while (state.buffer.length < size + 4) state.buffer = Buffer.concat([state.buffer, await once(socket, "data").then(([x]) => x)]);
  const body = state.buffer.subarray(4, size + 4); state.buffer = state.buffer.subarray(size + 4);
  return JSON.parse(body.toString("utf8"));
}
async function fakePrimeRoot() {
  const root = await mkdtemp(join(tmpdir(), "asterion-fake-prime-"));
  await mkdir(join(root, "packages/coding-agent/dist/core"), { recursive: true });
  await mkdir(join(root, "node_modules/typebox/build"), { recursive: true });
  await mkdir(join(root, "node_modules/@earendil-works/pi-ai/dist/utils"), { recursive: true });
  await writeFile(join(root, "package.json"), `{"type":"module"}`);
  await writeFile(join(root, "node_modules/typebox/package.json"), `{"type":"module"}`);
  await writeFile(join(root, "node_modules/@earendil-works/pi-ai/package.json"), `{"type":"module"}`);
  await writeFile(join(root, "node_modules/typebox/build/index.mjs"), `export const Type={Object:(properties)=>({type:"object",required:Object.keys(properties),properties}),String:()=>({type:"string"})};`);
  await writeFile(join(root, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js"), `export function createAssistantMessageEventStream(){let done;const p=new Promise(r=>{done=r});return{push(e){if(e?.type==="done")done(e.message)},async result(){return p},async*[Symbol.asyncIterator](){}}}`);
  await writeFile(join(root, "packages/coding-agent/dist/core/auth-storage.js"), `export const AuthStorage={inMemory:()=>({setRuntimeApiKey(){}})};`);
  await writeFile(join(root, "packages/coding-agent/dist/core/session-manager.js"), `export const SessionManager={inMemory:(workspace)=>({workspace})};`);
  await writeFile(join(root, "packages/coding-agent/dist/core/model-registry.js"), `let providerConfig;export const ModelRegistry={inMemory:()=>({registerProvider(_provider,config){providerConfig=config},unregisterProvider(){providerConfig=undefined},find(){return providerConfig.models[0]}})};export function streamSimple(model,context,options){return providerConfig.streamSimple(model,context,options)}`);
  await writeFile(join(root, "packages/coding-agent/dist/core/resource-loader.js"), `export class DefaultResourceLoader{async reload(){}}`);
  await writeFile(join(root, "packages/coding-agent/dist/core/settings-manager.js"), `export const SettingsManager={inMemory:(settings)=>({settings})};`);
  await writeFile(join(root, "packages/coding-agent/dist/core/sdk.js"), `
import {streamSimple} from "./model-registry.js";
export async function createAgentSession({model}){
  const listeners=new Set();
  const before=[{role:"user",content:[{type:"text",text:"solve"}]}];
  const after=[{role:"user",content:[{type:"text",text:"The conversation history before this point was compacted into the following summary:\\n\\n<summary>\\nsummary text\\n</summary>"}]}];
  const session={
    agent:{state:{messages:[]}},
    getActiveToolNames(){return ["ipython"]},
    subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener)},
    async prompt(){
      session.agent.state.messages=before;
      for(const listener of listeners) listener({type:"compaction_start",reason:"threshold"});
      const stream=streamSimple(model,{systemPrompt:"summarize",messages:[{role:"user",content:[{type:"text",text:"<conversation>\\n[User]: solve\\n</conversation>\\n\\nSummarize the conversation above."}]}]},{apiKey:"in-memory-solving-provider",maxTokens:4096,signal:{}});
      await stream.result();
      session.agent.state.messages=after;
      for(const listener of listeners) listener({type:"compaction_end",reason:"threshold",result:{summary:"summary text",firstKeptEntryId:"kept",tokensBefore:1},aborted:false,willRetry:false});
    },
    async waitForIdle(){},
    requestAbort(){},
    async disposeAsync(){}
  };
  return {session};
}`);
  return root;
}

test("bridge preserves two sibling IPython calls in source order and stops after their solved turn", async () => {
  const { P7SolvingBridge } = await import("../dist/src/p7-solving-bridge.js");
  const server = createServer(); server.listen(0, "127.0.0.1"); await once(server, "listening");
  const connected = once(server, "connection");
  const client = createConnection({ port: server.address().port, host: "127.0.0.1" });
  await once(client, "connect"); const [socket] = await connected;
  const run = new P7SolvingBridge(socket).run();
  const state = { buffer: Buffer.alloc(0), input: 0 };
  const send = (kind, request_id, payload) => client.write(framed({ protocol: PROTOCOL, ...identity, sequence: ++state.input, request_id, kind, payload }));
  send("open", "open-1", { prime_source_root: `${process.cwd()}/../../../3th-party/prime-agent`, workspace: process.cwd() });
  assert.equal((await readFrame(client, state)).kind, "ready");
  send("prompt", "prompt-1", { prompt: "solve" });
  const model = await readFrame(client, state); assert.equal(model.kind, "model.request");
  const message = {
    role: "assistant", api: "anthropic-messages", provider: "test", model: "test",
    content: [
      { type: "text", text: "first" },
      { type: "toolCall", id: "original-a", name: "ipython", arguments: { code: "a()" } },
      { type: "text", text: "between" },
      { type: "toolCall", id: "original-b", name: "ipython", arguments: { code: "b()" } },
    ],
    usage: { input: 7, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 12,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "toolUse", timestamp: 0,
  };
  send("model.response", model.request_id, { message });
  const first = await readFrame(client, state);
  assert.deepEqual(first.payload, { tool_call_id: "original-a", code: "a()" });
  send("tool.response", first.request_id, { result: { content: [{ type: "text", text: "a-result" }], details: { broker_terminal: "ACTIVE" }, isError: false } });
  const second = await readFrame(client, state);
  assert.deepEqual(second.payload, { tool_call_id: "original-b", code: "b()" });
  send("tool.response", second.request_id, { result: { content: [{ type: "text", text: "b-result" }], details: { broker_terminal: "LEVEL_SOLVED" }, isError: false } });
  const done = await readFrame(client, state);
  assert.equal(done.kind, "command.result");
  assert.deepEqual(done.payload.result.observations, {
    active_tool_names: ["ipython"], compact_count: 0,
    normal_model_callback_count: 1, summary_model_callback_count: 0,
    rlm_child_count: 0, tool_call_count: 2, solved_latched: true,
  });
  send("close", "close-1", {}); assert.equal((await readFrame(client, state)).kind, "command.result");
  await run; client.destroy(); server.close();
});

test("bridge emits exact accepted compaction transitions from Prime session events", async () => {
  const { P7SolvingBridge } = await import("../dist/src/p7-solving-bridge.js");
  const server = createServer(); server.listen(0, "127.0.0.1"); await once(server, "listening");
  const connected = once(server, "connection");
  const client = createConnection({ port: server.address().port, host: "127.0.0.1" });
  await once(client, "connect"); const [socket] = await connected;
  const run = new P7SolvingBridge(socket).run();
  const state = { buffer: Buffer.alloc(0), input: 0 };
  const send = (kind, request_id, payload) => client.write(framed({ protocol: PROTOCOL, ...identity, sequence: ++state.input, request_id, kind, payload }));
  send("open", "open-1", { prime_source_root: await fakePrimeRoot(), workspace: process.cwd() });
  assert.equal((await readFrame(client, state)).kind, "ready");
  send("prompt", "prompt-1", { prompt: "solve" });
  const model = await readFrame(client, state);
  assert.equal(model.kind, "model.request");
  assert.equal(Array.isArray(model.payload.context.tools), false);
  send("model.response", model.request_id, {
    message: {
      role: "assistant", api: "anthropic-messages", provider: "test", model: "test",
      content: [{ type: "text", text: "summary text" }],
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      stopReason: "stop", timestamp: 0,
    },
  });
  const compaction = await readFrame(client, state);
  assert.equal(compaction.kind, "compaction.accepted");
  assert.deepEqual(compaction.payload, {
    replaced_messages: [{ role: "user", content: [{ type: "text", text: "solve" }] }],
    replacement_messages: [{ role: "user", content: [{ type: "text", text: "The conversation history before this point was compacted into the following summary:\n\n<summary>\nsummary text\n</summary>" }] }],
    summary_spans: [{ kind: "history", transcript: "[User]: solve", previous_summary: null }],
  });
  assert.equal((await readFrame(client, state)).kind, "command.result");
  send("close", "close-1", {}); assert.equal((await readFrame(client, state)).kind, "command.result");
  await run; client.destroy(); server.close();
});
