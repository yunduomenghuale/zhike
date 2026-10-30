#!/usr/bin/env node
/**
 * 退出登录回归 —— CDP 真实浏览器 E2E
 *
 * 背景：userStore.logout() 先发 POST /auth/logout/ 再同步清 localStorage，而 axios
 * 请求拦截器在微任务里才执行，读 token 时 localStorage 已空 → 请求不带
 * Authorization → 后端 IsAuthenticated 判 401「身份认证信息未提供」，并且
 * P5-A2 的 refresh 吊销其实一次都没生效。
 *
 * 验证项：
 *   L1 点击「退出登录」后 /api/auth/logout/ 响应 200（而非 401）
 *   L2 该请求确实携带 Authorization: Bearer xxx
 *   L3 浏览器控制台无 401 资源错误、无「身份认证信息未提供」
 *   L4 页面无 el-message 错误提示，且已跳转 /login、localStorage 清空
 *   L5 后端吊销真正生效：登出前拿到的 refresh 不能再换 access（401）
 *   L6 登出后 1.5s 重新登录仍正常（作废线不误伤新 token）
 *
 * 运行：node test/e2e/logout-verify.js   （需 backend:8005 + serve-local:5273）
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9222;
const BASE = 'http://localhost:5273';
const API = 'http://127.0.0.1:8005';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-logout';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error('CDP timeout: ' + method));
        }
      }, 30000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error('eval exception: ' + (d.exception?.description || d.text));
    }
    return r.result.value;
  }
  async navigate(url) {
    await this.send('Page.navigate', { url });
    for (let i = 0; i < 150; i++) {
      const ready = await this.eval('document.readyState').catch(() => null);
      if (ready === 'complete') break;
      await sleep(100);
    }
    await sleep(400);
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
  }
}

async function waitFor(cdp, expr, timeout = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let ok = false;
    try { ok = await cdp.eval(expr); } catch { ok = false; }
    if (ok) return true;
    await sleep(150);
  }
  return false;
}

async function login(cdp, username, password) {
  await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
  await cdp.navigate(BASE + '/login');
  await waitFor(cdp, `!!document.querySelector('.split-auth__form-box--login .auth-submit')`, 15000);
  await cdp.eval(`(function(){
    function setVal(sel, v){
      var el = document.querySelector(sel);
      if(!el) return;
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    setVal('.split-auth__form-box--login input[placeholder="请输入用户名"]', ${JSON.stringify(username)});
    setVal('.split-auth__form-box--login input[placeholder="请输入密码"]', ${JSON.stringify(password)});
    var btn = document.querySelector('.split-auth__form-box--login .auth-submit');
    if (btn) btn.click();
  })()`);
  const ok = await waitFor(cdp, `location.pathname === '/dashboard' || location.pathname === '/'`, 30000);
  if (!ok) throw new Error('登录失败或未跳转工作台: ' + username);
  await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 1`, 30000);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用旧目录 */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
    '--no-first-run', '--remote-debugging-port=' + PORT,
    '--remote-allow-origins=*', '--user-data-dir=' + PROFILE,
    '--window-size=1440,900', 'about:blank',
  ], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 未就绪 */ }
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome devtools 端口未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');
  await cdp.send('Log.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { cdp, chrome };
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    await login(cdp, 't101', 'pass1234');
    check('L0 教师账号 t101 登录成功并进入工作台', true);

    // 记录登出前的凭证，用于验证后端吊销是否真的生效
    const before = await cdp.eval(`JSON.stringify({
      access: localStorage.getItem('access_token') || '',
      refresh: localStorage.getItem('refresh_token') || ''
    })`);
    const { refresh } = JSON.parse(before);

    // 清空事件缓冲，只看登出窗口内的网络与控制台
    const mark = cdp.events.length;

    // 打开用户菜单 → 退出登录
    await cdp.eval(`(function(){
      var el = document.querySelector('.user');
      if (el) el.click();
    })()`);
    const menuReady = await waitFor(cdp, `(function(){
      var it = document.querySelector('.logout-item');
      if (!it) return false;
      var r = it.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    })()`, 8000);
    check('L1 用户菜单展开且「退出登录」可见', menuReady);
    await cdp.eval(`(function(){
      var it = document.querySelector('.logout-item');
      if (it) it.click();
    })()`);

    // 等登出请求落地 + 路由跳转
    const jumped = await waitFor(cdp, `location.pathname === '/login'`, 15000);
    await sleep(1500);

    // ---- 从网络事件里取登出请求 ----
    const evts = cdp.events.slice(mark);
    const sent = evts.filter((e) => e.method === 'Network.requestWillBeSent'
      && String(e.params.request.url).includes('/api/auth/logout/'));
    const finished = evts.filter((e) => e.method === 'Network.responseReceived'
      && String(e.params.response.url).includes('/api/auth/logout/'));

    const reqHeaders = sent[0]?.params?.request?.headers || {};
    const authHeader = Object.keys(reqHeaders)
      .filter((k) => k.toLowerCase() === 'authorization')
      .map((k) => reqHeaders[k])[0] || '';
    const logoutStatus = finished[0]?.params?.response?.status ?? 0;

    check('L2 登出请求已发出', sent.length === 1, 'count=' + sent.length);
    check('L3 登出请求携带 Authorization: Bearer', /^Bearer\s+\S+/.test(authHeader), authHeader ? 'Bearer ***' : '(空)');
    check('L4 登出接口返回 200', logoutStatus === 200, 'status=' + logoutStatus);

    // ---- 控制台错误 ----
    const consoleErr = evts.filter((e) => {
      if (e.method === 'Log.entryAdded') return e.params.entry.level === 'error';
      if (e.method === 'Runtime.consoleAPICalled') return e.params.type === 'error';
      return false;
    }).map((e) => (e.params.entry?.text || (e.params.args || []).map((a) => a.value || a.description || '').join(' ')));
    const hasCredErr = consoleErr.some((t) => t.includes('身份认证信息未提供') || /401/.test(t));
    check('L5 控制台无 401/身份认证信息报错', !hasCredErr, hasCredErr ? consoleErr.join(' | ').slice(0, 300) : '');

    // ---- 页面提示与本地状态 ----
    const errToast = await cdp.eval(`!!document.querySelector('.el-message--error')`);
    check('L6 页面无红色错误提示框', !errToast);
    const cleared = await cdp.eval(`!localStorage.getItem('access_token') && !localStorage.getItem('refresh_token')`);
    check('L7 已跳转登录页且本地 token 清空', jumped && cleared, 'path=' + await cdp.eval('location.pathname'));
    await cdp.shot('logout-after-fix');

    // ---- 后端吊销是否真正生效（P5-A2）----
    if (refresh) {
      const resp = await fetch(API + '/api/auth/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      });
      check('L8 登出后旧 refresh 已进黑名单（换 token 被拒 401）', resp.status === 401, 'status=' + resp.status);
    } else {
      check('L8 登出后旧 refresh 已进黑名单', false, '未取到 refresh');
    }

    // ---- 等过作废线的同秒窗口后重新登录 ----
    await sleep(1500);
    await login(cdp, 't101', 'pass1234');
    const meOk = await cdp.eval(`(async function(){
      var r = await fetch('/api/auth/me/', { headers: { Authorization: 'Bearer ' + localStorage.getItem('access_token') } });
      return r.status;
    })()`);
    check('L9 登出后重新登录仍可正常访问接口', meOk === 200, 'GET /auth/me status=' + meOk);
  } finally {
    try { await cdp.send('Browser.close'); } catch { /* ignore */ }
    chrome.kill();
  }

  const failed = results.filter((r) => !r.ok);
  console.log('\n===== 汇总 =====');
  console.log('总计 ' + results.length + ' 项，通过 ' + (results.length - failed.length) + ' 项，失败 ' + failed.length + ' 项');
  if (failed.length) {
    failed.forEach((f) => console.log('失败: ' + f.name));
    process.exitCode = 1;
  } else {
    console.log('ALL_PASS');
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 2;
});
