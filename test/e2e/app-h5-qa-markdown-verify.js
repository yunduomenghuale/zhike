#!/usr/bin/env node
/**
 * 移动端 H5 AI 回答 markdown 渲染冒烟（app/src/pages/qa/index.vue 改 rich-text 后）：
 *   AH.1 H5 应用加载、学生 token 注入后进入问答页，课程下拉加载出课程
 *   AH.2 提问后回答以 rich-text 渲染：含 <strong>（加粗生效）且无 ** 残留
 *   AH.3 参考来源照常展示
 *   AH.4 无 console.error / 未捕获异常
 *
 * 前置：后端 8005 已启动；app 已 build:h5；本脚本自带 5299 静态+代理服务。
 * 运行：node test/e2e/app-h5-qa-markdown-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5299';
const BACKEND = 'http://127.0.0.1:8005';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const QUESTION = '这门课的重点是什么？';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-ah-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push('console.error: ' + (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        this.consoleErrors.push('page exception: ' + (d.exception?.description || d.text));
      }
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }
      }, 30000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
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
    await sleep(600);
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    return name + '.png';
  }
}

async function waitFor(cdp, expr, timeout = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let ok = false;
    try { ok = await cdp.eval(expr); } catch { ok = false; }
    if (ok) return true;
    await sleep(200);
  }
  return false;
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 忽略 */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu', '--enable-unsafe-swiftshader',
    '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=420,860', 'about:blank',
  ], { stdio: 'ignore', detached: true });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.filter((t) => t.type === 'page')[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
    await sleep(250);
  }
  if (!wsUrl) { killChrome(chrome); throw new Error('Chrome devtools 端口未就绪'); }

  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 420, height: 860, deviceScaleFactor: 2, mobile: true });
  return { cdp, chrome };
}

function killChrome(chrome) {
  try { execSync(`taskkill /PID ${chrome.pid} /T /F`, { stdio: 'ignore' }); } catch { /* 进程可能已退出 */ }
  try { chrome.kill(); } catch { /* ignore */ }
}

async function run() {
  // AH.0 登录拿 token
  const loginResp = await fetch(`${BACKEND}/api/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: '20249999', password: PW }),
  });
  const loginJson = await loginResp.json();
  const token = loginJson?.data?.token?.access;
  const refresh = loginJson?.data?.token?.refresh;
  const user = loginJson?.data?.user;
  if (!token) throw new Error('登录失败: ' + JSON.stringify(loginJson).slice(0, 200));
  log('登录成功，注入 storage');

  const { cdp, chrome } = await launchChrome();
  try {
    // AH.1 先落到任意页面注入 token，再进问答页（同 hash 重复导航不会重触发 onLoad）
    await cdp.navigate(BASE + '/');
    await cdp.eval(`(function(){
      localStorage.setItem('access_token', ${JSON.stringify(token)});
      localStorage.setItem('refresh_token', ${JSON.stringify(refresh || '')});
      localStorage.setItem('user', ${JSON.stringify(JSON.stringify(user || {}))});
    })()`);
    await cdp.navigate(BASE + '/#/pages/qa/index');
    const pickerOk = await waitFor(cdp,
      `document.body.innerText.includes('AI 助教') || document.body.innerText.includes('请选择课程')`, 20000);
    check('AH.1 问答页加载（含课程选择器）', pickerOk);

    // 等课程列表加载完（picker-value 出现课程名）
    const courseOk = await waitFor(cdp,
      `(function(){
        var el = document.querySelector('.picker-value');
        return el && el.textContent && el.textContent !== '请选择课程';
      })()`, 20000);
    check('AH.2 课程列表加载出当前课程', courseOk, courseOk ? await cdp.eval(`document.querySelector('.picker-value').textContent`) : '');

    // AH.3 点建议问题触发提问
    const asked = await cdp.eval(`(function(){
      var s = document.querySelector('.suggest');
      if (!s) return false;
      s.click();
      return true;
    })()`);
    check('AH.3 点击建议问题发起提问', asked);

    // AH.4 等待回答：rich-text 渲染出 <strong>
    const answered = await waitFor(cdp,
      `(function(){
        var rows = document.querySelectorAll('.msg.assistant');
        if (!rows.length) return false;
        var last = rows[rows.length - 1];
        return !!last.querySelector('strong');
      })()`, 180000);
    check('AH.4 回答渲染出 <strong> 加粗', answered);

    if (answered) {
      const stat = await cdp.eval(`(function(){
        var rows = document.querySelectorAll('.msg.assistant');
        var last = rows[rows.length - 1];
        var rt = last.querySelector('rich-text') || last;
        return {
          residualStar: (last.textContent.match(/\\*\\*/g) || []).length,
          strongCount: last.querySelectorAll('strong').length,
          textLen: last.textContent.length,
          hasSources: !!last.querySelector('.sources'),
        };
      })()`);
      check('AH.5 回答无 ** 残留', stat.residualStar === 0, `残留 ${stat.residualStar} 处`);
      check('AH.6 rich-text 内 <strong> 数量 >= 1', stat.strongCount >= 1, `${stat.strongCount} 处`);
      check('AH.7 参考来源展示', stat.hasSources === true);
    }

    await cdp.shot('app-h5-qa-markdown-ok');
    check('AH.8 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' ; ') || '');
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项: ' + failed.map((f) => f.name).join(' | '));
    process.exitCode = 1;
  }
}

run().catch((err) => {
  console.error('E2E 运行异常:', err.message);
  process.exitCode = 1;
});
