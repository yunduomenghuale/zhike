#!/usr/bin/env node
/**
 * 通知铃铛融合 E2E——真实 8092 测试环境验收：
 *  A1 教师/管理员：无独立悬浮球（.ai-task-bell 不存在）
 *  A2 通知铃铛 popover 内有「任务」页签，可切换，任务页显示「暂无任务」
 *  A3 学生：popover 内只有「通知」，无「任务」页签
 * 运行：node test/e2e/notify-bell-verify.js
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = 'http://192.168.3.145:8092';
const PROFILE = 'D:/tmp/zhike-e2e/notify-bell-profile';
const SHOT = path.resolve(__dirname, '../screenshots');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let PASS = 0, FAIL = 0;
const check = (label, ok, detail = '') => {
  if (ok) { PASS++; console.log(`PASS  ${label}${detail ? '  | ' + detail : ''}`); }
  else { FAIL++; console.log(`FAIL  ${label}${detail ? '  | ' + detail : ''}`); }
};

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); } }, 30000);
    });
  }
}

async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const chrome = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--disable-session-crashed-bubble', '--window-size=1440,900',
  ], { stdio: 'ignore' });
  await sleep(3500);

  const targets = await fetch(`http://127.0.0.1:${PORT}/json`).then((r) => r.json());
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  async function evalJs(expr) {
    const r = await cdp.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('eval fail: ' + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async function shot(name) {
    const r = await cdp.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT, name), Buffer.from(r.data, 'base64'));
  }
  // 登录（真实 API），user 由 145 夹具预建：test_student / Stu123456!
  async function login(u, p) {
    await evalJs(`localStorage.clear()`); // 先清 token 再进 /login，否则路由守卫带着旧 pinia 身份弹回首页
    await cdp.send('Page.navigate', { url: `${BASE}/login` });
    await sleep(2800);
    await evalJs(`(() => {
      const els = document.querySelectorAll('input');
      els.forEach(i => {
        if (i.placeholder && i.placeholder.includes('用户名')) { i.value = '${u}'; i.dispatchEvent(new Event('input', { bubbles: true })); }
        if (i.type === 'password') { i.value = '${p}'; i.dispatchEvent(new Event('input', { bubbles: true })); }
      });
      return els.length;
    })()`);
    // Vue 需要触发 input 事件
    await evalJs(`(() => {
      const btns = [...document.querySelectorAll('button')];
      const b = btns.find(x => x.textContent.includes('立即登录'));
      if (b) b.click();
      return !!b;
    })()`);
    await sleep(3500);
  }

  try {
    // ---- A1/A2：管理员视角 ----
    await login('test_admin', 'Test123456!');
    await sleep(1500);
    await shot('notify-bell-admin.png');
    const noBall = await evalJs(`!document.querySelector('.ai-task-bell')`);
    check('A1 管理员视角无独立悬浮球', noBall);
    const hasBell = await evalJs(`!!document.querySelector('.head-badge')`);
    check('A1 通知铃铛存在', hasBell);
    // 点开 popover
    await evalJs(`document.querySelector('.head-badge button, button.icon-btn').click(); 'ok'`);
    await sleep(1200);
    const tabs = await evalJs(`[...document.querySelectorAll('.notify-tab')].map(t => t.textContent.trim())`);
    const hasTaskTab = tabs.some((t) => t.startsWith('任务'));
    check('A2 popover 内有「任务」页签', hasTaskTab, JSON.stringify(tabs));
    if (hasTaskTab) {
      await evalJs(`[...document.querySelectorAll('.notify-tab')].find(t => t.textContent.includes('任务')).click(); 'ok'`);
      await sleep(1200);
      const panelText = await evalJs(`document.querySelector('.notify-panel').textContent`);
      check('A2 任务页显示空态「暂无任务」', panelText.includes('暂无任务'));
      await shot('notify-bell-task-tab.png');
      // B1：admin 有「全局队列看板」入口，打开抽屉有数据
      const hasBoard = await evalJs(`!!document.querySelector('.queue-board-entry')`);
      check('B1 admin 有全局看板入口', hasBoard);
      if (hasBoard) {
        await evalJs(`document.querySelector('.queue-board-entry button').click(); 'ok'`);
        await sleep(1800);
        const drawerText = await evalJs(`document.querySelector('.el-dialog').textContent`);
        check('B1 看板含状态卡片', drawerText.includes('排队中') && drawerText.includes('执行中') && drawerText.includes('活跃任务'));
        check('B1 看板含类型分布区/空态', drawerText.includes('活跃任务') || drawerText.includes('当前无'));
        await shot('queue-board.png');
        // 数据明细：弹窗里应能看到 用户/课程章节/内容量 字段
        const hasDetail = drawerText.includes('内容量') || drawerText.includes('近期失败') || drawerText.includes('当前无排队');
        check('B1 看板含任务明细字段', hasDetail);
        // 切到失败/完成页签截图
        await evalJs(`[...document.querySelectorAll('.el-tabs__item')].find(t => t.textContent.includes('完成') || t.textContent.includes('失败'))?.click(); 'ok'`);
        await sleep(800);
        await shot('queue-board-tab2.png');
      }
    }

    // ---- A3：学生视角 ----
    await login('test_student', 'Stu123456!');
    await sleep(1500);
    await evalJs(`document.querySelector('.head-badge button, button.icon-btn').click(); 'ok'`);
    await sleep(1200);
    const stuTabs = await evalJs(`[...document.querySelectorAll('.notify-tab')].map(t => t.textContent.trim())`);
    check('A3 学生无「任务」页签', stuTabs.length === 1 && stuTabs[0].startsWith('通知'), JSON.stringify(stuTabs));
    const stuNoBall = await evalJs(`!document.querySelector('.ai-task-bell')`);
    check('A3 学生无悬浮球', stuNoBall);
    check('B2 学生无看板入口', await evalJs(`!document.querySelector('.queue-board-entry')`));
    check('B2 学生无看板入口', await evalJs(`!document.querySelector('.queue-board-entry')`));
    await shot('notify-bell-student.png');
  } finally {
    ws.close(); chrome.kill();
  }
  console.log(`\n===== ${PASS}/${PASS + FAIL} PASS =====`);
  process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.error('E2E error:', e.message); process.exit(1); });
