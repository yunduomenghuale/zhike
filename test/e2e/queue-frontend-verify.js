#!/usr/bin/env node
/**
 * 队列化前端 E2E（阶段 5）—— CDP 真实浏览器验证
 *
 * 覆盖测试方案 L4 的 T1/T2/T3/T4/T5/T9 与交互场景：
 *   T9  旧客户端：无 X-AI-Task-Mode 头的裸 fetch → 410（不出现假成功/死循环）
 *   T1  点「生成讲稿」→ 按钮进「排队中（第 N 位）」或「讲稿 x/y」，console.error 为 0
 *   T4  连点 5 次 → 服务端只有 1 条讲稿任务
 *   T5  生成中手改第 5 页（API 模拟教师编辑）→ 完成后第 5 页仍是手改版
 *   T2  生成中刷新页面 → 任务态恢复，进度不倒退
 *   T3  关闭浏览器再开 → 任务已完成、内容可见、按钮无残留任务态
 *   场景 启动清 zhike:generation-tasks（旧续跑记录不残留）
 *
 * 前置：backend 8005 + serve-local 5273 + ai_worker 均已启动；
 *      夹具「P5E2E课 / P5E2E章节（10 页已解析课件）」由 run 前 Django shell 自建自清。
 *
 * 运行：node test/e2e/queue-frontend-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9223; // 与 cdp-drive.js 的 9222 错开
const BASE = 'http://localhost:5273';
const API = 'http://localhost:8005/api';
const PROFILE = 'D:/tmp/zhike-e2e/queue-p5-profile';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let PASS = 0, FAIL = 0;
function check(label, ok, detail = '') {
  if (ok) { PASS += 1; console.log(`PASS  ${label}${detail ? '  | ' + detail : ''}`); }
  else { FAIL += 1; console.log(`FAIL  ${label}${detail ? '  | ' + detail : ''}`); }
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      } else if (msg.method === 'Runtime.exceptionThrown') {
        this.consoleErrors.push(msg.params.exceptionDetails?.exception?.description || 'exception');
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push(msg.params.args?.map((a) => a.value || a.description || '').join(' '));
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
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
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

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用旧目录 */ }
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
      const page = (await res.json()).find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
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
  await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`, 30000);
}

// 页面上下文 API 请求（带 token；headers 可覆盖——传 null 值模拟旧客户端不带头）
async function apiCall(cdp, method, path, body, headers = undefined) {
  return cdp.eval(`(async function(){
    const token = localStorage.getItem('access_token');
    const hdrs = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token };
    const extra = ${JSON.stringify(headers || {})};
    for (const [k, v] of Object.entries(extra)) {
      if (v === null) delete hdrs[k]; else hdrs[k] = v;
    }
    const resp = await fetch(${JSON.stringify(API + path)}, {
      method: ${JSON.stringify(method)},
      headers: hdrs,
      body: ${JSON.stringify(body)} ? JSON.stringify(${JSON.stringify(body)}) : undefined,
    });
    const text = await resp.text();
    let json = null; try { json = JSON.parse(text); } catch {}
    return { status: resp.status, json };
  })()`);
}

// 在章节树里定位目标章节的讲稿按钮（el-tree 节点行）
function rowExpr(catalogTitle) {
  return `[...document.querySelectorAll('.el-tree-node__content')].find((r) => r.textContent.includes(${JSON.stringify(catalogTitle)}))`;
}
async function scriptButtonText(cdp, catalogTitle) {
  return cdp.eval(`(function(){
    const row = ${rowExpr(catalogTitle)};
    if (!row) return '';
    const btn = [...row.querySelectorAll('button')].find((b) => /讲稿|排队/.test(b.textContent));
    return btn ? btn.textContent.trim() : '';
  })()`);
}
async function clickScriptButton(cdp, catalogTitle) {
  return cdp.eval(`(function(){
    const row = ${rowExpr(catalogTitle)};
    if (!row) return false;
    const btn = [...row.querySelectorAll('button')].find((b) => /讲稿|排队|生成/.test(b.textContent));
    if (!btn) return false;
    btn.click(); return true;
  })()`);
}
async function activeTasks(cdp) {
  const r = await apiCall(cdp, 'GET', '/ai-tasks/active/?task_type=all');
  return (r.json && r.json.data) || [];
}

async function run() {
  const COURSE = 'P5E2E课';
  const CATALOG = 'P5E2E章节';

  const { cdp, chrome } = await launchChrome();
  let session2 = null;
  try {
    await login(cdp, 't101', 'A0987654');

    // 夹具定位（由外部 shell 预建，这里按标题查 id）
    const courseResp = await apiCall(cdp, 'GET', '/courses/?page_size=50');
    const course = ((courseResp.json?.data?.results) || []).find((c) => c.name === COURSE);
    const catResp = await apiCall(cdp, 'GET', `/catalogs/?course=${course.id}`);
    const catalog = ((catResp.json?.data?.results) || []).find((c) => c.title === CATALOG);
    const CATALOG_ID = catalog.id;
    check('夹具就位（课程/章节/课件）', !!course && !!catalog, `course=${course && course.id} catalog=${CATALOG_ID}`);

    // ---- 场景：启动清旧续跑记录（坑 22）----
    const legacy = await cdp.eval(`localStorage.getItem('zhike:generation-tasks')`);
    check('启动清 zhike:generation-tasks', legacy === null, `value=${legacy}`);

    // ---- T9：旧客户端（不带头）→ 410；新前端全局带 queue 头 ----
    const r410 = await apiCall(cdp, 'POST', `/catalogs/${CATALOG_ID}/generate-script/`, {}, { 'X-AI-Task-Mode': null });
    check('T9 旧客户端 410', r410.status === 410, `status=${r410.status} msg=${(r410.json && r410.json.message) || ''}`);

    // ---- 进入章节与课件页 ----
    await cdp.navigate(`${BASE}/teacher/courses/${course.id}/chapters`);
    const navOk = await waitFor(cdp, `[...document.querySelectorAll('.el-tree-node__content')].some((r) => r.textContent.includes(${JSON.stringify(CATALOG)}))`, 20000);
    check('进入章节与课件页', navOk);

    // ---- T1：点生成讲稿 → 排队/生成中 ----
    await clickScriptButton(cdp, CATALOG);
    await sleep(2000);
    const btn1 = await scriptButtonText(cdp, CATALOG);
    const t1ok = btn1.includes('排队') || /讲稿 \d+\/\d+/.test(btn1) || btn1.includes('生成中');
    check('T1 按钮进排队/生成态', t1ok, `text=${btn1}`);
    await cdp.shot('p5-t1-queued-or-running');

    // ---- T4：连点 5 次只有 1 条任务 ----
    for (let i = 0; i < 5; i++) { await clickScriptButton(cdp, CATALOG); await sleep(300); }
    await sleep(800);
    let tasks = await activeTasks(cdp);
    let scriptTasks = tasks.filter((t) => t.task_type === 'script_gen');
    check('T4 连点 5 次仅 1 条讲稿任务', scriptTasks.length === 1, `count=${scriptTasks.length}`);
    const taskId = scriptTasks[0] && scriptTasks[0].id;

    // ---- T5：生成中手改第 5 页（API 模拟教师编辑，走完整权限链）----
    await sleep(8000); // 等 worker 跑过第一批（真实 provider 每块约 12s）
    const videoResp = await apiCall(cdp, 'GET', `/videos/?catalog=${CATALOG_ID}`);
    const video = ((videoResp.json?.data?.results) || [])[0];
    const editResp = await apiCall(cdp, 'POST', `/videos/${video.id}/update-script/`, { page: 5, script: '【E2E手改】第五页由教师在生成期间改写。' });
    check('T5 生成中手改第5页 200', editResp.status === 200, `status=${editResp.status}`);

    // ---- T2：生成中刷新 → 任务态恢复、进度不倒退 ----
    const before = await apiCall(cdp, 'GET', `/ai-tasks/${taskId}/`);
    const progressBefore = (before.json?.data?.progress || {}).done || 0;
    const currentUrl = await cdp.eval('location.href');
    await cdp.navigate(currentUrl);
    await sleep(2000);
    const btn2 = await scriptButtonText(cdp, CATALOG);
    const restored = btn2.includes('排队') || /讲稿 \d+\/\d+/.test(btn2);
    check('T2 刷新后按钮恢复任务态', restored, `text=${btn2}`);
    const after = await apiCall(cdp, 'GET', `/ai-tasks/${taskId}/`);
    const progressAfter = (after.json?.data?.progress || {}).done || 0;
    check('T2 进度不倒退', progressAfter >= progressBefore, `${progressBefore} → ${progressAfter}`);
    await cdp.shot('p5-t2-restored');

    // ---- 等完成，验证第 5 页未被覆盖 ----
    let doneStatus = null;
    for (let i = 0; i < 60; i++) {
      const d = await apiCall(cdp, 'GET', `/ai-tasks/${taskId}/`);
      doneStatus = d.json?.data?.status;
      if (doneStatus === 'success' || doneStatus === 'failed') break;
      await sleep(3000);
    }
    check('讲稿任务最终 success', doneStatus === 'success', `status=${doneStatus}`);
    const v2 = await apiCall(cdp, 'GET', `/videos/?catalog=${CATALOG_ID}`);
    const video2 = ((v2.json?.data?.results) || [])[0];
    const p5 = (video2.scripts || []).find((s) => s.page === 5);
    check('T5 完成后第5页仍是手改版', !!p5 && String(p5.script).includes('【E2E手改】'), p5 ? String(p5.script).slice(0, 30) : 'missing');
    const filled = (video2.scripts || []).filter((s) => String(s.script || '').trim()).length;
    check('其余页全部生成', filled === 10, `filled=${filled}/10`);

    // ---- T3：关浏览器再开 → 无残留任务态、内容可见 ----
    chrome.kill();
    await sleep(1500);
    session2 = await launchChrome();
    const cdp2 = session2.cdp;
    await login(cdp2, 't101', 'A0987654');
    await cdp2.navigate(`${BASE}/teacher/courses/${course.id}/chapters`);
    await waitFor(cdp2, `[...document.querySelectorAll('.el-tree-node__content')].some((r) => r.textContent.includes(${JSON.stringify(CATALOG)}))`, 20000);
    const btn3 = await scriptButtonText(cdp2, CATALOG);
    check('T3 重开后无残留任务态', !btn3.includes('排队') && !/讲稿 \d+\/\d+/.test(btn3), `text=${btn3}`);
    const v3 = await apiCall(cdp2, 'GET', `/videos/?catalog=${CATALOG_ID}`);
    const video3 = ((v3.json?.data?.results) || [])[0];
    check('T3 内容持久可见', (video3.scripts || []).length === 10 && video3.is_published === true, `scripts=${(video3.scripts || []).length} published=${video3.is_published}`);
    await cdp2.shot('p5-t3-after-reopen');
    session2.chrome.kill(); session2 = null;

    check('console.error 为 0（T1 会话）', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' | '));
  } finally {
    try { chrome.kill(); } catch { /* 已退出 */ }
    if (session2) { try { session2.chrome.kill(); } catch { /* */ } }
  }

  console.log(`\n===== 结果：PASS ${PASS} / FAIL ${FAIL} =====`);
  process.exit(FAIL ? 1 : 0);
}

run().catch((e) => { console.error('E2E 异常:', e); process.exit(1); });
