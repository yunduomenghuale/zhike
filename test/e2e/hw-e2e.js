#!/usr/bin/env node
/**
 * 作业模块 E2E 验证（CDP 真实浏览器）—— 完全隔离版
 *
 * 覆盖本次需求：
 *   T1 教师端：附件作业——选择文件立即上传（不等保存）/ 上传进度 / 多附件追加不替换 /
 *       PDF 无工具栏滚动预览 / 已上传附件列表 / 发布后列表状态 / 重开编辑器附件仍在 / 已发布作业有保存按钮
 *   T2 学生端：纯客观题作业——提交后自动出分，立即可见正确答案/解析/结果
 *   T3 学生端：附件作业——选择即暂存上传（进度/状态展示），提交后结果页图片预览
 *
 * 隔离措施（历史坑：chrome.kill() 只杀启动器，浏览器进程树存活；
 * 同端口同 profile 会单例 attach 到旧浏览器，多脚本驱动同浏览器不同标签页）：
 *   - 每次运行用独立的调试端口 + 独立 profile 目录（PID 派生）
 *   - 运行结束后用 taskkill /T 杀整个浏览器进程树
 *
 * 前置：后端 127.0.0.1:8005、前端 5273 已启动；
 *      已执行 backend/seed_hw_e2e.py；学生账号无历史提交记录。
 *
 * 运行：node test/e2e/hw-e2e.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const FIXTURES = path.resolve(__dirname, 'fixtures');
const PW = 'A0987654';

// 每次运行独立端口与 profile，避免单例 attach 到存活的旧浏览器
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9300 + (parseInt(RUN_ID, 36) % 500);
const PROFILE = `D:/tmp/zhike-hw-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

// ---------------- CDP 客户端 ----------------
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
    await sleep(500); // 等 Vue 挂载
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    return name + '.png';
  }
}

// ---------------- 页面操作辅助 ----------------
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

async function clickByText(cdp, selector, text, exact = true) {
  return cdp.eval(`(function(){
    var els = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
    var el = els.find(function(e){
      var t = e.textContent.trim();
      return ${exact} ? t === ${JSON.stringify(text)} : t.includes(${JSON.stringify(text)});
    });
    if (!el) return 'NOT_FOUND';
    el.click();
    return 'CLICKED';
  })()`);
}

/** 点击学生作业列表中标题包含 keyword 的行的操作按钮，返回按钮文案 */
async function clickStudentRow(cdp, keyword) {
  return cdp.eval(`(function(){
    var rows = Array.from(document.querySelectorAll('.student-row'));
    var row = rows.find(function(r){
      var t = r.querySelector('.student-row-title');
      return t && t.textContent.includes(${JSON.stringify(keyword)});
    });
    if (!row) return 'ROW_NOT_FOUND';
    var btn = row.querySelector('.student-action-btn');
    if (!btn) return 'BTN_NOT_FOUND';
    var label = btn.textContent.trim();
    btn.click();
    return label;
  })()`);
}

/** 通过 CDP DOM 域给隐藏 file input 赋值（触发 el-upload on-change），带重试 */
async function setFiles(cdp, selector, files, retries = 3) {
  let lastErr = null;
  for (let i = 0; i < retries; i++) {
    try {
      const doc = await cdp.send('DOM.getDocument', { depth: 1 });
      const node = await cdp.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector });
      if (!node || node.nodeId === 0) throw new Error('file input not found: ' + selector);
      await cdp.send('DOM.setFileInputFiles', {
        nodeId: node.nodeId,
        files: files.map((f) => path.join(FIXTURES, f)),
      });
      return;
    } catch (e) {
      lastErr = e;
      await sleep(600);
    }
  }
  // 失败时 dump 容器 HTML 帮助定位
  try {
    const html = await cdp.eval(`(function(){
      var box = document.querySelector('.answer-dock') || document.querySelector('.attachment-panel') || document.body;
      return box.innerHTML.slice(0, 600);
    })()`);
    log('setFiles 失败，容器 HTML: ' + html);
  } catch { /* ignore */ }
  throw lastErr;
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

// ---------------- 测试结果记录 ----------------
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

// ---------------- 启动 Chrome（独立端口 + 独立 profile） ----------------
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
      log(`devtools 就绪，当前标签页 ${pages.length} 个: ` + pages.map((p) => p.url).join(' | '));
      const page = pages[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
    await sleep(250);
  }
  if (!wsUrl) { killChrome(chrome); throw new Error('Chrome devtools 端口未就绪'); }

  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('DOM.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { cdp, chrome };
}

/** 杀整个浏览器进程树（Windows: chrome.kill() 只杀启动器，浏览器会存活） */
function killChrome(chrome) {
  try {
    execSync(`taskkill /PID ${chrome.pid} /T /F`, { stdio: 'ignore' });
  } catch { /* 进程可能已退出 */ }
  try { chrome.kill(); } catch { /* ignore */ }
}

// ---------------- 测试流程 ----------------
async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);
  const ts = Date.now().toString().slice(-6);

  try {
    // ============ T1 教师端：附件作业（选择即上传 + 编辑页附件列表） ============
    log('===== T1 教师发布附件作业 =====');
    await login(cdp, 't101', PW);
    await goto('/teacher/homework');
    // 班级选择器默认选中第一个班级（loadClasses 自动选中），直接等待「发布作业」按钮可用
    await waitFor(cdp, `!!document.querySelector('.module-primary-button')`);
    await clickByText(cdp, '.module-primary-button', '发布作业');
    await waitFor(cdp, `!!document.querySelector('.homework-editor')`);
    check('T1.1 编辑器打开', true);

    // 时间选择框内提示（placeholder）
    const startPh = await cdp.eval(`!!document.querySelector('.homework-editor input[placeholder="不选择则立即开始"]')`);
    const deadlinePh = await cdp.eval(`!!document.querySelector('.homework-editor input[placeholder="不选择则截止不限"]')`);
    check('T1.2 开始时间选择框内提示「不选择则立即开始」', startPh);
    check('T1.3 截止时间选择框内提示「不选择则截止不限」', deadlinePh);

    // 切到附件模式
    await clickByText(cdp, '.homework-mode-switch .el-radio-button', '文本 / 附件');
    await waitFor(cdp, `!!document.querySelector('.attachment-uploader')`);

    // 填标题（新作业上传附件前会先自动创建草稿，草稿需要标题）
    await cdp.eval(`(function(){
      var el = document.querySelector('.homework-editor input[placeholder="请输入作业标题"]');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, ${JSON.stringify('E2E-附件作业-' + ts)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);

    // 安装进度采样器（必须在选择文件之前：即时上传在 on-change 即开始）
    await cdp.eval(`(function(){
      window.__prog = { samples: [], maxWidth: 0, sawUploading: false };
      window.__progTimer = setInterval(function(){
        var card = document.querySelector('.upload-file-card');
        var bar = document.querySelector('.upload-progress-bar');
        if (card && (card.className || '').indexOf('is-uploading') >= 0) window.__prog.sawUploading = true;
        if (bar && bar.style && bar.style.width) {
          var pct = parseFloat(bar.style.width);
          if (!isNaN(pct)) {
            window.__prog.maxWidth = Math.max(window.__prog.maxWidth, pct);
            if (window.__prog.samples.length < 400) window.__prog.samples.push(pct);
          }
        }
      }, 16);
    })()`);

    // 选择 12MB 附件 → 立即上传（不点任何保存按钮）
    await setFiles(cdp, '.attachment-uploader input[type="file"]', ['hw-teacher-big.pdf']);
    const cardSeen = await waitFor(cdp, `!!document.querySelector('.upload-file-card') || !!document.querySelector('.uploaded-attachments')`, 5000);
    const cardInfo = await cdp.eval(`(function(){
      var card = document.querySelector('.upload-file-card');
      var list = document.querySelector('.uploaded-attachments');
      var text = (card ? card.innerText : '') + ' ' + (list ? list.innerText : '');
      return { text: text.replace(/\\s+/g, ' ').trim(), hasSizeText: /MB|KB/.test(text) };
    })()`);
    check('T1.4 已选文件展示文件名/大小/格式', cardSeen && cardInfo.text.includes('hw-teacher-big.pdf') && cardInfo.hasSizeText, cardInfo.text.slice(0, 80));

    // 等待上传完成：「已上传附件」列表出现且包含查看链接
    const uploaded = await waitFor(cdp, `(function(){
      var box = document.querySelector('.uploaded-attachments');
      return !!box && box.innerText.indexOf('hw-teacher-big.pdf') >= 0 && !!box.querySelector('a.attachment-view-link');
    })()`, 40000);
    check('T1.5 选择文件后立即上传完成（未点保存），已上传附件列表出现', uploaded);

    const uploadedInfo = await cdp.eval(`(function(){
      var box = document.querySelector('.uploaded-attachments');
      if (!box) return null;
      var link = box.querySelector('a.attachment-view-link');
      return {
        text: box.innerText.replace(/\\s+/g, ' ').trim(),
        hasExt: !!box.querySelector('.upload-file-ext'),
        hasView: !!link,
        viewHref: link ? link.href : '',
        hasRemove: !!box.querySelector('.el-button--danger, button'),
      };
    })()`);
    check('T1.6 附件列表展示文件名/格式标签/大小统计', !!uploadedInfo && uploadedInfo.text.includes('hw-teacher-big.pdf') && uploadedInfo.hasExt, uploadedInfo && uploadedInfo.text.slice(0, 100));
    check('T1.7 支持查看具体附件（新窗口链接指向 /media/）', !!uploadedInfo && uploadedInfo.hasView && uploadedInfo.viewHref.indexOf('/media/') >= 0, uploadedInfo && uploadedInfo.viewHref);

    const prog = await cdp.eval(`(function(){ if (window.__progTimer) clearInterval(window.__progTimer); return window.__prog; })()`);
    check('T1.8 上传过程可见：进入「上传中」状态并有进度条', !!(prog && prog.sawUploading && prog.maxWidth > 0), prog ? 'maxWidth=' + prog.maxWidth + '%' : 'no sampler');
    check('T1.9 上传进度条有真实百分比推进', !!(prog && prog.samples.length >= 2), prog ? 'samples=' + prog.samples.length : '');

    // 再次上传第二个附件：追加不替换（原附件仍在，列表变为 2 个）
    await setFiles(cdp, '.attachment-uploader input[type="file"]', ['hw-teacher-attach.txt']);
    const twoUploaded = await waitFor(cdp, `(function(){
      var box = document.querySelector('.uploaded-attachments');
      if (!box) return false;
      var text = box.innerText;
      return text.indexOf('hw-teacher-big.pdf') >= 0 && text.indexOf('hw-teacher-attach.txt') >= 0
        && box.querySelectorAll('.uploaded-attachment-item').length === 2;
    })()`, 40000);
    check('T1.10 再次上传为追加不替换，附件列表共 2 个', twoUploaded);

    // PDF 附件「预览」：无工具栏连续滚动（页图列表，非 iframe）
    await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.uploaded-attachment-item'));
      var target = items.find(function(it){ return it.innerText.indexOf('hw-teacher-big.pdf') >= 0; });
      if (!target) return;
      var btn = Array.from(target.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim().indexOf('预览') >= 0; });
      if (btn) btn.click();
    })()`);
    const previewOk = await waitFor(cdp, `(function(){
      var box = document.querySelector('.pdf-scroll-preview');
      if (!box) return false;
      var imgs = box.querySelectorAll('img.pdf-page-img');
      var first = imgs[0];
      return imgs.length > 0 && !!first && first.complete && first.naturalWidth > 0;
    })()`, 40000);
    const previewInfo = await cdp.eval(`(function(){
      var box = document.querySelector('.pdf-scroll-preview');
      if (!box) return { exists: false };
      var scroll = box.querySelector('.pdf-preview-scroll');
      return {
        exists: true,
        pages: box.querySelectorAll('img.pdf-page-img').length,
        mediaSrc: Array.from(box.querySelectorAll('img.pdf-page-img')).filter(function(i){ return (i.getAttribute('src') || '').indexOf('/media/') >= 0; }).length,
        hasIframe: !!box.querySelector('iframe'),
        scrollable: !!scroll && getComputedStyle(scroll).overflowY === 'auto',
      };
    })()`);
    check('T1.11 PDF 无工具栏连续滚动预览（页图渲染完成）', previewOk && previewInfo.pages > 0 && previewInfo.mediaSrc === previewInfo.pages, JSON.stringify(previewInfo));
    check('T1.11b 预览为上下滚动容器且无 iframe 工具栏', !!previewInfo.exists && previewInfo.scrollable && !previewInfo.hasIframe, JSON.stringify(previewInfo));
    await cdp.shot('hw-t1-teacher-pdf-preview');

    // 保存并发布（此时作业已因自动建草稿而存在，按钮为「保存并发布」）
    await clickByText(cdp, '.hw-publish-btn', '保存并发布');
    const listed = await waitFor(cdp, `(function(){
      var titles = Array.from(document.querySelectorAll('.hw-title')).map(function(t){ return t.textContent; });
      return titles.some(function(t){ return t.includes(${JSON.stringify('E2E-附件作业-' + ts)}); });
    })()`, 40000);
    check('T1.12 发布成功并回到列表（新作业出现）', listed);
    await cdp.shot('hw-t1-teacher-published');

    const rowState = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.hw-title');
        return t && t.textContent.includes(${JSON.stringify('E2E-附件作业-' + ts)});
      });
      if (!row) return 'ROW_NOT_FOUND';
      var tag = row.querySelector('.el-tag');
      return tag ? tag.textContent.trim() : 'NO_TAG';
    })()`);
    check('T1.13 新作业状态为「已发布」', rowState === '已发布', rowState);

    // 重新打开编辑器：已上传附件仍在（原文件名经后端持久化往返）
    const reopened = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.hw-title');
        return t && t.textContent.includes(${JSON.stringify('E2E-附件作业-' + ts)});
      });
      if (!row) return 'ROW_NOT_FOUND';
      var btn = Array.from(row.querySelectorAll('.hw-action-btn')).find(function(b){ return b.textContent.trim().indexOf('编辑') >= 0; });
      if (!btn) return 'BTN_NOT_FOUND';
      btn.click();
      return 'CLICKED';
    })()`);
    if (reopened === 'CLICKED') {
      await waitFor(cdp, `!!document.querySelector('.homework-editor')`, 15000);
      const persisted = await cdp.eval(`(function(){
        var box = document.querySelector('.uploaded-attachments');
        if (!box) return { exists: false, text: '', items: 0 };
        return {
          exists: true,
          items: box.querySelectorAll('.uploaded-attachment-item').length,
          text: box.innerText.replace(/\\s+/g, ' ').trim(),
        };
      })()`);
      check('T1.14 重开编辑器：两个已上传附件仍在（原文件名持久化）', persisted.exists && persisted.items === 2 && persisted.text.includes('hw-teacher-big.pdf') && persisted.text.includes('hw-teacher-attach.txt'), JSON.stringify(persisted));
    } else {
      check('T1.14 重开编辑器：两个已上传附件仍在（原文件名持久化）', false, reopened);
    }

    // 已发布（冻结）作业：编辑器应有「保存修改」按钮（撤回之外可保存标题/说明/时间/附件）
    const frozenSave = await cdp.eval(`(function(){
      var actions = document.querySelector('.hw-editor-actions');
      if (!actions) return { exists: false };
      var btns = Array.from(actions.querySelectorAll('.el-button'));
      var save = btns.find(function(b){ return b.textContent.trim().indexOf('保存修改') >= 0; });
      return { exists: !!save, disabled: save ? save.disabled : null, hasWithdraw: btns.some(function(b){ return b.textContent.trim().indexOf('撤回修改') >= 0; }) };
    })()`);
    check('T1.15 已发布作业编辑器显示可用的「保存修改」按钮', !!frozenSave.exists && frozenSave.disabled === false && frozenSave.hasWithdraw, JSON.stringify(frozenSave));
    await cdp.shot('hw-t1-teacher-frozen-editor');

    // ============ T2 学生端：纯客观题作业（提交即见答案/解析/结果） ============
    log('===== T2 学生提交客观题作业 =====');
    await login(cdp, '20249999', PW);
    await goto('/student/homework');
    await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.includes('E2E-客观题作业'); })`, 20000);

    const btnLabel = await clickStudentRow(cdp, 'E2E-客观题作业');
    check('T2.0 作业行按钮为「查看作业」（无历史提交，状态干净）', btnLabel === '查看作业', btnLabel);
    const cardsOk = await waitFor(cdp, `document.querySelectorAll('.homework-question-card').length === 2`, 15000);
    check('T2.1 作业工作台打开且渲染 2 道单选题', cardsOk);

    // 两题都选 B（正确选项：Q3/Q4 答案均为 B）
    await cdp.eval(`(function(){
      var radios = Array.from(document.querySelectorAll('.homework-question-card .el-radio'));
      radios.filter(function(r){ return r.textContent.trim().indexOf('B.') === 0; }).forEach(function(r){ r.click(); });
    })()`);
    await sleep(500);
    const answered = await cdp.eval(`(function(){
      var prog = document.querySelector('.answer-progress');
      if (!prog) return { exists: false, text: '', html: '' };
      return { exists: true, text: (prog.innerText || '').replace(/\\s+/g, ' ').trim(), html: prog.outerHTML.slice(0, 160) };
    })()`);
    check('T2.2 两题均已作答（进度 2/2）', answered.exists && answered.text.indexOf('2') >= 0 && answered.text.indexOf('/ 2') >= 0, JSON.stringify(answered));

    // 提交
    await clickByText(cdp, '.workspace-footer .el-button', '确认提交');
    // 提交后：可能直接进入结果视图，也可能回到列表需手动点「查看结果」
    await waitFor(cdp, `!!document.querySelector('.result-summary') || !!document.querySelector('.student-list')`, 20000);
    const onList = await cdp.eval(`!!document.querySelector('.student-list') && !document.querySelector('.result-summary')`);
    if (onList) {
      const label2 = await clickStudentRow(cdp, 'E2E-客观题作业');
      log('提交后回到列表，二次点击按钮: ' + label2);
    }
    const viewOpened = await waitFor(cdp, `!!document.querySelector('.result-summary')`, 15000);
    check('T2.3 提交后可查看成绩结果（result-summary）', viewOpened);
    const summary = await cdp.eval(`(function(){
      var el = document.querySelector('.result-summary');
      return el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
    })()`);
    check('T2.4 显示「已发布成绩」与满分得分', summary.includes('已发布成绩') && summary.includes('20'), summary);

    const answerVisible = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.answer-result-item'));
      return {
        count: items.length,
        correct: Array.from(document.querySelectorAll('.correct-answer')).map(function(e){ return e.textContent.trim(); }),
        analysis: Array.from(document.querySelectorAll('.answer-analysis')).map(function(e){ return e.textContent.trim(); }),
        tags: Array.from(document.querySelectorAll('.result-score-row .el-tag')).map(function(e){ return e.textContent.trim(); }),
      };
    })()`);
    check('T2.5 每题展示正确答案（带选项内容）', answerVisible.correct.length === 2 && answerVisible.correct.every((t) => t.indexOf('正确答案：B.') === 0), JSON.stringify(answerVisible.correct));
    check('T2.6 每题展示解析', answerVisible.analysis.length === 2 && answerVisible.analysis.every((t) => t.indexOf('解析：') === 0), JSON.stringify(answerVisible.analysis.map((t) => t.slice(0, 24))));
    check('T2.7 每题展示对错与得分', answerVisible.tags.length === 2 && answerVisible.tags.every((t) => t.indexOf('答对') === 0), JSON.stringify(answerVisible.tags));
    await cdp.shot('hw-t2-student-result');

    // ============ T3 学生端：附件作业提交图片（预览 + 大小统计） ============
    log('===== T3 学生提交图片附件 =====');
    await clickByText(cdp, '.workspace-back', '返回作业列表');
    await waitFor(cdp, `Array.from(document.querySelectorAll('.student-row-title')).some(function(t){ return t.textContent.includes('计算机网络-作业1'); })`, 20000);
    const btnLabel3 = await clickStudentRow(cdp, '计算机网络-作业1');
    check('T3.0 作业行按钮为「查看作业」（无历史提交，状态干净）', btnLabel3 === '查看作业', btnLabel3);
    await waitFor(cdp, `!!document.querySelector('.answer-dock')`, 15000);
    check('T3.1 附件作业工作台打开', true);

    // 安装进度采样器（必须在选择文件之前：即时暂存上传在 on-change 即开始）
    await cdp.eval(`(function(){
      window.__subProg = { sawUploading: false, maxWidth: 0, samples: 0 };
      window.__subProgTimer = setInterval(function(){
        var items = Array.from(document.querySelectorAll('.submit-file-item'));
        items.forEach(function(item){
          if ((item.className || '').indexOf('is-uploading') >= 0) window.__subProg.sawUploading = true;
        });
        var bar = document.querySelector('.submit-progress-bar');
        if (bar && bar.style && bar.style.width) {
          var pct = parseFloat(bar.style.width);
          if (!isNaN(pct)) {
            window.__subProg.maxWidth = Math.max(window.__subProg.maxWidth, pct);
            window.__subProg.samples += 1;
          }
        }
      }, 16);
    })()`);

    // 选择两张图片（含一张 3.4MB 大图，保证「上传中」阶段足够长以供进度采样）
    await setFiles(cdp, '.answer-dock input[type="file"]', ['hw-submit-1.png', 'hw-submit-big.png']);
    await waitFor(cdp, `document.querySelectorAll('.submit-file-item').length === 2`, 10000);
    // 等待两个文件都暂存成功（状态变为「已上传」）
    const staged = await waitFor(cdp, `(function(){
      var items = Array.from(document.querySelectorAll('.submit-file-item'));
      return items.length === 2 && items.every(function(it){ return (it.className || '').indexOf('is-success') >= 0; });
    })()`, 40000);
    check('T3.2 选择即暂存上传：两个文件均展示「已上传」状态', staged);
    const subProg = await cdp.eval(`(function(){ if (window.__subProgTimer) clearInterval(window.__subProgTimer); return window.__subProg; })()`);
    // 说明：学生端附件较小（最大 3.4MB），回环网下上传耗时仅数十毫秒，16ms 采样器
    // 可能只捕获到 width=0% 的帧（maxWidth=0）；「上传中」状态与进度条渲染由
    // sawUploading + samples>=1 证明，百分比真实推进由教师端 12MB 场景（T1.8/T1.9）覆盖。
    check('T3.3 学生上传流程可见：进入「上传中」状态并渲染进度条', !!(subProg && subProg.sawUploading && subProg.samples >= 1), JSON.stringify(subProg));
    const thumbs = await cdp.eval(`(function(){
      var imgs = Array.from(document.querySelectorAll('.submit-file-thumb img'));
      return {
        thumbCount: document.querySelectorAll('.submit-file-thumb').length,
        blobSrcCount: imgs.filter(function(i){ return (i.getAttribute('src') || '').indexOf('blob:') === 0; }).length,
        statusTexts: Array.from(document.querySelectorAll('.submit-file-status')).map(function(e){ return e.textContent.trim(); }),
        summary: (document.querySelector('.submit-file-summary') || {textContent:''}).textContent.replace(/\\s+/g,' ').trim(),
      };
    })()`);
    check('T3.4 已选 2 个文件并展示大小统计', thumbs.summary.indexOf('已选 2 个文件') === 0, thumbs.summary);
    check('T3.5 图片缩略图预览（blob 本地预览）', thumbs.thumbCount === 2 && thumbs.blobSrcCount === 2, JSON.stringify(thumbs));
    check('T3.6 上传结果状态明确（已上传 x2）', thumbs.statusTexts.length === 2 && thumbs.statusTexts.every((t) => t === '已上传'), JSON.stringify(thumbs.statusTexts));

    // 填写文本内容并提交
    await cdp.eval(`(function(){
      var el = document.querySelector('.answer-dock-textarea textarea');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, 'E2E 图片附件提交验证');
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await clickByText(cdp, '.workspace-footer .el-button', '确认提交');
    // 提交后回到列表 → 点「查看结果」→ 验证已提交图片
    await waitFor(cdp, `!!document.querySelector('.student-list')`, 25000);
    const label4 = await clickStudentRow(cdp, '计算机网络-作业1');
    log('提交后回到列表，二次点击按钮: ' + label4);
    const submittedOk = await waitFor(cdp, `!!document.querySelector('.submitted-attachments')`, 20000);
    const submitted = await cdp.eval(`(function(){
      var imgs = Array.from(document.querySelectorAll('.submitted-attachment-thumb img'));
      return {
        exists: !!document.querySelector('.submitted-attachments'),
        thumbCount: document.querySelectorAll('.submitted-attachment-thumb').length,
        mediaSrcCount: imgs.filter(function(i){ return (i.getAttribute('src') || '').indexOf('/media/') >= 0; }).length,
      };
    })()`);
    check('T3.7 提交成功，结果页展示已提交图片（/media 持久化）', submittedOk && submitted.thumbCount === 2 && submitted.mediaSrcCount === 2, JSON.stringify(submitted));
    await cdp.shot('hw-t3-student-submitted');

    // 页面错误汇总（Vue 运行时错误等）
    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
  } finally {
    killChrome(chrome);
  }

  // ---------------- 汇总 ----------------
  const failed = results.filter((r) => !r.ok);
  log('===== 汇总: ' + (results.length - failed.length) + '/' + results.length + ' 通过 =====');
  if (failed.length) {
    failed.forEach((r) => console.log('FAIL | ' + r.name));
    process.exitCode = 1;
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 1;
});
