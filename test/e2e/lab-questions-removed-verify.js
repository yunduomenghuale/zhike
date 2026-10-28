#!/usr/bin/env node
/**
 * 实验附题残留删除——CDP 实测
 *
 * 验证点：
 *   L.1 教师实验管理页：创建表单无「题目权重」字段，详情抽屉无「题目权重」行
 *   L.2 学生实验页：评分构成无「附加题得分」项
 *   L.3 附题端点 404（API 层 double-check）
 *   L.4 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234、dbg1/A0987654。
 * 运行：node test/e2e/lab-questions-removed-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-labrem-e2e/run-${RUN_ID}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }
let failures = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (!ok) failures += 1;
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push('console.error: ' + (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        this.consoleErrors.push('page exception: ' + (d.exception?.description || d.text));
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval failed: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name), Buffer.from(r.data, 'base64'));
  }
}

async function launchChrome() {
  const proc = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
    `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', '--force-device-scale-factor=1', 'about:blank',
  ], { stdio: 'ignore', detached: true });
  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const page = (await res.json()).filter((t) => t.type === 'page')[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* retry */ }
    await sleep(250);
  }
  if (!wsUrl) throw new Error('Chrome devtools 端口未就绪');
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws 失败'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  return { cdp, chrome: proc };
}

async function waitFor(tab, expression, timeoutMs = 20000, pollMs = 250) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { if (await tab.eval(expression)) return true; } catch { /* retry */ }
    await sleep(pollMs);
  }
  return false;
}

async function login(tab, username, password) {
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.href.startsWith('http')`);
  await tab.eval(`localStorage.clear()`);
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2`);
  await tab.eval(`(() => {
    const inputs = document.querySelectorAll('input');
    inputs[0].value = ${JSON.stringify(username)};
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    const pwd = document.querySelector('input[type="password"]');
    pwd.value = ${JSON.stringify(password)};
    pwd.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(200);
  await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`);
  return waitFor(tab, `!location.pathname.startsWith('/login')`, 15000);
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const { cdp: tab, chrome } = await launchChrome();
  try {
    log('教师登录…');
    check('教师登录', await login(tab, 't101', 'pass1234'), await tab.eval('location.pathname'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/labs` });
    const pageReady = await waitFor(tab, `[...document.querySelectorAll('button')].some((b) => b.textContent.includes('创建实验'))`, 25000);
    check('实验管理页就绪', pageReady);

    // L.1 创建表单无题目权重
    const l1a = await tab.eval(`!document.body.textContent.includes('题目权重')`);
    check('L.1 创建表单无「题目权重」', l1a);
    await tab.shot('labrem-01-form.png');

    // L.1b 详情抽屉无题目权重行（点第一行实验的详情/管理入口）
    await tab.eval(`(() => {
      const btns = [...document.querySelectorAll('button, .el-button')];
      const b = btns.find((x) => x.textContent.includes('详情') || x.textContent.includes('管理') || x.textContent.includes('学生'));
      b?.click();
    })()`);
    await sleep(1200);
    const drawerOpen = await waitFor(tab, `!!document.querySelector('.el-drawer')`, 8000);
    const l1b = drawerOpen ? await tab.eval(`!document.querySelector('.el-drawer').textContent.includes('题目权重')`) : null;
    check('L.1b 详情抽屉无「题目权重」', drawerOpen && l1b, `drawer=${drawerOpen}`);
    await tab.shot('labrem-02-detail.png');
    // 关闭抽屉
    await tab.eval(`(() => { document.querySelector('.el-drawer__close-btn, .el-drawer__header button')?.click(); })()`);
    await sleep(600);

    // L.2 学生实验页评分构成无附加题
    await login(tab, 'dbg1', 'A0987654');
    await tab.send('Page.navigate', { url: `${BASE}/student/courses/5/labs` });
    const labPage = await waitFor(tab, `document.body.textContent.includes('实验')`, 25000);
    await sleep(1000);
    const l2 = await tab.eval(`!document.body.textContent.includes('附加题')`);
    check('L.2 学生实验页无「附加题」', labPage && l2);
    await tab.shot('labrem-03-student.png');

    // L.3 API 层 double-check（教师 token）
    await login(tab, 't101', 'pass1234');
    const l3 = await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
      const r1 = await fetch('/api/labs/1/questions/', { method: 'POST', headers: h, body: '{"question_ids":[1]}' });
      const r2 = await fetch('/api/lab-submissions/1/grade/', { method: 'POST', headers: h, body: '{"scores":{}}' });
      const r3 = await fetch('/api/lab-submissions/1/answers/', { headers: h });
      return { add: r1.status, grade: r2.status, answers: r3.status };
    })()`);
    check('L.3 附题端点全 404', l3 && l3.add === 404 && l3.grade === 404 && l3.answers === 404, JSON.stringify(l3));

    // L.4 console 干净
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('L.4 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
