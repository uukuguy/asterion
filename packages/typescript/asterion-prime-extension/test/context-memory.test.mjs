import assert from "node:assert/strict";
import test from "node:test";
import {mkdtempSync,openSync,readFileSync,writeFileSync,rmSync,closeSync,fstatSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {Check} from "typebox/value";
import * as extension from "../dist/p7-research-extension.mjs";

const revision = "sha256:" + "a".repeat(64);
const nextRevision = "sha256:" + "b".repeat(64);
const user = text => ({role:"user",content:text,timestamp:1});
const assistant = (...ids) => ({role:"assistant",content:ids.map(id => ({type:"toolCall",id,name:"document_note",arguments:{}})),timestamp:2});
const result = (id,text="accepted") => ({role:"toolResult",toolCallId:id,toolName:"document_note",isError:false,content:[{type:"text",text}],timestamp:3});
const checkpoint = {revision,anchorToolCallId:"note",content:"Document research instructions\nNOTES: selected findings\nCurrent document: chapter 5"};
const history = () => [user("PINNED_TASK"),assistant("old"),result("old"),assistant("note","sibling"),result("note"),result("sibling"),user("pending correction")];
const longHistory = (count=20,size=8192) => [user("PINNED_TASK"),...Array.from({length:count},(_,index) => [
  {role:"custom",customType:"observation",content:"grounding-"+index,timestamp:index},
  assistant("group-"+index),result("group-"+index,"RAW_GROUP_"+index+" "+"x".repeat(size)),
]).flat()];
const envelope = (commit=true,selectedRevision=revision,content=checkpoint.content,version="asterion.prime-context-memory/v2") => ({version,revision:selectedRevision,content,commit});
const snapshotOf = projected => projected.messages.find(message => message.customType === "asterion_context_memory");

test("accepted notes preserve complete history and do not mutate evidence", () => {
  const messages = history();
  const original = structuredClone(messages);
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"retained");
  assert.equal(projected.outcome.removed_messages,0);
  assert.equal(snapshotOf(projected).content,checkpoint.content);
  assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),messages);
  assert.deepEqual(messages,original);
});

test("large research history survives notes replacement without an extension window", () => {
  const messages = longHistory();
  messages.splice(16,0,user("LATER_OPERATOR_CORRECTION"));
  const original = structuredClone(messages);
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"retained");
  assert.ok(projected.outcome.history_bytes>96*1024);
  assert.equal(projected.outcome.retained_history_bytes,projected.outcome.history_bytes);
  assert.equal(projected.outcome.removed_messages,0);
  assert.equal(projected.outcome.retained_messages,messages.length);
  assert.equal(Object.hasOwn(projected.outcome,"retained_complete_units"),false);
  assert.equal(Object.hasOwn(projected.outcome,"pinned_messages"),false);
  assert.match(JSON.stringify(projected.messages),/RAW_GROUP_19|grounding-19/);
  assert.match(JSON.stringify(projected.messages),/RAW_GROUP_0 /);
  assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),messages);
  assert.deepEqual(projected.messages.filter(message => message.role === "user"),[user("PINNED_TASK"),user("LATER_OPERATOR_CORRECTION")]);
  for (const message of projected.messages.filter(message => message.role === "assistant")) {
    const id = message.content[0].id;
    assert.ok(projected.messages.some(result => result.toolCallId === id));
    const index = Number(id.split("-")[1]);
    assert.ok(projected.messages.some(message => message.content === "grounding-"+index));
  }
  assert.deepEqual(messages,original);
  const changedNote = extension.projectMemoryContext(messages,{revision:nextRevision,content:"new notes"});
  assert.deepEqual(changedNote.messages.filter(message => message.customType !== "asterion_context_memory"),
    projected.messages.filter(message => message.customType !== "asterion_context_memory"));
});

test("private result metadata and provider usage do not count as model history", () => {
  const messages = history();
  messages[2].details = {private:"x".repeat(256*1024)};
  messages[1].usage = {private:"x".repeat(256*1024)};
  assert.equal(extension.projectMemoryContext(messages,checkpoint).outcome.status,"retained");
});

test("pending or irregular tool groups stay untouched without a window boundary decision", () => {
  for (const messages of [
    [...history(),result("note")],
    [user("old"),assistant("earlier"),assistant("note"),result("note"),result("earlier")],
    [user("old"),assistant("note","note"),result("note")],
    [user("old"),assistant("note"),{...result("note"),toolName:"wrong_tool"}],
  ]) {
    const original = structuredClone(messages);
    const projected = extension.projectMemoryContext(messages,checkpoint);
    assert.equal(projected.outcome.status,"retained");
    assert.equal(projected.outcome.removed_messages,0);
    assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),original);
    assert.deepEqual(messages,original);
  }
});

test("large instructions evidence and every pending sibling survive snapshot refresh", () => {
  const messages = [...longHistory(4,32*1024),assistant("pending","sibling"),result("pending","PENDING_RESULT")];
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"retained");
  assert.equal(projected.outcome.removed_messages,0);
  assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),messages);
  assert.deepEqual(projected.messages.slice(-3,-1),messages.slice(-2));
  assert.match(JSON.stringify(projected.messages),/RAW_GROUP_3|RAW_GROUP_2|PENDING_RESULT/);
  assert.match(JSON.stringify(projected.messages),/RAW_GROUP_0 /);
  const pinned = extension.projectMemoryContext([user("x".repeat(100*1024)),...history()],checkpoint);
  assert.equal(pinned.outcome.status,"retained");
  assert.equal(pinned.messages.find(message => message.role === "user").content.length,100*1024);
});

test("native compaction and branch summaries retain large research history and one current snapshot", () => {
  const messages = [{role:"system",content:"native system",timestamp:0},
    {role:"compactionSummary",summary:"archive summary",timestamp:4},
    {role:"branchSummary",summary:"branch research",timestamp:5},...longHistory(),user("pending question")];
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"retained");
  assert.ok(projected.outcome.history_bytes>96*1024);
  assert.equal(projected.messages[0],messages[0]);
  assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),messages);
  assert.deepEqual(extension.projectMemoryContext(projected.messages,checkpoint).messages,projected.messages);
  const refreshed = extension.projectMemoryContext(projected.messages,{revision:nextRevision,content:"updated state"});
  assert.equal(refreshed.messages.filter(message => message.customType === "asterion_context_memory").length,1);
  assert.equal(snapshotOf(refreshed).content,"updated state");
  assert.deepEqual(refreshed.messages.filter(message => message.customType !== "asterion_context_memory"),messages);
});

test("v2 state without notes retains large history and old v1 refreshes remain revision-bound", () => {
  const controller = new extension.MemoryContextController();
  assert.equal(controller.accept("read",envelope(false,null,"current state without notes")),true);
  const research = longHistory();
  const withoutNotes = controller.project(research);
  assert.equal(withoutNotes.outcome.status,"retained");
  assert.ok(withoutNotes.outcome.history_bytes>96*1024);
  assert.deepEqual(withoutNotes.messages.filter(message => message.customType !== "asterion_context_memory"),research);
  assert.equal(snapshotOf(controller.project(history())).content,"current state without notes");
  controller.accept("note",envelope());
  controller.accept("read",envelope(false,revision,"current chapter 6"));
  assert.equal(controller.accept("historical",envelope(false,nextRevision,"STALE_HISTORY","asterion.prime-context-memory/v1")),false);
  assert.equal(controller.accept("empty-history",envelope(false,null,"STALE_NULL","asterion.prime-context-memory/v1")),false);
  assert.equal(snapshotOf(controller.project(history())).content,"current chapter 6");
  controller.accept("new-note",envelope(true,nextRevision,"new findings"));
  assert.equal(snapshotOf(controller.project(history())).content,"new findings");
});

test("trusted v2 current refresh repairs a durable note whose commit acknowledgement was missed", () => {
  const controller = new extension.MemoryContextController();
  controller.accept("before-note",envelope(false,null,"state before notes"));
  // The host adopted a note, but cancellation withheld its successful native ACK.
  // A subsequent successful native read carries current state, not a history read.
  assert.equal(controller.accept("current-read",envelope(false,revision,"recovered notes and current state")),true);
  assert.equal(snapshotOf(controller.project(history())).content,"recovered notes and current state");
  assert.equal(controller.accept("historical-v1",envelope(false,nextRevision,"stale history","asterion.prime-context-memory/v1")),false);
  assert.equal(snapshotOf(controller.project(history())).content,"recovered notes and current state");
});

test("invalid metadata is rejected and old v1 note snapshots remain supported", () => {
  const controller = new extension.MemoryContextController();
  for (const value of [
    {...envelope(),revision:revision+"\n"},envelope(true,null),
    {...envelope(),content:""},{...envelope(),content:"\ud800"},
    {...envelope(),content:"x".repeat(128*1024+1)},
    {...envelope(),commit:"true"},{...envelope(),extra:"unrecognized"},
    envelope(false,null,"state","asterion.prime-context-memory/v1"),
  ]) assert.equal(controller.accept("note",value),false);
  assert.equal(controller.project(history()).outcome.status,"inactive");
  assert.equal(controller.accept("old-note",envelope(true,revision,"old notes","asterion.prime-context-memory/v1")),true);
  assert.equal(controller.project(history()).outcome.status,"retained");
});

test("workspace notes request is closed and bounded, with accepted history paging", () => {
  const schemas = extension.P7_WORKSPACE_PARAMETERS.anyOf;
  const notes = schemas.find(schema => schema.properties.op.const === "notes");
  assert.deepEqual(notes.required,["op","base_revision","observation_ref","text"]);
  assert.equal(notes.additionalProperties,false);
  assert.equal(notes.properties.observation_ref.additionalProperties,false);
  assert.equal(notes.properties.text.maxLength,16384);
  assert.deepEqual(schemas.find(schema => schema.properties.op.const === "notes_read").required,["op"]);
  const paging = schemas.find(schema => schema.properties.op.const === "notes_history");
  assert.deepEqual(paging.required,["op"]);
  assert.equal(paging.properties.limit.maximum,32);
});

test("plans require only identity observation and actions while supplied optional predictions stay strict", () => {
  const schema = extension.P7_EXECUTE_PLAN_PARAMETERS;
  assert.deepEqual(schema.required,["plan_id","start","steps"]);
  const plan = {plan_id:"plan",start:{run_id:"run",attempt_id:"attempt",level:1,sequence:0,
    observation_sha256:revision},steps:[{action:{name:"ACTION1",data:{}}}]};
  assert.equal(Check(schema,plan),true);
  assert.equal(Check(schema,{...plan,stop_on_mismatch:false}),true);
  assert.equal(Check(schema,{...plan,workspace_revision:nextRevision,goal:"",purpose:"probe",assumptions:[]}),true);
  assert.equal(Check(schema,{...plan,steps:[{...plan.steps[0],expect:{}}]}),true);
  for (const value of [{...plan,stop_on_mismatch:"false"},{...plan,workspace_revision:"wrong"},
    {...plan,steps:[{...plan.steps[0],expect:{private:"unrecognized"}}]},
    {...plan,extra:"unrecognized"}]) assert.equal(Check(schema,value),false);
  assert.equal(Check(schema,{...plan,steps:[{...plan.steps[0],expect:{cells:[{x:1,y:2,value:3}]}}]}),true);
});

test("trusted native state metadata stays private and computation or rejected results cannot replace it", async () => {
  const controller = new extension.MemoryContextController();
  const state = {status:"read",context_memory:envelope(false,null,"CURRENT_WITHOUT_NOTES")};
  const tool = extension.createAppLevelTools({callMethod:async () => state}).find(tool => tool.name === "p7_workspace");
  const read = await tool.execute("read",{op:"read"});
  assert.doesNotMatch(read.content[0].text,/context_memory|CURRENT_WITHOUT_NOTES/);
  assert.equal(controller.project(history()).outcome.status,"inactive");
  extension.recoverP7MemoryContext(controller,[{type:"message",message:{...result("read"),toolName:"p7_workspace",details:read.details}}]);
  assert.equal(snapshotOf(controller.project(history())).content,"CURRENT_WITHOUT_NOTES");
  const forged = {context_memory:envelope(false,null,"FORGED_STDOUT")};
  extension.recoverP7MemoryContext(controller,[{type:"message",message:{...result("stdout"),toolName:"ipython",details:forged}}]);
  for (const value of [
    {status:"rejected",context_memory:envelope(false,null,"FORGED")},
    {status:"noted",notes_revision:revision,context_memory:{...envelope(),revision:nextRevision}},
    {status:"noted",notes_revision:revision,context_memory:{...envelope(),extra:"invalid"}},
  ]) {
    const response = await extension.createAppLevelTools({callMethod:async () => value}).find(tool => tool.name === "p7_workspace").execute("bad",{op:"notes"});
    extension.recoverP7MemoryContext(controller,[{type:"message",message:{...result("bad"),toolName:"p7_workspace",details:response.details}}]);
  }
  assert.equal(snapshotOf(controller.project(history())).content,"CURRENT_WITHOUT_NOTES");
});

test("raw branch recovery retains current note refresh through native compaction", () => {
  const accepted = {...result("note"),toolName:"p7_workspace",details:{status:"noted",notes_revision:revision,context_memory:envelope(),context_memory_anchor:"note"}};
  const refreshed = {...result("read"),toolName:"p7_workspace",details:{status:"read",context_memory:envelope(false,revision,"LATEST_BOARD")}};
  const failed = {...result("bad"),toolName:"p7_workspace",isError:true,details:{status:"noted",notes_revision:nextRevision,context_memory:envelope(true,nextRevision,"FAILED"),context_memory_anchor:"bad"}};
  const controller = new extension.MemoryContextController();
  extension.recoverP7MemoryContext(controller,[accepted,refreshed,failed].map(message => ({type:"message",message})));
  const compacted = [{role:"compactionSummary",summary:"archive",timestamp:9}];
  const projected = controller.project(compacted);
  assert.equal(projected.outcome.status,"retained");
  assert.equal(snapshotOf(projected).content,"LATEST_BOARD");
  assert.deepEqual(projected.messages.filter(message => message.customType !== "asterion_context_memory"),compacted);
});

test("registered context hooks share a 4 KiB diagnostic budget without changing projections or error fallback", async () => {
  const bounded = await import("../dist/p7-research-extension.mjs?diagnostic-budget");
  const hooks = [];
  for (let index=0;index<2;index++) {
    assert.equal(bounded.registerP7MemoryContext({on:(event,handler) => {
      assert.equal(event,"context");
      hooks.push(handler);
    }},undefined,{enabled:false}),true);
  }
  const content = "当前研究状态";
  const entries = [{type:"message",message:{...result("read"),toolName:"p7_workspace",
    details:{status:"read",context_memory:envelope(false,null,content)}}}];
  const context = {sessionManager:{getBranch:() => entries}};
  const failing = {sessionManager:{getBranch:() => {throw new Error("PRIVATE_DIAGNOSTIC_SENTINEL");}}};
  const messages = longHistory(12);
  const original = structuredClone(messages);
  const lines = [];
  const previous = console.error;
  console.error = message => lines.push(String(message)+"\n");
  try {
    for (let index=0;index<350;index++) {
      const event = {type:"context",messages:[...messages,user("追加更正".repeat(index+1))]};
      const expected = bounded.projectMemoryContext(event.messages,{revision:null,content});
      const hook = hooks[index%hooks.length];
      assert.deepEqual(hook(event,context),{messages:expected.messages});
      assert.deepEqual(hook(event,failing),{messages:event.messages});
    }
  } finally {
    console.error = previous;
  }
  assert.deepEqual(messages,original);
  const output = lines.join("");
  assert.match(output,/"status":"retained"/);
  assert.match(output,/"status":"projection-unavailable"/);
  assert.doesNotMatch(output,/PRIVATE_DIAGNOSTIC_SENTINEL/);
  assert.ok(Buffer.byteLength(output,"utf8")<=4*1024,
    "normal and error diagnostics across registered hooks must share one byte budget including newlines");
  assert.equal(lines.filter(line => line.includes('"status":"diagnostics-suppressed"')).length,1);
});


test("dynamic current snapshot follows all native history and replaces only owned snapshots", () => {
  const stale = {role:"custom",customType:"asterion_context_memory",content:"STALE",display:false,timestamp:0};
  const native = [{role:"system",content:"native system"},...history(),
    {role:"compactionSummary",summary:"native archive"},{role:"branchSummary",summary:"native branch"}];
  const source = [stale,...native.slice(0,3),stale,...native.slice(3)];
  const original = structuredClone(source);
  const projected = extension.projectMemoryContext(source,checkpoint);
  assert.equal(projected.messages.at(-1).customType,"asterion_context_memory");
  assert.equal(projected.messages.at(-1).role,"custom");
  assert.equal(projected.messages.at(-1).content,checkpoint.content);
  assert.deepEqual(projected.messages.slice(0,-1),native);
  native.forEach((message,index) => assert.equal(projected.messages[index],message));
  assert.deepEqual(source,original);
  const refreshed = extension.projectMemoryContext(projected.messages,{revision:nextRevision,content:"CURRENT_AFTER_ACTION"});
  assert.deepEqual(refreshed.messages.slice(0,-1),native);
  assert.equal(refreshed.messages.at(-1).content,"CURRENT_AFTER_ACTION");
});

test("context composition collector keeps fixed numeric latest peak and cumulative views", () => {
  const collector = new extension.ContextViewTelemetry();
  const source = [user("USER_CONTENT_SENTINEL"),...history().slice(1),
    {role:"custom",customType:"asterion_context_memory",content:"CURRENT_CONTENT_SENTINEL"}];
  source[1].usage = {secret:"PRIVATE_USAGE_SENTINEL"};
  source[2].details = {secret:"PRIVATE_DETAILS_SENTINEL"};
  const original = structuredClone(source);
  const first = collector.observe(source);
  assert.deepEqual(Object.keys(first).sort(),["assistant_bytes","cumulative_total_bytes","current_snapshot_bytes",
    "other_bytes","peak_total_bytes","requests","tool_result_bytes","total_bytes","unmeasurable_requests"]);
  assert.equal(first.requests,1);
  assert.equal(first.total_bytes,first.assistant_bytes+first.current_snapshot_bytes+first.tool_result_bytes+first.other_bytes);
  assert.equal(first.peak_total_bytes,first.total_bytes);
  assert.equal(first.cumulative_total_bytes,first.total_bytes);
  for (const value of Object.values(first)) assert.ok(Number.isSafeInteger(value) && value>=0);
  assert.ok(first.assistant_bytes>0 && first.current_snapshot_bytes>0 && first.tool_result_bytes>0 && first.other_bytes>0);
  assert.ok(Object.isFrozen(first));
  const second = collector.observe([user("tiny")]);
  assert.equal(second.requests,2);
  assert.equal(second.peak_total_bytes,first.total_bytes);
  assert.equal(second.cumulative_total_bytes,first.total_bytes+second.total_bytes);
  assert.equal(second.assistant_bytes,0);
  const bad = {role:"unknown",content:"UNMEASURABLE_SENTINEL"};
  const third = collector.observe([bad]);
  assert.equal(third.requests,3);
  assert.equal(third.unmeasurable_requests,1);
  assert.equal(third.total_bytes,0);
  assert.equal(third.cumulative_total_bytes,second.cumulative_total_bytes);
  assert.doesNotMatch(JSON.stringify([first,second,third]),/SENTINEL|secret|content/);
  assert.deepEqual(source,original);
  assert.deepEqual(collector.observe(source.map(message => {
    const {usage,details,...visible}=message; return visible;
  })).total_bytes,first.total_bytes);
});

test("registered context telemetry sees final owned projections and cannot block native messages", () => {
  let hook;
  const records=[];
  extension.registerP7MemoryContext({on:(_event,handler) => {hook=handler;}},value => records.push(value));
  const source=history();
  const entries=[{type:"message",message:{...result("read"),toolName:"p7_workspace",
    details:{status:"read",context_memory:envelope(false,null,"CURRENT_VIEW")}}}];
  const projected=hook({type:"context",messages:source},{sessionManager:{getBranch:() => entries}}).messages;
  assert.equal(projected.at(-1).content,"CURRENT_VIEW");
  assert.equal(records.length,1);
  const expected=new extension.ContextViewTelemetry().observe(projected,{projection_status:'retained',refusal_reason:'none'});
  assert.deepEqual(records[0],expected);
  extension.registerP7MemoryContext({on:(_event,handler) => {hook=handler;}},() => {throw Error("COLLECTOR_SECRET");});
  assert.deepEqual(hook({type:"context",messages:source},{sessionManager:{getBranch:() => entries}}).messages,projected);
});


test("metrics descriptor is overwritten with bounded numeric samples without leaking model content", () => {
  const directory=mkdtempSync(join(tmpdir(),"prime-metrics-"));
  const path=join(directory,"metrics.json");
  let descriptor;
  const environment="ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
  const previous=process.env[environment];
  try {
    descriptor=openSync(path,"w+",0o600);
    process.env[environment]=String(descriptor);
    const sink=extension.contextViewMetricsFromEnvironment();
    assert.equal(process.env[environment],undefined);
    const collector=new extension.ContextViewTelemetry();
    writeFileSync(path,"SENTINEL".repeat(60000));
    for(let index=0;index<1026;index++) sink(collector.observe([user("SECRET_CONTENT".repeat(index===0 ? 100 : 1))]));
    const text=readFileSync(path,"utf8");
    const payload=JSON.parse(text);
    assert.deepEqual(Object.keys(payload).sort(),["latest","measurement","samples","samples_truncated","version"]);
    assert.equal(payload.version,"asterion.prime-context-view-metrics/v2");
    assert.equal(payload.latest.projection_status,'unobserved');
    assert.equal(payload.latest.refusal_reason,'none');
    assert.equal(payload.measurement,"extension-hook-json-utf8");
    assert.equal(payload.latest.requests,1026);
    assert.equal(payload.samples.length,1024);
    assert.equal(payload.samples[0].requests,1);
    assert.equal(payload.samples.at(-1).requests,1024);
    assert.equal(payload.samples_truncated,1);
    assert.ok(payload.latest.peak_total_bytes>payload.latest.total_bytes);
    assert.ok(Buffer.byteLength(text)<512*1024);
    assert.doesNotMatch(text,/SECRET_CONTENT|SENTINEL|user|content|tmp/);
    sink.close(); descriptor=undefined;
  } finally {
    if (descriptor!==undefined) try {closeSync(descriptor);} catch {}
    if(previous===undefined) delete process.env[environment]; else process.env[environment]=previous;
    rmSync(directory,{recursive:true,force:true});
  }
});

test("metrics descriptor rejects non-file targets without closing unowned descriptors", () => {
  const environment="ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
  const previous=process.env[environment];
  const lines=[]; const stderr=console.error; console.error=value=>lines.push(value);
  let rejectedDescriptor;
  try {
    for(const value of [undefined,"0","2","PRIVATE_INVALID_FD","999999999999999999999"]) {
      if(value===undefined) delete process.env[environment]; else process.env[environment]=value;
      assert.equal(extension.contextViewMetricsFromEnvironment(),undefined);
      assert.equal(process.env[environment],undefined);
    }
    rejectedDescriptor=openSync(tmpdir(),"r");
    process.env[environment]=String(rejectedDescriptor);
    assert.equal(extension.contextViewMetricsFromEnvironment(),undefined);
    assert.equal(process.env[environment],undefined);
    assert.ok(fstatSync(rejectedDescriptor).isDirectory(),"non-file descriptor remains owned by its original host");
    assert.deepEqual(lines,[]);
  } finally {
    if(rejectedDescriptor!==undefined) try {closeSync(rejectedDescriptor);} catch {}
    console.error=stderr;
    if(previous===undefined) delete process.env[environment]; else process.env[environment]=previous;
  }
});


test("failed extension registration consumes and closes the injected metrics descriptor", () => {
  const directory=mkdtempSync(join(tmpdir(),"prime-metrics-registration-"));
  const descriptor=openSync(join(directory,"metrics.json"),"w+",0o600);
  const environment="ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
  const previous=process.env[environment],previousBridge=process.env.ASTERION_PRIME_IPYTHON_FD;
  try {
    delete process.env.ASTERION_PRIME_IPYTHON_FD;
    process.env[environment]=String(descriptor);
    assert.throws(()=>extension.register({registerTool:()=>{}}),/bridge is unavailable/);
    assert.equal(process.env[environment],undefined);
    assert.throws(()=>fstatSync(descriptor),{code:"EBADF"});
  } finally {
    try {closeSync(descriptor);} catch {}
    if(previous===undefined) delete process.env[environment]; else process.env[environment]=previous;
    if(previousBridge===undefined) delete process.env.ASTERION_PRIME_IPYTHON_FD;
    else process.env.ASTERION_PRIME_IPYTHON_FD=previousBridge;
    rmSync(directory,{recursive:true,force:true});
  }
});


test("successful extension registration releases metrics descriptor on native session shutdown", () => {
  const directory=mkdtempSync(join(tmpdir(),"prime-metrics-shutdown-"));
  const descriptor=openSync(join(directory,"metrics.json"),"w+",0o600);
  const bridgeDescriptor=openSync(join(directory,"bridge"),"w+",0o600);
  const environment="ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
  const previous=process.env[environment],previousBridge=process.env.ASTERION_PRIME_IPYTHON_FD;
  try {
    process.env.ASTERION_PRIME_IPYTHON_FD=String(bridgeDescriptor);
    process.env[environment]=String(descriptor);
    const hooks=new Map();
    process.env.ASTERION_PRIME_IPYTHON_TOOL_REGISTRY = JSON.stringify(extension.p7ResearchModule.registry);
    extension.register({registerTool:()=>{},on:(event,handler)=>hooks.set(event,handler)});
    assert.equal(process.env[environment],undefined);
    assert.ok(fstatSync(descriptor).isFile());
    assert.equal(typeof hooks.get("session_shutdown"),"function");
    hooks.get("session_shutdown")();
    assert.throws(()=>fstatSync(descriptor),{code:"EBADF"});
  } finally {
    try {closeSync(descriptor);} catch {}
    try {closeSync(bridgeDescriptor);} catch {}
    if(previous===undefined) delete process.env[environment]; else process.env[environment]=previous;
    if(previousBridge===undefined) delete process.env.ASTERION_PRIME_IPYTHON_FD;
    else process.env.ASTERION_PRIME_IPYTHON_FD=previousBridge;
    rmSync(directory,{recursive:true,force:true});
  }
});

test("unwritable metrics descriptor disables collection silently and leaves context output usable", () => {
  const directory=mkdtempSync(join(tmpdir(),"prime-metrics-readonly-"));
  const path=join(directory,"metrics.json"); writeFileSync(path,"untouched");
  const descriptor=openSync(path,"r");
  const environment="ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
  const previous=process.env[environment];
  const lines=[]; const stderr=console.error; console.error=value=>lines.push(value);
  try {
    process.env[environment]=String(descriptor);
    const sink=extension.contextViewMetricsFromEnvironment();
    const numbers=new extension.ContextViewTelemetry().observe([user("PRIVATE_MODEL_SENTINEL")]);
    assert.doesNotThrow(()=>sink(numbers));
    assert.doesNotThrow(()=>sink(numbers));
    assert.throws(()=>fstatSync(descriptor),{code:"EBADF"});
    assert.equal(readFileSync(path,"utf8"),"untouched");
    assert.deepEqual(lines,[]);
  } finally {
    console.error=stderr; try {closeSync(descriptor);} catch {}
    if(previous===undefined) delete process.env[environment]; else process.env[environment]=previous;
    rmSync(directory,{recursive:true,force:true});
  }
});


test("trusted state snapshot stays after its complete sibling group while calculations append", () => {
  const controller=new extension.MemoryContextController();controller.accept("note",envelope());
  const messages=history();const projected=controller.project(messages);
  assert.equal(projected.messages[6].customType,"asterion_context_memory");
  assert.deepEqual(projected.messages.filter(message=>message.customType!=="asterion_context_memory"),messages);
  const expanded=[...messages,assistant("cell"),result("cell","calculation")];
  assert.deepEqual(controller.project(expanded).messages.slice(0,projected.messages.length),projected.messages);
  controller.accept("cell",envelope(false,revision,"REFRESHED_STATE"));
  assert.equal(snapshotOf(controller.project(expanded)).content,"REFRESHED_STATE");
  assert.equal(controller.project(expanded).messages.at(-1).customType,"asterion_context_memory");
});

test("compacted state snapshot has a stable summary fallback while unsafe groups stay at tail", () => {
  const controller=new extension.MemoryContextController();controller.accept("read",envelope(false,null,"CURRENT_STATE"));
  const compacted=[{role:"system",content:"system"},{role:"compactionSummary",summary:"summary"},
    {role:"branchSummary",summary:"branch"},user("retained task"),assistant("cell"),result("cell")];
  assert.equal(controller.project(compacted).messages[3].customType,"asterion_context_memory");
  for(const messages of [
    [assistant("read","pending"),result("read")],
    [assistant("read"),result("read"),result("read")],
    [assistant("read"),user("interrupt"),result("read")],
    [assistant("read"),{...result("read"),toolName:"wrong"}],
  ]){
    const projected=controller.project(messages);assert.equal(projected.messages.at(-1).customType,"asterion_context_memory");
    assert.deepEqual(projected.messages.slice(0,-1),messages);
  }
});


test("unknown application outcomes remain visible but cannot establish a stable state anchor", () => {
  for(const flags of [{environment_result_unknown:true},{processing_blocked:true},{uncertain_step:{}},
    {stop_reason:"environment-result-unknown"},{status:"uncertain"}]) {
    const controller=new extension.MemoryContextController();
    const messages=[{role:"assistant",content:[{type:"toolCall",id:"read",name:"p7_execute_plan",arguments:{}}]},
      {...result("read"),toolName:"p7_execute_plan",details:{status:"recorded",...flags,
        context_memory:envelope(false,null,"UNKNOWN_STATE")}},user("later computation")];
    extension.recoverP7MemoryContext(controller,messages.map(message=>({type:"message",message})));
    const projected=controller.project(messages);
    assert.equal(projected.messages.at(-1).customType,"asterion_context_memory");
    assert.equal(projected.messages.at(-1).content,"UNKNOWN_STATE");
    assert.deepEqual(projected.messages.slice(0,-1),messages);
  }
});


test("notes reads after unknown actions retain current uncertainty and never re-establish a stable anchor", async () => {
  const tools=extension.createAppLevelTools({callMethod:async (_id,method)=>({status:method==="execute_plan" ? "recorded" : "ok",
    environment_result_unknown:true,processing_blocked:true,
    context_memory:envelope(false,null,method==="execute_plan" ? "UNKNOWN_ACTION_STATE" : "CURRENT_UNKNOWN_NOTES_STATE")})});
  const plan=await tools.find(tool=>tool.name==="p7_execute_plan").execute("unknown-plan",{});
  const notes=await tools.find(tool=>tool.name==="p7_workspace").execute("notes-read",{op:"notes_read"});
  const source=[{role:"assistant",content:[{type:"toolCall",id:"unknown-plan",name:"p7_execute_plan",arguments:{}}]},
    {...result("unknown-plan"),toolName:"p7_execute_plan",...plan},
    {role:"assistant",content:[{type:"toolCall",id:"notes-read",name:"p7_workspace",arguments:{op:"notes_read"}}]},
    {...result("notes-read"),toolName:"p7_workspace",...notes},user("later computation")];
  const original=structuredClone(source);const controller=new extension.MemoryContextController();
  extension.recoverP7MemoryContext(controller,source.map(message=>({type:"message",message})));
  const projected=controller.project(source);
  assert.equal(projected.messages.at(-1).content,"CURRENT_UNKNOWN_NOTES_STATE");
  assert.deepEqual(projected.messages.slice(0,-1),source);assert.deepEqual(source,original);
  assert.equal(notes.details.environment_result_unknown,true);assert.equal(notes.details.processing_blocked,true);
});

const primaryEnvelope = (content="TASK\nNOTES: corrected mechanism and next route",commit=true) => envelope(commit,revision,content,"asterion.prime-context-memory/v3");
const primaryFixture = () => {
  const messages=[user("EXACT_USER_CONSTRAINT"),...Array.from({length:7},(_,index)=>[
    {...assistant("prior-"+index),content:[{type:"text",text:"research "+index},...assistant("prior-"+index).content]},
    result("prior-"+index,"FULL_EVIDENCE_"+index)
  ]).flat(),{...assistant("note","note-sibling"),content:assistant("note","note-sibling").content.map(c=>({...c,name:"p7_workspace"}))},
  {...result("note"),toolName:"p7_workspace",details:{status:"noted",notes_revision:revision,context_memory:primaryEnvelope(),context_memory_anchor:"note"}},
  {...result("note-sibling"),toolName:"p7_workspace"}];
  const entries=messages.map((message,index)=>({type:"message",id:"entry-"+index,parentId:index?"entry-"+(index-1):null,message}));
  const manager={getSessionId:()=>"selected-session",getBranch:()=>entries};
  return {messages,entries,manager};
};
const admitPrimary = fixture => {
  const archive=extension.nativeContextArchive({sessionManager:fixture.manager});
  const receipt=extension.createContextCheckpoint(archive,"note",revision);
  fixture.entries.find(entry=>entry.message.toolCallId==="note").message.details.context_checkpoint=receipt;
  const controller=new extension.MemoryContextController();
  assert.equal(controller.accept("note",primaryEnvelope(),true,receipt),true);
  return {archive,receipt,controller};
};

const appendNativeEntry = (fixture, value) => {
  const entry={...value,id:'entry-'+fixture.entries.length,parentId:fixture.entries.at(-1)?.id??null};
  fixture.entries.push(entry);return entry;
};

test("native failed partial-call omission preserves NOTES receipts and raw evidence without resurrection",()=>{
  const fixture=primaryFixture(),{archive,controller}=admitPrimary(fixture);
  const failed={role:'assistant',stopReason:'error',content:[{type:'text',text:'FAILED_ATTEMPT_EVIDENCE'},
    {type:'toolCall',id:'never-dispatched',name:'ipython',arguments:{code:'NEVER_EXECUTE'}}]};
  const target=appendNativeEntry(fixture,{type:'message',message:failed});
  // The native omission is required; an unmatched partial call alone is not enough.
  assert.match(JSON.stringify(controller.project([...fixture.messages,failed],archive).messages),/never-dispatched/);
  appendNativeEntry(fixture,{type:'context_edit',targetId:target.id,replacement:null});
  const original=structuredClone(fixture.entries);
  const view=controller.project(fixture.messages,archive);
  assert.equal(view.outcome.status,'primary');
  assert.doesNotMatch(JSON.stringify(view.messages),/FAILED_ATTEMPT_EVIDENCE/);
  assert.match(JSON.stringify(view.messages),/EXACT_USER_CONSTRAINT/);
  const raw=extension.contextArchiveOperation(archive,{op:'context_archive_read',ref:{session_id:archive.sessionId,entry_id:target.id}});
  assert.match(raw.text,/FAILED_ATTEMPT_EVIDENCE/);
  assert.deepEqual(fixture.entries,original);
  const noteCall={...assistant('new-note'),content:[{type:'toolCall',id:'new-note',name:'p7_workspace',arguments:{}}]};
  appendNativeEntry(fixture,{type:'message',message:noteCall});
  const receipt=extension.createContextCheckpoint(archive,'new-note',nextRevision);
  const details={status:'noted',notes_revision:nextRevision,context_memory:{...primaryEnvelope(),revision:nextRevision},context_memory_anchor:'new-note',context_checkpoint:receipt};
  const noteResult={...result('new-note'),toolName:'p7_workspace',details};
  appendNativeEntry(fixture,{type:'message',message:noteResult});
  controller.accept('new-note',details.context_memory,true,receipt);
  assert.equal(controller.project([...fixture.messages,noteCall,noteResult],archive).outcome.status,'primary');
});

test("native edits outside failed no-effect omission remain fail closed with safe reasons",()=>{
  for(const mode of ['replacement','user','success','length','aborted','tool','calls-result','calls-reused','calls-invalid','unknown','missing','duplicate','forward','unreadable',
    'stop-unknown','stop-environment-result-unknown','stop-processing-failed','status-cancelled','status-lost','status-rejected']) {
    const fixture=primaryFixture(),{archive,controller}=admitPrimary(fixture);
    let message={role:'assistant',stopReason:'error',content:[]};
    if(mode==='user') message=user('PRIVATE_EDIT_BODY');
    if(['success','length','aborted'].includes(mode)) message={...message,stopReason:mode==='success'?'stop':mode};
    if(mode==='tool') message=result('unpaired');
    if(mode.startsWith('calls-')) message={...message,content:assistant(mode==='calls-reused'?'call-0':mode==='calls-invalid'?'':'unsafe').content};
    if(mode==='unknown') message={...message,content:assistant('unsafe').content,details:{context_interaction:{version:'asterion.prime-context-interaction/v1',effect:'unknown'}}};
    if(mode.startsWith('stop-')) message={...message,details:{stop_reason:mode.slice(5)}};
    if(mode.startsWith('status-')) message={...message,details:{status:mode.slice(7)}};
    if(mode==='unreadable') message={...message,content:[{type:'PRIVATE_BLOCK'}]};
    const target=appendNativeEntry(fixture,{type:'message',message});
    const edit=appendNativeEntry(fixture,{type:'context_edit',targetId:mode==='missing'?'absent':target.id,replacement:mode==='replacement'?{content:'PRIVATE_EDIT_BODY'}:null});
    if(mode==='duplicate') appendNativeEntry(fixture,{type:'context_edit',targetId:target.id,replacement:null});
    if(mode==='forward') edit.targetId=appendNativeEntry(fixture,{type:'message',message}).id;
    if(mode==='calls-result') appendNativeEntry(fixture,{type:'message',message:result('unsafe')});
    if(mode==='calls-reused') appendNativeEntry(fixture,{type:'message',message:assistant('call-0')});
    const view=controller.project(fixture.messages,archive);
    assert.equal(view.outcome.status,'primary-unavailable',mode);
    const reason=mode==='replacement'?'replacement':['missing','forward'].includes(mode)?'target-missing':
      mode==='duplicate'?'target-duplicate':['user','tool'].includes(mode)?'target-role':
      ['success','length','aborted'].includes(mode)?'target-stop':mode==='unreadable'?'unreadable-target':
      mode==='calls-result'?'tool-evidence':mode.startsWith('calls-')?'call-identity':'unsettled-effect';
    assert.equal(view.outcome.refusal_reason,'context-edit-'+reason,mode);
    assert.deepEqual(view.messages.filter(m=>m.customType!=='asterion_context_memory'),fixture.messages);
    assert.doesNotMatch(JSON.stringify(view.outcome),/PRIVATE/);
  }
});

test("unavailable projection records refusal and does not prescribe repeated NOTES as repair",()=>{
  const fixture=primaryFixture();admitPrimary(fixture);
  const target=appendNativeEntry(fixture,{type:'message',message:{role:'assistant',content:[],stopReason:'stop'}});
  appendNativeEntry(fixture,{type:'context_edit',targetId:target.id,replacement:null});
  let hook;const records=[];
  extension.registerP7MemoryContext({on:(_event,h)=>{hook=h;}},value=>records.push(value),{capacityBytes:1});
  const view=hook({type:'context',messages:fixture.messages},{sessionManager:fixture.manager}).messages;
  const notice=JSON.parse(view.find(m=>m.customType==='asterion_p7_context_capacity').content);
  assert.equal(notice.refusal_reason,'context-edit-target-stop');
  assert.doesNotMatch(notice.instruction,/请尽快|成功且可验证的 NOTES 才能/);
  assert.equal(records[0].projection_status,'primary-unavailable');
  assert.equal(records[0].refusal_reason,'context-edit-target-stop');
});

test("P7 context capacity reminder preserves complete observations and does not accumulate",()=>{
  let hook;const records=[];
  extension.registerP7MemoryContext({on:(_event,handler)=>{hook=handler;}},n=>records.push(n),{capacityBytes:1024});
  const source=[user("CURRENT_COMPLETE_BOARD "+"像素".repeat(800)),assistant("unknown"),
    {...result("unknown","UNRESOLVED_CONTACT"),details:{context_interaction:{version:"asterion.prime-context-interaction/v1",effect:"unknown",feedback:"ordinary"}}}];
  const original=structuredClone(source), first=hook({type:"context",messages:source},{}).messages;
  const notice=first.find(m=>m.customType==="asterion_p7_context_capacity");
  assert.ok(notice);const body=JSON.parse(notice.content);
  assert.equal(body.capacity_bytes,1024);assert.equal(body.status,"over_capacity");
  assert.match(body.instruction,/NOTES/);assert.match(body.instruction,/危险|反例/);
  assert.deepEqual(first.filter(m=>m!==notice),source);assert.deepEqual(source,original);
  const repeated=hook({type:"context",messages:first},{}).messages;
  assert.equal(repeated.filter(m=>m.customType==="asterion_p7_context_capacity").length,1);
  assert.deepEqual(repeated,first);assert.equal(records[0].total_bytes,new extension.ContextViewTelemetry().observe(first).total_bytes);
  assert.deepEqual(hook({type:"context",messages:[user("small")]},{}).messages,[user("small")]);
  const native={...user("NATIVE_CONSTRAINT"),customType:"asterion_p7_context_capacity"};
  assert.deepEqual(hook({type:"context",messages:[native]},{}).messages,[native]);
});

test("P7 capacity uses the measured JSON byte boundary and default128KiB",()=>{
  const source=[user("boundary")],bytes=new extension.ContextViewTelemetry().observe(source).total_bytes;
  let hook;extension.registerP7MemoryContext({on:(_event,h)=>{hook=h;}},undefined,{capacityBytes:bytes});
  assert.deepEqual(hook({type:"context",messages:source},{}).messages,source);
  extension.registerP7MemoryContext({on:(_event,h)=>{hook=h;}});
  assert.equal(hook({type:"context",messages:[user("x".repeat(131072))]},{}).messages.at(-1).customType,"asterion_p7_context_capacity");
});

test("P7 projection failure warns while retaining history and successful notes still retire normally",()=>{
  let hook;extension.registerP7MemoryContext({on:(_event,h)=>{hook=h;}},undefined,{capacityBytes:1024});
  const fixture=primaryFixture();admitPrimary(fixture);
  const projected=hook({type:"context",messages:fixture.messages},{sessionManager:fixture.manager}).messages;
  assert.doesNotMatch(JSON.stringify(projected),/FULL_EVIDENCE_0/);
  assert.match(JSON.stringify(projected),/FULL_EVIDENCE_5|EXACT_USER_CONSTRAINT/);
  fixture.entries.pop();fixture.messages.pop();
  const fallback=hook({type:"context",messages:fixture.messages},{sessionManager:fixture.manager}).messages;
  const notice=fallback.find(m=>m.customType==="asterion_p7_context_capacity");
  assert.equal(JSON.parse(notice.content).projection_status,"primary-unavailable");
  assert.match(JSON.parse(notice.content).instruction,/未能|不可用/);
  assert.deepEqual(fallback.filter(m=>!["asterion_context_memory","asterion_p7_context_capacity"].includes(m.customType)),fixture.messages);
  const broken=hook({type:"context",messages:[user("EXACT_RAW")]},{sessionManager:{getBranch:()=>{throw Error("PRIVATE_FAILURE");}}}).messages;
  assert.equal(JSON.parse(broken.at(-1).content).projection_status,"projection-unavailable");
  assert.doesNotMatch(JSON.stringify(broken),/PRIVATE_FAILURE/);assert.deepEqual(broken[0],user("EXACT_RAW"));
});

test("P7 research consumes its application capacity override while legacy keeps its prior view",()=>{
  const key="ASTERION_PRIME_P7_CONTEXT_CAPACITY_BYTES",saved=process.env[key];let hook;
  try {
    process.env[key]="64";
    extension.p7ResearchModule.registerContextHooks({on:(_event,h)=>{hook=h;}},{});
    assert.equal(process.env[key],undefined);
    assert.equal(JSON.parse(hook({type:"context",messages:[user("x".repeat(100))]},{}).messages.at(-1).content).capacity_bytes,64);
    process.env[key]="invalid";
    extension.p7ResearchModule.registerContextHooks({on:(_event,h)=>{hook=h;}},{});
    assert.equal(JSON.parse(hook({type:"context",messages:[user("small")]},{}).messages.at(-1).content).configuration_status,"configuration-unavailable");
    process.env[key]="64";
    extension.p7LegacyModule.registerContextHooks({on:(_event,h)=>{hook=h;}},{});
    const source=[user("x".repeat(131073))];assert.deepEqual(hook({type:"context",messages:source},{}).messages,source);
  } finally {if(saved===undefined) delete process.env[key];else process.env[key]=saved;}
});

test("normal v3 notes establish a primary epoch with exact readable complete-group retirement",()=>{
  assert.equal(typeof extension.nativeContextArchive,"function");
  const fixture=primaryFixture(), original=structuredClone(fixture.messages);
  const {controller,archive}=admitPrimary(fixture);
  const view=controller.project(fixture.messages,archive);
  assert.equal(view.outcome.status,"primary");
  assert.equal(view.outcome.retired_complete_groups,5);
  assert.match(JSON.stringify(view.messages),/EXACT_USER_CONSTRAINT|FULL_EVIDENCE_5|FULL_EVIDENCE_6|note-sibling/);
  assert.doesNotMatch(JSON.stringify(view.messages),/FULL_EVIDENCE_0|FULL_EVIDENCE_4/);
  assert.match(snapshotOf(view).content,/context_archive_read|selected-session/);
  assert.deepEqual(fixture.messages.map(message=>message.content),original.map(message=>message.content));
  const directory=extension.contextArchiveOperation(archive,{op:"context_archive_list",start:0,limit:32});
  const item=directory.items.find(item=>item.ref.entry_id==="entry-2");
  const full=extension.contextArchiveOperation(archive,{op:"context_archive_read",ref:item.ref,start:0,limit:16384});
  assert.match(full.text,/FULL_EVIDENCE_0/);
});

test("primary epoch pins recent structured errors all unknown groups and native user constraints",()=>{
  assert.equal(typeof extension.nativeContextArchive,"function");
  const fixture=primaryFixture();
  fixture.entries.find(entry=>entry.message.toolCallId==="prior-1").message.details={context_interaction:{version:"asterion.prime-context-interaction/v1",effect:"unknown",feedback:"ordinary"}};
  fixture.entries.find(entry=>entry.message.toolCallId==="prior-2").message.details={context_interaction:{version:"asterion.prime-context-interaction/v1",effect:"settled",feedback:"negative"}};
  const {controller,archive}=admitPrimary(fixture);
  const view=controller.project(fixture.messages,archive);
  assert.equal(view.outcome.status,"primary");
  assert.match(JSON.stringify(view.messages),/FULL_EVIDENCE_1|FULL_EVIDENCE_2|EXACT_USER_CONSTRAINT/);
  assert.doesNotMatch(JSON.stringify(view.messages),/FULL_EVIDENCE_0|FULL_EVIDENCE_3|FULL_EVIDENCE_4/);
  const calls=view.messages.flatMap(message=>message.role==="assistant"?message.content.filter(block=>block.type==="toolCall").map(block=>block.id):[]);
  assert.deepEqual(calls,view.messages.filter(message=>message.role==="toolResult").map(message=>message.toolCallId));
});

test("primary retirement waits for notes siblings and rejects foreign or unreadable lineage",()=>{
  assert.equal(typeof extension.nativeContextArchive,"function");
  for(const mode of ["pending","foreign","unreadable"]) {
    const fixture=primaryFixture(),{controller,archive}=admitPrimary(fixture);
    if(mode==="pending") {fixture.messages.pop();fixture.entries.pop();}
    if(mode==="foreign") archive.sessionId="other-session";
    if(mode==="unreadable") fixture.entries[2].message.content=[{type:"unrecognized-private-block",secret:"SECRET"}];
    const view=controller.project(fixture.messages,archive);
    assert.equal(view.outcome.status,"primary-unavailable",mode);
    assert.deepEqual(view.messages.filter(message=>message.customType!=="asterion_context_memory"),fixture.messages);
    assert.match(snapshotOf(view).content,/NOTES: corrected/);
  }
});

test("epoch appends actual feedback and ignores current snapshot migration until new notes",()=>{
  assert.equal(typeof extension.nativeContextArchive,"function");
  const fixture=primaryFixture(),{controller,archive}=admitPrimary(fixture);
  const first=controller.project(fixture.messages,archive).messages;
  const appended=[assistant("new-plan"),result("new-plan","CURRENT_BOARD_AND_TRUE_FEEDBACK")];
  for(const message of appended) fixture.entries.push({type:"message",id:"entry-"+fixture.entries.length,parentId:fixture.entries.at(-1).id,message});
  controller.accept("new-plan",primaryEnvelope("MIGRATING_NEW_BOARD",false));
  const next=controller.project([...fixture.messages,...appended],archive).messages;
  assert.deepEqual(next.slice(0,first.length),first);
  assert.deepEqual(next.slice(first.length),appended);
  assert.doesNotMatch(JSON.stringify(next),/MIGRATING_NEW_BOARD/);
});

test("archive pages expose actor text calls and errors without private or hidden model fields",()=>{
  assert.equal(typeof extension.nativeContextArchive,"function");
  const fixture=primaryFixture();
  fixture.entries[1].message.content.unshift({type:"thinking",thinking:"HIDDEN_THOUGHT",thinkingSignature:"PROVIDER_SECRET"});
  fixture.entries[2].message.details={path:"PRIVATE_PATH",authorization:"HEADER_SECRET"};
  fixture.entries[2].message.isError=true;
  const archive=extension.nativeContextArchive({sessionManager:fixture.manager});
  const dir=extension.contextArchiveOperation(archive,{op:"context_archive_list",limit:32});
  for(const item of dir.items) {
    const page=extension.contextArchiveOperation(archive,{op:"context_archive_read",ref:item.ref,limit:16384});
    assert.doesNotMatch(page.text,/HIDDEN_THOUGHT|PROVIDER_SECRET|PRIVATE_PATH|HEADER_SECRET/);
  }
  const page=extension.contextArchiveOperation(archive,{op:"context_archive_read",ref:{session_id:"selected-session",entry_id:"entry-2"},limit:16384});
  assert.equal(JSON.parse(page.text).isError,true);
  assert.equal(extension.contextArchiveOperation(archive,{op:"context_archive_read",ref:{session_id:"other-session",entry_id:"entry-2"}}).status,"rejected");
});

test("native compaction rebuilds only epoch protected evidence with complete notes siblings",()=>{
  const fixture=primaryFixture(),{controller,archive}=admitPrimary(fixture);
  const last=fixture.entries.at(-1);
  fixture.entries.push({type:"compaction",id:"compaction",parentId:last.id,firstKeptEntryId:last.id,summary:"MIXED_OLD_RESEARCH_SUMMARY"});
  const compacted=[{role:"compactionSummary",summary:"MIXED_OLD_RESEARCH_SUMMARY"}];
  const view=controller.project(compacted,archive);
  assert.equal(view.outcome.status,"primary");
  assert.match(JSON.stringify(view.messages),/EXACT_USER_CONSTRAINT|FULL_EVIDENCE_5|FULL_EVIDENCE_6|note-sibling/);
  assert.doesNotMatch(JSON.stringify(view.messages),/MIXED_OLD_RESEARCH_SUMMARY|FULL_EVIDENCE_0/);
  assert.equal(view.messages.filter(message=>message.toolCallId==="note-sibling").length,1);
  assert.equal(view.messages.filter(message=>message.role==="assistant" && message.content.some(block=>block.id==="note-sibling")).length,1);
  // A summary not bound to this raw lineage cannot authorize retirement/rebuild.
  const unbound=controller.project([{role:"compactionSummary",summary:"FOREIGN_SUMMARY"}],archive);
  assert.equal(unbound.outcome.status,"primary-unavailable");
  assert.match(JSON.stringify(unbound.messages),/FOREIGN_SUMMARY/);
});

test("existing workspace native archive route returns paged evidence without bridge dispatch",async()=>{
  const fixture=primaryFixture();let dispatches=0;
  const workspace=extension.createAppLevelTools({callMethod:async()=>{dispatches++;return {};}}).find(tool=>tool.name==="p7_workspace");
  const context={sessionManager:fixture.manager};
  const response=await workspace.execute("list-native",{op:"context_archive_list",limit:32},undefined,undefined,context);
  const listing=JSON.parse(response.content[0].text);
  assert.equal(listing.status,"ok");
  const ref=listing.items[2].ref;
  const first=JSON.parse((await workspace.execute("read-native",{op:"context_archive_read",ref,limit:7},undefined,undefined,context)).content[0].text);
  assert.equal(first.text.length,7);
  let full=first.text,next=first.next_start;
  while(next!==null) {const page=JSON.parse((await workspace.execute("read-native",{op:"context_archive_read",ref,start:next,limit:7},undefined,undefined,context)).content[0].text);full+=page.text;next=page.next_start;}
  assert.match(full,/FULL_EVIDENCE_0/);
  assert.equal(dispatches,0);
  assert.equal(Check(extension.P7_WORKSPACE_PARAMETERS,{op:"context_archive_read",ref,limit:16384}),true);
  assert.equal(Check(extension.P7_WORKSPACE_PARAMETERS,{op:"context_archive_read",ref,limit:16385}),false);
});

test("primary retirement preserves native system constraints and archives superseded standalone prose",()=>{
  const fixture=primaryFixture();
  fixture.messages.unshift({role:"system",content:"EXACT_NATIVE_SYSTEM",toolsAdded:[{name:"document_note",description:"note",parameters:{type:"object"}}],timestamp:0});
  fixture.messages.splice(4,0,{role:"assistant",content:[{type:"text",text:"SUPERSEDED_LONG_PROSE"}],stopReason:"stop",timestamp:2});
  fixture.entries.splice(0,fixture.entries.length,...fixture.messages.map((message,index)=>({type:"message",id:"entry-"+index,parentId:index?"entry-"+(index-1):null,message})));
  const {controller,archive}=admitPrimary(fixture),view=controller.project(fixture.messages,archive);
  assert.equal(view.outcome.status,"primary");
  assert.deepEqual(view.messages.find(message=>message.role==="system"),fixture.messages[0]);
  assert.doesNotMatch(JSON.stringify(view.messages),/SUPERSEDED_LONG_PROSE/);
});

const nativeSystem = () => ({role:"system",content:"",sections:{preamble:"native instructions",cwd:null},
  toolsAdded:[{name:"ipython",description:"execute",parameters:{type:"object",properties:{ratio:{type:"number",minimum:0.1}}},
    constrainedSampling:{type:"json_schema",strict:"require"}}],toolsRemoved:[{name:"old_tool"}],timestamp:1});

test("system section bytes and declaration metadata count without private native fields",()=>{
  const message=nativeSystem(),original=structuredClone(message);
  const decorated={...message,timestamp:999,details:{private:"PRIVATE_SYSTEM_SENTINEL"}};
  const small=new extension.ContextViewTelemetry().observe([decorated]);
  const expanded={...decorated,sections:{...message.sections,preamble:message.sections.preamble+"x".repeat(4000)}};
  const large=new extension.ContextViewTelemetry().observe([expanded]);
  const {timestamp,...modelFields}=message;
  assert.equal(small.other_bytes,Buffer.byteLength(JSON.stringify(modelFields),"utf8"));
  assert.equal(large.other_bytes-small.other_bytes,4000);
  assert.equal(small.unmeasurable_requests,0);
  assert.deepEqual(message,original);
});

test("native archive tool roundtrips ordered system sections and full tool changes",async()=>{
  const message={...nativeSystem(),details:{private:"PRIVATE_SYSTEM_SENTINEL"}},original=structuredClone(message);
  const entries=[{type:"message",id:"system-entry",parentId:null,message}];
  const context={sessionManager:{getSessionId:()=>"system-session",getBranch:()=>entries}};
  let dispatches=0;
  const tool=extension.createAppLevelTools({callMethod:async()=>{dispatches++;throw new Error("unexpected dispatch");}})
    .find(tool=>tool.name==="p7_workspace");
  const result=await tool.execute("read-system",{op:"context_archive_read",ref:{session_id:"system-session",entry_id:"system-entry"},limit:16384},undefined,undefined,context);
  const page=JSON.parse(result.content[0].text), archived=JSON.parse(page.text);
  const {timestamp,details,...modelFields}=message;
  assert.equal(page.status,"ok");
  assert.deepEqual(archived,modelFields);
  assert.deepEqual(Object.keys(archived.sections),Object.keys(message.sections));
  assert.equal(archived.toolsAdded[0].parameters.properties.ratio.minimum,0.1);
  assert.doesNotMatch(page.text,/PRIVATE_SYSTEM_SENTINEL|timestamp|details/);
  // Sorting the outer response, as a host transport may do, cannot alter the
  // ordered patch object held inside the archive's opaque JSON text.
  const transported=JSON.parse(JSON.stringify(Object.fromEntries(Object.entries(page).sort(([a],[b])=>a.localeCompare(b)))));
  assert.deepEqual(Object.keys(JSON.parse(transported.text).sections),Object.keys(message.sections));
  assert.equal(dispatches,0);
  assert.deepEqual(message,original);
});

test("primary reconstruction does not revive a hidden system with the same empty content",()=>{
  const fixture=primaryFixture(),hidden=nativeSystem(),visible={...nativeSystem(),sections:{preamble:"new instructions",cwd:null},toolsRemoved:[{name:"other_tool"}]};
  fixture.messages.unshift(hidden,visible);
  fixture.entries.splice(0,fixture.entries.length,...fixture.messages.map((message,index)=>({type:"message",id:"entry-"+index,parentId:index?"entry-"+(index-1):null,message})));
  const {controller,archive}=admitPrimary(fixture),view=controller.project(fixture.messages.filter(message=>message!==hidden),archive);
  assert.equal(view.outcome.status,"primary");
  assert.deepEqual(view.messages.filter(message=>message.role==="system"),[visible]);
});

test("trusted IPython error metadata and transport unknown receipts protect original computations",async()=>{
  for(const execution_status of ["python-error","interrupted","lost"]) {
    const tool=extension.createIpythonTool({execute:async()=>({content:[{type:"text",text:JSON.stringify({execution_status,generation:"g1",stdout:"not a marker",kernel_exports:[]})}],details:{}})});
    const result=await tool.execute("error-cell",{code:"raise ValueError()"});
    assert.deepEqual(result.details.context_interaction,{version:"asterion.prime-context-interaction/v1",effect:execution_status==="python-error"?"settled":"unknown",feedback:"negative"});
  }
  const tool=extension.createIpythonTool({execute:async()=>{throw new Error("PRIVATE_HOST_PATH");}});
  const result=await tool.execute("uncertain-cell",{code:"mutate()"}).catch(()=>({missing_receipt:true}));
  assert.equal(result.isError,true);
  assert.equal(result.details.context_interaction.effect,"unknown");
  assert.doesNotMatch(JSON.stringify(result),/PRIVATE_HOST_PATH/);
});
