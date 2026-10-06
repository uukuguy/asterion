import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { canonicalJSON, decodeObject, INDEX_PATH, readRoute, sha256, validateIndex } from '../cloud.mjs';
import { configureUploadProxy, packObjects, publishSpool } from '../upload.mjs';
import { createHandler } from '../api/cloud.js';
import { renderHTML } from '../html.mjs';

const baseRoutes = {'/api/overview':{games:[]},'/api/games':{games:[{game_id:'ar25-test',win_levels:1}]},'/api/state':{state:'idle',snapshot:null},'/api/runs':{runs:[]}};
function fixture(values=baseRoutes) {
  const routes={}; const objects=new Map();
  for (const [route,value] of Object.entries(values)) {
    const body=Buffer.from(canonicalJSON(value)); const sha=sha256(body); const gzip=gzipSync(body);
    routes[route]={sha256:sha,blobPath:`p7-console/objects/${sha}.json.gz`,contentType:'application/json',bytes:body.length,compressedBytes:gzip.length};
    objects.set(sha,gzip);
  }
  return {index:{schema:'asterion.p7.cloud-index/v1',capturedAt:new Date().toISOString(),generation:sha256(canonicalJSON(routes)),routes},objects};
}
function memorySDK() {
  const blobs=new Map(); const writes=[]; const reads=[];
  return {blobs,writes,reads,
    get:async(path,options)=>{reads.push({path,options}); const body=blobs.get(path); return body ? {statusCode:200,stream:new Response(body).body,blob:{pathname:path,size:body.length}} : null;},
    put:async(path,body,options)=>{writes.push({path,options}); blobs.set(path,Buffer.from(body)); return {pathname:path};}};
}
async function stage(t, fix) {
  const spool=await mkdtemp(join(tmpdir(),'p7-cloud-test-')); t.after(()=>rm(spool,{recursive:true,force:true}));
  await mkdir(join(spool,'objects'));
  await writeFile(join(spool,'index.json'),canonicalJSON(fix.index));
  for (const [sha,body] of fix.objects) await writeFile(join(spool,'objects',`${sha}.json.gz`),body);
  return spool;
}
function response() {
  return {headers:{},setHeader(key,value){this.headers[key]=value;},end(body){this.body=body;}};
}

test('index rejects arbitrary paths and pack offsets even when its generation is recomputed',()=>{
  for (const bad of ['/api/../secret','https://local.invalid/api/state','/api/start']) {
    const {index}=fixture(); index.routes[bad]=index.routes['/api/state']; index.generation=sha256(canonicalJSON(index.routes));
    assert.throws(()=>validateIndex(index),/binding/);
  }
  const fix=fixture(); const packed=packObjects(fix.index,fix.objects); const entry=packed.index.routes['/api/state'];
  entry.offset=entry.packBytes; packed.index.generation=sha256(canonicalJSON(packed.index.routes));
  assert.throws(()=>validateIndex(packed.index,{storage:true}),/pack-binding/);
});
test('corrupt gzip and replay revision/source mismatch fail closed',()=>{
  const run='p7-test-run',revision='a'.repeat(64),token='b'.repeat(64);
  const route=`/api/replay/${run}/levels/1/${revision}/frames/${token}/0/32`;
  const fix=fixture({...baseRoutes,[route]:{run_id:run,level:1,replay_revision:revision,source_token:token,start:0,frames:[]}});
  const entry=fix.index.routes[route]; const body=fix.objects.get(entry.sha256);
  assert.equal(decodeObject(body,entry,route).value.run_id,run);
  assert.throws(()=>decodeObject(Buffer.alloc(body.length),entry,route));
  assert.throws(()=>decodeObject(body,entry,route.replace(token,'c'.repeat(64))),/frame-source/);
  assert.throws(()=>decodeObject(body,entry,route.replace(revision,'d'.repeat(64))),/revision/);
});
test('packing preserves exact public bytes and private reads verify pack hashes',async()=>{
  const fix=fixture(); const packed=packObjects(fix.index,fix.objects); assert.equal(packed.packs.size,1);
  const sdk=memorySDK(); for (const [sha,body] of packed.packs) sdk.blobs.set(`p7-console/packs/${sha}.bin`,body);
  assert.deepEqual((await readRoute(sdk.get,packed.index,'/api/games')).value,baseRoutes['/api/games']);
  assert.equal(sdk.reads[0].options.access,'private');
  const other=fixture({...baseRoutes,'/api/overview':{games:[],changed:true}}); const corrupt=packObjects(other.index,other.objects);
  for (const [sha,body] of corrupt.packs) sdk.blobs.set(`p7-console/packs/${sha}.bin`,Buffer.alloc(body.length));
  await assert.rejects(()=>readRoute(sdk.get,corrupt.index,'/api/overview'),/pack-hash/);
});
test('concurrent cold reads share one private pack fetch and retain a working cache',async()=>{
  const fix=fixture({...baseRoutes,'/api/overview':{games:[],concurrentColdRead:true}});
  const packed=packObjects(fix.index,fix.objects); const sdk=memorySDK();
  for (const [sha,body] of packed.packs) sdk.blobs.set(`p7-console/packs/${sha}.bin`,body);
  let release; const gate=new Promise(resolve=>{release=resolve;});
  const slowGet=async(...args)=>{await gate; return sdk.get(...args);};
  const first=readRoute(slowGet,packed.index,'/api/overview');
  const second=readRoute(slowGet,packed.index,'/api/games');
  release(); const [overview,games]=await Promise.all([first,second]);
  assert.equal(overview.value.concurrentColdRead,true); assert.deepEqual(games.value,baseRoutes['/api/games']);
  assert.equal(sdk.reads.length,1);
  await readRoute(slowGet,packed.index,'/api/state'); assert.equal(sdk.reads.length,1);
});
test('partial upload retains previous pointer; retry and unchanged scan use receipts',async t=>{
  const fix=fixture({...baseRoutes,'/api/replay/p7-run':{run:{run_id:'p7-run'}}}); const spool=await stage(t,fix); const sdk=memorySDK();
  const previous=fixture({...baseRoutes,'/api/state':{state:'idle',snapshot:null,previous:true}});
  const previousPack=packObjects(previous.index,previous.objects);
  const old=Buffer.from(canonicalJSON(previousPack.index)); sdk.blobs.set(INDEX_PATH,old);
  for (const [sha,body] of previousPack.packs) sdk.blobs.set(`p7-console/packs/${sha}.bin`,body);
  let calls=0; const original=sdk.put;
  sdk.put=async(...args)=>{if (++calls===2) throw new Error('SENTINEL_PRIVATE_BACKEND'); return original(...args);};
  await assert.rejects(()=>publishSpool({spool,token:'SENTINEL_TOKEN',sdk}));
  assert.deepEqual(sdk.blobs.get(INDEX_PATH),old); assert.equal(sdk.writes.some(write=>write.path===INDEX_PATH),false);
  sdk.put=original;
  const result=await publishSpool({spool,token:'SENTINEL_TOKEN',sdk}); assert.ok(result.packs>=2);
  assert.equal(sdk.writes.at(-1).path,INDEX_PATH); assert.equal(sdk.writes.at(-1).options.allowOverwrite,true);
  assert.ok(sdk.writes.slice(0,-1).every(write=>write.options.allowOverwrite===false && write.options.addRandomSuffix===false));
  const writes=sdk.writes.length,reads=sdk.reads.length;
  assert.equal((await publishSpool({spool,token:'SENTINEL_TOKEN',sdk})).unchanged,true);
  assert.equal(sdk.writes.length,writes); assert.equal(sdk.reads.length,reads);
  const receipt=JSON.parse(await readFile(join(spool,'cloud-upload-state.json'),'utf8')); assert.ok(receipt.uploadAttempts>=3);
});
test('quota guard rejects before writes and records no token',async t=>{
  const spool=await stage(t,fixture()); const sdk=memorySDK();
  await assert.rejects(()=>publishSpool({spool,token:'SENTINEL_SECRET',sdk,maxUploadOperations:1}),/quota-exceeded/);
  assert.equal(sdk.writes.length,0);
});
test('uploader proxy honors explicit operator environment without cloud-side initialization',async()=>{
  const calls=[]; const agent={}; const createAgent=options=>{calls.push(options);return agent;};
  const setDispatcher=value=>calls.push(value);
  assert.equal(configureUploadProxy({env:{},createAgent,setDispatcher}),null); assert.equal(calls.length,0);
  assert.equal(configureUploadProxy({env:{HTTP_PROXY:'http://proxy.invalid:8080',HTTPS_PROXY:'http://secure-proxy.invalid:8081',NO_PROXY:'localhost'},createAgent,setDispatcher}),agent);
  assert.deepEqual(calls[0],{httpProxy:'http://proxy.invalid:8080',httpsProxy:'http://secure-proxy.invalid:8081',noProxy:'localhost'});
  assert.equal(calls[1],agent); calls.length=0;
  configureUploadProxy({env:{http_proxy:'http://lower.invalid:8082',HTTP_PROXY:'http://ignored.invalid:8080',no_proxy:'*'},createAgent,setDispatcher});
  assert.deepEqual(calls[0],{httpProxy:'http://lower.invalid:8082',httpsProxy:'',noProxy:'*'});
  assert.doesNotMatch(await readFile(new URL('../api/cloud.js',import.meta.url),'utf8'),/configureUploadProxy|EnvHttpProxyAgent|setGlobalDispatcher/);
});
test('remote mutation returns405 without storage reads and internal errors redact',async()=>{
  const sdk=memorySDK(); const handle=createHandler(sdk.get); const res=response();
  await handle({method:'POST',url:'/api/start'},res); assert.equal(res.statusCode,405); assert.equal(sdk.reads.length,0);
  const missing=response(); await handle({method:'GET',url:'/api/overview'},missing);
  assert.equal(missing.statusCode,503); assert.deepEqual(JSON.parse(missing.body),{error:'cloud-view-unavailable',readOnly:true});
});
test('existing console HTML enables readonly queries with no operator token and safe inline data',async()=>{
  const html=await renderHTML({schema:'asterion.arc-agi3-p7-console/v1',run:{run_id:'real-run',game_id:'ar25-test'},levels:[],note:'</script>'},baseRoutes['/api/games'].games);
  assert.match(html,/"readOnly":true/); assert.match(html,/if \(command\) throw/); assert.match(html,/cloud-sync-status/);
  assert.doesNotMatch(html,/X-P7-Console-Token/); assert.doesNotMatch(html,/__CONSOLE_/);
  assert.match(html,/\\u003c\/script\\u003e/);
  assert.match(html,/正在读取云端记录/); assert.doesNotMatch(html,/正在读取本地记录|本地记录 · 每 5 秒更新|求解模型尚未就绪/);
  assert.match(html,/云端只读 · 每 5 分钟检查更新/);
  assert.match(html,/id="run-start" hidden/); assert.match(html,/id="run-fresh" hidden/);
  assert.match(html,/button\.disabled = true; button\.hidden = true;/);
  assert.match(html,/label\.textContent = ' · 云端只读 · 更新于 ' \+ time;/);
  assert.match(html,/label\.title = '数据更新 '/);
  assert.match(html,/return best\?\.run_id \|\| null;/);
});
test('packaged cloud assets are fresh with five-minute polling and unchanged local source',async()=>{
  const source=new URL('../../../src/asterion/applications/prime/p7/console_assets/app.js',import.meta.url);
  const asset=new URL('../assets/app.js',import.meta.url);
  const before=await readFile(asset,'utf8'); const local=await readFile(source,'utf8');
  const result=spawnSync(process.execPath,[new URL('../refresh-assets.mjs',import.meta.url).pathname],{encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
  const cloud=await readFile(asset,'utf8'); assert.equal(cloud,before); assert.equal(await readFile(source,'utf8'),local);
  assert.match(cloud,/const CLOUD_REFRESH_INTERVAL = 300000;/);
  assert.match(cloud,/setInterval\(pollState, CLOUD_REFRESH_INTERVAL\)/);
  assert.match(cloud,/setInterval\(loadOverview, CLOUD_REFRESH_INTERVAL\)/);
  assert.equal(cloud.match(/setInterval\(\(\) => loadReplay\(\), CLOUD_REFRESH_INTERVAL\)/g)?.length,2);
  assert.match(cloud,/loadOverview\(\); initializeSelection\(\)/);
  assert.match(await readFile(new URL('../html.mjs',import.meta.url),'utf8'),/setInterval\(update,300000\)/);
  const functionText=cloud.match(/function preferredReplayId\(game\) \{[\s\S]*?\n  \}/)?.[0];
  assert.ok(functionText); const preferred=new Function('array',functionText+'; return preferredReplayId;')(value=>Array.isArray(value)?value:[]);
  assert.equal(preferred({best_run_id:'saved',completed_levels:2,solving_run_id:'current',solving:true,
    runs:[{run_id:'current',verified:false,completed_levels:0},{run_id:'saved',verified:true,completed_levels:2}]}),'saved');
  assert.equal(preferred({best_run_id:null,completed_levels:0,solving_run_id:'current',solving:true,
    runs:[{run_id:'current',verified:false,completed_levels:0}]}),null);
  assert.match(local,/return activeReplayId\(game\) \|\| best\?\.run_id \|\| attempt;/);
  const switchPattern=/function selectSwitchedGameLevel\(game\) \{[\s\S]*?\n  \}/;
  const switchText=cloud.match(switchPattern)?.[0]; assert.ok(switchText);
  assert.equal(switchText,local.match(switchPattern)?.[0]);
  assert.match(cloud,/selectSwitchedGameLevel\(overviewGame\(gameId\)\)/);
  assert.match(cloud,/selectSwitchedGameLevel\(overviewGame\(\$\('game-select'\)\.value\)\)/);
  const selected=[]; const switchState={replayFollow:true,eventSequence:1};
  const switchLevel=new Function('run','state','replaceSnapshot','emptyGamePreview','selectLevel',switchText+'; return selectSwitchedGameLevel;')(
    {game_id:'old'},switchState,()=>{},game=>({game_id:game.game_id}),(index,options)=>selected.push({index,options}));
  switchLevel({game_id:'new',win_levels:8,completed_levels:8});
  switchLevel({game_id:'partial',win_levels:8,completed_levels:3});
  switchLevel({game_id:'old',win_levels:8,completed_levels:3});
  assert.deepEqual(selected,[{index:0,options:{bindSavedSource:false}},{index:3,options:{bindSavedSource:false}}]);
});
