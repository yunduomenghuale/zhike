/* 最终验证（Edge 无头 + CDP）：教学资源列表布局调整 + tooltip 偏移修复 + 空表占位
 * 断言：
 *  ① 悬浮提示归位（dx/dy ≤ 30px，修复 backdrop-filter 包含块问题）
 *  ② 操作列按钮单行且为默认尺寸（高 32px，不做二次收缩）
 *  ③ 行高合理（≤ 50px）
 *  ④ 页面地址列短令牌
 *  ⑤ 表单两列并排 + 视频空表紧凑占位
 *  ⑥ 下拉菜单含 复制链接/删除
 *  ⑦ 0 控制台错误 / 0 失败请求
 * 用法: node verify-resource-layout.cjs <access_token> <app_url> <out_dir>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outDir = process.argv[4] || os.tmpdir();
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-reslayout-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-resource-layout.cjs <access_token> <app_url> <out_dir>');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = require('http').get(url, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
  });
}

async function main() {
  const edge = execFile(
    EDGE,
    [
      '--headless=new', '--remote-debugging-port=9224',
      `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run',
      '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000',
      'about:blank',
    ],
    () => {},
  );
  edge.unref();

  let version = null;
  for (let i = 0; i < 40; i++) {
    try { version = await getJson('http://127.0.0.1:9224/json/version'); break; } catch { await sleep(500); }
  }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }

  const targets = await getJson('http://127.0.0.1:9224/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let msgId = 0;
  const pending = new Map();
  const consoleErrors = [];
  const pageErrors = [];
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
    } else if (msg.method === 'Network.loadingFailed') {
      pageErrors.push(msg.params);
    } else if (msg.method === 'Network.responseReceived' && msg.params.response.status >= 400) {
      pageErrors.push({ url: msg.params.response.url, status: msg.params.response.status });
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++msgId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result?.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem('access_token', ${JSON.stringify(token)});`,
  });

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

  // ============ 教学资源列表 ============
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  let info = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    info = await evalJs(`(() => {
      const tables = Array.from(document.querySelectorAll('.compact-table'));
      const resRows = tables[0] ? Array.from(tables[0].querySelectorAll('.el-table__row')) : [];
      let opCell = null;
      let urlCell = null;
      let rowBox = null;
      if (resRows.length) {
        const row = resRows[0];
        const opDiv = row.querySelector('.op-cell');
        if (opDiv) {
          const btns = Array.from(opDiv.querySelectorAll('button'));
          const tops = btns.map(b => Math.round(b.getBoundingClientRect().top));
          opCell = {
            btnCount: btns.length,
            btnTops: tops,
            sameLine: new Set(tops).size === 1,
            btnHeight: btns[0] ? Math.round(btns[0].getBoundingClientRect().height) : null,
            width: Math.round(opDiv.getBoundingClientRect().width),
          };
        }
        const cells = Array.from(row.querySelectorAll('.el-table__cell'));
        const urlTd = cells.find(c => (c.textContent || '').includes('page/'));
        if (urlTd) {
          const link = urlTd.querySelector('.res-url-link');
          urlCell = {
            text: link ? link.textContent.trim() : '',
            isShortToken: !!(link && /^page\\/[0-9a-f]{8}…$/.test(link.textContent.trim())),
            overflowX: urlTd.scrollWidth > urlTd.clientWidth + 1,
          };
        }
        rowBox = { height: Math.round(row.getBoundingClientRect().height) };
      }
      return JSON.stringify({
        path: location.pathname,
        resRows: resRows.length,
        videoTableRows: tables[1] ? tables[1].querySelectorAll('.el-table__row').length : -1,
        videoEmptyHint: !!document.querySelector('.table-empty'),
        formRows: document.querySelectorAll('.form-row').length,
        opCell, urlCell, rowBox,
        moreBtns: document.querySelectorAll('.op-more').length,
      });
    })()`);
    const s = JSON.parse(info || '{}');
    if (s.resRows > 0) break;
  }
  const layout = JSON.parse(info || '{}');

  // 悬浮提示归位：找溢出最严重的单元格 hover（按 EP 同款逻辑查内层 .cell）
  const cellBox = JSON.parse(await evalJs(`(() => {
    const rows = document.querySelectorAll('.compact-table')[0].querySelectorAll('.el-table__row');
    let best = null;
    for (const row of rows) {
      for (const c of row.querySelectorAll('.el-table__cell')) {
        const inner = c.querySelector('.cell') || c;
        const over = inner.scrollWidth - inner.clientWidth;
        if (over > 4 && (!best || over > best.over)) best = { c, over };
      }
    }
    if (!best) return JSON.stringify({ found: false });
    const r = best.c.getBoundingClientRect();
    return JSON.stringify({ found: true, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right), over: best.over, text: best.c.textContent.trim().slice(0, 24) });
  })()`) || '{}');
  let tip = {};
  if (cellBox.found) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: cellBox.x, y: cellBox.y });
    for (let i = 0; i < 20; i++) {
      await sleep(300);
      const t = JSON.parse(await evalJs(`(() => {
        const p = Array.from(document.querySelectorAll('.el-popper')).find(x => {
          const cs = getComputedStyle(x);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          const r = x.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
        if (!p) return JSON.stringify({ shown: false });
        const r = p.getBoundingClientRect();
        return JSON.stringify({ shown: true, top: Math.round(r.top), left: Math.round(r.left), bottom: Math.round(r.bottom), w: Math.round(r.width), txt: (p.textContent || '').slice(0, 20) });
      })()`) || '{}');
      if (t.shown) { tip = t; break; }
    }
  }
  const tooltipDx = tip.shown && cellBox.found ? Math.round((tip.left + tip.w / 2) - (cellBox.left + (cellBox.right - cellBox.left) / 2)) : null;
  const tooltipDy = tip.shown && cellBox.found ? Math.round(tip.bottom - cellBox.top) : null;
  const tipPng = await shot('res-layout-final.png');

  // 点击 ⋯ 下拉确认菜单项
  let menu = null;
  await evalJs(`(() => { const b = document.querySelector('.op-more'); b && b.click(); })()`);
  for (let i = 0; i < 20; i++) {
    await sleep(300);
    menu = await evalJs(`(() => {
      const items = Array.from(document.querySelectorAll('.el-dropdown-menu__item'));
      const visible = items.filter(i => i.offsetParent !== null || getComputedStyle(i).display !== 'none');
      return JSON.stringify({ visibleCount: visible.length, texts: visible.map(i => i.textContent.trim()) });
    })()`);
    if (JSON.parse(menu || '{}').visibleCount > 0) break;
  }
  const menuInfo = JSON.parse(menu || '{}');

  const report = { layout, tooltip: { ...tip, dx: tooltipDx, dy: tooltipDy, cellFound: cellBox.found }, menu: menuInfo, png: tipPng, consoleErrors, failedRequests: pageErrors.slice(0, 8) };
  console.log(JSON.stringify(report, null, 2));

  const okRow = layout.rowBox && layout.rowBox.height > 0 && layout.rowBox.height <= 50;
  const okOp = layout.opCell && layout.opCell.sameLine && layout.opCell.btnCount >= 3 && layout.opCell.btnHeight === 32; // 默认尺寸按钮
  const okUrl = layout.urlCell && layout.urlCell.isShortToken && !layout.urlCell.overflowX;
  const okForm = layout.formRows >= 2; // 资源表单 + 视频表单各一行并排
  const okEmpty = layout.videoTableRows === -1 && layout.videoEmptyHint; // 空表被紧凑占位替代
  const okTip = tooltipDx !== null && Math.abs(tooltipDx) <= 30 && Math.abs(tooltipDy) <= 30;
  const okMenu = menuInfo.visibleCount >= 2 && menuInfo.texts.join(',').includes('复制链接') && menuInfo.texts.join(',').includes('删除');
  const okNoErr = consoleErrors.length === 0 && pageErrors.length === 0;
  console.log('VERDICT_TOOLTIP_ALIGNED=' + (okTip ? 'PASS' : 'FAIL') + ` (dx=${tooltipDx}, dy=${tooltipDy}, shown=${tip.shown})`);
  console.log('VERDICT_OP_SINGLE_LINE_DEFAULT_BTN=' + (okOp ? 'PASS' : 'FAIL') + ` (btns=${layout.opCell?.btnCount}, tops=${JSON.stringify(layout.opCell?.btnTops)}, btnH=${layout.opCell?.btnHeight})`);
  console.log('VERDICT_ROW_HEIGHT=' + (okRow ? 'PASS' : 'FAIL') + ` (height=${layout.rowBox?.height})`);
  console.log('VERDICT_SHORT_TOKEN=' + (okUrl ? 'PASS' : 'FAIL') + ` (text=${layout.urlCell?.text})`);
  console.log('VERDICT_FORM_TWO_COL=' + (okForm ? 'PASS' : 'FAIL') + ` (formRows=${layout.formRows})`);
  console.log('VERDICT_EMPTY_VIDEO_HINT=' + (okEmpty ? 'PASS' : 'FAIL') + ` (videoRows=${layout.videoTableRows}, hint=${layout.videoEmptyHint})`);
  console.log('VERDICT_DROPDOWN_MENU=' + (okMenu ? 'PASS' : 'FAIL') + ` (items=${JSON.stringify(menuInfo.texts)})`);
  console.log('VERDICT_NO_CONSOLE_ERROR=' + (okNoErr ? 'PASS' : 'FAIL'));
  if (consoleErrors.length) console.log('consoleErrors=' + JSON.stringify(consoleErrors.slice(0, 5)));
  if (pageErrors.length) console.log('failedRequests=' + JSON.stringify(pageErrors.slice(0, 5)));

  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(okRow && okOp && okUrl && okForm && okEmpty && okTip && okMenu && okNoErr ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
