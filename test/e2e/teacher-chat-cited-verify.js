#!/usr/bin/env node
/**
 * 教师端「完整讲解 - AI 助教」参考来源显示实测（CourseCatalog.vue）：
 *   TC.1 登录教师并进入课程章节页
 *   TC.2 章节树加载
 *   TC.3 打开「完整讲解」对话框
 *   TC.4 打开 AI 助教 Dock
 *   TC.5 点击预置问题「这一章的重点是什么？」并等待回答完成
 *   TC.6 回答下方出现「参考来源」区块与来源 pill（修复前教师端完全不显示）
 *   TC.7 pill 不含未挂章节的无关资料（在线预览测试.pdf）——章节检索过滤回归
 *   TC.8 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动（前端为最新构建）；教师 t101=pass1234，课程 5 有课件。
 * 运行：node test/e2e/teacher-chat-cited-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'pass1234';
const COURSE_ID = 5;

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-tc-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

// ---------------- CDP 客户端（与 learning-chat-cited-verify.js 同款） ----------------
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
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error('CDP timeout: ' + method));
        }
      }, 30000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture: true,
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
    await sleep(500);
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
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

async function launchChrome() {
  try {
    fs.rmSync(PROFILE, { recursive: true, force: true });
  } catch { /* 忽略 */ }
  const chrome = spawn(CHROME, [
    '--headless=new',
    '--no-proxy-server',
    '--disable-gpu',
    '--enable-unsafe-swiftshader',
    '--use-angle=swiftshader',
    '--no-first-run',
    '--remote-debugging-port=' + PORT,
    '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE,
    '--window-size=1440,900',
    'about:blank',
  ], { stdio: 'ignore', detached: true });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const pages = list.filter((t) => t.type === 'page');
      const page = pages[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
    await sleep(250);
  }
  if (!wsUrl) { killChrome(chrome); throw new Error('Chrome devtools 端口未绪'); }

  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { cdp, chrome };
}

function killChrome(chrome) {
  try {
    execSync(`taskkill /PID ${chrome.pid} /T /F`, { stdio: 'ignore' });
  } catch { /* 进程可能已退出 */ }
  try { chrome.kill(); } catch { /* ignore */ }
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    // TC.1 登录教师并进入课程章节页
    await login(cdp, 't101', PW);
    await cdp.navigate(BASE + `/teacher/courses/${COURSE_ID}/chapters`);
    const pageOk = await waitFor(cdp, `document.querySelectorAll('.tree-node').length >= 1`, 30000);
    check('TC.1 教师登录并进入课程章节页', pageOk);
    if (!pageOk) throw new Error('章节页未加载，终止');

    // TC.2 点击第一个章节的「完整讲解」
    const opened = await cdp.eval(`(function(){
      var btns = [...document.querySelectorAll('.node-action-btn')];
      var btn = btns.find((b) => b.textContent.trim() === '完整讲解');
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    check('TC.2 找到并点击「完整讲解」', opened);
    const dialogOk = await waitFor(cdp, `!!document.querySelector('.full-lecture-body')`, 20000);
    check('TC.3 完整讲解对话框打开', dialogOk);
    if (!dialogOk) throw new Error('完整讲解对话框未打开，终止');

    // TC.4 点击「AI 助教」打开 Dock
    const dockOpened = await cdp.eval(`(function(){
      var btns = [...document.querySelectorAll('.full-lecture-soft-btn')];
      var btn = btns.find((b) => b.textContent.includes('AI 助教'));
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    check('TC.4 点击「AI 助教」按钮', dockOpened);
    const chatOk = await waitFor(cdp, `!!document.querySelector('.dock-chat .chat-textarea')`, 20000);
    check('TC.5 助教 Dock 打开（chat 输入框可见）', chatOk);
    if (!chatOk) throw new Error('助教 Dock 未打开，终止');

    // TC.6 点击预置问题「这一章的重点是什么？」（与用户反馈的问题一致）
    const asked = await cdp.eval(`(function(){
      var sug = [...document.querySelectorAll('.chat-suggest')].find((b) => b.textContent.includes('这一章的重点'));
      if (sug) { sug.click(); return 'suggest'; }
      return false;
    })()`);
    check('TC.6 点击预置问题「这一章的重点是什么？」', !!asked, String(asked || ''));

    // TC.7 等待回答完成：assistant 消息出现且非流式（.chat-sources 只在结束后渲染）
    const answered = await waitFor(cdp,
      `!!document.querySelector('.chat-row.assistant .chat-sources')`, 180000);
    check('TC.7 回答输出完成并出现参考来源区块（修复前教师端不显示）', answered);
    if (!answered) {
      await cdp.shot('teacher-chat-cited-fail');
      throw new Error('回答未在预期时间内完成或参考来源未出现');
    }

    // TC.8 参考来源 pill 文案
    const tags = await cdp.eval(`[...document.querySelectorAll('.chat-sources .chat-source-tags .el-tag')].map((t) => t.textContent.trim())`);
    check('TC.8 参考来源 pill 非空', Array.isArray(tags) && tags.length >= 1, JSON.stringify(tags));

    // TC.9 章节过滤回归：pill 不含未挂章节的无关资料（在线预览测试.pdf）
    const noise = (tags || []).filter((t) => /在线预览测试|说明文档/.test(t));
    check('TC.9 参考来源不含未挂章节的无关资料', noise.length === 0, noise.length ? '混入: ' + noise.join(',') : '');

    // TC.10 无重复渲染：assistant 气泡内只应有 chat-md 一个正文块
    const dup = await cdp.eval(`(function(){
      var row = document.querySelector('.chat-row.assistant');
      if (!row) return null;
      return {
        mdCount: row.querySelectorAll('.chat-md').length,
        plainCount: row.querySelectorAll('.chat-text:not(.chat-md)').length,
      };
    })()`);
    check('TC.10 助手气泡无重复渲染', !!dup && dup.mdCount === 1 && dup.plainCount === 0, dup ? JSON.stringify(dup) : '未找到助手消息');

    await cdp.shot('teacher-chat-cited-ok');

    // TC.11 无 JS 异常
    check('TC.11 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' ; ') || '');
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
  console.error('E2E 执行异常:', err.message);
  process.exitCode = 1;
});
