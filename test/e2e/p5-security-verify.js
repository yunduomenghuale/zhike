#!/usr/bin/env node
/**
 * P5 E2E：安全加固的浏览器级验证。
 *
 * 验证点：
 *   A 管理端班级管理：删除按钮已被「归档」替代（X-04），归档确认弹窗 + 状态列「已归档」
 *   B 管理端大模型配置页：AI 日配额卡片（P5-B6）+ Mock 回退告警条（P5-B7，24h 内有回退）
 *   C 学生端 AI 问答：provider 不可达回退后回答带「当前为模拟数据」角标（P5-B7）
 *   D 学生端 AI 问答：配额封禁后提问显示后端中文 429 提示（P5-B6）
 *   E 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273（项目根 node serve-local.js）、admin/A0987654
 * 数据：自建自清（E2EP5 前缀）；AI chat 配置先存原值、结束恢复；配额恢复 null
 * 运行：node test/e2e/p5-security-verify.js
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
const PROFILE = `D:/tmp/zhike-p5-e2e/run-${RUN_ID}`;
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

const SEED = { classId: null, courseId: null, users: [], originalChatConfig: null };

async function apiLogin() {
  const adminLogin = await api('POST', '/auth/login/', { username: 'admin', password: 'A0987654' });
  if (adminLogin.status !== 200) throw new Error('admin 登录失败：' + JSON.stringify(adminLogin.data));
  return adminLogin.data.data.token.access;
}

async function seed() {
  const admin = await apiLogin();
  const teacherLogin = await api('POST', '/auth/login/', { username: 't101', password: 'pass1234' });
  if (teacherLogin.status !== 200) throw new Error('t101 登录失败');
  const teacher = teacherLogin.data.data.token.access;

  const course = await api('POST', '/courses/', { name: `E2E-P5课程-${RUN_ID}`, intro: 'P5 E2E 专用' }, teacher);
  if (course.status !== 201) throw new Error('建课失败：' + JSON.stringify(course.data));
  SEED.courseId = course.data.data.id;

  const cls = await api('POST', '/classes/', {
    name: `E2E-P5班-${RUN_ID}`, code: `E2EP5${RUN_ID.toUpperCase()}`,
    courses: [SEED.courseId], enrollment_year: 2024, duration_years: 4,
  }, admin);
  if (cls.status !== 201) throw new Error('建班失败：' + JSON.stringify(cls.data));
  SEED.classId = cls.data.data.id;

  const u = await api('POST', '/admin-panel/users/', {
    username: `e2ep5_${RUN_ID}_s1`, real_name: 'E2ES1', role: 'student', password: PWD,
  }, admin);
  if (u.status !== 201) throw new Error('建学生失败：' + JSON.stringify(u.data));
  SEED.users.push({ id: u.data.data.id, username: u.data.data.username });
  const add = await api('POST', `/classes/${SEED.classId}/add-students-batch/`,
    { usernames: SEED.users.map((x) => x.username) }, admin);
  if (add.status !== 200) throw new Error('入班失败：' + JSON.stringify(add.data));

  // 记住当前 chat 配置（结束恢复）
  const cfg = await api('GET', '/admin-panel/ai-configuration/', undefined, admin);
  const chatItem = (cfg.data?.data?.items || []).find((i) => i.capability === 'chat');
  SEED.originalChatConfig = chatItem ? {
    capability: 'chat', provider: chatItem.provider, enabled: chatItem.enabled,
    base_url: chatItem.base_url || '', model_name: chatItem.model_name || '',
    // api_key 掩码不可逆：若原本有 key，恢复时留空（Key 留空=沿用已保存值）
    ...(chatItem.api_key_configured ? {} : { api_key: '' }),
  } : null;
}

// ---------------------------------------------------------------------------
// CDP 驱动（与 p1/p3/p4 同款）
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

async function askInQa(tab, question) {
  // 学生端 /student/qa：选课程 → 输入问题 → 发送
  await tab.send('Page.navigate', { url: `${BASE}/student/qa` });
  await waitFor(tab, `document.querySelector('.chat-list') !== null || document.body.innerText.includes('请先选择一门课程')`, 25000);
  await sleep(800);
  // 课程下拉（EP select）：点开 → 点选项
  await tab.eval(`document.querySelector('.chat-side, .chat-main, .qa-page, #app') && (() => {
    const sel = document.querySelector('.el-select__wrapper') || document.querySelector('.el-select');
    if (sel) sel.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return !!sel;
  })()`);
  await waitFor(tab, `document.querySelector('.el-select-dropdown__item') && document.querySelector('.el-select-dropdown__item').getBoundingClientRect().height > 0`, 8000);
  await sleep(300);
  await tab.eval(`(() => {
    const item = [...document.querySelectorAll('.el-select-dropdown__item')]
      .find((i) => i.innerText.includes('E2E-P5课程'));
    if (item) { item.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true; }
    return false;
  })()`);
  await sleep(600);
  await tab.eval(`(() => {
    const ta = document.querySelector('.dock-textarea textarea') || document.querySelector('textarea');
    ta.value = ${JSON.stringify(question)};
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(200);
  await tab.eval(`(() => {
    const ta = document.querySelector('.dock-textarea textarea') || document.querySelector('textarea');
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    return true;
  })()`);
}

async function cleanup() {
  try {
    const admin = await apiLogin();
    // AI chat 配置恢复原值；配额恢复不限
    if (SEED.originalChatConfig) {
      await api('PUT', '/admin-panel/ai-configuration/', { capabilities: [SEED.originalChatConfig] }, admin);
    }
    await api('PUT', '/admin-panel/ai-quota/', { default_daily_limit: null, overrides: [] }, admin);
    // 班级归档态恢复 active，再按 PROTECT 顺序清数据
    if (SEED.classId) await api('PATCH', `/classes/${SEED.classId}/`, { status: 'active' }, admin);
    // 学生停用恢复（避免名单页遗留停用者）
    for (const u of SEED.users) {
      await api('PATCH', `/admin-panel/users/${u.id}/`, { is_active: true, edu_status: 'enrolled' }, admin);
    }
    // 班/人/课清理：API 不提供班级删除（P5-B5 正是本阶段改动），物理清理走
    // python 临时脚本（queryset 通道，X-04 保留的运维通道语义）
    if (SEED.classId) {
      const { execSync } = require('child_process');
      const pyFile = path.join(ROOT, 'backend', `p5_e2e_cleanup_${RUN_ID}.py`);
      fs.writeFileSync(pyFile, `
import os, sys, django
sys.path.insert(0, r'${ROOT}\\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from apps.classroom.models import ClassRoom, ClassStudent
from apps.users.models import User
from apps.courses.models import Course
rooms = ClassRoom.objects.filter(code__startswith='E2EP5')
for room in rooms:
    ClassStudent.objects.filter(classroom=room).delete()
    room.course_links.all().delete()
    rooms.filter(pk=room.pk).delete()
User.objects.filter(username__startswith='e2ep5_').delete()
for stale in Course.objects.filter(name__startswith='E2E-P5课程'):
    try:
        stale.delete()
    except Exception as e:
        print('course skip:', e)
print('cleanup ok')
`);
      try {
        const out = execSync(
          `"${ROOT}/backend/venv/Scripts/python.exe" "${pyFile}"`,
          { cwd: ROOT, stdio: 'pipe', timeout: 60000 },
        ).toString();
        fs.unlinkSync(pyFile);
        log('ORM 清理：' + out.trim().split('\n').pop());
      } catch (e) {
        log('ORM 清理失败（留待手工）：' + e.message.slice(0, 200));
      }
    }
  } catch (e) {
    log('清理异常：' + e.message);
  }
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  await seed();
  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // ===================== A. 管理端班级管理：删除→归档 =====================
    check('管理员登录', await login(tab, 'admin', 'A0987654'));
    await tab.send('Page.navigate', { url: `${BASE}/admin/classes` });
    check('班级管理页渲染', await waitFor(tab, `document.querySelectorAll('.class-actions').length > 0`, 25000));
    await sleep(1200);
    check('没有「删除班级」按钮', await tab.eval(`![...document.querySelectorAll('button')].some((b) => (b.title || b.getAttribute('aria-label') || b.innerText) === '删除班级')`));
    check('有「归档班级」按钮', await tab.eval(`[...document.querySelectorAll('button')].some((b) => b.title === '归档班级')`));
    // 分页查找本班卡片（列表按课程名等排序，新建班不一定在第一页），
    // 找到后点它的归档按钮；弹窗内校验班名守卫，绝不碰其他班
    const OUR_CLASS = `E2E-P5班-${RUN_ID}`;
    let opened = false;
    for (let page = 1; page <= 15 && !opened; page++) {
      await tab.eval(`(() => {
        const li = [...document.querySelectorAll('.el-pagination .el-pager li')]
          .find((x) => x.innerText.trim() === '${page}');
        if (li) { li.click(); return true; }
        return false;
      })()`);
      await sleep(700);
      opened = await tab.eval(`(() => {
        const card = [...document.querySelectorAll('article')].find((c) => c.innerText.includes('${OUR_CLASS}'));
        if (!card) return false;
        const btn = [...card.querySelectorAll('button')].find((b) => b.title === '归档班级');
        if (btn) { btn.click(); return true; }
        return false;
      })()`);
    }
    check('定位到本班并点开归档弹窗', opened);
    check('归档确认弹窗出现', await waitFor(tab, `(() => {
      const btns = [...document.querySelectorAll('.el-message-box, .el-dialog, .el-overlay')];
      return btns.some((d) => d.getBoundingClientRect().height > 0 && d.innerText.includes('归档班级') && d.innerText.includes('${OUR_CLASS}'));
    })()`, 8000));
    const dlgText = await tab.eval(`(() => { const b = [...document.querySelectorAll('.el-message-box, .el-dialog')].find((d) => d.getBoundingClientRect().height > 0 && d.innerText.includes('归档')); return b ? b.innerText : ''; })()`);
    check('弹窗确认对象是本班（守卫）', dlgText.includes(OUR_CLASS), dlgText.slice(0, 90));
    check('弹窗文案为归档语义（不支持物理删除）', dlgText.includes('不支持物理删除') || dlgText.includes('历史成绩与学籍完整保留'), dlgText.slice(0, 100));
    await tab.shot('p5-01-class-archive-dialog.png');
    await tab.eval(`(() => { const b = [...document.querySelectorAll('.el-message-box button, .el-dialog button')].find((x) => x.innerText.includes('确认归档')); if (b) b.click(); return !!b; })()`);
    check('归档成功提示', await waitFor(tab, `document.body.innerText.includes('已归档')`, 8000));
    await sleep(800);
    check('本班卡片状态变「已归档」', await tab.eval(`[...document.querySelectorAll('article')].some((c) => c.innerText.includes('${OUR_CLASS}') && c.innerText.includes('已归档'))`));
    await tab.shot('p5-02-class-archived.png');
    // 恢复 active 供后续清理
    const adminTok = await apiLogin();
    await api('PATCH', `/classes/${SEED.classId}/`, { status: 'active' }, adminTok);

    // ===================== B. 触发一次真实 Mock 回退（供 B/C 用） =====================
    await api('PUT', '/admin-panel/ai-configuration/', {
      capabilities: [{
        capability: 'chat', provider: 'openai', enabled: true,
        base_url: 'http://127.0.0.1:9', model_name: 'e2ep5-unreachable',
        api_key: 'sk-e2ep5', timeout: 5,
      }],
    }, adminTok);
    const s1 = SEED.users[0];
    const sLogin = await api('POST', '/auth/login/', { username: s1.username, password: PWD });
    const sTok = sLogin.data.data.token.access;
    await api('POST', '/qa-records/ask/', { course: SEED.courseId, question: 'E2E 回退预热' }, sTok);

    // ===================== B2. 管理端 AI 设置页 =====================
    await tab.send('Page.navigate', { url: `${BASE}/admin/ai-settings` });
    check('AI 设置页渲染', await waitFor(tab, `document.body.innerText.includes('当前生效配置')`, 25000));
    await sleep(1200);
    check('AI 日配额卡片存在（B6）', await hasText(tab, 'AI 日配额'));
    check('配额输入框与保存按钮', await tab.eval(`!!document.querySelector('.quota-card .el-input-number') && [...document.querySelectorAll('.quota-card button')].some((b) => b.innerText.includes('保存配额'))`));
    check('Mock 回退告警条可见（B7）', await waitFor(tab, `(() => { const a = document.querySelector('.mock-fallback-alert'); return !!(a && a.getBoundingClientRect().height > 0 && a.innerText.includes('Mock 回退')); })()`, 10000));
    await tab.shot('p5-03-admin-ai-settings.png');

    // ===================== C. 学生端问答：模拟数据角标 =====================
    check('学生登录', await login(tab, s1.username, PWD));
    await askInQa(tab, 'E2E 回退角标验证');
    check('回答完成', await waitFor(tab, `document.querySelector('.answer-md') && document.querySelector('.answer-md').innerText.trim().length > 0`, 40000));
    check('「模拟数据」角标出现（B7）', await waitFor(tab, `(() => { const n = document.querySelector('.qa-note.mock-note'); return !!(n && n.getBoundingClientRect().height > 0 && n.innerText.includes('模拟数据')); })()`, 10000));
    await tab.shot('p5-04-qa-mock-badge.png');

    // ===================== D. 学生端问答：配额 429 提示 =====================
    await api('PUT', '/admin-panel/ai-quota/', { default_daily_limit: 0, overrides: [] }, adminTok);
    await sleep(500);
    await askInQa(tab, 'E2E 配额封禁验证');
    check('后端 429 中文提示透出（B6）', await waitFor(tab, `document.body.innerText.includes('今日 AI 调用次数已达上限')`, 20000));
    await tab.shot('p5-05-qa-quota-429.png');

    // ===================== E. 控制台 =====================
    const errs = tab.consoleErrors.filter((e) => !/favicon|ResizeObserver/.test(e));
    check('全程无 console.error / 页面异常', errs.length === 0, errs.slice(0, 3).join(' ; '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
    await cleanup();
  }

  log(`P5 E2E：通过 ${passes} 项，失败 ${failures} 项`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => { console.error('E2E 崩溃：', err); process.exit(2); });
