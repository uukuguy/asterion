import assert from "node:assert/strict";
import test from "node:test";
import {Check} from "typebox/value";
import * as extension from "../dist/ipython-extension.mjs";

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
  assert.deepEqual(projected.messages.slice(-2),messages.slice(-2));
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
  const bounded = await import("../dist/ipython-extension.mjs?diagnostic-budget");
  const hooks = [];
  for (let index=0;index<2;index++) {
    assert.equal(bounded.registerP7MemoryContext({on:(event,handler) => {
      assert.equal(event,"context");
      hooks.push(handler);
    }}),true);
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
