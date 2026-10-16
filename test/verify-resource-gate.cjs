/* 浏览器级验证（Edge 无头 + CDP）：
 * A. 教师课程空间 → 教学资源 → 预览（sign → 查看器 iframe 加载签名预置页）
 * B. 教师课程空间 → 学习统计 → 点击学生卡片（应停留在课程空间，导航栏不变主导航）
 * 用法: node verify-resource-gate.cjs <access_token> <app_url> <out_dir>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outDir = process.argv[4] || os.tmpdir();
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-resgate-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-resource-gate.cjs <access_token> <app_url> <out_dir>');
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
      '--headless=new', '--remote-debugging-port=9223',
      `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run',
      '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000',
      'about:blank',
    ],
    () => {},
  );
  edge.unref();

  let version = null;
  for (let i = 0; i < 40; i++) {
    try { version = await getJson('http://127.0.0.1:9223/json/version'); break; } catch { await sleep(500); }
  }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }

  const targets = await getJson('http://127.0.0.1:9223/json/list');
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

  const report = {};

  // ============ A. 教学资源预览 ============
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  let a = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    a = await evalJs(`(() => {
      const rows = document.querySelectorAll('.el-table__row');
      const urls = Array.from(document.querySelectorAll('.res-url-link')).map(e => e.textContent.trim());
      const previewBtns = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.trim() === '预览');
      return JSON.stringify({ rows: rows.length, urls, hasPreview: previewBtns.length, url: location.pathname });
    })()`);
    const s = JSON.parse(a || '{}');
    if (s.rows > 0) break;
  }
  const rowsInfo = JSON.parse(a || '{}');
  // 点击第一行「预览」→ 进入查看器（sign → iframe）
  await evalJs(`(() => {
    const btns = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.trim() === '预览');
    btns[0] && btns[0].click();
  })()`);
  let frame = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    frame = await evalJs(`(() => {
      const ifr = document.querySelector('iframe.viewer-frame');
      if (!ifr) return JSON.stringify({ hasFrame: false, path: location.pathname });
      let doc = null;
      try { doc = ifr.contentDocument; } catch (e) { return JSON.stringify({ hasFrame: true, crossOrigin: true }); }
      return JSON.stringify({
        hasFrame: true,
        src: (ifr.getAttribute('src') || '').slice(0, 120),
        title: doc?.title || '',
        hasBase: !!doc?.querySelector('base[href*="course-resources/asset"]'),
        hasSvg: !!doc?.querySelector('#mindmap svg, svg.markmap, .markmap svg'),
        bodyLen: (doc?.body?.textContent || '').length,
      });
    })()`);
    const s = JSON.parse(frame || '{}');
    if (s.hasSvg || (s.title && s.hasBase)) break;
  }
  report.resource = {
    tableRows: rowsInfo.rows,
    uniqueUrls: [...new Set(rowsInfo.urls || [])].slice(0, 3),
    urlsAllUnique: new Set(rowsInfo.urls || []).size === (rowsInfo.urls || []).length,
    frame: JSON.parse(frame || '{}'),
  };
  report.resourcePng = await shot('res-gate-viewer.png');

  // ============ B. 学习统计 → 学生详情（导航栏应保持课程空间） ============
  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/analytics` });
  let b = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    b = await evalJs(`(() => {
      const cards = document.querySelectorAll('.stu-card');
      return JSON.stringify({ cards: cards.length, path: location.pathname });
    })()`);
    if (JSON.parse(b || '{}').cards > 0) break;
  }
  await evalJs(`(() => { const c = document.querySelector('.stu-card'); c && c.click(); })()`);
  let detail = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    detail = await evalJs(`(() => JSON.stringify({
      path: location.pathname,
      hasCoursePage: !!document.querySelector('.course-page'),
      hasCourseRail: !!document.querySelector('.course-rail'),
      hasMainSidebar: !!document.querySelector('.sidebar, .main-sidebar, .layout-sidebar'),
      hasDetail: !!document.querySelector('.stu-detail-page'),
      heroName: document.querySelector('.hero-name')?.textContent || '',
      statCards: document.querySelectorAll('.stat-card').length,
    }))()`);
    const s = JSON.parse(detail || '{}');
    if (s.hasDetail) break;
  }
  report.analytics = JSON.parse(detail || '{}');
  report.analyticsPng = await shot('res-gate-student-detail.png');

  report.consoleErrors = consoleErrors;
  report.failedRequests = pageErrors.slice(0, 8);

  console.log(JSON.stringify(report, null, 2));
  const okA = report.resource?.frame?.hasBase && report.resource?.frame?.hasSvg && report.resource?.urlsAllUnique;
  const okB = report.analytics?.hasDetail && report.analytics?.hasCoursePage && !report.analytics?.hasMainSidebar;
  console.log('VERDICT_A_RESOURCE=' + (okA ? 'PASS' : 'FAIL'));
  console.log('VERDICT_B_NAVBAR=' + (okB ? 'PASS' : 'FAIL'));

  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(okA && okB ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
