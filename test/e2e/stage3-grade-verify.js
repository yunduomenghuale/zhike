#!/usr/bin/env node
/** Stage 3 真实浏览器端到端（本地 5273 / 8092 通用）。
 *
 * 覆盖：平台父页面持票据 → sandbox iframe 内 shim → postMessage → 父页面代发
 * POST /api/lab-gate/grade/ → 服务端入库；以及 C41 伪造消息丢弃、S4 失败重试、
 * 预览不提交、学生端立刻看分、教师端统计「不适用」（C17）。
 *
 * 用法：node test/e2e/stage3-grade-verify.js [setupJson]
 *   SETUP=D:/tmp/stage3-setup.json SHOT_PREFIX=stage3-local node test/e2e/stage3-grade-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = Number(process.env.CDP_PORT || 9225);
const SETUP_PATH = process.argv[2] || process.env.SETUP || 'D:/tmp/stage3-setup.json';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const SHOT_PREFIX = process.env.SHOT_PREFIX || 'stage3-local';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-stage3';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const setup = JSON.parse(fs.readFileSync(SETUP_PATH, 'utf-8'));
const BASE = process.env.BASE || setup.base || 'http://127.0.0.1:5273';

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
    const extra = where && where.sessionId ? { sessionId: where.sessionId } : {};
    const r = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, ...extra,
    }, where && where.sessionId);
    if (r.exceptionDetails) {
      return { __error: (r.exceptionDetails.exception?.description || r.exceptionDetails.text || '').split('\n')[0] };
    }
    return r.result.value;
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    console.log('shot -> test/screenshots/' + name + '.png');
  }
  consoleErrors(mark = 0) {
    return this.events.slice(mark)
      .filter((e) => e.method === 'Log.entryAdded' && e.params.entry.level === 'error')
      .map((e) => e.params.entry.text)
      .filter((t) => !t.includes('Cross-Origin-Opener-Policy header has been ignored'));
  }
  async attachIframe(since) {
    for (let i = 0; i < 30; i++) {
      const hits = this.events.slice(since)
        .filter((e) => e.method === 'Target.attachedToTarget')
        .filter((e) => {
          const t = e.params.targetInfo || {};
          return t.type === 'iframe' || String(t.url || '').includes('/lab-gate/frame/');
        });
      if (hits.length) {
        const sid = hits[hits.length - 1].params.sessionId;
        try { await this.send('Runtime.enable', {}, sid); } catch (e) {}
        return { sessionId: sid };
      }
      await sleep(300);
    }
    return null;
  }
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined ? ' | ' + String(detail).slice(0, 260) : ''));
}

async function login(cdp, username, password) {
  await cdp.eval('try { localStorage.clear() } catch (e) {}');
  await cdp.send('Page.navigate', { url: BASE + '/login' });
  await sleep(2200);
  for (let i = 0; i < 60; i++) {
    if (await cdp.eval('document.readyState') === 'complete') break;
    await sleep(150);
  }
  const n = await cdp.eval(`(() => {
    const setVal = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set;
      setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const inputs = document.querySelectorAll('.split-auth__form-box--login input');
    if (inputs.length < 2) return inputs.length;
    setVal(inputs[0], ${JSON.stringify(username)});
    setVal(inputs[1], ${JSON.stringify(password)});
    return inputs.length;
  })()`);
  if (n !== 2) return '/login(inputs=' + n + ')';
  await sleep(300);
  await cdp.eval(`document.querySelector('.split-auth__form-box--login .auth-submit').click()`);
  for (let i = 0; i < 100; i++) {
    await sleep(200);
    const p = await cdp.eval('location.pathname').catch(() => '');
    if (p && p !== '/login') return p;
  }
  return await cdp.eval('location.pathname');
}

const PATCH_FETCH = `(() => {
  if (window.__stage3FetchPatched) return window.__stage3Posts.length;
  window.__stage3Posts = [];
  const orig = window.fetch;
  window.fetch = function (u, o) {
    if (String(u).indexOf('/lab-gate/grade/') >= 0) {
      window.__stage3Posts.push({ url: String(u), options: o || null });
    }
    return orig.apply(this, arguments);
  };
  window.__stage3FetchPatched = true;
  return 0;
})()`;

(async () => {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
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
    } catch (e) {}
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('Chrome 未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws fail'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');
  try { await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }); } catch (e) {}
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  try {
    // ================= 阶段 A：正式父页面 + iframe =================
    const sinceA = cdp.events.length;
    await cdp.send('Page.navigate', { url: BASE + setup.page_url });
    await sleep(4500);

    const parentHtml = await cdp.eval('document.documentElement.outerHTML');
    check('A1 平台父页面渲染（含 sandbox iframe）', typeof parentHtml === 'string' && parentHtml.includes('id="lab-frame"'));
    const sandboxAttr = await cdp.eval(`document.getElementById('lab-frame') && document.getElementById('lab-frame').getAttribute('sandbox')`);
    check('A2 iframe sandbox 不含 allow-same-origin（C40）',
      sandboxAttr === 'allow-scripts allow-forms allow-modals', sandboxAttr);
    const frameSrc = await cdp.eval(`document.getElementById('lab-frame') && document.getElementById('lab-frame').getAttribute('src')`);
    check('A3 iframe src 绝对路径且不含票据（C45）',
      typeof frameSrc === 'string' && frameSrc.startsWith('/api/lab-gate/frame/') && !frameSrc.includes('token='), frameSrc);
    const bootGone = await cdp.eval(`typeof window.__LAB_BOOT_TOKEN__ === 'undefined'`);
    check('A4 父页面票据引导变量用完即删', bootGone === true);
    check('A5 父页面 fetch 探针注入', (await cdp.eval(PATCH_FETCH)) === 0);

    // C41 运行时：伪造 postMessage（source = 顶层 window，不是 frame.contentWindow）应被丢弃
    await cdp.eval(`window.postMessage({ type: 'lab:grade', payload: { total_score: 100, elapsed_seconds: 1 } }, '*')`);
    await sleep(1500);
    const forgedPosts = await cdp.eval(`window.__stage3Posts.length`);
    check('A6 伪造 postMessage 被父页面丢弃（未发起成绩上报，C41）', forgedPosts === 0, 'posts=' + forgedPosts);

    const frame = await cdp.attachIframe(sinceA);
    check('A7 定位到 sandbox iframe 独立执行上下文', !!frame, JSON.stringify(frame));

    if (frame) {
      const storage = await cdp.eval(`(() => { try { localStorage.getItem('x'); return 'READABLE'; } catch (e) { return e.name; } })()`, frame);
      check('A8 iframe 内 localStorage 抛 SecurityError（L2 隔离）', storage === 'SecurityError', storage);
      const bridge = await cdp.eval(`(() => ({
        hasBridge: typeof window.LabBridge !== 'undefined',
        preview: window.LabBridge && window.LabBridge.preview,
        context: window.__stage3Context || (window.LabBridge && window.LabBridge.context),
        ready: window.__stage3Ready === true,
        bootToken: typeof window.__LAB_BOOT_TOKEN__,
        htmlHasToken: document.documentElement.outerHTML.indexOf('X-Lab-Token') >= 0
      }))()`, frame);
      check('A9 iframe 内 shim 注入且 preview=false', bridge && bridge.hasBridge === true && bridge.preview === false, JSON.stringify(bridge));
      check('A10 validate() 拿到的 context 只有四字段、不含票据（C45）',
        bridge && bridge.context && typeof bridge.context.labId === 'number'
        && typeof bridge.context.submissionId === 'number'
        && typeof bridge.context.totalScore === 'number'
        && bridge.context.gradeEndpoint === '/api/lab-gate/grade/'
        && JSON.stringify(bridge.context).indexOf('token') < 0,
        JSON.stringify(bridge && bridge.context));
      check('A11 iframe 内无引导票据变量、页面无票据头字面量（C42）',
        bridge && bridge.bootToken === 'undefined' && bridge.htmlHasToken === false, JSON.stringify(bridge));

      // 失败重试：越界分数 → 中文错误 → 修正后成功（S4 失败自动解除闸门）
      const bad = await cdp.eval(`window.__stage3Submit({ total_score: 101, elapsed_seconds: 1 })`, frame);
      check('A12 越界分数返回中文错误且 code=400',
        bad && bad.code === 400 && String(bad.message).includes('成绩超出实验总分范围'), JSON.stringify(bad));
      const good = await cdp.eval(`(async () => {
        document.querySelectorAll('#tasks input[type=checkbox]').forEach(b => { b.checked = true; });
        return await document.getElementById('finish').onclick();
      })()`, frame);
      check('A13 修正后 reportGrade 成功，总分 100 / status=submitted',
        good && good.code === 0 && good.data && Number(good.data.total_score) === 100
        && good.data.status === 'submitted', JSON.stringify(good));

      const posts = await cdp.eval(`window.__stage3Posts.map(p => ({ url: p.url, hasToken: !!(p.options && p.options.headers && p.options.headers['X-Lab-Token']) }))`);
      check('A14 两次上报均由父页面代发且带 X-Lab-Token',
        Array.isArray(posts) && posts.length === 2 && posts.every(p => p.hasToken === true), JSON.stringify(posts));

      // S4：成功后再次上报不得再产生 POST（一次性闸门）
      // 不 await 这个 Promise：S4 闸门下父页面不会再响应，故意只发不等
      await cdp.eval(`(() => { window.__stage3Submit({ total_score: 100, elapsed_seconds: 1 }); return 'SENT'; })()`, frame);
      await sleep(1200);
      const afterThird = await cdp.eval(`window.__stage3Posts.length`);
      check('A15 成功后一次性闸门拒绝重复上报（S4）', afterThird === 2, 'posts=' + afterThird);

      const frameLog = await cdp.eval(`document.getElementById('log').textContent`, frame);
      check('A16 iframe 日志含失败与成功两次响应',
        typeof frameLog === 'string' && frameLog.includes('成绩超出实验总分范围') && frameLog.includes('成绩已提交'), frameLog);
      await cdp.shot(SHOT_PREFIX + '-after-report');
    }

    // ================= 阶段 B：教师预览不提交 =================
    const sinceB = cdp.events.length;
    await cdp.send('Page.navigate', { url: BASE + setup.preview_url });
    await sleep(3500);
    check('B1 预览页 fetch 探针注入', (await cdp.eval(PATCH_FETCH)) === 0);
    const pv = await cdp.eval(`(() => ({ preview: window.__LAB_PREVIEW__, token: window.__LAB_BOOT_TOKEN__ }))()`);
    check('B2 预览父页面 preview=true 且无票据', pv && pv.preview === true && pv.token == null, JSON.stringify(pv));
    const pvFrame = await cdp.attachIframe(sinceB);
    check('B3 定位预览 iframe 会话', !!pvFrame);
    if (pvFrame) {
      const shim = await cdp.eval(`(() => ({
        preview: window.LabBridge && window.LabBridge.preview,
        log: (document.getElementById('log') || {}).textContent || ''
      }))()`, pvFrame);
      check('B4 预览 iframe 内跳过提交', shim && shim.preview === true && shim.log.includes('不提交'), JSON.stringify(shim));
    }
    await sleep(1000);
    const pvPosts = await cdp.eval(`window.__stage3Posts.length`);
    check('B5 预览模式零成绩上报', pvPosts === 0, 'posts=' + pvPosts);
    await cdp.shot(SHOT_PREFIX + '-preview');

    // ================= 阶段 C：学生端真实登录 → 立刻看到分数 =================
    const markC = cdp.events.length;
    const stuPath = await login(cdp, setup.student, setup.student_pass);
    check('C1 学生真实账号 UI 登录成功', stuPath !== '/login', 'path=' + stuPath);
    await cdp.send('Page.navigate', { url: BASE + '/student/courses/' + setup.course_id + '/labs' });
    await sleep(3500);
    const stuText = await cdp.eval(`document.body.innerText`);
    check('C2 学生实验列表出现该自定义实验',
      typeof stuText === 'string' && stuText.includes(setup.lab_title), String(stuText).slice(0, 160));
    const scoreCard = await cdp.eval(`(() => {
      const title = ${JSON.stringify(setup.lab_title)};
      const card = [...document.querySelectorAll('article.lab-card')].find(c => {
        const t = c.querySelector('.lab-title');
        return t && t.textContent.trim() === title;
      });
      if (!card) return { found: false, all: [...document.querySelectorAll('article.lab-card .lab-title')].map(e => e.textContent.trim()) };
      const total = card.querySelector('.lab-score-total');
      const tag = [...card.querySelectorAll('.lab-card-head .el-tag')].map(e => e.textContent.trim());
      return { found: true, total: total ? total.textContent.trim().replace(/\\s+/g, ' ') : null, tag: tag };
    })()`);
    check('C3 学生端立刻显示总分 100',
      scoreCard && scoreCard.found && scoreCard.total && parseFloat(scoreCard.total) === 100
      && scoreCard.tag.some(t => t.includes('100')), JSON.stringify(scoreCard));
    const errsC = cdp.consoleErrors(markC);
    check('C4 学生实验页无控制台错误', errsC.length === 0, errsC.slice(0, 2).join(' | '));
    await cdp.shot(SHOT_PREFIX + '-student-score');

    // ================= 阶段 D：教师端统计（C17） =================
    const markD = cdp.events.length;
    const teaPath = await login(cdp, setup.teacher, setup.teacher_pass);
    check('D1 教师真实账号 UI 登录成功', teaPath !== '/login', 'path=' + teaPath);
    await cdp.send('Page.navigate', { url: BASE + '/teacher/courses/' + setup.course_id + '/labs' });
    await sleep(3500);
    const opened = await cdp.eval(`(() => {
      const rows = [...document.querySelectorAll('.el-table__body tr')];
      const row = rows.find(r => r.innerText.includes(${JSON.stringify(setup.lab_title)}));
      if (!row) return 'NO_ROW';
      const btn = [...row.querySelectorAll('button')].find(b => b.innerText.trim() === '详情');
      if (!btn) return 'NO_BTN';
      btn.click(); return 'OK';
    })()`);
    check('D2 打开该实验详情抽屉', opened === 'OK', opened);
    await sleep(3500);
    const drawer = await cdp.eval(`(() => {
      const t = document.querySelector('.el-drawer__title');
      const items = [...document.querySelectorAll('.el-drawer .d-item')].map(e => e.innerText.replace(/\\s+/g, ' ').trim());
      return { title: t ? t.textContent.trim() : null, items: items };
    })()`);
    check('D2b 抽屉确实是本次已发布的实验',
      drawer && drawer.title === setup.lab_title && drawer.items.some(s => s.includes('已发布')),
      JSON.stringify(drawer));
    const stats = await cdp.eval(`(() => {
      const nums = [...document.querySelectorAll('.stat-box .stat-num')].map(e => e.textContent.trim());
      const labels = [...document.querySelectorAll('.stat-box .stat-label')].map(e => e.textContent.trim());
      const cells = [...document.querySelectorAll('.el-drawer .el-table__body td')].map(e => e.innerText.trim());
      return { nums: nums, labels: labels, avgSteps: nums[labels.indexOf('平均步骤通过')] || null,
               avgScore: nums[labels.indexOf('提交均分')] || null,
               stepCells: cells.filter(c => c === '不适用').length };
    })()`);
    check('D3 教师端提交均分 = 100', stats && Number(stats.avgScore) === 100, JSON.stringify(stats));
    check('D4 平均步骤通过率为「—」（external 不拉低统计，C17）',
      stats && stats.avgSteps === '—', stats && stats.avgSteps);
    check('D5 详情表步骤列标注「不适用」', stats && stats.stepCells >= 1, JSON.stringify(stats && stats.stepCells));
    const errsD = cdp.consoleErrors(markD);
    check('D6 教师实验页无控制台错误', errsD.length === 0, errsD.slice(0, 2).join(' | '));
    await cdp.shot(SHOT_PREFIX + '-teacher-detail');
  } finally {
    try { await cdp.send('Browser.close'); } catch (e) {}
    chrome.kill();
  }

  const bad = results.filter((r) => !r.ok);
  console.log(`\n===== 汇总 =====\n总计 ${results.length} 项，通过 ${results.length - bad.length} 项，失败 ${bad.length} 项`);
  if (bad.length) { bad.forEach((b) => console.log('失败: ' + b.name)); process.exitCode = 1; } else console.log('ALL_PASS');
})().catch((e) => { console.error('验证异常:', e); process.exitCode = 2; });
