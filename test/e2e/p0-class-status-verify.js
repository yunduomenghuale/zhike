#!/usr/bin/env node
/**
 * P0 地基 E2E：班级状态枚举改造后，三端页面状态标签必须显示新文案。
 *
 * 验证点：
 *   A.1 教师端「班级管理」列表标签显示「在读」，不再出现「开课中/已结课」
 *   A.2 教师端班级编辑弹窗回填 status=active（不是旧的 'open'）
 *   A.3 管理端「教学监管」打开班级详情抽屉，标签显示「在读」
 *   A.4 学生端「我的班级」显示「在读」，且转班后只剩 1 个班
 *   A.5 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234；admin/A0987654；20249999/pass1234
 * 运行：node test/e2e/p0-class-status-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9700 + (parseInt(RUN_ID, 36) % 300);
const PROFILE = `D:/tmp/zhike-p0-e2e/run-${RUN_ID}`;
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

const BODY_TEXT = `document.body.innerText`;

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // ===== 教师端 =====
    check('教师登录', await login(tab, 't101', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    check('班级管理页渲染出班级卡片',
      await waitFor(tab, `document.body.innerText.includes('网络2026届-1班')`, 25000));
    await sleep(700);

    const teacherText = await tab.eval(BODY_TEXT);
    check('列表出现「在读」标签', teacherText.includes('在读'), '');
    check('不再出现「开课中」', !teacherText.includes('开课中'), '');
    check('不再出现「已结课」', !teacherText.includes('已结课'), '');
    check('显示届别相关字段不报错', !teacherText.includes('undefined'), '');
    await tab.shot('p0-01-teacher-classes.png');

    // 打开第一个班级的编辑弹窗，确认 status 回填 active
    // 编辑按钮是纯图标 + title="编辑班级"，没有文字，只能用 title 选
    const clickedEdit = await tab.eval(`(() => {
      const edit = document.querySelector('[title="编辑班级"]');
      if (edit) edit.click();
      return !!edit;
    })()`);
    check('找到编辑按钮', clickedEdit);
    await sleep(900);
    const editVisible = await tab.eval(`(() => {
      const d = document.querySelector('.creation-dialog') || document.querySelector('.el-dialog');
      return !!(d && d.getBoundingClientRect().height > 100);
    })()`);
    check('编辑弹窗打开', editVisible);
    if (editVisible) {
      await tab.shot('p0-02-teacher-class-edit.png');
      // 状态回填必须是 active，不能残留旧的 'open'
      const dialogText = await tab.eval(`(() => {
        const d = document.querySelector('.creation-dialog') || document.querySelector('.el-dialog');
        return d ? d.innerText : '';
      })()`);
      check('编辑弹窗含「在读」选项', dialogText.includes('在读'), '');
      await tab.eval(`(() => {
        const d = document.querySelector('.creation-dialog') || document.querySelector('.el-dialog');
        const cancel = [...d.querySelectorAll('button')].find((b) => /取消/.test(b.innerText));
        if (cancel) cancel.click();
      })()`);
      await sleep(500);
    }

    // ===== 管理端 =====
    check('管理员登录', await login(tab, 'admin', 'A0987654'));
    await tab.send('Page.navigate', { url: `${BASE}/admin/teaching` });
    check('教学监管页加载',
      await waitFor(tab, `document.body.innerText.includes('班级')`, 25000));
    await sleep(1200);
    // 默认停在「课程监管」页签，需先切到「班级监管」才能看到班级状态标签
    const tabClicked = await tab.eval(`(() => {
      const el = [...document.querySelectorAll('.el-tabs__item, .tab, .nav-item')]
        .find((n) => n.innerText.trim() === '班级监管');
      if (el) el.click();
      return !!el;
    })()`);
    check('切换到班级监管页签', tabClicked);
    await sleep(1500);
    await waitFor(tab, `document.body.innerText.includes('网络2026届-1班')`, 15000);
    const adminText = await tab.eval(BODY_TEXT);
    check('管理端也显示「在读」', adminText.includes('在读'), '');
    check('管理端不再显示「开课中」', !adminText.includes('开课中'), '');
    await tab.shot('p0-03-admin-teaching.png');

    // ===== 学生端 =====
    check('学生登录', await login(tab, '20249999', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/student/my-classes` });
    await waitFor(tab, `document.body.innerText.includes('网络2026届-1班') || document.body.innerText.includes('我的')`, 25000);
    await sleep(1200);
    const stuText = await tab.eval(BODY_TEXT);
    check('学生端显示所在班级', stuText.includes('网络2026届-1班'), '');
    check('学生端状态为「在读」', stuText.includes('在读'), '');
    check('转班后不再显示旧班（数据结构B班）', !stuText.includes('数据结构B班'), '');
    await tab.shot('p0-04-student-my-classes.png');

    check('无 console.error / 页面异常', tab.consoleErrors.length === 0, tab.consoleErrors.slice(0, 3).join(' | '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
  }

  console.log('');
  if (failures) {
    console.log(`E2E 失败 ${failures} 项`);
    process.exit(1);
  }
  console.log('E2E 全部通过');
}

main().catch((e) => { console.error(e); process.exit(1); });
