#!/usr/bin/env node
/**
 * AI 问答「参考来源」单行折叠 —— CDP 真实浏览器验证
 *
 * 验证点：
 *   A1 参考来源区域渲染出 .cited-tags，且默认带 folded（只占一行）
 *   A2 folded 时容器高度 == 一行 tag 高度（不露半行）
 *   A3 内容超出一行时出现「展开全部」按钮
 *   A4 点「展开全部」后容器变高、按钮变「收起」，能看全所有来源
 *   A5 再点「收起」回到一行
 *   A6 窄视口（窗口宽度变化）重新计算折叠，仍不溢出
 *
 * 前置：后端 8005、前端 5273（dist 已构建），学生 20249999/A0987654，课程 5 有资料。
 * 运行：node test/e2e/cited-sources-fold-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PORT = 9321;
const PROFILE = 'D:/tmp/zhike-citefold-e2e/profile';
const COURSE_ID = 5;
const QUESTION = '介绍一下网络层和传输层的主要功能';

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
    this.ws = ws; this.id = 0; this.pending = new Map();
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
      }, 60000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error('eval exception: ' + (d.exception?.description || d.text));
    }
    return r.result.value;
  }
  async navigate(url) {
    await this.send('Page.navigate', { url });
    for (let i = 0; i < 200; i++) {
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
  async viewport(width, height = 900) {
    await this.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await sleep(600);
  }
}

async function waitFor(cdp, expr, timeout = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let ok = false;
    try { ok = await cdp.eval(expr); } catch { ok = false; }
    if (ok) return true;
    await sleep(250);
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
  if (!ok) throw new Error('登录未跳转工作台: ' + username);
}

/** 读取参考来源区域的折叠状态 */
async function snap(cdp) {
  const raw = await cdp.eval(`(function(){
    var box = document.querySelector('.cited-sources');
    if (!box) return '{"state":"NO_BOX"}';
    var tags = box.querySelector('.cited-tags');
    var btn = box.querySelector('.cite-toggle');
    var first = tags && tags.firstElementChild;
    var out = {
      state: 'OK',
      groups: tags ? tags.children.length : 0,
      folded: tags ? tags.classList.contains('folded') : null,
      clientH: tags ? tags.clientHeight : 0,
      scrollH: tags ? tags.scrollHeight : 0,
      rowH: first ? first.offsetHeight : 0,
      btn: btn ? btn.textContent.replace(/\\s+/g, '') : null,
      toggleLeft: btn ? Math.round(btn.getBoundingClientRect().left) : null
    };
    return JSON.stringify(out);
  })()`);
  try { return JSON.parse(raw); } catch { return { state: 'PARSE_ERR', raw }; }
}

/** 滚到参考来源区域再截图，否则证据图里看不到区块 */
async function shotCited(cdp, name) {
  try {
    await cdp.eval(`(function(){
      var el = document.querySelector('.cited-sources');
      if (el) el.scrollIntoView({ block: 'center' });
      return 'OK';
    })()`);
    await sleep(350);
  } catch { /* 滚动失败也照样截图 */ }
  return cdp.shot(name);
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用旧 profile */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
    '--no-first-run', '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', 'about:blank',
  ], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      const list = await res.json();
      const page = list.find((t) => t.type === 'page');
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 未就绪 */ }
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
  await cdp.viewport(1440, 1000);
  return { cdp, chrome };
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    log('登录学生账号');
    await login(cdp, '20249999', 'A0987654');

    log('打开 AI 助教页 course=' + COURSE_ID);
    await cdp.navigate(`${BASE}/student/courses/${COURSE_ID}/qa`);
    const ready = await waitFor(cdp, `!!document.querySelector('.dock-textarea textarea, textarea')`, 20000);
    check('A0 问答输入框就绪', ready);
    if (!ready) throw new Error('AI 助教页未加载');

    log('提问并等待回答 + 参考来源');
    await cdp.eval(`(function(){
      var el = document.querySelector('.dock-textarea textarea, textarea');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, ${JSON.stringify(QUESTION)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return 'OK';
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){ var b = document.querySelector('button.dock-send'); if(b) b.click(); return 'OK'; })()`);

    const cited = await waitFor(cdp, `!!document.querySelector('.cited-sources .cited-tags')`, 150000);
    check('A0b 回答已带参考来源', cited);
    if (!cited) {
      await cdp.shot('cited-fold-no-sources');
      throw new Error('未出现参考来源（检索为空或 AI 不可用）');
    }
    await sleep(800);

    // ===== A1/A2/A3 默认态 =====
    const s1 = await snap(cdp);
    log('默认态: ' + JSON.stringify(s1));
    check('A1 默认收起（folded）', s1.folded === true, `groups=${s1.groups} clientH=${s1.clientH} scrollH=${s1.scrollH}`);
    check('A2 只占一行高度', s1.clientH <= s1.rowH + 6, `clientH=${s1.clientH} rowH=${s1.rowH}`);
    const needFold = s1.scrollH > s1.clientH + 2;
    check('A3 溢出时才出现展开按钮', needFold ? s1.btn === '展开全部' : s1.btn === null, `btn=${s1.btn}`);
    await shotCited(cdp, 'cited-fold-collapsed');

    // 展开/收起一轮：折叠前 scrollHeight 即全部内容高度，展开后 clientHeight 应达到它
    async function toggleRound(tag, before) {
      const contentH = before.scrollH;
      await cdp.eval(`(function(){ var b = document.querySelector('.cite-toggle'); if(b) b.click(); return 'OK'; })()`);
      await sleep(450);
      const s2 = await snap(cdp);
      log(`展开态(${tag}): ` + JSON.stringify(s2));
      check(`A4 展开后看全来源(${tag})`, s2.folded === false && s2.clientH >= contentH - 2 && s2.btn === '收起',
        `clientH=${s2.clientH} contentH=${contentH} btn=${s2.btn}`);
      await shotCited(cdp, 'cited-fold-expanded-' + tag);

      await cdp.eval(`(function(){ var b = document.querySelector('.cite-toggle'); if(b) b.click(); return 'OK'; })()`);
      await sleep(450);
      const s3 = await snap(cdp);
      check(`A5 再收起回到一行(${tag})`, s3.folded === true && s3.clientH <= s3.rowH + 6, `clientH=${s3.clientH} rowH=${s3.rowH}`);
    }

    if (needFold) await toggleRound('wide', s1);

    // ===== A6 窄视口重算 =====
    await cdp.viewport(760, 900);
    await sleep(800);
    const s4 = await snap(cdp);
    log('窄视口: ' + JSON.stringify(s4));
    check('A6 窄视口仍只占一行', s4.folded === true && s4.clientH <= s4.rowH + 6, `clientH=${s4.clientH} rowH=${s4.rowH}`);
    const narrowFold = s4.scrollH > s4.clientH + 2;
    check('A6b 窄视口出现展开入口', narrowFold ? s4.btn === '展开全部' : true, `btn=${s4.btn}`);
    await shotCited(cdp, 'cited-fold-narrow');

    // 窄视口下溢出时，把展开/收起重跑一遍（真实交互动线）
    if (narrowFold) {
      if (!needFold) {
        check('A3 溢出时才出现展开按钮',
          s1.btn === null && s4.btn === '展开全部', `wideBtn=${s1.btn} narrowBtn=${s4.btn}`);
      }
      await toggleRound('narrow', s4);
      await cdp.viewport(760, 900);
      await sleep(400);
      const s5 = await snap(cdp);
      check('A7 收起后窄视口仍一行', s5.folded === true && s5.btn === '展开全部',
        `clientH=${s5.clientH} btn=${s5.btn}`);

      // ===== A8 点回答里的 [N] 上标：被折叠的来源应自动展开并高亮 =====
      // 回答正文不一定会带 [N] 引用标记（模型自由发挥），无上标则跳过此条
      const clicked = await cdp.eval(`(function(){
        var sup = document.querySelector('.cite-sup[data-cite]');
        if (!sup) return 'NO_SUP';
        sup.click();
        return 'CLICKED ' + sup.dataset.cite;
      })()`);
      if (clicked === 'NO_SUP') {
        log('SKIP  A8 本次回答正文无 [N] 引用上标');
      } else {
        await sleep(500);
        const s6 = await snap(cdp);
        const hi = await cdp.eval(`document.querySelectorAll('.cite-tag.highlighted').length`);
        log('点上标后: ' + JSON.stringify(s6) + ' highlighted=' + hi);
        check('A8 点上标自动展开并高亮目标来源', s6.folded === false && hi >= 1,
          `${clicked} folded=${s6.folded} highlighted=${hi}`);
        await shotCited(cdp, 'cited-fold-cite-jump');
      }
    }

    await cdp.viewport(1440, 1000);
    await sleep(500);

    log('清理登录态');
    await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
  }

  console.log(`\n==== 结果: ${failures === 0 ? 'ALL PASS' : failures + ' FAIL'} ====`);
  process.exit(failures === 0 ? 0 : 1);
}

run().catch((e) => {
  console.error('运行异常: ' + e.message);
  process.exit(2);
});
