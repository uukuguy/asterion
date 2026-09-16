import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
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
// The native side is authoritative for the prompt material and delivers it on
// the arm frame, so the shared fixture supplies it here too.
const material = JSON.parse(readFileSync(
  resolve("../../../tests/fixtures/asterion_prime_p1/v1/summarization-parity.json"))).material;
const arm = {...base, phase: "arm", summarization: material};
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

test("reject cancels before either real built-in summary callback or appendCompaction", async () => {
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

test("approve permits only Pi built-in summary then one persisted frame and ack", async () => {
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

test("bad decision frames cancel and permanently fence before mutation", async t => {
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

test("short native source never pads or calls summary", async()=>{
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
          import register from ${JSON.stringify(artifact)};
          import {fstatSync} from 'node:fs';
          const kind=process.argv[1];
          const deps=Object.freeze({buildSessionContext(){return {messages:[]};},convertToLlm(){return [];},serializeConversation(){return "";}});
          if(kind!=='missing-ipython-fd')process.env.ASTERION_PRIME_IPYTHON_FD='999998';
          process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD=kind==='closed-descriptor'?'999999':'3';
          if(kind!=='missing-nonce')process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE=${JSON.stringify(launch)};
          let message=null;
          try{register(kind==='invalid-api'?null:{on(){},registerTool(){throw new Error(${JSON.stringify(secret)})}},deps)}catch(error){message=error.message}
          await new Promise(done=>setImmediate(done));
          let closed=false;try{fstatSync(kind==='closed-descriptor'?999999:3)}catch{closed=true}
          process.stdout.write(JSON.stringify({closed,message,removed:process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD===undefined}));
          process.exit(0);
        `;
        const child=spawnSync(process.execPath,["--input-type=module","-e",source,kind],{stdio:["ignore","pipe","pipe",sockets.client._handle.fd],encoding:"utf8",timeout:3000});
        assert.equal(child.status,0);assert.equal(child.stderr,"");
        const result=JSON.parse(child.stdout);
        assert.equal(result.closed,true);assert.equal(result.removed,true);
        assert.equal(result.message,"Asterion ipython bridge is unavailable");
      }finally{sockets.close();}
    });
  }
});

test("proposal backpressure times out before summary or append",async()=>{
  const sockets=await pair();
  try{
    sockets.peer.pause();
    const running=run(sockets,{backpressure:true,timeoutMs:100});
    sockets.peer.write(frame(arm));
    const result=await running;
    assert.equal(result.fenced,true);assert.equal(result.calls,0);assert.equal(result.appends,0);
  }finally{sockets.close();}
});

test("missing post-mutation ack fences the observer",async()=>{
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
