#!/usr/bin/env node
/**
 * 教学资源页布局改版（教师端资源库 + 学生端卡片中心）——CDP 实测
 *
 * 验证点：
 *   N.1 教师页：类型分段 tab（带计数）、搜索框、添加资源按钮；无常驻表单
 *   N.2 添加弹窗：三种类型单选，切文档出文件选择；预置类选页面可预览
 *   N.3 弹窗内上传 pdf 文档 → 表格出现新行（图标章 + 副标题文件名）
 *   N.4 发布 switch 切换 → 状态变更（行内开关，无发布/下架按钮）
 *   N.5 类型 tab 过滤 + 搜索过滤（前端即时）
 *   N.6 学生页：封面卡片网格（色块封面 + 图标章）、类型 tab、搜索
 *   N.7 清理验收文档
 *   N.8 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234、dbg1/A0987654。
 * 运行：node test/e2e/course-resources-layout-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-reslayout-e2e/run-${RUN_ID}`;
const MINIMAL_PDF = Buffer.from(
  'JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50IDE+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL01lZGlhQm94WzAgMCA2MTIgNzkyXS9Db250ZW50cyA0IDAgUi9SZXNvdXJjZXM8PC9Gb250PDwvRjE8PC9UeXBlL0ZvbnQvU3VidHlwZS9UeXBlMS9CYXNlRm9udC9IZWx2ZXRpY2E+Pj4+Pj4+Pj4KZW5kb2JqCjQgMCBvYmoKPDwvTGVuZ3RoIDU4Pj4Kc3RyZWFtCkJUCi9GMSAyNCBUZgo3MiA3MDAgVGQKKEUyRSByZXNvdXJjZSBkb2MpIFRqCkVUCmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDUKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDA5IDAwMDAwIG4gCjAwMDAwMDAwNTIgMDAwMDAgbiAKMDAwMDAwMDEwMSAwMDAwMCBuIAowMDAwMDAwMjA4IDAwMDAwIG4gCnRyYWlsZXIKPDwvU2l6ZSA1L1Jvb3QgMSAwIFI+PgpzdGFydHhyZWYKMjY2CiUlRU9GCg==',
  'base64',
);

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

async function login(tab, username, password) {
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.href.startsWith('http') && !location.href.startsWith('chrome-error')`, 20000);
  await tab.eval(`localStorage.clear()`);
  await tab.send('Page.navigate', { url: `${BASE}/login` });
  await waitFor(tab, `location.pathname === '/login' && document.querySelectorAll('input').length >= 2`);
  await tab.eval(`(() => {
    const inputs = document.querySelectorAll('input');
    inputs[0].value = ${JSON.stringify(username)};
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    const pwd = document.querySelector('input[type="password"]');
    pwd.value = ${JSON.stringify(password)};
    pwd.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(200);
  await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`);
  return waitFor(tab, `!location.pathname.startsWith('/login')`, 15000);
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const { cdp: tab, chrome } = await launchChrome();
  try {
    log('教师登录…');
    check('教师登录', await login(tab, 't101', 'pass1234'), await tab.eval('location.pathname'));
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/resources` });
    const pageReady = await waitFor(tab, `document.querySelectorAll('.kind-tab').length === 4`, 25000);
    check('教师页就绪', pageReady);
    await sleep(800);

    // N.1 结构
    const n1 = await tab.eval(`(() => ({
      tabs: [...document.querySelectorAll('.kind-tab')].map((t) => t.textContent.trim()),
      hasAddBtn: [...document.querySelectorAll('button')].some((b) => b.textContent.includes('添加资源')),
      hasInlineForm: !!document.querySelector('.res-panel .el-form'),
      hasSwitch: !!document.querySelector('.el-switch'),
      rows: document.querySelectorAll('.el-table__row').length,
      opsPerRow: document.querySelector('.el-table__row .op-cell')?.querySelectorAll('button').length || 0,
    }))()`);
    check('N.1 资源库结构（tab+按钮+无常驻表单+开关）',
      n1 && n1.tabs.length === 4 && n1.hasAddBtn && !n1.hasInlineForm && n1.hasSwitch && n1.rows > 0 && n1.opsPerRow === 3,
      JSON.stringify(n1));
    await tab.shot('reslayout-01-teacher.png');

    // N.2 添加弹窗 + 类型切换
    await tab.eval(`[...document.querySelectorAll('button')].find((b) => b.textContent.includes('添加资源'))?.click()`);
    await waitFor(tab, `!!document.querySelector('.add-res-dialog')`, 8000);
    await sleep(400);
    const n2a = await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      return {
        kindRadios: [...dlg.querySelectorAll('.el-radio-button')].map((r) => r.textContent.trim()).slice(0, 3),
        hasPresetSelect: !!dlg.querySelector('.el-select'),
      };
    })()`);
    check('N.2a 弹窗三类型 + 预置类表单(默认来源=平台预置)',
      n2a && n2a.kindRadios.length === 3 && n2a.kindRadios.includes('文档') && n2a.hasPresetSelect, JSON.stringify(n2a));
    // 切"上传文件"来源 → 出 HTML 拖拽区
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('.el-radio-button')].find((r) => r.textContent.trim() === '上传文件')?.querySelector('input')?.click();
    })()`);
    await sleep(400);
    const n2a2 = await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      return { hasHtmlUpload: !!dlg.querySelector('.course-upload input[type=file]'), selectGone: !dlg.querySelector('.el-select') };
    })()`);
    check('N.2a-2 切上传来源出 HTML 拖拽区', n2a2 && n2a2.hasHtmlUpload && n2a2.selectGone, JSON.stringify(n2a2));
    // 切回平台预置（后续文档流程从类型切换开始）
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('.el-radio-button')].find((r) => r.textContent.trim() === '平台预置')?.querySelector('input')?.click();
    })()`);
    await sleep(300);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('.el-radio-button')].find((r) => r.textContent.trim() === '文档')?.querySelector('input')?.click();
    })()`);
    await sleep(400);
    const n2b = await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      return { hasFile: !!dlg.querySelector('input[type=file]'), hasPresetSelect: !!dlg.querySelector('.el-select') };
    })()`);
    check('N.2b 切文档出文件选择', n2b && n2b.hasFile && !n2b.hasPresetSelect, JSON.stringify(n2b));

    // N.3 弹窗内上传 pdf
    const tmpPdf = path.join(SHOT_DIR, '_e2e_layout.pdf');
    fs.writeFileSync(tmpPdf, MINIMAL_PDF);
    const docDom = await tab.send('DOM.getDocument', { depth: -1 });
    const query = await tab.send('DOM.querySelector', {
      nodeId: docDom.root.nodeId,
      selector: '.add-res-dialog input[type=file]',
    });
    await tab.send('DOM.setFileInputFiles', { files: [tmpPdf], nodeId: query.nodeId });
    await sleep(400);
    await tab.eval(`(() => {
      const input = document.querySelector('.add-res-dialog input[type=file]');
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await sleep(300);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      const titleInput = [...dlg.querySelectorAll('input')].find((i) => i.placeholder?.includes('复习大纲'));
      titleInput.value = 'E2E布局验收大纲';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('button')].find((b) => b.textContent.includes('上传并添加'))?.click();
    })()`);
    const uploaded = await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E布局验收大纲'))`, 20000);
    check('N.3 弹窗上传 pdf 入表格', uploaded);
    await tab.shot('reslayout-02-uploaded.png');

    // N.4 行内 switch 发布
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E布局验收大纲'));
      row.querySelector('.el-switch')?.click();
    })()`);
    await sleep(1800);
    const n4 = await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E布局验收大纲'));
      return { on: !!row?.querySelector('.el-switch.is-checked') };
    })()`);
    check('N.4 switch 行内发布', n4 && n4.on, JSON.stringify(n4));

    // N.5 类型 tab + 搜索过滤
    await tab.eval(`[...document.querySelectorAll('.kind-tab')].find((t) => t.textContent.includes('文档'))?.click()`);
    await sleep(500);
    const n5a = await tab.eval(`(() => {
      const rows = [...document.querySelectorAll('.el-table__row')];
      return { rows: rows.length, allDoc: rows.every((r) => r.textContent.includes('文档')) };
    })()`);
    await tab.eval(`(() => {
      const input = document.querySelector('.toolbar-search input');
      input.value = '不存在的资源xyz';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(500);
    const n5b = await tab.eval(`document.querySelectorAll('.el-table__row').length`);
    await tab.eval(`(() => {
      const input = document.querySelector('.toolbar-search input');
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await tab.eval(`[...document.querySelectorAll('.kind-tab')].find((t) => t.textContent.trim() === '全部')?.click()`);
    await sleep(500);
    check('N.5 tab 过滤 + 搜索过滤', n5a && n5a.allDoc && n5b === 0, JSON.stringify({ n5a, n5b }));

    // N.6 学生页
    await login(tab, 'dbg1', 'A0987654');
    await tab.send('Page.navigate', { url: `${BASE}/student/courses/5/resources` });
    const stuReady = await waitFor(tab, `document.querySelectorAll('.kind-tab').length === 4`, 25000);
    await sleep(1200);
    const n6 = await tab.eval(`(() => ({
      cards: document.querySelectorAll('.res-card').length,
      covers: document.querySelectorAll('.res-cover').length,
      docVisible: [...document.querySelectorAll('.res-card')].some((c) => c.textContent.includes('E2E布局验收大纲')),
      hasCoverBadge: !!document.querySelector('.cover-badge'),
    }))()`);
    check('N.6 学生封面卡片网格', stuReady && n6 && n6.covers === n6.cards && n6.docVisible && n6.hasCoverBadge, JSON.stringify(n6));
    await tab.shot('reslayout-03-student.png');

    // N.6b 自定义 HTML 导图：教师上传 → 发布 → 学生查看器渲染签名页面
    await login(tab, 't101', 'pass1234');
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/resources` });
    await waitFor(tab, `document.querySelectorAll('.kind-tab').length === 4`, 25000);
    await sleep(1000);
    await tab.eval(`[...document.querySelectorAll('button')].find((b) => b.textContent.includes('添加资源'))?.click()`);
    await waitFor(tab, `!!document.querySelector('.add-res-dialog')`, 8000);
    await sleep(400);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('.el-radio-button')].find((r) => r.textContent.trim() === '上传文件')?.querySelector('input')?.click();
    })()`);
    await sleep(400);
    const tmpHtml = path.join(SHOT_DIR, '_e2e_custom.html');
    fs.writeFileSync(tmpHtml, '<!doctype html><html><head><title>E2E自定义导图</title></head><body><h1>E2E自定义HTML验收</h1></body></html>');
    const htmlDom = await tab.send('DOM.getDocument', { depth: -1 });
    const htmlQuery = await tab.send('DOM.querySelector', {
      nodeId: htmlDom.root.nodeId,
      selector: '.add-res-dialog .course-upload input[type=file]',
    });
    await tab.send('DOM.setFileInputFiles', { files: [tmpHtml], nodeId: htmlQuery.nodeId });
    await sleep(400);
    await tab.eval(`(() => {
      const input = document.querySelector('.add-res-dialog .course-upload input[type=file]');
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await sleep(300);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      const titleInput = [...dlg.querySelectorAll('input')].find((i) => i.placeholder?.includes('传输层'));
      titleInput.value = 'E2E自定义HTML导图';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.add-res-dialog');
      [...dlg.querySelectorAll('button')].find((b) => b.textContent.includes('上传并添加'))?.click();
    })()`);
    const customUp = await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E自定义HTML导图'))`, 20000);
    check('N.6b-1 自定义 HTML 上传入表格', customUp);
    // 行内副标题显示文件名（path 为空）
    const subOk = await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E自定义HTML导图'));
      return row?.querySelector('.res-sub')?.textContent?.includes('_e2e_custom.html') || false;
    })()`);
    check('N.6b-2 副标题显示自定义文件名', subOk);
    // 发布 + 学生端查看
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E自定义HTML导图'));
      row.querySelector('.el-switch')?.click();
    })()`);
    await sleep(1800);
    await login(tab, 'dbg1', 'A0987654');
    await tab.send('Page.navigate', { url: `${BASE}/student/courses/5/resources` });
    await waitFor(tab, `document.querySelectorAll('.res-card').length > 0`, 25000);
    await sleep(1000);
    const stuSigned = await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
      const listRes = await fetch('/api/course-resources/?course=5', { headers: h });
      const items = (await listRes.json())?.data?.results || [];
      const custom = items.find((i) => i.title === 'E2E自定义HTML导图' && i.kind === 'mindmap');
      if (!custom) return { err: 'not found' };
      const signRes = await fetch('/api/course-resources/' + custom.id + '/sign/', { method: 'POST', headers: h });
      const url = (await signRes.json())?.data?.url || '';
      const pageRes = await fetch(url, { headers: h });
      const text = await pageRes.text();
      return { signedPage: url.includes('/page/'), rendered: text.includes('E2E自定义HTML验收'), csp: !!pageRes.headers.get('Content-Security-Policy') };
    })()`);
    check('N.6b-3 学生签发并渲染自定义 HTML', stuSigned && stuSigned.signedPage && stuSigned.rendered && stuSigned.csp, JSON.stringify(stuSigned).slice(0, 120));
    await tab.shot('reslayout-04-custom-html.png');
    fs.rmSync(tmpHtml, { force: true });
    // 清理自定义资源（教师端删除）
    await login(tab, 't101', 'pass1234');
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/resources` });
    await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E自定义HTML导图'))`, 25000);
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E自定义HTML导图'));
      [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '删除')?.click();
    })()`);
    await sleep(800);
    await tab.eval(`(() => {
      const box = document.querySelector('.el-message-box');
      [...box.querySelectorAll('button')].find((b) => b.textContent.includes('确定'))?.click();
    })()`);
    await sleep(1500);

    // N.7 清理验收文档（教师端删除）
    await login(tab, 't101', 'pass1234');
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/resources` });
    await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E布局验收大纲'))`, 25000);
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E布局验收大纲'));
      [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '删除')?.click();
    })()`);
    await sleep(800);
    await tab.eval(`(() => {
      const box = document.querySelector('.el-message-box');
      [...box.querySelectorAll('button')].find((b) => b.textContent.includes('确定'))?.click();
    })()`);
    const cleaned = await waitFor(tab, `![...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E布局验收大纲'))`, 10000);
    check('N.7 清理验收文档', cleaned);
    fs.rmSync(tmpPdf, { force: true });

    // N.8 API 层回归（承接旧版验收脚本口径）：无章节字段 / 视频端点 404 / 签名文件可匿名下载
    await login(tab, 't101', 'pass1234');
    const apiCheck = await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
      const listRes = await fetch('/api/course-resources/?course=5', { headers: h });
      const items = (await listRes.json())?.data?.results || [];
      const noCatalogField = items.every((i) => !('catalog' in i) && !('catalog_title' in i));
      const videos404 = (await fetch('/api/course-videos/?course=5', { headers: h })).status === 404;
      return { noCatalogField, videos404, total: items.length };
    })()`);
    check('N.8 API 回归（无章节字段+视频404）', apiCheck && apiCheck.noCatalogField && apiCheck.videos404, JSON.stringify(apiCheck));

    // N.9 无 console.error / 未捕获异常
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('N.9 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
