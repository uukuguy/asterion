import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';

export const MAX_BYTES = 4_500_000;
export const INDEX_PATH = 'p7-console/latest.json';
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export function canonicalJSON(value) {
  if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJSON(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
const hashPattern = /^[a-f0-9]{64}$/;
const id = '[A-Za-z0-9][A-Za-z0-9_.:@+\\-]{0,159}';
const replayRoute = new RegExp(`^/api/replay/(${id})(?:/(manifest)|/levels/([1-9][0-9]{0,2})/([a-f0-9]{64})(?:/frames/([a-f0-9]{64})/(0|[1-9][0-9]*)/32)?)?$`);
const previewRoute = /^\/api\/preview\/([A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)(?:\/([1-9][0-9]{0,2}))?$/;
export function allowedRoute(route) {
  return typeof route === 'string' && !route.includes('..') &&
    (/^\/api\/(overview|state|games|runs)$/.test(route) || replayRoute.test(route) || previewRoute.test(route));
}
function record(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
export function validateIndex(index, { storage = false } = {}) {
  if (!record(index) || index.schema !== 'asterion.p7.cloud-index/v1' || !record(index.routes) ||
      !hashPattern.test(index.generation) || typeof index.capturedAt !== 'string' || !Number.isFinite(Date.parse(index.capturedAt)) ||
      Object.keys(index.routes).length > 100000 || sha256(canonicalJSON(index.routes)) !== index.generation) throw new Error('cloud-index-invalid');
  for (const required of ['/api/overview', '/api/state', '/api/games', '/api/runs']) {
    if (!Object.hasOwn(index.routes, required)) throw new Error('cloud-index-incomplete');
  }
  for (const [route, entry] of Object.entries(index.routes)) {
    if (!allowedRoute(route) || !record(entry) || !hashPattern.test(entry.sha256) ||
        entry.blobPath !== `p7-console/objects/${entry.sha256}.json.gz` || entry.contentType !== 'application/json' ||
        !Number.isSafeInteger(entry.bytes) || entry.bytes < 1 || entry.bytes > MAX_BYTES ||
        !Number.isSafeInteger(entry.compressedBytes) || entry.compressedBytes < 1 || entry.compressedBytes > MAX_BYTES) throw new Error('cloud-index-binding-invalid');
    if (storage && (!hashPattern.test(entry.packSHA) || entry.packPath !== `p7-console/packs/${entry.packSHA}.bin` ||
        !Number.isSafeInteger(entry.packBytes) || entry.packBytes < 1 || entry.packBytes > MAX_BYTES ||
        !Number.isSafeInteger(entry.offset) || entry.offset < 0 || entry.offset + entry.compressedBytes > entry.packBytes)) throw new Error('cloud-pack-binding-invalid');
  }
  return index;
}
export async function readBoundedBlob(get, pathname, { token, maximum = MAX_BYTES, fresh = false } = {}) {
  const result = await get(pathname, { access: 'private', token, useCache: !fresh, abortSignal: AbortSignal.timeout(15000) });
  if (!result || result.statusCode !== 200 || !result.stream || result.blob.pathname !== pathname) throw new Error('cloud-object-unavailable');
  if (result.blob.size > maximum) throw new Error('cloud-object-too-large');
  const chunks = []; let size = 0;
  for await (const chunk of result.stream) {
    size += chunk.byteLength;
    if (size > maximum) throw new Error('cloud-object-too-large');
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}
export async function readIndex(get, token) {
  return validateIndex(JSON.parse((await readBoundedBlob(get, INDEX_PATH, { token, fresh: true })).toString('utf8')), { storage: true });
}
export function decodeObject(compressed, entry, route) {
  if (compressed.length !== entry.compressedBytes) throw new Error('cloud-object-size-invalid');
  const bytes = gunzipSync(compressed, { maxOutputLength: MAX_BYTES });
  if (bytes.length !== entry.bytes || sha256(bytes) !== entry.sha256) throw new Error('cloud-object-hash-invalid');
  const value = JSON.parse(bytes.toString('utf8'));
  validatePayloadBinding(value, route);
  return { value, bytes };
}
export function validatePayloadBinding(value, route) {
  const match = replayRoute.exec(route);
  if (match) {
    const [,runId,manifest,level,revision,token,start] = match;
    if (!record(value) || (manifest ? value.run_id : token ? value.run_id : value.run?.run_id) !== runId) throw new Error('cloud-source-invalid');
    if (manifest && !((value.state === 'ready' && hashPattern.test(value.revision) && value.run?.run_id === runId) ||
        (value.state === 'loading' && value.revision === null && value.run === null && Array.isArray(value.levels) && value.levels.length === 0))) throw new Error('cloud-manifest-invalid');
    if (revision && value.replay_revision !== revision) throw new Error('cloud-revision-invalid');
    if (token && (value.source_token !== token || value.level !== Number(level) || value.start !== Number(start) ||
        !Array.isArray(value.frames) || value.frames.length > 32)) throw new Error('cloud-frame-source-invalid');
    if (level && !token && (value.levels?.length !== 1 || value.levels[0].level !== Number(level))) throw new Error('cloud-level-invalid');
  }
  const preview = previewRoute.exec(route);
  if (preview && (!record(value) || value.run?.game_id !== preview[1] ||
      (preview[2] && (value.levels?.length !== 1 || value.levels[0].level !== Number(preview[2]))))) throw new Error('cloud-preview-invalid');
}
const packCache = new Map(); let cacheBytes = 0;
const packRequests = new Map();
async function readPack(get, entry, token) {
  const cached = packCache.get(entry.packSHA);
  if (cached) return cached;
  if (!packRequests.has(entry.packSHA)) {
    const pending = (async () => {
      const pack = await readBoundedBlob(get, entry.packPath, { token, maximum: entry.packBytes });
      if (pack.length !== entry.packBytes || sha256(pack) !== entry.packSHA) throw new Error('cloud-pack-hash-invalid');
      const previous = packCache.get(entry.packSHA);
      if (previous) cacheBytes -= previous.length;
      packCache.set(entry.packSHA,pack); cacheBytes += pack.length;
      while (cacheBytes > 32 * 1024 * 1024 && packCache.size) {
        const key = packCache.keys().next().value;
        cacheBytes -= packCache.get(key).length; packCache.delete(key);
      }
      return pack;
    })().finally(()=>packRequests.delete(entry.packSHA));
    packRequests.set(entry.packSHA,pending);
  }
  return packRequests.get(entry.packSHA);
}
export async function readRoute(get, index, route, token) {
  if (!allowedRoute(route) || !Object.hasOwn(index.routes, route)) throw new Error('cloud-route-unavailable');
  const entry = index.routes[route];
  const pack = await readPack(get,entry,token);
  return decodeObject(pack.subarray(entry.offset, entry.offset + entry.compressedBytes), entry, route);
}
