// Explicit provider-free integration probe; this is not part of portable npm test.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {createAppLevelTools,registerP7MemoryContext} from "../dist/ipython-extension.mjs";

const packageRoot = resolve(process.env.ASTERION_TEST_PI_PACKAGE_ROOT
  ?? "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent");
const native = await import(pathToFileURL(resolve(packageRoot,"dist/index.js")).href);
const ai = await import(pathToFileURL(resolve(packageRoot,"node_modules/@earendil-works/pi-ai/dist/index.js")).href);
const {loadExtensionFromFactory} = await import(pathToFileURL(resolve(packageRoot,"dist/core/extensions/loader.js")).href);
const revision = "sha256:" + "a".repeat(64);
const user = text => ({role:"user",content:text,timestamp:1});
const call = (id,name,arguments_={op:"notes"}) => ({type:"toolCall",id,name,arguments:arguments_});
const assistant = (...calls) => ({role:"assistant",content:calls,api:"openai-responses",provider:"openai",model:"probe",
  usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},
  stopReason:"toolUse",timestamp:2});
const toolResult = (id,name,value) => ({role:"toolResult",toolCallId:id,toolName:name,isError:false,...value,timestamp:3});
const current = "IMMUTABLE_DOCUMENT_RESEARCH_INSTRUCTIONS\nCURRENT_CHAPTER_5_BOARD";
const calls = [];
let hasNotes = false;
const runtime = native.createExtensionRuntime();
const factory = await loadExtensionFromFactory(pi => {
  assert.equal(registerP7MemoryContext(pi),true);
  for (const tool of createAppLevelTools({callMethod:async (id,method,params) => {
    calls.push({id,method,params});
    const commit = method === "workspace" && params.op === "notes";
    if (commit) hasNotes = true;
    return {status:commit ? "noted" : method === "workspace" ? "read" : "settled",
      ...(commit ? {notes_revision:revision} : {}),
      context_memory:{version:"asterion.prime-context-memory/v2",revision:hasNotes ? revision : null,
        content:current+(hasNotes ? "\nNOTES: selected findings" : "\nNo notes saved"),commit}};
  }})) pi.registerTool(tool);
},process.cwd(),native.createEventBus(),runtime,"<asterion-memory-probe>");
const session = native.SessionManager.inMemory(process.cwd());
session.appendMessage({role:"system",content:"PI_OWNED_SYSTEM_PROMPT",
  toolsAdded:[{name:"p7_workspace",description:"notes",parameters:{type:"object"}}],timestamp:0});
session.appendMessage(user("OPERATOR_TASK_INSTRUCTIONS"));
const runner = new native.ExtensionRunner([factory],runtime,process.cwd(),session,{});
const errors = [];
runner.onError(error => errors.push(error));
const workspace = native.wrapRegisteredTool(factory.tools.get("p7_workspace"),runner);
const planTool = native.wrapRegisteredTool(factory.tools.get("p7_execute_plan"),runner);

// Actual registered tool produces a trusted v2 snapshot before any note exists.
const readCall = call("state-read","p7_workspace",{op:"read"});
session.appendMessage(assistant(readCall));
const read = await workspace.execute(readCall.id,ai.validateToolArguments(workspace,readCall));
assert.equal(read.details.context_memory.revision,null);
assert.equal(read.details.context_memory.commit,false);
assert.doesNotMatch(read.content[0].text,/context_memory|CURRENT_CHAPTER_5_BOARD/);
session.appendMessage(toolResult(readCall.id,readCall.name,read));
let source = session.buildSessionContext().messages;
let projected = await runner.emitContext(source);
assert.match(JSON.stringify(native.convertToLlm(projected)),/No notes saved|CURRENT_CHAPTER_5_BOARD/);

// Installed Pi's argument validator and native tool wrapper accept the minimal plan.
const minimal = {plan_id:"minimal-plan",start:{run_id:"run",attempt_id:"attempt",level:1,
  sequence:0,observation_sha256:revision},steps:[{action:{name:"ACTION1",data:{}}}]};
const planCall = call("minimal-plan-tool","p7_execute_plan",minimal);
session.appendMessage(assistant(planCall));
const planned = await planTool.execute(planCall.id,ai.validateToolArguments(planTool,planCall));
assert.deepEqual(calls.find(item => item.id === planCall.id).params,minimal);
session.appendMessage(toolResult(planCall.id,planCall.name,planned));

for (let chapter = 1; chapter <= 4; chapter++) {
  session.appendMessage(assistant(call("chapter-"+chapter,"p7_workspace")));
  session.appendMessage(toolResult("chapter-"+chapter,"p7_workspace",
    {content:[{type:"text",text:"RAW_CHAPTER_"+chapter}],details:{}}));
}
for (let group = 0; group < 20; group++) {
  const id = "before-note-"+group;
  session.appendMessage(assistant(call(id,"p7_execute_plan")));
  session.appendMessage(toolResult(id,"p7_execute_plan",
    {content:[{type:"text",text:"BEFORE_NOTES_RESEARCH_"+group+" "+"x".repeat(8192)}],details:{}}));
}
source = session.buildSessionContext().messages;
assert.ok(Buffer.byteLength(JSON.stringify(source),"utf8")>96*1024);
projected = await runner.emitContext(source);
assert.deepEqual(projected.filter(message => message.customType !== "asterion_context_memory"),source,
  "research before any notes survives beyond the former 96 KiB trigger");
assert.match(JSON.stringify(projected),/No notes saved|BEFORE_NOTES_RESEARCH_0 /);
session.appendMessage(user("LATER_OPERATOR_CORRECTION"));
session.appendMessage(assistant(call("accepted-note","p7_workspace"),call("sibling","p7_execute_plan")));
const accepted = await workspace.execute("accepted-note",{op:"notes"});
session.appendMessage(toolResult("accepted-note","p7_workspace",accepted));
source = session.buildSessionContext().messages;
projected = await runner.emitContext(source);
assert.deepEqual(projected.filter(message => message.customType !== "asterion_context_memory"),source,
  "notes and a pending sibling preserve all research beyond the former trigger");
session.appendMessage(toolResult("sibling","p7_execute_plan",
  {content:[{type:"text",text:"SIBLING_RESULT"}],details:{}}));
source = session.buildSessionContext().messages;
projected = await runner.emitContext(source);
assert.match(JSON.stringify(projected),/RAW_CHAPTER_1|RAW_CHAPTER_4|SIBLING_RESULT/);
assert.equal(projected.filter(message => message.customType === "asterion_context_memory").length,1);

for (let group = 0; group < 20; group++) {
  const id = "large-"+group;
  session.appendMessage(assistant(call(id,"p7_execute_plan")));
  session.appendMessage(toolResult(id,"p7_execute_plan",
    {content:[{type:"text",text:"LARGE_EVIDENCE_"+group+" "+"x".repeat(8192)}],details:{}}));
}
session.appendMessage(user("PENDING_CURRENT_QUESTION"));
const rawBefore = structuredClone(session.getBranch());
source = session.buildSessionContext().messages;
projected = await runner.emitContext(source);
const modelView = native.convertToLlm(projected);
const serialized = JSON.stringify(modelView);
for (const text of ["PI_OWNED_SYSTEM_PROMPT","OPERATOR_TASK_INSTRUCTIONS","LATER_OPERATOR_CORRECTION",
  "IMMUTABLE_DOCUMENT_RESEARCH_INSTRUCTIONS","NOTES: selected findings","CURRENT_CHAPTER_5_BOARD",
  "LARGE_EVIDENCE_19","PENDING_CURRENT_QUESTION"]) assert.ok(serialized.includes(text),text);
for (const text of ["RAW_CHAPTER_1","RAW_CHAPTER_4","BEFORE_NOTES_RESEARCH_0 ","LARGE_EVIDENCE_0 "])
  assert.ok(serialized.includes(text),text);
assert.deepEqual(projected.filter(message => message.customType !== "asterion_context_memory"),source);
assert.deepEqual(projected[0].toolsAdded,source[0].toolsAdded);
assert.deepEqual(session.getBranch(),rawBefore,"native raw branch remains unchanged");
assert.deepEqual(errors,[]);
const restored = new native.ExtensionRunner([factory],runtime,process.cwd(),session,{});
const compacted = [{role:"system",content:"PI_OWNED_SYSTEM_PROMPT",timestamp:0},
  {role:"compactionSummary",summary:"NATIVE_RETAINED_SUMMARY",timestamp:4},
  {role:"branchSummary",summary:"NATIVE_BRANCH_RESEARCH",timestamp:5},...source.slice(-41)];
assert.ok(Buffer.byteLength(JSON.stringify(compacted),"utf8")>96*1024);
const restoredView = await restored.emitContext(compacted);
assert.deepEqual(restoredView.filter(message => message.customType !== "asterion_context_memory"),compacted);
const recovered = native.convertToLlm(restoredView);
assert.match(JSON.stringify(recovered),/CURRENT_CHAPTER_5_BOARD/);
assert.match(JSON.stringify(recovered),/NATIVE_RETAINED_SUMMARY/);
assert.match(JSON.stringify(recovered),/NATIVE_BRANCH_RESEARCH|LARGE_EVIDENCE_0 /);
assert.equal(restoredView.filter(message => message.customType === "asterion_context_memory").length,1);
const manifest = JSON.parse(readFileSync(resolve(packageRoot,"package.json"),"utf8"));
console.log(JSON.stringify({status:"pass",package:manifest.name,version:manifest.version,provider_calls:0,
  raw_messages:source.length,model_messages:modelView.length,state_before_notes:true,minimal_plan_validated:true,
  research_without_notes_retained:true,research_with_notes_retained:true,native_compaction_research_retained:true,
  user_corrections_retained:true,
  complete_sibling_group:true,system_and_tools_preserved:true,raw_branch_unchanged:true,restart_after_compaction:true}));
