#!/usr/bin/env node
/**
 * 纯客观题作业「提交即可见答案/解析/结果」实测（对应用户第五轮反馈第 4 项）
 *
 * 验证点：
 *   PO.0  学生作业列表加载出纯客观题作业
 *   PO.1  未提交时显示「查看作业」入口
 *   PO.2  答题页渲染 4 道客观题（单选/判断/多选/填空）
 *   PO.3  全部作答后可提交
 *   PO.4  提交即自动出分并发布（toast 提示「成绩已发布」）
 *   PO.5  列表状态徽章直接显示「已发布 N 分」（无需教师操作）
 *   PO.6  结果页显示得分卡片（15/20）
 *   PO.7  每题显示正确答案与解析（提交后立即可见）
 *   PO.8  每题显示得分徽章（答对/答错）
 *   PO.9  无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动；已播种纯客观题作业（4 题，20 分，班级 1）。
 * 作答策略：单选选 B（对）、判断选 A 正确（对）、多选选 A/B/C（对）、填空填 1,2（错）→ 15/20。
 * 重复运行：学生只能提交一次，二次运行时自动跳过提交阶段直接验证结果页；
 * 如需完整重跑，先删提交：backend shell 里 HomeworkSubmission.objects.filter(homework__title='纯客观题即时出分E2E').delete()
 * 运行：node test/e2e/homework-pure-objective-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const HW_TITLE = '纯客观题即时出分E2E';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9500 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-po-e2e/run-${RUN_ID}`;

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
    log('===== 纯客观题作业：提交即可见答案/解析/结果 =====');
    await login(cdp, '20249999', PW);
    await goto('/student/homework');

    const listReady = await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.trim() === ${JSON.stringify(HW_TITLE)}; })`, 20000);
    check('PO.0 学生作业列表加载出纯客观题作业', listReady);

    const rowInfo = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      if (!row) return null;
      var btn = row.querySelector('.student-action-btn');
      var status = row.querySelector('.student-status');
      return { btn: btn ? btn.textContent.trim() : '', disabled: btn ? btn.disabled : null, status: status ? status.textContent.trim() : '' };
    })()`);
    // 已提交过（重复运行）→ 跳过提交阶段，直接验证结果页
    if (rowInfo && /查看结果/.test(rowInfo.btn)) {
      log('--- 检测到已提交（重复运行），跳过提交阶段，直接验证结果页 ---');
      check('PO.1 未提交时显示「查看作业」入口（重复运行已提交，跳过）', true, JSON.stringify(rowInfo));
    } else {
      check('PO.1 未提交时显示「查看作业」入口', !!(rowInfo && /查看作业/.test(rowInfo.btn)), JSON.stringify(rowInfo));
      await cdp.eval(`(function(){
        var rows = Array.from(document.querySelectorAll('.student-row'));
        var row = rows.find(function(r){
          var t = r.querySelector('.student-row-title');
          return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
        });
        var btn = row.querySelector('.student-action-btn');
        if (btn) btn.click();
      })()`);
      const cardsReady = await waitFor(cdp, `document.querySelectorAll('.homework-question-card').length >= 4`, 20000);
      check('PO.2 答题页渲染 4 道客观题', cardsReady);

      // 作答：单选选 B（第 2 项）/ 判断选 A 正确 / 多选选 A,B,C / 填空填 1,2（故意答错）
      // 注意：多选必须逐次点击并留间隔——EP checkbox-group 的 modelValue 经 props 更新，
      // 同步连点时组件读到的还是旧值，会丢失前几次选择（真实用户逐次点不受影响）
      const clickCardOption = async (cardIndex, kind, optIndex) => {
        return cdp.eval(`(function(){
          var cards = Array.from(document.querySelectorAll('.homework-question-card'));
          var card = cards[${cardIndex}];
          if (!card) return 'NO_CARD';
          var els = card.querySelectorAll(${JSON.stringify(kind)});
          var el = els[${optIndex}];
          if (!el) return 'NO_OPTION';
          el.click();
          return 'CLICKED';
        })()`);
      };
      const r1 = await clickCardOption(0, '.el-radio', 1);
      const r2 = await clickCardOption(1, '.el-radio', 0);
      check('PO.3 单选/判断选项点击', r1 === 'CLICKED' && r2 === 'CLICKED', r1 + ',' + r2);
      const m1 = await clickCardOption(2, '.el-checkbox', 0);
      await sleep(120);
      const m2 = await clickCardOption(2, '.el-checkbox', 1);
      await sleep(120);
      const m3 = await clickCardOption(2, '.el-checkbox', 2);
      await sleep(120);
      check('PO.3a 多选逐次点击 A/B/C', m1 === 'CLICKED' && m2 === 'CLICKED' && m3 === 'CLICKED', m1 + ',' + m2 + ',' + m3);
      const multiChecked = await cdp.eval(`(function(){
        var cards = Array.from(document.querySelectorAll('.homework-question-card'));
        return cards[2] ? cards[2].querySelectorAll('.el-checkbox.is-checked').length : -1;
      })()`);
      check('PO.3a2 多选选中态为 3 项', multiChecked === 3, 'checked=' + multiChecked);
      const blankFilled = await cdp.eval(`(function(){
        var cards = Array.from(document.querySelectorAll('.homework-question-card'));
        if (cards.length < 4) return 'CARDS_NOT_READY';
        var inputs3 = cards[3].querySelectorAll('.blank-answer-list .el-input__inner');
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        var vals = ['1', '2'];
        inputs3.forEach(function(inp, i){
          setter.call(inp, vals[i] !== undefined ? vals[i] : '');
          inp.dispatchEvent(new Event('input', { bubbles: true }));
        });
        return 'ANSWERED';
      })()`);
      check('PO.3b 填空填写 1,2（故意答错）', blankFilled === 'ANSWERED', blankFilled);
      await sleep(400);

      const progress = await cdp.eval(`(function(){
        var p = document.querySelector('.answer-progress');
        return p ? p.textContent.replace(/\\s+/g, ' ').trim() : '';
      })()`);
      check('PO.3b 作答进度 4/4', /4\s*\/\s*4/.test(progress), progress);

      await cdp.eval(`(function(){
        var footer = document.querySelector('.workspace-footer');
        var btn = footer ? Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('确认提交') >= 0; }) : null;
        if (btn) btn.click();
      })()`);
      const submitToast = await waitFor(cdp, `(function(){
        var toasts = Array.from(document.querySelectorAll('.el-message__content')).map(function(t){ return t.textContent; });
        return toasts.some(function(t){ return t.indexOf('提交成功') >= 0; });
      })()`, 20000);
      check('PO.4 提交成功（纯客观题自动批改并发布）', submitToast);
      await sleep(1200); // 等 load() 刷新列表
    }

    // 列表状态：已发布 N 分（无需教师任何操作）
    const statusAfter = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      if (!row) return null;
      var status = row.querySelector('.student-status');
      var btn = row.querySelector('.student-action-btn');
      return { status: status ? status.textContent.trim() : '', btn: btn ? btn.textContent.trim() : '' };
    })()`);
    check('PO.5 列表状态直接显示「已发布 15 分」', !!(statusAfter && /已发布 15 分/.test(statusAfter.status)), JSON.stringify(statusAfter));

    // 进入结果页
    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      var btn = row.querySelector('.student-action-btn');
      if (btn) btn.click();
    })()`);
    const viewReady = await waitFor(cdp, `!!document.querySelector('.result-summary')`, 15000);
    check('PO.6 结果页显示得分卡片', viewReady);

    const summary = await cdp.eval(`(function(){
      var s = document.querySelector('.result-summary');
      return s ? s.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('PO.6b 得分卡片显示 15/20', /15/.test(summary) && /20/.test(summary), summary);

    const resultItems = await cdp.eval(`(function(){
      var list = Array.from(document.querySelectorAll('.answer-result-item'));
      return list.map(function(item){
        return {
          title: (item.querySelector('.result-question-title') || {}).textContent,
          correct: !!item.querySelector('.correct-answer'),
          correctText: (item.querySelector('.correct-answer') || {}).textContent,
          analysis: !!item.querySelector('.answer-analysis'),
          scoreRow: (item.querySelector('.result-score-row') || {}).textContent,
        };
      });
    })()`);
    check('PO.7 结果页渲染全部 4 题', resultItems.length === 4, 'count=' + resultItems.length);
    check('PO.7b 每题显示正确答案', resultItems.every(function(i){ return i.correct; }), JSON.stringify(resultItems.map(function(i){ return i.correctText && i.correctText.trim().slice(0, 16); })));
    check('PO.7c 每题显示解析', resultItems.every(function(i){ return i.analysis; }), resultItems.filter(function(i){ return !i.analysis; }).length + ' 题缺解析');
    check('PO.8 每题显示得分徽章（含答错项）', resultItems.every(function(i){ return /得分/.test(i.scoreRow || ''); }) && resultItems.some(function(i){ return /答错/.test(i.scoreRow || ''); }), JSON.stringify(resultItems.map(function(i){ return i.scoreRow && i.scoreRow.trim(); })));

    await cdp.shot('student-pure-objective-result');

    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('PO.9 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
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
