import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import test from "node:test";
import * as extension from "../dist/ipython-extension.mjs";

const version = "asterion.prime-tool-state-view/v1";
const proposal = replacement_text => ({version,state_key:"document.current-board",replacement_text});
const hash = text => "sha256:"+createHash("sha256").update(text,"utf8").digest("hex");
const call = (id,name="document_action") => ({role:"assistant",content:[
  {type:"text",text:"Hypothesis and program code must survive"},
  {type:"toolCall",id,name,arguments:{code:"model = compute()"}},
]});
const result = (id,body,short,name="document_action") => ({role:"toolResult",toolCallId:id,toolName:name,
  isError:false,content:[{type:"text",text:body}],details:{tool_state_view:{
    ...proposal(short),original_text_sha256:hash(body),tool_call_id:id,tool_name:name,
  }}});
const messages = () => [
  {role:"user",content:"operator instruction"},call("old"),
  result("old","board: "+"x".repeat(4096)+"; feedback: mismatch","board archived; feedback: mismatch"),
  call("new"),result("new","board: "+"y".repeat(4096)+"; feedback: matched","board archived; feedback: matched"),
];

test("only older paired trusted state changes while latest and research evidence stay complete", () => {
  const source = messages();
  const original = structuredClone(source);
  const projected = extension.projectToolStateViews(source);
  assert.equal(projected[2].content[0].text,"board archived; feedback: mismatch");
  assert.deepEqual(projected[4],original[4]);
  assert.deepEqual(projected.filter(message => message.role !== "toolResult"),
    original.filter(message => message.role !== "toolResult"));
  assert.equal(projected[2].toolCallId,"old");
  assert.equal(projected[2].toolName,"document_action");
  assert.deepEqual(source,original);
  assert.deepEqual(extension.projectToolStateViews(projected),projected);
});

test("projection reports only bounded replacement counts and byte reduction", () => {
  const source=messages();
  const {messages:projected,outcome}=extension.projectToolStateViewContext(source);
  assert.deepEqual(projected,extension.projectToolStateViews(source));
  assert.equal(outcome.replaced_results,1);
  assert.equal(outcome.replaced_bytes,Buffer.byteLength(source[2].content[0].text,"utf8")
    -Buffer.byteLength(projected[2].content[0].text,"utf8"));
  assert.deepEqual(Object.keys(outcome).sort(),["replaced_bytes","replaced_results"]);
});

test("invalid hashes metadata errors and ambiguous pairs leave original messages unchanged", () => {
  const variants = [
    source => {source[2].details.tool_state_view.original_text_sha256=hash("forged");},
    source => {source[2].details.tool_state_view.extra="unknown";},
    source => {source[2].details.tool_state_view.tool_call_id="other";},
    source => {source[2].details.tool_state_view.tool_name="other";},
    source => {source[2].isError=true;},
    source => {source.splice(1,1);},
    source => {source.splice(1,0,call("old"));},
    source => {source.splice(3,0,structuredClone(source[2]));},
    source => {source[1].content[1].name="wrong";},
    source => {source[2].content.push({type:"image",data:"private"});},
    source => {source[2].details.tool_state_view.replacement_text="z".repeat(5000);},
    source => {source[2].details.tool_state_view.replacement_text="\ud800";},
    source => {source[4].isError=true;},
    source => {source[3].content[1].name="wrong";},
  ];
  for (const change of variants) {
    const source = messages(); change(source);
    const original = structuredClone(source);
    assert.deepEqual(extension.projectToolStateViews(source),original);
    assert.deepEqual(source,original);
  }
});

test("state key is additionally scoped by native tool name", () => {
  const source = messages();
  source[3]=call("new","other_tool");
  source[4]=result("new",source[4].content[0].text,"short","other_tool");
  assert.deepEqual(extension.projectToolStateViews(source),source);
});

test("method admission strips proposals and binds native metadata to exact visible text", async () => {
  const response = {status:"recorded",feedback:[{actual:"matched"}],observation:{frame:"x".repeat(4096)},
    tool_state_view:proposal(JSON.stringify({status:"recorded",feedback:[{actual:"matched"}],
      observation:{frame_read:"read-only evidence"}}))};
  const tool = extension.createAppLevelTools({callMethod:async () => response})
    .find(tool => tool.name === "p7_execute_plan");
  const admitted = await tool.execute("action",{});
  assert.doesNotMatch(admitted.content[0].text,/tool_state_view|original_text_sha256/);
  assert.equal(admitted.details.tool_state_view.original_text_sha256,hash(admitted.content[0].text));
  assert.equal(admitted.details.tool_state_view.tool_call_id,"action");
  assert.equal(admitted.details.tool_state_view.tool_name,"p7_execute_plan");
  for (const change of [{status:"rejected"},{status:"uncertain"},{processing_blocked:true},
    {environment_result_unknown:true},{uncertain_step:{action:"unknown"}},
    {stop_reason:"processing-failed"},{stop_reason:"environment-result-unknown"},
    {tool_state_view:{...proposal("short"),extra:"unknown"}}]) {
    const rejected = await extension.createAppLevelTools({callMethod:async () => ({...response,...change})})
      .find(tool => tool.name === "p7_execute_plan").execute("unsafe",{});
    assert.equal(Object.hasOwn(rejected.details,"tool_state_view"),false);
    assert.doesNotMatch(rejected.content[0].text,/tool_state_view/);
  }
});

test("proposal and native metadata bounds fail closed", () => {
  const original="x".repeat(4096);
  for (const value of [
    {...proposal("short"),version:"unknown"}, {...proposal("short"),state_key:"k".repeat(1025)},
    {...proposal("short"),replacement_text:"r".repeat(128*1024+1)},
    {...proposal("short"),extra:true}, {...proposal("short"),state_key:"\ud800"},
  ]) assert.equal(extension.admitToolStateView(value,original,"id","tool"),undefined);
  assert.equal(extension.admitToolStateView(proposal("short"),"x".repeat(128*1024+1),"id","tool"),undefined);
});

test("registered context hook projects marked state without notes and keeps current branch pairing", () => {
  let hook;
  extension.registerP7MemoryContext({on:(_event,handler) => {hook=handler;}});
  const source=messages();
  const projected=hook({type:"context",messages:source},{sessionManager:{getBranch:() =>
    source.map(message => ({type:"message",message}))}}).messages;
  assert.equal(projected[2].content[0].text,"board archived; feedback: mismatch");
  const unpaired=source.slice(2).map(message => ({type:"message",message}));
  assert.deepEqual(hook({type:"context",messages:source},{sessionManager:{getBranch:() => unpaired}}).messages,source);
});


test("context composition telemetry measures stale-state replacement and appended snapshot together", () => {
  let hook; const records=[];
  extension.registerP7MemoryContext({on:(_event,handler) => {hook=handler;}},numbers=>records.push(numbers));
  const source=messages();
  const snapshot={type:"message",message:{role:"toolResult",toolCallId:"read",toolName:"p7_workspace",isError:false,
    content:[{type:"text",text:"read"}],details:{status:"read",context_memory:{version:"asterion.prime-context-memory/v2",
      revision:null,content:"LATEST_SNAPSHOT_SENTINEL",commit:false}}}};
  const original=structuredClone(source);
  const branch=[...source.map(message=>({type:"message",message})),snapshot];
  const projected=hook({type:"context",messages:source},{sessionManager:{getBranch:()=>branch}}).messages;
  assert.equal(projected[2].content[0].text,"board archived; feedback: mismatch");
  assert.equal(projected.at(-1).content,"LATEST_SNAPSHOT_SENTINEL");
  const raw=new extension.ContextViewTelemetry().observe(source);
  assert.ok(records[0].tool_result_bytes<raw.tool_result_bytes);
  assert.deepEqual(records[0],new extension.ContextViewTelemetry().observe(projected));
  assert.deepEqual(source,original);
  assert.doesNotMatch(JSON.stringify(records),/SENTINEL|board|feedback|compute/);
});
