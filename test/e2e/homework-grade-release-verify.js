#!/usr/bin/env node
/**
 * 作业「提交后即可学习 + 批改即发布 + 答案展示增强」全流程实测（对应用户第六/七轮反馈）
 *
 * 验证点：
 *   LN.1  学生提交后（教师未批改）即可见每题正确答案与解析（含主观题解析）
 *   LN.1b 选择题「我的答案」附带选项内容（C. 完全无法通信，而非仅 C）
 *   LN.1c 简答题展示为「参考答案」（非「正确答案」）
 *   LN.2  客观题即时显示得分徽章（自动批改出分）
 *   LN.3  主观题显示「等待教师批改」，未发布时不显示总得分卡片
 *   LN.4  填空多空答案分隔符为「；」（非 /）
 *   GR.1  教师端抽屉：学生/提交时间/逾期/得分/成绩/操作 六列，列宽按卡片宽度分配、占满且均衡
 *   GR.1a 表格宽度占满抽屉（分配列宽生效，无留白/无横向溢出）
 *   GR.1d 列宽均衡：无某列过宽/某列过窄（历史事故：学生列 balloon 到 600px+）
 *   GR.1e 各列内容单行渲染不换行（时间/得分/操作按钮；用户反馈按钮从单行变两行）
 *   GR.1f 表格正文字体统一（14px/600，学生姓名曾走默认 400 与其他列 700/850 混杂）
 *   GR.2  未批改时成绩列显示「待批改」
 *   GR.3  批改弹窗：摘要栏/待评高亮/自动定位/评分行可见
 *   GR.3d 批改弹窗「学生答案」附带选项内容；简答题标签为「参考答案」
 *   GR.4  单一按钮「提交批改」——批改即发布，无中间状态
 *   GR.5  批改后抽屉直接显示「已发布」
 *   ST.1  学生端状态徽章显示「已发布 N 分」
 *   ST.2  结果页显示总得分卡片
 *   ST.3  主观题显示得分与逐题评语
 *   ST.4  无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动；t101 有待批改提交（作业「3」，学生 20249999，含简答题）。
 * 运行：node test/e2e/homework-grade-release-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const HW_TITLE = '3';
const MANUAL_SCORE = '3';
const MANUAL_COMMENT = '再组织一下语言会更好';
const OVERALL_COMMENT = '整体完成不错，简答题再展开一点';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-gr-e2e/run-${RUN_ID}`;
// 默认 1440；E2E_VIEWPORT_W=1920 可复验宽屏（抽屉 max-width 封顶后的列均衡）
const VIEWPORT_W = Number(process.env.E2E_VIEWPORT_W || 1440);

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

// elementFromPoint 绘制探针：元素中心点最顶层是否就是目标元素（或其子元素）
async function painted(cdp, selector) {
  return cdp.eval(`(function(){
    var el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return { found: false };
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return { found: true, painted: false, reason: 'zero-size' };
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) return { found: true, painted: false, reason: 'out-of-viewport' };
    var top = document.elementFromPoint(cx, cy);
    return { found: true, painted: !!(top && el.contains(top)), top: top ? (top.className || top.tagName) : '' };
  })()`);
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
    '--window-size=' + VIEWPORT_W + ',900',
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
    width: VIEWPORT_W, height: 900, deviceScaleFactor: 1, mobile: false,
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
  // 学生进入作业「3」的结果页
  const openStudentResult = async () => {
    await goto('/student/homework');
    await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.trim() === ${JSON.stringify(HW_TITLE)}; })`, 20000);
    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      var btn = row.querySelector('.student-action-btn');
      if (btn) btn.click();
    })()`);
    return waitFor(cdp, `!!document.querySelector('.answer-result-list') || !!document.querySelector('.pending-review')`, 15000);
  };

  try {
    // ========== 阶段 A：学生提交后、教师未批改 → 直接学习 ==========
    log('===== 阶段 A：提交后即可学习（教师未批改） =====');
    await login(cdp, '20249999', PW);
    await openStudentResult();

    const learnItems = await cdp.eval(`(function(){
      var list = Array.from(document.querySelectorAll('.answer-result-item'));
      return list.map(function(item){
        return {
          qtype: (item.querySelector('.question-type-tag') || {}).textContent,
          studentAns: (item.querySelector('.submitted-answer') || {}).textContent,
          answerLine: (item.querySelector('.correct-answer') || {}).textContent,
          correct: !!item.querySelector('.correct-answer'),
          correctText: (item.querySelector('.correct-answer') || {}).textContent,
          analysis: !!item.querySelector('.answer-analysis'),
          scoreRow: (item.querySelector('.result-score-row') || {}).textContent,
        };
      });
    })()`);
    check('LN.0 结果页渲染全部 5 题', learnItems.length === 5, 'count=' + learnItems.length);
    check('LN.1 提交后每题即可见正确答案与解析（含主观题）',
      learnItems.every(function(i){ return i.correct && i.analysis; }),
      JSON.stringify(learnItems.map(function(i){ return (i.correctText || '').trim().slice(0, 14); })));
    // LN.1b 选择题「我的答案」附带选项内容
    check('LN.1b 选择题我的答案附带选项内容',
      /我的答案：C\.完全无法通信/.test((learnItems[0].studentAns || '').replace(/\s+/g, '')),
      (learnItems[0].studentAns || '').trim());
    // LN.1c 简答题展示为「参考答案」
    check('LN.1c 简答题展示为「参考答案」', /参考答案：/.test(learnItems[4].answerLine || '') && !/正确答案/.test(learnItems[4].answerLine || ''), (learnItems[4].answerLine || '').trim().slice(0, 30));
    check('LN.2 客观题即时显示得分徽章',
      learnItems.slice(0, 4).every(function(i){ return /得分/.test(i.scoreRow || ''); }),
      JSON.stringify(learnItems.map(function(i){ return (i.scoreRow || '').trim(); })));
    check('LN.3 主观题显示「等待教师批改」', /等待教师批改/.test(learnItems[4].scoreRow || ''), (learnItems[4].scoreRow || '').trim());
    const summaryBefore = await cdp.eval(`!!document.querySelector('.result-summary')`);
    check('LN.3b 未批改时不显示总得分卡片', !summaryBefore);
    const pendingText = await cdp.eval(`(function(){
      var p = document.querySelector('.pending-review');
      return p ? p.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('LN.3c 待批改提示引导学习', /答案与解析已开放学习/.test(pendingText), pendingText);
    // LN.4 填空分隔符：正确答案「2；4」而非「2 / 4」
    const blankCorrect = (learnItems[3].correctText || '').trim();
    check('LN.4 填空多空答案分隔符为「；」', blankCorrect.indexOf('；') >= 0 && blankCorrect.indexOf('/') < 0, blankCorrect);
    await cdp.shot('student-learn-before-grading');

    // ========== 阶段 B：教师端批改（批改即发布） ==========
    log('===== 阶段 B：教师端批改即发布 =====');
    await login(cdp, 't101', PW);
    await goto('/teacher/homework');
    const rowReady = await waitFor(cdp, `Array.from(document.querySelectorAll('.hw-title')).some(function(t){ return t.textContent.trim() === ${JSON.stringify(HW_TITLE)}; })`, 20000);
    check('GR.0 教师作业列表加载出目标作业', rowReady);

    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.hw-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      var btn = Array.from(row.querySelectorAll('.hw-action-btn')).find(function(b){ return b.textContent.indexOf('批改') >= 0; });
      if (btn) btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.grading-drawer .grading-table')`, 15000);
    const rowsReady = await waitFor(cdp, `document.querySelectorAll('.grading-table tbody tr').length >= 1`, 15000);
    check('GR.0b 提交抽屉数据行渲染', rowsReady);

    // GR.1 抽屉列结构：无「提交内容」列，含「提交时间」，学生列为弹性宽度
    const headers = await cdp.eval(`(function(){
      return Array.from(document.querySelectorAll('.grading-table thead th')).map(function(th){ return th.textContent.trim(); });
    })()`);
    check('GR.1 抽屉列为 学生/提交时间/逾期/得分/成绩/操作',
      headers.length === 6 && headers.indexOf('提交内容') < 0 && headers[0] === '学生' && headers[1] === '提交时间' && headers[5] === '操作',
      JSON.stringify(headers));
    // 表格占满抽屉：表头单元格总宽与卡片内容宽一致（JS 按卡片宽度分配列宽，无留白/无横向溢出）
    const tableFill = await cdp.eval(`(function(){
      var card = document.querySelector('.grading-table-card');
      var ths = Array.from(document.querySelectorAll('.grading-table thead th'));
      if (!card || !ths.length) return null;
      var cardW = card.clientWidth;
      var sum = ths.reduce(function(s, th){ return s + th.getBoundingClientRect().width; }, 0);
      return { cardW: Math.round(cardW), tableW: Math.round(sum) };
    })()`);
    check('GR.1a 表格宽度占满抽屉（分配列宽生效）',
      !!tableFill && tableFill.tableW >= tableFill.cardW - 2 && tableFill.tableW <= tableFill.cardW + 2,
      JSON.stringify(tableFill));
    // GR.1d 列宽均衡：无某列过宽/某列过窄（历史事故：学生列 balloon 到 600px+）
    const colBalance = await cdp.eval(`(function(){
      var ths = Array.from(document.querySelectorAll('.grading-table thead th'));
      if (!ths.length) return null;
      var ws = ths.map(function(th){ return Math.round(th.getBoundingClientRect().width); });
      var max = Math.max.apply(null, ws), min = Math.min.apply(null, ws);
      return { ws: ws, max: max, min: min, ratio: Math.round((max / min) * 100) / 100 };
    })()`);
    check('GR.1d 各列宽度均衡（最宽≤230、最窄≥70、宽窄比≤2.8）',
      !!colBalance && colBalance.max <= 230 && colBalance.min >= 70 && colBalance.ratio <= 2.8,
      JSON.stringify(colBalance));
    // GR.1e 不换行：每个单元格的内容行数必须为 1（Range.getClientRects 按文本行计数）。
    // 历史事故：1440 窄卡片下时间列 150px、得分列 80px 均换行成两行；用户浏览器操作按钮也换行。
    // 学生列是裸文本（show-overflow-tooltip 注入 nowrap，超长省略号），其余列为 span/el-tag/button。
    const cellLines = await cdp.eval(`(function(){
      var row = document.querySelector('.grading-table tbody tr');
      if (!row) return null;
      function lineRects(node){
        var range = document.createRange();
        range.selectNodeContents(node);
        return range.getClientRects().length;
      }
      return Array.from(row.querySelectorAll('td')).map(function(td, i){
        var cell = td.querySelector('.cell');
        if (!cell) return { i: i, lines: null };
        var btn = cell.querySelector('.grading-action');
        var target = btn || cell.firstElementChild || cell;
        return { i: i, lines: lineRects(target) };
      });
    })()`);
    check('GR.1e 各列内容单行渲染不换行（含操作按钮）',
      !!cellLines && cellLines.length === 6 && cellLines.every(function(c){ return c.lines === 1; }),
      JSON.stringify(cellLines));
    // GR.1f 字体统一：前 5 列正文 14px/600（学生列无元素子节点，取 td 自身 computed），
    // 操作列按钮作为控件 13px/700。历史问题：学生列默认 400 vs 其他列 700/800/850 混杂。
    const cellFonts = await cdp.eval(`(function(){
      var row = document.querySelector('.grading-table tbody tr');
      if (!row) return null;
      function fontOf(el){
        var cs = getComputedStyle(el);
        return cs.fontSize + '/' + cs.fontWeight;
      }
      return Array.from(row.querySelectorAll('td')).map(function(td, i){
        var cell = td.querySelector('.cell');
        var btn = cell ? cell.querySelector('.grading-action') : null;
        var inner = btn || (cell && cell.firstElementChild);
        return { i: i, font: fontOf(inner || td) };
      });
    })()`);
    check('GR.1f 表格正文字体统一（前 5 列 14px/600，按钮 13px/700）',
      !!cellFonts && cellFonts.length === 6
        && cellFonts.slice(0, 5).every(function(f){ return f.font === '14px/600'; })
        && cellFonts[5].font === '13px/700',
      JSON.stringify(cellFonts));
    const brief = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.grading-table tbody tr'));
      return rows.map(function(r){
        return {
          student: (r.querySelector('td:nth-child(1)') || {}).textContent,
          time: (r.querySelector('td:nth-child(2)') || {}).textContent,
          score: (r.querySelector('td:nth-child(4)') || {}).textContent,
          status: (r.querySelector('td:nth-child(5)') || {}).textContent,
          action: (r.querySelector('.grading-action') || {}).textContent,
        };
      });
    })()`);
    check('GR.1b 操作列显示「查看/批改」',
      brief.length === 1 && /查看\/批改/.test(brief[0].action || ''),
      JSON.stringify(brief[0] && brief[0].action));
    check('GR.1c 提交时间精确到秒',
      brief.length === 1 && /^\d{4}\/\d{1,2}\/\d{1,2}\s+\d{1,2}:\d{2}:\d{2}$/.test((brief[0].time || '').trim()),
      JSON.stringify(brief[0] && brief[0].time));
    check('GR.2 未批改时成绩列显示「待批改」',
      brief.length === 1 && /待批改/.test(brief[0].status || '') && /客观 5 分/.test(brief[0].score || ''),
      JSON.stringify(brief[0] && { status: brief[0].status, score: brief[0].score }));

    // 打开批改弹窗
    await cdp.eval(`(function(){
      var btn = document.querySelector('.grading-table .grading-action');
      if (btn) btn.click();
    })()`);
    const dialogReady = await waitFor(cdp, `!!document.querySelector('.grade-dialog .answer-review-item')`, 15000);
    check('GR.3 批改弹窗渲染题目回顾列表', dialogReady);

    await sleep(900); // 等弹窗过渡与自动定位滚动结束
    const briefBar = await cdp.eval(`(function(){
      var b = document.querySelector('.grade-dialog .grade-mode-brief');
      return b ? b.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('GR.3a 摘要栏显示题量与待评分数', /共 5 题/.test(briefBar) && /1 道主观题待评分/.test(briefBar), briefBar);

    const manualPainted = await painted(cdp, '.grade-dialog .manual-grade-row');
    check('GR.3b 评分行自动定位且真实绘制可见', !!(manualPainted.found && manualPainted.painted), JSON.stringify(manualPainted));

    // 填分 + 逐题评语 + 总评语
    const filled = await cdp.eval(`(function(){
      var row = document.querySelector('.grade-dialog .manual-grade-row');
      if (!row) return 'NO_ROW';
      var numInput = row.querySelector('.el-input-number input');
      if (!numInput) return 'NO_NUM_INPUT';
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(numInput, ${JSON.stringify(MANUAL_SCORE)});
      numInput.dispatchEvent(new Event('input', { bubbles: true }));
      numInput.dispatchEvent(new Event('change', { bubbles: true }));
      numInput.dispatchEvent(new Event('blur', { bubbles: true }));
      var comment = row.querySelector('input[placeholder="本题评语（选填）"]');
      if (comment) {
        setter.call(comment, ${JSON.stringify(MANUAL_COMMENT)});
        comment.dispatchEvent(new Event('input', { bubbles: true }));
      }
      var ta = document.querySelector('.grade-dialog .el-textarea__inner');
      if (ta) {
        var tsetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        tsetter.call(ta, ${JSON.stringify(OVERALL_COMMENT)});
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return 'FILLED';
    })()`);
    check('GR.3c 可填入主观题分数/逐题评语/总评语', filled === 'FILLED', filled);
    await sleep(400);

    // GR.3d 批改弹窗：学生答案附带选项内容；简答题标签为「参考答案」
    const dialogAnswers = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.grade-dialog .answer-review-item'));
      return items.map(function(it){
        return {
          student: (it.querySelector('.student-answer') || {}).textContent,
          correctLine: (it.querySelector('.correct-answer') || {}).textContent,
        };
      });
    })()`);
    check('GR.3d 批改弹窗学生答案附带选项内容',
      dialogAnswers.length === 5 && /C\.完全无法通信/.test((dialogAnswers[0].student || '').replace(/\s+/g, '')),
      (dialogAnswers[0] && dialogAnswers[0].student || '').trim());
    check('GR.3e 批改弹窗简答题标签为「参考答案」',
      /参考答案：隔离广播域/.test((dialogAnswers[4].correctLine || '').replace(/\s+/g, '')),
      (dialogAnswers[4] && dialogAnswers[4].correctLine || '').trim().slice(0, 30));

    await cdp.shot('teacher-grade-dialog');

    // GR.4 单一按钮「提交批改」
    const footerBtns = await cdp.eval(`(function(){
      var footer = document.querySelector('.grade-dialog .dialog-footer');
      if (!footer) return [];
      return Array.from(footer.querySelectorAll('button')).map(function(b){ return b.textContent.trim(); });
    })()`);
    check('GR.4 弹窗底部仅「取消 + 提交批改」', JSON.stringify(footerBtns) === JSON.stringify(['取消', '提交批改']), JSON.stringify(footerBtns));
    await cdp.eval(`(function(){
      var footer = document.querySelector('.grade-dialog .dialog-footer');
      var btn = Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('提交批改') >= 0; });
      if (btn) btn.click();
    })()`);
    const graded = await waitFor(cdp, `(function(){
      var toasts = Array.from(document.querySelectorAll('.el-message__content')).map(function(t){ return t.textContent; });
      return toasts.some(function(t){ return t.indexOf('批改完成，成绩已发布') >= 0; });
    })()`, 15000);
    check('GR.4b 提交批改即发布（toast）', graded);

    // GR.5 抽屉刷新：直接「已发布」（无中间待发布状态）
    const afterGrade = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.grading-table tbody tr'));
      if (!rows.length) return false;
      var r = rows[0];
      // 列结构：td0=学生 td1=提交时间 td2=逾期 td3=得分 td4=成绩 td5=操作
      var status = (r.querySelectorAll('td')[4] || {}).textContent || '';
      return status.indexOf('已发布') >= 0;
    })()`, 15000);
    check('GR.5 批改后直接显示「已发布」（无中间待发布状态）', afterGrade);
    const scoreAfter = await cdp.eval(`(function(){
      var r = document.querySelector('.grading-table tbody tr');
      return r ? (r.querySelectorAll('td')[3] || {}).textContent : '';
    })()`);
    check('GR.5b 得分列显示最终成绩 8', /8/.test(scoreAfter || ''), (scoreAfter || '').trim());
    await cdp.shot('teacher-submissions-released');

    // ========== 阶段 C：学生端查看最终结果 ==========
    log('===== 阶段 C：学生端查看最终结果 =====');
    await login(cdp, '20249999', PW);
    await openStudentResult();

    const stuStatus = await cdp.eval(`(function(){
      // 结果页为工作区详情视图（detailMode 整体替换列表），徽章在 workspace-header
      var status = document.querySelector('.workspace-header .student-status');
      return status ? status.textContent.trim() : '';
    })()`);
    check('ST.1 状态徽章显示「已发布 8 分」', /已发布 8 分/.test(stuStatus || ''), stuStatus);

    const viewReady = await waitFor(cdp, `!!document.querySelector('.result-summary')`, 15000);
    check('ST.2 结果页显示总得分卡片', viewReady);
    const summary = await cdp.eval(`(function(){
      var s = document.querySelector('.result-summary');
      return s ? s.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('ST.2b 得分卡片显示 8/30', /8/.test(summary) && /30/.test(summary), summary);

    const finalItems = await cdp.eval(`(function(){
      var list = Array.from(document.querySelectorAll('.answer-result-item'));
      return list.map(function(item){
        return {
          correct: !!item.querySelector('.correct-answer'),
          analysis: !!item.querySelector('.answer-analysis'),
          scoreRow: (item.querySelector('.result-score-row') || {}).textContent,
          comment: (item.querySelector('.answer-comment') || {}).textContent,
        };
      });
    })()`);
    check('ST.3 主观题显示得分', /得分 3 分/.test(finalItems[4].scoreRow || ''), (finalItems[4].scoreRow || '').trim());
    check('ST.3b 逐题评语可见', /再组织一下语言/.test(finalItems[4].comment || ''), (finalItems[4].comment || '').trim());
    const overall = await cdp.eval(`(function(){
      var c = document.querySelector('.teacher-comment');
      return c ? c.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('ST.3c 作业总评语可见', /整体完成不错/.test(overall), overall.slice(0, 50));
    await cdp.shot('student-result-view');

    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('ST.4 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
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
