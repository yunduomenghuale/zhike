#!/usr/bin/env node
/**
 * 教师端 AI 问答「参考来源」展示验证（CourseQA.vue 补 sources 渲染后）
 *
 * 背景：教师端 Web 此前只携带 cited_chunks 数据、模板不展示来源标签；
 * 本脚本验证补齐后：历史会话加载 → 答案下方出现「参考来源」，
 * 课件片段标签带页码（第4章 网络层课件 P1）。
 *
 * 前置：后端 8005、前端 5273 已启动；t101=pass1234（课程5教师，
 *       有其本人 QA#82 记录：5 条课件引用，页码 1/2/9/10/17）。
 * 运行：node test/e2e/teacher-qa-cited-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9222;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const TEACHER = 't101';
const PW = process.env.T101_PW || 'pass1234';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------- CDP 客户端（与 cdp-drive.js 同款） ----------------
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.exceptions = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method === 'Runtime.exceptionThrown') {
        this.exceptions.push(msg.params.exceptionDetails?.exception?.description || 'unknown');
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
    await sleep(500); // 等 Vue 挂载 + 首屏请求
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
  if (!ok) throw new Error('登录失败或未跳转工作台: ' + username);
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用旧 profile */ }
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

// ---------------- 测试结果记录 ----------------
const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}

// ---------------- 测试流程 ----------------
async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    await login(cdp, TEACHER, PW);

    // 1. 进入教师端课程5 AI 问答页
    await cdp.navigate(BASE + '/teacher/courses/5/qa');
    const pageOk = await waitFor(cdp, `document.body.innerText.includes('AI 问答')`, 15000);
    check('Q1 进入教师端课程5 AI 问答页', pageOk, await cdp.eval('location.pathname'));
    check('Q2 初始为空白新会话（还没有提问）', await waitFor(cdp, `document.body.innerText.includes('还没有提问')`, 8000));

    // 2. 打开历史记录面板
    await cdp.eval(`(function(){
      var btns = Array.from(document.querySelectorAll('.action-btn'));
      var b = btns.find(function(x){ return x.textContent.includes('历史记录'); });
      if (b) b.click();
    })()`);
    const panelOk = await waitFor(cdp, `document.querySelectorAll('.side-item').length > 0`, 10000);
    check('Q3 历史面板打开且存在会话', panelOk);

    // 3. 点击最新会话（含 QA#82「考核方式」，5 条课件引用）
    const firstTitle = await cdp.eval(`(document.querySelector('.side-item .side-item-q')||{textContent:''}).textContent.trim()`);
    check('Q4 最新会话为「考核方式」提问（QA#82）', firstTitle.includes('考核方式'), firstTitle);
    await cdp.eval(`(function(){ var it = document.querySelector('.side-item'); if (it) it.click(); })()`);

    // 4. 等消息渲染，断言参考来源
    const msgOk = await waitFor(cdp, `document.querySelectorAll('.qa-item .message.answer .answer-md').length > 0`, 10000);
    check('Q5 会话消息加载（答案渲染）', msgOk);

    const srcCount = await waitFor(cdp, `document.querySelectorAll('.qa-item .sources').length > 0`, 8000)
      ? await cdp.eval(`document.querySelectorAll('.qa-item .sources').length`)
      : 0;
    check('Q6 答案下方出现「参考来源」区块', srcCount > 0, 'blocks=' + srcCount);

    const titleText = await cdp.eval(`(document.querySelector('.qa-item .sources-title')||{textContent:''}).textContent.trim()`);
    check('Q7 来源标题为「参考来源」', titleText.includes('参考来源'), titleText);

    const tags = await cdp.eval(`Array.from(document.querySelectorAll('.qa-item .source-tags .el-tag')).map(function(t){return t.textContent.trim()})`);
    check('Q8 来源标签汇总为 1 条（同章课件 5 页引用合并）', tags.length === 1, JSON.stringify(tags));
    check('Q9 汇总标签为「第4章 网络层课件 P1 / P2 / P9 / P10 / P17」', tags[0] === '第4章 网络层课件 P1 / P2 / P9 / P10 / P17', JSON.stringify(tags));
    const pages = (tags[0] || '').split('P').slice(1).map((s) => s.trim().split(' ')[0]).filter(Boolean);
    check('Q10 页码齐全且数字升序（1/2/9/10/17）', JSON.stringify(pages) === JSON.stringify(['1', '2', '9', '10', '17']), JSON.stringify(pages));

    // Q10.5 可见性：el-tag 自带 zoom-in-center 过渡，headless 下起始态 scaleX(0)，
    // 需等过渡 class 清除、布局宽度恢复（与学生端同款行为，真实浏览器 0.3s 内完成）
    const visible = await waitFor(cdp, `(function(){
      var t = document.querySelector('.qa-item .source-tags .el-tag');
      return !!t && t.getBoundingClientRect().width > 50;
    })()`, 10000);
    const tagW = visible ? await cdp.eval(`Math.round(document.querySelector('.qa-item .source-tags .el-tag').getBoundingClientRect().width)`) : 0;
    check('Q10.5 标签过渡完成、实际可见（宽度>50px）', visible, 'w=' + tagW + 'px');

    // 5. 视觉留证（等过渡稳定后）
    const shot = await cdp.shot('teacher-qa-cited');
    check('Q11 截图留存', true, shot);

    // 6. 无未捕获异常（页面级，CDP exceptionThrown 事件收集）
    check('Q12 无页面 JS 未捕获异常', cdp.exceptions.length === 0, 'exceptions=' + cdp.exceptions.length + (cdp.exceptions.length ? ' | ' + cdp.exceptions[0].slice(0, 120) : ''));
  } finally {
    try { await cdp.send('Browser.close'); } catch { /* ignore */ }
    chrome.kill();
  }

  const failed = results.filter((r) => !r.ok);
  console.log('\n===== 汇总 =====');
  console.log('总计 ' + results.length + ' 项，通过 ' + (results.length - failed.length) + ' 项，失败 ' + failed.length + ' 项');
  if (failed.length) {
    failed.forEach((f) => console.log('失败: ' + f.name));
    process.exitCode = 1;
  } else {
    console.log('ALL_PASS');
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 2;
});
