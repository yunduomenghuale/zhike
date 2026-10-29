#!/usr/bin/env node
/**
 * 教师端学情分析页「导出 Excel」配置弹窗 E2E（CDP 实测）
 *
 * 验证点：
 *   A.1 点「导出 Excel」只打开配置弹窗，不直接下载
 *   A.2 弹窗含 4 个时间预设 + 7 项导出内容，成绩总览默认勾选且不可取消
 *   A.3 选「近 30 天」提示显示具体范围；切「自定义」出现日期选择器
 *   A.4 取消勾选「章节矩阵」后导出：摘要更新，请求 sheets 不含 chapter 且带 start/end
 *   A.5 前端生成 xlsx blob、文件名正确，导出后弹窗自动关闭
 *   A.6 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234（至少一个班级有学生）。
 * 运行：node test/e2e/class-export-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-export-e2e/run-${RUN_ID}`;
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
    this.ws = ws; this.id = 0; this.pending = new Map(); this.consoleErrors = []; this.requests = [];
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
      } else if (msg.method === 'Network.requestWillBeSent') {
        this.requests.push(msg.params.request.url);
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
  await cdp.send('Network.enable');
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

const DIALOG_VISIBLE = `(() => {
  const d = document.querySelector('.an-export-dialog');
  return !!(d && d.getBoundingClientRect().height > 60);
})()`;

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });

  const { cdp: tab, chrome } = await launchChrome();
  try {
    await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // ---- 登录 ----
    await tab.send('Page.navigate', { url: `${BASE}/login` });
    await waitFor(tab, `location.href.startsWith('http')`);
    await tab.eval(`localStorage.clear()`);
    await tab.send('Page.navigate', { url: `${BASE}/login` });
    await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2`);
    await tab.eval(`(() => {
      const inputs = document.querySelectorAll('input');
      inputs[0].value = 't101';
      inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
      const pwd = document.querySelector('input[type="password"]');
      pwd.value = 'pass1234';
      pwd.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(200);
    await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`);
    check('登录教师账号', await waitFor(tab, `!location.pathname.startsWith('/login')`, 15000));

    await tab.send('Page.navigate', { url: `${BASE}/teacher/analytics` });
    check('学情页加载出学生列表', await waitFor(tab, `document.querySelectorAll('.stu-table .el-table__row').length >= 1`, 25000));
    await sleep(800);

    // 拦截 blob 生成与 a.click：Chrome 对无手势下载会静默拦截，这里断言前端产物本身
    await tab.eval(`(() => {
      window.__dl = {};
      const origCreate = URL.createObjectURL.bind(URL);
      URL.createObjectURL = function (blob) {
        try { window.__dl.size = blob.size; window.__dl.type = blob.type; window.__dl.blob = blob; } catch (e) { /* ignore */ }
        return origCreate(blob);
      };
      const origClick = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        window.__dl.name = this.download;
        if (this.href && this.href.startsWith('blob:')) return;
        return origClick.call(this);
      };
    })()`);

    // ---- A.1 点击导出：只开弹窗，不产生请求/下载 ----
    const reqBefore = tab.requests.filter((u) => u.includes('/export/')).length;
    await tab.eval(`(() => {
      const btns = [...document.querySelectorAll('.an-toolbar-actions button')];
      btns.find((b) => b.textContent.includes('导出'))?.click();
    })()`);
    const dialogOpen = await waitFor(tab, DIALOG_VISIBLE, 8000);
    check('A.1 点导出只打开配置弹窗', dialogOpen);
    const reqAfterOpen = tab.requests.filter((u) => u.includes('/export/')).length;
    const noImmediate = await tab.eval(`(!window.__dl || !window.__dl.name) ? 'NO_DL' : 'DL_FIRED'`);
    check('A.1b 打开弹窗未触发导出请求/下载', reqAfterOpen === reqBefore && noImmediate === 'NO_DL', `requests ${reqBefore}->${reqAfterOpen} ${noImmediate}`);

    // ---- A.2 弹窗内容 ----
    const dialogInfo = await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      if (!d) return null;
      const presets = [...d.querySelectorAll('.exp-presets .el-radio-button')].map((p) => p.textContent.trim());
      const boxes = [...d.querySelectorAll('.exp-sections .el-checkbox')].map((c) => ({
        text: c.textContent.trim(),
        checked: !!c.querySelector('input')?.checked,
        disabled: !!c.querySelector('input')?.disabled,
      }));
      return {
        presets,
        boxes,
        allChecked: !!d.querySelector('.exp-all input')?.checked,
        rangeHint: d.querySelector('.exp-block .exp-hint')?.textContent.trim(),
        hasDatePicker: !!d.querySelector('.exp-range'),
        footer: [...d.querySelectorAll('.el-dialog__footer button')].map((b) => b.textContent.trim()),
      };
    })()`);
    check(
      'A.2 弹窗含 4 个时间预设',
      dialogInfo && dialogInfo.presets.length === 4 && dialogInfo.presets.join('/') === '全部时间/近 7 天/近 30 天/自定义',
      dialogInfo?.presets.join('/')
    );
    check(
      'A.2b 弹窗含 7 项导出内容，成绩总览默认勾选且不可取消',
      dialogInfo && dialogInfo.boxes.length === 7 &&
        dialogInfo.boxes[0].text === '成绩总览' && dialogInfo.boxes[0].checked && dialogInfo.boxes[0].disabled &&
        dialogInfo.boxes.filter((b) => b.checked).length === 7 &&
        dialogInfo.allChecked,
      JSON.stringify(dialogInfo?.boxes?.slice(0, 2))
    );
    check('A.2c 默认范围提示为全部时间', /全部时间/.test(dialogInfo?.rangeHint || ''), dialogInfo?.rangeHint);
    check('A.2d 底部按钮为「取消 / 开始导出」', (dialogInfo?.footer || []).join('/') === '取消/开始导出', (dialogInfo?.footer || []).join('/'));
    await sleep(700); // 等弹窗淡入动画结束再截图（否则拍到半透明中间态）
    await tab.shot('class-export-01-dialog.png');

    // ---- A.3 预设切换：近30天 提示范围；自定义出现日期选择器 ----
    await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      [...d.querySelectorAll('.exp-presets .el-radio-button')].find((p) => p.textContent.includes('近 30 天'))?.click();
    })()`);
    await sleep(400);
    const hint30 = await tab.eval(`document.querySelector('.an-export-dialog .exp-block .exp-hint')?.textContent.trim()`);
    const rangeOk = /\d{4}-\d{2}-\d{2} ~ \d{4}-\d{2}-\d{2}/.test(hint30 || '') && /近 30 天/.test(hint30 || '');
    check('A.3 选近 30 天显示具体范围', rangeOk, hint30);

    await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      [...d.querySelectorAll('.exp-presets .el-radio-button')].find((p) => p.textContent.includes('自定义'))?.click();
    })()`);
    await sleep(400);
    const customInfo = await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      return {
        hasPicker: !!d.querySelector('.exp-range'),
        hint: d.querySelector('.exp-block .exp-hint')?.textContent.trim(),
      };
    })()`);
    check('A.3b 自定义出现日期选择器并提示选择', customInfo && customInfo.hasPicker && /请选择/.test(customInfo.hint || ''), JSON.stringify(customInfo));

    // 回到近 30 天（避免自定义未选日期阻断导出）
    await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      [...d.querySelectorAll('.exp-presets .el-radio-button')].find((p) => p.textContent.includes('近 30 天'))?.click();
    })()`);
    await sleep(300);

    // ---- A.4 取消勾选「章节矩阵」后导出 ----
    const unchecked = await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      const cb = [...d.querySelectorAll('.exp-sections .el-checkbox')].find((c) => c.textContent.includes('章节矩阵'));
      if (!cb) return 'NO_CHECKBOX';
      cb.querySelector('input')?.click();
      const left = [...d.querySelectorAll('.exp-sections .el-checkbox')].filter((c) => c.querySelector('input')?.checked).length;
      return 'UNCHECKED left=' + left;
    })()`);
    log(`取消勾选结果：${unchecked}`);
    await sleep(300);
    const summaryHint = await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      const hints = [...d.querySelectorAll('.exp-hint')].map((h) => h.textContent.trim());
      return hints[hints.length - 1];
    })()`);
    check('A.4 内容摘要随勾选更新', /6 个表/.test(summaryHint || '') && !/章节矩阵/.test(summaryHint || ''), summaryHint);

    await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      [...d.querySelectorAll('.el-dialog__footer button')].find((b) => b.textContent.includes('开始导出'))?.click();
    })()`);

    // 等请求与 blob
    let exportReq = '';
    for (let i = 0; i < 60; i++) {
      exportReq = tab.requests.filter((u) => u.includes('/export/')).pop() || '';
      if (exportReq) break;
      await sleep(250);
    }
    for (let i = 0; i < 60; i++) {
      const ready = await tab.eval(`(window.__dl && window.__dl.name) ? 'DL_READY' : 'DL_WAIT'`);
      if (ready === 'DL_READY') break;
      await sleep(250);
    }
    const dl = await tab.eval(`(() => {
      const d = window.__dl || {};
      return { name: d.name || '', size: d.size || 0, type: d.type || '' };
    })()`);
    check(
      'A.4b 导出请求带 sheets（不含 chapter）与时间范围',
      /sheets=overview%2Chomework%2Cexam%2Clab%2Cpractice%2Cqa|sheets=overview,homework,exam,lab,practice,qa/.test(exportReq) &&
        /start=\d{4}-\d{2}-\d{2}/.test(exportReq) && /end=\d{4}-\d{2}-\d{2}/.test(exportReq) && !/chapter/.test(exportReq),
      exportReq
    );
    check(
      'A.5 前端生成 xlsx blob 且文件名正确',
      dl.size > 3000 && /spreadsheetml/.test(dl.type) && dl.name.includes('学习数据导出') && dl.name.endsWith('.xlsx'),
      `${dl.name} ${dl.size}B`
    );

    const closed = await waitFor(tab, `(() => {
      const d = document.querySelector('.an-export-dialog');
      if (!d) return true;
      const ov = d.closest('.el-overlay');
      if (ov && getComputedStyle(ov).display === 'none') return true;
      return d.getBoundingClientRect().height === 0;
    })()`, 5000);
    const closedState = await tab.eval(`(() => {
      const d = document.querySelector('.an-export-dialog');
      const ov = d ? d.closest('.el-overlay') : null;
      return {
        exists: !!d,
        h: d ? Math.round(d.getBoundingClientRect().height) : -1,
        overlayDisplay: ov ? getComputedStyle(ov).display : 'no-overlay',
      };
    })()`);
    check('A.5b 导出后弹窗自动关闭', closed, JSON.stringify(closedState));
    await tab.shot('class-export-02-after-export.png');

    // ---- A.6 console ----
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('A.6 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    await sleep(400);
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
