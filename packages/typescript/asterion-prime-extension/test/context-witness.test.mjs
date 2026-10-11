import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { constants as bufferConstants } from "node:buffer";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer, createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import * as extension from "../dist/ipython-extension.mjs";

const launch = "a".repeat(64);
const command = "b".repeat(64);
const authority = "c".repeat(64);
const base = { protocol: "asterion.prime-context-witness/v1", launch_nonce: launch, command_nonce: command, authority_sha256: authority };
const artifact = pathToFileURL(resolve("dist/ipython-extension.mjs")).href;
// These tests require a historical private compaction harness. That harness
// was removed with the legacy gateway surface, and installed Pi no longer exposes the
// `_performCompaction` seam used by the witness harness. Keep the protocol and
// registration tests below active, but do not replace the missing mechanics
// with a local fake.
const harnessPath = resolve("test/context-witness-harness.mjs");
const externalMechanicsSkip = !existsSync(harnessPath)
  ? "external Pi mechanics unavailable: the compatibility harness is absent"
  : false;
// The Python host delivers inherited prompt material on the arm frame.
// This fixture proves transport parity, not actual native request certification.
const material = JSON.parse(readFileSync(
  resolve("../../../tests/fixtures/asterion_prime_p1/v1/summarization-parity.json"))).material;
const arm = {...base, phase: "arm", summarization: material, compaction_policy:
  {max_total_tokens:262144,max_frame_bytes:16777216,max_material_bytes:65536,config_source:"framework-default"}};
const secret = "private-sentinel-prompt-and-summary";

async function pair() {
  const root = mkdtempSync(join(tmpdir(), "asterion-context-witness-"));
  const server = createServer();
  await new Promise((done) => server.listen(join(root, "private.sock"), done));
  const accepted = new Promise((done) => server.once("connection", done));
  const client = createConnection(join(root, "private.sock"));
  await new Promise((done) => client.once("connect", done));
  const peer = await accepted;
  peer.on("error", () => {});
  return { client, peer, close() { client.destroy(); peer.destroy(); server.close(); rmSync(root, { recursive: true, force: true }); } };
}

function frame(value) {
  const raw = Buffer.from(extension.canonicalJson(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(raw.length);
  return Buffer.concat([header, raw]);
}

function readFrame(socket) {
  return new Promise((done, reject) => {
    let pending = Buffer.alloc(0);
    const timer = setTimeout(() => reject(new Error("test peer timed out")), 15000);
    function data(chunk) {
      pending = Buffer.concat([pending, chunk]);
      if (pending.length < 4 || pending.length < 4 + pending.readUInt32BE(0)) return;
      socket.off("data", data);
      clearTimeout(timer);
      try { done(JSON.parse(pending.subarray(4).toString())); } catch (error) { reject(error); }
    }
    socket.on("data", data);
  });
}

function run(socketPair, options = {}) {
  const child = spawn(process.execPath, [resolve("test/context-witness-harness.mjs"), JSON.stringify(options)], { stdio: ["ignore", "pipe", "pipe", socketPair.client] });
  let stdout = "", stderr = "";
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  return new Promise((done, reject) => { child.once("error", reject); child.once("exit", (code) => {
    if (code !== 0 || stderr) reject(new Error("witness test child failed: " + stderr));
    else { try { done(JSON.parse(stdout)); } catch(error) { reject(error); } }
  }); });
}

test("witness and cross-language encoder exports exist", () => {
  assert.equal(typeof extension.registerContextWitness, "function", "authenticated witness hooks are missing");
  assert.equal(typeof extension.countRebuiltContext, "function");
});

test("shared fixture has byte-for-byte TypeScript projection parity", () => {
  assert.equal(typeof extension.projectPrimeContext, "function", "shared projection export is missing");
  const fixture=JSON.parse(readFileSync(resolve("../../../tests/fixtures/asterion_prime_p1/v1/context-parity.json")));
  for(const item of fixture.cases){
    const projection=extension.projectPrimeContext(item.raw_messages);
    assert.deepEqual(projection,item.projection);
    const canonical=extension.canonicalJson(projection);
    assert.equal(canonical,item.canonical_json);
    assert.equal(extension.countRebuiltContext(projection),item.asterion_units);
    assert.equal(createHash("sha256").update(canonical).digest("hex"),item.sha256);
  }
});

test("reject cancels before either real built-in summary callback or appendCompaction", {skip: externalMechanicsSkip}, async () => {
  assert.equal(typeof extension.registerContextWitness,"function");
  const sockets=await pair();
  try {
    const running=run(sockets);
    sockets.peer.write(frame(arm));
    const proposal=await readFrame(sockets.peer);
    assert.equal(proposal.phase,"proposal");
    assert(proposal.private_diagnostics.tokensBefore>0);
    assert(!Object.hasOwn(proposal,"tokensBefore"));
    sockets.peer.write(frame({...base,phase:"decision",status:"reject"}));
    const result=await running;
    assert.equal(result.calls,0);assert.equal(result.appends,0);
    assert.deepEqual(result.order,["session_before_compact"]);
    assert.equal(result.error,"Compaction cancelled");
    assert(!JSON.stringify(result).includes(secret));
  } finally{sockets.close();}
});

test("approve permits only Pi built-in summary then one persisted frame and ack", {skip: externalMechanicsSkip}, async () => {
  assert.equal(typeof extension.registerContextWitness,"function");
  const sockets=await pair();
  try {
    const running=run(sockets);
    sockets.peer.write(frame(arm));
    const proposal=await readFrame(sockets.peer);
    assert.equal(proposal.phase,"proposal");
    sockets.peer.write(frame({...base,phase:"decision",status:"approve"}));
    const persisted=await Promise.race([readFrame(sockets.peer),running.then(result=>{throw new Error(JSON.stringify(result))})]);
    assert.equal(persisted.phase,"persisted");
    assert.equal(persisted.first_kept_entry_id,proposal.first_kept_entry_id);
    assert.equal(persisted.compaction_entry.summary,persisted.summary);
    assert.equal(persisted.compaction_entry.fromHook,false);
    assert(extension.countRebuiltContext(persisted.post_context_projection)<proposal.pre_units);
    sockets.peer.write(frame({...base,phase:"ack"}));
    const result=await running;
    assert.equal(result.error,null);assert.equal(result.calls,2);assert.equal(result.appends,1);
    assert.deepEqual(result.captures.map(value=>value.sha256),[proposal.main_summary_request,proposal.turn_prefix_summary_request].map(value=>createHash("sha256").update(value).digest("hex")));
    assert.deepEqual(result.captures.map(value=>value.max_tokens),[3276,2048]);
    assert.deepEqual(result.order,["session_before_compact","summary","summary","append","session_compact"]);
  } finally{sockets.close();}
});

test("bad decision frames cancel and permanently fence before mutation", {skip: externalMechanicsSkip}, async t => {
  assert.equal(typeof extension.registerContextWitness,"function");
  for(const kind of ["wrong-command","wrong-launch","wrong-authority","duplicate","malformed","oversized","closed","missing"]){
    await t.test(kind,async()=>{
      const sockets=await pair();
      try{
        const running=run(sockets,{timeoutMs:150});
        sockets.peer.write(frame(arm));
        await readFrame(sockets.peer);
        let reply={...base,phase:"decision",status:"approve"};
        if(kind==="wrong-command")reply.command_nonce="d".repeat(64);
        if(kind==="wrong-launch")reply.launch_nonce="d".repeat(64);
        if(kind==="wrong-authority")reply.authority_sha256="d".repeat(64);
        if(kind==="duplicate")sockets.peer.write(Buffer.concat([frame(reply),frame(reply)]));
        else if(kind==="malformed")sockets.peer.write(Buffer.from([0,0,0,1,123]));
        else if(kind==="oversized")sockets.peer.write(Buffer.from([127,255,255,255]));
        else if(kind==="closed")sockets.peer.destroy();
        else if(kind!=="missing")sockets.peer.write(frame(reply));
        const result=await running;
        assert.equal(result.calls,0);assert.equal(result.appends,0);assert.equal(result.fenced,true);
        assert(!JSON.stringify(result).includes(secret));
      }finally{sockets.close();}
    });
  }
});

test("short native source never pads or calls summary", {skip: externalMechanicsSkip}, async()=>{
  assert.equal(typeof extension.registerContextWitness,"function");
  const sockets=await pair();
  try {const result=await run(sockets,{short:true});assert.equal(result.calls,0);assert.equal(result.appends,0);assert.deepEqual(result.order,[]);}
  finally{sockets.close();}
});

test("failed environment or tool registration closes the context descriptor", async t=>{
  for(const kind of ["missing-nonce","missing-ipython-fd","invalid-api","registration-failure","closed-descriptor"]){
    await t.test(kind,async()=>{
      const sockets=await pair();
      try{
        const source=`
          import register, {coreOnlyModule} from ${JSON.stringify(artifact)};
          import {fstatSync} from 'node:fs';
          const kind=process.argv[1];
          process.env.ASTERION_PRIME_IPYTHON_TOOL_REGISTRY=JSON.stringify(coreOnlyModule.registry);
          const deps=Object.freeze({buildSessionContext(){return {messages:[]};},getCurrentSystemMessage(){return undefined;},convertToLlm(){return [];},serializeConversation(){return "";}});
          if(kind!=='missing-ipython-fd')process.env.ASTERION_PRIME_IPYTHON_FD='999998';
          process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD=kind==='closed-descriptor'?'999999':'3';
          process.env.ASTERION_PRIME_IPYTHON_COMPACTION_POLICY=JSON.stringify({config_source:'framework-default',max_frame_bytes:16777216,max_material_bytes:65536,max_total_tokens:262144});
          if(kind!=='missing-nonce')process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE=${JSON.stringify(launch)};
          let message=null,toolReached=false;
          try{register(kind==='invalid-api'?null:{on(){},registerTool(){toolReached=true;throw new Error(${JSON.stringify(secret)})}},deps)}catch(error){message=error.message}
          await new Promise(done=>setImmediate(done));
          let closed=false;try{fstatSync(kind==='closed-descriptor'?999999:3)}catch{closed=true}
          process.stdout.write(JSON.stringify({closed,message,toolReached,removed:process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD===undefined}));
          process.exit(0);
        `;
        const child=spawnSync(process.execPath,["--input-type=module","-e",source,kind],{stdio:["ignore","pipe","pipe",sockets.client._handle.fd],encoding:"utf8",timeout:3000});
        assert.equal(child.status,0);assert.equal(child.stderr,"");
        const result=JSON.parse(child.stdout);
        assert.equal(result.closed,true);assert.equal(result.removed,true);
        assert.equal(result.toolReached,kind==="registration-failure");
        assert.equal(result.message,"Asterion ipython bridge is unavailable");
      }finally{sockets.close();}
    });
  }
});

test("proposal backpressure times out before summary or append", {skip: externalMechanicsSkip}, async()=>{
  const sockets=await pair();
  try{
    sockets.peer.pause();
    const running=run(sockets,{backpressure:true,timeoutMs:100});
    sockets.peer.write(frame(arm));
    const result=await running;
    assert.equal(result.fenced,true);assert.equal(result.calls,0);assert.equal(result.appends,0);
  }finally{sockets.close();}
});

test("missing post-mutation ack fences the observer", {skip: externalMechanicsSkip}, async()=>{
  const sockets=await pair();
  try{
    const running=run(sockets,{timeoutMs:150});
    sockets.peer.write(frame(arm));
    await readFrame(sockets.peer);
    sockets.peer.write(frame({...base,phase:"decision",status:"approve"}));
    await readFrame(sockets.peer);
    const result=await running;
    assert.equal(result.calls,2);assert.equal(result.appends,1);assert.equal(result.fenced,true);
    assert.equal(result.error,"Asterion context witness is unavailable");
  }finally{sockets.close();}
});


test("system projection rejects ambiguous and nonfinite metadata", () => {
  const system = extension.projectPrimeContext([{role:"system",content:"instructions",sections:{first:"A"}}]).messages[0];
  for (const changes of [
    {extra:"private-sentinel"},
    {sections:[{name:"same",value:"A"},{name:"same",value:null}]},
    {tools_added_json:'[{"name":"x","name":"y"}]'},
    {tools_added_json:'[{"name":"x","parameters":{"minimum":1e999}}]'},
    {tools_removed_json:'{}'},
  ]) assert.throws(() => extension.countRebuiltContext({format:"asterion.prime-context-projection/v1",
    system_prompt:"",messages:[{...system,...changes}]}), /invalid Prime context/);
  assert.throws(() => extension.projectPrimeContext([{role:"system",content:[],sections:null}]), /invalid Prime context/);
});

const policy = {max_total_tokens: 262144, max_frame_bytes: 16777216, max_material_bytes: 65536};
const deps = Object.freeze({buildSessionContext(){return {messages:[]};},
  getCurrentSystemMessage(){return undefined;},convertToLlm(){return [];},serializeConversation(){return "";}});

test("constructor rejects policy structural bounds and alias disagreements before owning socket", async () => {
  const sockets = await pair();
  try {
    for (const changes of [
      {policy:{...policy,max_frame_bytes:2 ** 32}},
      {policy:{...policy,max_frame_bytes:Math.min(0xffffffff,bufferConstants.MAX_LENGTH-4)+1}},
      {policy:{...policy,max_material_bytes:policy.max_frame_bytes}},
      {policy:{...policy,max_total_tokens:Number.MAX_SAFE_INTEGER + 1}},
      {policy:{...policy,extra:1}},
      {policy,maxFrameBytes:8192},
      {policy,configSource:'invalid'},
    ]) assert.throws(() => new extension.ContextWitness(deps, {
      descriptor:sockets.client._handle.fd,launchNonce:launch,...changes}), /resource limit|unavailable/);
  } finally {sockets.close();}
});

function capacityChild(sockets, options = {}) {
  const source = `
    import {registerContextWitness} from ${JSON.stringify(artifact)};
    const options=JSON.parse(process.argv[1]);
    const deps=Object.freeze({
      buildSessionContext:entries=>({messages:entries.at(-1)?.type==='compaction'
        ? [{role:'compactionSummary',summary:entries.at(-1).summary??'',retainedMessageCount:0}]:[]}),
      getCurrentSystemMessage:()=>undefined,convertToLlm:messages=>messages,
      serializeConversation:()=> 'x'.repeat(options.conversation ?? 10000)});
    const hooks=new Map();
    const witness=registerContextWitness({on:(name,hook)=>hooks.set(name,hook)},deps,
      {descriptor:3,launchNonce:${JSON.stringify(launch)},policy:options.policy,
       configSource:options.source,maxFrameBytes:options.maxFrameBytes,timeoutMs:1500});
    const concat=Buffer.concat;
    let concats=0;
    if(options.countConcat)Buffer.concat=(...args)=>{concats++;return concat(...args)};
    const event={type:'session_before_compact',
      preparation:{settings:{enabled:false,reserveTokens:16384,keepRecentTokens:256},
        firstKeptEntryId:'entry-2',messagesToSummarize:[{role:'user',content:[{type:'text',text:'hello'}]}],
        turnPrefixMessages:[],isSplitTurn:false,tokensBefore:12},
      branchEntries:[{id:'entry-1',parentId:null,type:'message'},
        {id:'entry-2',parentId:'entry-1',type:'message'}]};
    const result=await hooks.get('session_before_compact')(event, {getSystemPrompt:()=> 'system'});
    let followupCancel;
    if(options.followupConversation !== undefined && result?.cancel && !witness.closed) {
      options.conversation=options.followupConversation;
      const followup=await hooks.get('session_before_compact')(event, {getSystemPrompt:()=> 'system'});
      followupCancel=followup?.cancel??false;
    }
    let persistedError;
    if(options.persistedSummary && result===undefined) {
      const entry={type:'compaction',id:'entry-3',parentId:'entry-2',timestamp:'2000-01-01T00:00:00.000Z',
        firstKeptEntryId:'entry-2',summary:'s'.repeat(options.persistedSummary),tokensBefore:12,fromHook:false};
      try{await hooks.get('session_compact')({type:'session_compact',fromExtension:false,compactionEntry:entry},
        {getSystemPrompt:()=> 'system',sessionManager:{getBranch:()=> [...event.branchEntries,entry]}})}
      catch(error){persistedError=error.message}
    }
    process.stdout.write(JSON.stringify({cancel:result?.cancel??false,closed:witness.closed,concats,
      ...followupCancel!==undefined?{followupCancel}:{},...persistedError?{persistedError}:{}}));
    process.exit(0);`;
  const child=spawn(process.execPath,['--input-type=module','-e',source,JSON.stringify(options)],
    {stdio:['ignore','pipe','pipe',sockets.client]});
  let stdout='',stderr='';
  child.stdout.on('data',chunk=>{stdout+=chunk});
  child.stderr.on('data',chunk=>{stderr+=chunk});
  return new Promise((done,reject)=>{
    child.once('error',reject);
    child.once('exit',code=>{try{assert.equal(code,0);assert.equal(stderr,'');done(JSON.parse(stdout))}catch(error){reject(error)}});
  });
}

async function proposalCapacity(policyValue, conversation=10000, summaryMaterial=material) {
  const sockets=await pair();
  try {
    const result=capacityChild(sockets,{policy:policyValue,conversation,source:'application'});
    const observed=readFrame(sockets.peer);
    sockets.peer.write(frame({...arm,summarization:summaryMaterial,
      compaction_policy:{...policyValue,config_source:'application'}}));
    const reply=await observed;
    if(reply.phase==='proposal')sockets.peer.write(frame({...base,phase:'decision',status:'reject'}));
    return {reply,outcome:await result};
  } finally {sockets.close();}
}

test('whole proposal frame capacity has inclusive boundaries and no hidden 1 MiB ceiling',async()=>{
  const initial=await proposalCapacity(policy);
  const bytes=Buffer.byteLength(extension.canonicalJson(initial.reply));
  for(const cap of [bytes-1,bytes,bytes+1]) {
    const selected={...policy,max_frame_bytes:cap,max_material_bytes:8000};
    const {reply,outcome}=await proposalCapacity(selected);
    assert.equal(reply.phase,cap<bytes?'limit':'proposal');
    if(cap<bytes)assert.deepEqual(reply.limit_diagnostic,{limit_code:'witness-frame-limit',
      phase:'admission',action:'rejected',observed:bytes,limit:cap,unit:'bytes',
      measurement:'exact',config_source:'application'});
    assert.equal(outcome.cancel,true);
    assert.equal(outcome.closed,false);
  }
  const large=await proposalCapacity(policy,1024*1024+1);
  assert.equal(large.reply.phase,'proposal');
  assert(Buffer.byteLength(extension.canonicalJson(large.reply))>1024*1024);
});

test('injected material capacity reports exact canonical byte measurement',async()=>{
  const selected={...policy,max_material_bytes:12000};
  const initial=Buffer.byteLength(extension.canonicalJson(material));
  for(const size of [11999,12000,12001]) {
    const padded={...material,system_prompt:material.system_prompt+'x'.repeat(size-initial)};
    const {reply,outcome}=await proposalCapacity(selected,10000,padded);
    assert.equal(reply.phase,size>12000?'limit':'proposal');
    if(size>12000)assert.deepEqual(reply.limit_diagnostic,{limit_code:'summarization-material-limit',
      phase:'admission',action:'rejected',observed:size,limit:12000,unit:'bytes',
      measurement:'exact',config_source:'application'});
    assert.equal(outcome.closed,false);
  }
});

test('authenticated capacity refusal permits a fresh smaller transaction on the same channel',async()=>{
  const sockets=await pair();
  const selected={...policy,max_frame_bytes:20000,max_material_bytes:8000};
  try {
    const result=capacityChild(sockets,{policy:selected,conversation:50000,
      followupConversation:1,source:'application'});
    const first=readFrame(sockets.peer);
    sockets.peer.write(frame({...arm,compaction_policy:{...selected,config_source:'application'}}));
    assert.equal((await first).phase,'limit');
    const nextBase={...base,command_nonce:'d'.repeat(64)};
    const second=readFrame(sockets.peer);
    sockets.peer.write(frame({...arm,...nextBase,compaction_policy:{...selected,config_source:'application'}}));
    const proposal=await second;
    assert.equal(proposal.phase,'proposal');
    assert.equal(proposal.command_nonce,nextBase.command_nonce);
    sockets.peer.write(frame({...nextBase,phase:'decision',status:'reject'}));
    assert.deepEqual(await result,{cancel:true,closed:false,concats:0,followupCancel:true});
  } finally {sockets.close();}
});

test('oversized header rejects before concatenating any declared body',async()=>{
  const sockets=await pair();
  try {
    const result=capacityChild(sockets,{policy,countConcat:true});
    const header=Buffer.alloc(5);header.writeUInt32BE(policy.max_frame_bytes+1);
    sockets.peer.write(header);
    assert.deepEqual(await result,{cancel:true,closed:true,concats:0});
  } finally {sockets.close();}
});

test('arm policy and source must exactly match constructor injection',async()=>{
  for(const changed of [{...policy,max_total_tokens:policy.max_total_tokens+1,config_source:'application'},
    {...policy,config_source:'operator'}, {...policy,config_source:'application',extra:1}]) {
    const sockets=await pair();
    try {
      const result=capacityChild(sockets,{policy,source:'application'});
      sockets.peer.write(frame({...arm,compaction_policy:changed}));
      assert.deepEqual(await result,{cancel:true,closed:true,concats:0});
    } finally {sockets.close();}
  }
});

test('private bootstrap validates closed canonical keys and consumes only host transport',async()=>{
  const bootstrap=extension.canonicalJson({...policy,config_source:'application'});
  for(const kind of ['valid','invalid-json','duplicate','extra','unsafe','oversized','buffer-bound',
    'missing-policy','missing-fd','missing-nonce']) {
    const sockets=await pair();
    try {
      const source=`
        import register,{coreOnlyModule} from ${JSON.stringify(artifact)};
        const kind=process.argv[1],injected=JSON.parse(process.argv[2]);
        process.env.ASTERION_PRIME_IPYTHON_FD='999998';
        process.env.ASTERION_PRIME_IPYTHON_TOOL_REGISTRY=JSON.stringify(coreOnlyModule.registry);
        if(kind!=='missing-fd')process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD='3';
        if(kind!=='missing-nonce')process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE=${JSON.stringify(launch)};
        if(kind!=='missing-policy')process.env.ASTERION_PRIME_IPYTHON_COMPACTION_POLICY=injected;
        process.env.ASTERION_OPERATOR_POLICY='private-sentinel';
        const deps=Object.freeze({buildSessionContext(){return {messages:[]}},
          getCurrentSystemMessage(){},convertToLlm(){return []},serializeConversation(){return ''}});
        const hooks=new Map();let error=null,tools=0;
        try{register({on:(name,hook)=>hooks.set(name,hook),registerTool(){tools++}},deps)}catch(e){error=e.message}
        const consumed=['ASTERION_PRIME_IPYTHON_CONTEXT_FD','ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE',
          'ASTERION_PRIME_IPYTHON_COMPACTION_POLICY'].every(key=>process.env[key]===undefined);
        hooks.get('session_shutdown')?.();
        process.stdout.write(JSON.stringify({error,tools,consumed,operatorKept:process.env.ASTERION_OPERATOR_POLICY==='private-sentinel'}));
        process.exit(0);`;
      let value=bootstrap;
      if(kind==='invalid-json')value='{';
      if(kind==='duplicate')value=bootstrap.replace('"max_total_tokens":','"max_total_tokens":1,"max_total_tokens":');
      if(kind==='extra')value=extension.canonicalJson({...policy,config_source:'application',extra:1});
      if(kind==='unsafe')value=JSON.stringify({...policy,config_source:'application',max_total_tokens:2**53});
      if(kind==='oversized')value=' '.repeat(513);
      if(kind==='buffer-bound')value=extension.canonicalJson({...policy,config_source:'application',max_frame_bytes:2**32});
      const child=spawnSync(process.execPath,['--input-type=module','-e',source,kind,JSON.stringify(value)],
        {stdio:['ignore','pipe','pipe',sockets.client._handle.fd],encoding:'utf8',timeout:3000});
      assert.equal(child.status,0);assert.equal(child.stderr,'');
      const result=JSON.parse(child.stdout);
      assert.deepEqual(result,{error:kind==='valid'?null:'Asterion ipython bridge is unavailable',
        tools:kind==='valid'?1:0,consumed:true,operatorKept:true});
    } finally {sockets.close();}
  }
});


test('frame refusal after approval sends numeric settlement metadata and closes',async()=>{
  const selected={...policy,max_frame_bytes:20000,max_material_bytes:8000};
  const sockets=await pair();
  try {
    const result=capacityChild(sockets,{policy:selected,source:'application',conversation:1000,persistedSummary:10000});
    let received=readFrame(sockets.peer);
    sockets.peer.write(frame({...arm,compaction_policy:{...selected,config_source:'application'}}));
    const proposal=await received;
    assert.equal(proposal.phase,'proposal');
    received=readFrame(sockets.peer);
    sockets.peer.write(frame({...base,phase:'decision',status:'approve'}));
    const refusal=await received;
    assert.equal(refusal.phase,'limit');
    assert.equal(refusal.launch_nonce,launch);assert.equal(refusal.command_nonce,command);
    assert.equal(refusal.authority_sha256,authority);
    assert.deepEqual({...refusal.limit_diagnostic,observed:0},{limit_code:'witness-frame-limit',
      phase:'settlement',action:'recovery-required',observed:0,limit:20000,unit:'bytes',
      measurement:'exact',config_source:'application'});
    assert(refusal.limit_diagnostic.observed>20000);
    assert.deepEqual(await result,{cancel:false,closed:true,concats:0,
      persistedError:'Asterion context witness is unavailable'});
  } finally {sockets.close();}
});

test('legacy frame alias without explicit policy becomes the only effective frame cap',async()=>{
  const sockets=await pair();
  try {
    const result=capacityChild(sockets,{maxFrameBytes:1048576});
    const received=readFrame(sockets.peer);
    sockets.peer.write(frame({...arm,compaction_policy:{...policy,max_frame_bytes:1048576,
      config_source:'framework-default'}}));
    assert.equal((await received).phase,'proposal');
    sockets.peer.write(frame({...base,phase:'decision',status:'reject'}));
    assert.deepEqual(await result,{cancel:true,closed:false,concats:0});
  } finally {sockets.close();}
});
