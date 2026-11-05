#!/usr/bin/env node
/** Stage 0 基线冒烟：8092 测试环境。
 * 场景 A：test_admin 登录 → 教师实验管理页渲染、无控制台错误。
 * 场景 B：B2204011 登录（会话内）→ 打开预置实验门控页 → 验证门控页 200、
 *        lab-bridge.js 已加载、window.LabBridge 可用（不提交）。
 * 用法：node test/e2e/stage0-8092-smoke.js [gateUrl]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = process.env.BASE || 'http://192.168.3.145:8092';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-stage0';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const GATE_URL = process.argv[2] || '';
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
    console.log('shot -> test/screenshots/' + name + '.png');
  }
  consoleErrors() {
    return this.events.filter((e) => e.method === 'Log.entryAdded' && e.params.entry.level === 'error')
      .map((e) => e.params.entry.text)
      // 环境性告警：HTTP 非安全源下 Chrome 把 COOP 头忽略提示记为 error 级，与应用无关
      .filter((t) => !t.includes("Cross-Origin-Opener-Policy header has been ignored"));
  }
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}

async function waitReady(cdp, timeoutMs = 20000) {
  for (let i = 0; i < timeoutMs / 100; i++) {
    const ready = await cdp.eval('document.readyState').catch(() => null);
    if (ready === 'complete') return true;
    await sleep(100);
  }
  return false;
}

async function login(cdp, username, password) {
  // 每次登录前清空本地凭证（上一次会话的角色令牌会导致 /login 被重定向）
  await cdp.eval('try { localStorage.clear() } catch (e) {}');
  await cdp.send('Page.navigate', { url: BASE + '/login' });
  await waitReady(cdp);
  await sleep(2000);
  // EP el-input：写原生 input 值并派发 input 事件触发 v-model
  await cdp.eval(`(() => {
    const setVal = (el, v) => {
      const proto = Object.getPrototypeOf(el);
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const inputs = document.querySelectorAll('.split-auth__form-box--login input');
    setVal(inputs[0], ${JSON.stringify(username)});
    setVal(inputs[1], ${JSON.stringify(password)});
    return inputs.length;
  })()`);
  await sleep(300);
  await cdp.eval(`document.querySelector('.split-auth__form-box--login .auth-submit').click()`);
  for (let i = 0; i < 100; i++) {
    await sleep(200);
    const path = await cdp.eval('location.pathname').catch(() => '');
    if (path && path !== '/login') return path;
  }
  return await cdp.eval('location.pathname');
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
    // ===== 场景 A：test_admin 教师实验管理页 =====
    const adminPath = await login(cdp, 'test_admin', 'Test123456!');
    check('A1 test_admin 登录成功并跳转', adminPath !== '/login', 'path=' + adminPath);

    await cdp.send('Page.navigate', { url: BASE + '/teacher/courses/1/labs' });
    await waitReady(cdp);
    await sleep(3000);
    const labTitle = await cdp.eval(`(document.body.innerText || '').includes('VLAN') || (document.body.innerText || '').includes('实验')`);
    check('A2 教师实验管理页渲染（含实验内容）', labTitle);
    const errsA = cdp.consoleErrors();
    check('A3 教师页无控制台错误', errsA.length === 0, errsA.slice(0, 2).join(' | '));
    await cdp.shot('stage0-8092-admin-labs');

    // ===== 场景 B：学生门控页 =====
    if (GATE_URL) {
      await login(cdp, 'B2204011', 'Test123456!');
      await cdp.send('Page.navigate', { url: BASE + GATE_URL });
      await waitReady(cdp);
      await sleep(4000);
      const status = await cdp.eval('document.readyState');
      const bodyText = await cdp.eval('document.body ? document.body.innerText.slice(0, 200) : ""');
      check('B1 门控页加载完成', status === 'complete', 'readyState=' + status);
      const bridgeLoaded = await cdp.eval(`typeof window.LabBridge !== 'undefined'`);
      check('B2 lab-bridge.js 已注入（window.LabBridge 存在）', bridgeLoaded);
      const bridgeScript = await cdp.eval(`!!document.querySelector('script[src*="lab-bridge"]')`);
      check('B3 页面含 lab-bridge script 标签', bridgeScript);
      const errsB = cdp.consoleErrors();
      check('B4 门控页无控制台错误', errsB.length === 0, errsB.slice(0, 2).join(' | '));
      await cdp.shot('stage0-8092-student-gate');
      console.log('gate body excerpt: ' + JSON.stringify(bodyText));
    } else {
      console.log('SKIP 场景 B：未提供 gateUrl');
    }
  } finally {
    try { await cdp.send('Browser.close'); } catch {}
    chrome.kill();
  }

  const bad = results.filter((r) => !r.ok);
  console.log(`\n===== 汇总 =====\n总计 ${results.length} 项，通过 ${results.length - bad.length} 项，失败 ${bad.length} 项`);
  if (bad.length) { bad.forEach((b) => console.log('失败: ' + b.name)); process.exitCode = 1; } else console.log('ALL_PASS');
})().catch((e) => { console.error('冒烟异常:', e); process.exitCode = 2; });
