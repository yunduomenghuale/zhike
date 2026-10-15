#!/usr/bin/env node
/**
 * 考试三项需求 E2E 视觉验证（CDP 真实浏览器）
 *
 *   T1 教师监控实时更新：抽屉内「每 5 秒自动刷新」提示 + 手动刷新按钮；
 *      等待 6 秒「更新于」时间戳变化（轮询真实发生）
 *   T2 考试统计页：总览卡片、总分分布图、逐题统计表（含选项分布展开）、
 *      学生排名表、筛选条件各自归属列表（题型归题目卡 .question-filters，
 *      状态/成绩/搜索归学生卡 .rank-filters）、常驻吸顶返回栏、返回考试列表
 *   T3 学生导航修复：课程空间 → 我的考试 → 查看成绩，导航栏保持课程内部
 *      （.course-rail 存在、非默认布局）；回看页常驻吸顶返回栏；
 *      返回考试列表后仍恢复课程内导航
 *
 * 运行：node test/e2e/exam-features-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9225;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-features';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const EXAM_ID = 25;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }
      }, 35000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
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

async function waitFor(cdp, expr, timeout = 25000) {
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
    // 登录/注册两个表单同时渲染在 DOM 中，选择器必须限定在登录表单容器内
    var box = document.querySelector('.split-auth__form-box--login');
    function setVal(sel, v){
      var el = box.querySelector(sel);
      if(!el) return;
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    setVal('.split-auth__form-box--login input[placeholder="请输入用户名"]', ${JSON.stringify(username)});
    setVal('.split-auth__form-box--login input[placeholder="请输入密码"]', ${JSON.stringify(password)});
    var btn = box.querySelector('.auth-submit');
    if (btn) btn.click();
  })()`);
  const ok = await waitFor(cdp, `location.pathname === '/dashboard' || location.pathname === '/'`, 30000);
  if (!ok) throw new Error('登录失败: ' + username);
}

// 页面内 fetch（带 token、解包统一响应）
async function apiGet(cdp, url) {
  return cdp.eval(`(async function(){
    const token = localStorage.getItem('access_token');
    const res = await fetch(${JSON.stringify(url)}, { headers: { Authorization: 'Bearer ' + token } });
    const json = await res.json();
    return json.data ?? json;
  })()`);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* reuse */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank',
  ], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* not ready */ }
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome devtools 端口未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  return { cdp, chrome };
}

// 点击考试列表中某考试的指定按钮
// 列表标题显示的是考试「名称」而非 ID，先经 API 反查名称再按文本定位；
// 同时兼容教师端（article.exam-list-card + .exam-card-title）与
// 学生端（article.exam-row + .exam-title）两种列表结构
async function clickExamAction(cdp, examId, btnText) {
  let examName = null;
  try {
    const exams = await apiGet(cdp, '/api/exams/');
    const rows = exams.results ?? exams;
    const exam = rows.find((r) => r.id === examId);
    examName = exam ? String(exam.name) : null;
  } catch { /* 回退按 ID 文本匹配 */ }
  return cdp.eval(`(function(){
    var containers = Array.from(document.querySelectorAll('.exam-list-card, .exam-row, .exam-card, article'));
    var row = containers.find(function(el){
      var t = el.querySelector('.exam-card-title, .exam-title, .exam-name');
      return t && t.textContent.trim() === ${JSON.stringify(examName || String(examId))};
    });
    if (!row) return 'ROW_NOT_FOUND';
    var btn = Array.from(row.querySelectorAll('button')).find(function(b){
      return b.textContent.trim().includes(${JSON.stringify(btnText)});
    });
    if (!btn) return 'BTN_NOT_FOUND';
    btn.click();
    return 'CLICKED';
  })()`);
}

(async () => {
  const { cdp, chrome } = await launchChrome();
  try {
    // ========== T1 教师监控：实时刷新 + 手动刷新 ==========
    await login(cdp, 't101', 'pass1234');
    await cdp.navigate(BASE + '/teacher/exams');
    await waitFor(cdp, `!!document.querySelector('.exam-list-card .exam-card-title')`, 20000);
    const monitorClicked = await clickExamAction(cdp, EXAM_ID, '监控');
    check('T1.1 打开监控抽屉', monitorClicked === 'CLICKED', monitorClicked);
    const drawerOk = await waitFor(cdp, `!!document.querySelector('.monitor-drawer .el-drawer__body') && document.querySelectorAll('.monitor-drawer .el-table__row').length > 0`, 15000);
    check('T1.2 监控抽屉加载出答卷行', drawerOk);

    const tipText = await cdp.eval(`(document.querySelector('.monitor-auto-tip')||{}).textContent || ''`);
    check('T1.3 显示「每 5 秒自动刷新」提示', tipText.includes('每 5 秒自动刷新'), tipText.trim());
    const hasRefreshBtn = await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.monitor-toolbar button'));
      return btns.some(function(b){ return b.textContent.trim() === '刷新'; });
    })()`);
    check('T1.4 手动刷新按钮存在', hasRefreshBtn);

    // 轮询验证：记录时间戳 → 等 6 秒 → 时间戳应变化
    const ts1 = await cdp.eval(`(document.querySelector('.monitor-auto-tip')||{}).textContent || ''`);
    await sleep(6500);
    const ts2 = await cdp.eval(`(document.querySelector('.monitor-auto-tip')||{}).textContent || ''`);
    check('T1.5 轮询自动刷新（6 秒后「更新于」时间戳变化）', ts1 !== ts2 && ts2.includes('更新于'), ts1.trim() + ' → ' + ts2.trim());

    // 手动刷新：点击后不报错且时间戳更新
    const beforeClick = await cdp.eval(`(document.querySelector('.monitor-auto-tip')||{}).textContent || ''`);
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.monitor-toolbar button'));
      var b = btns.find(function(x){ return x.textContent.trim() === '刷新'; });
      if (b) b.click();
    })()`);
    await sleep(1200);
    const afterClick = await cdp.eval(`(document.querySelector('.monitor-auto-tip')||{}).textContent || ''`);
    check('T1.6 手动刷新按钮可点击且数据刷新', afterClick.includes('更新于') && afterClick !== beforeClick, afterClick.trim());

    // ========== T2 考试统计页 ==========
    // 关闭抽屉，从列表点「考试统计」
    await cdp.eval(`(function(){
      var btn = document.querySelector('.monitor-drawer .el-drawer__close-btn');
      if (btn) btn.click();
    })()`);
    await sleep(600);
    const statsClicked = await clickExamAction(cdp, EXAM_ID, '考试统计');
    check('T2.1 列表点击「考试统计」进入统计页', statsClicked === 'CLICKED', statsClicked);
    const statsLoaded = await waitFor(cdp, `location.pathname === '/teacher/exams/${EXAM_ID}/stats' && !!document.querySelector('.exam-stats-page .stat-cards')`, 15000);
    check('T2.2 统计页加载（总览卡片出现）', statsLoaded);

    const cards = await cdp.eval(`(function(){
      return Array.from(document.querySelectorAll('.exam-stats-page .stat-card')).map(function(c){
        return { label: c.querySelector('.stat-label').textContent.trim(), value: c.querySelector('.stat-value').textContent.trim() };
      });
    })()`);
    const cardOf = (label) => (cards.find((c) => c.label.includes(label)) || {}).value;
    check('T2.3 总览卡片数值（应考2/交卷1/缺考1/均分17）',
      cardOf('应考人数') === '2' && cardOf('已交卷') === '1' && cardOf('缺考') === '1' && cardOf('平均分') === '17',
      JSON.stringify(cards));

    const distBars = await cdp.eval(`document.querySelectorAll('.exam-stats-page .dist-col').length`);
    check('T2.4 总分分布图（5 个分段列）', distBars === 5, 'cols=' + distBars);

    const qRows = await cdp.eval(`(function(){
      var tables = document.querySelectorAll('.exam-stats-page .el-table');
      // 题目表：第一个表
      var t = tables[0];
      return t ? t.querySelectorAll('.el-table__row').length : -1;
    })()`);
    check('T2.5 题目统计表 6 行', qRows === 6, 'rows=' + qRows);

    // 展开第一行看选项分布
    await cdp.eval(`(function(){
      var expand = document.querySelector('.exam-stats-page .el-table .el-table__expand-icon');
      if (expand) expand.click();
    })()`);
    await sleep(600);
    const optDist = await cdp.eval(`(function(){
      var rows = document.querySelectorAll('.exam-stats-page .opt-dist-row');
      return Array.from(rows).map(function(r){
        // .opt-dist-key 文本形如「D.」，去掉尾部句点
        return r.querySelector('.opt-dist-key').textContent.trim().replace(/\\.$/, '') + ':' + r.querySelector('.opt-dist-count').textContent.trim();
      });
    })()`);
    check('T2.6 选项分布展开（Q1：D 1 人，正确答案 B）',
      optDist.length === 4 && optDist.some((x) => x === 'D:1 人') && optDist.some((x) => x === 'B:0 人'),
      optDist.join(' '));

    const rankRows = await cdp.eval(`(function(){
      var tables = document.querySelectorAll('.exam-stats-page .el-table');
      var t = tables[tables.length - 1];
      return Array.from(t.querySelectorAll('.el-table__row')).map(function(r){
        var cells = r.querySelectorAll('.el-table__cell');
        return { rank: cells[0].textContent.trim(), name: cells[1].textContent.trim(), status: cells[2].textContent.trim(), total: cells[4].textContent.trim() };
      });
    })()`);
    check('T2.7 学生排名表（多班学生第1名17分、单班学生缺考）',
      rankRows.length === 2 && rankRows[0].rank === '1' && rankRows[0].name === '多班学生' && rankRows[0].total === '17'
        && rankRows[1].name === '单班学生' && rankRows[1].status === '缺考',
      JSON.stringify(rankRows));

    // 筛选：状态=缺考 → 只剩 1 人（状态筛选现位于学生排名卡头部 .rank-filters）
    await cdp.eval(`(function(){
      var sel = document.querySelectorAll('.rank-filters .el-select')[0];
      sel.querySelector('.el-select__wrapper').click();
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.el-select__popper .el-select-dropdown__item'));
      var it = items.find(function(x){ return x.textContent.trim() === '缺考'; });
      if (it) it.click();
    })()`);
    await sleep(500);
    const filteredRows = await cdp.eval(`(function(){
      var tables = document.querySelectorAll('.exam-stats-page .el-table');
      var t = tables[tables.length - 1];
      return t.querySelectorAll('.el-table__row').length;
    })()`);
    check('T2.8 状态筛选「缺考」→ 排名表仅 1 行', filteredRows === 1, 'rows=' + filteredRows);

    // 题型筛选：单选题 → 题目表 2 行（题型筛选现位于题目统计卡头部 .question-filters）
    await cdp.eval(`(function(){
      var sel = document.querySelectorAll('.rank-filters .el-select')[0];
      sel.querySelector('.el-select__wrapper').click();
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.el-select__popper .el-select-dropdown__item'));
      var it = items.find(function(x){ return x.textContent.trim() === '全部状态'; });
      if (it) it.click();
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){
      var sel = document.querySelectorAll('.question-filters .el-select')[0];
      sel.querySelector('.el-select__wrapper').click();
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.el-select__popper .el-select-dropdown__item'));
      var it = items.find(function(x){ return x.textContent.trim() === '单选题'; });
      if (it) it.click();
    })()`);
    await sleep(500);
    const qFiltered = await cdp.eval(`document.querySelectorAll('.exam-stats-page .el-table')[0].querySelectorAll('.el-table__row').length`);
    check('T2.9 题型筛选「单选题」→ 题目表 2 行', qFiltered === 2, 'rows=' + qFiltered);

    // 常驻返回栏：课程空间头部被隐藏/滚动后仍可返回
    const statsBackBar = await cdp.eval(`(function(){
      var bar = document.querySelector('.exam-stats-page .page-back-bar');
      if (!bar) return 'NO_BAR';
      var btn = bar.querySelector('button');
      var pos = getComputedStyle(bar).position;
      return (btn && btn.textContent.includes('返回考试列表') ? 'BTN_OK' : 'BTN_MISSING') + ' pos=' + pos;
    })()`);
    check('T2.10 统计页常驻返回栏（sticky 吸顶）', statsBackBar === 'BTN_OK pos=sticky', statsBackBar);

    await cdp.shot('exam-stats-page');
    // 返回考试列表（点击常驻返回栏按钮）
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.exam-stats-page .page-back-bar button'));
      var b = btns.find(function(x){ return x.textContent.includes('返回考试列表'); });
      if (b) b.click();
    })()`);
    await sleep(800);
    check('T2.11 返回考试列表', (await cdp.eval('location.pathname')) === '/teacher/exams');

    // ========== T3 学生导航修复 ==========
    await login(cdp, '20249999', 'A0987654');
    // 找到 exam 25 所属课程 → 课程空间考试列表
    const courseId = await (async () => {
      const exams = await apiGet(cdp, '/api/exams/');
      const rows = exams.results ?? exams;
      const exam = rows.find((r) => r.id === EXAM_ID);
      return exam ? Number(exam.course) : null;
    })();
    check('T3.1 定位学生课程（exam 25 所属课程空间）', !!courseId, 'courseId=' + courseId);

    await cdp.navigate(BASE + '/student/courses/' + courseId + '/exams');
    await waitFor(cdp, `!!document.querySelector('.exam-row .exam-title')`, 20000);
    const viewClicked = await clickExamAction(cdp, EXAM_ID, '查看成绩');
    check('T3.2 点击「查看成绩」', viewClicked === 'CLICKED', viewClicked);
    await sleep(1500);
    const reviewUrl = await cdp.eval('location.pathname');
    const hasCourseRail = await cdp.eval(`!!document.querySelector('.course-rail')`);
    const hasDefaultLayout = await cdp.eval(`!!document.querySelector('.layout.app-page')`);
    check('T3.3 回看页停留在课程空间路由', reviewUrl === `/student/courses/${courseId}/exams/${EXAM_ID}/review`, reviewUrl);
    check('T3.4 导航栏为课程内部导航（非默认导航）', hasCourseRail && !hasDefaultLayout,
      'courseRail=' + hasCourseRail + ' defaultLayout=' + hasDefaultLayout);

    // 常驻返回栏：课程空间头部被隐藏/滚动后仍可返回
    const reviewBackBar = await cdp.eval(`(function(){
      var bar = document.querySelector('.exam-review-page .page-back-bar');
      if (!bar) return 'NO_BAR';
      var btn = bar.querySelector('button');
      var pos = getComputedStyle(bar).position;
      return (btn && btn.textContent.includes('返回考试列表') ? 'BTN_OK' : 'BTN_MISSING') + ' pos=' + pos;
    })()`);
    check('T3.5 回看页常驻返回栏（sticky 吸顶）', reviewBackBar === 'BTN_OK pos=sticky', reviewBackBar);

    // 成绩卡应显示乱序提示（S4 功能仍在）
    const shuffleTip = await cdp.eval(`(document.querySelector('.exam-review-page .shuffle-tip')||{}).textContent || ''`);
    check('T3.6 回看页显示选项乱序提示', shuffleTip.includes('选项乱序'), shuffleTip.trim().slice(0, 30));

    await cdp.shot('exam-review-back-bar');

    // 返回考试列表 → 仍回课程空间考试列表且课程导航保持（点击常驻返回栏按钮）
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.exam-review-page .page-back-bar button'));
      var b = btns.find(function(x){ return x.textContent.includes('返回考试列表'); });
      if (b) b.click();
    })()`);
    await sleep(1000);
    const backUrl = await cdp.eval('location.pathname');
    const backRail = await cdp.eval(`!!document.querySelector('.course-rail')`);
    check('T3.7 返回考试列表回到课程空间且课程导航恢复',
      backUrl === `/student/courses/${courseId}/exams` && backRail,
      backUrl + ' courseRail=' + backRail);

    await cdp.shot('exam-student-course-nav');
    console.log('截图: exam-stats-page.png / exam-student-course-nav.png');
  } finally {
    chrome.kill();
  }
  const failed = results.filter((r) => !r.ok);
  console.log('----');
  console.log(results.length + ' 项断言，通过 ' + (results.length - failed.length) + '，失败 ' + failed.length);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('ERROR:', e.message); process.exit(2); });
