import assert from "node:assert/strict";
import test from "node:test";
import {closeSync,fstatSync,mkdtempSync,openSync,readFileSync,rmSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import * as extension from "../dist/ipython-extension.mjs";

const payload = (text="USER_SECRET_SENTINEL") => ({model:"fake",input:[{role:"developer",content:"SYSTEM_SECRET_SENTINEL"},
  {role:"user",content:[{type:"input_text",text}]}],instructions:"INSTRUCTIONS_SECRET_SENTINEL",prompt_cache_key:"CACHE_KEY_SECRET_SENTINEL"});
const fields=["requests","input_bytes","previous_input_bytes","common_prefix_bytes","common_prefix_items",
  "input_items","previous_input_items","system_changed","cache_key_changed","tools_changed","unmeasurable_requests","peak_input_bytes"].sort();

test("provider prefix observer reports exact numeric adjacent input prefixes without payload fields", () => {
  const observer=new extension.ProviderPrefixTelemetry();
  const firstPayload=payload();const original=structuredClone(firstPayload);
  const first=observer.observe(firstPayload);
  assert.deepEqual(Object.keys(first).sort(),fields);
  assert.equal(first.input_bytes,Buffer.byteLength(JSON.stringify(firstPayload.input),"utf8"));
  assert.equal(first.previous_input_bytes,0);assert.equal(first.common_prefix_bytes,0);assert.equal(first.common_prefix_items,0);
  assert.equal(first.system_changed,0);assert.equal(first.cache_key_changed,0);
  const next=payload();next.input.push({type:"function_call",call_id:"cell",name:"ipython",arguments:"{}"});
  const second=observer.observe(next);
  assert.equal(second.previous_input_bytes,first.input_bytes);
  assert.equal(second.common_prefix_bytes,first.input_bytes-1);
  assert.equal(second.common_prefix_items,2);assert.equal(second.input_items,3);assert.equal(second.previous_input_items,2);
  assert.equal(second.system_changed,0);assert.equal(second.cache_key_changed,0);
  const changed=structuredClone(next);changed.input[0].content="SYSTEM_CHANGED";changed.instructions="changed";changed.prompt_cache_key="different";
  const third=observer.observe(changed);
  changed.tools=[{type:"function",name:"ipython",parameters:{type:"object"}}];
  const fourth=observer.observe(changed);assert.equal(fourth.tools_changed,1);
  assert.equal(third.system_changed,1);assert.equal(third.cache_key_changed,1);assert.equal(third.common_prefix_items,0);
  assert.ok(third.common_prefix_bytes<second.common_prefix_bytes);
  assert.deepEqual(firstPayload,original);
  for(const value of Object.values(third)) assert.ok(Number.isSafeInteger(value)&&value>=0);
  assert.ok(Object.isFrozen(third));assert.doesNotMatch(JSON.stringify([first,second,third]),/SECRET|content|instructions|model|call_id/);
  observer.close();
});

test("unsupported malformed and oversized payloads reset numeric prefix baselines without blocking requests", () => {
  const observer=new extension.ProviderPrefixTelemetry();
  const cyclic=payload();cyclic.input[1].cycle=cyclic;
  for(const invalid of [null,{messages:[]},{input:"text"},{input:[null]},cyclic,payload("x".repeat(8*1024*1024))]) {
    observer.observe(payload("valid"));
    const unknown=observer.observe(invalid);
    assert.equal(unknown.input_bytes,0);assert.equal(unknown.previous_input_bytes,0);assert.equal(unknown.common_prefix_bytes,0);
    const recovered=observer.observe(payload("recovered"));
    assert.equal(recovered.previous_input_bytes,0);assert.equal(recovered.previous_input_items,0);
    assert.equal(recovered.system_changed,0);assert.equal(recovered.cache_key_changed,0);
  }
  const final=observer.observe(payload());assert.equal(final.unmeasurable_requests,6);assert.equal(final.requests,19);
  observer.close();assert.equal(observer.observe(payload()).previous_input_bytes,0);
});

test("registered provider observer returns undefined and isolates sink errors", () => {
  let handler;const records=[];
  assert.equal(extension.registerProviderPrefixMetrics({on:(event,fn)=>{if(event==="before_provider_request")handler=fn;}},value=>records.push(value)),true);
  const request=payload();const original=structuredClone(request);
  assert.equal(handler({type:"before_provider_request",payload:request}),undefined);
  assert.deepEqual(request,original);assert.equal(records.length,1);
  extension.registerProviderPrefixMetrics({on:(event,fn)=>{if(event==="before_provider_request")handler=fn;}},()=>{throw Error("SECRET_SINK_ERROR");});
  assert.equal(handler({type:"before_provider_request",payload:request}),undefined);
});

test("prefix file output overwrites bounded numeric chronology and releases owned file descriptors", () => {
  const root=mkdtempSync(join(tmpdir(),"prime-prefix-"));
  const environment="ASTERION_PRIME_IPYTHON_PREFIX_METRICS_FD",prior=process.env[environment];let descriptor;
  try {
    const path=join(root,"prefix.json");descriptor=openSync(path,"w+",0o600);writeFileSync(path,"SECRET_STALE_FILE".repeat(100000));
    process.env[environment]=String(descriptor);const sink=extension.providerPrefixMetricsFromEnvironment();
    assert.equal(process.env[environment],undefined);const observer=new extension.ProviderPrefixTelemetry();
    for(let index=0;index<1026;index++) sink(observer.observe(payload()));
    const text=readFileSync(path,"utf8"),archive=JSON.parse(text);
    assert.deepEqual(Object.keys(archive).sort(),["latest","measurement","samples","samples_truncated","version"]);
    assert.equal(archive.version,"asterion.prime-provider-prefix-metrics/v1");assert.equal(archive.measurement,"provider-hook-responses-input-json-utf8");
    assert.equal(archive.latest.requests,1026);assert.equal(archive.samples.length,1024);assert.equal(archive.samples_truncated,1);
    assert.deepEqual(Object.keys(archive.latest).sort(),fields);assert.ok(Buffer.byteLength(text)<1024*1024);
    assert.doesNotMatch(text,/SECRET|content|instructions|model|prompt_cache_key|tmp/);sink.close();sink.close();
    assert.throws(()=>fstatSync(descriptor),{code:"EBADF"});descriptor=undefined;
    const foreign=openSync(root,"r");process.env[environment]=String(foreign);
    assert.equal(extension.providerPrefixMetricsFromEnvironment(),undefined);assert.ok(fstatSync(foreign).isDirectory());closeSync(foreign);
  } finally {
    if(descriptor!==undefined)try{closeSync(descriptor);}catch{}
    if(prior===undefined)delete process.env[environment];else process.env[environment]=prior;
    rmSync(root,{recursive:true,force:true});
  }
});


test("failed provider observer subscriptions leave no active callback or payload baseline", () => {
  let handler;const records=[];
  const registered=extension.registerProviderPrefixMetrics({on:(event,fn)=>{
    if(event==="before_provider_request") handler=fn;else throw Error("PRIVATE_REGISTRATION_ERROR");
  }},numbers=>records.push(numbers));
  assert.equal(registered,false);
  assert.equal(handler({type:"before_provider_request",payload:payload()}),undefined);
  assert.deepEqual(records,[]);
});

test("prefix descriptor ownership covers registration failure shutdown and silent write failure", () => {
  const root=mkdtempSync(join(tmpdir(),"prime-prefix-lifecycle-"));
  const environment="ASTERION_PRIME_IPYTHON_PREFIX_METRICS_FD",prior=process.env[environment];
  const bridgePrior=process.env.ASTERION_PRIME_IPYTHON_FD;
  const descriptors=[];
  try {
    const owned=openSync(join(root,"failed.json"),"w+",0o600);descriptors.push(owned);
    process.env[environment]=String(owned);delete process.env.ASTERION_PRIME_IPYTHON_FD;
    assert.throws(()=>extension.register({registerTool:()=>{}}),/bridge is unavailable/);
    assert.equal(process.env[environment],undefined);assert.throws(()=>fstatSync(owned),{code:"EBADF"});
    const bridge=openSync(join(root,"bridge"),"w+",0o600);descriptors.push(bridge);
    const active=openSync(join(root,"active.json"),"w+",0o600);descriptors.push(active);
    process.env[environment]=String(active);process.env.ASTERION_PRIME_IPYTHON_FD=String(bridge);
    const handlers=new Map();extension.register({registerTool:()=>{},on:(event,fn)=>handlers.set(event,fn)});
    const request=payload();assert.equal(handlers.get("before_provider_request")({type:"before_provider_request",payload:request}),undefined);
    handlers.get("session_shutdown")();assert.throws(()=>fstatSync(active),{code:"EBADF"});
    const readonly=openSync(join(root,"active.json"),"r");descriptors.push(readonly);
    process.env[environment]=String(readonly);const sink=extension.providerPrefixMetricsFromEnvironment();
    assert.doesNotThrow(()=>sink(new extension.ProviderPrefixTelemetry().observe(payload())));
    assert.throws(()=>fstatSync(readonly),{code:"EBADF"});sink.close();
  } finally {
    for(const fd of descriptors)try{closeSync(fd);}catch{}
    if(prior===undefined)delete process.env[environment];else process.env[environment]=prior;
    if(bridgePrior===undefined)delete process.env.ASTERION_PRIME_IPYTHON_FD;else process.env.ASTERION_PRIME_IPYTHON_FD=bridgePrior;
    rmSync(root,{recursive:true,force:true});
  }
});
