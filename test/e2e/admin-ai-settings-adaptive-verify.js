#!/usr/bin/env node
/**
 * 管理端大模型配置「调用统计/问答质量」tab 自适应修复——CDP 实测
 *
 * 验证点：
 *   A.1 1440×900（100% 缩放等效）：调用统计 tab 所有卡片宽度 == 面板宽度，无溢出
 *   A.2 同屏问答质量 tab 卡片宽度 == 面板宽度
 *   A.3 1366×768（用户小屏场景）：两个 tab 均不溢出
 *   A.4 调用流水表格内部横滚可用（列总宽 > 容器时 el-table 出现横向滚动条区域）
 *   A.5 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；admin/A0987654。
 * 运行：node test/e2e/admin-ai-settings-adaptive-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-admadapt-e2e/run-${RUN_ID}`;
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

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    // 登录
    await tab.send('Page.navigate', { url: `${BASE}/login` });
    await waitFor(tab, `location.href.startsWith('http')`);
    await tab.eval(`localStorage.clear()`);
    await tab.send('Page.navigate', { url: `${BASE}/login` });
    await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2`);
    await tab.eval(`(() => {
      const inputs = document.querySelectorAll('input');
      inputs[0].value = 'admin';
      inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
      const pwd = document.querySelector('input[type="password"]');
      pwd.value = 'A0987654';
      pwd.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(200);
    await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`);
    await waitFor(tab, `!location.pathname.startsWith('/login')`, 15000);
    await tab.send('Page.navigate', { url: `${BASE}/admin/ai-settings` });
    await waitFor(tab, `document.querySelectorAll('.el-tabs__item').length >= 4`, 25000);
    await sleep(1500);

    const measure = async () => tab.eval(`(() => {
      const pane = [...document.querySelectorAll('.el-tab-pane')].find((p) => p.offsetParent !== null);
      const panel = pane?.querySelector('.stats-panel');
      if (!panel) return { err: 'no panel' };
      const pw = panel.getBoundingClientRect().width;
      const kids = [...panel.children].map((c) => Math.round(c.getBoundingClientRect().width));
      const tabsContent = document.querySelector('.el-tabs__content')?.getBoundingClientRect().width ?? 0;
      // 是否有元素横向超出 tabsContent（被裁的判定）
      const tcRight = document.querySelector('.el-tabs__content')?.getBoundingClientRect().right ?? 0;
      const overflow = kids.some((w) => w > Math.round(tabsContent) + 2);
      return { panel: Math.round(pw), tabsContent: Math.round(tabsContent), kids, overflow };
    })()`);

    // A.1 调用统计 @1440
    await tab.eval(`[...document.querySelectorAll('.el-tabs__item')].find((t) => t.textContent.includes('调用统计'))?.click()`);
    await sleep(3000);
    const m1 = await measure();
    check('A.1 调用统计@1440 卡片不溢出', m1 && !m1.err && !m1.overflow && Math.abs(m1.panel - m1.tabsContent) <= 2, JSON.stringify(m1));
    await tab.shot('adm-adapt-01-stats-1440.png');

    // A.4 表格内部横滚
    const scrollable = await tab.eval(`(() => {
      const pane = [...document.querySelectorAll('.el-tab-pane')].find((p) => p.offsetParent !== null);
      const wrap = pane?.querySelector('.el-table .el-scrollbar__wrap');
      if (!wrap) return { err: 'no table wrap' };
      return { sw: wrap.scrollWidth, cw: wrap.clientWidth, canScroll: wrap.scrollWidth > wrap.clientWidth + 2 };
    })()`);
    check('A.4 调用流水表格内部横滚可用', scrollable && scrollable.canScroll, JSON.stringify(scrollable));

    // A.2 问答质量 @1440
    await tab.eval(`[...document.querySelectorAll('.el-tabs__item')].find((t) => t.textContent.includes('问答质量'))?.click()`);
    await sleep(3000);
    const m2 = await measure();
    check('A.2 问答质量@1440 卡片不溢出', m2 && !m2.err && !m2.overflow && Math.abs(m2.panel - m2.tabsContent) <= 2, JSON.stringify(m2));
    await tab.shot('adm-adapt-02-qa-1440.png');

    // A.3 小屏 1366×768 两 tab
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1366, height: 768, deviceScaleFactor: 1, mobile: false });
    await sleep(1200);
    const m3a = await measure();
    check('A.3a 问答质量@1366 不溢出', m3a && !m3a.overflow, JSON.stringify(m3a));
    await tab.eval(`[...document.querySelectorAll('.el-tabs__item')].find((t) => t.textContent.includes('调用统计'))?.click()`);
    await sleep(2500);
    const m3b = await measure();
    check('A.3b 调用统计@1366 不溢出', m3b && !m3b.overflow, JSON.stringify(m3b));
    await tab.shot('adm-adapt-03-stats-1366.png');

    // A.5 console 干净
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('A.5 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
