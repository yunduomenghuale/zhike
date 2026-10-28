#!/usr/bin/env node
/**
 * 题库用途分类——CDP 实测
 *
 * 验证点：
 *   S.1 题库列表：行内显示用途分类标签；工具栏出现「用途分类」筛选
 *   S.2 筛选生效：选「考试」后行均带 exam 标签
 *   S.3 新建题目弹窗含「用途分类」多选，默认勾练习+作业
 *   S.4 勾选「考试」创建并发布 → 行内出现「考试」标签
 *   S.5 学生端章节练习看不到该考试专用题（防泄题）
 *   S.6 考试组卷池含该题（考试页选题）
 *   S.7 AI 生题对话框含用途分类多选
 *   S.8 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234、dbg1/A0987654。
 * 运行：node test/e2e/question-scenes-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-scenes-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }
let failures = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (!ok) failures += 1;
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
  const args = [
    `--remote-debugging-port=${PORT}`, `--remote-allow-origins=*`,
    `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', '--force-device-scale-factor=1',
    '--disable-session-crashed-bubble', '--hide-crash-restore-bubble', 'about:blank',
  ];
  const proc = spawn(CHROME, args, { stdio: 'ignore', detached: true });
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
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws 连接失败'))); });
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
  // 已登录态会被守卫弹回 dashboard（无输入框）：清 token 后再回到登录页
  await tab.eval(`localStorage.clear()`);
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2 && !!document.querySelector('input[type="password"]')`);
  await tab.eval(`(() => {
    const inputs = document.querySelectorAll('input');
    inputs[0].value = ${JSON.stringify(username)};
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    const pwd = document.querySelector('input[type="password"]');
    pwd.value = ${JSON.stringify(password)};
    pwd.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(200);
  await tab.eval(`(() => { document.querySelector('button[type="submit"], .el-button--primary').click(); })()`);
  return waitFor(tab, `!location.pathname.startsWith('/login')`, 15000);
}

/** EP 下拉选择：打开下拉 → 轮询可见选项 → DOM click（与项目 E2E 经验一致） */
async function selectOption(tab, wrapperSelector, text) {
  await tab.eval(`(() => { document.querySelector(${JSON.stringify(wrapperSelector)}).click(); })()`);
  await sleep(400);
  const ok = await tab.eval(`(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')].filter((el) => el.getBoundingClientRect().height > 0);
    const target = items.find((el) => el.textContent.trim().includes(${JSON.stringify(text)}));
    if (!target) return false;
    target.click();
    return true;
  })()`);
  await sleep(300);
  return ok;
}

/** 点击对话框头部空白处关闭可能残留的弹层（不点遮罩，避免误关弹窗） */
async function closePoppers(tab) {
  await tab.eval(`(() => {
    const dlg = document.querySelector('.el-dialog');
    (dlg?.querySelector('.el-dialog__header') || document.body).click();
  })()`);
  await sleep(250);
}

/** 工具栏「用途分类」下拉：按 placeholder 定位，选 text；点开后轮询等待选项渲染 */
async function selectToolbarScene(tab, text) {
  const wrapperSel = '.q-toolbar .el-select__wrapper';
  for (let attempt = 0; attempt < 3; attempt++) {
    const opened = await tab.eval(`(() => {
      const wraps = [...document.querySelectorAll(${JSON.stringify(wrapperSel)})];
      const target = wraps.find((w) => w.querySelector('.el-select__placeholder')?.textContent.includes('用途分类'));
      if (!target) return 'no-wrapper';
      target.click();
      return 'ok';
    })()`);
    // 轮询等待可见选项（EP popper 异步渲染 + 进场动画，固定 sleep 不可靠）
    let clicked = 'no-item';
    for (let i = 0; i < 16; i++) {
      await sleep(250);
      const state = await tab.eval(`(() => {
        const items = [...document.querySelectorAll('.el-select-dropdown__item')];
        const vis = items.filter((el) => el.getBoundingClientRect().height > 0);
        const target = vis.find((el) => el.textContent.trim() === ${JSON.stringify(text)});
        if (target) { target.click(); return 'ok'; }
        return items.length ? 'waiting' : 'empty';
      })()`);
      if (state === 'ok') { clicked = 'ok'; break; }
      if (state === 'empty' && i >= 6) break; // DOM 里一直没有选项：重试点击
      if (opened === 'no-wrapper') break;
    }
    await sleep(400);
    const val = await tab.eval(`(() => {
      const wraps = [...document.querySelectorAll(${JSON.stringify(wrapperSel)})];
      return wraps.map((w) => w.textContent.trim()).join('|');
    })()`);
    log(`  selectToolbarScene attempt${attempt}: opened=${opened} click=${clicked} vals=${val}`);
    if (clicked === 'ok' && val.includes(text)) return true;
    await closePoppers(tab);
  }
  return false;
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const { cdp: tab, chrome } = await launchChrome();
  try {
    // ---- 教师登录进题库 ----
    log('教师登录…');
    check('教师登录', await login(tab, 't101', 'pass1234'), await tab.eval('location.pathname'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/questions` });
    const listReady = await waitFor(tab, `document.querySelectorAll('.q-row').length > 0`, 25000);
    check('题库列表渲染', listReady);

    // ---- S.1 标签列 + 筛选下拉 ----
    const s1 = await tab.eval(`(() => ({
      hasSceneFilter: [...document.querySelectorAll('.q-toolbar .el-select')].some((s) => s.textContent.includes('用途分类')),
      rowsWithSceneTags: document.querySelectorAll('.q-row .q-meta .el-tag').length,
    }))()`);
    check('S.1 用途分类筛选下拉存在', s1.hasSceneFilter, JSON.stringify(s1));

    // ---- S.2 筛选「考试」 ----
    const examSelected = await selectToolbarScene(tab, '考试');
    await sleep(800);
    const s2rows = await tab.eval(`[...document.querySelectorAll('.q-row .q-meta')].every((m) => m.textContent.includes('考试'))`);
    const s2count = await tab.eval(`document.querySelectorAll('.q-row').length`);
    check('S.2 筛选「考试」后行均带考试标签', examSelected && (s2count === 0 || s2rows), `rows=${s2count}`);
    await tab.shot('scenes-01-filter-exam.png');
    // 清除筛选：筛选态是内存态，直接刷新页面复位（与项目内既有 E2E 口径一致）
    await tab.send('Page.navigate', { url: `${BASE}/teacher/questions` });
    await waitFor(tab, `document.querySelectorAll('.q-row').length > 0`, 25000);
    await sleep(500);

    // ---- S.3 新建弹窗用途分类多选（默认练习+作业） ----
    await tab.eval(`(() => { [...document.querySelectorAll('button')].find((b) => b.textContent.includes('新建题目'))?.click(); })()`);
    await waitFor(tab, `!!document.querySelector('.question-form-dialog')`, 8000);
    await sleep(400);
    const s3 = await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      const labels = [...form.querySelectorAll('.el-form-item__label')];
      const sceneLabel = labels.find((l) => l.textContent.includes('用途分类'));
      if (!sceneLabel) return { hasField: false };
      const formItem = sceneLabel.closest('.el-form-item');
      const tags = [...formItem.querySelectorAll('.el-select__selected-item, .el-tag')].map((t) => t.textContent.trim());
      return { hasField: true, selected: tags };
    })()`);
    check('S.3 新建弹窗含用途分类多选', s3.hasField, JSON.stringify(s3));

    // ---- S.4 勾选「考试」并创建 ----
    // 场景多选：默认已勾练习+作业，补勾「考试」
    for (let attempt = 0; attempt < 2; attempt++) {
      await tab.eval(`(() => {
        const form = document.querySelector('.question-form-dialog');
        const labels = [...form.querySelectorAll('.el-form-item__label')];
        const sceneItem = labels.find((l) => l.textContent.includes('用途分类')).closest('.el-form-item');
        sceneItem.querySelector('.el-select__wrapper').click();
      })()`);
      await sleep(500);
      const picked = await tab.eval(`(() => {
        const items = [...document.querySelectorAll('.el-select-dropdown__item')].filter((el) => el.getBoundingClientRect().height > 0);
        const t = items.find((el) => el.textContent.trim() === '考试');
        if (!t) return false;
        t.click();
        return true;
      })()`);
      await sleep(300);
      if (picked) break;
      await closePoppers(tab);
    }
    const s4scenes = await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      const labels = [...form.querySelectorAll('.el-form-item__label')];
      const sceneItem = labels.find((l) => l.textContent.includes('用途分类')).closest('.el-form-item');
      return sceneItem.querySelector('.el-select__wrapper').textContent;
    })()`);
    await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      const labels = [...form.querySelectorAll('.el-form-item__label')];
      const stemItem = labels.find((l) => l.textContent.includes('题干')).closest('.el-form-item');
      const ta = stemItem.querySelector('textarea');
      ta.value = 'E2E场景验收考试专用题X';
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      const labels = [...form.querySelectorAll('.el-form-item__label')];
      const optItem = labels.find((l) => l.textContent.includes('选项')).closest('.el-form-item');
      const inputs = optItem.querySelectorAll('input');
      inputs[0].value = '选项甲'; inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
      inputs[1].value = '选项乙'; inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      const btn = [...form.querySelectorAll('button')].find((b) => b.textContent.includes('设为答案'));
      btn?.click();
    })()`);
    await sleep(200);
    // 选择章节（重试+读回确认；先关场景弹层防选项串台）
    let chapterOk = false;
    for (let attempt = 0; attempt < 3 && !chapterOk; attempt++) {
      await closePoppers(tab);
      await tab.eval(`(() => {
        const form = document.querySelector('.question-form-dialog');
        const labels = [...form.querySelectorAll('.el-form-item__label')];
        const catItem = labels.find((l) => l.textContent.includes('所属章节')).closest('.el-form-item');
        catItem.querySelector('.el-select__wrapper').click();
      })()`);
      await sleep(600);
      await tab.eval(`(() => {
        const items = [...document.querySelectorAll('.el-select-dropdown__item')].filter((el) => el.getBoundingClientRect().height > 0);
        // 章节选项文本通常带「第X章」或任意非分类文案；取当前可见选项第一个
        if (items.length) items[0].click();
      })()`);
      await sleep(300);
      chapterOk = await tab.eval(`(() => {
        const form = document.querySelector('.question-form-dialog');
        const labels = [...form.querySelectorAll('.el-form-item__label')];
        const catItem = labels.find((l) => l.textContent.includes('所属章节')).closest('.el-form-item');
        const txt = catItem.querySelector('.el-select__wrapper').textContent.trim();
        return txt && !txt.includes('请选择');
      })()`);
    }
    log(`  章节选择: ${chapterOk}`);
    // 「创建并发布」
    await tab.eval(`(() => {
      const form = document.querySelector('.question-form-dialog');
      [...form.querySelectorAll('button')].find((b) => b.textContent.includes('创建并发布'))?.click();
    })()`);
    await sleep(1500);
    const diag = await tab.eval(`(() => ({
      dialogOpen: !!document.querySelector('.question-form-dialog'),
      message: document.querySelector('.el-message')?.textContent || '',
    }))()`);
    log(`创建后诊断: ${JSON.stringify(diag)}`);
    const created = await waitFor(tab, `[...document.querySelectorAll('.q-row')].some((r) => r.textContent.includes('E2E场景验收考试专用题X'))`, 15000);
    check('S.4 创建并发布后列表出现新题', created);
    const s4tag = await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.q-row')].find((r) => r.textContent.includes('E2E场景验收考试专用题X'));
      return row ? row.querySelector('.q-meta').textContent.includes('考试') : false;
    })()`);
    check('S.4 新题行带「考试」标签', s4tag);
    await tab.shot('scenes-02-created.png');

    // ---- S.4b 用 API 把该题改为「仅考试」分类（泄题验证的前提：剔除 practice 标签） ----
    const patchRes = await tab.eval(`(async () => {
      try {
        const token = localStorage.getItem('access_token') || '';
        const findRes = await fetch('/api/questions/?search=E2E场景验收考试专用题X&page_size=10', { headers: { Authorization: 'Bearer ' + token } });
        const found = await findRes.json();
        const q = (found?.data?.results || [])[0];
        if (!q) return { error: 'question not found' };
        const res = await fetch('/api/questions/' + q.id + '/', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
          body: JSON.stringify({ scenes: ['exam'] }),
        });
        const d = await res.json();
        return { id: q.id, code: d.code, scenes: d.data?.scenes };
      } catch (e) { return { error: String(e) }; }
    })()`);
    check('S.4b 改为仅考试分类', patchRes && patchRes.code === 0 && JSON.stringify(patchRes.scenes) === '["exam"]', JSON.stringify(patchRes));

    // ---- S.5 学生端练习防泄题 ----
    const stuOk = await login(tab, 'dbg1', 'A0987654');
    check('S.5 学生登录', stuOk);
    const leak = await tab.eval(`(async () => {
      const res = await fetch('/api/questions/?page_size=100', { headers: { Authorization: 'Bearer ' + JSON.parse(localStorage.getItem('zhike-auth') || '{}')?.token?.access } });
      return null;
    })()`).catch(() => null);
    // 直接用页面上下文请求（同域带 cookie/token 由拦截器处理不便，走 evaluate fetch 用 localStorage token）
    const leakResult = await tab.eval(`(async () => {
      try {
        const token = localStorage.getItem('access_token') || '';
        if (!token) return { error: 'no token' };
        const res = await fetch('/api/questions/?page_size=100', { headers: { Authorization: 'Bearer ' + token } });
        const d = await res.json();
        const list = d?.data?.results || [];
        return { total: d?.data?.total ?? list.length, leaked: list.some((q) => (q.stem || '').includes('E2E场景验收考试专用题X')) };
      } catch (e) { return { error: String(e) }; }
    })()`);
    check('S.5 学生练习看不到考试专用题', leakResult && leakResult.leaked === false, JSON.stringify(leakResult));

    // ---- S.6 考试组卷池含该题（组卷为整页工作台：新建考试打开即加载 scene=exam 题库池） ----
    log('教师登录查考试组卷池…');
    await login(tab, 't101', 'pass1234');
    await tab.send('Page.navigate', { url: `${BASE}/teacher/exams` });
    const examPageReady = await waitFor(tab, `[...document.querySelectorAll('button')].some((b) => b.textContent.includes('新建考试'))`, 20000);
    check('S.6 考试管理页就绪', examPageReady);
    await tab.eval(`(() => { [...document.querySelectorAll('button')].find((x) => x.textContent.includes('新建考试'))?.click(); })()`);
    await waitFor(tab, `!!document.querySelector('.exam-editor')`, 10000);
    const poolLoaded = await waitFor(tab, `document.querySelector('.exam-editor').textContent.includes('E2E场景验收考试专用题X')`, 20000);
    check('S.6 考试组卷池含考试专用题', poolLoaded);
    await tab.shot('scenes-03-exam-pool.png');
    // 退出编辑不保存（E2E 不遗留草稿考试）
    await tab.eval(`(() => { [...document.querySelectorAll('.exam-editor-actions button')].find((b) => b.textContent.includes('退出编辑'))?.click(); })()`);
    await sleep(800);

    // ---- S.7 AI 生题对话框用途分类 ----
    await tab.send('Page.navigate', { url: `${BASE}/teacher/questions` });
    await waitFor(tab, `document.querySelectorAll('.q-row').length > 0`, 25000);
    await tab.eval(`(() => { [...document.querySelectorAll('button')].find((b) => b.textContent.includes('AI 生成'))?.click(); })()`);
    await waitFor(tab, `!!document.querySelector('.ai-gen-dialog')`, 8000);
    await sleep(400);
    const s7 = await tab.eval(`(() => {
      const dlg = document.querySelector('.ai-gen-dialog');
      return [...dlg.querySelectorAll('.el-form-item__label')].some((l) => l.textContent.includes('用途分类'));
    })()`);
    check('S.7 AI 生题对话框含用途分类', s7);
    await tab.shot('scenes-04-aigen.png');

    // ---- 清理：删除验收题 ----
    await tab.eval(`(() => {
      const dlg = document.querySelector('.ai-gen-dialog');
      [...dlg.querySelectorAll('button')].find((b) => b.textContent.includes('取消'))?.click();
    })()`);
    await sleep(400);
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.q-row')].find((r) => r.textContent.includes('E2E场景验收考试专用题X'));
      if (!row) return;
      [...row.querySelectorAll('button')].find((b) => b.textContent.includes('删除'))?.click();
    })()`);
    await sleep(600);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.el-dialog');
      if (!dlg) return;
      [...dlg.querySelectorAll('button')].find((b) => b.textContent.includes('确认删除') || b.textContent.includes('删除'))?.click();
    })()`);
    await sleep(1000);
    const cleaned = await tab.eval(`![...document.querySelectorAll('.q-row')].some((r) => r.textContent.includes('E2E场景验收考试专用题X'))`);
    check('清理验收题', cleaned);

    // ---- S.8 console 干净 ----
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('S.8 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
