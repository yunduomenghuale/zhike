#!/usr/bin/env node
/**
 * 学生端答题页实测——题目类型徽章 + 判断题对错选项
 *
 * 验证点（对应用户反馈）：
 *   SV.1 每道题卡片展示题型徽章（单选/多选/判断/填空/简答）
 *   SV.2 题型徽章文案与快照 qtype 一一对应
 *   SV.3 判断题渲染「正确/错误」单选选项（修复快照缺 options 的问题）
 *   SV.4 单选/多选回归：选项正常渲染
 *   SV.5 填空/简答回归：输入框/文本域正常渲染
 *   SV.6 交互回归：点击判断题选项能选中
 *   SV.7 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动；学生 20249999 在测试班，有已发布题目作业（未提交）。
 * 运行：node test/e2e/student-question-view-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const HW_TITLE = '3'; // 已发布题目作业标题（5 题：单选/多选/判断/填空/简答）

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9800 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-sv-e2e/run-${RUN_ID}`;

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
  async shotClip(name, clip) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', {
      format: 'png',
      clip: { x: clip.x, y: clip.y, width: clip.width, height: clip.height, scale: 1 },
    });
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

async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);

  try {
    log('===== 学生端答题页实测 =====');
    await login(cdp, process.env.SV_STUDENT || '20249999', PW);
    await goto('/student/homework');
    const listReady = await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.trim() === ${JSON.stringify(HW_TITLE)}; })`, 20000);
    check('SV.0 学生作业列表加载出目标作业', listReady);

    // 未提交作业 → 点「查看作业」进入答题
    const opened = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      if (!row) return 'ROW_NOT_FOUND';
      var btn = row.querySelector('.student-action-btn');
      if (!btn) return 'BTN_NOT_FOUND';
      var label = btn.textContent.trim();
      btn.click();
      return label;
    })()`);
    check('SV.0b 点击「查看作业」进入答题页', opened.indexOf('NOT_FOUND') < 0, 'btn="' + opened + '"');

    const cardsReady = await waitFor(cdp, `document.querySelectorAll('.homework-question-card').length >= 5`, 20000);
    check('SV.0c 答题页题目卡片渲染（5 题）', cardsReady);

    // ---------- SV.1/SV.2 题型徽章 ----------
    const badges = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.homework-question-card'));
      return cards.map(function(card){
        var tag = card.querySelector('.question-type-tag');
        var radios = card.querySelectorAll('.el-radio').length;
        var checks = card.querySelectorAll('.el-checkbox').length;
        var inputs = card.querySelectorAll('.blank-answer-list .el-input__inner').length;
        var textarea = card.querySelectorAll('textarea').length;
        return {
          tag: tag ? tag.textContent.trim() : '',
          tagClass: tag ? tag.className : '',
          radios: radios, checks: checks, inputs: inputs, textarea: textarea,
        };
      });
    })()`);
    check('SV.1 每题均有题型徽章',
      badges.length === 5 && badges.every(function(b){ return b.tag.length > 0; }),
      JSON.stringify(badges.map(function(b){ return b.tag; })));
    check('SV.2 题型徽章与快照 qtype 对应（单选/多选/判断/填空/简答）',
      JSON.stringify(badges.map(function(b){ return b.tag; })) === JSON.stringify(['单选', '多选', '判断', '填空', '简答']),
      JSON.stringify(badges.map(function(b){ return b.tag + ':' + b.tagClass; })));

    // ---------- SV.3 判断题对错选项 ----------
    const judgeCard = badges[2];
    const judgeOptions = await cdp.eval(`(function(){
      var cards = document.querySelectorAll('.homework-question-card');
      var card = cards[2];
      if (!card) return null;
      var labels = Array.from(card.querySelectorAll('.el-radio__label')).map(function(l){ return l.textContent.trim(); });
      return { labels: labels };
    })()`);
    check('SV.3 判断题渲染「正确/错误」单选选项（修复快照缺 options）',
      judgeCard.radios === 2 && judgeOptions && judgeOptions.labels.length === 2
        && judgeOptions.labels[0].indexOf('正确') >= 0 && judgeOptions.labels[1].indexOf('错误') >= 0,
      JSON.stringify(judgeOptions));

    // ---------- SV.4/SV.5 其他题型回归 ----------
    check('SV.4 单选/多选回归：选项正常渲染',
      badges[0].radios === 4 && badges[1].checks === 4,
      `single radios=${badges[0].radios} multi checks=${badges[1].checks}`);
    check('SV.5 填空/简答回归：输入框与文本域正常渲染',
      badges[3].inputs >= 1 && badges[4].textarea >= 1,
      `blank inputs=${badges[3].inputs} short textarea=${badges[4].textarea}`);

    // ---------- SV.6 交互回归：点判断题选项能选中 ----------
    const clicked = await cdp.eval(`(function(){
      var cards = document.querySelectorAll('.homework-question-card');
      var card = cards[2];
      var radio = card.querySelector('.el-radio');
      if (!radio) return 'NO_RADIO';
      radio.click();
      return 'CLICKED';
    })()`);
    await sleep(400);
    const checked = await cdp.eval(`(function(){
      var cards = document.querySelectorAll('.homework-question-card');
      var card = cards[2];
      var checkedRadio = card.querySelector('.el-radio.is-checked');
      var label = checkedRadio ? checkedRadio.querySelector('.el-radio__label') : null;
      return { checked: !!checkedRadio, label: label ? label.textContent.trim() : '' };
    })()`);
    check('SV.6 交互回归：点击判断题选项能选中',
      clicked === 'CLICKED' && checked.checked && checked.label.indexOf('正确') >= 0,
      JSON.stringify(checked));

    await cdp.shot('student-answer-page');

    // 判断题卡片裁剪放大截图
    const judgeClip = await cdp.eval(`(function(){
      var cards = document.querySelectorAll('.homework-question-card');
      var card = cards[2];
      if (!card) return null;
      var r = card.getBoundingClientRect();
      return { x: Math.round(r.left - 8), y: Math.round(r.top - 8), width: Math.round(r.width + 16), height: Math.round(r.height + 16) };
    })()`);
    if (judgeClip) await cdp.shotClip('student-judge-card-zoom', judgeClip);

    // ---------- 页面错误汇总 ----------
    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('SV.7 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
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
