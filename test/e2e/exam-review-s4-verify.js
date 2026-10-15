#!/usr/bin/env node
/**
 * S4 回看归序 E2E 视觉验证（CDP 真实浏览器）
 *
 * 背景：多选题回看曾显示「正确答案：C、D、B」（顺序乱），且解析按原题顺序书写
 * （如「D 错误」）在选项乱序后字母错位。S4 方案：乱序只在答题时生效，回看/批改
 * 统一回原题空间（原始选项顺序 + 原始正确答案 + 学生答案 unmap）。
 *
 * 覆盖：
 *   R1 学生登录 → 回看页正常加载（exam 25，sub 6，含乱序 layout 的真实答卷）
 *   R2 成绩卡显示乱序提示行「本场考试开启了选项乱序…」
 *   R3 多选题（q6）选项为原始顺序；正确答案 A、B、C（字母升序）；
 *      学生答案 A、B、C；「正确答案/你的选择」标记与解析文本「D 错误」对齐
 *   R4 单选题（q3）答错：正确 B / 你的选择 D 标记正确
 *   R5 成绩数字与 API 一致（objective_score）
 *
 * 运行：node test/e2e/exam-review-s4-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-review';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const EXAM_ID = 25;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }
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

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
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

// 从回看页提取结构化信息（供断言）
function extractReview() {
  const cards = Array.from(document.querySelectorAll('.exam-review-page .q-card'));
  const tip = document.querySelector('.exam-review-page .score-tips .shuffle-tip');
  const scoreMain = document.querySelector('.exam-review-page .score-card .score-main');
  return JSON.stringify({
    shuffleTip: tip ? tip.textContent.trim().replace(/\s+/g, ' ') : null,
    objective: scoreMain ? scoreMain.querySelector('.score-value.primary')?.textContent.trim() : null,
    total: scoreMain ? scoreMain.querySelectorAll('.score-value')[1]?.textContent.trim() : null,
    cards: cards.map((c) => {
      const opts = Array.from(c.querySelectorAll('.q-opt')).map((o) => ({
        key: o.querySelector('.opt-key')?.textContent.replace('.', '').trim(),
        text: o.textContent.replace(/^[A-D]\./, '').trim(),
        right: o.classList.contains('opt-right'),
        wrong: o.classList.contains('opt-wrong'),
        tag: o.querySelector('.el-tag')?.textContent.trim() || null,
      }));
      const lines = Array.from(c.querySelectorAll('.review-line')).map((l) => l.textContent.trim().replace(/\s+/g, ' '));
      return { opts, lines };
    }),
  });
}

(async () => {
  const { cdp, chrome } = await launchChrome();
  try {
    // R1 登录学生并进入回看页
    await login(cdp, '20249999', 'A0987654');
    await cdp.navigate(BASE + '/student/exams/' + EXAM_ID + '/review');
    const loaded = await waitFor(cdp, `!!document.querySelector('.exam-review-page .q-card')`, 20000);
    check('R1 回看页加载（含题目卡片）', loaded);

    const data = JSON.parse(await cdp.eval('(' + extractReview.toString() + ')()'));

    // R2 乱序提示行
    check('R2 成绩卡显示乱序提示行', /选项乱序.*回看按原题顺序展示/.test(data.shuffleTip || ''), data.shuffleTip);

    // 多选题卡片：正确答案 A/B/C、解析「D 错误」与 D 选项对齐
    const multi = data.cards.find((c) => c.opts.length === 4 && c.lines.some((l) => l.includes('多选题')) )
      || data.cards.find((c) => c.opts.length === 4 && /正确/.test(c.lines.join('')));
    // 用题干文本精确定位多选卡片
    const multiCard = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-review-page .q-card'));
      var c = cards.find(function(x){ return x.querySelector('.q-stem') && x.querySelector('.q-stem').textContent.includes('VLAN 与 STP'); });
      if (!c) return null;
      return JSON.stringify({
        opts: Array.from(c.querySelectorAll('.q-opt')).map(function(o){
          return { key: o.querySelector('.opt-key').textContent.replace('.','').trim(),
                   text: o.textContent.replace(/^[A-D]\\./,'').trim(),
                   right: o.classList.contains('opt-right'), wrong: o.classList.contains('opt-wrong'),
                   tag: o.querySelector('.el-tag') ? o.querySelector('.el-tag').textContent.trim() : null };
        }),
        lines: Array.from(c.querySelectorAll('.review-line')).map(function(l){ return l.textContent.trim().replace(/\\s+/g,' '); })
      });
    })()`);
    const m = multiCard ? JSON.parse(multiCard) : null;
    check('R3.1 多选选项为原始顺序 A/B/C/D', !!m && m.opts.map((o) => o.key).join('') === 'ABCD',
      m ? m.opts.map((o) => o.key + ':' + o.text.slice(0, 8)).join(' ') : 'card not found');
    check('R3.2 多选正确答案 A、B、C（字母升序，不再 C、D、B）',
      !!m && m.lines.some((l) => l.startsWith('正确答案：A、B、C')),
      m ? (m.lines.find((l) => l.startsWith('正确答案')) || '') : '');
    check('R3.3 多选学生答案 A、B、C（unmap 回原始空间）',
      !!m && m.lines.some((l) => l.startsWith('你的答案：A、B、C')),
      m ? (m.lines.find((l) => l.startsWith('你的答案')) || '') : '');
    check('R3.4 A/B/C 标记「正确答案」且 D 无标记（与解析「D 错误」对齐）',
      !!m && m.opts.filter((o) => o.tag === '正确答案').map((o) => o.key).join('') === 'ABC'
        && m.opts[3].tag === null,
      m ? m.opts.map((o) => o.key + ':' + (o.tag || '-')).join(' ') : '');
    check('R3.5 解析文本含「D 错误」且与选项 D 内容匹配',
      !!m && m.lines.some((l) => l.includes('D 错误'))
        && m.opts[3].text.includes('阻断所有冗余链路'),
      m ? (m.lines.find((l) => l.includes('解析')) || '').slice(0, 50) : '');

    // R4 单选题答错标记：正确 B / 你的选择 D
    const singleCard = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-review-page .q-card'));
      var c = cards.find(function(x){ return x.querySelector('.q-stem') && x.querySelector('.q-stem').textContent.includes('属于不同 VLAN 的端口之间'); });
      if (!c) return null;
      return JSON.stringify(Array.from(c.querySelectorAll('.q-opt')).map(function(o){
        return { key: o.querySelector('.opt-key').textContent.replace('.','').trim(),
                 right: o.classList.contains('opt-right'), wrong: o.classList.contains('opt-wrong'),
                 tag: o.querySelector('.el-tag') ? o.querySelector('.el-tag').textContent.trim() : null };
      }));
    })()`);
    const s = singleCard ? JSON.parse(singleCard) : null;
    check('R4 单选题答错：B 标记正确、D 标记「你的选择」',
      !!s && s.find((o) => o.key === 'B')?.tag === '正确答案'
        && s.find((o) => o.key === 'D')?.tag === '你的选择',
      s ? s.map((o) => o.key + ':' + (o.tag || '-')).join(' ') : 'card not found');

    // R5 成绩数字与 API 一致（objective 17 = 单选5+单选0+多选5+判断5+填空按空部分分2；
    //     简答未批阅 → 总分「待批阅」）
    check('R5 客观题得分 17、总分待批阅（简答未批）', data.objective === '17' && data.total === '待批阅',
      'objective=' + data.objective + ' total=' + data.total);

    await cdp.shot('exam-review-s4');
    console.log('截图: exam-review-s4.png');
  } finally {
    chrome.kill();
  }
  const failed = results.filter((r) => !r.ok);
  console.log('----');
  console.log(results.length + ' 项断言，通过 ' + (results.length - failed.length) + '，失败 ' + failed.length);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('ERROR:', e.message); process.exit(2); });
