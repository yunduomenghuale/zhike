#!/usr/bin/env node
/**
 * 讲解稿与配音页三项反馈 E2E：
 *   AP.1 章节列表点「配音」打开「讲解稿与配音」页（script 模式）
 *   AP.2 配音未完成时后台续跑，对话框内出现「正在合成配音 x/y」进度横幅
 *   AP.3 分页音频为自定义播放器（.page-audio），无原生 controls
 *   AP.4 未播放时进度条为 0（0:00 / x:xx，填充宽 0%）——修复「未播已有进度」
 *   AP.5 播放后进度填充可见增长（浅轨道+深填充，进度可辨）——修复「看不清进度」
 *   AP.6 单页「重新配音」：加载态→完成后该页出现播放器与「已配音」标
 *   AP.7 单页「重新生成本页」（有配音页）：确认框说明连带重配 → 讲稿重生成 + 自动重配，音频地址变化
 *   AP.8 后台批次推进时，已打开对话框内的分页配音实时合并出现（live merge）
 *   AP.9 无 console.error / 未捕获异常
 *
 * 数据隔离：独立章节「E2E生成续跑测试章」（catalog 9 / video 5），18 页讲稿、前 5 页有配音；
 * 测试数据由外部 shell 创建与清理。
 * 运行：node test/e2e/audio-page-verify.js
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
const CATALOG_ID = 9;
const CATALOG_TITLE = 'E2E生成续跑测试章';
const LS_KEY = 'zhike:generation-tasks';

const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 190);
const PROFILE = `D:/tmp/zhike-ap-e2e/run-${RUN_ID}`;

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

// 章节树节点按钮
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

// 讲解稿与配音弹窗中指定页的操作按钮
const PAGE_ITEM = `(function(pageNo){
  var items = Array.from(document.querySelectorAll('.script-item'));
  return items.find(function(el){
    var p = el.querySelector('.script-page');
    return p && p.textContent.replace(/\\s/g, '').indexOf('第' + pageNo + '页') >= 0;
  }) || null;
})`;
const PAGE_BTN = `(function(pageNo, btnKey, click){
  var it = (${PAGE_ITEM})(pageNo);
  if (!it) return null;
  var btn = Array.from(it.querySelectorAll('.script-page-actions button')).find(function(b){ return b.textContent.indexOf(btnKey) >= 0; });
  if (!btn) return null;
  var info = { text: btn.textContent.trim(), loading: btn.classList.contains('is-loading') };
  if (click) btn.click();
  return info;
})`;

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
    await sleep(600);

    // ---------- AP.1 配音按钮打开讲解稿与配音页 ----------
    await cdp.eval(`(${FIND_BTN})(${JSON.stringify(CATALOG_TITLE)}, '配音', true)`);
    const dialogUp = await waitFor(cdp, `(function(){
      var d = document.querySelector('.script-dialog');
      var t = document.querySelector('.script-head-title');
      return !!(d && t && t.textContent.indexOf('讲解稿与配音') >= 0);
    })()`, 15000);
    check('AP.1 点「配音」打开「讲解稿与配音」页', dialogUp);
    await waitFor(cdp, `document.querySelectorAll('.script-item').length > 0`, 15000);

    // ---------- AP.2 进度横幅 ----------
    const banner = await waitFor(cdp, `(function(){
      var b = document.querySelector('.script-gen-banner');
      return !!(b && b.textContent.indexOf('正在合成配音') >= 0);
    })()`, 10000);
    check('AP.2 对话框内出现「正在合成配音 x/y」进度横幅', banner,
      await cdp.eval(`(document.querySelector('.script-gen-banner')||{}).textContent || ''`));
    await cdp.shot('ap2-dialog-with-progress-banner');

    // ---------- AP.3 自定义播放器、无原生 controls ----------
    const playerInfo = await cdp.eval(`(function(){
      return {
        custom: document.querySelectorAll('.script-list .page-audio').length,
        nativeVisible: Array.from(document.querySelectorAll('.script-list audio')).filter(function(a){ return a.hasAttribute('controls') && a.offsetParent !== null; }).length,
      };
    })()`);
    check('AP.3 分页音频为自定义播放器且无原生 controls', playerInfo.custom > 0 && playerInfo.nativeVisible === 0,
      `自定义播放器 ${playerInfo.custom} 个，原生 controls ${playerInfo.nativeVisible} 个`);

    // ---------- AP.4 未播放进度为 0 ----------
    const initial = await cdp.eval(`(function(){
      var p = document.querySelector('.script-list .page-audio');
      if (!p) return null;
      var fill = p.querySelector('.page-audio-fill');
      var times = Array.from(p.querySelectorAll('.page-audio-time')).map(function(e){ return e.textContent.trim(); });
      return { width: fill ? fill.style.width : null, times: times };
    })()`);
    check('AP.4 未播放时进度为 0（0:00 / 填充 0%）',
      !!initial && (initial.width === '0%' || initial.width === '0' || initial.width === '') && initial.times[0] === '0:00',
      JSON.stringify(initial));

    // ---------- AP.5 播放后进度可见增长 ----------
    await cdp.eval(`(function(){
      var p = document.querySelector('.script-list .page-audio');
      var btn = p && p.querySelector('.page-audio-btn');
      if (btn) btn.click();
    })()`);
    await sleep(1600);
    const playingInfo = await cdp.eval(`(function(){
      var p = document.querySelector('.script-list .page-audio');
      if (!p) return null;
      var fill = p.querySelector('.page-audio-fill');
      var w = fill ? parseFloat(fill.style.width) : 0;
      var times = Array.from(p.querySelectorAll('.page-audio-time')).map(function(e){ return e.textContent.trim(); });
      return { width: w, times: times };
    })()`);
    check('AP.5 播放中进度填充可见增长', !!playingInfo && playingInfo.width > 0.5, JSON.stringify(playingInfo));
    await cdp.shot('ap5-playing-visible-progress');
    await cdp.eval(`(function(){
      var p = document.querySelector('.script-list .page-audio');
      var btn = p && p.querySelector('.page-audio-btn');
      if (btn) btn.click();
    })()`);

    // ---------- AP.6 单页重新配音（挑后台批次尚未轮到的第 18 页） ----------
    const regenAudioBtn = await cdp.eval(`(${PAGE_BTN})(18, '重新配音', true)`);
    check('AP.6 第 18 页存在「重新配音」按钮并已点击', !!regenAudioBtn, regenAudioBtn && regenAudioBtn.text);
    const audioRegenDone = await waitFor(cdp, `(function(){
      var it = (${PAGE_ITEM})(18);
      return !!(it && it.querySelector('.page-audio'));
    })()`, 30000);
    check('AP.6b 重新配音完成后第 18 页出现播放器', audioRegenDone);

    // ---------- 等后台配音全部完成（避免与单页重生成竞争） ----------
    await waitFor(cdp, `(function(){
      var b = document.querySelector('.script-gen-banner');
      return !b;
    })()`, 120000);

    // ---------- AP.7 单页重新生成（讲稿+自动重配） ----------
    const srcBefore = await cdp.eval(`(function(){
      var it = (${PAGE_ITEM})(1);
      var a = it && it.querySelector('.page-audio-el');
      return a ? a.getAttribute('src') : null;
    })()`);
    await cdp.eval(`(${PAGE_BTN})(1, '重新生成本页', true)`);
    await sleep(400);
    // 确认框：说明会连带重配 → 确认
    const confirmText = await cdp.eval(`(function(){
      var box = document.querySelector('.el-message-box');
      return box ? box.textContent.replace(/\\s+/g, ' ').slice(0, 120) : '';
    })()`);
    const confirmOk = await cdp.eval(`(function(){
      var box = document.querySelector('.el-message-box');
      if (!box) return false;
      var btn = box.querySelector('.el-button--primary');
      if (btn) btn.click();
      return true;
    })()`);
    check('AP.7 确认框说明「讲稿覆盖+自动重配」且可确认',
      confirmOk && confirmText.indexOf('自动重新合成') >= 0, confirmText);
    const regenChainDone = await waitFor(cdp, `(function(before){
      var it = (${PAGE_ITEM})(1);
      var a = it && it.querySelector('.page-audio-el');
      return !!(a && a.getAttribute('src') && a.getAttribute('src') !== before);
    })(${JSON.stringify(srcBefore)})`, 60000);
    check('AP.7b 第 1 页讲稿重生成后自动重配（音频地址已更新）', regenChainDone);
    await cdp.shot('ap7-page1-regenerated');

    // ---------- AP.8 后台批次已把分页配音实时合并进弹窗 ----------
    const finalState = await cdp.eval(`(function(){
      return {
        players: document.querySelectorAll('.script-list .page-audio').length,
        tags: Array.from(document.querySelectorAll('.script-item .el-tag')).filter(function(t){ return t.textContent.indexOf('已配音') >= 0; }).length,
      };
    })()`);
    check('AP.8 弹窗内配音页实时补齐（播放器随批次出现）', finalState.players >= 17, JSON.stringify(finalState));

    // ---------- AP.9 控制台干净 ----------
    check('AP.9 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 2).join(' ; '));
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n==== 汇总: ${results.length - failed}/${results.length} 通过 ====`);
  if (failed === 0) console.log('ALL_PASS');
  process.exit(failed ? 1 : 0);
}

main().catch((err) => { console.error('FATAL', err); process.exit(2); });
