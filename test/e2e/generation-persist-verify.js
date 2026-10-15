#!/usr/bin/env node
/**
 * 生成任务进度持久化 E2E（对应需求：刷新/关闭页面不影响进度显示与功能操作）
 *
 * 验证点：
 *   GP.1 点击「生成讲稿」后按钮进入「讲稿 x/y」加载态（is-loading），localStorage 出现任务记录
 *   GP.2 首批完成后刷新页面——不点任何按钮，按钮自动恢复「讲稿 x/y」加载态（任务自动续跑）
 *   GP.3 讲稿持续推进至 18/18 完成，任务记录自动清除
 *   GP.4 点击「配音」进入「配音 x/y」加载态，刷新后自动续跑（同 GP.2）
 *   GP.5 配音推进至完成，记录清除，全部页有配音、gen_status=audio_ready
 *   GP.6 全程无 console.error / 未捕获异常
 *
 * 数据隔离：使用独立章节「E2E生成续跑测试章」（catalog 8），不碰用户数据；
 * 测试数据由外部 shell 创建与清理。
 * 运行：node test/e2e/generation-persist-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const TEACHER = 't101';
const PWS = ['pass1234', 'A0987654'];
const COURSE_ID = 5;
const CATALOG_ID = Number(process.env.E2E_CATALOG_ID || 8);
const CATALOG_TITLE = process.env.E2E_CATALOG_TITLE || 'E2E生成续跑测试章';
const TOTAL_PAGES = 18;
const LS_KEY = 'zhike:generation-tasks';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-gp-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

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
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
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
  async reload() {
    await this.send('Page.reload', { ignoreCache: false });
    for (let i = 0; i < 150; i++) {
      const ready = await this.eval('document.readyState').catch(() => null);
      if (ready === 'complete') break;
      await sleep(100);
    }
    await sleep(800);
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
    await sleep(250);
  }
  return false;
}

async function login(cdp, username, passwords) {
  await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
  for (const password of passwords) {
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
    const ok = await waitFor(cdp, `location.pathname === '/dashboard' || location.pathname === '/'`, 12000);
    if (ok) { log(`登录成功（${username}）`); return; }
    log(`密码 ${password} 未命中，尝试下一个`);
  }
  throw new Error('登录失败: ' + username);
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 忽略 */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu', '--enable-unsafe-swiftshader',
    '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank',
  ], { stdio: 'ignore', detached: true });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.filter((t) => t.type === 'page')[0];
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
  try { execSync(`taskkill /PID ${chrome.pid} /T /F`, { stdio: 'ignore' }); } catch { /* 进程可能已退出 */ }
  try { chrome.kill(); } catch { /* ignore */ }
}

async function apiCall(cdp, method, url, body) {
  return cdp.eval(`(async function(){
    var tok = localStorage.getItem('access_token') || '';
    var opt = { method: ${JSON.stringify(method)}, headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' } };
    if (${JSON.stringify(body === undefined ? null : body)} !== null) opt.body = JSON.stringify(${JSON.stringify(body === undefined ? null : body)});
    var r = await fetch(${JSON.stringify(url)}, opt);
    var text = await r.text();
    try { return JSON.parse(text); } catch (e) { return { __raw: text, __status: r.status }; }
  })()`);
}

// 找到目标章节节点内文本包含 btnKey 的操作按钮，返回 {text, loading}；click=true 时点击
const FIND_BTN = `(function(titleKey, btnKey, click){
  var titles = Array.from(document.querySelectorAll('.node-title'));
  var t = titles.find(function(el){ return el.textContent.indexOf(titleKey) >= 0; });
  if (!t) return null;
  var el = t;
  while (el && !(el.querySelector && el.querySelector('.node-action-group'))) el = el.parentElement;
  if (!el) return null;
  var btn = Array.from(el.querySelectorAll('.node-action-btn')).find(function(b){ return b.textContent.indexOf(btnKey) >= 0; });
  if (!btn) return null;
  var info = { text: btn.textContent.trim(), loading: btn.classList.contains('is-loading') };
  if (click) btn.click();
  return info;
})`;

// 按钮处于「任务进行中」态：x/y 数字 + is-loading（区别于持久化的「续讲稿/续配音」静态标签）
const btnRunningExpr = (btnKey) => `(function(){
  var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, ${JSON.stringify(btnKey)}, false);
  return !!(info && info.loading && /\\d+\\/\\d+/.test(info.text));
})()`;
const btnTextExpr = (btnKey) => `(function(){
  var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, ${JSON.stringify(btnKey)}, false);
  return info ? info.text : '';
})()`;

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

async function main() {
  const { cdp, chrome } = await launchChrome();
  try {
    await login(cdp, TEACHER, PWS);
    await cdp.navigate(`${BASE}/teacher/courses/${COURSE_ID}/chapters`);
    const nodeReady = await waitFor(cdp, `Array.from(document.querySelectorAll('.node-title')).some(function(el){return el.textContent.indexOf('${CATALOG_TITLE}')>=0})`, 20000);
    if (!nodeReady) throw new Error('章节树未加载出目标节点');
    await sleep(800);

    // ---------- GP.1 讲稿任务启动 ----------
    const btn0 = await cdp.eval(btnTextExpr('讲稿'));
    log('点击前按钮: ' + btn0);
    await cdp.eval(`(${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '讲稿', true)`);
    const started = await waitFor(cdp, btnRunningExpr('讲稿'), 30000);
    const btn1 = await cdp.eval(btnTextExpr('讲稿'));
    check('GP.1 点击「生成讲稿」后按钮进入 讲稿 x/y 加载态', started, btn1);
    await cdp.shot('gp1-script-running');
    const record1 = await cdp.eval(`(localStorage.getItem(${JSON.stringify(LS_KEY)}) || '{}')`);
    check('GP.1b 任务记录已写入 localStorage', record1.includes(`"script:${CATALOG_ID}"`), record1.slice(0, 110));

    // ---------- GP.2 中途刷新 → 自动续跑 ----------
    await waitFor(cdp, `(function(){
      var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '讲稿', false);
      var m = info && info.text.match(/(\\d+)\\/(\\d+)/);
      return m && Number(m[1]) > 0;
    })()`, 40000);
    log('刷新前按钮: ' + await cdp.eval(btnTextExpr('讲稿')));
    await cdp.reload();
    await waitFor(cdp, `Array.from(document.querySelectorAll('.node-title')).some(function(el){return el.textContent.indexOf('${CATALOG_TITLE}')>=0})`, 20000);
    const resumed = await waitFor(cdp, btnRunningExpr('讲稿'), 20000);
    const btn2 = await cdp.eval(btnTextExpr('讲稿'));
    check('GP.2 刷新后无需点击，按钮自动恢复 讲稿 x/y 加载态（任务自动续跑）', resumed, btn2);
    await cdp.shot('gp2-script-resumed-after-reload');

    // ---------- GP.3 续跑至完成 ----------
    const scriptDone = await waitFor(cdp, `(function(){
      var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '讲稿', false);
      return info && !info.loading && info.text === '讲稿';
    })()`, 120000);
    check('GP.3 讲稿续跑至完成（按钮回到「讲稿」）', scriptDone);
    const vlist = await apiCall(cdp, 'GET', `/api/videos/?catalog=${CATALOG_ID}`);
    const vdata = vlist.data || {};
    const video = (Array.isArray(vdata) ? vdata : (vdata.results || []))[0] || {};
    const scripts = video.scripts || [];
    const withScript = scripts.filter((s) => String(s.script || '').trim()).length;
    check('GP.3b 全部页有讲稿', withScript === TOTAL_PAGES, `${withScript}/${TOTAL_PAGES}`);
    const record2 = await cdp.eval(`(localStorage.getItem(${JSON.stringify(LS_KEY)}) || '{}')`);
    check('GP.3c 完成后任务记录已清除', !record2.includes(`"script:${CATALOG_ID}"`), record2.slice(0, 80));

    // ---------- GP.4 配音任务：启动 → 刷新 → 自动续跑 ----------
    const abtn0 = await cdp.eval(btnTextExpr('配音'));
    log('点击前按钮: ' + abtn0);
    await cdp.eval(`(${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '配音', true)`);
    const audioStarted = await waitFor(cdp, btnRunningExpr('配音'), 30000);
    check('GP.4 点击「配音」后按钮进入 配音 x/y 加载态', audioStarted, await cdp.eval(btnTextExpr('配音')));
    await waitFor(cdp, `(function(){
      var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '配音', false);
      var m = info && info.text.match(/(\\d+)\\/(\\d+)/);
      return m && Number(m[1]) > 0;
    })()`, 30000);
    log('刷新前按钮: ' + await cdp.eval(btnTextExpr('配音')));
    await cdp.shot('gp4-audio-running');
    await cdp.reload();
    await waitFor(cdp, `Array.from(document.querySelectorAll('.node-title')).some(function(el){return el.textContent.indexOf('${CATALOG_TITLE}')>=0})`, 20000);
    const audioResumed = await waitFor(cdp, btnRunningExpr('配音'), 20000);
    check('GP.4b 刷新后配音任务自动续跑（配音 x/y 加载态）', audioResumed, await cdp.eval(btnTextExpr('配音')));
    await cdp.shot('gp4b-audio-resumed-after-reload');

    // ---------- GP.5 配音续跑至完成 ----------
    const audioDone = await waitFor(cdp, `(function(){
      var info = (${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '配音', false);
      return info && !info.loading && info.text === '配音';
    })()`, 180000);
    check('GP.5 配音续跑至完成（按钮回到「配音」）', audioDone);
    const vlist2 = await apiCall(cdp, 'GET', `/api/videos/?catalog=${CATALOG_ID}`);
    const vdata2 = vlist2.data || {};
    const video2 = (Array.isArray(vdata2) ? vdata2 : (vdata2.results || []))[0] || {};
    const scripts2 = video2.scripts || [];
    const withAudio = scripts2.filter((s) => s.audio_url).length;
    check('GP.5b 全部页有配音', withAudio === TOTAL_PAGES, `${withAudio}/${TOTAL_PAGES}`);
    check('GP.5c gen_status=audio_ready', video2.gen_status === 'audio_ready', video2.gen_status);
    const record3 = await cdp.eval(`(localStorage.getItem(${JSON.stringify(LS_KEY)}) || '{}')`);
    check('GP.5d 配音完成后任务记录已清除', !record3.includes(`"audio:${CATALOG_ID}"`), record3.slice(0, 80));

    // ---------- GP.6 控制台干净 ----------
    check('GP.6 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 2).join(' ; '));
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n==== 汇总: ${results.length - failed}/${results.length} 通过 ====`);
  if (failed === 0) console.log('ALL_PASS');
  process.exit(failed ? 1 : 0);
}

main().catch((err) => { console.error('FATAL', err); process.exit(2); });
