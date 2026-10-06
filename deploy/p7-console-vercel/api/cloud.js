import { get } from '@vercel/blob';
import { MAX_BYTES, allowedRoute, readIndex, readRoute } from '../cloud.mjs';
import { renderHTML } from '../html.mjs';

export function createHandler(blobGet = get) {
  let indexPromise = null; let indexUntil = 0;
  const currentIndex = () => {
    if (!indexPromise || Date.now() >= indexUntil) {
      indexUntil = Date.now() + 60000;
      indexPromise = readIndex(blobGet,process.env.BLOB_READ_WRITE_TOKEN).catch(error=>{indexPromise=null;throw error;});
    }
    return indexPromise;
  };
  return async function handler(req, res) {
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Cache-Control','no-store');
    res.setHeader('Vercel-CDN-Cache-Control','no-store');
    if (!['GET','HEAD'].includes(req.method)) {
      res.setHeader('Allow','GET, HEAD'); res.statusCode = 405;
      return res.end(JSON.stringify({error:'cloud-read-only'}));
    }
    const url = new URL(req.url, 'https://console.invalid');
    const route = req.query?.route ?? url.searchParams.get('route') ?? url.pathname;
    if (typeof route !== 'string' || (route !== '/' && route !== '/api/sync-status' && !allowedRoute(route))) {
      res.statusCode = 404; return res.end(JSON.stringify({error:'cloud-route-unavailable'}));
    }
    try {
      const index = await currentIndex();
      res.setHeader('X-P7-Sync-Generation',index.generation);
      res.setHeader('X-P7-Sync-Captured-At',index.capturedAt);
      let body; let type = 'application/json; charset=utf-8';
      if (route === '/api/sync-status') {
        const ageSeconds = Math.max(0,Math.floor((Date.now()-Date.parse(index.capturedAt))/1000));
        body = Buffer.from(JSON.stringify({schema:'asterion.p7.cloud-sync-status/v1',readOnly:true,capturedAt:index.capturedAt,
          generation:index.generation,logicalGeneration:index.logicalGeneration,ageSeconds,routes:Object.keys(index.routes).length,
          uploadOperations:index.uploadOperations,storage:index.storage}));
      } else if (route === '/') {
        const state = (await readRoute(blobGet,index,'/api/state')).value;
        const catalog = (await readRoute(blobGet,index,'/api/games')).value;
        const games = Array.isArray(catalog) ? catalog : catalog.games;
        if (!Array.isArray(games) || !games.length) throw new Error('cloud-catalog-invalid');
        const snapshot = state.snapshot ?? (await readRoute(blobGet,index,`/api/preview/${games[0].game_id}`)).value;
        body = Buffer.from(await renderHTML(snapshot,games)); type = 'text/html; charset=utf-8';
      } else {
        if (!Object.hasOwn(index.routes,route)) { res.statusCode = 404; return res.end(JSON.stringify({error:'cloud-route-unavailable'})); }
        body = (await readRoute(blobGet,index,route)).bytes;
        if (/\/levels\//.test(route)) {
          res.setHeader('Cache-Control','public, max-age=31536000, immutable');
          res.setHeader('Vercel-CDN-Cache-Control','public, max-age=31536000, immutable');
        }
      }
      if (body.length > MAX_BYTES) throw new Error('cloud-response-too-large');
      res.setHeader('Content-Type',type); res.setHeader('Content-Length',body.length);
      res.statusCode = 200; return res.end(req.method === 'HEAD' ? undefined : body);
    } catch (_) {
      res.statusCode = 503; res.setHeader('Content-Type','application/json');
      return res.end(JSON.stringify({error:'cloud-view-unavailable',readOnly:true}));
    }
  };
}
export default createHandler();
