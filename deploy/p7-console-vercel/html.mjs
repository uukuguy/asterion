import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
let assets;
const inline = value => JSON.stringify(value).replaceAll('&','\\u0026').replaceAll('<','\\u003c').replaceAll('>','\\u003e').replaceAll('\u2028','\\u2028').replaceAll('\u2029','\\u2029');
const hash = value => 'sha256-' + createHash('sha256').update(value).digest('base64');
const syncJS = `\n(() => {
  const label = document.createElement('span'); label.id = 'cloud-sync-status'; label.setAttribute('role','status');
  document.querySelector('.header-note').append(label);
  async function update() { try {
    const response = await fetch('/api/sync-status', {cache:'no-store',signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('unavailable'); const data = await response.json();
    label.textContent = ' · 云端只读 · 数据更新 ' + data.capturedAt + ' · ' + data.ageSeconds + ' 秒前' +
      (data.uploadOperations ? ' · 上传操作 ' + data.uploadOperations.attempts + '/' + data.uploadOperations.limit : '') +
      (data.storage?.warning ? ' · 云端存储接近限额；请检查本地发布器' : '');
  } catch (_) { label.textContent = ' · 云端同步读取失败 · 保留最近画面'; } }
  update(); const timer = setInterval(update,60000); addEventListener('pagehide',()=>clearInterval(timer));
})();`;
export async function renderHTML(snapshot, games) {
  if (!assets) {
    const read = name => readFile(new URL(`./assets/${name}`, import.meta.url), 'utf8');
    const [template,tailwind,styles,js] = await Promise.all(['index.html','tailwind.css','styles.css','app.js'].map(read));
    assets = {template,css:tailwind+'\n'+styles,js:js+syncJS};
  }
  const data = inline(snapshot); const config = inline({readOnly:true,games,replay_loading:'level-manifest/v1'});
  const csp = `default-src 'none'; connect-src 'self'; img-src data:; style-src '${hash(assets.css)}'; script-src '${hash(assets.js)}' '${hash(data)}' '${hash(config)}'; base-uri 'none'; form-action 'none'; object-src 'none'`;
  const replacements = {__CONSOLE_CSP__:csp,__CONSOLE_CSS__:assets.css,__CONSOLE_JS__:assets.js,__CONSOLE_DATA__:data,__CONSOLE_CONFIG__:config};
  return assets.template.replace(/__CONSOLE_(?:CSP|CSS|JS|DATA|CONFIG)__/g, marker => replacements[marker]);
}
