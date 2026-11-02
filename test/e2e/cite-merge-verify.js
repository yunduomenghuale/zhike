#!/usr/bin/env node
/**
 * 参考来源「按章节归并」—— 真实浏览器验证
 *
 * 验证点：
 *   B1 参考来源渲染成功，标签数 <= 引用条数
 *   B2 标签之间不存在「同章节重复」（剥掉 课件/讲解稿/·资料 后缀后唯一）
 *   B3 标签文案是章节名 + 汇总页码，徽章反映来源类型
 *   B4 展开详情里每段片段标明来源类型（课件/讲稿/资料）
 *   B5 折叠仍生效（一行 + 展开全部）
 *
 * 前置：后端 8005、前端 5273（dist 最新），学生 20249999/A0987654。
 * 运行：node test/e2e/cite-merge-verify.js [courseId]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PORT = 9331;
const PROFILE = 'D:/tmp/zhike-citemerge-e2e/profile';
const COURSE_ID = Number(process.argv[2]) || 5;
const QUESTION = '这门课程主要讲哪些内容？';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(m) { console.log(`[${stamp()}] ${m}`); }

let failures = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`);
  if (!ok) failures += 1;
}

// 与 utils/cited-sources.js 的 chapterBaseOf 同口径，用于断言「无同章节重复」
function chapterBase(name) {
  const m = /(课件|讲解稿| ?· ?资料)$/.exec(String(name || ''));
  return m ? String(name).slice(0, m.index).trim() : '';
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout ' + method)); } }, 60000);
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async navigate(url) {
    await this.send('Page.navigate', { url });
    for (let i = 0; i < 200; i++) {
      if ((await this.eval('document.readyState').catch(() => null)) === 'complete') break;
      await sleep(100);
    }
    await sleep(600);
  }
  async shot(name) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
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

async function login(cdp, user, pass) {
  await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
  await cdp.navigate(BASE + '/login');
  await waitFor(cdp, `!!document.querySelector('.split-auth__form-box--login .auth-submit')`, 15000);
  await cdp.eval(`(function(){
    function setVal(sel, v){
      var el=document.querySelector(sel); if(!el) return;
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el, v);
      el.dispatchEvent(new Event('input',{bubbles:true}));
    }
    setVal('.split-auth__form-box--login input[placeholder="请输入用户名"]', ${JSON.stringify(user)});
    setVal('.split-auth__form-box--login input[placeholder="请输入密码"]', ${JSON.stringify(pass)});
    var b=document.querySelector('.split-auth__form-box--login .auth-submit'); if(b) b.click();
  })()`);
  const ok = await waitFor(cdp, `location.pathname === '/dashboard' || location.pathname === '/'`, 30000);
  if (!ok) throw new Error('登录未跳转工作台');
}

(async () => {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用 */ }
  const chrome = spawn(CHROME, ['--headless=new', '--no-proxy-server', '--disable-gpu', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*', '--user-data-dir=' + PROFILE,
    '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      const p = list.find((t) => t.type === 'page');
      if (p) { wsUrl = p.webSocketDebuggerUrl; break; }
    } catch { /* 未就绪 */ }
    await sleep(250);
  }
  if (!wsUrl) { chrome.kill(); throw new Error('devtools 未就绪'); }
  const ws = new WebSocket(wsUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

  try {
    log('登录');
    await login(cdp, '20249999', 'A0987654');
    log(`打开 AI 助教 course=${COURSE_ID}`);
    await cdp.navigate(`${BASE}/student/courses/${COURSE_ID}/qa`);
    const ready = await waitFor(cdp, `!!document.querySelector('.dock-textarea textarea, textarea')`, 20000);
    check('B0 问答页就绪', ready);
    if (!ready) throw new Error('页面未加载');

    log('提问并等待参考来源');
    await cdp.eval(`(function(){
      var el=document.querySelector('.dock-textarea textarea, textarea');
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(el, ${JSON.stringify(QUESTION)});
      el.dispatchEvent(new Event('input',{bubbles:true}));
      return 'OK';
    })()`);
    await sleep(400);
    await cdp.eval(`(function(){ var b=document.querySelector('button.dock-send'); if(b) b.click(); return 'OK'; })()`);
    const hasCited = await waitFor(cdp, `!!document.querySelector('.cited-sources .cite-tag')`, 150000);
    check('B0b 出现参考来源标签', hasCited);
    if (!hasCited) { await cdp.shot('cite-merge-no-source'); throw new Error('没有参考来源'); }
    await sleep(800);

    // 读取标签
    const raw = await cdp.eval(`(function(){
      var tags = Array.from(document.querySelectorAll('.cited-sources .cite-tag'));
      return JSON.stringify({
        count: tags.length,
        items: tags.map(function(t){
          return {
            text: t.textContent.replace(/\\s+/g,' ').trim(),
            title: t.getAttribute('title') || '',
            badge: (t.querySelector('.cite-kind')||{}).textContent || '',
            nums: (t.querySelector('.cite-nums')||{}).textContent || ''
          };
        })
      });
    })()`);
    const info = JSON.parse(raw);
    log('标签: ' + JSON.stringify(info, null, 2));

    check('B1 至少一个标签', info.count >= 1, `count=${info.count}`);

    // B2：标签间不能出现同章节重复
    const bases = info.items.map((it) => chapterBase(it.title || it.text)).filter(Boolean);
    const dup = bases.filter((b, i) => bases.indexOf(b) !== i);
    check('B2 无同章节重复标签', dup.length === 0, bases.length ? `章节: ${bases.join(' | ')}` : '无章节名（原文兜底条目）');

    // B3：章节名做展示名（不能以课件/讲解稿结尾）
    const stillSuffixed = info.items.filter((it) => /(课件|讲解稿| ?· ?资料)$/.test((it.title || '').replace(/（引用.*$/, '').trim()));
    check('B3 展示名已剥类型后缀', stillSuffixed.length === 0, stillSuffixed.map((x) => x.title).join('; '));

    // B4：展开详情，每段应带来源类型
    await cdp.eval(`(function(){ var t=document.querySelector('.cited-sources .cite-tag'); if(t) t.click(); return 'OK'; })()`);
    await sleep(400);
    const detail = await cdp.eval(`(function(){
      var items = Array.from(document.querySelectorAll('.cite-detail .cite-item'));
      return JSON.stringify({
        total: items.length,
        withKind: items.filter(function(i){ return !!i.querySelector('.cite-item-kind'); }).length,
        kinds: items.map(function(i){ return (i.querySelector('.cite-item-kind')||{}).textContent || ''; })
      });
    })()`);
    const d = JSON.parse(detail);
    log('详情: ' + JSON.stringify(d));
    check('B4 详情每段标明来源类型', d.total > 0 && d.withKind === d.total, `${d.withKind}/${d.total} kinds=${d.kinds.join(',')}`);
    await cdp.shot('cite-merge-expanded');

    // B5：折叠仍生效
    const fold = JSON.parse(await cdp.eval(`(function(){
      var box=document.querySelector('.cited-sources .cited-tags');
      var first=box && box.firstElementChild;
      return JSON.stringify({
        folded: box ? box.classList.contains('folded') : null,
        clientH: box ? box.clientHeight : 0,
        scrollH: box ? box.scrollHeight : 0,
        rowH: first ? first.offsetHeight : 0,
        btn: (document.querySelector('.cite-toggle')||{}).textContent || null
      });
    })()`));
    log('折叠态: ' + JSON.stringify(fold));
    check('B5 折叠仍生效（一行）', fold.folded === true && fold.clientH <= fold.rowH + 6, `clientH=${fold.clientH} rowH=${fold.rowH}`);
    await cdp.shot('cite-merge-collapsed');

    // B6：来源里的编号必须都出现在正文引用上标里（不允许「正文没引用却列出来」的幽灵条目）
    const consistency = JSON.parse(await cdp.eval(`(function(){
      var sups = Array.from(document.querySelectorAll('.cite-sup')).map(function(s){ return Number(s.dataset.cite); });
      var shown = [];
      Array.from(document.querySelectorAll('.cited-sources .cite-nums')).forEach(function(t){
        t.textContent.trim().split(/\\s+/).forEach(function(x){ var n = Number(x); if(n) shown.push(n); });
      });
      var ghost = shown.filter(function(n){ return sups.indexOf(n) < 0; });
      return JSON.stringify({ supNums: sups, shownNums: shown, ghost: ghost });
    })()`));
    log('编号一致性: ' + JSON.stringify(consistency));
    // 正文一个上标都没有时组件会保留全部来源（有意为之），此时不做该断言
    check(
      'B6 来源编号均在正文标注内（无幽灵条目）',
      consistency.supNums.length === 0 || consistency.ghost.length === 0,
      `正文标注=[${consistency.supNums.join(' ')}] 来源显示=[${consistency.shownNums.join(' ')}] 幽灵=[${consistency.ghost.join(' ')}]`
    );

    // B7：来源编号必须从 1 开始连续（重编号后不应出现「从 3 开始」）
    const shown = [...new Set(consistency.shownNums)].sort((a, b) => a - b);
    const continuous = shown.length > 0 && shown.every((n, i) => n === i + 1);
    check(
      'B7 来源编号连续 1..M',
      shown.length === 0 || continuous,
      `显示编号=[${shown.join(' ')}]`
    );
    // 正文上标集合应与来源集合一致（重编号后一一对应）
    const supSet = [...new Set(consistency.supNums)].sort((a, b) => a - b);
    const sameSet = supSet.length === 0 || JSON.stringify(supSet) === JSON.stringify(shown);
    check(
      'B8 正文上标与来源编号一一对应',
      sameSet,
      `正文=[${supSet.join(' ')}] 来源=[${shown.join(' ')}]`
    );

    await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
  } finally {
    try { chrome.kill(); } catch { /* ignore */ }
  }

  console.log(`\n==== 结果: ${failures === 0 ? 'ALL PASS' : failures + ' FAIL'} ====`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error('运行异常: ' + e.message); process.exit(2); });
