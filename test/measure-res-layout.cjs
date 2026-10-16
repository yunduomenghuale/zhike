/* 实测（Edge 无头 + CDP）：资源页空白分布 + show-overflow-tooltip 偏移量
 * 用法: node measure-res-layout.cjs <access_token> <app_url> <out_dir>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outDir = process.argv[4] || os.tmpdir();
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-resmeasure-'));

if (!token || !APP_URL) { console.error('usage: node measure-res-layout.cjs <token> <app_url> <out_dir>'); process.exit(2); }
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
  const edge = execFile(EDGE, [
    '--headless=new', '--remote-debugging-port=9225',
    `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000', 'about:blank',
  ], () => {});
  edge.unref();
  let version = null;
  for (let i = 0; i < 40; i++) { try { version = await getJson('http://127.0.0.1:9225/json/version'); break; } catch { await sleep(500); } }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }
  const targets = await getJson('http://127.0.0.1:9225/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let msgId = 0;
  const pending = new Map();
  const consoleErrors = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      consoleErrors.push(msg.params.args.map((a) => a.value || a.description || '').join(' '));
    } else if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description || ''));
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++msgId; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result?.value;
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('access_token', ${JSON.stringify(token)});` });

  const shot = async (name) => {
    const metrics = await send('Page.getLayoutMetrics');
    const size = metrics.cssContentSize || metrics.contentSize;
    const s = await send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: Math.min(size.width, 1600), height: Math.min(size.height, 2400), scale: 1 },
    });
    const p = path.join(outDir, name);
    fs.writeFileSync(p, Buffer.from(s.data, 'base64'));
    return p;
  };

  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    const n = await evalJs(`document.querySelectorAll('.el-table__row').length`);
    if (n > 0) break;
  }

  // ---- 1. 空白分布测量 ----
  const layout = await evalJs(`(() => {
    const R = (el) => { const r = el.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height), width: Math.round(r.width) }; };
    const cs = (el, p) => getComputedStyle(el)[p];
    const cards = Array.from(document.querySelectorAll('.res-panel'));
    const out = { cards: [], gaps: {} };
    // 页面容器
    const pc = document.querySelector('.page-container');
    if (pc) out.pageContainerPad = cs(pc, 'padding');
    // 表单与表格间距
    const form = document.querySelector('.res-panel .el-form');
    const table = document.querySelector('.res-panel .el-table');
    if (form && table) {
      const fr = form.getBoundingClientRect(), tr = table.getBoundingClientRect();
      out.gaps.formToTable = Math.round(tr.top - fr.bottom);
      out.formMarginBottom = cs(form, 'marginBottom');
    }
    // 卡片间缝隙
    if (cards.length === 2) {
      out.gaps.cardGap = Math.round(cards[1].getBoundingClientRect().top - cards[0].getBoundingClientRect().bottom);
      out.card1MarginBottom = cs(cards[0], 'marginBottom');
    }
    // 卡片内边距
    const body = document.querySelector('.res-panel .el-card__body');
    if (body) out.cardBodyPad = cs(body, 'padding');
    const header = document.querySelector('.res-panel .el-card__header');
    if (header) out.cardHeaderPad = cs(header, 'padding');
    // 表头行高 / 数据行高 / 单元格内边距 / 按钮高度
    const th = document.querySelector('.compact-table .el-table__header th');
    if (th) out.headerRow = R(th);
    const rows = Array.from(document.querySelectorAll('.compact-table')[0]?.querySelectorAll('.el-table__row') || []);
    out.rowHeights = rows.map(R).map(r => r.height);
    const td = document.querySelector('.compact-table .el-table__cell');
    if (td) out.cellPad = cs(td, 'paddingTop') + ' ' + cs(td, 'paddingBottom');
    const btn = document.querySelector('.op-cell .el-button');
    if (btn) { out.btnBox = R(btn); out.btnHeight = cs(btn, 'height'); out.btnPad = cs(btn, 'padding'); }
    // 空表格（视频表 0 行）的空白块高度
    const emptyBlock = document.querySelector('.el-table__empty-block');
    if (emptyBlock) out.emptyBlock = R(emptyBlock);
    const emptyText = document.querySelector('.el-table__empty-text');
    if (emptyText) out.emptyTextMinH = cs(emptyText, 'minHeight');
    // 表单项间距
    const fi = document.querySelector('.res-panel .el-form-item');
    if (fi) out.formItemMargin = cs(fi, 'marginBottom');
    // 表单整体高度
    if (form) out.formHeight = R(form).height;
    // 操作列宽
    const opCell = document.querySelector('.op-cell');
    if (opCell) out.opCellWidth = R(opCell).width;
    return JSON.stringify(out);
  })()`);
  const layoutInfo = JSON.parse(layout || '{}');

  // ---- 2. 悬浮提示偏移：hover 最后一行的「章节」单元格 ----
  const cellBox = await evalJs(`(() => {
    const tables = document.querySelectorAll('.compact-table');
    const rows = tables[0].querySelectorAll('.el-table__row');
    const row = rows[rows.length - 1];
    const cells = Array.from(row.querySelectorAll('.el-table__cell'));
    const c = cells.find(x => (x.textContent || '').includes('第2章'));
    if (!c) return JSON.stringify({ found: false });
    const r = c.getBoundingClientRect();
    return JSON.stringify({ found: true, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right), text: c.textContent.trim().slice(0, 30), overflowing: c.scrollWidth > c.clientWidth + 1 });
  })()`);
  const cell = JSON.parse(cellBox || '{}');
  let tip = {};
  if (cell.found) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: cell.x, y: cell.y });
    for (let i = 0; i < 20; i++) {
      await sleep(300);
      const t = await evalJs(`(() => {
        const pops = Array.from(document.querySelectorAll('.el-popper')).filter(p => p.style.display !== 'none' && p.offsetParent !== null);
        const tip = pops.find(p => (p.textContent || '').includes('第2章'));
        if (!tip) return JSON.stringify({ shown: false });
        const r = tip.getBoundingClientRect();
        return JSON.stringify({ shown: true, text: tip.textContent.trim().slice(0, 40), top: Math.round(r.top), left: Math.round(r.left), bottom: Math.round(r.bottom), right: Math.round(r.right), placement: tip.getAttribute('data-popper-placement') || '', ariaDesc: tip.getAttribute('aria-describedby') || '' });
      })()`);
      const s = JSON.parse(t || '{}');
      if (s.shown) { tip = s; break; }
    }
  }
  const tipPng = await shot('res-tooltip-offset.png');

  const report = { layout: layoutInfo, cell, tooltip: tip, tooltipPng: tipPng, consoleErrors };
  console.log(JSON.stringify(report, null, 2));

  // 判定：提示框应紧贴单元格（垂直方向在单元格附近，水平左缘接近单元格左缘）
  const dx = tip.shown && cell.found ? Math.abs(tip.left - cell.left) : null;
  const dy = tip.shown && cell.found ? Math.abs(tip.top - cell.top) : null;
  const okTip = tip.shown && dx !== null && dx <= 30 && dy <= 30;
  console.log('TOOLTIP_OFFSET dx=' + dx + ' dy=' + dy + ' placement=' + (tip.placement || '-'));
  console.log('VERDICT_TOOLTIP=' + (okTip ? 'PASS' : 'FAIL'));
  ws.close(); edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(0);
}
main().catch((e) => { console.error('FAIL', e); process.exit(1); });
