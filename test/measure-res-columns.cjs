/* 测量（Edge 无头 + CDP）：资源表容器宽度 + 各列渲染宽度 + 按钮宽度
 * 用法: node measure-res-columns.cjs <access_token> <app_url>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-rescols-'));

if (!token || !APP_URL) { console.error('usage: node measure-res-columns.cjs <token> <url>'); process.exit(2); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = require('http').get(url, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
    });
    req.on('error', reject);
  });
}

async function main() {
  const edge = execFile(EDGE, ['--headless=new', '--remote-debugging-port=9226', `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1440,1000', 'about:blank'], () => {});
  edge.unref();
  let version = null;
  for (let i = 0; i < 40; i++) { try { version = await getJson('http://127.0.0.1:9226/json/version'); break; } catch { await sleep(500); } }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }
  const targets = await getJson('http://127.0.0.1:9226/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    }
  };
  const send = (m, p = {}) => new Promise((resolve, reject) => { const id = ++msgId; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method: m, params: p })); });
  const evalJs = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('access_token', ${JSON.stringify(token)});` });

  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  let info = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    info = await evalJs(`(() => {
      const rows = document.querySelectorAll('.res-panel .compact-table .el-table__row');
      if (!rows.length) return JSON.stringify({ ready: false });
      const table = document.querySelector('.res-panel .compact-table');
      const headerCells = Array.from(table.querySelectorAll('.el-table__header th'));
      const row = rows[0];
      const cells = Array.from(row.querySelectorAll('.el-table__cell'));
      const opBtns = Array.from(row.querySelectorAll('.op-cell button'));
      const measure = (el) => { const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; };
      const cols = headerCells.map((th, i) => {
        const c = cells[i];
        const inner = c ? (c.querySelector('.cell') || c) : null;
        return {
          label: th.textContent.trim(),
          width: Math.round(th.getBoundingClientRect().width),
          contentW: inner ? Math.round(inner.scrollWidth) : null,
          cellPad: inner ? getComputedStyle(inner).padding : null,
        };
      });
      return JSON.stringify({
        ready: true,
        tableClientW: table.clientWidth,
        tableBodyW: Math.round((table.querySelector('.el-table__body') || table).getBoundingClientRect().width),
        cols,
        opBtns: opBtns.map((b) => ({ txt: b.textContent.trim(), ...measure(b) })),
        opCell: measure(row.querySelector('.op-cell')),
        viewportW: window.innerWidth,
        sidebarW: Math.round(document.querySelector('.course-rail')?.getBoundingClientRect().width || 0),
      });
    })()`);
    if (JSON.parse(info || '{}').ready) break;
  }
  console.log(JSON.stringify(JSON.parse(info || '{}'), null, 2));
  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
}
main().catch((e) => { console.error('FAIL', e); process.exit(1); });
