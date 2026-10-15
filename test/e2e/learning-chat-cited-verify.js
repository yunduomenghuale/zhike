#!/usr/bin/env node
/**
 * 课程讲解页 AI 助教两项修复实测（Learning.vue）：
 *   LC.1 参考来源恢复：回答下方出现「参考来源」区块与来源 pill（重排阈值修复后 meta 事件生效）
 *   LC.2 markdown 加粗渲染：回答中无 ** 残留，且渲染出 <strong>（flanking 兜底修复）
 *   LC.3 交互回归：提问→流式输出→参考来源随正文结束出现
 *   LC.4 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273 已启动（前端为最新构建）；学生 20249999=A0987654，课程 5 有课件。
 * 运行：node test/e2e/learning-chat-cited-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';
const QUESTION = 'Java 程序设计这门课的考核方式是什么？';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9800 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-lc-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

// ---------------- CDP 客户端（与 cdp-drive.js 同款） ----------------
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
  await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`, 30000);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
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

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    // LC.0 登录并进入课程学习页
    await login(cdp, '20249999', PW);
    await cdp.navigate(BASE + '/student/learning');
    const rowsOk = await waitFor(cdp, `document.querySelectorAll('.tree-node').length >= 1`, 30000);
    check('LC.1 课程学习页加载出章节列表', rowsOk);
    if (!rowsOk) throw new Error('章节列表未加载，终止');

    // LC.2 点第一个章节的「AI 问答」打开助教 Dock
    const opened = await cdp.eval(`(function(){
      var btns = [...document.querySelectorAll('.node-action-btn')];
      var btn = btns.find((b) => b.textContent.includes('AI 问答'));
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    check('LC.2 找到并点击「AI 问答」入口', opened);
    const dockOk = await waitFor(cdp, `!!document.querySelector('.full-lecture-dock .chat-textarea')`, 20000);
    check('LC.3 助教 Dock 打开（chat 输入框可见）', dockOk);
    if (!dockOk) throw new Error('Dock 未打开，终止');

    // LC.3 输入问题并发送
    await cdp.eval(`(function(){
      var el = document.querySelector('.chat-textarea');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, ${JSON.stringify(QUESTION)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await cdp.eval(`document.querySelector('.chat-send').click()`);

    // LC.4 等待回答完成：assistant 消息出现且非流式（.chat-sources 只在结束后渲染）
    const answered = await waitFor(cdp,
      `!!document.querySelector('.chat-row.assistant .chat-sources')`, 180000);
    check('LC.4 回答输出完成并出现参考来源区块', answered);
    if (!answered) {
      await cdp.shot('learning-chat-fail');
      throw new Error('回答未在预期时间内完成');
    }

    // LC.5 markdown 加粗：无 ** 残留且有 <strong>
    const mdStat = await cdp.eval(`(function(){
      var md = document.querySelector('.chat-row.assistant .chat-md');
      if (!md) return null;
      return {
        residualStar: (md.textContent.match(/\\*\\*/g) || []).length,
        strongCount: md.querySelectorAll('strong').length,
        textLen: md.textContent.length,
      };
    })()`);
    check('LC.5 回答无 ** 残留', !!mdStat && mdStat.residualStar === 0, mdStat ? `残留 ${mdStat.residualStar} 处` : '未找到回答');
    check('LC.6 回答渲染出 <strong> 加粗', !!mdStat && mdStat.strongCount >= 1, mdStat ? `${mdStat.strongCount} 处加粗` : '未找到回答');

    // LC.7 参考来源 pill 文案
    const tags = await cdp.eval(`[...document.querySelectorAll('.chat-sources .chat-source-tags .el-tag')].map((t) => t.textContent.trim())`);
    check('LC.7 参考来源 pill 非空', Array.isArray(tags) && tags.length >= 1, JSON.stringify(tags));

    // LC.7b 无重复渲染：assistant 气泡内只应有 chat-md 一个正文块（v-else 错位会导致纯文本二次渲染）
    const dup = await cdp.eval(`(function(){
      var row = document.querySelector('.chat-row.assistant');
      if (!row) return null;
      return {
        mdCount: row.querySelectorAll('.chat-md').length,
        plainCount: row.querySelectorAll('.chat-text:not(.chat-md)').length,
      };
    })()`);
    check('LC.7b 助手气泡无重复渲染', !!dup && dup.mdCount === 1 && dup.plainCount === 0, dup ? JSON.stringify(dup) : '未找到助手消息');

    await cdp.shot('learning-chat-cited-ok');

    // LC.8 无 JS 异常
    check('LC.8 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' ; ') || '');
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项: ' + failed.map((f) => f.name).join(' | '));
    process.exitCode = 1;
  }
}

run().catch((err) => {
  console.error('E2E 运行异常:', err.message);
  process.exitCode = 1;
});
