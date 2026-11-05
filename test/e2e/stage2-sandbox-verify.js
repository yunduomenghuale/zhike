#!/usr/bin/env node
/** Stage 2 本地浏览器验证：custom 实验父页面 + sandbox iframe 三项隔离实测。
 * 关键手法：用 Runtime.executionContextCreated + Page.getFrameTree 定位 iframe
 * 的独立 JS 上下文（opaque origin），在该 contextId 内执行探测，才是真·iframe 内执行。
 * 用法：node test/e2e/stage2-sandbox-verify.js <parentUrl>
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = process.env.CDP_PORT || 9223;
const BASE = process.env.BASE || 'http://127.0.0.1:5273';
const PARENT = process.argv[2] || '';
const PREVIEW = process.argv[3] || '';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-stage2';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const SHOT_PREFIX = process.env.SHOT_PREFIX || 'stage2-local';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(m.error.message)) : resolve(m.result);
      } else if (m.method) this.events.push(m);
    });
  }
  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('timeout ' + method)); } }, 30000);
    });
  }
  async eval(expression, where) {
    // where 可为 {sessionId}（OOPIF 独立 target）或 {contextId}（同 target 内独立上下文）
    const extra = where && where.sessionId ? { sessionId: where.sessionId } : (where && where.contextId ? { contextId: where.contextId } : {});
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, ...extra }, where && where.sessionId);
    if (r.exceptionDetails) return { __error: (r.exceptionDetails.exception?.description || r.exceptionDetails.text || '').split('\n')[0] };
    return r.result.value;
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    console.log('shot -> test/screenshots/' + name + '.png');
  }
  findContext(frameId) {
    const evs = this.events.filter((e) => e.method === 'Runtime.executionContextCreated');
    for (const e of evs) {
      const c = e.params.context;
      if (c.auxData && c.auxData.frameId === frameId && c.auxData.type === 'default') {
        return c.id;
      }
    }
    return null;
  }
  findIframeSession() {
    const evs = this.events.filter((e) => e.method === 'Target.attachedToTarget');
    for (const e of evs) {
      const info = e.params.targetInfo || {};
      if (info.type === 'iframe' || String(info.url || '').includes('/lab-gate/frame/')) {
        return e.params.sessionId;
      }
    }
    return null;
  }
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + String(detail).slice(0, 200) : ''));
}

(async () => {
  if (!PARENT) { console.error('缺少 parentUrl 参数'); process.exit(2); }
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  const chrome = spawn(CHROME, ['--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank'], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = list.find((t) => t.type === 'page');
      if (p) { wsUrl = p.webSocketDebuggerUrl; break; }
    } catch {}
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome 未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws fail'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  // OOPIF：sandbox iframe（opaque origin）常是独立 target，扁平自动挂载后在其会话内执行
  try { await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }); } catch (e) {}
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  try {
    await cdp.send('Page.navigate', { url: BASE + PARENT });
    await sleep(5000);

    // 主上下文探测：父页面结构
    const parentHtml = await cdp.eval('document.documentElement.outerHTML');
    check('P1 父页面渲染（含 sandbox iframe）', typeof parentHtml === 'string' && parentHtml.includes('id="lab-frame"'));
    const sandboxAttr = await cdp.eval(`(() => { const f = document.getElementById('lab-frame'); return f ? f.getAttribute('sandbox') : null; })()`);
    check('P2 iframe sandbox 属性 = allow-scripts allow-forms allow-modals（C40 无 allow-same-origin）',
      sandboxAttr === 'allow-scripts allow-forms allow-modals', sandboxAttr);
    const frameSrc = await cdp.eval(`(() => { const f = document.getElementById('lab-frame'); return f ? f.getAttribute('src') : null; })()`);
    check('P3 iframe src 绝对路径且不含票据（C45）', typeof frameSrc === 'string' && frameSrc.startsWith('/api/lab-gate/frame/') && !frameSrc.includes('token='), frameSrc);
    const parentScripts = await cdp.eval(`(async () => {
      const urls = [...document.querySelectorAll('script[src]')].map(s => s.src);
      const st = await Promise.all(urls.map(u => fetch(u, {method:'HEAD'}).then(r => r.status).catch(() => 0)));
      return urls.map((u, i) => u.split('/').pop() + ':' + st[i]);
    })()`);
    check('P4 lab-bridge-parent.js 200', Array.isArray(parentScripts) && parentScripts.some(s => s.startsWith('lab-bridge-parent.js:200')), JSON.stringify(parentScripts));
    const parentBase = await cdp.eval(`(() => { const b = document.querySelector('base'); return b ? b.getAttribute('href') : null; })()`);
    check('P5 父页面自带 <base> 签名资产路由', typeof parentBase === 'string' && parentBase.startsWith('/api/lab-gate/asset/'), parentBase);

    // 定位 iframe 的执行位置：优先 OOPIF 会话，退到同 target 的独立 contextId
    let where = null;
    let sessionId = cdp.findIframeSession();
    for (let i = 0; i < 30 && !sessionId; i++) { await sleep(300); sessionId = cdp.findIframeSession(); }
    if (sessionId) {
      try { await cdp.send('Runtime.enable', {}, sessionId); } catch (e) {}
      where = { sessionId };
    } else {
      const tree = await cdp.send('Page.getFrameTree');
      const mainFrameId = tree.frameTree.frame.id;
      const child = (tree.frameTree.childFrames || []).find((c) => c.frame.id !== mainFrameId);
      if (!child) {
        console.log('DIAG frameTree=' + JSON.stringify(tree).slice(0, 400));
        console.log('DIAG contexts=' + JSON.stringify(cdp.events.filter(e => e.method === 'Runtime.executionContextCreated').map(e => e.params.context.auxData)).slice(0, 400));
        throw new Error('未找到 iframe frame');
      }
      let ctxId = cdp.findContext(child.frame.id);
      for (let i = 0; i < 30 && !ctxId; i++) { await sleep(300); ctxId = cdp.findContext(child.frame.id); }
      if (ctxId) where = { contextId: ctxId };
    }
    check('C0 定位到 iframe 独立执行上下文（opaque origin）', where != null, JSON.stringify(where));

    if (where) {
      // I1-I3：真·iframe 内隔离探测
      const storage = await cdp.eval(`(() => { try { localStorage.getItem('x'); return 'READABLE'; } catch (e) { return e.name; } })()`, where);
      check('I1 iframe 内读 localStorage 抛 SecurityError', storage === 'SecurityError', storage);
      const ss = await cdp.eval(`(() => { try { sessionStorage.setItem('a','b'); return 'WRITABLE'; } catch (e) { return e.name; } })()`, where);
      check('I2 iframe 内写 sessionStorage 抛 SecurityError', ss === 'SecurityError', ss);
      const cookie = await cdp.eval(`(() => { try { return 'VAL:' + document.cookie; } catch (e) { return e.name; } })()`, where);
      check('I3 iframe 内 document.cookie 不可读（抛错或为空）', cookie === 'SecurityError' || cookie === 'VAL:', cookie);
      const parentDoc = await cdp.eval(`(() => { try { window.parent.document; return 'READABLE'; } catch (e) { return e.name; } })()`, where);
      check('I4 iframe 内访问 window.parent.document 抛 SecurityError', parentDoc === 'SecurityError', parentDoc);
      const opener = await cdp.eval(`(() => { try { return 'VAL:' + window.opener; } catch (e) { return e.name; } })()`, where);
      check('I5 iframe 内 window.opener 为空/受限', opener === 'VAL:null', opener);
      const apiFetch = await cdp.eval(`fetch('/api/auth/config/', { credentials: 'include' }).then(r => 'RESOLVED:' + r.status).catch(e => 'REJECTED:' + (e.name || e.message))`, where);
      check('I6 iframe 内 fetch /api 被 CORS 拒绝', typeof apiFetch === 'string' && apiFetch.startsWith('REJECTED'), apiFetch);

      // S1-S3：shim 四 API 与 postMessage 链路
      const bridgeState = await cdp.eval(`(async () => {
        if (!window.LabBridge) return { ok: false, why: 'no LabBridge' };
        const ctx = await LabBridge.validate();
        return { ok: true, preview: LabBridge.preview, ctx: ctx, log: (document.getElementById('log')||{}).textContent || '' };
      })()`, where);
      check('S1 iframe 内 LabBridge 存在（shim 注入）', bridgeState && bridgeState.ok === true, JSON.stringify(bridgeState));
      check('S2 正式模式 preview=false', bridgeState && bridgeState.preview === false);
      check('S3 validate() 经 postMessage 拿到 context（四字段，无票据）',
        bridgeState && bridgeState.ctx && typeof bridgeState.ctx.labId === 'number'
          && typeof bridgeState.ctx.submissionId === 'number'
          && typeof bridgeState.ctx.totalScore === 'number'
          && bridgeState.ctx.gradeEndpoint === '/api/lab-gate/grade/'
          && JSON.stringify(bridgeState.ctx).indexOf('token') < 0,
        JSON.stringify(bridgeState && bridgeState.ctx));

      // S4：reportGrade 经 postMessage → 父页面代发（Stage 3 端点未上线，任何响应都算链路通）
      const report = await cdp.eval(`(async () => {
        const boxes = document.querySelectorAll('#tasks input[type=checkbox]');
        boxes.forEach(b => { b.checked = true; b.dispatchEvent(new Event('change', {bubbles:true})); });
        document.getElementById('finish').click();
        for (let i = 0; i < 50; i++) {
          await new Promise(r => setTimeout(r, 200));
          const log = (document.getElementById('log')||{}).textContent || '';
          if (log.includes('reportGrade =>')) return log.trim().split('\\n').pop();
        }
        return 'TIMEOUT';
      })()`, where);
      check('S4 reportGrade 经 postMessage 有响应（父页面代发已触发）', typeof report === 'string' && report.includes('reportGrade =>'), report);
      await cdp.shot(SHOT_PREFIX + '-parent');
    }

    // 教师预览模式：不取票据、LabBridge.preview=true、不提交
    if (PREVIEW) {
      const attachBefore = cdp.events.filter(e => e.method === 'Target.attachedToTarget').length;
      await cdp.send('Page.navigate', { url: BASE + PREVIEW });
      await sleep(4000);
      const pv = await cdp.eval(`(() => ({ preview: window.__LAB_PREVIEW__, token: window.__LAB_BOOT_TOKEN__, context: window.__LAB_CONTEXT__ }))()`);
      check('V1 预览父页面 preview=true 且无票据', pv && pv.preview === true && pv.token == null, JSON.stringify(pv));
      const pvFrame = await cdp.eval(`(() => { const f = document.getElementById('lab-frame'); return f ? f.getAttribute('src') : null; })()`);
      check('V2 预览 iframe 带 preview=1 且无票据', typeof pvFrame === 'string' && pvFrame.includes('preview=1') && !pvFrame.includes('token='), pvFrame);
      const freshIframes = () => cdp.events.filter(e => e.method === 'Target.attachedToTarget')
        .slice(attachBefore).map(e => e.params)
        .filter(p => p.targetInfo && p.targetInfo.type === 'iframe');
      let pvSession = freshIframes().pop();
      for (let i = 0; i < 20 && !pvSession; i++) { await sleep(300); pvSession = freshIframes().pop(); }
      if (pvSession) {
        const shim = await cdp.eval(`(() => { try { return { preview: LabBridge.preview, hasBridge: typeof LabBridge.reportGrade === 'function', log: (document.getElementById('log')||{}).textContent || '' }; } catch (e) { return { err: e.message }; } })()`, { sessionId: pvSession.sessionId });
        check('V3 iframe 内 LabBridge.preview=true 且跳过提交', shim && shim.preview === true && shim.hasBridge && shim.log.includes('不提交'), JSON.stringify(shim));
      } else {
        check('V3 iframe 内 LabBridge.preview=true 且跳过提交', false, '未定位预览 iframe 会话');
      }
      await cdp.shot(SHOT_PREFIX + '-preview');
    }
  } finally {
    try { await cdp.send('Browser.close'); } catch {}
    chrome.kill();
  }

  const bad = results.filter((r) => !r.ok);
  console.log(`\n===== 汇总 =====\n总计 ${results.length} 项，通过 ${results.length - bad.length} 项，失败 ${bad.length} 项`);
  if (bad.length) { bad.forEach((b) => console.log('失败: ' + b.name)); process.exitCode = 1; } else console.log('ALL_PASS');
})().catch((e) => { console.error('验证异常:', e); process.exitCode = 2; });
