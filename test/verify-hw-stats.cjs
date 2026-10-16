/* 用系统 Edge 无头模式 + CDP 验证需登录的 SPA 页面渲染（绕过被拦的 Chromium 下载与 http 代理污染）。
 * 用法: node verify-hw-stats.cjs <access_token> <app_url> <out_png>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outPng = process.argv[4] || path.join(os.tmpdir(), 'verify-page.png');
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-verify-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-hw-stats.cjs <token> <app_url> <out_png>');
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
      '--headless=new',
      '--remote-debugging-port=9222',
      `--user-data-dir=${userDataDir}`,
      '--no-proxy-server',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--window-size=1600,2200',
      'about:blank',
    ],
    () => {},
  );
  edge.unref();

  // 等 devtools 端口就绪
  let version = null;
  for (let i = 0; i < 40; i++) {
    try { version = await getJson('http://127.0.0.1:9222/json/version'); break; } catch { await sleep(500); }
  }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }

  let targets = await getJson('http://127.0.0.1:9222/json/list');
  let page = targets.find((t) => t.type === 'page');
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
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++msgId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  await send('Page.enable');
  await send('Runtime.enable');
  // 预置登录态：SAP 读取 localStorage access_token，守卫会自行拉取 profile
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem('access_token', ${JSON.stringify(token)});`,
  });

  await send('Page.navigate', { url: APP_URL });

  // 轮询等待统计页渲染：总览卡片与排名表格出现
  let ok = false;
  let snapshotText = '';
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    const r = await send('Runtime.evaluate', {
      expression: `(() => {
        const page = document.querySelector('.homework-stats-page');
        const cards = document.querySelectorAll('.stat-card').length;
        const rankRows = document.querySelectorAll('.table-card tbody tr').length;
        const title = document.querySelector('.page-title')?.textContent || '';
        const err = document.querySelector('.el-empty__description')?.textContent || '';
        return JSON.stringify({ hasPage: !!page, cards, rankRows, title, err });
      })()`,
      returnByValue: true,
    });
    snapshotText = r.result.value;
    const s = JSON.parse(snapshotText || '{}');
    if (s.cards > 0 && s.rankRows > 0) { ok = true; break; }
    // 被守卫弹回登录页则失败
    if (location_guard(s)) { break; }
  }
  function location_guard(s) {
    return s.title === '登录' || s.err.includes('暂无统计数据') && s.cards === 0;
  }

  // 全页截图
  const metrics = await send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize || metrics.contentSize;
  const shot = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: Math.min(size.width, 1600), height: Math.min(size.height, 4000), scale: 1 },
  });
  fs.writeFileSync(outPng, Buffer.from(shot.data, 'base64'));

  // 关键文案抽查
  const texts = await send('Runtime.evaluate', {
    expression: `JSON.stringify({
      subtitle: document.querySelector('.page-subtitle')?.textContent,
      labels: Array.from(document.querySelectorAll('.stat-label')).map(e => e.textContent),
      values: Array.from(document.querySelectorAll('.stat-value')).map(e => e.textContent),
      chartTitles: Array.from(document.querySelectorAll('.chart-title')).map(e => e.textContent),
      firstRow: document.querySelector('.table-card tbody tr')?.textContent,
    })`,
    returnByValue: true,
  });

  console.log('RENDER_OK=' + ok);
  console.log('SNAPSHOT=' + snapshotText);
  console.log('TEXTS=' + texts.result.value);
  console.log('CONSOLE_ERRORS=' + JSON.stringify(consoleErrors));
  console.log('PNG=' + outPng);

  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(ok ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
