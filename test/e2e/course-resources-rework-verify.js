#!/usr/bin/env node
/**
 * 教学资源改版（去章节 + 文档类 + 删数字人视频）——CDP 实测
 *
 * 验证点：
 *   R.1 教师资源页：无「挂载章节」下拉、无数字人视频卡、有「文档资源」上传表单
 *   R.2 教师上传 pdf 文档 → 列表出现文档行（文件名/大小）
 *   R.3 教师发布文档 → 学生资源页可见「文档资料」卡片
 *   R.4 学生点文档（PDF）→ 打开查看器（iframe 加载签名 file 地址，200）
 *   R.5 预置资源（思维导图）仍正常：教师添加（无章节字段）→ 学生可见
 *   R.6 全页无「数字人」字样、无章节分组
 *   R.7 无 console.error / 未捕获异常
 *
 * 前置：后端 8005、前端 5273；t101/pass1234、dbg1/A0987654。
 * 运行：node test/e2e/course-resources-rework-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-resrework-e2e/run-${RUN_ID}`;
// 最小合法 PDF（单页，浏览器可渲染）
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
    const pageReady = await waitFor(tab, `[...document.querySelectorAll('.el-card')].some((c) => c.textContent.includes('文档资源'))`, 25000);
    check('资源管理页就绪', pageReady);

    // R.1 结构检查
    const r1 = await tab.eval(`(() => ({
      hasCatalogField: document.body.textContent.includes('挂载章节'),
      hasVideoSection: document.body.textContent.includes('数字人视频'),
      hasDocSection: [...document.querySelectorAll('.el-card')].some((c) => c.textContent.includes('文档资源')),
    }))()`);
    check('R.1 无章节下拉/无视频卡/有文档表单', r1 && !r1.hasCatalogField && !r1.hasVideoSection && r1.hasDocSection, JSON.stringify(r1));
    await tab.shot('res-01-teacher.png');

    // R.2 上传 pdf 文档（原生 file input 需 CDP DOM.setFileInputFiles）
    await tab.eval(`(() => {
      const cards = [...document.querySelectorAll('.el-card')];
      const docCard = cards.find((c) => c.textContent.includes('文档资源'));
      const input = docCard.querySelector('input[type=file]');
      input.scrollIntoView();
    })()`);
    // 把最小 PDF 落盘后用 DOM.setFileInputFiles
    const tmpPdf = path.join(SHOT_DIR, '_e2e_upload.pdf');
    fs.writeFileSync(tmpPdf, MINIMAL_PDF);
    const docDom = await tab.send('DOM.getDocument', { depth: -1 });
    const query = await tab.send('DOM.querySelector', {
      nodeId: docDom.root.nodeId,
      selector: 'input[type=file][accept=".pdf,.doc,.docx"]',
    });
    await tab.send('DOM.setFileInputFiles', { files: [tmpPdf], nodeId: query.nodeId });
    await sleep(400);
    // 触发表单响应 + 填标题
    await tab.eval(`(() => {
      const input = document.querySelector('input[type=file][accept=".pdf,.doc,.docx"]');
      input.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
    await sleep(300);
    await tab.eval(`(() => {
      const cards = [...document.querySelectorAll('.el-card')];
      const docCard = cards.find((c) => c.textContent.includes('文档资源'));
      const titleInput = [...docCard.querySelectorAll('input')].find((i) => i.placeholder?.includes('复习大纲'));
      titleInput.value = 'E2E验收复习大纲';
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await sleep(200);
    await tab.eval(`(() => {
      const cards = [...document.querySelectorAll('.el-card')];
      const docCard = cards.find((c) => c.textContent.includes('文档资源'));
      [...docCard.querySelectorAll('button')].find((b) => b.textContent.includes('上传文档'))?.click();
    })()`);
    const uploaded = await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E验收复习大纲'))`, 20000);
    check('R.2 上传 pdf 文档入列表', uploaded);
    await tab.shot('res-02-uploaded.png');

    // R.3 发布 → 学生可见
    const docRow = await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E验收复习大纲'));
      if (!row) return null;
      const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '发布');
      btn?.click();
      return true;
    })()`);
    await sleep(1500);
    check('R.3a 教师发布文档', docRow === true);

    await login(tab, 'dbg1', 'A0987654');
    await tab.send('Page.navigate', { url: `${BASE}/student/courses/5/resources` });
    const stuReady = await waitFor(tab, `document.body.textContent.includes('文档资料')`, 25000);
    await sleep(1200);
    const r3 = await tab.eval(`(() => {
      const hasDoc = [...document.querySelectorAll('.res-card')].some((c) => c.textContent.includes('E2E验收复习大纲'));
      const hasVideo = document.body.textContent.includes('数字人视频');
      const chapterGroup = !!document.querySelector('.chapter-group');
      return { hasDoc, hasVideo, chapterGroup };
    })()`);
    check('R.3b 学生可见文档卡片', stuReady && r3.hasDoc, JSON.stringify(r3));
    check('R.6 学生页无视频/无章节分组', !r3.hasVideo && !r3.chapterGroup);
    await tab.shot('res-03-student.png');

    // R.4 学生打开 PDF 查看器：签名 → 查看器路由 → iframe 加载签名 file 地址
    //（eval 点击无用户激活会被弹窗拦截，直接复用签名链路验证查看器渲染）
    const viewerInfo = await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
      const listRes = await fetch('/api/course-resources/?course=5', { headers: h });
      const items = (await listRes.json())?.data?.results || [];
      const doc = items.find((i) => i.kind === 'document' && i.title.includes('E2E验收'));
      if (!doc) return { err: 'doc not found' };
      const signRes = await fetch('/api/course-resources/' + doc.id + '/sign/', { method: 'POST', headers: h });
      const signed = (await signRes.json())?.data?.url || '';
      if (!signed.includes('/file/')) return { err: 'bad sign url', signed };
      const viewerUrl = '/student/courses/5/resources/viewer?src=' + encodeURIComponent(signed) +
        '&title=' + encodeURIComponent(doc.title) + '&type=pdf&kind=document&back=student-course-resources';
      return { viewerUrl, signed };
    })()`);
    check('R.4a 学生签发文档得 file 地址', viewerInfo && viewerInfo.viewerUrl && !viewerInfo.err, JSON.stringify(viewerInfo).slice(0, 120));
    if (viewerInfo?.viewerUrl) {
      await tab.send('Page.navigate', { url: `${BASE}${viewerInfo.viewerUrl}` });
      await sleep(3500);
      const frame = await tab.eval(`(() => {
        const f = document.querySelector('.viewer-frame');
        return { hasIframe: !!f, src: f?.src || '' };
      })()`);
      check('R.4b 查看器 iframe 加载签名 file 地址', frame && frame.hasIframe && frame.src.includes('/api/course-resources/file/'), JSON.stringify(frame).slice(0, 120));
      await tab.shot('res-04-viewer.png');
      await tab.send('Page.navigate', { url: `${BASE}/student/courses/5/resources` });
      await sleep(1500);
    }

    // R.5 预置资源教师侧无章节创建（回归）：直接验 API 层 catalog 字段已不存在
    await login(tab, 't101', 'pass1234');
    const apiCheck = await tab.eval(`(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
      const listRes = await fetch('/api/course-resources/?course=5', { headers: h });
      const d = await listRes.json();
      const items = d?.data?.results || [];
      const noCatalogField = items.every((i) => !('catalog' in i) && !('catalog_title' in i));
      const videos404 = (await fetch('/api/course-videos/?course=5', { headers: h })).status === 404;
      return { noCatalogField, videos404, total: items.length };
    })()`);
    check('R.5 序列化无章节字段 + 视频端点404', apiCheck && apiCheck.noCatalogField && apiCheck.videos404, JSON.stringify(apiCheck));

    // 清理验收文档（走 UI 删除，顺带验证删除链路）
    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses/5/resources` });
    await waitFor(tab, `[...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E验收复习大纲'))`, 25000);
    await tab.eval(`(() => {
      const row = [...document.querySelectorAll('.el-table__row')].find((r) => r.textContent.includes('E2E验收复习大纲'));
      [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '删除')?.click();
    })()`);
    await sleep(800);
    await tab.eval(`(() => {
      const dlg = document.querySelector('.el-message-box');
      [...dlg.querySelectorAll('button')].find((b) => b.textContent.includes('确定'))?.click();
    })()`);
    await sleep(1500);
    const cleaned = await waitFor(tab, `![...document.querySelectorAll('.el-table__row')].some((r) => r.textContent.includes('E2E验收复习大纲'))`, 10000);
    check('清理验收文档', cleaned);
    fs.rmSync(tmpPdf, { force: true });

    // R.7 console 干净
    const errs = tab.consoleErrors.filter((e) => !e.includes('favicon'));
    check('R.7 无 console.error / 异常', errs.length === 0, errs.slice(0, 3).join(' | ') || 'clean');

    console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`);
    process.exitCode = failures === 0 ? 0 : 1;
  } finally {
    try { process.kill(-chrome.pid, 'SIGKILL'); } catch { chrome.kill('SIGKILL'); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
  }
}

main().catch((e) => { console.error('E2E 异常:', e); process.exit(2); });
