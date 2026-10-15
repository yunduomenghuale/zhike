#!/usr/bin/env node
/**
 * 工作台多课程跳转（学生 + 教师）—— CDP 真实浏览器 E2E 测试
 *
 * 驱动本地 Chrome（headless + --no-proxy-server，绕开沙箱代理）访问
 * Vite 开发服务器(http://localhost:5273)，对以下修改项做全链路验证：
 *   T1 多课程学生工作台：课程级入口弹课程选择、点击即进入、最近学习排最前
 *   T2 学生课程空间：「切换课程」已按需求隐藏；各 tab 数据随课程参数正确加载
 *   T3 单课程学生：一键直达不受影响、空间内无切换器
 *   T4 零课程学生：走独立页空态
 *   T5 教师端：多课程选择跳转（弹窗、点击即进入、最近操作排最前）+ 原回归
 *
 * 运行：node test/e2e/cdp-drive.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9222;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const LAST_COURSE_KEY = 'zhike.lastCourseId.student';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------- CDP 客户端 ----------------
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
    await sleep(400); // 等 Vue 挂载
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    return name + '.png';
  }
}

// ---------------- 页面操作辅助 ----------------
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

/** 轮询等待页面文本出现（同时规避导航后 eval 上下文漂移与异步渲染） */
async function waitForText(cdp, text, timeout = 20000) {
  return waitFor(cdp, `document.body.innerText.includes(${JSON.stringify(text)})`, timeout);
}

/** 轮询等待选择器命中并返回其文本（规避 eval 上下文漂移返回空值） */
async function waitForSelectorText(cdp, selector, timeout = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let text = '';
    try {
      text = await cdp.eval(`(document.querySelector(${JSON.stringify(selector)})||{textContent:''}).textContent.trim()`);
    } catch { text = ''; }
    if (text) return text;
    await sleep(200);
  }
  return '';
}

/** 点击工作台功能卡（按 feature-label 精确匹配，避免 desc 文案误匹配） */
async function clickFeature(cdp, label) {
  return cdp.eval(`(function(){
    var labels = Array.from(document.querySelectorAll('.feature-card .feature-label'));
    var el = labels.find(function(l){ return l.textContent.trim() === ${JSON.stringify(label)}; });
    if (!el) return 'NOT_FOUND';
    var card = el.closest('.feature-card');
    card.scrollIntoView({block:'center'});
    card.click();
    return 'CLICKED';
  })()`);
}

/** 点击课程选择弹窗中的课程（按课程名精确匹配） */
async function clickPickerCourse(cdp, name) {
  return cdp.eval(`(function(){
    var names = Array.from(document.querySelectorAll('.course-picker-item .picker-course-name'));
    var el = names.find(function(n){ return n.textContent.trim() === ${JSON.stringify(name)}; });
    if (!el) return 'NOT_FOUND';
    el.closest('.course-picker-item').click();
    return 'CLICKED';
  })()`);
}

/** 点击切换课程下拉菜单中的课程 */
async function clickSwitchCourse(cdp, name) {
  return cdp.eval(`(function(){
    var names = Array.from(document.querySelectorAll('.course-switcher-menu .switcher-item-name'));
    var el = names.find(function(n){ return n.textContent.trim() === ${JSON.stringify(name)}; });
    if (!el) return 'NOT_FOUND';
    el.closest('.el-dropdown-menu__item').click();
    return 'CLICKED';
  })()`);
}

async function clickButton(cdp, text) {
  return cdp.eval(`(function(){
    var btns = Array.from(document.querySelectorAll('.el-dialog__footer .el-button, .el-dialog__footer button'));
    var el = btns.find(function(b){ return b.textContent.trim() === ${JSON.stringify(text)}; });
    if (!el) return 'NOT_FOUND';
    el.click();
    return 'CLICKED';
  })()`);
}

async function login(cdp, username, password) {
  // 已登录态访问 /login 会被路由守卫弹回工作台；about:blank 上无法访问 localStorage，
  // 用 CDP Storage 域按 origin 清理登录态，再进入登录页
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

async function bodyText(cdp) {
  return cdp.eval('document.body.innerText');
}

// ---------------- 测试结果记录 ----------------
const results = [];
function report(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}
async function check(name, ok, detail) {
  report(name, !!ok, detail);
}

// ---------------- 启动 Chrome ----------------
async function launchChrome() {
  // 复用旧 profile 不影响测试正确性（登录时 CDP 会清 localStorage）；
  // 清理失败（如沙箱安全护栏拦截批量删除）时静默继续。
  try {
    fs.rmSync(PROFILE, { recursive: true, force: true });
  } catch { /* profile 清理失败则复用旧目录 */ }
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
  ], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
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
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { cdp, chrome };
}

// ---------------- 测试流程 ----------------
async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);

  try {
    // ============ T1 多课程学生（20249999，两个班级两门课） ============
    console.log('\n===== T1 多课程学生工作台 =====');
    await login(cdp, '20249999', 'A0987654');
    await cdp.eval(`localStorage.removeItem(${JSON.stringify(LAST_COURSE_KEY)})`);
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);

    // 1.1 点击「课程学习」应弹课程选择框（两门课）
    await clickFeature(cdp, '课程学习');
    const dlg = await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    check('T1.1 点击课程学习弹出课程选择框且列出 2 门课程', dlg);
    if (dlg) {
      const names = await cdp.eval(`Array.from(document.querySelectorAll('.course-picker-item .picker-course-name')).map(function(n){return n.textContent.trim()}).join('|')`);
      check('T1.2 弹窗课程为「真实测试课程1789789245」与「数据结构B」', names === '真实测试课程1789789245|数据结构B', names);
      const noEnterBtn = await cdp.eval(`!Array.from(document.querySelectorAll('.course-picker-footer .el-button')).some(function(b){return b.textContent.trim()==='进入'})`);
      check('T1.3 弹窗无「进入」按钮（点击课程项即进入）', noEnterBtn);
      await cdp.shot('t1-course-picker');
    }

    // 1.4 点击第一门课「真实测试课程1789789245」即直接进入课程5（一步完成）
    await clickPickerCourse(cdp, '真实测试课程1789789245');
    const c5Direct = await waitFor(cdp, `location.pathname === '/student/courses/5/learning'`, 10000);
    check('T1.4 点击第一门课程直接进入 /student/courses/5/learning', c5Direct, await cdp.eval('location.pathname'));
    await waitForText(cdp, '第4章 网络层');

    // 1.5 再次弹窗点击第二门课「数据结构B」，URL 与内容应为课程6
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '课程学习');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    await clickPickerCourse(cdp, '数据结构B');
    const urlOk = await waitFor(cdp, `location.pathname === '/student/courses/6/learning'`, 10000);
    check('T1.5 点击数据结构B直接进入 /student/courses/6/learning', urlOk, await cdp.eval('location.pathname'));
    await waitForText(cdp, '第1章 线性表');
    const learnText = await bodyText(cdp);
    check('T1.6 课程学习页展示课程B章节（第1章 线性表/第2章 栈和队列）', learnText.includes('第1章 线性表') && learnText.includes('第2章 栈和队列'));
    check('T1.7 课程学习页不展示课程5章节（第4章 网络层）', !learnText.includes('第4章 网络层'));
    await cdp.shot('t1-learning-course-b');
    const lastCourse = await cdp.eval(`localStorage.getItem(${JSON.stringify(LAST_COURSE_KEY)})`);
    check('T1.8 记住最近点击的课程到 localStorage', lastCourse === '6', 'last=' + lastCourse);

    // 1.9 知识库提问入口 → 弹窗中最近学习课程排在最前 → 点击课程5 → 进入课程5的 qa
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '知识库提问');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    const firstItem = await waitForSelectorText(cdp, '.course-picker-item .picker-course-name');
    check('T1.9 再次弹窗最近学习课程排在最前（数据结构B）', firstItem === '数据结构B', firstItem);
    await clickPickerCourse(cdp, '真实测试课程1789789245');
    const qaUrl = await waitFor(cdp, `location.pathname === '/student/courses/5/qa'`, 10000);
    check('T1.10 知识库提问可进入课程5（/student/courses/5/qa）', qaUrl, await cdp.eval('location.pathname'));
    await waitFor(cdp, `!!document.querySelector('.chat-empty, .chat-messages, .qa-page, .page-container')`, 10000);

    // 1.11 我的作业 → 课程B
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '我的作业');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    await clickPickerCourse(cdp, '数据结构B');
    const hwUrl = await waitFor(cdp, `location.pathname === '/student/courses/6/homework'`, 10000);
    check('T1.11 我的作业可进入课程B（/student/courses/6/homework）', hwUrl, await cdp.eval('location.pathname'));
    await waitForText(cdp, '数据结构-作业1');
    const hwText = await bodyText(cdp);
    check('T1.12 作业页展示课程B作业（数据结构-作业1）', hwText.includes('数据结构-作业1'));
    check('T1.13 作业页不展示课程5作业（计算机网络-作业1）', !hwText.includes('计算机网络-作业1'));

    // 1.14 我的考试 → 课程B
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '我的考试');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    await clickPickerCourse(cdp, '数据结构B');
    const exUrl = await waitFor(cdp, `location.pathname === '/student/courses/6/exams'`, 10000);
    check('T1.14 我的考试可进入课程B（/student/courses/6/exams）', exUrl, await cdp.eval('location.pathname'));
    await waitForText(cdp, '数据结构-期中1');
    const exText = await bodyText(cdp);
    check('T1.15 考试页展示课程B考试（数据结构-期中1）', exText.includes('数据结构-期中1'));
    check('T1.16 考试页不展示课程5考试（计算机网络-月考1）', !exText.includes('计算机网络-月考1'));

    // 1.17 错题本 → 课程B
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '错题本');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    await clickPickerCourse(cdp, '数据结构B');
    const wbUrl = await waitFor(cdp, `location.pathname === '/student/courses/6/wrong'`, 10000);
    check('T1.17 错题本可进入课程B（/student/courses/6/wrong）', wbUrl, await cdp.eval('location.pathname'));
    await waitForText(cdp, '顺序表中访问第 i 个元素');
    const wbText = await bodyText(cdp);
    check('T1.18 错题本展示课程B错题（顺序表/栈）', wbText.includes('顺序表中访问第 i 个元素') && wbText.includes('栈的特点是后进先出'));
    check('T1.19 错题本不展示课程5错题（VLAN）', !wbText.includes('VLAN'));
    await cdp.shot('t1-wrong-course-b');

    // 1.20 课程5 的内容也能通过选择器进入（回归：原第一门课不受影响）
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '课程学习');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    await clickPickerCourse(cdp, '真实测试课程1789789245');
    const c5Url = await waitFor(cdp, `location.pathname === '/student/courses/5/learning'`, 10000);
    check('T1.20 课程5仍可通过选择器进入', c5Url, await cdp.eval('location.pathname'));
    await waitForText(cdp, '第4章 网络层');
    const c5Text = await bodyText(cdp);
    check('T1.21 课程学习页展示课程5章节（第4章 网络层）', c5Text.includes('第4章 网络层'));

    // ============ T2 课程空间内切换课程 ============
    console.log('\n===== T2 课程空间内切换课程 =====');
    // 需求变更：「切换课程」下拉暂时隐藏，仅需验证不显示 + 各 tab 数据随课程参数正确加载
    await goto('/student/courses/6/homework');
    await waitFor(cdp, `document.body.innerText.includes('数据结构-作业1')`, 20000);
    const switcherHidden = await waitFor(cdp, `!document.querySelector('.course-switcher-btn')`, 8000);
    check('T2.1 课程空间不再显示「切换课程」按钮（按需求隐藏）', switcherHidden);

    // 直接进入另一门课的同一 tab，数据应随课程参数加载（作业）
    await goto('/student/courses/5/homework');
    await waitFor(cdp, `document.body.innerText.includes('计算机网络-作业1')`, 15000);
    const hw5Text = await bodyText(cdp);
    check('T2.2 作业 tab 进入课程5展示课程5作业（计算机网络-作业1）', hw5Text.includes('计算机网络-作业1') && !hw5Text.includes('数据结构-作业1'));

    // 错题本
    await goto('/student/courses/5/wrong');
    await waitFor(cdp, `document.body.innerText.includes('VLAN')`, 15000);
    const wb5Text = await bodyText(cdp);
    check('T2.3 错题本 tab 进入课程5展示课程5错题（VLAN）', wb5Text.includes('VLAN') && !wb5Text.includes('顺序表中访问第 i 个元素'));

    // 实验（验证 LabList 课程过滤）
    await goto('/student/courses/5/labs');
    await waitFor(cdp, `document.body.innerText.includes('实验一')`, 15000);
    const lab5Text = await bodyText(cdp);
    check('T2.4 实验 tab 进入课程5展示课程5实验（实验一）', lab5Text.includes('实验一') && !lab5Text.includes('数据结构实验'));

    // 课程资料（验证 CourseMaterials 课程参数）
    await goto('/student/courses/5/materials');
    await waitFor(cdp, `document.body.innerText.includes('新版测试.docx')`, 15000);
    const mat5Text = await bodyText(cdp);
    check('T2.5 课程资料 tab 进入课程5展示课程5资料（新版测试.docx）', mat5Text.includes('新版测试.docx') && !mat5Text.includes('数据结构课件.pdf'));

    // ============ T3 单课程学生（dbg1） ============
    console.log('\n===== T3 单课程学生回归 =====');
    await login(cdp, 'dbg1', 'A0987654');
    await cdp.eval(`localStorage.removeItem(${JSON.stringify(LAST_COURSE_KEY)})`);
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '课程学习');
    // 单课程应直接进入，不弹窗
    const directUrl = await waitFor(cdp, `location.pathname === '/student/courses/5/learning'`, 10000);
    check('T3.1 单课程学生点击课程学习直接进入课程空间（不弹选择框）', directUrl, await cdp.eval('location.pathname'));
    const noDialog = await cdp.eval(`!document.querySelector('.course-picker-item')`);
    check('T3.2 单课程学生不出现课程选择弹窗', noDialog);
    await waitFor(cdp, `document.body.innerText.includes('第4章 网络层')`, 15000);
    const noSwitcher = await cdp.eval(`!document.querySelector('.course-switcher-btn')`);
    check('T3.3 单课程学生课程空间不显示切换课程按钮', noSwitcher);
    await cdp.shot('t3-single-course');

    // ============ T4 零课程学生（dbg2，未加入任何班级） ============
    console.log('\n===== T4 零课程学生 =====');
    await login(cdp, 'dbg2', 'A0987654');
    await cdp.eval(`localStorage.removeItem(${JSON.stringify(LAST_COURSE_KEY)})`);
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '课程学习');
    const zeroUrl = await waitFor(cdp, `location.pathname === '/student/learning'`, 10000);
    check('T4.1 零课程学生点击课程学习进入独立页（/student/learning）', zeroUrl, await cdp.eval('location.pathname'));
    const zeroOk = await waitForText(cdp, '请先选择课程', 15000);
    const zeroText = await bodyText(cdp);
    check('T4.2 独立页显示引导空态（请先选择课程）', zeroOk && zeroText.includes('请先选择课程'));

    // ============ T5 教师端回归 ============
    console.log('\n===== T5 教师端回归 =====');
    await login(cdp, 't101', 'A0987654');
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    const teacherText = await bodyText(cdp);
    check('T5.1 教师工作台展示教师功能（课程管理/班级管理）', teacherText.includes('课程管理') && teacherText.includes('班级管理'));
    await clickFeature(cdp, '课程管理');
    const tcUrl = await waitFor(cdp, `location.pathname === '/teacher/courses'`, 10000);
    check('T5.2 教师点击课程管理进入课程列表', tcUrl, await cdp.eval('location.pathname'));
    await waitForText(cdp, '数据结构B', 15000);
    const tcText = await bodyText(cdp);
    check('T5.3 教师课程列表展示两门课程', tcText.includes('真实测试课程1789789245') && tcText.includes('数据结构B'));
    // 进入教师课程空间，确认无学生端切换器、无学生端选择弹窗
    await goto('/teacher/courses/5/chapters');
    await waitFor(cdp, `document.body.innerText.includes('第4章 网络层') || document.querySelector('.course-menu')`, 15000);
    const teacherNoSwitcher = await cdp.eval(`!document.querySelector('.course-switcher-btn')`);
    check('T5.4 教师课程空间不显示学生端切换课程按钮', teacherNoSwitcher);
    await cdp.shot('t5-teacher-workspace');

    // ============ T5 教师端多课程选择（t101 有 2 门课） ============
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await cdp.eval(`localStorage.removeItem('zhike.lastCourseId.teacher')`);
    await clickFeature(cdp, '作业管理');
    const tDlg = await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    check('T5.5 教师点击作业管理弹出课程选择框且列出 2 门课程', tDlg);
    if (tDlg) {
      const tNames = await cdp.eval(`Array.from(document.querySelectorAll('.course-picker-item .picker-course-name')).map(function(n){return n.textContent.trim()}).join('|')`);
      check('T5.5b 教师弹窗课程为两门所授课程', tNames === '真实测试课程1789789245|数据结构B', tNames);
      await sleep(600); // 等弹窗开场动画稳定后再截图
      await cdp.shot('t5-teacher-picker');
    }

    // 点击课程即进入教师课程空间对应 tab（一步完成）
    await clickPickerCourse(cdp, '数据结构B');
    const tHwUrl = await waitFor(cdp, `location.pathname === '/teacher/courses/6/homework'`, 10000);
    check('T5.6 教师点击课程直接进入 /teacher/courses/6/homework', tHwUrl, await cdp.eval('location.pathname'));
    await waitForText(cdp, '数据结构-作业1');
    const tHwText = await bodyText(cdp);
    check('T5.7 教师作业页展示课程B作业（数据结构-作业1）', tHwText.includes('数据结构-作业1') && !tHwText.includes('计算机网络-作业1'));

    // 再次弹窗（考试入口）：最近操作的课程排最前，可进入另一门课
    await goto('/dashboard');
    await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`);
    await clickFeature(cdp, '考试');
    await waitFor(cdp, `document.querySelectorAll('.course-picker-item').length === 2`, 10000);
    const tFirst = await waitForSelectorText(cdp, '.course-picker-item .picker-course-name');
    check('T5.8 教师再次弹窗最近操作课程排最前（数据结构B）', tFirst === '数据结构B', tFirst);
    await clickPickerCourse(cdp, '真实测试课程1789789245');
    const tExUrl = await waitFor(cdp, `location.pathname === '/teacher/courses/5/exams'`, 10000);
    await waitForText(cdp, '计算机网络-月考1');
    const tExText = await bodyText(cdp);
    check('T5.9 教师点击另一门课进入 /teacher/courses/5/exams 且展示课程5考试', tExUrl && tExText.includes('计算机网络-月考1'), await cdp.eval('location.pathname'));

    // 我的班级页回归（学生）
    await login(cdp, '20249999', 'A0987654');
    await goto('/student/my-classes');
    await waitFor(cdp, `document.body.innerText.includes('数据结构B')`, 15000);
    const myClassText = await bodyText(cdp);
    check('T5.10 我的班级页展示两门课程（点击可分别进入）', myClassText.includes('真实测试课程1789789245') && myClassText.includes('数据结构B'));
    await cdp.shot('t5-my-classes');
  } finally {
    try { await cdp.send('Browser.close'); } catch { /* ignore */ }
    chrome.kill();
  }

  // ---------------- 汇总 ----------------
  const failed = results.filter((r) => !r.ok);
  console.log('\n===== 汇总 =====');
  console.log('总计 ' + results.length + ' 项，通过 ' + (results.length - failed.length) + ' 项，失败 ' + failed.length + ' 项');
  if (failed.length) {
    failed.forEach((f) => console.log('失败: ' + f.name));
    process.exitCode = 1;
  } else {
    console.log('ALL_PASS');
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 2;
});
