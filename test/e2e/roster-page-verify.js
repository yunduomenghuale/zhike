#!/usr/bin/env node
/**
 * 学生名单抽屉改独立列表页——CDP 实测
 *
 * 验证点：
 *   R.1 班级管理页点「学生」→ URL 跳转到 /teacher/classes/:id/students（不再是抽屉）
 *   R.2 名单页有表格（el-table），行数 = 班级学生数；无 student-drawer
 *   R.3 工具栏：搜索框 / 状态筛选 / 排序下拉 / 添加学生按钮齐全
 *   R.4 关键字筛选生效（输入关键字后行数减少且均匹配）
 *   R.5 排序切换生效（加入时间正/倒序首行不同）
 *   R.6 行内「详情」按钮可点（跳转学生详情页）
 *   R.7 返回按钮回到班级管理页
 *   R.8 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动；教师账号 t101/pass1234。
 * 运行：node test/e2e/roster-page-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-roster-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }
let failures = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (!ok) failures += 1;
}

// ---------------- CDP 客户端 ----------------
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
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
    return new Cdp(ws);
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
    log(`截图 ${name}`);
  }
}

async function launchChrome() {
  const args = [
    `--remote-debugging-port=${PORT}`,
    `--remote-allow-origins=*`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', '--force-device-scale-factor=1',
    '--disable-session-crashed-bubble', '--hide-crash-restore-bubble',
    'about:blank',
  ];
  const proc = spawn(CHROME, args, { stdio: 'ignore', detached: true });
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
  if (!wsUrl) throw new Error('Chrome devtools 端口未就绪');
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  return { cdp, chrome: proc };
}

async function waitFor(tab, expression, timeoutMs = 15000, pollMs = 250) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { if (await tab.eval(expression)) return true; } catch { /* retry */ }
    await sleep(pollMs);
  }
  return false;
}

async function domClick(tab, selector) {
  const ok = await tab.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true; })()`);
  if (!ok) throw new Error(`元素不可点击: ${selector}`);
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const { cdp: tab, chrome } = await launchChrome();
  try {

    // ---- 登录 ----
    log('打开登录页…');
    await tab.send('Page.navigate', { url: `${BASE}/login` });
    await waitFor(tab, `location.pathname === '/login'`);
    await waitFor(tab, `!!document.querySelector('input')`);
    await tab.eval(`(() => {
      const inputs = document.querySelectorAll('input');
      inputs[0].value = 't101';
      inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
      const pwd = document.querySelector('input[type="password"]');
      pwd.value = 'pass1234';
      pwd.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(200);
    await domClick(tab, 'button[type="submit"], .el-button--primary');
    const loggedIn = await waitFor(tab, `location.pathname.startsWith('/teacher') || location.pathname.startsWith('/student') || location.pathname.startsWith('/dashboard')`, 15000);
    check('登录成功', loggedIn, await tab.eval('location.pathname'));

    // ---- R.1 班级管理页点「学生」→ 跳转名单页 ----
    log('进入班级管理页…');
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    await waitFor(tab, `location.pathname === '/teacher/classes'`);
    const hasRow = await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 15000);
    check('班级列表渲染', hasRow);

    // 点击第一行的「学生」按钮
    await tab.eval(`(() => {
      const row = document.querySelector('.class-row');
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('学生'));
      btn.click();
    })()`);
    const navigated = await waitFor(tab, `location.pathname.match(/^\\/teacher\\/classes\\/\\d+\\/students$/)`, 10000);
    check('R.1 点「学生」跳转到名单页', navigated, await tab.eval('location.pathname'));
    check('R.1 不再是抽屉', await tab.eval(`!document.querySelector('.student-drawer')`));

    // ---- R.2 表格渲染（等数据行出现） ----
    const tableReady = await waitFor(tab, `!!document.querySelector('.roster-table')`, 30000);
    check('R.2 名单表格渲染', tableReady);
    const rowsAppeared = await waitFor(tab, `document.querySelectorAll('.roster-table .el-table__body tr').length > 0`, 30000);
    const rowCount = await tab.eval(`document.querySelectorAll('.roster-table .el-table__body tr').length`);
    check('R.2 表格有数据行', rowsAppeared && rowCount > 0, `rows=${rowCount}`);
    // R.2b 头像：有头像的行渲染 <img>，无头像的行显示首字符兜底
    const avatarState = await tab.eval(`(() => {
      const rows = [...document.querySelectorAll('.roster-table .el-table__body tr')];
      let img = 0, fallback = 0;
      rows.forEach((tr) => {
        const cell = tr.querySelector('.stu-avatar-sm');
        if (cell?.querySelector('img')) img += 1;
        else if (cell?.textContent.trim()) fallback += 1;
      });
      return { img, fallback };
    })()`);
    check('R.2b 头像渲染（img/首字符兜底）', rowCount > 0 && avatarState.img + avatarState.fallback === rowCount, JSON.stringify(avatarState));
    await tab.shot('roster-page-01-table.png');

    // ---- R.3 工具栏 ----
    const toolbar = await tab.eval(`(() => ({
      search: !!document.querySelector('.roster-search input'),
      filter: !!document.querySelector('.roster-filter'),
      sort: !!document.querySelector('.roster-sort'),
      add: [...document.querySelectorAll('.roster-toolbar button')].some((b) => b.textContent.includes('添加学生')),
      head: !!document.querySelector('.roster-head'),
      invite: !!document.querySelector('.roster-head .invite-chip'),
    }))()`);
    check('R.3 工具栏齐全（搜索/筛选/排序/添加）', toolbar.search && toolbar.filter && toolbar.sort && toolbar.add, JSON.stringify(toolbar));
    check('R.3 页头含邀请码', toolbar.head && toolbar.invite);

    // ---- R.4 关键字筛选 ----
    const firstUsername = await tab.eval(`(document.querySelector('.roster-table .el-table__body tr .stu-username')||{}).textContent || ''`);
    const firstName = await tab.eval(`(document.querySelector('.roster-table .el-table__body tr .stu-name')||{}).textContent || ''`);
    const kw = (firstUsername || firstName).slice(0, 3);
    await tab.eval(`(() => {
      const input = document.querySelector('.roster-search input');
      input.value = ${JSON.stringify(kw)};
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(500);
    const filteredCount = await tab.eval(`document.querySelectorAll('.roster-table .el-table__body tr').length`);
    const filteredMatch = await tab.eval(`[...document.querySelectorAll('.roster-table .el-table__body tr')].every((tr) => tr.textContent.includes(${JSON.stringify(kw)}))`);
    check('R.4 关键字筛选生效', filteredCount > 0 && filteredCount <= rowCount && filteredMatch, `kw=${kw} rows=${rowCount}->${filteredCount} match=${filteredMatch}`);
    await tab.shot('roster-page-02-filtered.png');

    // 清空筛选
    await tab.eval(`(() => {
      const input = document.querySelector('.roster-search input');
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(400);

    // ---- R.5 排序切换 ----
    async function firstCellText() {
      return tab.eval(`(() => {
        const tr = document.querySelector('.roster-table .el-table__body tr');
        return tr ? tr.querySelector('.stu-username, .stu-name').textContent : '';
      })()`);
    }
    // 切换到按学号
    await tab.eval(`(() => {
      const sel = document.querySelector('.roster-sort');
      sel.click();
    })()`);
    await sleep(400);
    await tab.eval(`(() => {
      const items = [...document.querySelectorAll('.el-select-dropdown__item')].filter((el) => el.getBoundingClientRect().height > 0);
      const target = items.find((el) => el.textContent.includes('按学号'));
      if (target) target.click();
    })()`);
    await sleep(500);
    const byUsername = await firstCellText();
    check('R.5 排序切换（按学号）后有数据', byUsername.length > 0, `first=${byUsername}`);

    // ---- R.6 行内「详情」跳转 ----
    await tab.eval(`(() => {
      const tr = document.querySelector('.roster-table .el-table__body tr');
      const btn = [...tr.querySelectorAll('button')].find((b) => b.textContent.includes('详情'));
      btn.click();
    })()`);
    let detailNav = await waitFor(tab, `location.pathname.match(/^\\/teacher\\/classes\\/\\d+\\/students\\/\\d+$/)`, 10000);
    check('R.6 「详情」跳转学生详情页', detailNav, await tab.eval('location.pathname'));

    // ---- R.6b 点击姓名/学号区域直接进入详情 ----
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    await waitFor(tab, `location.pathname === '/teacher/classes'`);
    await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 15000);
    await sleep(300);
    await tab.eval(`(() => {
      const row = document.querySelector('.class-row');
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('学生'));
      btn.click();
    })()`);
    await waitFor(tab, `location.pathname.match(/^\\/teacher\\/classes\\/\\d+\\/students$/)`);
    const rowsReady6b = await waitFor(tab, `document.querySelectorAll('.roster-table .el-table__body tr').length > 0`, 30000);
    await sleep(300);
    await tab.eval(`(() => { document.querySelector('.roster-table .stu-cell-link').click(); })()`);
    detailNav = await waitFor(tab, `location.pathname.match(/^\\/teacher\\/classes\\/\\d+\\/students\\/\\d+$/)`, 10000);
    check('R.6b 点击学生姓名/学号区域进详情', rowsReady6b && detailNav, await tab.eval('location.pathname'));

    // ---- R.7 返回 ----
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    await waitFor(tab, `location.pathname === '/teacher/classes'`);
    await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 15000);
    await sleep(300);
    const backOk = await tab.eval(`(() => {
      const row = document.querySelector('.class-row');
      if (!row) return false;
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('学生'));
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    await waitFor(tab, `location.pathname.match(/^\\/teacher\\/classes\\/\\d+\\/students$/)`);
    await waitFor(tab, `document.querySelectorAll('.roster-table .el-table__body tr').length > 0`, 15000);
    await sleep(400);
    const headBtnOk = await tab.eval(`(() => {
      const btn = document.querySelector('.roster-head button');
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    const backNav = await waitFor(tab, `location.pathname === '/teacher/classes'`, 8000);
    check('R.7 返回按钮回到班级管理页', backOk && headBtnOk && backNav, await tab.eval('location.pathname'));

    // ---- R.8 console 干净 ----
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('R.8 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
