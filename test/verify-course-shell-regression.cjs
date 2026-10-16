/* 回归验证（Edge 无头 + CDP）：课程空间 CourseWorkspaceShell（本轮移除 backdrop-filter 后的副作用排查）
 * 断言（每个页面）：
 *  ① 课程空间外壳渲染（.course-page / .course-rail 存在，非主导航）
 *  ② 无控制台错误 / 无 4xx-5xx 失败请求
 *  ③ 关键内容渲染（课程主页卡片 / 公告 / 作业表 / 资源表）
 * 用法: node verify-course-shell-regression.cjs <access_token> <app_url> <out_dir>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outDir = process.argv[4] || os.tmpdir();
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-shellreg-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-course-shell-regression.cjs <access_token> <app_url> <out_dir>');
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

const PAGES = [
  { name: 'course-home', url: `${APP_URL}/teacher/courses/5`, check: '.course-hero, .course-overview, .course-main-panel', shot: 'reg-course-home.png' },
  { name: 'course-chapters', url: `${APP_URL}/teacher/courses/5/chapters`, check: '.course-main-panel', shot: 'reg-course-chapters.png' },
  { name: 'course-exams', url: `${APP_URL}/teacher/courses/5/exams`, check: '.course-main-panel', shot: 'reg-course-exams.png' },
  { name: 'course-resources', url: `${APP_URL}/teacher/courses/5/resources`, check: '.res-panel', shot: 'reg-course-resources.png' },
  { name: 'course-homework', url: `${APP_URL}/teacher/courses/5/homework`, check: '.course-main-panel', shot: 'reg-course-homework.png' },
];

async function main() {
  const edge = execFile(
    EDGE,
    [
      '--headless=new', '--remote-debugging-port=9225',
      `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run',
      '--no-default-browser-check', '--disable-extensions', '--window-size=1600,1000',
      'about:blank',
    ],
    () => {},
  );
  edge.unref();

  let version = null;
  for (let i = 0; i < 40; i++) {
    try { version = await getJson('http://127.0.0.1:9225/json/version'); break; } catch { await sleep(500); }
  }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }

  const targets = await getJson('http://127.0.0.1:9225/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let msgId = 0;
  const pending = new Map();
  let consoleErrors = [];
  let pageErrors = [];
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
      pageErrors.push({ url: msg.params.request?.url, error: msg.params.errorText });
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

  const results = [];
  for (const p of PAGES) {
    consoleErrors = [];
    pageErrors = [];
    await send('Page.navigate', { url: p.url });
    let info = null;
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      info = await evalJs(`(() => {
        const shell = document.querySelector('.course-page');
        const rail = document.querySelector('.course-rail');
        const mainNav = document.querySelector('.main-layout, .app-sidebar, .el-menu--horizontal');
        const check = document.querySelector(${JSON.stringify(p.check)});
        const txt = (document.body.innerText || '').replace(/\\s+/g, ' ').trim();
        return JSON.stringify({
          path: location.pathname,
          hasShell: !!shell,
          hasRail: !!rail,
          hasMainNav: !!mainNav,
          hasCheck: !!check,
          bodyLen: txt.length,
          bodyHead: txt.slice(0, 60),
          hasVueApp: !!document.querySelector('#app') && document.querySelector('#app').children.length > 0,
        });
      })()`);
      const s = JSON.parse(info || '{}');
      if (s.hasShell && s.hasCheck) break;
      if (s.path !== new URL(p.url).pathname && i > 8) break; // 路由跳走（重定向等）
    }
    const parsed = JSON.parse(info || '{}');
    const ok =
      parsed.hasShell && parsed.hasRail && !parsed.hasMainNav && parsed.hasCheck &&
      parsed.bodyLen > 20 && consoleErrors.length === 0 && pageErrors.length === 0;
    const png = await shot(p.shot);
    results.push({ page: p.name, ok, ...parsed, consoleErrors: consoleErrors.slice(0, 5), failedRequests: pageErrors.slice(0, 5), png });
    console.log(JSON.stringify(results[results.length - 1], null, 2));
  }

  let allOk = results.every((r) => r.ok);
  for (const r of results) console.log(`VERDICT_${r.page.toUpperCase().replace(/-/g, '_')}=` + (r.ok ? 'PASS' : 'FAIL'));
  console.log('VERDICT_ALL=' + (allOk ? 'PASS' : 'FAIL'));

  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(allOk ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
