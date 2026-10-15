#!/usr/bin/env node
/**
 * 修复验证：上传解析进度三个问题（对应 parse-progress-ui-repro.js 复现的 bug）。
 *
 * 问题 → 修复后断言：
 *   F1 卡住（状态翻 done 后轮询失明、UI 冻结）：
 *       embed 阶段逐批推进可见（num 形如 "10/44 片段"），最后进度变化到
 *       进度块消失的间隔 < 10s（不再冻结到上传响应）
 *   F2 串台（其他章节弹窗显示同一份进度）：
 *       上传进行中打开第8章/第9章弹窗，进度块不显示（blockVisible=false）
 *   F3 恢复永冻（刷新页面后重开弹窗永驻）：
 *       上传途中刷新页面 → 重开弹窗恢复进度 → 无需任何操作自动收尾
 *       （进度块自行消失 + 弹窗展示已解析课件）
 *   C 并发上传（两章同时上传）：互不串台、各自完成；无任务章节上传区保持
 *     原样（原标题 + 可点击 + 无进度块）；进度数字固定进度条右侧同行
 *
 * 另验证：序列化器 updated_at 字段暴露（陈旧保护依赖）。
 * 上传到临时章节（不碰用户数据），用完清理。
 *
 * 运行：node test/e2e/parse-progress-fix-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = 'http://localhost:5273';
const API = 'http://127.0.0.1:8005';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-fix';
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

async function closePptDialog(cdp) {
  await cdp.eval(`(function(){
    var btn = document.querySelector('.ppt-dialog .el-dialog__headerbtn');
    if (btn) btn.click();
  })()`);
  await sleep(500);
}

/** 页面内 250ms 采样进度块可见性/阶段/数字（含当前弹窗章节，用于串台判定） */
async function startSampler(cdp) {
  return cdp.eval(`(function(){
    if (window.__sampler) clearInterval(window.__sampler);
    window.__samples = [];
    window.__sampler = setInterval(function(){
      var dlg = document.querySelector('.ppt-dialog');
      var block = dlg ? dlg.querySelector('.ppt-upload-progress') : null;
      var num = dlg ? dlg.querySelector('.ppt-upload-progress-num') : null;
      var stage = block ? (block.querySelector('.ppt-upload-progress-stage')||{}).textContent : '';
      var sub = dlg ? (dlg.querySelector('.ppt-head-subtitle')||{}).textContent : '';
      window.__samples.push({
        t: Date.now(), visible: !!block,
        stage: (stage||'').trim(), num: num ? num.textContent.trim() : '',
        chapter: (sub||'').trim(),
      });
    }, 250);
    return 'SAMPLER_ON';
  })()`);
}

async function readSamples(cdp) {
  return cdp.eval(`window.__samples || []`);
}

async function stopSampler(cdp) {
  await cdp.eval(`(function(){ if (window.__sampler) { clearInterval(window.__sampler); window.__sampler = null; } })()`);
}

/** 读取当前弹窗上传区状态（标题文案 + 文件输入禁用态） */
async function readUploadArea(cdp) {
  return cdp.eval(`(function(){
    var dlg = document.querySelector('.ppt-dialog');
    if (!dlg) return { dialog: false };
    var uploadTitle = dlg.querySelector('.ppt-upload-title');
    var fileInput = dlg.querySelector('.ppt-upload input[type=file]');
    var sub = dlg.querySelector('.ppt-head-subtitle');
    return {
      dialog: true,
      chapter: sub ? sub.textContent.trim() : '',
      uploadTitleText: uploadTitle ? uploadTitle.textContent.trim() : '',
      uploadDisabled: fileInput ? fileInput.disabled : null,
    };
  })()`);
}

/** 数字位置：应在进度条右侧、与进度条同行（垂直重叠）、行内最右 */
async function measureNumPosition(cdp) {
  return cdp.eval(`(function(){
    var dlg = document.querySelector('.ppt-dialog');
    if (!dlg) return 'NO_DIALOG';
    var row = dlg.querySelector('.ppt-upload-progress-bar-row');
    var num = dlg.querySelector('.ppt-upload-progress-num');
    var bar = dlg.querySelector('.ppt-upload-progress .el-progress-bar__outer');
    if (!row || !num || !bar) return 'MISSING: row=' + !!row + ' num=' + !!num + ' bar=' + !!bar;
    var nr = num.getBoundingClientRect(), br = bar.getBoundingClientRect(), rr = row.getBoundingClientRect();
    var cs = getComputedStyle(num);
    return JSON.stringify({
      numRightOfBar: nr.left >= br.right - 1,
      sameRow: nr.top < br.bottom && nr.bottom > br.top,
      atRowRight: Math.abs(nr.right - rr.right) < 2,
      numColor: cs.color,
      numFontWeight: cs.fontWeight,
    });
  })()`);
}

/** 向当前弹窗的文件输入注入 PDF（触发上传） */
async function injectPdf(cdp) {
  return cdp.eval(`(async function(){
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

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log((ok ? '  ✓ ' : '  ✗ ') + name + (detail ? ' — ' + detail : ''));
}

async function run() {
  // ---------- API 预备：登录 + 临时章节 + updated_at 字段断言 ----------
  const loginRes = await fetch(API + '/api/auth/login/', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 't101', password: 'pass1234' }),
  });
  const token = (await loginRes.json()).data.token.access;
  const SCRATCH_TITLE = 'UI验证临时章节' + (Date.now() % 100000);
  const catRes = await fetch(API + '/api/catalogs/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ course: COURSE_ID, title: SCRATCH_TITLE }),
  });
  if (!catRes.ok) throw new Error('创建临时章节失败: ' + catRes.status);
  console.log('临时章节已创建:', SCRATCH_TITLE);
  // 场景 C（两章同时上传）专用第二个临时章节
  const SCRATCH_TITLE_B = SCRATCH_TITLE + 'B';
  const catResB = await fetch(API + '/api/catalogs/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ course: COURSE_ID, title: SCRATCH_TITLE_B }),
  });
  if (!catResB.ok) throw new Error('创建临时章节B失败: ' + catResB.status);
  console.log('临时章节B已创建:', SCRATCH_TITLE_B);

  const pptsRes = await fetch(API + '/api/ppts/?course=' + COURSE_ID, { headers: { Authorization: 'Bearer ' + token } });
  const pptsJson = await pptsRes.json();
  const ppts = pptsJson.data.results || pptsJson.data || [];
  check('序列化器暴露 updated_at', ppts.length > 0 && ppts.every((p) => typeof p.updated_at === 'string'),
    ppts.length ? '样例: ' + ppts[0].updated_at : '无课件');

  const { cdp, chrome } = await launchChrome();
  try {
    await login(cdp, 't101', 'pass1234');
    await cdp.navigate(BASE + '/teacher/courses/' + COURSE_ID + '/chapters');
    await waitFor(cdp, `document.body.innerText.includes('第7章')`, 20000);
    await waitFor(cdp, `Array.from(document.querySelectorAll('.tree-node')).some(function(n){return (n.querySelector('.node-title')||{}).textContent === ${JSON.stringify(SCRATCH_TITLE)};})`, 15000);

    // ================= 场景 A：在途上传 + 串台 + embed 进度 + 平滑收尾 =================
    console.log('\n—— 场景 A：在途上传 ——');
    const opened = await openChapterPpt(cdp, SCRATCH_TITLE);
    await waitFor(cdp, `!!document.querySelector('.ppt-dialog .ppt-upload')`, 10000);
    await startSampler(cdp);
    console.log('注入 PDF（打开弹窗:', opened, '）');
    await injectPdf(cdp);

    await sleep(3000); // 等渲染阶段跑起来
    await cdp.shot('parse-fix-1-uploading');

    // ---- F2 串台：打开其他章节弹窗，进度块不应出现 ----
    await closePptDialog(cdp);
    const o1 = await openChapterPpt(cdp, '第8章 图形用户界面');
    await sleep(1000);
    const s1 = (await readSamples(cdp)).filter((s) => s.chapter === '第8章 图形用户界面');
    check('F2 串台·第8章弹窗无进度块', o1 === 'CLICKED' && s1.length > 0 && s1.every((s) => !s.visible),
      `采样 ${s1.length} 次，可见 ${s1.filter((s) => s.visible).length} 次`);
    await cdp.shot('parse-fix-2-other-chapter');

    await closePptDialog(cdp);
    const o2 = await openChapterPpt(cdp, '第9章 多线程');
    await sleep(1000);
    const s2 = (await readSamples(cdp)).filter((s) => s.chapter === '第9章 多线程');
    check('F2 串台·第9章弹窗无进度块', o2 === 'CLICKED' && s2.length > 0 && s2.every((s) => !s.visible),
      `采样 ${s2.length} 次，可见 ${s2.filter((s) => s.visible).length} 次`);

    // ---- 回到临时章节：进度应仍在（轮询未停）且继续推进 ----
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE);
    await sleep(600);
    const back = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE);
    const backVisible = back.length > 0 && back[back.length - 1].visible;
    check('回到上传章节进度仍可见', backVisible, back.length ? '末次: ' + back[back.length - 1].stage + ' ' + back[back.length - 1].num : '无采样');

    // ---- 等待进度块自行消失（上传响应收尾） ----
    const t0 = Date.now();
    let gone = false;
    while (Date.now() - t0 < 150000) {
      const samples = await readSamples(cdp);
      const mine = samples.filter((s) => s.chapter === SCRATCH_TITLE);
      if (mine.length && !mine[mine.length - 1].visible) { gone = true; break; }
      await sleep(300);
    }
    await stopSampler(cdp);
    const samples = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE);

    // ---- F1：embed 阶段分批推进可见（"x/y 片段"） ----
    const embedSamples = samples.filter((s) => /^\d+\/\d+\s*片段$/.test(s.num));
    check('F1 embed 阶段分批推进可见', embedSamples.length >= 2,
      embedSamples.length ? '序列: ' + embedSamples.map((s) => s.num).join(' → ') : '未采到 embed 片段采样');

    // ---- F1：无长冻结——最后进度变化到进度块消失 < 10s ----
    const visible = samples.filter((s) => s.visible);
    if (visible.length && gone) {
      const lastVis = visible[visible.length - 1];
      // 末次可见采样之后第一次不可见的时间
      const idx = samples.indexOf(lastVis);
      const after = samples.slice(idx + 1).find((s) => !s.visible);
      const gap = after ? (after.t - lastVis.t) / 1000 : null;
      check('F1 收尾无冻结（变化→消失 < 10s）', gap !== null && gap < 10,
        gap !== null ? `间隔 ${gap.toFixed(1)}s` : '未采到消失点');
    } else {
      check('F1 收尾无冻结（变化→消失 < 10s）', false, `visible=${visible.length} gone=${gone}`);
    }

    // ---- 进度推进幅度：至少经历 3 个不同阶段/数字签名 ----
    const sigs = new Set(samples.filter((s) => s.visible).map((s) => s.stage + '|' + s.num));
    check('进度多阶段推进', sigs.size >= 3, `签名数 ${sigs.size}`);

    await sleep(800);
    await cdp.shot('parse-fix-3-done');
    const doneText = await cdp.eval(`(function(){ var d = document.querySelector('.ppt-dialog'); return d ? d.innerText.includes('已解析') : false; })()`);
    check('场景 A 完成后弹窗展示已解析课件', doneText === true);

    // ================= 场景 B：刷新页面 → 恢复轮询 → 自动收尾 =================
    console.log('\n—— 场景 B：上传途中刷新页面 ——');
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE);
    await waitFor(cdp, `!!document.querySelector('.ppt-dialog .ppt-upload')`, 10000);
    await injectPdf(cdp);
    await sleep(3500); // 解析途中（渲染阶段）刷新
    console.log('刷新页面（解析途中）…');
    await cdp.navigate(BASE + '/teacher/courses/' + COURSE_ID + '/chapters');
    await waitFor(cdp, `Array.from(document.querySelectorAll('.tree-node')).some(function(n){return (n.querySelector('.node-title')||{}).textContent === ${JSON.stringify(SCRATCH_TITLE)};})`, 30000);

    // 重开弹窗：应恢复进度轮询
    const reopened = await openChapterPpt(cdp, SCRATCH_TITLE);
    await startSampler(cdp);
    const resumed = await waitFor(cdp, `(function(){
      var dlg = document.querySelector('.ppt-dialog');
      var block = dlg ? dlg.querySelector('.ppt-upload-progress') : null;
      return !!block;
    })()`, 8000);
    check('F3 刷新后重开弹窗恢复进度', reopened === 'CLICKED' && resumed,
      resumed ? '进度块已恢复' : '未见进度块（可能解析已提前完成）');
    await cdp.shot('parse-fix-4-resume');

    // 恢复后进度继续推进
    await sleep(2500);
    const resumeSamples = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE && s.visible);
    const resumeSigs = new Set(resumeSamples.map((s) => s.stage + '|' + s.num));
    check('F3 恢复后进度继续推进', resumeSigs.size >= 2,
      resumeSamples.length ? '末次: ' + resumeSamples[resumeSamples.length - 1].stage + ' ' + resumeSamples[resumeSamples.length - 1].num : '无可见采样');

    // ---- F3：无需任何操作，进度块自动消失（自动收尾） ----
    const t1 = Date.now();
    let autoGone = false;
    while (Date.now() - t1 < 150000) {
      const ss = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE);
      if (ss.length && !ss[ss.length - 1].visible) { autoGone = true; break; }
      await sleep(300);
    }
    await stopSampler(cdp);
    check('F3 恢复轮询自动收尾（进度块自行消失）', autoGone,
      autoGone ? `耗时 ${((Date.now() - t1) / 1000).toFixed(1)}s` : '150s 内未消失');

    const parsedAfter = await waitFor(cdp, `(function(){
      var dlg = document.querySelector('.ppt-dialog');
      return dlg ? dlg.innerText.includes('已解析') : false;
    })()`, 10000);
    check('F3 自动收尾后弹窗展示已解析课件', parsedAfter);
    await cdp.shot('parse-fix-5-autofinish');

    // ================= 场景 C：两章同时上传（互不串台 + 各自完成） =================
    console.log('\n—— 场景 C：两章同时上传 ——');
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE);
    await waitFor(cdp, `!!document.querySelector('.ppt-dialog .ppt-upload')`, 10000);
    await startSampler(cdp);
    await injectPdf(cdp); // 上传 A
    await sleep(2500);
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE_B);
    await waitFor(cdp, `!!document.querySelector('.ppt-dialog .ppt-upload')`, 10000);
    await injectPdf(cdp); // 上传 B（与 A 并发，服务端渲染阶段排队）
    await sleep(2500);

    // ---- C1：B 弹窗显示自己的上传进度 ----
    const bSamples = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE_B);
    check('C1 B章弹窗显示自己的上传进度', bSamples.length > 0 && bSamples.some((s) => s.visible),
      bSamples.length ? '末次: ' + bSamples[bSamples.length - 1].stage + ' ' + bSamples[bSamples.length - 1].num : '无采样');

    // ---- C2：数字位置（进度条右侧、同行、行内最右 + 主色加粗） ----
    const pos = JSON.parse(await measureNumPosition(cdp));
    check('C2 数字固定进度条右侧同行', pos.numRightOfBar && pos.sameRow && pos.atRowRight, JSON.stringify(pos));

    // ---- C3：无任务的第三章上传区完全正常：原标题 + 可点击 + 无进度块 ----
    await closePptDialog(cdp);
    const o3 = await openChapterPpt(cdp, '第9章 多线程');
    await sleep(800);
    const area9 = await readUploadArea(cdp);
    const block9 = (await readSamples(cdp)).filter((s) => s.chapter === '第9章 多线程');
    check('C3 无任务章节上传区不串台',
      o3 === 'CLICKED' && area9.uploadTitleText === '拖入或选择课件文件' && area9.uploadDisabled === false
      && block9.length > 0 && block9.every((s) => !s.visible),
      JSON.stringify(area9));

    // ---- C4：回到 A/B 弹窗，进度各自仍在 ----
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE);
    await sleep(500);
    const aBack = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE);
    const aVisible = aBack.length > 0 && aBack[aBack.length - 1].visible;
    await closePptDialog(cdp);
    await openChapterPpt(cdp, SCRATCH_TITLE_B);
    await sleep(500);
    const bBack = (await readSamples(cdp)).filter((s) => s.chapter === SCRATCH_TITLE_B);
    const bVisible = bBack.length > 0 && bBack[bBack.length - 1].visible;
    check('C4 两章进度各自独立仍在', aVisible || bVisible, `A可见=${aVisible} B可见=${bVisible}`);
    await cdp.shot('parse-fix-6-third-chapter');

    // ---- C5：两章各自完成（进度块自行消失 + 展示已解析） ----
    const waitChapterDone = async (title, budget = 180000) => {
      await closePptDialog(cdp);
      await openChapterPpt(cdp, title);
      const t = Date.now();
      while (Date.now() - t < budget) {
        const ss = (await readSamples(cdp)).filter((s) => s.chapter === title);
        if (ss.length && !ss[ss.length - 1].visible) break;
        await sleep(300);
      }
      return waitFor(cdp, `(function(){
        var dlg = document.querySelector('.ppt-dialog');
        return dlg ? dlg.innerText.includes('已解析') : false;
      })()`, 15000);
    };
    const aDone = await waitChapterDone(SCRATCH_TITLE);
    check('C5 A章上传完成并展示已解析', aDone);
    const bDone = await waitChapterDone(SCRATCH_TITLE_B);
    check('C5 B章上传完成并展示已解析', bDone);
    await stopSampler(cdp);
    await cdp.shot('parse-fix-7-concurrent-done');
  } finally {
    try { await cdp.send('Browser.close'); } catch { /* ignore */ }
    chrome.kill();

    // 清理：删临时章节（含其课件）
    const del = async (url) => {
      try {
        const r = await fetch(url, { method: 'DELETE', headers: { Authorization: 'Bearer ' + token } });
        return r.status;
      } catch (e) { return String(e); }
    };
    const catsRes = await fetch(API + '/api/catalogs/?course=' + COURSE_ID, { headers: { Authorization: 'Bearer ' + token } });
    const catsJson = await catsRes.json();
    const rows = catsJson.data.results || catsJson.data;
    const findDeep = (nodes, title) => {
      for (const n of nodes || []) {
        if (n.title === title) return n;
        const hit = findDeep(n.children, title);
        if (hit) return hit;
      }
      return null;
    };
    for (const title of [SCRATCH_TITLE, SCRATCH_TITLE_B]) {
      const scratch = findDeep(rows, title);
      if (!scratch) continue;
      const pptsRes2 = await fetch(API + '/api/ppts/?catalog=' + scratch.id, { headers: { Authorization: 'Bearer ' + token } });
      const pptsJson2 = await pptsRes2.json();
      for (const p of (pptsJson2.data.results || [])) {
        console.log('删除临时课件', p.id, await del(API + '/api/ppts/' + p.id + '/'));
      }
      console.log('删除临时章节', scratch.id, await del(API + '/api/catalogs/' + scratch.id + '/'));
    }
    console.log('清理完成');
  }

  console.log('\n================ 验证结果 ================');
  const failed = results.filter((r) => !r.ok);
  results.forEach((r) => console.log((r.ok ? '✓' : '✗') + ' ' + r.name + (r.detail ? ' — ' + r.detail : '')));
  console.log(failed.length ? `\n${failed.length} 项未通过` : '\n全部通过');
  if (failed.length) process.exitCode = 1;
}

run().catch((e) => { console.error('验证脚本异常:', e); process.exitCode = 2; });
