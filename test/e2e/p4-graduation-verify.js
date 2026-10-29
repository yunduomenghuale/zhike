#!/usr/bin/env node
/**
 * P4 E2E：整班毕业全链（管理端）+ 毕业生/休学生端门控（学生端）。
 *
 * 验证点（对应任务规范 §4 P4 的前端部分）：
 *   A 管理端名单页：学籍状态列、整班毕业入口
 *   B 毕业弹窗：预览名单（将毕业 N 人）、在途作业清单、force 勾选后才可确认（X-14）
 *   C 确认毕业：成功提示 + 名单学籍列变「已毕业」
 *   D 撤销毕业：确认框 + 名单回到「在读」
 *   E 个别学籍变更弹窗：把 s1 置为毕业（与整班毕业互补）
 *   F 毕业生（s1）：作业「查看作业」禁用且带原因、考试显示「已毕业，不能开始考试」、
 *     AI 问答输入禁用且 placeholder 带原因、课程学习仍可进入（X-31 学习不拦）
 *   G 休学生（s3）：课程学习显示「休学中，暂不可学习」
 *   H 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273（node serve-local.js）、admin/A0987654
 * 数据：脚本自建自清（班级编码 E2EP4 前缀 + e2ep4_ 用户前缀），走 API 播种、UI 驱动
 * 运行：node test/e2e/p4-graduation-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const API = 'http://127.0.0.1:5273/api';
const ROOT = path.resolve(__dirname, '../..');
const SHOT_DIR = path.join(ROOT, 'test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9950 + (parseInt(RUN_ID, 36) % 40);
const PROFILE = `D:/tmp/zhike-p4-e2e/run-${RUN_ID}`;
const PWD = 'E2ePass123!';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }
let failures = 0;
let passes = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (ok) passes += 1; else failures += 1;
}

// ---------------------------------------------------------------------------
// API 播种（自建自清）
// ---------------------------------------------------------------------------
async function api(method, url, body, token) {
  const res = await fetch(API + url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

const SEED = { classId: null, courseId: null, catalogId: null, questionId: null, users: [], code: `E2EP4${RUN_ID.toUpperCase()}` };

async function seed() {
  const teacherLogin = await api('POST', '/auth/login/', { username: 't101', password: 'pass1234' });
  if (teacherLogin.status !== 200) throw new Error('t101 登录失败：' + JSON.stringify(teacherLogin.data));
  const teacher = teacherLogin.data.data.token.access;
  const adminLogin = await api('POST', '/auth/login/', { username: 'admin', password: 'A0987654' });
  if (adminLogin.status !== 200) throw new Error('admin 登录失败：' + JSON.stringify(adminLogin.data));
  const admin = adminLogin.data.data.token.access;

  // 课程归教师（compose 组卷仅教师可调，锚点是课程负责人）
  const course = await api('POST', '/courses/', { name: `E2E-P4课程-${RUN_ID}`, intro: 'P4 E2E 专用' }, teacher);
  if (course.status !== 201) throw new Error('建课失败：' + JSON.stringify(course.data));
  SEED.courseId = course.data.data.id;

  // 2020 级 4 年制 → 已到毕业年份，避免 force 年份分支干扰在途分支
  const cls = await api('POST', '/classes/', {
    name: `E2E-P4班-${RUN_ID}`, code: SEED.code,
    courses: [SEED.courseId], enrollment_year: 2020, duration_years: 4,
  }, admin);
  if (cls.status !== 201) throw new Error('建班失败：' + JSON.stringify(cls.data));
  SEED.classId = cls.data.data.id;

  for (const key of ['s1', 's2', 's3']) {
    const u = await api('POST', '/admin-panel/users/', {
      username: `e2ep4_${RUN_ID}_${key}`, real_name: `E2E${key.toUpperCase()}`, role: 'student', password: PWD,
    }, admin);
    if (u.status !== 201) throw new Error(`建学生 ${key} 失败：` + JSON.stringify(u.data));
    SEED.users.push({ key, id: u.data.data.id, username: u.data.data.username });
  }
  const add = await api('POST', `/classes/${SEED.classId}/add-students-batch/`,
    { usernames: SEED.users.map((u) => u.username) }, admin);
  if (add.status !== 200) throw new Error('入班失败：' + JSON.stringify(add.data));

  // 未截止作业：毕业弹窗的在途清单（X-14 force 分支）
  const hw = await api('POST', '/homeworks/', {
    classroom: SEED.classId, course: SEED.courseId, title: `E2E-P4作业-${RUN_ID}`,
    mode: 'attachment', status: 'published', total_score: 100,
    deadline: new Date(Date.now() + 7 * 86400e3).toISOString(),
  }, admin);
  if (hw.status !== 201) throw new Error('建作业失败：' + JSON.stringify(hw.data));

  // 长期开放考试（学生端「进入考试」入口）：草稿 → 组卷 → 发布
  const catalog = await api('POST', '/catalogs/', { course: SEED.courseId, title: `E2E章节-${RUN_ID}`, is_published: true }, teacher);
  if (catalog.status !== 201) throw new Error('建章节失败：' + JSON.stringify(catalog.data));
  SEED.catalogId = catalog.data.data.id;
  const question = await api('POST', '/questions/', {
    course: SEED.courseId, catalog: catalog.data.data.id, qtype: 'single',
    stem: `E2E-P4题-${RUN_ID}`,
    options: [{ key: 'A', text: '对' }, { key: 'B', text: '错' }],
    answer: { key: 'A' }, score: 5, status: 'published',
  }, teacher);
  if (question.status !== 201) throw new Error('建题目失败：' + JSON.stringify(question.data));
  SEED.questionId = question.data.data.id;
  const exam = await api('POST', '/exams/', {
    name: `E2E-P4考试-${RUN_ID}`, course: SEED.courseId, classroom: SEED.classId, duration: 60,
  }, teacher);
  if (exam.status !== 201) throw new Error('建考试失败：' + JSON.stringify(exam.data));
  const compose = await api('POST', `/exams/${exam.data.data.id}/compose/`,
    { mode: 'manual', questions: [{ question_id: question.data.data.id, score: 5 }] }, teacher);
  if (compose.status !== 200) throw new Error('组卷失败：' + JSON.stringify(compose.data));
  const publish = await api('PATCH', `/exams/${exam.data.data.id}/`, { status: 'published' }, teacher);
  if (publish.status !== 200) throw new Error('发布考试失败：' + JSON.stringify(publish.data));

  log(`播种完成：班 ${SEED.classId}（${SEED.code}）· 课 ${SEED.courseId} · 学生 ${SEED.users.map((u) => u.username).join(',')}`);
}

async function cleanup() {
  const adminLogin = await api('POST', '/auth/login/', { username: 'admin', password: 'A0987654' });
  if (adminLogin.status !== 200) { log('清理跳过：admin 登录失败'); return; }
  const admin = adminLogin.data.data.token.access;
  const teacherLogin = await api('POST', '/auth/login/', { username: 't101', password: 'pass1234' });
  const teacher = teacherLogin.status === 200 ? teacherLogin.data.data.token.access : admin;
  // 先删班（级联作业/考试/占用关系），再删人；题目→章节→课按 PROTECT 顺序
  if (SEED.classId) await api('DELETE', `/classes/${SEED.classId}/`, undefined, admin);
  for (const u of SEED.users) await api('DELETE', `/admin-panel/users/${u.id}/`, undefined, admin);
  if (SEED.questionId) await api('DELETE', `/questions/${SEED.questionId}/`, undefined, teacher);
  if (SEED.catalogId) await api('DELETE', `/catalogs/${SEED.catalogId}/`, undefined, teacher);
  if (SEED.courseId) await api('DELETE', `/courses/${SEED.courseId}/`, undefined, teacher);
  log('清理完成（班/人/题/章节/课）');
}

// ---------------------------------------------------------------------------
// CDP 驱动（与 p1/p3 同款）
// ---------------------------------------------------------------------------
class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push('console.error: ' + (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        this.consoleErrors.push('page exception: ' + (d.exception?.description || d.text));
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval failed: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name), Buffer.from(r.data, 'base64'));
  }
}

async function launchChrome() {
  const proc = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
    `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', '--force-device-scale-factor=1', 'about:blank',
  ], { stdio: 'ignore', detached: true });
  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const page = (await res.json()).filter((t) => t.type === 'page')[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* retry */ }
    await sleep(250);
  }
  if (!wsUrl) throw new Error('Chrome devtools 端口未就绪');
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws 失败'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  return { cdp, chrome: proc };
}

async function waitFor(tab, expression, timeoutMs = 20000, pollMs = 250) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { if (await tab.eval(expression)) return true; } catch { /* retry */ }
    await sleep(pollMs);
  }
  return false;
}

async function login(tab, username, password) {
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.href.startsWith('http')`);
  await tab.eval(`localStorage.clear()`);
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2`, 20000);
  await tab.eval(`(() => {
    const inputs = document.querySelectorAll('input');
    inputs[0].value = ${JSON.stringify(username)};
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    const pwd = document.querySelector('input[type="password"]');
    pwd.value = ${JSON.stringify(password)};
    pwd.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(200);
  await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`);
  return waitFor(tab, `!location.pathname.startsWith('/login')`, 20000);
}

const BODY = `document.body.innerText`;
const hasText = async (tab, text) => (await tab.eval(BODY)).includes(text);
const clickByText = (sel, text) => `(() => {
  const els = [...document.querySelectorAll('${sel}')];
  const el = els.find((e) => e.innerText.trim() === ${JSON.stringify(text)});
  if (el) { el.click(); return true; }
  return false;
})()`;

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  await seed();
  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    const roster = `${BASE}/admin/classes/${SEED.classId}/students`;

    // ===================== A. 管理端名单页 =====================
    check('管理员登录', await login(tab, 'admin', 'A0987654'));
    await tab.send('Page.navigate', { url: roster });
    check('名单页渲染', await waitFor(tab, `document.querySelector('.roster-table') !== null`, 25000));
    await sleep(1200); // 名单翻页拉取 + 渲染
    check('学籍状态列表头', await hasText(tab, '学籍状态'));
    check('学籍列显示「在读」', await tab.eval(`[...document.querySelectorAll('.el-table__row')].every((r) => r.innerText.includes('在读'))`));
    check('有「整班毕业」入口', await tab.eval(`[...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '整班毕业')`));
    await tab.shot('p4-01-admin-roster-before.png');

    // ===================== B. 毕业弹窗：预览 + 在途 + force =====================
    await tab.eval(clickByText('button', '整班毕业'));
    check('毕业弹窗打开', await waitFor(tab, `(() => {
      const d = document.querySelector('.class-graduate-dialog');
      return !!(d && d.getBoundingClientRect().height > 100);
    })()`, 8000));
    await sleep(800); // preview 请求 + 渲染
    const dlgText = await tab.eval(`(() => { const d = document.querySelector('.class-graduate-dialog'); return d ? d.innerText : ''; })()`);
    check('弹窗显示将毕业 3 人', dlgText.includes('将毕业 3 人'), dlgText.slice(0, 80));
    check('弹窗含在途作业清单', dlgText.includes('E2E-P4作业'), dlgText.slice(0, 120));
    check('弹窗含强制确认勾选', await tab.eval(`!!document.querySelector('.class-graduate-dialog .grad-force')`));
    check('未勾选时确认毕业禁用', await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.class-graduate-dialog .el-dialog__footer .el-button--primary')][0];
      return !!btn && btn.disabled === true;
    })()`));
    await tab.shot('p4-02-graduate-dialog-preview.png');

    // 勾选 force → 确认可点 → 执行
    // 注意：el-checkbox 的 class 透传到根 label 自身（.grad-force 就是 label），
    // `.grad-force .el-checkbox` 后代选择器永不命中——点里面的原生 input
    await tab.eval(`(() => { const cb = document.querySelector('.class-graduate-dialog .grad-force .el-checkbox__original'); if (cb) cb.click(); })()`);
    await sleep(300);
    check('勾选后确认毕业可点', await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.class-graduate-dialog .el-dialog__footer .el-button--primary')][0];
      return !!btn && btn.disabled === false;
    })()`));
    await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.class-graduate-dialog .el-dialog__footer .el-button--primary')][0];
      if (btn) btn.click();
    })()`);
    check('毕业成功提示', await waitFor(tab, `[...document.querySelectorAll('.el-message')].some((m) => m.innerText.includes('已毕业 3 名学生'))`, 15000));
    check('弹窗关闭', await waitFor(tab, `(() => {
      const d = document.querySelector('.class-graduate-dialog');
      return !d || d.offsetParent === null;
    })()`, 8000));
    await sleep(1500); // 名单刷新
    check('名单学籍列变「已毕业」', await tab.eval(`(() => {
      const rows = [...document.querySelectorAll('.el-table__row')];
      return rows.length === 3 && rows.every((r) => r.innerText.includes('已毕业'));
    })()`));
    await tab.shot('p4-03-admin-roster-graduated.png');

    // ===================== C. 撤销毕业 =====================
    await tab.eval(clickByText('button', '撤销毕业'));
    check('撤销确认框出现', await waitFor(tab, `(() => {
      const box = document.querySelector('.el-message-box');
      return !!box && box.getBoundingClientRect().height > 50;
    })()`, 6000));
    await sleep(400);
    await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.el-message-box .el-button--primary')][0];
      if (btn) btn.click();
    })()`);
    check('撤销成功提示', await waitFor(tab, `[...document.querySelectorAll('.el-message')].some((m) => m.innerText.includes('已撤销 3 名学生的毕业状态'))`, 15000));
    await sleep(1500);
    check('名单回到「在读」', await tab.eval(`(() => {
      const rows = [...document.querySelectorAll('.el-table__row')];
      return rows.length === 3 && rows.every((r) => r.innerText.includes('在读'));
    })()`));
    await tab.shot('p4-04-admin-roster-revoked.png');

    // ===================== D. 个别学籍变更：s1 毕业 =====================
    const s1 = SEED.users[0];
    check('s1 行存在', await tab.eval(`[...document.querySelectorAll('.el-table__row')].some((r) => r.innerText.includes(${JSON.stringify(s1.username)}))`));
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.innerText.includes(${JSON.stringify(s1.username)}));
      const btn = [...row.querySelectorAll('button')].find((b) => b.innerText.trim() === '学籍');
      if (btn) btn.click();
    })()`);
    check('学籍变更弹窗打开', await waitFor(tab, `(() => {
      const d = [...document.querySelectorAll('.el-dialog')].find((x) => x.innerText.includes('变更学籍状态'));
      return !!(d && d.getBoundingClientRect().height > 100);
    })()`, 6000));
    await sleep(500);
    await tab.eval(`(() => {
      const d = [...document.querySelectorAll('.el-dialog')].find((x) => x.innerText.includes('变更学籍状态'));
      const radio = [...d.querySelectorAll('.el-radio')].find((r) => r.innerText.trim() === '毕业');
      if (radio) radio.click();
    })()`);
    await sleep(300);
    await tab.eval(`(() => {
      const d = [...document.querySelectorAll('.el-dialog')].find((x) => x.innerText.includes('变更学籍状态'));
      const btn = [...d.querySelectorAll('.el-dialog__footer .el-button--primary')][0];
      if (btn) btn.click();
    })()`);
    check('学籍变更成功提示', await waitFor(tab, `[...document.querySelectorAll('.el-message')].some((m) => m.innerText.includes('学籍状态已更新'))`, 12000));
    await sleep(1500);
    check('名单中仅 s1 已毕业', await tab.eval(`(() => {
      const rows = [...document.querySelectorAll('.el-table__row')];
      const s1row = rows.find((r) => r.innerText.includes(${JSON.stringify(s1.username)}));
      const others = rows.filter((r) => !r.innerText.includes(${JSON.stringify(s1.username)}));
      return !!s1row && s1row.innerText.includes('已毕业') && others.every((r) => r.innerText.includes('在读'));
    })()`));
    await tab.shot('p4-05-admin-roster-s1-graduated.png');

    // ===================== E. 毕业生 s1：提交类全拦、学习类放行 =====================
    check('s1 登录', await login(tab, s1.username, PWD));

    await tab.send('Page.navigate', { url: `${BASE}/student/homework` });
    check('作业页渲染', await waitFor(tab, `document.querySelector('.student-row') !== null`, 25000));
    await sleep(1000);
    check('毕业生作业提交按钮禁用', await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.student-action-btn')].find((b) => b.innerText.includes('查看作业'));
      return !!btn && btn.disabled === true;
    })()`));
    check('禁用原因与后端 403 一致', await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('.student-action-btn')].find((b) => b.innerText.includes('查看作业'));
      return !!btn && (btn.title || '').includes('已毕业，不能提交作业');
    })()`));
    await tab.shot('p4-06-student-homework-gated.png');

    await tab.send('Page.navigate', { url: `${BASE}/student/exams` });
    check('考试页渲染', await waitFor(tab, `document.querySelector('.exam-row') !== null`, 25000));
    await sleep(1000);
    check('考试入口显示拦截原因', await hasText(tab, '已毕业，不能开始考试'));
    await tab.shot('p4-07-student-exam-gated.png');

    await tab.send('Page.navigate', { url: `${BASE}/student/qa` });
    check('问答页渲染', await waitFor(tab, `document.querySelector('.dock-textarea') !== null`, 25000));
    await sleep(1200);
    check('问答输入禁用', await tab.eval(`(() => {
      const ta = document.querySelector('.dock-textarea textarea');
      return !!ta && ta.disabled === true;
    })()`));
    check('placeholder 显示拦截原因', await tab.eval(`(() => {
      const ta = document.querySelector('.dock-textarea textarea');
      return !!ta && (ta.placeholder || '').includes('已毕业，不能提问');
    })()`));
    await tab.shot('p4-08-student-qa-gated.png');

    await tab.send('Page.navigate', { url: `${BASE}/student/learning` });
    check('学习页渲染（X-31 不拦毕业生）', await waitFor(tab, `document.querySelector('.learn-shell') !== null || document.body.innerText.includes('E2E-P4课程')`, 25000));
    await sleep(1200);
    check('毕业生仍看到课程', await hasText(tab, 'E2E-P4课程'));
    await tab.shot('p4-09-student-learning-visible.png');

    // ===================== F. 休学生 s3：学习入口关闭 =====================
    const s3 = SEED.users[2];
    const adminAgain = await api('POST', '/auth/login/', { username: 'admin', password: 'A0987654' });
    const sus = await api('POST', `/classes/${SEED.classId}/edu-status/`,
      { student: s3.id, edu_status: 'suspended', note: 'E2E 休学验证' },
      adminAgain.data.data.token.access);
    check('s3 置为休学（API）', sus.status === 200, String(sus.status));

    check('s3 登录', await login(tab, s3.username, PWD));
    await tab.send('Page.navigate', { url: `${BASE}/student/learning` });
    check('休学空状态出现', await waitFor(tab, `document.body.innerText.includes('休学中，暂不可学习')`, 25000));
    await sleep(600);
    check('休学提示含复学指引', await hasText(tab, '复学后课程与学习进度自动恢复'));
    await tab.shot('p4-10-student-learning-suspended.png');

    await tab.send('Page.navigate', { url: `${BASE}/student/homework` });
    check('休学生作业列表为空', await waitFor(tab, `document.body.innerText.includes('暂无作业')`, 20000));

    // ===================== G. 控制台 =====================
    const errs = tab.consoleErrors.filter((e) => !/favicon|ResizeObserver/.test(e));
    check('全程无 console.error / 页面异常', errs.length === 0, errs.slice(0, 3).join(' ; '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
    await cleanup();
  }

  log(`P4 E2E：通过 ${passes} 项，失败 ${failures} 项`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => { console.error('E2E 崩溃：', err); process.exit(2); });
