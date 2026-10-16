/* 诊断：表格 tooltip 偏移根因 —— 祖先链包含块属性 + popper 定位上下文
 * 用法: node diag-tooltip.cjs <token> <app_url>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-diag-'));
if (!token || !APP_URL) { console.error('usage'); process.exit(2); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = require('http').get(url, (res) => {
      let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    }); req.on('error', reject);
  });
}
async function main() {
  const edge = execFile(EDGE, ['--headless=new', '--remote-debugging-port=9226', `--user-data-dir=${userDataDir}`,
    '--no-proxy-server', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000', 'about:blank'], () => {});
  edge.unref();
  let v = null;
  for (let i = 0; i < 40; i++) { try { v = await getJson('http://127.0.0.1:9226/json/version'); break; } catch { await sleep(500); } }
  const targets = await getJson('http://127.0.0.1:9226/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const { resolve, reject } = pending.get(m.id); pending.delete(m.id); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => { const i = ++id; pending.set(i, { resolve, reject }); ws.send(JSON.stringify({ id: i, method, params })); });
  const evalJs = async (e) => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.value;
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('access_token', ${JSON.stringify(token)});` });
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  for (let i = 0; i < 60; i++) { await sleep(500); if (await evalJs(`document.querySelectorAll('.el-table__row').length`) > 0) break; }

  const chain = await evalJs(`(() => {
    const table = document.querySelector('.compact-table');
    const out = [];
    let el = table;
    while (el && el !== document.documentElement) {
      const cs = getComputedStyle(el);
      const flags = [];
      for (const p of ['transform', 'filter', 'willChange', 'contain', 'perspective', 'backdropFilter', 'transformStyle']) {
        const val = cs[p];
        if (val && val !== 'none' && val !== 'auto' && val !== 'flat' && val !== 'visible') flags.push(p + '=' + val.slice(0, 60));
      }
      out.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className || '').toString().slice(0, 60),
        position: cs.position,
        flags,
      });
      el = el.parentElement;
    }
    return JSON.stringify(out);
  })()`);
  console.log('ANCESTOR_CHAIN:');
  console.log(chain);

  // hover 触发 tooltip，然后检查 popper 的 position 与 offsetParent
  const box = await evalJs(`(() => {
    const tables = document.querySelectorAll('.compact-table');
    const rows = tables[0].querySelectorAll('.el-table__row');
    const row = rows[rows.length - 1];
    const cells = Array.from(row.querySelectorAll('.el-table__cell'));
    const c = cells.find(x => (x.textContent || '').includes('思维导图：第2章')) || cells[0];
    const r = c.getBoundingClientRect();
    return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) });
  })()`);
  const b = JSON.parse(box);
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: b.x, y: b.y });
  let tip = null;
  for (let i = 0; i < 20; i++) {
    await sleep(300);
    tip = await evalJs(`(() => {
      const p = Array.from(document.querySelectorAll('.el-popper')).find(x => x.offsetParent !== null || getComputedStyle(x).display !== 'none');
      if (!p) return JSON.stringify({ shown: false });
      const cs = getComputedStyle(p);
      const r = p.getBoundingClientRect();
      return JSON.stringify({
        shown: true, position: cs.position, transform: cs.transform, left: cs.left, top: cs.top,
        rect: { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width) },
        offsetParent: p.offsetParent ? p.offsetParent.tagName.toLowerCase() + '.' + (p.offsetParent.className || '').toString().slice(0, 50) : null,
        parent: p.parentElement ? p.parentElement.tagName.toLowerCase() + '.' + (p.parentElement.className || '').toString().slice(0, 50) : null,
      });
    })()`);
    if (JSON.parse(tip || '{}').shown) break;
  }
  console.log('POPPER:', tip);
  ws.close(); edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(0);
}
main().catch((e) => { console.error('FAIL', e); process.exit(1); });
