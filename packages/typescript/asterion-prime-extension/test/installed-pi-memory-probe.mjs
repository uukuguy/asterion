// Explicit provider-free integration probe; this is not part of portable npm test.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {createAppLevelTools,registerP7MemoryContext} from "../dist/ipython-extension.mjs";

const packageRoot = resolve(process.env.ASTERION_TEST_PI_PACKAGE_ROOT
  ?? "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent");
const native = await import(pathToFileURL(resolve(packageRoot,"dist/index.js")).href);
const {loadExtensionFromFactory} = await import(pathToFileURL(resolve(packageRoot,"dist/core/extensions/loader.js")).href);
const revision = "sha256:" + "a".repeat(64);
const user = text => ({role:"user",content:text,timestamp:1});
const call = (id,name) => ({type:"toolCall",id,name,arguments:{op:"notes"}});
const assistant = (...calls) => ({role:"assistant",content:calls,api:"openai-responses",provider:"openai",model:"probe",
  usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},
  stopReason:"toolUse",timestamp:2});
const toolResult = (id,name,value) => ({role:"toolResult",toolCallId:id,toolName:name,isError:false,...value,timestamp:3});
const current = "IMMUTABLE_DOCUMENT_RESEARCH_INSTRUCTIONS\nNOTES: selected findings\nCURRENT_CHAPTER_5_BOARD";
const runtime = native.createExtensionRuntime();
const factory = await loadExtensionFromFactory(pi => {
  assert.equal(registerP7MemoryContext(pi),true);
  for (const tool of createAppLevelTools({callMethod:async (_id,method) => method === "workspace"
    ? {status:"noted",notes_revision:revision,context_memory:{version:"asterion.prime-context-memory/v1",revision,content:current,commit:true}}
    : {status:"settled"}})) pi.registerTool(tool);
},process.cwd(),native.createEventBus(),runtime,"<asterion-memory-probe>");
const session = native.SessionManager.inMemory(process.cwd());
session.appendMessage({role:"system",content:"PI_OWNED_SYSTEM_PROMPT",toolsAdded:[{name:"p7_workspace",description:"notes",parameters:{type:"object"}}],timestamp:0});
session.appendMessage(user("OBSOLETE_INITIAL_BOARD"));
for (let chapter = 1; chapter <= 4; chapter++) {
  session.appendMessage(assistant(call("chapter-" + chapter,"p7_workspace")));
  session.appendMessage(toolResult("chapter-" + chapter,"p7_workspace",{content:[{type:"text",text:"RAW_CHAPTER_"+chapter}],details:{}}));
}
session.appendMessage(assistant(call("accepted-note","p7_workspace"),call("sibling","p7_execute_plan")));
const tool = factory.tools.get("p7_workspace");
const accepted = await tool.definition.execute("accepted-note",{op:"notes"});
assert.doesNotMatch(accepted.content[0].text,/context_memory|CURRENT_CHAPTER_5_BOARD/);
session.appendMessage(toolResult("accepted-note","p7_workspace",accepted));
const runner = new native.ExtensionRunner([factory],runtime,process.cwd(),session,{});
const errors = [];
runner.onError(error => errors.push(error));
let source = session.buildSessionContext().messages;
let projected = await runner.emitContext(source);
assert.deepEqual(projected,source,"pending sibling must prevent prefix deletion");
session.appendMessage(toolResult("sibling","p7_execute_plan",{content:[{type:"text",text:"SIBLING_RESULT"}],details:{}}));
session.appendMessage(user("PENDING_CURRENT_QUESTION"));
const rawBefore = structuredClone(session.getBranch());
source = session.buildSessionContext().messages;
projected = await runner.emitContext(source);
const modelView = native.convertToLlm(projected);
const serialized = JSON.stringify(modelView);
assert.match(serialized,/PI_OWNED_SYSTEM_PROMPT/);
assert.match(serialized,/IMMUTABLE_DOCUMENT_RESEARCH_INSTRUCTIONS/);
assert.match(serialized,/NOTES: selected findings/);
assert.match(serialized,/CURRENT_CHAPTER_5_BOARD/);
assert.match(serialized,/SIBLING_RESULT/);
assert.match(serialized,/PENDING_CURRENT_QUESTION/);
assert.doesNotMatch(serialized,/RAW_CHAPTER_|OBSOLETE_INITIAL_BOARD/);
assert.deepEqual(projected[0].toolsAdded,source[0].toolsAdded);
assert.deepEqual(session.getBranch(),rawBefore,"native raw branch remains unchanged");
assert.deepEqual(errors,[]);
const restored = new native.ExtensionRunner([factory],runtime,process.cwd(),session,{});
const compacted = [{role:"system",content:"PI_OWNED_SYSTEM_PROMPT",timestamp:0},
  {role:"compactionSummary",summary:"NATIVE_RETAINED_SUMMARY",timestamp:4},user("pending")];
const recovered = native.convertToLlm(await restored.emitContext(compacted));
assert.match(JSON.stringify(recovered),/CURRENT_CHAPTER_5_BOARD/);
assert.match(JSON.stringify(recovered),/NATIVE_RETAINED_SUMMARY/);
assert.equal(recovered.length,4);
const manifest = JSON.parse(readFileSync(resolve(packageRoot,"package.json"),"utf8"));
console.log(JSON.stringify({status:"pass",package:manifest.name,version:manifest.version,
  provider_calls:0,raw_messages:source.length,model_messages:modelView.length,
  complete_sibling_group:true,system_and_tools_preserved:true,raw_branch_unchanged:true,
  restart_after_compaction:true}));
