// Explicit provider-free integration probe; this is not part of portable npm test.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {createAppLevelTools,registerP7MemoryContext,registerProviderPrefixMetrics} from "../dist/p7-research-extension.mjs";

const packageRoot = resolve(process.env.ASTERION_TEST_PI_PACKAGE_ROOT
  ?? "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent");
const native = await import(pathToFileURL(resolve(packageRoot,"dist/index.js")).href);
const ai = await import(pathToFileURL(resolve(packageRoot,"node_modules/@earendil-works/pi-ai/dist/index.js")).href);
const {convertResponsesMessages}=await import(pathToFileURL(resolve(packageRoot,"node_modules/@earendil-works/pi-ai/dist/api/openai-responses-shared.js")).href);
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
const telemetry = [];
const providerTelemetry = [];
let hasNotes = false;
const runtime = native.createExtensionRuntime();
const factory = await loadExtensionFromFactory(pi => {
  // This legacy-v2 probe compares native history verbatim; capacity reminders
  // have dedicated hook tests and remain enabled in the primary probe below.
  assert.equal(registerP7MemoryContext(pi,numbers => telemetry.push(numbers),{enabled:false}),true);
  assert.equal(registerProviderPrefixMetrics(pi,numbers => providerTelemetry.push(numbers)),true);
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

// Same accepted state and appended cells must extend the entire previous provider input.
const prefixModel={id:"probe",provider:"openai",api:"openai-responses",reasoning:true,input:["text"]};
const providerInput=messages=>convertResponsesMessages(prefixModel,{messages:native.convertToLlm(messages)},new Set(["openai"]),
  {supportsMidConvoSystemMessages:false});
const previousProvider=providerInput(projected);
const previousPayload={model:"probe",input:previousProvider,prompt_cache_key:"provider-free-session"};
assert.equal(await runner.emitBeforeProviderRequest(previousPayload),previousPayload);
const cellCall=call("prefix-cell","ipython",{code:"1+1"});
session.appendMessage(assistant(cellCall));
session.appendMessage(toolResult(cellCall.id,cellCall.name,{content:[{type:"text",text:"2"}],details:{}}));
const afterCellSource=session.buildSessionContext().messages;
const afterCellView=await runner.emitContext(afterCellSource);
const afterCellProvider=providerInput(afterCellView);
assert.deepEqual(afterCellProvider.slice(0,previousProvider.length),previousProvider,
  "fixed state snapshot preserves the complete serialized provider input across a cell");
const nextPayload={...previousPayload,input:afterCellProvider};
assert.equal(await runner.emitBeforeProviderRequest(nextPayload),nextPayload);
assert.equal(providerTelemetry.length,2);
assert.equal(providerTelemetry[1].common_prefix_items,previousProvider.length);
assert.equal(providerTelemetry[1].common_prefix_bytes,Buffer.byteLength(JSON.stringify(previousProvider),"utf8")-1);
assert.equal(providerTelemetry[1].cache_key_changed,0);
assert.equal(providerTelemetry[1].tools_changed,0);

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
const snapshotIndex=projected.findIndex(message=>message.customType==="asterion_context_memory");
assert.equal(projected[snapshotIndex-1].toolCallId,"sibling","snapshot follows the complete admitted source group");
assert.equal(modelView[snapshotIndex].role,"user","Pi keeps its native custom-to-user conversion");
assert.match(JSON.stringify(modelView[snapshotIndex]),/CURRENT_CHAPTER_5_BOARD/);
assert.equal(modelView.at(-1).content,"PENDING_CURRENT_QUESTION");
assert.ok(telemetry.at(-1).current_snapshot_bytes>0);
assert.equal(telemetry.at(-1).requests,telemetry.length);
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
assert.equal(restoredView[3].customType,"asterion_context_memory");
assert.equal(recovered[3].role,"user");
// Navigating to a branch without trusted state must not inherit another branch's snapshot.
const otherSession=native.SessionManager.inMemory(process.cwd());
otherSession.appendMessage(user("OTHER_BRANCH_OPERATOR"));
const otherRunner=new native.ExtensionRunner([factory],runtime,process.cwd(),otherSession,{});
const otherSource=otherSession.buildSessionContext().messages;
const otherView=await otherRunner.emitContext(otherSource);
assert.deepEqual(otherView,otherSource);
assert.doesNotMatch(JSON.stringify(otherView),/CURRENT_CHAPTER_5_BOARD/);
assert.deepEqual(session.getBranch(),rawBefore);
// Normal NOTES v3 through the installed native tool wrapper and selected-session archive.
const primaryRuntime=native.createExtensionRuntime();
const primaryTelemetry=[];
const primaryFactory=await loadExtensionFromFactory(pi=>{
  registerP7MemoryContext(pi,value=>primaryTelemetry.push(value));
  for(const tool of createAppLevelTools({callMethod:async(id,method,params)=>{
    const commit=method==="workspace" && params.op==="notes";
    return {status:commit?"noted":"recorded",...(commit?{notes_revision:revision}:{}),
      environment_result_unknown:false,processing_blocked:false,actual_feedback:"ACTUAL_"+id,
      context_interaction:{version:"asterion.prime-context-interaction/v1",effect:"settled",feedback:"ordinary"},
      context_memory:{version:"asterion.prime-context-memory/v3",revision,commit,content:commit?"PRIMARY_TASK_AND_NOTES_AS_OF_BOARD":"NEW_STATE_PROPOSAL"}};
  }})) pi.registerTool(tool);
},process.cwd(),native.createEventBus(),primaryRuntime,"<asterion-primary-probe>");
const primarySession=native.SessionManager.inMemory(process.cwd());
primarySession.appendMessage({role:"system",content:"NATIVE_PRIMARY_SYSTEM",toolsAdded:[{name:"p7_workspace",description:"workspace",parameters:{type:"object"}}],timestamp:0});
primarySession.appendMessage(user("PRIMARY_EXACT_USER_CONSTRAINT"));
for(let index=0;index<7;index++) {
  const id="old-primary-"+index;
  primarySession.appendMessage(assistant(call(id,"p7_execute_plan")));
  primarySession.appendMessage(toolResult(id,"p7_execute_plan",{content:[{type:"text",text:"PRIMARY_RAW_"+index}],details:{}}));
}
const primaryRunner=new native.ExtensionRunner([primaryFactory],primaryRuntime,process.cwd(),primarySession,{});
const primaryErrors=[];primaryRunner.onError(error=>primaryErrors.push(error));
const primaryWorkspace=native.wrapRegisteredTool(primaryFactory.tools.get("p7_workspace"),primaryRunner);
const noteRequest={op:"notes",base_revision:revision,observation_ref:minimal.start,text:"Corrected useful findings"};
const primaryNoteCall=call("primary-note","p7_workspace",noteRequest);
primarySession.appendMessage(assistant(primaryNoteCall,call("primary-sibling","ipython",{code:"2+2"})));
const primaryNote=await primaryWorkspace.execute(primaryNoteCall.id,ai.validateToolArguments(primaryWorkspace,primaryNoteCall));
assert.equal(primaryNote.details.context_memory.version,"asterion.prime-context-memory/v3");
assert.equal(primaryNote.details.context_checkpoint.version,"asterion.prime-context-checkpoint/v1");
assert.doesNotMatch(primaryNote.content[0].text,/context_interaction|context_memory/);
primarySession.appendMessage(toolResult(primaryNoteCall.id,primaryNoteCall.name,primaryNote));
primarySession.appendMessage(toolResult("primary-sibling","ipython",{content:[{type:"text",text:"4"}],details:{}}));
let primaryView=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.doesNotMatch(JSON.stringify(primaryView),/PRIMARY_RAW_0|PRIMARY_RAW_4/);
assert.match(JSON.stringify(primaryView),/PRIMARY_RAW_5|PRIMARY_RAW_6|PRIMARY_EXACT_USER_CONSTRAINT|PRIMARY_TASK_AND_NOTES/);
assert.equal(primaryView.filter(message=>message.role==="system").length,1);
const nativeListCall=call("primary-list","p7_workspace",{op:"context_archive_list",limit:32});
primarySession.appendMessage(assistant(nativeListCall));
const nativeList=await primaryWorkspace.execute(nativeListCall.id,ai.validateToolArguments(primaryWorkspace,nativeListCall));
const listing=JSON.parse(nativeList.content[0].text);
assert.equal(listing.status,"ok");
const oldRef=listing.items.find(item=>item.role==="toolResult").ref;
primarySession.appendMessage(toolResult(nativeListCall.id,nativeListCall.name,nativeList));
const nativeReadCall=call("primary-read","p7_workspace",{op:"context_archive_read",ref:oldRef,limit:16384});
primarySession.appendMessage(assistant(nativeReadCall));
const nativeRead=await primaryWorkspace.execute(nativeReadCall.id,ai.validateToolArguments(primaryWorkspace,nativeReadCall));
assert.match(JSON.parse(nativeRead.content[0].text).text,/PRIMARY_RAW_0/);
primarySession.appendMessage(toolResult(nativeReadCall.id,nativeReadCall.name,nativeRead));
primaryView=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
const epochProviderInput=providerInput(primaryView);
const primaryPlanTool=native.wrapRegisteredTool(primaryFactory.tools.get("p7_execute_plan"),primaryRunner);
const advancingCall=call("primary-advance","p7_execute_plan",minimal);
primarySession.appendMessage(assistant(advancingCall));
const advancing=await primaryPlanTool.execute(advancingCall.id,ai.validateToolArguments(primaryPlanTool,advancingCall));
primarySession.appendMessage(toolResult(advancingCall.id,advancingCall.name,advancing));
const advancingView=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.deepEqual(providerInput(advancingView).slice(0,epochProviderInput.length),epochProviderInput);
assert.doesNotMatch(JSON.stringify(providerInput(advancingView)),/NEW_STATE_PROPOSAL/);
const beforePrimaryCompaction=primarySession.getBranch();
primarySession.appendCompaction("MIXED_NATIVE_PRIOR_RESEARCH",beforePrimaryCompaction.at(-1).id,100);
const compactedPrimary=primarySession.buildSessionContext().messages;
const rebuiltPrimary=await primaryRunner.emitContext(compactedPrimary);
assert.doesNotMatch(JSON.stringify(rebuiltPrimary),/MIXED_NATIVE_PRIOR_RESEARCH/);
assert.match(JSON.stringify(rebuiltPrimary),/PRIMARY_EXACT_USER_CONSTRAINT|PRIMARY_TASK_AND_NOTES|ACTUAL_primary-advance|primary-sibling/);
const reloadedPrimarySession=native.SessionManager.inMemory(process.cwd(),undefined,
  JSON.parse(JSON.stringify([primarySession.getHeader(),...primarySession.getEntries()])));
const reloadedPrimaryRunner=new native.ExtensionRunner([primaryFactory],primaryRuntime,process.cwd(),reloadedPrimarySession,{});
assert.deepEqual(await reloadedPrimaryRunner.emitContext(reloadedPrimarySession.buildSessionContext().messages),rebuiltPrimary);
assert.deepEqual(primaryErrors,[]);
// Native retry omission shape: no model/provider calls, raw evidence stays intact.
const failedAttempt={...assistant(),stopReason:'error',content:[{type:'text',text:'FAILED_PROVIDER_ATTEMPT'}]};
const failedId=primarySession.appendMessage(failedAttempt);
primarySession.appendContextEdit(failedId,null);
const afterOmission=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.equal(primaryTelemetry.at(-1).projection_status,'primary');
assert.doesNotMatch(JSON.stringify(afterOmission),/FAILED_PROVIDER_ATTEMPT/);
assert.deepEqual(primarySession.getEntry(failedId).message,failedAttempt);
const newNoteCall=call('after-omission-note','p7_workspace',noteRequest);
primarySession.appendMessage(assistant(newNoteCall));
const newNote=await primaryWorkspace.execute(newNoteCall.id,ai.validateToolArguments(primaryWorkspace,newNoteCall));
assert.equal(newNote.details.context_checkpoint.source_tool_call_id,newNoteCall.id);
primarySession.appendMessage(toolResult(newNoteCall.id,newNoteCall.name,newNote));
const afterNewNote=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.equal(primaryTelemetry.at(-1).projection_status,'primary');
assert.doesNotMatch(JSON.stringify(afterNewNote),/FAILED_PROVIDER_ATTEMPT/);
assert.match(JSON.stringify(afterNewNote),/PRIMARY_EXACT_USER_CONSTRAINT/);
// Run the actual native loop and retry producer using a synthetic stream only.
// Failed responses can retain partial calls; neither native execution nor bridge runs.
const {runAgentLoop}=await import(pathToFileURL(resolve(packageRoot,"node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js")).href);
let partialToolExecutions=0, syntheticStreamCalls=0;
const partialAttempt={...assistant(call('failed-partial-call','p7_execute_plan',{incomplete:true})),
  stopReason:'error',errorMessage:'WebSocket closed 1000'};
const partialEvents=[];
const partialTools=createAppLevelTools({callMethod:async()=>{
  partialToolExecutions++;throw new Error('Failed response dispatched to bridge');
}});
await runAgentLoop([user('SYNTHETIC_RETRY_PROMPT')],{messages:[],tools:partialTools},
  {model:{id:'probe',api:'openai-responses',provider:'openai'},convertToLlm:native.convertToLlm},
  event=>{partialEvents.push(event);},undefined,()=>{
    syntheticStreamCalls++;
    const stream=new ai.EventStream(event=>event.type==='error',event=>event.error);
    stream.push({type:'start',partial:partialAttempt});
    stream.push({type:'toolcall_start',contentIndex:0,partial:partialAttempt});
    stream.push({type:'error',reason:'error',error:partialAttempt});
    return stream;
  });
assert.equal(syntheticStreamCalls,1);
assert.equal(partialToolExecutions,0);
assert.equal(partialEvents.filter(event=>event.type.startsWith('tool_execution')).length,0);
assert.deepEqual(partialEvents.find(event=>event.type==='turn_end').toolResults,[]);
const persistedPartial=partialEvents.find(event=>event.type==='message_end' && event.message.role==='assistant').message;
const partialId=primarySession.appendMessage(persistedPartial);
const recovery={sessionManager:primarySession,agent:{state:{messages:primarySession.buildSessionContext().messages}},
  _entryIdsByMessage:new WeakMap(),_retryAttempt:0,
  settingsManager:{getRetrySettings:()=>({enabled:true,maxRetries:1,baseDelayMs:0,maxDelayMs:0})},
  _emit:event=>partialEvents.push(event),_refreshFinalizedContext:()=>{},
  _findPersistedMessageEntryId:native.AgentSession.prototype._findPersistedMessageEntryId,
  _omitRecoveryAttempt:native.AgentSession.prototype._omitRecoveryAttempt};
assert.equal(await native.AgentSession.prototype._prepareRetry.call(recovery,persistedPartial),true);
assert.equal(primarySession.getBranch().at(-1).type,'context_edit');
assert.equal(primarySession.getBranch().at(-1).targetId,partialId);
assert.equal(primarySession.getBranch().at(-1).replacement,null);
const partialView=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.equal(primaryTelemetry.at(-1).projection_status,'primary');
assert.doesNotMatch(JSON.stringify(partialView),/failed-partial-call/);
assert.deepEqual(primarySession.getEntry(partialId).message,persistedPartial);
const partialNoteCall=call('after-partial-note','p7_workspace',noteRequest);
primarySession.appendMessage(assistant(partialNoteCall));
const partialNote=await primaryWorkspace.execute(partialNoteCall.id,ai.validateToolArguments(primaryWorkspace,partialNoteCall));
assert.equal(partialNote.details.context_checkpoint.coverage_through_entry_id,partialId);
primarySession.appendMessage(toolResult(partialNoteCall.id,partialNoteCall.name,partialNote));
const afterPartialNote=await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.equal(primaryTelemetry.at(-1).projection_status,'primary');
assert.doesNotMatch(JSON.stringify(afterPartialNote),/failed-partial-call/);
assert.match(JSON.stringify(afterPartialNote),/PRIMARY_EXACT_USER_CONSTRAINT/);
// The earlier diagnosis witness used successful prose, which must remain unsupported.
const successfulId=primarySession.appendMessage({...assistant(),stopReason:'stop',content:[{type:'text',text:'SUCCESSFUL_PROSE'}]});
primarySession.appendContextEdit(successfulId,null);
await primaryRunner.emitContext(primarySession.buildSessionContext().messages);
assert.equal(primaryTelemetry.at(-1).projection_status,'primary-unavailable');
assert.equal(primaryTelemetry.at(-1).refusal_reason,'context-edit-target-stop');
assert.deepEqual(primaryErrors,[]);
const manifest = JSON.parse(readFileSync(resolve(packageRoot,"package.json"),"utf8"));
console.log(JSON.stringify({status:"pass",package:manifest.name,version:manifest.version,provider_calls:0,
  raw_messages:source.length,model_messages:modelView.length,state_before_notes:true,minimal_plan_validated:true,
  research_without_notes_retained:true,research_with_notes_retained:true,native_compaction_research_retained:true,
  user_corrections_retained:true,
  complete_sibling_group:true,system_and_tools_preserved:true,raw_branch_unchanged:true,restart_after_compaction:true,
  snapshot_after_state_group:true,snapshot_fixed_across_computation:true,
  actual_provider_event_numeric_observation:true,actual_provider_input_append_prefix:true,snapshot_native_user_conversion:true,selected_branch_isolated:true,
  normal_notes_v3_primary:true,native_archive_read:true,primary_actual_plan_append_prefix:true,primary_compaction_reload:true,final_extension_view_numeric_telemetry:true,
  failed_partial_call_zero_dispatch:true,failed_partial_call_native_retry_primary:true,
  failed_no_call_omission_primary:true,new_notes_after_omission_primary:true,successful_prose_edit_rejected:true}));
