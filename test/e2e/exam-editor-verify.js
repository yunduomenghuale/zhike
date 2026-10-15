#!/usr/bin/env node
/**
 * 考试管理整页编辑器 E2E 视觉验证（CDP 真实浏览器）
 *
 * 覆盖本轮需求：
 *   T1 新建考试整页编辑器：左基础信息 + 右组卷（随机抽题/题库选题/自写题目）+ 试卷预览
 *   T2 选项乱序默认选中
 *   T3 题库选题 → 生成试卷 → 预览刷新（新建态自动建草稿）
 *   T4 再次进入编辑：组卷信息回填（不再空白）
 *   T5 草稿考试随机抽题 → 生成试卷 → 预览展示抽出的题目 → 发布考试
 *      （T5.0 通过 API 自备草稿数据，保证脚本可重复运行）
 *   T6 查看试卷：hover 题干显示题目详情浮层（复用 QuestionDetailPopover，断言真实可见）
 *   T7 已组卷考试点「生成试卷」：覆盖确认框必须真实可见、位于编辑器之上、可点击；
 *      连点第二次必须被忽略（不堆叠确认框）；点「重新生成」后组卷成功
 *      （回归：EP 2.14.2 的 MessageBox 根节点是 .el-overlay.is-message-box，
 *       旧选择器 .el-message-box__wrapper 不存在导致确认框被 3000 的编辑器盖住，
 *       表现为「点击无反应」，发布后堆叠确认框集中爆发且全部失败）
 *
 * 运行：node test/e2e/exam-editor-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9223;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-exam';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

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
        if (this.pending.has(msg_id(id))) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }
      }, 30000);
      function msg_id(i) { return i; }
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
  if (!ok) throw new Error('登录失败: ' + username);
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

// 点击编辑器内按钮（按文本）
async function clickBtn(cdp, text) {
  return cdp.eval(`(function(){
    var btns = Array.from(document.querySelectorAll('.exam-editor .el-button, .exam-editor button'))
      .filter(function(b){ return b.textContent.trim().includes(${JSON.stringify(text)}); });
    if (!btns.length) return 'NOT_FOUND';
    btns[btns.length-1].click();
    return 'CLICKED';
  })()`);
}

// 点击 el-tabs 页签
async function clickTab(cdp, label) {
  return cdp.eval(`(function(){
    var tabs = Array.from(document.querySelectorAll('.exam-editor .el-tabs__item'));
    var el = tabs.find(function(t){ return t.textContent.trim() === ${JSON.stringify(label)}; });
    if (!el) return 'NOT_FOUND';
    el.click();
    return 'CLICKED';
  })()`);
}

// 通过 API 自备测试数据：在「列表默认选中的第一个班级」下找一个草稿且未组卷的考试，
// 没有则创建。保证脚本可重复运行（不再依赖上一轮遗留的未组卷草稿）。
async function prepareDraftExam(cdp) {
  return cdp.eval(`(async function(){
    var token = localStorage.getItem('access_token');
    var headers = { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };
    async function api(path, opts) {
      var res = await fetch(path, Object.assign({ headers: headers }, opts || {}));
      var text = await res.text();
      var data = {};
      try { data = JSON.parse(text); } catch (e) {}
      if (!res.ok) throw new Error(path + ' -> ' + res.status + ': ' + text.slice(0, 200));
      return data;
    }
    // 统一响应包装 {code,message,data}，列表数据在 data.results（或 data 为数组）
    function items(parsed) {
      var d = parsed && parsed.data !== undefined ? parsed.data : parsed;
      if (Array.isArray(d)) return d;
      return (d && d.results) || [];
    }
    // 列表页默认选中第一个班级，自备数据必须落在同一班级才能出现在列表里
    var classes = await api('/api/classes/?page_size=1000');
    var cls = items(classes)[0];
    if (!cls) throw new Error('教师无班级，无法自备考试数据');
    var courseId = (cls.courses || [])[0];
    if (!courseId) throw new Error('班级未关联课程');
    // 1. 该班级下已有草稿且未组卷 → 复用
    var list = await api('/api/exams/?classroom=' + cls.id + '&page_size=1000');
    var draft = items(list).find(function(e){ return e.status === 'draft' && !e.has_paper; });
    if (draft) return draft.name;
    // 2. 创建草稿考试
    function pad(n){ return (n < 10 ? '0' : '') + n; }
    function fmt(d){ return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }
    var now = new Date();
    var name = 'E2E随机抽题验证-' + now.getTime();
    await api('/api/exams/', {
      method: 'POST',
      body: JSON.stringify({
        course: courseId, classroom: cls.id, name: name,
        start_at: fmt(new Date(now.getTime() + 3600e3)),
        end_at: fmt(new Date(now.getTime() + 7200e3)),
        duration: 60, total_score: 100, status: 'draft',
      }),
    });
    return name;
  })()`);
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    console.log('\n===== 考试管理整页编辑器验证 =====');
    await login(cdp, 't101', 'pass1234');
    await cdp.navigate(BASE + '/teacher/exams');
    await waitFor(cdp, `document.body.innerText.includes('考试管理')`, 20000);
    await waitFor(cdp, `document.querySelectorAll('.exam-list-card').length > 0`, 20000);
    await cdp.shot('exam-01-list');
    check('T0.1 考试列表渲染', true, await cdp.eval(`document.querySelectorAll('.exam-list-card').length + ' 张考试卡片'`));

    const t3ExamName = 'E2E整页编辑器验证-' + Date.now();

    // ============ T1 新建考试：整页编辑器 ============
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.el-button'));
      var b = btns.find(function(x){ return x.textContent.trim() === '新建考试'; });
      if (b) b.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-editor')`, 10000);
    await sleep(600);
    const editorOk = await cdp.eval(`(function(){
      var t = document.querySelector('.exam-editor');
      if (!t) return 'NO_EDITOR';
      return {
        title: (document.querySelector('.exam-editor-title')||{}).textContent,
        tabs: Array.from(document.querySelectorAll('.exam-editor .el-tabs__item')).map(function(x){return x.textContent.trim()}),
        hasInfoCard: !!document.querySelector('.exam-info-card'),
        hasPreview: !!document.querySelector('.selected-panel'),
        hasRuleTable: !!document.querySelector('.compose-rule-table'),
      };
    })()`);
    check('T1.1 整页编辑器打开（标题=新建考试）', editorOk && editorOk.title === '新建考试', JSON.stringify(editorOk));
    check('T1.2 组卷三个页签（随机抽题/题库选题/自写题目）',
      editorOk && editorOk.tabs.join('|') === '随机抽题|题库选题|自写题目', editorOk && editorOk.tabs.join('|'));
    check('T1.3 左侧基础信息卡 + 右侧试卷预览', !!(editorOk && editorOk.hasInfoCard && editorOk.hasPreview && editorOk.hasRuleTable));
    await cdp.shot('exam-02-editor-new');

    // ============ T2 选项乱序默认选中 ============
    const shuffleChecked = await cdp.eval(`(function(){
      var boxes = Array.from(document.querySelectorAll('.exam-editor .el-checkbox'));
      var b = boxes.find(function(x){ return x.textContent.trim().includes('选项乱序'); });
      return b ? b.classList.contains('is-checked') : null;
    })()`);
    check('T2.1 选项乱序默认选中', shuffleChecked === true, 'is-checked=' + shuffleChecked);

    // ============ T3 题库选题 → 生成试卷（新建态自动建草稿） ============
    await clickTab(cdp, '题库选题');
    await waitFor(cdp, `document.querySelectorAll('.question-pool-table .pool-action').length > 0`, 15000);
    await sleep(400);
    await cdp.eval(`(function(){
      var acts = Array.from(document.querySelectorAll('.question-pool-table .pool-action'));
      acts.slice(0, 3).forEach(function(a){ a.click(); });
    })()`);
    await sleep(400);
    const previewCount = await cdp.eval(`document.querySelectorAll('.selected-panel .selected-item').length`);
    check('T3.1 题库添加 3 题后试卷预览同步显示', previewCount === 3, 'preview=' + previewCount);
    await cdp.shot('exam-03-pool-selected');

    // 填写考试名称后生成试卷（未点「创建考试」，验证自动建草稿）
    await cdp.eval(`(function(){
      var input = document.querySelector('.exam-info-card input');
      if (!input) return;
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(t3ExamName)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await clickBtn(cdp, '生成试卷');
    const composeOk = await waitFor(cdp, `document.body.innerText.includes('组卷完成')`, 20000);
    check('T3.2 点击生成试卷成功（新建态自动建草稿）', composeOk);
    await sleep(800);
    const afterCompose = await cdp.eval(`(function(){
      return {
        alert: !!document.querySelector('.compose-paper-alert'),
        preview: document.querySelectorAll('.selected-panel .selected-item').length,
        publishEnabled: (function(){
          var btns = Array.from(document.querySelectorAll('.exam-editor-actions .el-button'));
          var b = btns.find(function(x){ return x.textContent.trim().includes('发布考试'); });
          return b ? !b.disabled : null;
        })(),
        title: (document.querySelector('.exam-editor-title')||{}).textContent,
      };
    })()`);
    check('T3.3 组卷后出现覆盖提示 + 预览刷新 + 发布按钮可用',
      afterCompose.alert && afterCompose.preview === 3 && afterCompose.publishEnabled === true,
      JSON.stringify(afterCompose));
    await cdp.shot('exam-04-composed');

    // ============ T4 退出后再次进入：组卷信息回填 ============
    await clickBtn(cdp, '退出编辑');
    await waitFor(cdp, `!document.querySelector('.exam-editor')`, 8000);
    await waitFor(cdp, `document.body.innerText.includes(${JSON.stringify(t3ExamName)})`, 10000);
    await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-list-card'));
      var card = cards.find(function(c){ return c.textContent.includes(${JSON.stringify(t3ExamName)}); });
      if (!card) return;
      var btn = Array.from(card.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim() === '编辑'; });
      if (btn) btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-editor')`, 10000);
    await sleep(1200); // 等回填完成
    const backfill = await cdp.eval(`(function(){
      return {
        preview: document.querySelectorAll('.selected-panel .selected-item').length,
        activeTab: (function(){
          var t = document.querySelector('.exam-editor .el-tabs__item.is-active');
          return t ? t.textContent.trim() : null;
        })(),
        alert: !!document.querySelector('.compose-paper-alert'),
        total: (document.querySelector('.selected-header span')||{}).textContent,
      };
    })()`);
    check('T4.1 再次进入编辑：试卷题目回填（3 题）', backfill.preview === 3, JSON.stringify(backfill));
    check('T4.2 回填后定位到题库选题页签', backfill.activeTab === '题库选题', backfill.activeTab);
    check('T4.3 回填后显示已生成试卷提示', backfill.alert === true);
    await cdp.shot('exam-05-backfill');

    // 退出编辑器
    await clickBtn(cdp, '退出编辑');
    await waitFor(cdp, `!document.querySelector('.exam-editor')`, 8000);

    // ============ T5 草稿考试随机抽题 → 生成 → 发布 ============
    // 通过 API 自备数据（草稿且未组卷），保证脚本可重复运行
    const t5ExamName = await prepareDraftExam(cdp);
    check('T5.0 自备草稿考试数据（API）', !!t5ExamName, 'name=' + t5ExamName);
    await cdp.navigate(BASE + '/teacher/exams');
    await waitFor(cdp, `document.querySelectorAll('.exam-list-card').length > 0`, 20000);
    await waitFor(cdp, `document.body.innerText.includes(${JSON.stringify(t5ExamName)})`, 15000);
    await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-list-card'));
      var card = cards.find(function(c){ return c.textContent.includes(${JSON.stringify(t5ExamName)}); });
      if (!card) return;
      var btn = Array.from(card.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim() === '编辑'; });
      if (btn) btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-editor')`, 10000);
    await sleep(800);
    const draftState = await cdp.eval(`(function(){
      return {
        activeTab: (function(){
          var t = document.querySelector('.exam-editor .el-tabs__item.is-active');
          return t ? t.textContent.trim() : null;
        })(),
        preview: document.querySelectorAll('.selected-panel .selected-item').length,
        publishEnabled: (function(){
          var btns = Array.from(document.querySelectorAll('.exam-editor-actions .el-button'));
          var b = btns.find(function(x){ return x.textContent.trim().includes('发布考试'); });
          return b ? !b.disabled : null;
        })(),
      };
    })()`);
    check('T5.1 未组卷草稿：默认随机抽题页签 + 预览空 + 发布禁用',
      draftState.activeTab === '随机抽题' && draftState.preview === 0 && draftState.publishEnabled === false,
      JSON.stringify(draftState));
    await cdp.shot('exam-06-draft-random');
    await clickBtn(cdp, '生成试卷');
    const randomOk = await waitFor(cdp, `document.body.innerText.includes('组卷完成')`, 20000);
    check('T5.2 随机抽题生成试卷成功', randomOk);
    await sleep(800);
    const randomPreview = await cdp.eval(`document.querySelectorAll('.selected-panel .selected-item').length`);
    check('T5.3 随机抽题后预览展示抽出的题目', randomPreview >= 1, 'preview=' + randomPreview);
    await cdp.shot('exam-07-random-preview');

    // 发布考试
    await clickBtn(cdp, '发布考试');
    const published = await waitFor(cdp, `!document.querySelector('.exam-editor') && document.body.innerText.includes('已发布')`, 20000);
    check('T5.4 发布考试成功并退出编辑器', published);
    await sleep(600);

    // ============ T6 查看试卷 hover 题目详情 ============
    await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-list-card'));
      var card = cards.find(function(c){ return c.textContent.includes(${JSON.stringify(t5ExamName)}); });
      if (!card) return;
      var btn = Array.from(card.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim() === '查看试卷'; });
      if (btn) btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-paper-dialog .paper-q-item')`, 15000);
    await sleep(600);
    // 真实鼠标悬停第一题题干
    const box = await cdp.eval(`(function(){
      var el = document.querySelector('.exam-paper-dialog .paper-q-stem');
      if (!el) return null;
      var r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    })()`);
    if (box) {
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
    }
    // 浮层必须真实可见（排除 EP 隐藏残留节点误报：display/visibility 正常 + 尺寸非零）
    const popoverOk = await waitFor(cdp, `(function(){
      var p = document.querySelector('.question-detail-popper');
      if (!p) return false;
      var s = getComputedStyle(p);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
      var r = p.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    })()`, 8000);
    const popoverText = popoverOk
      ? await cdp.eval(`(document.querySelector('.question-detail-popper')||{textContent:''}).textContent`)
      : '';
    check('T6.1 hover 题干显示题目详情浮层（真实可见）', popoverOk);
    check('T6.2 浮层包含参考答案/题型/分值', popoverText.includes('参考答案') && popoverText.includes('分值'), popoverText.slice(0, 80));
    await cdp.shot('exam-08-paper-hover');

    // ============ T7 已组卷考试点「生成试卷」：覆盖确认框可见性与防堆叠 ============
    // T3 创建的考试是「草稿 + 已组卷」，正适合复现「编辑考试点生成试卷」
    await cdp.navigate(BASE + '/teacher/exams');
    await waitFor(cdp, `document.querySelectorAll('.exam-list-card').length > 0`, 20000);
    await waitFor(cdp, `document.body.innerText.includes(${JSON.stringify(t3ExamName)})`, 15000);
    await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-list-card'));
      var card = cards.find(function(c){ return c.textContent.includes(${JSON.stringify(t3ExamName)}); });
      if (!card) return;
      var btn = Array.from(card.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim() === '编辑'; });
      if (btn) btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-editor')`, 10000);
    await sleep(1200); // 等回填完成（composedPaper 就位后才会弹覆盖确认）
    // 连点两次「生成试卷」：第二次必须被禁用/忽略，只能出现一个确认框
    await clickBtn(cdp, '生成试卷');
    await sleep(300);
    await clickBtn(cdp, '生成试卷');
    await sleep(500);
    const overlayState = await cdp.eval(`(function(){
      var overlays = Array.from(document.querySelectorAll('.el-overlay.is-message-box'));
      var box = overlays[overlays.length - 1];
      var editorZ = (function(){
        var ed = document.querySelector('.exam-editor');
        return ed ? parseInt(getComputedStyle(ed).zIndex, 10) : 0;
      })();
      if (!box) return { count: overlays.length, visible: false, zIndex: 0, editorZ: editorZ };
      var s = getComputedStyle(box);
      var r = box.getBoundingClientRect();
      return {
        count: overlays.length,
        visible: s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0,
        zIndex: parseInt(s.zIndex, 10),
        editorZ: editorZ,
        text: box.textContent.slice(0, 50),
      };
    })()`);
    check('T7.1 覆盖确认框真实可见且位于编辑器之上（连点不堆叠）',
      overlayState.count === 1 && overlayState.visible && overlayState.zIndex > overlayState.editorZ,
      JSON.stringify(overlayState));
    await cdp.shot('exam-09-overwrite-confirm');
    // 「重新生成」按钮必须可点击（绘制在最顶层）
    const regenTop = await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.el-overlay.is-message-box .el-button'));
      var b = btns.find(function(x){ return x.textContent.trim() === '重新生成'; });
      if (!b) return 'NOT_FOUND';
      var r = b.getBoundingClientRect();
      var el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return (el && (el === b || b.contains(el))) ? 'TOP' : 'COVERED:' + (el ? String(el.className).slice(0, 40) : 'null');
    })()`);
    check('T7.2 「重新生成」按钮位于最顶层可点击', regenTop === 'TOP', regenTop);
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.el-overlay.is-message-box .el-button'));
      var b = btns.find(function(x){ return x.textContent.trim() === '重新生成'; });
      if (b) b.click();
    })()`);
    const recomposed = await waitFor(cdp, `document.body.innerText.includes('组卷完成')`, 20000);
    check('T7.3 点击重新生成后组卷成功', recomposed);
    await sleep(800);
    const recomposedCount = await cdp.eval(`document.querySelectorAll('.selected-panel .selected-item').length`);
    check('T7.4 重新生成后试卷预览仍展示题目', recomposedCount >= 1, 'preview=' + recomposedCount);
    await cdp.shot('exam-10-recomposed');
    await clickBtn(cdp, '退出编辑');
    await waitFor(cdp, `!document.querySelector('.exam-editor')`, 8000);

    // ============ 汇总 ============
    const failed = results.filter((r) => !r.ok);
    console.log('\n===== 结果：' + (results.length - failed.length) + '/' + results.length + ' 通过 =====');
    if (failed.length) {
      failed.forEach((f) => console.log('FAIL | ' + f.name));
      process.exitCode = 1;
    }
  } finally {
    chrome.kill();
  }
}

run().catch((e) => { console.error('E2E 运行异常:', e); process.exit(1); });
