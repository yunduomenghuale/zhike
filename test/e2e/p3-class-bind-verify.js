#!/usr/bin/env node
/**
 * P3-4 E2E：教师选班抽屉（P1 偏差收口）——把自己的课挂进班级。
 *
 * 验证点：
 *   A 教师端班级行有「课程」入口（管理员看到的是编辑按钮，不走这个抽屉）
 *   B 抽屉列出我的全部课程，班内已挂的课显示「已加入」且不可再点
 *   C 勾选未挂的课 → 按钮文案计数正确 → 保存成功 → 行内课程名刷新
 *   D 重新打开抽屉，刚挂的课变成「已加入」（真的落库，不是本地态）
 *   E 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273、t101/pass1234
 * 运行：node test/e2e/p3-class-bind-verify.js
 * 收尾：脚本会删掉本次建立的班级-课程关联（不动其它数据）
 */
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const ROOT = path.resolve(__dirname, '../..');
const PYTHON = process.env.PYTHON_BIN || path.join(ROOT, 'backend/venv/Scripts/python.exe');
const SHOT_DIR = path.join(ROOT, 'test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9800 + (parseInt(RUN_ID, 36) % 150);
const PROFILE = `D:/tmp/zhike-p3-bind-e2e/run-${RUN_ID}`;
const CLASS_NAME = '数据结构兴趣班';
const COURSE_NAME = 'Java程序设计';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
let failures = 0;
let passes = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (ok) passes += 1; else failures += 1;
}

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

const DRAWER = '.class-bind-drawer';
const rowExpr = (name) => `[...document.querySelectorAll('.class-row')].find((r) => r.innerText.includes(${JSON.stringify(name)}))`;

function cleanupBinding(classId, courseId) {
  const py = `
import os, django, sys
sys.path.insert(0, r'${path.join(ROOT, 'backend').replace(/\\/g, '/')}')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from apps.classroom.models import ClassCourse
n, _ = ClassCourse.objects.filter(classroom_id=${classId}, course_id=${courseId}).delete()
print('已删除班级-课程关联：', n)
`;
  try {
    process.stdout.write(execFileSync(PYTHON, ['-c', py], { encoding: 'utf8' }));
  } catch (err) {
    console.log('清理关联失败，请手工删除：', err.message);
  }
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const { cdp: tab, chrome } = await launchChrome();
  let classId = null;
  let courseId = null;

  try {
    check('A0 教师登录', await login(tab, 't101', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/classes` });
    check('A1 班级列表加载', await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 20000));

    // 抓 classId / courseId 供收尾清理
    await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token');
      const headers = { Authorization: 'Bearer ' + token };
      const cRes = await fetch('/api/classes/?page_size=100', { headers });
      const cBody = await cRes.json();
      const cRows = (cBody.data?.results) || cBody.data || [];
      const cls = cRows.find((r) => r.name === ${JSON.stringify(CLASS_NAME)});
      window.__classId = cls ? cls.id : null;
      const kRes = await fetch('/api/courses/?page_size=100', { headers });
      const kBody = await kRes.json();
      const kRows = (kBody.data?.results) || kBody.data || [];
      const course = kRows.find((c) => c.name === ${JSON.stringify(COURSE_NAME)});
      window.__courseId = course ? course.id : null;
    })()`);
    classId = await tab.eval(`window.__classId`);
    courseId = await tab.eval(`window.__courseId`);

    const entry = await tab.eval(`(() => {
      const row = ${rowExpr(CLASS_NAME)};
      if (!row) return null;
      const btn = row.querySelector('.class-bind-entry');
      return { hasBtn: !!btn, actions: (row.querySelector('.class-actions') || {}).innerText || '' };
    })()`);
    check('A2 教师行有「课程」入口且无管理端编辑按钮',
      !!entry && entry.hasBtn && !entry.actions.includes('编辑'),
      JSON.stringify(entry));

    // 打开抽屉
    await tab.eval(`(() => { const btn = ${rowExpr(CLASS_NAME)}.querySelector('.class-bind-entry'); btn.click(); return true; })()`);
    const opened = await waitFor(tab, `(() => {
      const d = document.querySelector('${DRAWER}');
      return !!d && d.offsetParent !== null && d.querySelectorAll('.bind-item').length > 0;
    })()`, 20000);
    check('B1 选班抽屉打开并列出课程', opened);
    await sleep(600); // 等抽屉滑入动画结束再截图，否则截到半路的空框
    await tab.shot('p3-05-bind-drawer.png');

    const items = await tab.eval(`(() => {
      return [...document.querySelectorAll('${DRAWER} .bind-item')].map((i) => ({
        name: (i.querySelector('.bind-course-name') || {}).innerText || '',
        bound: i.classList.contains('is-bound'),
        tag: (i.querySelector('.el-tag') || {}).innerText || '',
        disabled: !!i.querySelector('.el-checkbox.is-disabled'),
      }));
    })()`);
    check('B2 列出全部课程', items.length >= 3, items.map((i) => i.name).join(' / '));
    const boundItem = items.find((i) => i.bound);
    check('B3 班内已挂课程显示「已加入」且不可再点',
      !!boundItem && boundItem.tag.includes('已加入') && boundItem.disabled,
      JSON.stringify(boundItem));
    const target = items.find((i) => i.name === COURSE_NAME);
    check(`B4 目标课程「${COURSE_NAME}」当前未挂且可选`, !!target && !target.bound && !target.disabled,
      JSON.stringify(target));

    // 勾选 + 保存
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('${DRAWER} .bind-item')]
        .find((i) => i.innerText.includes(${JSON.stringify(COURSE_NAME)}));
      const box = row.querySelector('.el-checkbox');
      (box || row).click();
      return true;
    })()`);
    await sleep(300);
    const btnText = await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('${DRAWER} button')]
        .find((b) => b.innerText.includes('加入'));
      return btn ? btn.innerText.trim() : '';
    })()`);
    check('C1 按钮文案反映勾选数量', btnText.includes('1 门课程'), btnText);

    await tab.eval(`(() => {
      const btn = [...document.querySelectorAll('${DRAWER} button')]
        .find((b) => b.innerText.includes('加入'));
      btn.click();
      return true;
    })()`);
    const closed = await waitFor(tab, `(() => {
      const d = document.querySelector('${DRAWER}');
      return !d || d.offsetParent === null;
    })()`, 20000);
    check('C2 保存后抽屉关闭', closed);

    const rowCourses = await waitFor(tab, `(() => {
      const row = ${rowExpr(CLASS_NAME)};
      return !!row && row.innerText.includes(${JSON.stringify(COURSE_NAME)});
    })()`, 20000);
    check('C3 班级行内课程名已刷新', rowCourses);

    // 重新打开抽屉，确认已落库
    await tab.eval(`(() => { const btn = ${rowExpr(CLASS_NAME)}.querySelector('.class-bind-entry'); btn.click(); return true; })()`);
    await waitFor(tab, `(() => {
      const d = document.querySelector('${DRAWER}');
      return !!d && d.offsetParent !== null && d.querySelectorAll('.bind-item').length > 0;
    })()`, 20000);
    const after = await tab.eval(`(() => {
      const row = [...document.querySelectorAll('${DRAWER} .bind-item')]
        .find((i) => i.innerText.includes(${JSON.stringify(COURSE_NAME)}));
      return row ? { bound: row.classList.contains('is-bound'), tag: (row.querySelector('.el-tag') || {}).innerText || '' } : null;
    })()`);
    check('D1 重开抽屉后该课为「已加入」（真落库）',
      !!after && after.bound && after.tag.includes('已加入'), JSON.stringify(after));
    await tab.shot('p3-06-bind-done.png');

    const errors = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('E1 全程无 console.error / 未捕获异常', errors.length === 0, errors.slice(0, 3).join(' | '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
    if (classId && courseId) {
      cleanupBinding(classId, courseId);
    } else {
      console.log('缺少 classId/courseId，未执行关联清理');
    }
  }

  console.log(`\n== 通过 ${passes} / 失败 ${failures} ==`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => { console.error('E2E 异常：', err); process.exit(1); });
