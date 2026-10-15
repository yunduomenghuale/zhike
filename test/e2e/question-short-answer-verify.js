#!/usr/bin/env node
/**
 * 题目编辑器：简答题「参考答案」字段实测（对应用户第七轮反馈）
 *
 * 验证点：
 *   QA.1  教师题库页加载，可选择课程
 *   QA.2  新建题目对话框：题型切到「简答题」出现「参考答案」输入项
 *   QA.3  填入题干+参考答案保存后，重新编辑可见回填（answer.text 已落库）
 *   QA.4  题型从简答切回单选，「参考答案」输入项消失
 *   QA.5  删除测试题目，无残留
 *
 * 前置：后端 8005、前端 5273 已启动；t101 有课程（java程序设计）与章节。
 * 运行：node test/e2e/question-short-answer-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const STEM = 'E2E简答题参考要点测试（自动创建，可删）';
const REF_ANSWER = '要点一：隔离广播域；要点二：便于管理';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9700 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-qa-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

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
  if (!wsUrl) { killChrome(chrome); throw new Error('Chrome devtools 端口未就绪'); }

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

// 在页面上下文中调用后端 API（复用 localStorage 里的 token），返回 JSON
async function apiGet(cdp, url) {
  return cdp.eval(`(async function(){
    var raw = localStorage.getItem('zhike.token') || localStorage.getItem('token') || '';
    var tok = '';
    try { tok = JSON.parse(raw).access || raw; } catch (e) { tok = raw; }
    var r = await fetch(${JSON.stringify(url)}, { headers: { 'Authorization': 'Bearer ' + tok } });
    return await r.json();
  })()`);
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);

  try {
    log('===== 题目编辑器：简答题参考答案 =====');
    await login(cdp, 't101', PW);
    await goto('/teacher/questions');

    // QA.1 课程默认自动选中第一个（286 行逻辑，异步加载）。
    // 注意：EP el-select 选中后 input.value 仍为空，可靠判据是 v-if="courseId" 的「新建题目」按钮
    const courseReady = await waitFor(cdp, `(function(){
      var btn = Array.from(document.querySelectorAll('.q-toolbar-actions button')).find(function(b){ return b.textContent.indexOf('新建题目') >= 0; });
      return !!btn;
    })()`, 20000);
    check('QA.1 题库页加载且课程已自动选中（新建题目按钮出现）', courseReady);
    const listReady = await waitFor(cdp, `document.querySelectorAll('.q-row').length >= 1`, 20000);
    check('QA.1b 题目列表加载', listReady);

    // 打开新建题目对话框
    await cdp.eval(`(function(){
      var btn = Array.from(document.querySelectorAll('.q-toolbar-actions button')).find(function(b){ return b.textContent.indexOf('新建题目') >= 0; });
      if (btn) btn.click();
    })()`);
    const dialogReady = await waitFor(cdp, `!!document.querySelector('.question-form-dialog .question-creation-form')`, 15000);
    check('QA.2 新建题目对话框打开', dialogReady);

    // 题型切到简答题
    await cdp.eval(`(function(){
      var sel = document.querySelector('.question-form-dialog .question-type-field .el-select');
      var input = sel.querySelector('input');
      input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      input.click();
    })()`);
    await sleep(500);
    const shortPicked = await cdp.eval(`(function(){
      var opts = Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(function(o){ return o.offsetParent !== null; });
      var target = opts.find(function(o){ return o.textContent.trim() === '简答题'; });
      if (target) { target.click(); return 'PICKED'; }
      return 'NOT_FOUND:' + opts.map(function(o){ return o.textContent.trim(); }).join(',');
    })()`);
    check('QA.2b 题型切换为简答题', shortPicked === 'PICKED', shortPicked);
    await sleep(400);

    // 「参考答案」输入项出现
    const refVisible = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.question-form-dialog .el-form-item'));
      var hit = items.find(function(it){ return (it.querySelector('.el-form-item__label') || {}).textContent === '参考答案'; });
      if (!hit) return { found: false };
      var ta = hit.querySelector('textarea');
      return { found: true, placeholder: ta ? ta.getAttribute('placeholder') : '' };
    })()`);
    check('QA.2c 简答题出现「参考答案」输入项', !!refVisible.found, JSON.stringify(refVisible));

    // 填题干 + 参考答案，选择所属章节，保存（草稿）
    await cdp.eval(`(function(){
      function setTa(sel, v){
        var el = document.querySelector(sel);
        if (!el) return;
        var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      setTa('.question-form-dialog textarea[placeholder="请输入题干"]', ${JSON.stringify(STEM)});
      var refItems = Array.from(document.querySelectorAll('.question-form-dialog .el-form-item'));
      var hit = refItems.find(function(it){ return (it.querySelector('.el-form-item__label') || {}).textContent === '参考答案'; });
      var ta = hit.querySelector('textarea');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, ${JSON.stringify(REF_ANSWER)});
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(300);
    // 选择所属章节（save 校验必选）
    await cdp.eval(`(function(){
      var sel = document.querySelector('.question-form-dialog .form-row-grow .el-select');
      if (!sel) return;
      var input = sel.querySelector('input');
      input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      input.click();
    })()`);
    await sleep(500);
    const catalogPicked = await cdp.eval(`(function(){
      var opts = Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(function(o){ return o.offsetParent !== null; });
      if (!opts.length) return 'NO_OPTIONS';
      opts[0].click();
      return 'PICKED';
    })()`);
    check('QA.2d 选择所属章节', catalogPicked === 'PICKED', catalogPicked);
    await sleep(400);
    await cdp.eval(`(function(){
      var footer = document.querySelector('.question-form-dialog .creation-dialog-footer');
      var btn = Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.trim() === '创建题目'; });
      if (btn) btn.click();
    })()`);
    const created = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.q-row'));
      return rows.some(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
    })()`, 15000);
    check('QA.3 保存后题目出现在列表', created);
    await cdp.shot('question-short-ref-created');

    // 重新编辑该题，验证参考答案回填
    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.q-row'));
      var row = rows.find(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
      var btn = Array.from(row.querySelectorAll('.q-action-group button')).find(function(b){ return b.textContent.indexOf('编辑') >= 0; });
      if (btn) btn.click();
    })()`);
    const reopenReady = await waitFor(cdp, `!!document.querySelector('.question-form-dialog .question-creation-form')`, 15000);
    check('QA.3b 重新打开编辑对话框', reopenReady);
    await sleep(500);
    const refFilled = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.question-form-dialog .el-form-item'));
      var hit = items.find(function(it){ return (it.querySelector('.el-form-item__label') || {}).textContent === '参考答案'; });
      if (!hit) return 'NO_FIELD';
      var ta = hit.querySelector('textarea');
      return ta ? ta.value : 'NO_TA';
    })()`);
    check('QA.3c 参考答案回填（answer.text 已落库）', refFilled === REF_ANSWER, refFilled);

    // 题型切回单选，「参考答案」输入项消失
    await cdp.eval(`(function(){
      var sel = document.querySelector('.question-form-dialog .question-type-field .el-select');
      var input = sel.querySelector('input');
      input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      input.click();
    })()`);
    await sleep(500);
    await cdp.eval(`(function(){
      var opts = Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(function(o){ return o.offsetParent !== null; });
      var target = opts.find(function(o){ return o.textContent.trim() === '单选题'; });
      if (target) target.click();
    })()`);
    await sleep(400);
    const refGone = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.question-form-dialog .el-form-item'));
      var hit = items.find(function(it){ return (it.querySelector('.el-form-item__label') || {}).textContent === '参考答案'; });
      return !hit;
    })()`);
    check('QA.4 切回单选后「参考答案」输入项消失', refGone);

    // 关闭对话框，删除所有测试题目（兼容上轮未删净的残留，最多 3 轮）
    await cdp.eval(`(function(){
      var btn = document.querySelector('.question-form-dialog .creation-dialog-close');
      if (btn) btn.click();
    })()`);
    await sleep(400);
    let removed = false;
    for (let round = 0; round < 3; round++) {
      const hasRow = await cdp.eval(`(function(){
        var rows = Array.from(document.querySelectorAll('.q-row'));
        return rows.some(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
      })()`);
      if (!hasRow) { removed = true; break; }
      await cdp.eval(`(function(){
        var rows = Array.from(document.querySelectorAll('.q-row'));
        var row = rows.find(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
        var btn = Array.from(row.querySelectorAll('.q-action-group button')).find(function(b){ return b.textContent.indexOf('删除') >= 0; });
        if (btn) btn.click();
      })()`);
      const confirmReady = await waitFor(cdp, `!!document.querySelector('.platform-delete-dialog')`, 10000);
      if (confirmReady) {
        await sleep(400);
        await cdp.eval(`(function(){
          var dlg = document.querySelector('.platform-delete-dialog');
          var btn = Array.from(dlg.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('确认删除') >= 0; });
          if (btn) btn.click();
        })()`);
      }
      await waitFor(cdp, `!document.querySelector('.platform-delete-dialog')`, 10000);
      await sleep(600);
    }
    check('QA.5 测试题目已删除（无残留）', removed);

    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('QA.6 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok);
  log('===== 汇总: ' + (results.length - failed.length) + '/' + results.length + ' 通过 =====');
  if (failed.length) {
    failed.forEach((r) => console.log('FAIL | ' + r.name));
    process.exitCode = 1;
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 1;
});
