/* A/B 验证：移除 .course-main-panel 的 backdrop-filter 后，表格 tooltip 是否归位
 * 用法: node ab-tooltip-fix.cjs <token> <app_url>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-ab-'));
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
  const edge = execFile(EDGE, ['--headless=new', '--remote-debugging-port=9227', `--user-data-dir=${userDataDir}`,
    '--no-proxy-server', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000', 'about:blank'], () => {});
  edge.unref();
  let v = null;
  for (let i = 0; i < 40; i++) { try { v = await getJson('http://127.0.0.1:9227/json/version'); break; } catch { await sleep(500); } }
  const targets = await getJson('http://127.0.0.1:9227/json/list');
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
  const evalJson = async (e) => JSON.parse((await evalJs(e)) || 'null');
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('access_token', ${JSON.stringify(token)});` });
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  for (let i = 0; i < 60; i++) { await sleep(500); if (await evalJs(`document.querySelectorAll('.el-table__row').length`) > 0) break; }

  async function measure(label) {
    const box = await evalJson(`(() => {
      const tables = document.querySelectorAll('.compact-table');
      const rows = tables[0].querySelectorAll('.el-table__row');
      const row = rows[rows.length - 1];
      const cells = Array.from(row.querySelectorAll('.el-table__cell'));
      const c = cells.find(x => (x.textContent || '').includes('思维导图：第2章')) || cells[0];
      const r = c.getBoundingClientRect();
      return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), top: Math.round(r.top), left: Math.round(r.left), bottom: Math.round(r.bottom), right: Math.round(r.right) });
    })()`);
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 5 });
    await sleep(400);
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
    let tip = {};
    for (let i = 0; i < 20; i++) {
      await sleep(300);
      const t = await evalJson(`(() => {
        const p = Array.from(document.querySelectorAll('.el-popper')).find(x => {
          const cs = getComputedStyle(x);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          const r = x.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
        if (!p) return JSON.stringify({ shown: false });
        const r = p.getBoundingClientRect();
        return JSON.stringify({ shown: true, top: Math.round(r.top), left: Math.round(r.left), bottom: Math.round(r.bottom), right: Math.round(r.right), w: Math.round(r.width), txt: (p.textContent || '').slice(0, 20) });
      })()`);
      if (t && t.shown) { tip = t; break; }
    }
    const dx = tip.shown ? Math.round((tip.left + tip.w / 2) - (box.left + (box.right - box.left) / 2)) : null;
    const dy = tip.shown ? Math.round(tip.bottom - box.top) : null;
    console.log(`${label}: cell水平中心=${Math.round(box.left + (box.right - box.left) / 2)} tip水平中心=${tip.shown ? Math.round(tip.left + tip.w / 2) : '-'} → 水平偏移dx=${dx}px; tip.bottom=${tip.bottom} cell.top=${box.top} → dy=${dy}px`);
    return { dx, dy };
  }

  const a = await measure('A-修复前(带backdrop-filter)');
  // 注册修复 CSS：下次导航时随新文档注入（同单元格重复进入不会重开 popper，必须重载页面）
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `document.addEventListener('DOMContentLoaded', () => {
      const st = document.createElement('style');
      st.textContent = '.course-main-panel{backdrop-filter:none !important;background:rgba(255,255,255,0.88) !important;}';
      document.head.appendChild(st);
    });`,
  });
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  for (let i = 0; i < 60; i++) { await sleep(500); if (await evalJs(`document.querySelectorAll('.el-table__row').length`) > 0) break; }
  await sleep(1500);
  console.log('DEBUG backdrop=', await evalJs(`getComputedStyle(document.querySelector('.course-main-panel')).backdropFilter`));
  const b = await measure('B-修复后(无backdrop-filter)');
  console.log('DEBUG poppers=', await evalJs(`JSON.stringify(Array.from(document.querySelectorAll('.el-popper')).map(p => ({vis: getComputedStyle(p).display, op: p.offsetParent ? 'y' : 'n', pos: getComputedStyle(p).position, txt: (p.textContent||'').slice(0,24)})))`));
  const metrics = await send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize || metrics.contentSize;
  const s = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: Math.min(size.width, 1600), height: Math.min(size.height, 1400), scale: 1 } });
  const png = path.join(os.tmpdir(), 'ab-panel.png');
  fs.writeFileSync(png, Buffer.from(s.data, 'base64'));
  console.log('screenshot: ' + png);
  const ok = b.dx !== null && b.dy !== null && Math.abs(b.dx) <= 30 && Math.abs(b.dy) <= 30;
  console.log('VERDICT=' + (ok ? 'PASS' : 'FAIL') + (b.dx === null ? ' (B组tooltip未显示)' : ''));
  ws.close(); edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(ok ? 0 : 4);
}
main().catch((e) => { console.error('FAIL', e); process.exit(1); });
