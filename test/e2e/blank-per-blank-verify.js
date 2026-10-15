#!/usr/bin/env node
/**
 * 填空题「按空单独赋分」全链路实测（对应用户第十一轮需求）
 *
 * 验证点：
 *   QB.1  题库新建填空题：每行「第N空 + 答案 + 分值」；总分直填框隐藏，
 *         改显「合计 9 分（按空自动累计）」
 *   QB.2  创建并发布后，列表分值显示 Σ空分（2+3+4 → 9 分）
 *   QB.3  重新编辑回填每空答案与分值
 *   QB.4  清空某空分值后保存被前端拦截（toast 提示），已发布题目不受影响
 *   QB.5  API 播种作业后，学生部分作答（对 2 空/错 1 空）→ 提交即自动出分 5/9，
 *         且提交后直接停留在该作业结果页（不回列表）
 *   QB.6  学生结果页徽章显示「部分正确 · 得分 5 分」
 *   QB.7  正确答案按空文本展示（封装；继承；多态），无 [object Object]
 *   QB.8  教师批改弹窗显示「5 / 9 分」与「自动判定：部分正确」
 *   QB.9  清理：测试作业与题目经 API 删除，无残留
 *   QB.10 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动；t101 有课程与班级，学生 20249999 在该班级。
 * 运行：node test/e2e/blank-per-blank-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const TEACHER = 't101';
const STUDENT = '20249999';
const STEM = 'E2E填空按空赋分测试（自动创建，可删）';
const HW_TITLE = '填空题按空赋分E2E';
const BLANKS = [
  { text: '封装', score: '2' },
  { text: '继承', score: '3' },
  { text: '多态', score: '4' },
];
// 学生作答：前两空对、第三空错 → 期望得 2+3=5 分（满分 9）
const STU_ANSWER = ['封装', '继承', '答错'];
const EXPECT_EARNED = 5;
const EXPECT_TOTAL = 9;

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-qb-e2e/run-${RUN_ID}`;

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

// 在页面上下文中调用后端 API（复用 localStorage 里的 access_token），返回 JSON
async function apiCall(cdp, method, url, body) {
  return cdp.eval(`(async function(){
    var tok = localStorage.getItem('access_token') || '';
    var opt = { method: ${JSON.stringify(method)}, headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' } };
    if (${JSON.stringify(body === undefined ? null : body)} !== null) opt.body = JSON.stringify(${JSON.stringify(body === undefined ? null : body)});
    var r = await fetch(${JSON.stringify(url)}, opt);
    var text = await r.text();
    try { return JSON.parse(text); } catch (e) { return { __raw: text, __status: r.status }; }
  })()`);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

// 打开题目对话框里的题型下拉并选择
async function pickQtype(cdp, label) {
  await cdp.eval(`(function(){
    var sel = document.querySelector('.question-form-dialog .question-type-field .el-select');
    var input = sel.querySelector('input');
    input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    input.click();
  })()`);
  await sleep(500);
  return cdp.eval(`(function(){
    var opts = Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(function(o){ return o.offsetParent !== null; });
    var target = opts.find(function(o){ return o.textContent.trim() === ${JSON.stringify(label)}; });
    if (target) { target.click(); return 'PICKED'; }
    return 'NOT_FOUND:' + opts.map(function(o){ return o.textContent.trim(); }).join(',');
  })()`);
}

// 给第 i 个填空行填答案与分值（答案取非分值输入框）
async function fillBlankRow(cdp, index, text, score) {
  return cdp.eval(`(function(){
    var rows = Array.from(document.querySelectorAll('.question-form-dialog .blank-row'));
    var row = rows[${index}];
    if (!row) return 'NO_ROW';
    var scoreInput = row.querySelector('.blank-score-input input');
    var answerInput = Array.from(row.querySelectorAll('input')).find(function(inp){ return !inp.closest('.blank-score-input'); });
    if (!answerInput || !scoreInput) return 'NO_INPUT';
    function setVal(el, v){
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    setVal(answerInput, ${JSON.stringify(text)});
    setVal(scoreInput, ${JSON.stringify(score)});
    return 'FILLED';
  })()`);
}

async function readBlankRows(cdp) {
  return cdp.eval(`(function(){
    var rows = Array.from(document.querySelectorAll('.question-form-dialog .blank-row'));
    return rows.map(function(row){
      var scoreInput = row.querySelector('.blank-score-input input');
      var answerInput = Array.from(row.querySelectorAll('input')).find(function(inp){ return !inp.closest('.blank-score-input'); });
      return {
        idx: (row.querySelector('.blank-idx') || {}).textContent,
        answer: answerInput ? answerInput.value : null,
        score: scoreInput ? scoreInput.value : null,
      };
    });
  })()`);
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);

  try {
    log('===== 填空题按空赋分：题库编辑器 =====');
    await login(cdp, TEACHER, PW);
    await goto('/teacher/questions');

    const courseReady = await waitFor(cdp, `(function(){
      var btn = Array.from(document.querySelectorAll('.q-toolbar-actions button')).find(function(b){ return b.textContent.indexOf('新建题目') >= 0; });
      return !!btn;
    })()`, 20000);
    check('QB.0 题库页加载且课程已自动选中', courseReady);

    // 清理上一轮残留（幂等）：按题干搜删旧题、按标题搜删旧作业
    const staleQ = await apiCall(cdp, 'GET', `/api/questions/?search=${encodeURIComponent(STEM)}`);
    const staleQuestions = ((staleQ.data || {}).results) || (staleQ.results) || [];
    for (const q of staleQuestions) {
      if ((q.stem || '').indexOf(STEM) >= 0) await apiCall(cdp, 'DELETE', `/api/questions/${q.id}/`);
    }
    const staleHw = await apiCall(cdp, 'GET', `/api/homeworks/?search=${encodeURIComponent(HW_TITLE)}`);
    const staleHomeworks = ((staleHw.data || {}).results) || (staleHw.results) || [];
    for (const h of staleHomeworks) {
      if ((h.title || '').indexOf(HW_TITLE) >= 0) await apiCall(cdp, 'DELETE', `/api/homeworks/${h.id}/`);
    }
    log('--- 残留清理完成：题目 ' + staleQuestions.length + ' 条、作业 ' + staleHomeworks.length + ' 条 ---');

    // 打开新建题目对话框并切到填空题
    await cdp.eval(`(function(){
      var btn = Array.from(document.querySelectorAll('.q-toolbar-actions button')).find(function(b){ return b.textContent.indexOf('新建题目') >= 0; });
      if (btn) btn.click();
    })()`);
    const dialogReady = await waitFor(cdp, `!!document.querySelector('.question-form-dialog .question-creation-form')`, 15000);
    check('QB.1a 新建题目对话框打开', dialogReady);
    const picked = await pickQtype(cdp, '填空题');
    check('QB.1b 题型切换为填空题', picked === 'PICKED', picked);
    await sleep(400);

    // 编辑器结构：每行「第N空 + 答案 + 分值」，默认 1 行
    const rowStruct = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.question-form-dialog .blank-row'));
      if (!rows.length) return { count: 0 };
      var row = rows[0];
      return {
        count: rows.length,
        idx: (row.querySelector('.blank-idx') || {}).textContent,
        hasScore: !!row.querySelector('.blank-score-input input'),
      };
    })()`);
    check('QB.1c 填空题答案编辑器每行带分值输入', rowStruct.count === 1 && rowStruct.hasScore && rowStruct.idx === '第1空', JSON.stringify(rowStruct));

    // 添加到 3 个空并逐空填答案+分值
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.question-form-dialog button')).filter(function(b){ return b.textContent.indexOf('添加空') >= 0; });
      if (btns[0]) btns[0].click();
    })()`);
    await sleep(200);
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.question-form-dialog button')).filter(function(b){ return b.textContent.indexOf('添加空') >= 0; });
      if (btns[0]) btns[0].click();
    })()`);
    await sleep(200);
    const rowCount = await cdp.eval(`document.querySelectorAll('.question-form-dialog .blank-row').length`);
    check('QB.1d 添加空至 3 行', rowCount === 3, 'rows=' + rowCount);
    const fills = [];
    for (let i = 0; i < BLANKS.length; i++) {
      fills.push(await fillBlankRow(cdp, i, BLANKS[i].text, BLANKS[i].score));
      await sleep(120);
    }
    check('QB.1e 逐空填入答案与分值（2/3/4）', fills.every((f) => f === 'FILLED'), fills.join(','));

    // 合计展示 + 总分直填框隐藏
    const totalInfo = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.question-form-dialog .el-form-item'));
      var hit = items.find(function(it){ return (it.querySelector('.el-form-item__label') || {}).textContent === '分值/难度'; });
      if (!hit) return { found: false };
      var total = hit.querySelector('.blank-total-score');
      return {
        found: true,
        totalText: total ? total.textContent.replace(/\\s+/g, ' ').trim() : '',
        hasNumberInput: !!hit.querySelector('.el-input-number'),
      };
    })()`);
    check('QB.1f 填空题隐藏总分直填、显示合计（按空自动累计）',
      !!totalInfo.found && !totalInfo.hasNumberInput && /合计\s*9\s*分/.test(totalInfo.totalText) && /按空自动累计/.test(totalInfo.totalText),
      JSON.stringify(totalInfo));

    // 题干 + 章节 + 创建并发布
    await cdp.eval(`(function(){
      var ta = document.querySelector('.question-form-dialog textarea[placeholder="请输入题干"]');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, ${JSON.stringify(STEM)});
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(200);
    await cdp.eval(`(function(){
      var sel = document.querySelector('.question-form-dialog .form-row-grow .el-select');
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
    check('QB.2a 选择所属章节', catalogPicked === 'PICKED', catalogPicked);
    await sleep(400);
    await cdp.eval(`(function(){
      var footer = document.querySelector('.question-form-dialog .creation-dialog-footer');
      var btn = Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('创建并发布') >= 0; });
      if (btn) btn.click();
    })()`);
    const created = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.q-row'));
      return !document.querySelector('.table-skeleton') && rows.some(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
    })()`, 15000);
    check('QB.2 创建并发布后题目出现在列表', created);

    // 列表分值 = Σ空分
    const listScore = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.q-row'));
      var row = rows.find(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
      if (!row) return null;
      var s = row.querySelector('.q-score');
      return s ? s.textContent.trim() : '';
    })()`);
    check('QB.2b 列表分值显示 Σ空分（9 分）', /^9(\.0)?\s*分$/.test(listScore || ''), listScore);

    // 取题目 id（供 API 播种作业）——POST 与搜索存在竞态，轮询直至可查；
    // 且必须确认加载结束（无骨架屏）后行仍在，排除 load() 未完成时抓到旧 DOM 的瞬时状态
    let targetQ = null;
    for (let i = 0; i < 40; i++) {
      const qList = await apiCall(cdp, 'GET', `/api/questions/?search=${encodeURIComponent(STEM)}`);
      const qResults = ((qList.data || {}).results) || (qList.results) || [];
      targetQ = qResults
        .filter((q) => (q.stem || '').indexOf(STEM) >= 0)
        .sort((a, b) => b.id - a.id)[0] || null;
      if (targetQ) break;
      await sleep(250);
    }
    const rowStable = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.q-row'));
      return !document.querySelector('.table-skeleton') && rows.some(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
    })()`, 10000);
    check('QB.2c API 可查到新题（answer.blanks 为对象数组）', !!targetQ && Array.isArray(targetQ.answer?.blanks) && typeof targetQ.answer.blanks[0] === 'object' && Number(targetQ.score) === 9 && rowStable,
      targetQ ? JSON.stringify({ id: targetQ.id, score: targetQ.score, blanks: targetQ.answer?.blanks, rowStable }) : 'NOT_FOUND');

    // 重新编辑：回填每空答案与分值（行可能因 load() 骨架屏瞬时消失，先等稳定再点）
    let reopened = false;
    for (let attempt = 0; attempt < 3 && !reopened; attempt++) {
      await waitFor(cdp, `(function(){
        var rows = Array.from(document.querySelectorAll('.q-row'));
        return !document.querySelector('.table-skeleton') && rows.some(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
      })()`, 10000);
      const clickRes = await cdp.eval(`(function(){
        var rows = Array.from(document.querySelectorAll('.q-row'));
        var row = rows.find(function(r){ return (r.querySelector('.q-stem') || {}).textContent.indexOf(${JSON.stringify(STEM)}) >= 0; });
        if (!row) return { ok: false, why: 'NO_ROW', rows: rows.length, stems: rows.map(function(r){ return (r.querySelector('.q-stem') || {}).textContent; }).slice(0, 5), skeleton: !!document.querySelector('.table-skeleton'), href: location.href };
        var btn = Array.from(row.querySelectorAll('.q-action-group button')).find(function(b){ return b.textContent.indexOf('编辑') >= 0; });
        if (!btn) return { ok: false, why: 'NO_BTN' };
        btn.click();
        return { ok: true };
      })()`);
      if (clickRes && clickRes.ok) {
        reopened = await waitFor(cdp, `!!document.querySelector('.question-form-dialog .question-creation-form')`, 8000);
      } else {
        log('--- QB.3 点击编辑失败: ' + JSON.stringify(clickRes) + ' ---');
        await sleep(500);
      }
    }
    check('QB.3-pre 重新打开编辑对话框', reopened);
    if (!reopened) throw new Error('无法重新打开编辑对话框');
    await sleep(600);
    const rowsRead = await readBlankRows(cdp);
    const expectRead = BLANKS.map((b, i) => ({ idx: `第${i + 1}空`, answer: b.text, score: b.score }));
    check('QB.3 重新编辑回填每空答案与分值', JSON.stringify(rowsRead) === JSON.stringify(expectRead), JSON.stringify(rowsRead));

    // 前端校验：清空某空分值 → 保存被拦截
    await fillBlankRow(cdp, 0, BLANKS[0].text, '');
    await sleep(200);
    await cdp.eval(`(function(){
      var footer = document.querySelector('.question-form-dialog .creation-dialog-footer');
      var btn = Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('保存修改') >= 0; });
      if (btn) btn.click();
    })()`);
    const blocked = await waitFor(cdp, `(function(){
      var toasts = Array.from(document.querySelectorAll('.el-message__content')).map(function(t){ return t.textContent; });
      return toasts.some(function(t){ return t.indexOf('每个空的分值必须大于 0') >= 0; });
    })()`, 8000);
    check('QB.4 清空某空分值后保存被前端拦截', blocked);
    const stillOpen = await cdp.eval(`!!document.querySelector('.question-form-dialog .question-creation-form')`);
    check('QB.4b 拦截后对话框保持打开', stillOpen);
    await cdp.shot('blank-per-blank-editor');

    // 关闭对话框（不保存，题目保持已发布状态）
    await cdp.eval(`(function(){
      var btn = document.querySelector('.question-form-dialog .creation-dialog-close');
      if (btn) btn.click();
    })()`);
    await sleep(400);

    // ---------------- API 播种作业（教师 token） ----------------
    log('===== API 播种作业（含该填空题，卷面 9 分） =====');
    const classes = await apiCall(cdp, 'GET', '/api/classes/');
    const classList = ((classes.data || {}).results) || (classes.results) || [];
    let pick = null;
    for (const c of classList) {
      const members = await apiCall(cdp, 'GET', `/api/class-students/?classroom=${c.id}`);
      const mList = ((members.data || {}).results) || (members.results) || [];
      const hasStudent = mList.some((m) => String(m.username || m.student_username || '') === STUDENT);
      const courses = c.courses || [];
      if (hasStudent && courses.length) { pick = { classroom: c.id, course: courses[0] }; break; }
    }
    check('QB.5a 定位到含学生的班级与关联课程', !!pick, JSON.stringify(pick));
    if (!pick) throw new Error('未找到含学生 ' + STUDENT + ' 且关联课程的班级');

    const hwCreated = await apiCall(cdp, 'POST', '/api/homeworks/', {
      title: HW_TITLE,
      description: '填空题按空赋分 E2E（自动创建，可删）',
      start_time: null,
      deadline: null,
      status: 'published',
      course: pick.course,
      classroom: pick.classroom,
      mode: 'questions',
      question_items: [{ question: targetQ.id, score: EXPECT_TOTAL }],
    });
    const hwId = (hwCreated.data || {}).id;
    check('QB.5 作业发布成功（题库选题，卷面 9 分）', hwCreated.code === 0 && !!hwId, JSON.stringify({ code: hwCreated.code, id: hwId, msg: hwCreated.message }));

    // ---------------- 学生端：部分作答 ----------------
    log('===== 学生端：部分作答（对 2 空/错 1 空） =====');
    await login(cdp, STUDENT, PW);
    await goto('/student/homework');
    const listReady = await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.trim() === ${JSON.stringify(HW_TITLE)}; })`, 20000);
    check('QB.5b 学生作业列表加载出测试作业', listReady);

    const rowInfo = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.student-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.student-row-title');
        return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
      });
      if (!row) return null;
      var btn = row.querySelector('.student-action-btn');
      return { btn: btn ? btn.textContent.trim() : '' };
    })()`);
    let justSubmitted = false
    if (rowInfo && /查看作业/.test(rowInfo.btn)) {
      await cdp.eval(`(function(){
        var rows = Array.from(document.querySelectorAll('.student-row'));
        var row = rows.find(function(r){
          var t = r.querySelector('.student-row-title');
          return t && t.textContent.trim() === ${JSON.stringify(HW_TITLE)};
        });
        var btn = row.querySelector('.student-action-btn');
        if (btn) btn.click();
      })()`);
      const cardsReady = await waitFor(cdp, `(function(){
        var cards = Array.from(document.querySelectorAll('.homework-question-card'));
        return cards.length >= 1 && cards[0].querySelectorAll('.blank-answer-list .el-input__inner').length === 3;
      })()`, 20000);
      check('QB.5c 答题页渲染 3 个填空输入框', cardsReady);

      const filled = await cdp.eval(`(function(){
        var cards = Array.from(document.querySelectorAll('.homework-question-card'));
        var inputs = cards[0].querySelectorAll('.blank-answer-list .el-input__inner');
        var vals = ${JSON.stringify(STU_ANSWER)};
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        inputs.forEach(function(inp, i){
          setter.call(inp, vals[i] !== undefined ? vals[i] : '');
          inp.dispatchEvent(new Event('input', { bubbles: true }));
        });
        return inputs.length;
      })()`);
      check('QB.5d 填入「封装/继承/答错」（前两空对、第三空错）', filled === 3, 'inputs=' + filled);
      await sleep(400);

      await cdp.eval(`(function(){
        var footer = document.querySelector('.workspace-footer');
        var btn = footer ? Array.from(footer.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('确认提交') >= 0; }) : null;
        if (btn) btn.click();
      })()`);
      const submitToast = await waitFor(cdp, `(function(){
        var toasts = Array.from(document.querySelectorAll('.el-message__content')).map(function(t){ return t.textContent; });
        return toasts.some(function(t){ return t.indexOf('提交成功') >= 0; });
      })()`, 20000);
      check('QB.5e 提交成功（纯客观题自动批改并发布）', submitToast);
      justSubmitted = true
      await sleep(1200);
    } else {
      log('--- 检测到已提交（重复运行），跳过提交阶段 ---');
    }

    // 结果页验证
    if (justSubmitted) {
      // 新行为：提交后直接停留在该作业结果页，无需返回列表再点入
      const autoView = await waitFor(cdp, `!!document.querySelector('.result-summary')`, 15000);
      check('QB.6a 提交后直接进入结果页（得分卡片）', autoView);
    } else {
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
      check('QB.6a 结果页显示得分卡片', viewReady);
    }
    const summary = await cdp.eval(`(function(){
      var s = document.querySelector('.result-summary');
      return s ? s.textContent.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    const m6b = summary.match(/本次得分\s*([\d.]+)\s*\/\s*([\d.]+)\s*分/);
    check('QB.6b 得分卡片显示 5/9（按空得分）',
      !!m6b && Math.abs(parseFloat(m6b[1]) - EXPECT_EARNED) < 1e-9 && Math.abs(parseFloat(m6b[2]) - EXPECT_TOTAL) < 1e-9,
      summary);

    const itemInfo = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.answer-result-item'));
      if (!items.length) return null;
      var it = items[0];
      return {
        myAnswer: (it.querySelector('.submitted-answer') || {}).textContent,
        correct: (it.querySelector('.correct-answer') || {}).textContent,
        scoreRow: (it.querySelector('.result-score-row') || {}).textContent,
      };
    })()`);
    const scoreRowClean = (itemInfo?.scoreRow || '').replace(/\s+/g, ' ').trim();
    const correctClean = (itemInfo?.correct || '').replace(/\s+/g, ' ').trim();
    check('QB.6 徽章显示「部分正确 · 得分 5 分」', /部分正确/.test(scoreRowClean) && /得分\s*5(?:\.0+)?\s*分/.test(scoreRowClean), scoreRowClean);
    check('QB.7 正确答案按空文本展示（封装；继承；多态），无 [object Object]',
      /封装；继承；多态/.test(correctClean) && correctClean.indexOf('[object Object]') < 0, correctClean);
    const myAnswerClean = (itemInfo?.myAnswer || '').replace(/\s+/g, ' ').trim();
    check('QB.7b 我的答案展示（封装；继承；答错）', /封装；继承；答错/.test(myAnswerClean), myAnswerClean);
    await cdp.shot('blank-per-blank-student-result');

    // ---------------- 教师端：批改弹窗 ----------------
    log('===== 教师端：批改弹窗核对 =====');
    await login(cdp, TEACHER, PW);
    await goto('/teacher/homework');
    const hwRowReady = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row, .data-row, tr'));
      return rows.some(function(r){ return r.textContent.indexOf(${JSON.stringify(HW_TITLE)}) >= 0; });
    })()`, 20000);
    check('QB.8a 教师作业列表加载出测试作业', hwRowReady);
    // 列表「批改」→ 打开提交抽屉（并非直接弹批改框）
    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      var row = rows.find(function(r){ return r.textContent.indexOf(${JSON.stringify(HW_TITLE)}) >= 0; });
      var btn = row ? Array.from(row.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('批改') >= 0; }) : null;
      if (btn) btn.click();
    })()`);
    const drawerReady = await waitFor(cdp, `!!document.querySelector('.grading-drawer .grading-table')`, 15000);
    check('QB.8a2 提交抽屉打开', drawerReady);
    const subRowReady = await waitFor(cdp, `(function(){
      var btns = Array.from(document.querySelectorAll('.grading-drawer .grading-action'));
      return btns.length >= 1;
    })()`, 15000);
    check('QB.8a3 抽屉内加载出学生提交记录', subRowReady);
    // 抽屉内第一条提交的「查看/批改」→ 批改弹窗
    await cdp.eval(`(function(){
      var btn = document.querySelector('.grading-drawer .grading-action');
      if (btn) btn.click();
    })()`);
    const gradeReady = await waitFor(cdp, `!!document.querySelector('.grade-dialog .answer-review-item')`, 15000);
    check('QB.8b 批改弹窗打开', gradeReady);
    const gradeInfo = await cdp.eval(`(function(){
      var it = document.querySelector('.grade-dialog .answer-review-item');
      if (!it) return null;
      return {
        head: (it.querySelector('.answer-review-head') || {}).textContent,
        correct: (it.querySelector('.correct-answer') || {}).textContent,
        tag: (it.querySelector('.el-tag') || {}).textContent,
      };
    })()`);
    const headClean = (gradeInfo?.head || '').replace(/\s+/g, ' ').trim();
    const tagClean = (gradeInfo?.tag || '').replace(/\s+/g, ' ').trim();
    const gradeCorrect = (gradeInfo?.correct || '').replace(/\s+/g, ' ').trim();
    check('QB.8 批改弹窗显示「5 / 9 分」', /5(?:\.0+)?\s*\/\s*9(?:\.0+)?\s*分/.test(headClean), headClean);
    check('QB.8c 批改弹窗判定徽章为「自动判定：部分正确」', /部分正确/.test(tagClean), tagClean);
    check('QB.8d 批改弹窗正确答案无 [object Object]', /封装；继承；多态/.test(gradeCorrect) && gradeCorrect.indexOf('[object Object]') < 0, gradeCorrect);
    await cdp.shot('blank-per-blank-teacher-grade');

    // ---------------- 清理 ----------------
    log('===== 清理测试数据 =====');
    const delHw = await apiCall(cdp, 'DELETE', `/api/homeworks/${hwId}/`);
    const delQ = await apiCall(cdp, 'DELETE', `/api/questions/${targetQ.id}/`);
    check('QB.9a 测试作业已删除', delHw.code === 0 || delHw.__status === 204, JSON.stringify(delHw));
    check('QB.9b 测试题目已删除', delQ.code === 0 || delQ.__status === 204, JSON.stringify(delQ));
    const afterQ = await apiCall(cdp, 'GET', `/api/questions/?search=${encodeURIComponent(STEM)}`);
    const afterList = ((afterQ.data || {}).results) || (afterQ.results) || [];
    check('QB.9c 无残留题目', !afterList.some((q) => (q.stem || '').indexOf(STEM) >= 0), 'remaining=' + afterList.length);

    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('QB.10 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
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
