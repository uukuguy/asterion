// Run from the repository after console UI changes; deployment has no adjacent-source dependency.
import { readFile, writeFile, copyFile } from 'node:fs/promises';
const source = new URL('../../src/asterion/applications/prime/p7/console_assets/', import.meta.url);
const target = new URL('./assets/', import.meta.url);
for (const name of ['index.html', 'styles.css', 'tailwind.css', 'TAILWIND-LICENSE.txt']) {
  await copyFile(new URL(name, source), new URL(name, target));
}
let js = await readFile(new URL('app.js', source), 'utf8');
function replace(before, after) {
  if (!js.includes(before)) throw new Error('console-source-changed');
  js = js.replace(before, after);
}
replace("const liveConfig = isRecord(consoleConfig) && typeof consoleConfig.token === 'string' && consoleConfig.token ? consoleConfig : null;",
  "const liveConfig = isRecord(consoleConfig) && consoleConfig.readOnly === true ? consoleConfig : null;\n" +
  "  const CLOUD_REFRESH_INTERVAL = 300000;\n" +
  "  function enforceCloudReadOnly() {\n" +
  "    document.querySelectorAll('#run-start,#run-fresh,#run-pause,#run-resume,#run-stop,#manual-close,#manual-restart,#retry-command,[data-overview-start],[data-overview-fresh]').forEach(button => {button.disabled = true; button.title = '云端只读；请在本地控制求解';});\n" +
  "    $('game-select').disabled = false;\n" +
  "    $('manual-note').textContent = '云端只读观察与回放；游戏动作和求解控制在本地执行。';\n" +
  "  }\n" +
  "  $('console-mode').querySelector('option[value=manual]')?.remove();");
replace("async function request(path, command = null) {", "async function request(path, command = null) {\n    if (command) throw new Error('request-rejected');");
replace("headers: { 'X-P7-Console-Token': liveConfig.token, ...(command ? { 'Content-Type': 'application/json' } : {}) },", "headers: {},");
replace("write('session-id', manual && state.manualView?.session_id ? `试玩 ${state.manualView.session_id}` : state.liveView?.session_id ? `会话 ${state.liveView.session_id}` : '');",
  "write('session-id', state.liveView?.session_id ? `会话 ${state.liveView.session_id}` : '');\n    enforceCloudReadOnly();");
replace("row.querySelector('[data-overview-select]').disabled = manualUnsaved() || Boolean(state.manualPending) || state.commandBusy;\n    });",
  "row.querySelector('[data-overview-select]').disabled = manualUnsaved() || Boolean(state.manualPending) || state.commandBusy;\n    });\n    enforceCloudReadOnly();");
js = js.replaceAll('正在连接本地服务', '正在读取云端同步记录');
replace('window.setInterval(pollState, 1000)', 'window.setInterval(pollState, CLOUD_REFRESH_INTERVAL)');
replace('window.setInterval(loadOverview, 5000)', 'window.setInterval(loadOverview, CLOUD_REFRESH_INTERVAL)');
replace('window.setInterval(() => loadReplay(),2000)', 'window.setInterval(() => loadReplay(), CLOUD_REFRESH_INTERVAL)');
replace('window.setInterval(() => loadReplay(), 2000)', 'window.setInterval(() => loadReplay(), CLOUD_REFRESH_INTERVAL)');
await writeFile(new URL('app.js', target), js);
