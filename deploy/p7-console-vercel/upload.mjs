import { readFile, writeFile, rename } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { get, put } from '@vercel/blob';
import { EnvHttpProxyAgent, setGlobalDispatcher } from 'undici';
import { INDEX_PATH, MAX_BYTES, canonicalJSON, decodeObject, readBoundedBlob, readIndex, sha256, validateIndex } from './cloud.mjs';

const PACK_TARGET = 1024 * 1024;
const STORAGE_GUARD_BYTES = 900 * 1024 * 1024;
const STORAGE_WARNING_BYTES = 750 * 1024 * 1024;
export function configureUploadProxy({ env=process.env, createAgent=options=>new EnvHttpProxyAgent(options),
  setDispatcher=setGlobalDispatcher } = {}) {
  const httpProxy=env.http_proxy ?? env.HTTP_PROXY;
  const httpsProxy=env.https_proxy ?? env.HTTPS_PROXY;
  if (!httpProxy && !httpsProxy) return null;
  const agent=createAgent({httpProxy:httpProxy??'',httpsProxy:httpsProxy??'',noProxy:env.no_proxy??env.NO_PROXY??''});
  setDispatcher(agent);
  return agent;
}
export function packObjects(index, objects) {
  const groups = new Map();
  for (const route of Object.keys(index.routes).sort()) {
    const key = route.startsWith('/api/replay/') ? route.split('/').slice(0,4).join('/') : route.startsWith('/api/preview/') ? 'previews' : 'metadata';
    if (!groups.has(key)) groups.set(key,new Map());
    groups.get(key).set(index.routes[route].sha256,objects.get(index.routes[route].sha256));
  }
  const packs = new Map(); const locations = new Map();
  for (const group of groups.values()) {
    let members = []; let length = 0;
    const flush = () => {
      if (!members.length) return;
      const body = Buffer.concat(members.map(member=>member.body)); const packSHA = sha256(body);
      packs.set(packSHA,body); let offset = 0;
      for (const member of members) {
        locations.set(member.sha,{packSHA,packPath:`p7-console/packs/${packSHA}.bin`,packBytes:body.length,offset});
        offset += member.body.length;
      }
      members = []; length = 0;
    };
    for (const [sha,body] of [...group.entries()].sort(([left],[right])=>left.localeCompare(right))) {
      if (locations.has(sha)) continue;
      if (length && length + body.length > PACK_TARGET) flush();
      members.push({sha,body}); length += body.length;
    }
    flush();
  }
  const routes = Object.fromEntries(Object.entries(index.routes).map(([route,entry])=>[route,{...entry,...locations.get(entry.sha256)}]));
  const cloudIndex = {...index,logicalGeneration:index.generation,generation:sha256(canonicalJSON(routes)),routes};
  if (Buffer.byteLength(canonicalJSON(cloudIndex)) > MAX_BYTES) throw new Error('cloud-index-too-large');
  return {index:validateIndex(cloudIndex,{storage:true}),packs};
}
async function saveReceipt(path, receipt) {
  await writeFile(path+'.tmp',canonicalJSON(receipt),{mode:0o600}); await rename(path+'.tmp',path);
}
export async function publishSpool({ spool, token, sdk = { get, put }, maxUploadOperations = 1500 }) {
  if (typeof token !== 'string' || !token.trim()) throw new Error('cloud-token-required');
  if (!Number.isInteger(maxUploadOperations) || maxUploadOperations < 1 || maxUploadOperations > 2000) throw new Error('cloud-quota-invalid');
  const index = validateIndex(JSON.parse(await readFile(resolve(spool,'index.json'),'utf8')));
  const receiptPath = resolve(spool,'cloud-upload-state.json'); const month = new Date().toISOString().slice(0,7);
  const store = sha256(token).slice(0,24); let receipt;
  try { receipt = JSON.parse(await readFile(receiptPath,'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (receipt && receipt.store !== store) throw new Error('cloud-receipt-store-mismatch');
  receipt ??= {schema:'asterion.p7.cloud-upload-state/v1',store,month,uploadAttempts:0,knownPacks:[],packSizes:{},logicalGeneration:null};
  receipt.packSizes ??= {};
  if (receipt.month !== month) { receipt.month=month; receipt.uploadAttempts=0; }
  if (!Number.isSafeInteger(receipt.uploadAttempts) || receipt.uploadAttempts < 0 || !Array.isArray(receipt.knownPacks)) throw new Error('cloud-receipt-invalid');
  if (receipt.logicalGeneration === index.generation) return {generation:receipt.generation,logicalGeneration:index.generation,
    capturedAt:receipt.capturedAt,routes:Object.keys(index.routes).length,uploaded:0,reused:receipt.knownPacks.length,
    unchanged:true,uploadAttempts:receipt.uploadAttempts,maxUploadOperations,retainedCloudBytes:receipt.retainedCloudBytes,
    currentCompressedBytes:receipt.currentCompressedBytes,storageWarning:receipt.retainedCloudBytes>=STORAGE_WARNING_BYTES};
  const objects = new Map();
  for (const [route,entry] of Object.entries(index.routes)) {
    const body = objects.get(entry.sha256) ?? await readFile(resolve(spool,'objects',`${entry.sha256}.json.gz`));
    decodeObject(body,entry,route); objects.set(entry.sha256,body);
  }
  const packed = packObjects(index,objects);
  const known = new Set(receipt.knownPacks);
  if (!receipt.generation) {
    try { const previous = await readIndex(sdk.get,token); for (const entry of Object.values(previous.routes)) {
      known.add(entry.packSHA); receipt.packSizes[entry.packSHA]=entry.packBytes;
    } }
    catch (error) { if (error.message !== 'cloud-object-unavailable') throw error; }
  }
  const missing = [...packed.packs.keys()].filter(sha=>!known.has(sha));
  if (receipt.uploadAttempts + missing.length + 1 > maxUploadOperations) throw new Error('cloud-upload-quota-exceeded');
  const expectedRetainedPacks = {...receipt.packSizes};
  for (const [sha,body] of packed.packs) expectedRetainedPacks[sha]=body.length;
  const packBytes=Object.values(expectedRetainedPacks).reduce((sum,bytes)=>sum+bytes,0);
  if (packBytes+Buffer.byteLength(canonicalJSON(packed.index))>STORAGE_GUARD_BYTES) throw new Error('cloud-storage-quota-exceeded');
  let uploaded = 0;
  const countedPut = async (path,body,options) => {
    receipt.uploadAttempts++; await saveReceipt(receiptPath,receipt);
    return sdk.put(path,body,{access:'private',token,addRandomSuffix:false,abortSignal:AbortSignal.timeout(30000),...options});
  };
  for (const [sha,body] of packed.packs) {
    if (known.has(sha)) continue;
    const path = `p7-console/packs/${sha}.bin`;
    try { await countedPut(path,body,{allowOverwrite:false,contentType:'application/octet-stream',cacheControlMaxAge:31536000}); }
    catch (error) {
      let existing;
      try { existing=await readBoundedBlob(sdk.get,path,{token,maximum:body.length,fresh:true}); } catch (_) { throw error; }
      if (sha256(existing) !== sha) throw new Error('cloud-existing-pack-invalid');
    }
    known.add(sha); receipt.packSizes[sha]=body.length; receipt.knownPacks=[...known].sort();
    receipt.retainedCloudBytes=Object.values(receipt.packSizes).reduce((sum,bytes)=>sum+bytes,0)+(receipt.indexBytes??0);
    await saveReceipt(receiptPath,receipt); uploaded++;
  }
  packed.index.uploadOperations={month,attempts:receipt.uploadAttempts+1,limit:maxUploadOperations};
  const currentCompressedBytes=[...packed.packs.values()].reduce((sum,body)=>sum+body.length,0);
  packed.index.storage={currentCompressedBytes,retainedPackBytes:packBytes,guardBytes:STORAGE_GUARD_BYTES,
    warning:packBytes>=STORAGE_WARNING_BYTES};
  await countedPut(INDEX_PATH,canonicalJSON(packed.index),{allowOverwrite:true,contentType:'application/json',cacheControlMaxAge:60});
  Object.assign(receipt,{generation:packed.index.generation,logicalGeneration:index.generation,capturedAt:index.capturedAt,knownPacks:[...known].sort()});
  receipt.currentCompressedBytes=currentCompressedBytes; receipt.indexBytes=Buffer.byteLength(canonicalJSON(packed.index));
  receipt.retainedCloudBytes=packBytes+receipt.indexBytes;
  await saveReceipt(receiptPath,receipt);
  const entries = new Map(Object.values(index.routes).map(entry=>[entry.sha256,entry]));
  return {generation:packed.index.generation,logicalGeneration:index.generation,capturedAt:index.capturedAt,
    routes:Object.keys(index.routes).length,packs:packed.packs.size,uploaded,reused:packed.packs.size-uploaded,
    uncompressedBytes:[...entries.values()].reduce((sum,entry)=>sum+entry.bytes,0),
    compressedBytes:currentCompressedBytes,currentCompressedBytes,retainedCloudBytes:receipt.retainedCloudBytes,
    storageWarning:receipt.retainedCloudBytes>=STORAGE_WARNING_BYTES,uploadAttempts:receipt.uploadAttempts,maxUploadOperations};
}
async function main() {
  const args=process.argv.slice(2); const options={};
  for (let i=0;i<args.length;i+=2) {
    if (!['--spool','--token-file','--max-upload-operations'].includes(args[i]) || !args[i+1]) throw new Error('cloud-arguments-invalid');
    options[args[i]]=args[i+1];
  }
  if (!options['--spool']) throw new Error('cloud-spool-required');
  const token=options['--token-file'] ? (await readFile(options['--token-file'],'utf8')).trim() : process.env.BLOB_READ_WRITE_TOKEN;
  // This process-local dispatcher is installed only by the uploader CLI, never the cloud Function.
  const proxy=configureUploadProxy();
  try {
    console.log(JSON.stringify(await publishSpool({spool:options['--spool'],token,
      ...(options['--max-upload-operations'] ? {maxUploadOperations:Number(options['--max-upload-operations'])} : {})})));
  } finally { if (proxy) await proxy.close(); }
}
if (process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error=>{ const code=['cloud-upload-quota-exceeded','cloud-storage-quota-exceeded'].includes(error.message) ? error.message : 'cloud-upload-failed';
    console.error(JSON.stringify({error:code})); process.exitCode=1; });
}
