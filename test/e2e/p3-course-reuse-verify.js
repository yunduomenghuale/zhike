#!/usr/bin/env node
/**
 * P3 E2E：教师端「复用课程」全链（入口 → 资产盘点 → 提交 → 阶段进度 → 结果 → 跳转 → 列表停用）。
 *
 * 验证点（对应任务规范 §4 P3 的前端部分）：
 *   A 课程卡片有「复用课程」入口，点击打开弹窗
 *   B 弹窗展示将复制的资产清单（章节/课件/页/讲稿/配音/资料/片段/资源）与总体积
 *   C 默认新课程名、学期沿用、题库勾选与题数提示
 *   D 提交后进入阶段进度，轮询到完成，结果摘要正确
 *   E 「查看新课程」跳转到章节页；返回列表可见新课程且状态为「停用」
 *   F 全程无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273（node serve-local.js）、t101/pass1234、源课程 7（Java程序设计）
 * 运行：node test/e2e/p3-course-reuse-verify.js
 * 收尾：脚本会调 test/e2e/purge_courses.py 删掉本次建的副本（行 + 媒体文件）
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
const PROFILE = `D:/tmp/zhike-p3-e2e/run-${RUN_ID}`;
const SOURCE_NAME = 'Java程序设计';
const NEW_NAME = `E2E复用-${Date.now().toString(36).slice(-5).toUpperCase()}`;
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

const DIALOG = '.reuse-dialog';
const dlgText = `(() => { const d = document.querySelector('${DIALOG}'); return d ? d.innerText : ''; })()`;

function clickBtn(tab, text, scope) {
  return tab.eval(`(() => {
    const root = ${scope ? `document.querySelector('${scope}')` : 'document'};
    if (!root) return false;
    const btn = [...root.querySelectorAll('button')].find((b) => b.innerText.trim().includes(${JSON.stringify(text)}));
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const { cdp: tab, chrome } = await launchChrome();
  const createdIds = [];

  try {
    // ================= A. 入口 =================
    check('A0 教师登录', await login(tab, 't101', 'pass1234'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses` });
    const listReady = await waitFor(tab, `!!document.querySelector('.course-card')`, 20000);
    check('A1 课程列表加载', listReady);

    const cardInfo = await tab.eval(`(() => {
      const cards = [...document.querySelectorAll('.course-card')];
      const card = cards.find((c) => c.innerText.includes(${JSON.stringify(SOURCE_NAME)}));
      if (!card) return null;
      const btn = card.querySelector('.course-actions button[title="复用课程"]');
      return { hasBtn: !!btn, cardCount: cards.length };
    })()`);
    check('A2 卡片上有「复用课程」入口', !!cardInfo && cardInfo.hasBtn,
      JSON.stringify(cardInfo));

    // hover 后按钮可见（课程卡的 actions 默认 opacity:0）：CSS :hover 只能由真实
    // 鼠标事件触发，合成 MouseEvent 改不了命中状态，故经 CDP 发真实 mousemove
    const cardRect = await tab.eval(`(() => {
      const card = [...document.querySelectorAll('.course-card')]
        .find((c) => c.innerText.includes(${JSON.stringify(SOURCE_NAME)}));
      if (!card) return null;
      const r = card.getBoundingClientRect();
      return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
    })()`);
    if (cardRect) {
      await tab.send('Input.dispatchMouseEvent', {
        type: 'mouseMoved', x: cardRect.x, y: cardRect.y, buttons: 0,
      });
    }
    await sleep(500);
    const opacity = await tab.eval(`(() => {
      const card = [...document.querySelectorAll('.course-card')]
        .find((c) => c.innerText.includes(${JSON.stringify(SOURCE_NAME)}));
      const actions = card && card.querySelector('.course-actions');
      return actions ? Number(getComputedStyle(actions).opacity) : -1;
    })()`);
    check('A3 hover 后操作按钮可见', opacity > 0.9, `opacity=${opacity}`);

    // ================= B. 弹窗与资产盘点 =================
    await tab.eval(`(() => {
      const card = [...document.querySelectorAll('.course-card')]
        .find((c) => c.innerText.includes(${JSON.stringify(SOURCE_NAME)}));
      const btn = card.querySelector('.course-actions button[title="复用课程"]');
      btn.click();
      return true;
    })()`);
    const opened = await waitFor(tab, `(() => {
      const d = document.querySelector('${DIALOG}');
      return !!d && d.offsetParent !== null && d.innerText.includes('将复制的资产');
    })()`, 20000);
    check('B1 复用弹窗打开且资产清单加载完成', opened);
    await tab.shot('p3-01-reuse-dialog.png');

    const assets = await tab.eval(`(() => {
      const items = [...document.querySelectorAll('${DIALOG} .asset-item')].map((i) => ({
        label: (i.querySelector('.asset-label') || {}).innerText || '',
        value: (i.querySelector('.asset-value') || {}).innerText || '',
      }));
      return {
        items,
        title: (document.querySelector('${DIALOG} .reuse-title') || {}).innerText || '',
        sub: (document.querySelector('${DIALOG} .reuse-subtitle') || {}).innerText || '',
        size: (document.querySelector('${DIALOG} .asset-size') || {}).innerText || '',
        name: (document.querySelector('${DIALOG} input[maxlength="200"]') || {}).value || '',
        checkText: (document.querySelector('${DIALOG} .reuse-check-text') || {}).innerText || '',
        checked: !!(document.querySelector('${DIALOG} .reuse-check .el-checkbox.is-checked')),
        // EP 的 el-select 选中值渲染在 .el-select__selected-item 里，input 的 value 为空
        term: (document.querySelector('${DIALOG} .reuse-select') || {}).innerText || '',
      };
    })()`);
    const byLabel = Object.fromEntries(assets.items.map((i) => [i.label, i.value]));
    check('B2 弹窗标题与源课程名正确',
      assets.title.includes('复用课程') && assets.sub.includes(SOURCE_NAME),
      `${assets.title} / ${assets.sub}`);
    check('B3 资产清单覆盖 8 类', assets.items.length === 8,
      assets.items.map((i) => `${i.label}=${i.value}`).join(' '));
    check('B4 资产数量与源课程一致（3 章节 / 2 课件 / 62 页 / 146 片段 / 5 资源）',
      byLabel['章节'] === '3' && byLabel['课件'] === '2' && byLabel['课件页'] === '62'
      && byLabel['知识库片段'] === '146' && byLabel['教学资源'] === '5',
      JSON.stringify(byLabel));
    check('B5 展示总体积', /\d+(\.\d+)?\s*(KB|MB|GB)/.test(assets.size), assets.size);
    check('B6 默认新课程名为「原名（复用）」', assets.name === `${SOURCE_NAME}（复用）`, assets.name);
    check('B7 学期沿用原课程', assets.term.includes('2026'), assets.term);
    check('B8 题库默认勾选且显示题数', assets.checked && /10\s*道题/.test(assets.checkText),
      assets.checkText);

    // ================= C. 交互：改名 + 取消题库 =================
    await tab.eval(`(() => {
      const input = document.querySelector('${DIALOG} input[maxlength="200"]');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(NEW_NAME)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return input.value;
    })()`);
    await tab.eval(`(() => {
      const box = document.querySelector('${DIALOG} .reuse-check .el-checkbox');
      const root = box || document.querySelector('${DIALOG} .reuse-check');
      root.click();
      return true;
    })()`);
    await sleep(300);
    const unchecked = await tab.eval(
      `!document.querySelector('${DIALOG} .reuse-check .el-checkbox').classList.contains('is-checked')`);
    check('C1 可改课程名并取消勾选题库', unchecked);

    // ================= D. 提交与阶段进度 =================
    check('D0 点击「开始复用」', await clickBtn(tab, '开始复用', DIALOG));
    const running = await waitFor(tab, `document.querySelector('${DIALOG} .reuse-progress') !== null`, 20000);
    check('D1 进入任务进度态', running);
    const progressText = await tab.eval(
      `(document.querySelector('${DIALOG} .reuse-progress') || {}).innerText || ''`);
    check('D2 进度有阶段文案', progressText.trim().length > 0,
      progressText.replace(/\n+/g, ' / ').slice(0, 120));
    await tab.shot('p3-02-reuse-progress.png');

    const done = await waitFor(tab, `document.querySelector('${DIALOG} .reuse-result') !== null`, 300000, 500);
    check('D3 任务执行完成并显示结果', done);
    const resultText = await tab.eval(dlgText);
    check('D4 结果标题含新课程名',
      resultText.includes('复用完成') && resultText.includes(NEW_NAME),
      resultText.replace(/\n+/g, ' / ').slice(0, 200));
    check('D5 结果摘要含复制统计与体积',
      /章节/.test(resultText) && /\d+(\.\d+)?\s*(KB|MB|GB)/.test(resultText),
      resultText.replace(/\n+/g, ' / ').slice(0, 220));
    check('D6 提示新课程为停用态', resultText.includes('停用'));
    await tab.shot('p3-03-reuse-done.png');

    // ================= E. 跳转与新课程可见 =================
    check('E0 点「查看新课程」', await clickBtn(tab, '查看新课程', DIALOG));
    const jumped = await waitFor(tab, `/^\\/teacher\\/courses\\/\\d+\\/chapters$/.test(location.pathname)`, 20000);
    const newId = jumped ? await tab.eval(`location.pathname.split('/')[3]`) : '';
    if (newId) createdIds.push(newId);
    check('E1 跳转到新课程章节页', jumped, `path=${await tab.eval('location.pathname')}`);

    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses` });
    const listed = await waitFor(tab, `document.body.innerText.includes(${JSON.stringify(NEW_NAME)})`, 20000);
    check('E2 课程列表出现新课程', listed);
    const statusTag = await tab.eval(`(() => {
      const card = [...document.querySelectorAll('.course-card')]
        .find((c) => c.innerText.includes(${JSON.stringify(NEW_NAME)}));
      if (!card) return null;
      return { tag: (card.querySelector('.el-tag') || {}).innerText || '', text: card.innerText.slice(0, 120) };
    })()`);
    check('E3 新课程状态为「停用」', !!statusTag && statusTag.tag.includes('停用'),
      JSON.stringify(statusTag));
    await tab.shot('p3-04-course-list.png');

    // ================= F. 零报错 =================
    const errors = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('F1 全程无 console.error / 未捕获异常', errors.length === 0, errors.slice(0, 3).join(' | '));
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
    if (createdIds.length) {
      log(`清理副本课程：${createdIds.join(',')}`);
      try {
        const out = execFileSync(PYTHON, ['../test/e2e/purge_courses.py', ...createdIds],
          { cwd: path.join(ROOT, 'backend'), encoding: 'utf8' });
        process.stdout.write(out);
      } catch (err) {
        console.log('清理失败，请手动执行 purge_courses.py：', err.message);
      }
    }
  }

  console.log(`\n== 通过 ${passes} / 失败 ${failures} ==`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => { console.error('E2E 异常：', err); process.exit(1); });
