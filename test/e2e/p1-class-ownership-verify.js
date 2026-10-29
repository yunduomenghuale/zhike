#!/usr/bin/env node
/**
 * P1 E2E：班级归口管理员后，三端入口必须按角色收敛。
 *
 * 验证点（对应任务规范 §4 P1 第 4 条「教师端班级管理只剩只读名单」）：
 *   A 教师端 /teacher/classes：无「新建班级」、无邀请码、无编辑/删除、有只读提示
 *   B 教师端名单页 /teacher/classes/:id/students：无「添加学生」、无「移除」、无邀请码
 *   C 管理端侧边栏出现「班级管理」，/admin/classes 可建班（弹窗含编码/届别/学制）
 *   D 学生端 /student/my-classes：无「加入班级」卡片、无邀请码
 *   E 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005（node serve-local.js 起的 5273 亦可）、t101/pass1234、admin/A0987654、20249999/pass1234
 * 运行：node test/e2e/p1-class-ownership-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9700 + (parseInt(RUN_ID, 36) % 300);
const PROFILE = `D:/tmp/zhike-p1-e2e/run-${RUN_ID}`;
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

const BODY = `document.body.innerText`;
const hasText = async (tab, text) => (await tab.eval(BODY)).includes(text);

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // ===================== A. 教师端班级列表：只读 =====================
    check('教师登录', await login(tab, 't101', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    check('班级列表渲染', await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 25000));
    await sleep(600);

    const teacherText = await tab.eval(BODY);
    check('无「新建班级」按钮', !teacherText.includes('新建班级'), '');
    check('无「邀请码」字样', !teacherText.includes('邀请码'), '');
    check('无「换邀请码」', !teacherText.includes('换邀请码'), '');
    check('有只读提示', teacherText.includes('班级由学校统一分配'), '');
    const noAdminIcons = await tab.eval(`!document.querySelector('[title="编辑班级"]') && !document.querySelector('[title="删除班级"]')`);
    check('无编辑/删除图标', noAdminIcons);
    const hasRosterBtn = await tab.eval(`[...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '学生')`);
    check('保留「学生」名单入口', hasRosterBtn);
    await tab.shot('p1-01-teacher-classes-readonly.png');

    // ===================== B. 教师端名单页：只读 =====================
    await tab.eval(`[...document.querySelectorAll('button')].find((b) => b.innerText.trim() === '学生').click()`);
    check('进入名单页', await waitFor(tab, `location.pathname.includes('/teacher/classes/') && location.pathname.includes('/students')`, 15000));
    await waitFor(tab, `document.querySelector('.roster-count') !== null`, 15000);
    await sleep(900);
    const rosterText = await tab.eval(BODY);
    check('名单页无「添加学生」', !rosterText.includes('添加学生'), '');
    check('名单页无「邀请码」', !rosterText.includes('邀请码'), '');
    const hasRemove = await tab.eval(`[...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '移除')`);
    check('名单页无「移除」操作', !hasRemove);
    await tab.shot('p1-02-teacher-roster-readonly.png');

    // ===================== C. 管理端班级管理：可写 =====================
    check('管理员登录', await login(tab, 'admin', 'A0987654'));
    await tab.send('Page.navigate', { url: `${BASE}/dashboard` });
    await waitFor(tab, `document.querySelector('.el-menu, aside') !== null`, 20000);
    await sleep(800);
    const menuText = await tab.eval(BODY);
    check('管理端菜单含「班级管理」', menuText.includes('班级管理'), '');

    await tab.send('Page.navigate', { url: `${BASE}/admin/classes` });
    check('管理端班级页渲染', await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 25000));
    await sleep(600);
    const adminText = await tab.eval(BODY);
    check('管理端有「新建班级」', adminText.includes('新建班级'), '');
    check('管理端无只读提示', !adminText.includes('班级由学校统一分配'), '');
    const hasAdminIcons = await tab.eval(`!!document.querySelector('[title="编辑班级"]') && !!document.querySelector('[title="删除班级"]')`);
    check('管理端有编辑/删除图标', hasAdminIcons);
    await tab.shot('p1-03-admin-classes.png');

    // 打开新建弹窗，确认编码/届别/学制字段都在
    await tab.eval(`[...document.querySelectorAll('button')].find((b) => b.innerText.includes('新建班级')).click()`);
    const dialogUp = await waitFor(tab, `(() => {
      const d = document.querySelector('.class-form-dialog') || document.querySelector('.el-dialog');
      return !!(d && d.getBoundingClientRect().height > 100);
    })()`, 8000);
    check('新建弹窗打开', dialogUp);
    if (dialogUp) {
      const dialogText = await tab.eval(`(() => {
        const d = document.querySelector('.class-form-dialog') || document.querySelector('.el-dialog');
        return d ? d.innerText : '';
      })()`);
      check('弹窗含「班级编码」', dialogText.includes('班级编码'), '');
      check('弹窗含「届别」', dialogText.includes('届别'), '');
      check('弹窗含「学制」', dialogText.includes('学制'), '');
      await tab.shot('p1-04-admin-class-dialog.png');
      await tab.eval(`(() => {
        const d = document.querySelector('.class-form-dialog') || document.querySelector('.el-dialog');
        const cancel = [...d.querySelectorAll('button')].find((b) => b.innerText.trim() === '取消');
        if (cancel) cancel.click();
      })()`);
      await sleep(500);
    }

    // ===================== D. 学生端：无邀请码入口 =====================
    check('学生登录', await login(tab, '20249999', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/student/my-classes` });
    check('学生我的课程渲染', await waitFor(tab, `document.body.innerText.length > 50`, 25000));
    await sleep(900);
    const stuText = await tab.eval(BODY);
    check('学生端无「加入班级」', !stuText.includes('加入班级'), '');
    check('学生端无「邀请码」', !stuText.includes('邀请码'), '');
    check('学生端无邀请码输入框', await tab.eval(`!document.querySelector('.join-add-card') && !document.querySelector('input[placeholder*="邀请码"]')`));
    check('学生端仍能看到课程卡', await tab.eval(`document.querySelectorAll('.class-card').length > 0`));
    await tab.shot('p1-05-student-my-classes.png');

    // ===================== E. 控制台 =====================
    const errs = tab.consoleErrors.filter((e) => !/favicon|ResizeObserver/.test(e));
    check('全程无 console.error / 页面异常', errs.length === 0, errs.slice(0, 3).join(' ; '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
  }

  log(`失败 ${failures} 项`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => { console.error('E2E 崩溃：', err); process.exit(2); });
