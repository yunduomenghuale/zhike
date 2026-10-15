#!/usr/bin/env node
/**
 * 浏览器复现「上传解析进度」三个问题：
 *   B1 卡住：状态翻 done 后轮询失明，UI 冻结在最后一帧（render 43/44）
 *   B2 数字裁切：`.ppt-upload-progress-num` 只显示上半截
 *   B3 串台：上传进行中，打开其他章节弹窗显示同一份进度
 * 上传到临时章节（不碰用户数据），用完清理。
 *
 * 运行：node test/e2e/parse-progress-ui-repro.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9223;
const BASE = 'http://localhost:5273';
const API = 'http://127.0.0.1:8005';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-parse';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PDF_MEDIA = '/media/ppt/1eacaf087c394965890ac3ca8f2c0e27.pdf'; // 用户第7章上传过的 44 页 PDF
const COURSE_ID = 7;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------- CDP 客户端（同 cdp-drive.js） ----------------
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
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
    await sleep(600);
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    return name + '.png';
  }
}

async function waitFor(cdp, expr, timeout = 25000) {
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
  if (!ok) throw new Error('登录失败: ' + username);
}

/** 点击章节树中指定标题节点的「课件」按钮 */
async function openChapterPpt(cdp, title) {
  return cdp.eval(`(function(){
    var nodes = Array.from(document.querySelectorAll('.tree-node'));
    var node = nodes.find(function(n){
      var t = n.querySelector('.node-title');
      return t && t.textContent.trim() === ${JSON.stringify(title)};
    });
    if (!node) return 'NODE_NOT_FOUND';
    var btn = Array.from(node.querySelectorAll('.node-action-btn')).find(function(b){ return b.textContent.trim() === '课件'; });
    if (!btn) return 'BTN_NOT_FOUND';
    btn.click();
    return 'CLICKED';
  })()`);
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* reuse */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank',
  ], { stdio: 'ignore' });
  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* not ready */ }
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome devtools 端口未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  return { cdp, chrome };
}

/** 读取当前章节课件弹窗里的进度块状态 */
async function readProgress(cdp) {
  return cdp.eval(`(function(){
    var dlg = document.querySelector('.ppt-dialog');
    if (!dlg) return { dialog: false };
    var block = dlg.querySelector('.ppt-upload-progress');
    var num = dlg.querySelector('.ppt-upload-progress-num');
    var title = dlg.querySelector('.ppt-head-subtitle');
    return {
      dialog: true,
      chapter: title ? title.textContent.trim() : '',
      blockVisible: !!block,
      stageText: block ? (block.querySelector('.ppt-upload-progress-stage')||{}).textContent : '',
      numText: num ? num.textContent.trim() : '',
    };
  })()`);
}

/** 量测进度数字与进度条的几何关系（裁切分析） */
async function measureClip(cdp) {
  return cdp.eval(`(function(){
    var dlg = document.querySelector('.ppt-dialog');
    if (!dlg) return 'NO_DIALOG';
    var num = dlg.querySelector('.ppt-upload-progress-num');
    var head = dlg.querySelector('.ppt-upload-progress-head');
    var bar = dlg.querySelector('.ppt-upload-progress .el-progress-bar__outer');
    var block = dlg.querySelector('.ppt-upload-progress');
    if (!num || !head || !bar) return 'MISSING: num=' + !!num + ' head=' + !!head + ' bar=' + !!bar;
    var r = num.getBoundingClientRect(), hr = head.getBoundingClientRect(),
        br = bar.getBoundingClientRect(), kr = block.getBoundingClientRect();
    var cs = getComputedStyle(num);
    return JSON.stringify({
      numRect: { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) },
      headRect: { top: Math.round(hr.top), bottom: Math.round(hr.bottom), height: Math.round(hr.height) },
      barRect: { top: Math.round(br.top), bottom: Math.round(br.bottom), height: Math.round(br.height) },
      blockRect: { top: Math.round(kr.top), bottom: Math.round(kr.bottom) },
      numOverflowsHead: r.bottom > hr.bottom + 0.5,
      barCoversNum: br.top < r.bottom - 0.5,
      fontSize: cs.fontSize, lineHeight: cs.lineHeight,
      headOverflow: getComputedStyle(head).overflow,
      blockOverflow: getComputedStyle(block).overflow,
    }, null, 1);
  })()`);
}

async function run() {
  // 临时章节（API 预创建，避免污染现有章节数据）
  const loginRes = await fetch(API + '/api/auth/login/', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 't101', password: 'pass1234' }),
  });
  const token = (await loginRes.json()).data.token.access;
  const catRes = await fetch(API + '/api/catalogs/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ course: COURSE_ID, title: 'UI复现临时章节' }),
  });
  const SCRATCH_TITLE = 'UI复现临时章节';
  console.log('临时章节已创建:', SCRATCH_TITLE);

  const { cdp, chrome } = await launchChrome();
  const uploaded = { pptId: null };
  try {
    await login(cdp, 't101', 'pass1234');
    await cdp.navigate(BASE + '/teacher/courses/' + COURSE_ID + '/chapters');
    await waitFor(cdp, `document.body.innerText.includes('第7章')`, 20000);
    await waitFor(cdp, `Array.from(document.querySelectorAll('.tree-node')).some(function(n){return (n.querySelector('.node-title')||{}).textContent === ${JSON.stringify(SCRATCH_TITLE)};})`, 15000);

    // ---- 打开临时章节课件弹窗并注入 PDF ----
    const opened = await openChapterPpt(cdp, SCRATCH_TITLE);
    console.log('打开临时章节课件弹窗:', opened);
    await waitFor(cdp, `!!document.querySelector('.ppt-dialog .ppt-upload')`, 10000);

    await cdp.eval(`(async function(){
      var input = document.querySelector('.ppt-dialog input[type=file]');
      if (!input) throw new Error('file input not found');
      var resp = await fetch(${JSON.stringify(PDF_MEDIA)});
      var blob = await resp.blob();
      var file = new File([blob], 'di-er-zhang.pdf', { type: 'application/pdf' });
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return 'INJECTED ' + file.size;
    })()`);
    console.log('PDF 已注入，开始采样进度…');

    // ---- B3 串台复现：上传进行中，打开其他章节弹窗 ----
    await sleep(2500); // 等渲染阶段跑起来
    const mid = await readProgress(cdp);
    console.log('[上传中·临时章节]', JSON.stringify(mid));
    const clip1 = await measureClip(cdp);
    console.log('[裁切测量·临时章节]', clip1);
    await cdp.shot('parse-ui-1-uploading');

    // 关闭当前弹窗，打开第8章弹窗
    await cdp.eval(`(function(){
      var btn = document.querySelector('.ppt-dialog .el-dialog__headerbtn');
      if (btn) btn.click();
    })()`);
    await sleep(600);
    const other = await openChapterPpt(cdp, '第8章 图形用户界面');
    await sleep(1200);
    const otherProg = await readProgress(cdp);
    console.log('[B3 串台·第8章弹窗]', JSON.stringify(otherProg));
    await cdp.shot('parse-ui-2-other-chapter');

    // 再打开一个没有课件的章节验证
    await cdp.eval(`(function(){
      var btn = document.querySelector('.ppt-dialog .el-dialog__headerbtn');
      if (btn) btn.click();
    })()`);
    await sleep(600);
    await openChapterPpt(cdp, '第9章 多线程');
    await sleep(1200);
    const other2 = await readProgress(cdp);
    console.log('[B3 串台·第9章弹窗]', JSON.stringify(other2));

    // 回到临时章节弹窗，继续看到进度（轮询应仍在跑）
    await cdp.eval(`(function(){
      var btn = document.querySelector('.ppt-dialog .el-dialog__headerbtn');
      if (btn) btn.click();
    })()`);
    await sleep(600);
    await openChapterPpt(cdp, SCRATCH_TITLE);
    await sleep(500);

    // ---- 持续采样直到进度块消失（上传响应回来） ----
    const samples = [];
    const t0 = Date.now();
    let lastText = '';
    let frozeAt = null;
    while (Date.now() - t0 < 150000) {
      const p = await readProgress(cdp);
      const sig = p.stageText + '|' + p.numText;
      if (sig !== lastText) {
        samples.push({ t: Math.round((Date.now() - t0) / 100) / 10, ...p });
        lastText = sig;
      }
      if (!p.blockVisible && samples.length) break;
      await sleep(300);
    }
    console.log('\n进度变化序列：');
    samples.forEach((s) => console.log('   ', JSON.stringify(s)));

    // ---- 冻结判定：最后状态与上传响应到达的时间差 ----
    const finalState = samples[samples.length - 1] || {};
    console.log('\n最终可见状态:', JSON.stringify(finalState));

    // ---- 上传完成后的弹窗状态 ----
    await sleep(1000);
    const done = await readProgress(cdp);
    console.log('[上传后·临时章节]', JSON.stringify(done));
    await cdp.shot('parse-ui-3-done');
  } finally {
    try { await cdp.send('Browser.close'); } catch { /* ignore */ }
    chrome.kill();

    // 清理：删临时章节的课件 + 临时章节
    const del = async (url) => {
      try {
        const r = await fetch(url, { method: 'DELETE', headers: { Authorization: 'Bearer ' + token } });
        return r.status;
      } catch (e) { return String(e); }
    };
    const listRes = await fetch(API + '/api/ppts/?catalog=' + encodeURIComponent(SCRATCH_TITLE) + '', { headers: { Authorization: 'Bearer ' + token } });
    // catalog 标题查不到，改用课程维度找临时章节 id
    const catsRes = await fetch(API + '/api/catalogs/?course=' + COURSE_ID, { headers: { Authorization: 'Bearer ' + token } });
    const catsJson = await catsRes.json();
    const rows = catsJson.data.results || catsJson.data;
    const findDeep = (nodes) => {
      for (const n of nodes || []) {
        if (n.title === SCRATCH_TITLE) return n;
        const hit = findDeep(n.children);
        if (hit) return hit;
      }
      return null;
    };
    const scratch = findDeep(rows);
    if (scratch) {
      const pptsRes = await fetch(API + '/api/ppts/?catalog=' + scratch.id, { headers: { Authorization: 'Bearer ' + token } });
      const pptsJson = await pptsRes.json();
      for (const p of (pptsJson.data.results || [])) {
        console.log('删除临时课件', p.id, await del(API + '/api/ppts/' + p.id + '/'));
      }
      console.log('删除临时章节', scratch.id, await del(API + '/api/catalogs/' + scratch.id + '/'));
    }
    console.log('清理完成');
  }
}

run().catch((e) => { console.error('复现脚本异常:', e); process.exitCode = 2; });
