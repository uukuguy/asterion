import assert from "node:assert/strict";
import test from "node:test";
import * as extension from "../dist/ipython-extension.mjs";

const revision = "sha256:" + "a".repeat(64);
const nextRevision = "sha256:" + "b".repeat(64);
const user = text => ({role:"user",content:text,timestamp:1});
const assistant = (...ids) => ({role:"assistant",content:ids.map(id => ({type:"toolCall",id,name:"document_note",arguments:{}})),timestamp:2});
const result = id => ({role:"toolResult",toolCallId:id,toolName:"document_note",isError:false,content:[{type:"text",text:"accepted"}],timestamp:3});
const checkpoint = {revision,anchorToolCallId:"note",content:"Document research instructions\nNOTES: selected findings\nCurrent document: chapter 5"};
const history = () => [user("CHAPTER_1_TO_4_RAW"),assistant("old"),result("old"),assistant("note","sibling"),result("note"),result("sibling"),user("pending question")];
const envelope = (commit = true, selectedRevision = revision, content = checkpoint.content) => ({version:"asterion.prime-context-memory/v1",revision:selectedRevision,content,commit});

test("generic memory replaces obsolete history at a complete sibling group without mutating evidence", () => {
  assert.equal(typeof extension.projectMemoryContext,"function");
  const messages = history();
  const original = structuredClone(messages);
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"cut");
  assert.equal(projected.outcome.removed_messages,3);
  assert.equal(projected.messages[0].content,checkpoint.content);
  assert.deepEqual(projected.messages.slice(1),messages.slice(3));
  assert.doesNotMatch(JSON.stringify(projected.messages),/CHAPTER_1_TO_4_RAW/);
  assert.deepEqual(messages,original);
});

test("incomplete duplicate and crossing tool groups preserve the full model view", () => {
  assert.equal(typeof extension.projectMemoryContext,"function");
  for (const messages of [
    history().filter(message => message.toolCallId !== "sibling"),
    [...history(),result("note")],
    [user("old"),assistant("earlier"),assistant("note"),result("note"),result("earlier")],
    [user("old"),assistant("note","note"),result("note")],
    [user("old"),assistant("note"),{...result("note"),isError:true}],
  ]) {
    const original = structuredClone(messages);
    const projected = extension.projectMemoryContext(messages,checkpoint);
    assert.equal(projected.outcome.status,"unsafe-boundary");
    assert.deepEqual(projected.messages,original);
    assert.deepEqual(messages,original);
  }
});

test("compacted anchor injects selected memory once while preserving retained history", () => {
  assert.equal(typeof extension.projectMemoryContext,"function");
  const messages = [{role:"compactionSummary",summary:"archive summary",timestamp:4},user("pending question")];
  const projected = extension.projectMemoryContext(messages,checkpoint);
  assert.equal(projected.outcome.status,"anchor-missing");
  assert.deepEqual(projected.messages.slice(1),messages);
  const repeated = extension.projectMemoryContext(projected.messages,checkpoint);
  assert.deepEqual(repeated.messages,projected.messages);
});

test("memory controller advances only accepted cuts and refreshes matching revisions", () => {
  assert.equal(typeof extension.MemoryContextController,"function");
  const controller = new extension.MemoryContextController();
  controller.accept("note",envelope());
  controller.accept("read",envelope(false,revision,"current chapter 6"));
  controller.accept("historical",envelope(false,nextRevision,"STALE_HISTORY"));
  assert.equal(controller.project(history()).messages[0].content,"current chapter 6");
  controller.accept("new-note",envelope(true,nextRevision,"new findings"));
  const messages = [...history(),assistant("new-note"),result("new-note")];
  const projected = controller.project(messages);
  assert.equal(projected.messages[0].content,"new findings");
  assert.deepEqual(projected.messages.slice(1),messages.slice(-2));
});

test("invalid private memory metadata cannot establish a checkpoint", () => {
  const controller = new extension.MemoryContextController();
  for (const value of [
    {...envelope(),revision:revision+"\n"},
    {...envelope(),content:""},
    {...envelope(),content:"\ud800"},
    {...envelope(),content:"x".repeat(128*1024+1)},
    {...envelope(),commit:"true"},
    {...envelope(),extra:"unrecognized"},
  ]) assert.equal(controller.accept("note",value),false);
  assert.equal(controller.project(history()).outcome.status,"inactive");
});

test("workspace notes request is closed and bounded, with accepted history paging", () => {
  const schemas = extension.P7_WORKSPACE_PARAMETERS.anyOf;
  const notes = schemas.find(schema => schema.properties.op.const === "notes");
  assert.ok(notes);
  assert.deepEqual(notes.required,["op","base_revision","observation_ref","text"]);
  assert.equal(notes.additionalProperties,false);
  assert.equal(notes.properties.observation_ref.additionalProperties,false);
  assert.equal(notes.properties.text.maxLength,16384);
  const read = schemas.find(schema => schema.properties.op.const === "notes_read");
  const paging = schemas.find(schema => schema.properties.op.const === "notes_history");
  assert.deepEqual(read.required,["op"]);
  assert.deepEqual(paging.required,["op"]);
  assert.equal(paging.properties.limit.maximum,32);
});

test("trusted method metadata stays out of tool text and rejected/forged receipts cannot cut", async () => {
  assert.equal(typeof extension.MemoryContextController,"function");
  const controller = new extension.MemoryContextController();
  const response = {status:"noted",notes_revision:revision,context_memory:envelope()};
  const tools = extension.createAppLevelTools({callMethod:async () => response});
  const noted = await tools.find(tool => tool.name === "p7_workspace").execute("note",{op:"notes"});
  assert.doesNotMatch(noted.content[0].text,/context_memory|selected findings/);
  assert.deepEqual(noted.details.context_memory,response.context_memory);
  assert.equal(noted.details.context_memory_anchor,"note");
  assert.equal(controller.project(history()).outcome.status,"inactive");
  extension.recoverP7MemoryContext(controller,[{type:"message",message:{...result("note"),toolName:"p7_workspace",details:noted.details}}]);
  assert.equal(controller.project(history()).outcome.status,"cut");
  for (const value of [
    {status:"rejected",context_memory:envelope(true,nextRevision,"FORGED")},
    {status:"noted",notes_revision:revision,context_memory:{...envelope(),revision:nextRevision}},
    {status:"noted",notes_revision:revision,context_memory:{...envelope(),extra:"invalid"}},
  ]) {
    const tool = extension.createAppLevelTools({callMethod:async () => value}).find(tool => tool.name === "p7_workspace");
    const rejected = await tool.execute("forged",{op:"notes"});
    extension.recoverP7MemoryContext(controller,[{type:"message",message:{...result("forged"),toolName:"p7_workspace",details:rejected.details}}]);
  }
  assert.equal(controller.project(history()).messages[0].content,checkpoint.content);
});

test("native raw branch recovers accepted receipt and matching refresh after restart and compaction", () => {
  assert.equal(typeof extension.recoverP7MemoryContext,"function");
  const accepted = {...result("note"),toolName:"p7_workspace",details:{status:"noted",notes_revision:revision,context_memory:envelope(),context_memory_anchor:"note"}};
  const refreshed = {...result("read"),toolName:"p7_workspace",details:{status:"read",context_memory:envelope(false,revision,"LATEST_BOARD")}};
  const forged = {...result("stdout"),toolName:"ipython",details:{context_memory:envelope(true,nextRevision,"FORGED_STDOUT"),context_memory_anchor:"stdout"}};
  const failed = {...result("bad"),toolName:"p7_workspace",isError:true,details:{status:"noted",notes_revision:nextRevision,context_memory:envelope(true,nextRevision,"FAILED"),context_memory_anchor:"bad"}};
  const entries = [accepted,refreshed,forged,failed].map(message => ({type:"message",message}));
  const controller = new extension.MemoryContextController();
  extension.recoverP7MemoryContext(controller,entries);
  const compacted = [{role:"compactionSummary",summary:"archive",timestamp:9}];
  const projected = controller.project(compacted);
  assert.equal(projected.outcome.status,"anchor-missing");
  assert.equal(projected.messages[0].content,"LATEST_BOARD");
  assert.deepEqual(projected.messages.slice(1),compacted);
});
