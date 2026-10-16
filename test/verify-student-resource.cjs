/* 学生端验证：课程资源卡片 → sign → 新标签页查看器 iframe 加载签名预置页。
 * 用法: node verify-student-resource.cjs <access_token> <app_url> <out_png>
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outPng = process.argv[4] || path.join(os.tmpdir(), 'stu-res.png');
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-stures-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-student-resource.cjs <token> <app_url> <out_png>');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getJson = (url) => new Promise((resolve, reject) => {
  const req = require('http').get(url, (res) => {
    let body = '';
    res.on('data', (c) => (body += c));
    res.on('end', () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
  });
  req.on('error', reject);
});

async function attach(wsUrl) {
  const ws = new WebSocket(wsUrl);
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
      consoleErrors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;
  return { ws, send, evalJs, consoleErrors };
}

async function main() {
  const edge = execFile(EDGE, [
    '--headless=new', '--remote-debugging-port=9224', `--user-data-dir=${userDataDir}`,
    '--no-proxy-server', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--window-size=1600,1000', 'about:blank',
  ], () => {});
  edge.unref();

  for (let i = 0; i < 40; i++) {
    try { await getJson('http://127.0.0.1:9224/json/version'); break; } catch { await sleep(500); }
  }

  const list0 = await getJson('http://127.0.0.1:9224/json/list');
  const page0 = list0.find((t) => t.type === 'page');
  const main = await attach(page0.webSocketDebuggerUrl);
  await main.send('Page.enable');
  await main.send('Runtime.enable');
  await main.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem('access_token', ${JSON.stringify(token)});`,
  });

  await main.send('Page.navigate', { url: `${APP_URL}/student/courses/5/resources` });
  let cards = 0;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    cards = await main.evalJs(`document.querySelectorAll('.res-card').length`);
    if (cards > 0) break;
  }

  // 真实鼠标点击（合成 click 不授予用户手势，window.open 会被拦截）
  const box = await main.evalJs(`(() => {
    const c = document.querySelector('.res-card');
    if (!c) return null;
    c.scrollIntoView({ block: 'center' });
    const r = c.getBoundingClientRect();
    return JSON.stringify({ x: r.x + r.width / 2, y: r.y + r.height / 2 });
  })()`);
  if (!box) { console.error('no resource card'); process.exit(3); }
  const { x, y } = JSON.parse(box);
  await main.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await main.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });

  // 等待新标签页（查看器，localhost 页面）出现并附着（排除 Edge 同步对话框等内部页）
  let viewer = null;
  let viewerUrl = '';
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const list = await getJson('http://127.0.0.1:9224/json/list');
    const pages = list.filter(
      (t) => t.type === 'page' && t.id !== page0.id && /^http:\/\/(localhost|127\.0\.0\.1)/.test(t.url || ''),
    );
    if (pages.length) { viewerUrl = pages[0].url; viewer = await attach(pages[0].webSocketDebuggerUrl); break; }
  }
  if (!viewer) { console.error('viewer tab not opened'); process.exit(3); }
  await viewer.send('Page.enable');
  await viewer.send('Runtime.enable');

  let frame = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    frame = await viewer.evalJs(`(() => {
      const ifr = document.querySelector('iframe.viewer-frame');
      const empty = document.querySelector('.el-empty__description')?.textContent || '';
      return JSON.stringify({
        hasFrame: !!ifr,
        href: location.href.slice(0, 200),
        empty,
        bodyText: (document.body?.textContent || '').slice(0, 120),
      });
    })()`);
    const s = JSON.parse(frame || '{}');
    if (s.hasFrame) {
      frame = await viewer.evalJs(`(() => {
        const ifr = document.querySelector('iframe.viewer-frame');
        let doc = null;
        try { doc = ifr.contentDocument; } catch (e) { return JSON.stringify({ hasFrame: true, crossOrigin: true }); }
        return JSON.stringify({
          hasFrame: true,
          src: (ifr.getAttribute('src') || '').slice(0, 100),
          title: doc?.title || '',
          hasBase: !!doc?.querySelector('base[href*="course-resources/asset"]'),
          hasSvg: !!doc?.querySelector('#mindmap svg, svg'),
          viewerTitle: document.querySelector('.vh-title')?.textContent || '',
        });
      })()`);
      break;
    }
  }

  const metrics = await viewer.send('Page.getLayoutMetrics');
  const size = metrics.cssContentSize || metrics.contentSize;
  const s = await viewer.send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: Math.min(size.width, 1600), height: Math.min(size.height, 2000), scale: 1 },
  });
  fs.writeFileSync(outPng, Buffer.from(s.data, 'base64'));

  const report = { cards, viewerUrl, frame: JSON.parse(frame || '{}'), consoleErrors: viewer.consoleErrors };
  console.log(JSON.stringify(report, null, 2));
  const ok = report.frame?.hasBase && report.frame?.hasSvg;
  console.log('VERDICT_STUDENT_RESOURCE=' + (ok ? 'PASS' : 'FAIL'));
  console.log('PNG=' + outPng);

  viewer.ws.close();
  main.ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  process.exit(ok ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
