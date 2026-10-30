#!/usr/bin/env node
/** 生产发布后冒烟：真实浏览器打开 http://192.168.3.145:8088 ，检查登录页渲染、无控制台报错、无失败请求 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9223;
const BASE = 'http://192.168.3.145:8088';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-prod';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(m.error.message)) : resolve(m.result);
      } else if (m.method) this.events.push(m);
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('timeout ' + method)); } }, 30000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
  }
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}

(async () => {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  const chrome = spawn(CHROME, ['--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank'], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = list.find((t) => t.type === 'page');
      if (p) { wsUrl = p.webSocketDebuggerUrl; break; }
    } catch {}
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome 未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws fail'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Network.enable'); await cdp.send('Log.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  try {
    await cdp.send('Page.navigate', { url: BASE + '/login' });
    for (let i = 0; i < 150; i++) {
      const ready = await cdp.eval('document.readyState').catch(() => null);
      if (ready === 'complete') break;
      await sleep(100);
    }
    await sleep(2500);

    const hasForm = await cdp.eval(`!!document.querySelector('.split-auth__form-box--login .auth-submit')`);
    check('P1 生产登录页渲染完成（登录按钮可见）', hasForm);
    const title = await cdp.eval('document.title');
    // 应用挂载后会把 index.html 静态标题改写成「智课平台」，两者都算正常
    check('P2 页面标题正确', /智课平台|智能课程教学平台/.test(title), title);

    const errs = cdp.events.filter((e) => e.method === 'Log.entryAdded' && e.params.entry.level === 'error')
      .map((e) => e.params.entry.text);
    check('P3 无控制台错误', errs.length === 0, errs.slice(0, 2).join(' | '));

    const failed = cdp.events.filter((e) => e.method === 'Network.loadingFailed')
      .map((e) => e.params.errorText + ' ' + (e.params.type || ''));
    check('P4 无失败资源请求', failed.length === 0, failed.slice(0, 2).join(' | '));

    const apiOk = cdp.events.filter((e) => e.method === 'Network.responseReceived'
      && String(e.params.response.url).includes('/api/auth/config/'))
      .map((e) => e.params.response.status)[0];
    check('P5 后端接口可达（/api/auth/config/ 200）', apiOk === 200, 'status=' + apiOk);

    await cdp.shot('prod-smoke-login');
  } finally {
    try { await cdp.send('Browser.close'); } catch {}
    chrome.kill();
  }

  const bad = results.filter((r) => !r.ok);
  console.log(`\n===== 汇总 =====\n总计 ${results.length} 项，通过 ${results.length - bad.length} 项，失败 ${bad.length} 项`);
  if (bad.length) { bad.forEach((b) => console.log('失败: ' + b.name)); process.exitCode = 1; } else console.log('ALL_PASS');
})().catch((e) => { console.error('冒烟异常:', e); process.exitCode = 2; });
