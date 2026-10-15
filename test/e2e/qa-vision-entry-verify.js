#!/usr/bin/env node
/**
 * 问答图片上传入口·视觉能力开关闭环实测（任务 #48/#49）：
 *   VE.1 开关关闭时学生端助教 Dock 无「图片」按钮（fail-closed）
 *   VE.2 管理端 chat 卡开关为关闭态；模型名填 qwen-vl-max 出现错配警告（UI 态，不保存）
 *   VE.3 管理端打开开关并保存 → 成功提示
 *   VE.4 生效表格出现「图片」标记
 *   VE.5 学生端重新进入 → 「图片」按钮出现（开关生效）
 *   VE.6 教师端讲解页助教同样出现「图片」按钮
 *   VE.7 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动（前端为最新构建）；dev 库 chat 行 supports_vision=False
 *       （脚本运行前由调用方关闭；脚本结束保持在 True）。
 * 运行：node test/e2e/qa-vision-entry-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW_STUDENT = 'A0987654';
const PW_TEACHER = 'pass1234';
const PW_ADMIN = 'A0987654';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9800 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-ve-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

// ---------------- CDP 客户端（与 cdp-drive.js 同款） ----------------
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
        if (this.pending.has(this.id)) {
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
  await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`, 30000);
}

// 打开学生端助教 Dock（点第一个章节的「AI 问答」）
async function openStudentDock(cdp) {
  await cdp.navigate(BASE + '/student/learning');
  const rowsOk = await waitFor(cdp, `document.querySelectorAll('.tree-node').length >= 1`, 30000);
  if (!rowsOk) throw new Error('章节列表未加载');
  await cdp.eval(`(function(){
    var btns = [...document.querySelectorAll('.node-action-btn')];
    var btn = btns.find((b) => b.textContent.includes('AI 问答'));
    if (btn) btn.click();
  })()`);
  return waitFor(cdp, `!!document.querySelector('.full-lecture-dock .chat-textarea')`, 20000);
}

// 图片按钮是否存在（chat-input-bar 内的 .chat-tool，title=提交图片提问）
const IMAGE_BTN_EXPR = `!!document.querySelector('.chat-input-bar .chat-tool[title="提交图片提问"]')`;

// chat 卡内「支持图片（多模态）」表单项里的开关（注意：卡头还有一个启用/停用开关，
// 不能直接取卡内第一个 .el-switch）
const VISION_SWITCH_EXPR = `(function(){
  var card = document.querySelector('.capability-grid .config-card');
  var items = [...card.querySelectorAll('.el-form-item')];
  var fi = items.find((i) => {
    var lb = i.querySelector('.el-form-item__label');
    return lb && lb.textContent.includes('支持图片');
  });
  return fi && fi.querySelector('.el-switch');
})()`;

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
      const page = list.filter((t) => t.type === 'page')[0];
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
    // ---------- VE.1 开关关闭 → 学生端无图片入口 ----------
    await login(cdp, '20249999', PW_STUDENT);
    const dockOk = await openStudentDock(cdp);
    check('VE.0 学生端助教 Dock 打开', dockOk);
    if (!dockOk) throw new Error('Dock 未打开，终止');
    // 等挂载时的能力查询返回（接口很快；给 2s 宽限）
    await sleep(2000);
    const hidden = await cdp.eval(`!${IMAGE_BTN_EXPR}`);
    check('VE.1 开关关闭时学生端无「图片」按钮', hidden === true);
    await cdp.shot('qa-vision-student-hidden');

    // ---------- VE.2 管理端：开关关闭态 + 错配警告 ----------
    await login(cdp, 'admin', PW_ADMIN);
    await cdp.navigate(BASE + '/admin/ai-settings');
    const cardOk = await waitFor(cdp, `document.querySelectorAll('.capability-grid .config-card').length >= 4`, 20000);
    check('VE.2a 管理端大模型配置页加载', cardOk);
    if (!cardOk) throw new Error('配置页未加载，终止');
    const switchOff = await cdp.eval(`(function(){
      var sw = ${VISION_SWITCH_EXPR};
      return !!sw && !sw.classList.contains('is-checked');
    })()`);
    check('VE.2b chat 卡「支持图片」开关为关闭态', switchOff === true);

    // 模型名填 qwen-vl-max（不保存）→ 出现错配警告
    await cdp.eval(`(function(){
      var card = document.querySelector('.capability-grid .config-card');
      var inputs = card.querySelectorAll('input.el-input__inner');
      var model = inputs[1]; // [base_url, model_name, timeout, api_key]
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(model, 'qwen-vl-max');
      model.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    const warnOk = await waitFor(cdp, `(function(){
      var card = document.querySelector('.capability-grid .config-card');
      var note = card && card.querySelector('.warn-note');
      return !!note && note.textContent.includes('疑似多模态');
    })()`, 5000);
    check('VE.2c 模型名疑似视觉但开关关闭 → 错配警告出现', warnOk);
    // 还原模型名（仅表单态，不保存）
    await cdp.eval(`(function(){
      var card = document.querySelector('.capability-grid .config-card');
      var inputs = card.querySelectorAll('input.el-input__inner');
      var model = inputs[1];
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(model, 'qwen3.7-plus');
      model.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);

    // ---------- VE.3 打开「支持图片」开关并保存 ----------
    await cdp.eval(`(function(){
      var sw = ${VISION_SWITCH_EXPR};
      if (sw && !sw.classList.contains('is-checked')) sw.click();
    })()`);
    await sleep(300);
    await cdp.eval(`document.querySelector('.action-bar .el-button--primary').click()`);
    const saved = await waitFor(cdp, `!!document.querySelector('.el-message--success')`, 20000);
    check('VE.3 打开开关并保存成功', saved);

    // ---------- VE.4 生效表格出现「图片」标记 ----------
    const tagOk = await waitFor(cdp, `!!document.querySelector('.effective-table .vision-tag')`, 10000);
    check('VE.4 生效表格 chat 行出现「图片」标记', tagOk);
    await cdp.shot('qa-vision-admin-on');

    // ---------- VE.5 学生端重新进入 → 图片按钮出现 ----------
    await login(cdp, '20249999', PW_STUDENT);
    const dock2 = await openStudentDock(cdp);
    check('VE.5a 学生端助教 Dock 再次打开', dock2);
    if (!dock2) throw new Error('Dock 未打开，终止');
    const shown = await waitFor(cdp, IMAGE_BTN_EXPR, 10000);
    check('VE.5b 开关开启后学生端出现「图片」按钮', shown);
    await cdp.shot('qa-vision-student-shown');

    // ---------- VE.6 教师端同样出现 ----------
    await login(cdp, 't101', PW_TEACHER);
    await cdp.navigate(BASE + '/teacher/courses/5/chapters');
    const treeOk = await waitFor(cdp, `document.querySelectorAll('.tree-node, .catalog-node').length >= 1`, 20000);
    check('VE.6a 教师端课程章节页加载', treeOk);
    // 点第一个章节的「完整讲解」再点「AI 助教」（选择器与 teacher-chat-cited-verify.js 一致）
    await cdp.eval(`(function(){
      var btns = [...document.querySelectorAll('.node-action-btn')];
      var full = btns.find((b) => b.textContent.trim() === '完整讲解');
      if (full) full.click();
    })()`);
    const dialogOk = await waitFor(cdp, `!!document.querySelector('.full-lecture-body')`, 20000);
    check('VE.6b 完整讲解对话框打开', dialogOk);
    let tShown = false;
    if (dialogOk) {
      await cdp.eval(`(function(){
        var btns = [...document.querySelectorAll('.full-lecture-soft-btn')];
        var ai = btns.find((b) => b.textContent.includes('AI 助教'));
        if (ai) ai.click();
      })()`);
      const dockOk3 = await waitFor(cdp, `!!document.querySelector('.dock-chat .chat-textarea')`, 20000);
      check('VE.6c 教师端助教 Dock 打开', dockOk3);
      tShown = await waitFor(cdp, IMAGE_BTN_EXPR, 10000);
    }
    check('VE.6d 教师端助教出现「图片」按钮', tShown);
    if (tShown) await cdp.shot('qa-vision-teacher-shown');

    // ---------- VE.7 无 JS 异常 ----------
    check('VE.7 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' ; ') || '');
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
