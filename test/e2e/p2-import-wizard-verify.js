#!/usr/bin/env node
/**
 * P2 E2E：三类批量导入的浏览器全链（上传 → 预览 → 确认 → 结果 → 下载）。
 *
 * 验证点（对应任务规范 §4 P2）：
 *   A 管理端「用户管理」有批量导入入口，可导入教师（预览统计 + 结果页 + 密码表下载）
 *   B 导入学生：预览出现「待建班级」清单；未勾选直接提交被拦；勾选后建班入班
 *   C 结果页：新建班级展示、失败行下载、初始密码表下载且内容符合 Zk+后6位
 *   D 管理端「班级管理」可导入班级；待修正行需勾选「跳过」才放行；失败行文件可下载
 *   E 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005（可用临时库）、前端 5273（node serve-local.js）、admin/A0987654
 * 运行：node test/e2e/p2-import-wizard-verify.js
 */
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const ROOT = path.resolve(__dirname, '../..');
const PYTHON = process.env.PYTHON_BIN || path.join(ROOT, 'backend/venv/Scripts/python.exe');
const SHOT_DIR = path.join(ROOT, 'test/screenshots');
const FIXTURE_DIR = path.join(ROOT, 'test/e2e/fixtures/p2-run');
const DL_DIR = path.join('D:/tmp', `p2-downloads-${process.pid}`);
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
// 账号规则：学号/工号 6~8 位且仅字母数字 → TAG 固定 5 位，
// 学号 = TAG+两位序号（7 位）、工号 = T+TAG+序号（7 位）、管理员 = TAG+角色字母（6 位）；
// 班级编码用 TAG-xx（8 位，编码规则允许短横线，不受学号规则影响）
const TAG = `P2${Date.now().toString(36).slice(-3).toUpperCase()}`;
const PORT = 9800 + (parseInt(RUN_ID, 36) % 150);
const PROFILE = `D:/tmp/zhike-p2-e2e/run-${RUN_ID}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
const log = (msg) => console.log(`[${stamp()}] ${msg}`);
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

// ---- 用 API 建独立管理员：避开 admin_heavy 5 次/分（限流按 user.pk 计数） ----
async function apiLogin(username, password) {
  const res = await fetch(`${BASE}/api/auth/login/`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const body = await res.json();
  const data = body.data || body;
  return (data.token || {}).access || data.access;
}

async function makeAdmin(token, tag) {
  const username = `p2e2e${tag}`;
  const password = 'pw123456';
  await fetch(`${BASE}/api/admin-panel/users/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ username, real_name: 'E2E导入', role: 'admin', password, is_active: true }),
  });
  return { username, password };
}

// ---- 上传：DOM.setFileInputFiles + change 事件 ----
async function uploadFile(tab, selector, filePath) {
  const docDom = await tab.send('DOM.getDocument', { depth: -1 });
  const q = await tab.send('DOM.querySelector', { nodeId: docDom.root.nodeId, selector });
  if (!q.nodeId) throw new Error('找不到文件输入框: ' + selector);
  await tab.send('DOM.setFileInputFiles', { files: [filePath], nodeId: q.nodeId });
  await sleep(200);
  // setFileInputFiles 不保证派发 change（版本行为不同），显式补一次；
  // 若 Element Plus 已在 set 时自行消费了文件，input 会被卸载，这里用兜底选择器容错。
  await tab.eval(`(() => {
    const list = [...document.querySelectorAll('input[type="file"]')];
    const input = document.querySelector(${JSON.stringify(selector)}) || list[list.length - 1];
    if (!input) return false;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
}

const WZ = '.import-wizard';
const dlgText = `(() => { const d = document.querySelector('${WZ}'); return d ? d.innerText : ''; })()`;

function clickButtonByText(tab, text, scope) {
  return tab.eval(`(() => {
    const root = ${scope ? `document.querySelector('${scope}')` : 'document'};
    if (!root) return false;
    const btn = [...root.querySelectorAll('button')].find((b) => b.innerText.trim().includes(${JSON.stringify(text)}));
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
}

async function openImportMenu(tab, itemText) {
  const opened = await tab.eval(`(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.innerText.trim().startsWith('批量导入'));
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
  if (!opened) return false;
  const ready = await waitFor(tab, `(() => {
    const items = [...document.querySelectorAll('.el-dropdown-menu__item')];
    return items.some((i) => i.getBoundingClientRect().height > 0);
  })()`, 8000);
  if (!ready) return false;
  return tab.eval(`(() => {
    const item = [...document.querySelectorAll('.el-dropdown-menu__item')]
      .find((i) => i.innerText.includes(${JSON.stringify(itemText)}));
    if (!item) return false;
    item.click();
    return true;
  })()`);
}

async function closeWizard(tab) {
  await clickButtonByText(tab, '关闭', WZ);
  await sleep(150);
  await clickButtonByText(tab, '取消', WZ);
  await sleep(600);
}

function readXlsx(filePath) {
  const code = `
import json, sys
from openpyxl import load_workbook
wb = load_workbook(sys.argv[1])
ws = wb.worksheets[0]
print(json.dumps([[c for c in row] for row in ws.iter_rows(values_only=True)], ensure_ascii=False))
`;
  const out = execFileSync(PYTHON, ['-c', code, filePath], { encoding: 'utf8' });
  return JSON.parse(out.trim());
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function waitFile(dir, matcher, timeoutMs = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (fs.existsSync(dir)) {
      const hit = fs.readdirSync(dir).find((name) => matcher(name) && !name.endsWith('.crdownload'));
      if (hit) return path.join(dir, hit);
    }
    sleepSync(200);
  }
  return null;
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.mkdirSync(DL_DIR, { recursive: true });
  fs.rmSync(FIXTURE_DIR, { recursive: true, force: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  log(`生成夹具 tag=${TAG}`);
  execFileSync(PYTHON, [path.join(__dirname, 'fixtures/make_p2_import_fixtures.py'), TAG, FIXTURE_DIR], { stdio: 'inherit' });

  const adminToken = await apiLogin('admin', 'A0987654');
  const adminTeacher = await makeAdmin(adminToken, `${TAG}T`);
  const adminStudent = await makeAdmin(adminToken, `${TAG}S`);
  const adminClass = await makeAdmin(adminToken, `${TAG}C`);
  log(`独立管理员：${adminTeacher.username} / ${adminStudent.username} / ${adminClass.username}`);

  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await tab.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL_DIR });

    // ================= A. 教师导入 =================
    check('A1 管理员登录', await login(tab, adminTeacher.username, adminTeacher.password));
    await tab.send('Page.navigate', { url: `${BASE}/admin/users` });
    check('A2 用户管理页渲染', await waitFor(tab, `document.querySelector('.user-table') !== null`, 25000));
    await sleep(600);

    check('A3 打开「批量导入」下拉并选中教师', await openImportMenu(tab, '导入教师'));
    check('A4 向导弹出且标题正确', await waitFor(tab, `(() => {
      const d = document.querySelector('${WZ}');
      return d && d.getBoundingClientRect().height > 100 && d.innerText.includes('批量导入教师');
    })()`, 8000));
    const uploadStep = await tab.eval(dlgText);
    check('A5 上传页含模板下载与填写要点', uploadStep.includes('下载教师导入模板') && uploadStep.includes('初始密码'), '');
    await tab.shot('p2-01-teacher-upload.png');

    await uploadFile(tab, `${WZ} input[type=file]`, path.join(FIXTURE_DIR, 'teachers.xlsx'));
    check('A6 进入预览页', await waitFor(tab, `!!document.querySelector('${WZ} .wz-preview')`, 20000));
    const previewTeacher = await tab.eval(dlgText);
    check('A7 预览统计：共 2 行 / 可导入 2', previewTeacher.includes('共 2 行') && previewTeacher.includes('可导入 2'),
      previewTeacher.replace(/\n+/g, ' / ').slice(0, 120));
    check('A8 教师无待建班级区块', await tab.eval(`!document.querySelector('${WZ} .wz-pending-table')`));
    await tab.shot('p2-02-teacher-preview.png');

    await clickButtonByText(tab, '确认导入', WZ);
    check('A9 进入结果页', await waitFor(tab, `!!document.querySelector('${WZ} .wz-result')`, 20000));
    const resultTeacher = await tab.eval(dlgText);
    check('A10 结果：新建 2 个账号', /2\s*新建账号/.test(resultTeacher.replace(/\n/g, ' ')) || resultTeacher.includes('新建 2 个账号'),
      resultTeacher.replace(/\n+/g, ' / ').slice(0, 160));
    check('A11 结果页有初始密码表下载按钮', await tab.eval(`!!document.querySelector('${WZ} .wz-dl-password')`));
    check('A12 教师导入无失败行下载', await tab.eval(`!document.querySelector('${WZ} .wz-dl-failure')`));
    await tab.shot('p2-03-teacher-result.png');

    await tab.eval(`document.querySelector('${WZ} .wz-dl-password').click()`);
    const teacherPwdFile = waitFile(DL_DIR, (n) => n.includes('initial_passwords_teacher'));
    check('A13 初始密码表真的下载下来了', !!teacherPwdFile, teacherPwdFile || '未出现文件');
    if (teacherPwdFile) {
      const sheet = readXlsx(teacherPwdFile);
      check('A14 密码表表头正确', JSON.stringify(sheet[0]) === JSON.stringify(['工号', '姓名', '初始密码']),
        JSON.stringify(sheet[0]));
      const row = sheet[1] || [];
      check('A15 密码规则 Zk+工号后6位', String(row[2]) === 'Zk' + String(row[0]).slice(-6),
        `${row[0]} → ${row[2]}`);
    }
    await closeWizard(tab);

    // ================= B. 学生导入（自动建班 + 未勾选被拦） =================
    check('B1 换学生导入管理员登录', await login(tab, adminStudent.username, adminStudent.password));
    await tab.send('Page.navigate', { url: `${BASE}/admin/users` });
    check('B2 用户管理页渲染', await waitFor(tab, `document.querySelector('.user-table') !== null`, 25000));
    await sleep(600);

    check('B3 选中「导入学生」', await openImportMenu(tab, '导入学生'));
    check('B4 向导标题为学生', await waitFor(tab, `(() => {
      const d = document.querySelector('${WZ}');
      return d && d.getBoundingClientRect().height > 100 && d.innerText.includes('批量导入学生');
    })()`, 8000));

    await uploadFile(tab, `${WZ} input[type=file]`, path.join(FIXTURE_DIR, 'students_auto.xlsx'));
    check('B5 进入预览并出现待建班级清单', await waitFor(tab, `!!document.querySelector('${WZ} .wz-pending-table')`, 20000));
    const previewStudent = await tab.eval(dlgText);
    check('B6 待建班级 1 个 / 3 人', previewStudent.includes(`待建班级 1 个 / 3 人`),
      previewStudent.replace(/\n+/g, ' / ').slice(0, 200));
    check('B7 待建清单里有编码', previewStudent.includes(`${TAG}-51`), '');
    check('B8 默认未勾选', await tab.eval(`(() => {
      const t = document.querySelector('${WZ} .wz-pending-table .el-table__body');
      const box = t && t.querySelector('.el-checkbox__original');
      return !!(box && !box.checked);
    })()`));
    await tab.shot('p2-04-student-preview.png');

    // B9 未勾选直接提交 → 二次确认 → 继续导入仍被后端拒绝
    await clickButtonByText(tab, '确认导入', WZ);
    const confirmUp = await waitFor(tab, `(() => {
      const box = document.querySelector('.el-message-box');
      return !!(box && box.getBoundingClientRect().height > 0 && box.innerText.includes('未确认的班级'));
    })()`, 8000);
    check('B9 未勾选时弹二次确认', confirmUp);
    if (confirmUp) {
      await tab.eval(`(() => {
        const box = document.querySelector('.el-message-box');
        const btn = [...box.querySelectorAll('button')].find((b) => b.innerText.trim() === '继续导入');
        if (btn) btn.click();
      })()`);
      const blocked = await waitFor(tab, `(() => {
        const msg = document.querySelector('.el-message--error');
        return !!(msg && msg.innerText.length > 0);
      })()`, 15000);
      check('B10 未勾选提交被拒绝（错误提示）', blocked);
      check('B11 仍停留在预览页', await tab.eval(`!!document.querySelector('${WZ} .wz-preview')`));
      await sleep(400);
    }

    // B12 勾选后提交成功
    await tab.eval(`(() => {
      const t = document.querySelector('${WZ} .wz-pending-table .el-table__body');
      const label = t && t.querySelector('.el-checkbox');
      if (label) label.click();
    })()`);
    await sleep(400);
    const checked = await tab.eval(`(() => {
      const t = document.querySelector('${WZ} .wz-pending-table .el-table__body');
      const box = t && t.querySelector('.el-checkbox__original');
      return !!(box && box.checked);
    })()`);
    check('B12 勾选待建班级生效', checked);

    await clickButtonByText(tab, '确认导入', WZ);
    check('B13 进入结果页', await waitFor(tab, `!!document.querySelector('${WZ} .wz-result')`, 25000));
    const resultStudent = await tab.eval(dlgText);
    check('B14 结果：新建 1 个班级', resultStudent.includes('新建 1 个班级'),
      resultStudent.replace(/\n+/g, ' / ').slice(0, 200));
    check('B15 结果：3 人入班', resultStudent.includes('3 人已入班'), '');
    check('B16 结果页列出新建班级', resultStudent.includes(`${TAG}-51`), '');
    check('B17 有初始密码表下载', await tab.eval(`!!document.querySelector('${WZ} .wz-dl-password')`));
    await tab.shot('p2-05-student-result.png');

    await tab.eval(`document.querySelector('${WZ} .wz-dl-password').click()`);
    const studentPwd = waitFile(DL_DIR, (n) => n.includes('initial_passwords_student'));
    check('B18 学生初始密码表下载成功', !!studentPwd, studentPwd || '未出现文件');
    if (studentPwd) {
      const sheet = readXlsx(studentPwd);
      const row = sheet[1] || [];
      check('B19 密码表含班级列且填了班名', sheet[0][2] === '班级' && row[2] === 'E2E新建班',
        JSON.stringify(sheet[0]));
      check('B20 密码规则 Zk+学号后6位', String(row[3]) === 'Zk' + String(row[0]).slice(-6),
        `${row[0]} → ${row[3]}`);
    }
    await closeWizard(tab);

    // ================= C. 班级导入（错误行 + 跳过） =================
    check('C1 换班级导入管理员登录', await login(tab, adminClass.username, adminClass.password));
    await tab.send('Page.navigate', { url: `${BASE}/admin/classes` });
    check('C2 班级管理页渲染', await waitFor(tab, `document.querySelectorAll('.class-row').length > 0`, 25000));
    await sleep(500);
    check('C3 有「批量导入班级」按钮', await tab.eval(`[...document.querySelectorAll('button')].some((b) => b.innerText.includes('批量导入班级'))`));

    await clickButtonByText(tab, '批量导入班级');
    check('C4 班级向导弹出', await waitFor(tab, `(() => {
      const d = document.querySelector('${WZ}');
      return d && d.getBoundingClientRect().height > 100 && d.innerText.includes('批量导入班级');
    })()`, 8000));

    await uploadFile(tab, `${WZ} input[type=file]`, path.join(FIXTURE_DIR, 'classes.xlsx'));
    check('C5 进入预览', await waitFor(tab, `!!document.querySelector('${WZ} .wz-preview')`, 20000));
    const previewClass = await tab.eval(dlgText);
    check('C6 统计：共 27 行 / 可导入 24 / 跳过 2 / 待修正 1',
      previewClass.includes('共 27 行') && previewClass.includes('可导入 24')
      && previewClass.includes('跳过 2') && previewClass.includes('待修正 1'),
      previewClass.replace(/\n+/g, ' / ').slice(0, 220));
    check('C7 出现「跳过待修正」开关', await tab.eval(`!!document.querySelector('${WZ} .wz-skip-invalid')`));
    await tab.shot('p2-06-class-preview.png');

    // C8 未勾跳过 → 点确认导入应被前端拦住（提示而不是请求）
    await clickButtonByText(tab, '确认导入', WZ);
    const warn = await waitFor(tab, `(() => {
      const msg = document.querySelector('.el-message--warning, .el-message--error');
      return !!(msg && msg.innerText.includes('待修正'));
    })()`, 8000);
    check('C8 未勾选跳过时提示待修正行', warn);
    check('C9 仍在预览页', await tab.eval(`!!document.querySelector('${WZ} .wz-preview')`));

    await tab.eval(`(() => {
      // class 落在 el-checkbox 的根 label 上，根自身就是可点区域
      const box = document.querySelector('${WZ} .wz-skip-invalid');
      if (!box) return false;
      (box.querySelector('.el-checkbox') || box).click();
      return true;
    })()`);
    await sleep(300);
    check('C10 勾选「跳过待修正」生效', await tab.eval(`(() => {
      const o = document.querySelector('${WZ} .wz-skip-invalid .el-checkbox__original');
      return !!(o && o.checked);
    })()`));

    await clickButtonByText(tab, '确认导入', WZ);
    check('C11 进入结果页', await waitFor(tab, `!!document.querySelector('${WZ} .wz-result')`, 25000));
    const resultClass = await tab.eval(dlgText);
    check('C12 结果：新建 24 个班级', resultClass.includes('新建 24 个班级'),
      resultClass.replace(/\n+/g, ' / ').slice(0, 200));
    check('C13 结果：1 行未能导入', resultClass.includes('1 行未能导入'), '');
    check('C14 有失败行下载按钮', await tab.eval(`!!document.querySelector('${WZ} .wz-dl-failure')`));
    await tab.shot('p2-07-class-result.png');

    await tab.eval(`document.querySelector('${WZ} .wz-dl-failure').click()`);
    const failFile = waitFile(DL_DIR, (n) => n.includes('import_failures_class'));
    check('C15 失败行文件下载成功', !!failFile, failFile || '未出现文件');
    if (failFile) {
      const sheet = readXlsx(failFile);
      check('C16 失败行文件含「错误原因」列', sheet[0][sheet[0].length - 1] === '错误原因',
        JSON.stringify(sheet[0]));
      check('C17 失败行文件只有 1 条数据', sheet.length === 2, String(sheet.length));
    }
    await closeWizard(tab);

    // C18 列表已刷新：导入 24 个班后总数跨页，应自动停在末页（最新建的班在末尾）
    const LAST_CODE = `${TAG}-24`;
    const LAST_NAME = 'E2E计算机2424班';
    await waitFor(tab, `document.body.innerText.includes('${LAST_CODE}')`, 20000);
    const c18 = await tab.eval(`(() => ({
      rows: document.querySelectorAll('.class-row').length,
      pager: (document.querySelector('.class-pager') || {}).innerText || '',
      active: (document.querySelector('.class-pager .el-pager .is-active') || {}).innerText || '',
      has: document.body.innerText.includes('${LAST_CODE}'),
      path: location.pathname,
    }))()`);
    check('C18 末页可见最新导入的班级', c18.has, JSON.stringify(c18));
    check('C18b 班级列表有分页且停在末页（否则导完看不到新班）',
      !!c18.pager && c18.active !== '', JSON.stringify({ pager: c18.pager, active: c18.active }));

    // C19 从末页进名单：班级多到翻页时，名单页不能靠「列表里找一下」拿班名
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.class-row')]
        .find((r) => r.innerText.includes('${LAST_CODE}'));
      if (!row) return false;
      const btn = [...row.querySelectorAll('button')].find((b) => b.innerText.trim() === '学生');
      if (btn) btn.click();
      return !!btn;
    })()`);
    check('C19 进入名单页', await waitFor(tab, `location.pathname.includes('/students')`, 15000));
    const rosterOk = await waitFor(tab,
      `document.body.innerText.includes('${LAST_NAME}')`, 15000);
    check('C20 名单页能显示末页班级的班名', rosterOk);
    await tab.shot('p2-08-class-roster.png');

    // ================= E. 前端零报错 =================
    const errors = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('E1 全程无 console.error / 未捕获异常', errors.length === 0, errors.slice(0, 3).join(' | '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
  }

  console.log(`\n== 通过 ${passes} / 失败 ${failures} ==`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => { console.error('E2E 异常：', err); process.exit(1); });
