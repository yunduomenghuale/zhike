#!/usr/bin/env node
/** 调试：查看试卷 hover 浮层是否真实显示 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const CHROME = 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9224;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-exam-dbg';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => { const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) { const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id); if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result); } }); }
  send(method, params = {}) { return new Promise((resolve, reject) => {
      const id = ++this.id; this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); } }, 30000); }); }
  async eval(expression) { const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value; }
  async navigate(url) { await this.send('Page.navigate', { url });
    for (let i = 0; i < 150; i++) { const ready = await this.eval('document.readyState').catch(() => null); if (ready === 'complete') break; await sleep(100); } await sleep(500); }
  async shot(name) { fs.mkdirSync(path.resolve(__dirname, '../../test/screenshots'), { recursive: true });
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.resolve(__dirname, '../../test/screenshots', name + '.png'), Buffer.from(r.data, 'base64')); }
}

async function waitFor(cdp, expr, timeout = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let ok = false; try { ok = await cdp.eval(expr); } catch { ok = false; }
    if (ok) return true; await sleep(200);
  }
  return false;
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  const chrome = spawn(CHROME, ['--headless=new','--no-proxy-server','--disable-gpu','--enable-unsafe-swiftshader','--use-angle=swiftshader','--no-first-run','--remote-debugging-port='+PORT,'--remote-allow-origins=*','--user-data-dir='+PROFILE,'--window-size=1440,900','about:blank'], { stdio: 'ignore' });
  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    try { const res = await fetch('http://127.0.0.1:' + PORT + '/json/list'); const list = await res.json();
      const page = list.find((t) => t.type === 'page'); if (page) { wsUrl = page.webSocketDebuggerUrl; break; } } catch {}
    await sleep(250);
  }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', () => reject(new Error('ws fail'))); });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  return { cdp, chrome };
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  try {
    await cdp.send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage' });
    await cdp.navigate(BASE + '/login');
    await waitFor(cdp, `!!document.querySelector('.split-auth__form-box--login .auth-submit')`, 15000);
    await cdp.eval(`(function(){
      function setVal(sel, v){ var el = document.querySelector(sel); if(!el) return;
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }
      setVal('.split-auth__form-box--login input[placeholder="请输入用户名"]', 't101');
      setVal('.split-auth__form-box--login input[placeholder="请输入密码"]', 'pass1234');
      document.querySelector('.split-auth__form-box--login .auth-submit').click();
    })()`);
    await waitFor(cdp, `location.pathname === '/dashboard' || location.pathname === '/'`, 30000);
    await cdp.navigate(BASE + '/teacher/exams');
    await waitFor(cdp, `document.querySelectorAll('.exam-list-card').length > 0`, 20000);

    // 打开第一个已发布考试的查看试卷
    await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.exam-list-card'));
      var card = cards.find(function(c){ return c.textContent.includes('已发布'); });
      var btn = Array.from(card.querySelectorAll('.el-button')).find(function(b){ return b.textContent.trim() === '查看试卷'; });
      btn.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.exam-paper-dialog .paper-q-stem')`, 15000);
    await sleep(1000);

    const box = await cdp.eval(`(function(){
      var el = document.querySelector('.exam-paper-dialog .paper-q-stem');
      var r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), text: el.textContent.trim().slice(0,20) };
    })()`);
    console.log('stem box:', JSON.stringify(box));

    // 方式1：CDP 真实鼠标移动
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
    for (let i = 0; i < 8; i++) {
      await sleep(300);
      const st = await cdp.eval(`(function(){
        var p = document.querySelector('.question-detail-popper');
        if (!p) return 'NO_ELEMENT';
        var cs = getComputedStyle(p);
        var r = p.getBoundingClientRect();
        return 'display=' + cs.display + ' vis=' + cs.visibility + ' op=' + cs.opacity + ' rect=' + Math.round(r.x) + ',' + Math.round(r.y) + ',' + Math.round(r.width) + 'x' + Math.round(r.height) + ' z=' + cs.zIndex;
      })()`);
      console.log('t+' + ((i + 1) * 300) + 'ms:', st);
      if (st !== 'NO_ELEMENT' && !st.startsWith('display=none')) break;
    }
    await cdp.shot('exam-dbg-hover');
    console.log('screenshot saved');
  } finally { chrome.kill(); }
}
run().catch((e) => { console.error('debug fail:', e); process.exit(1); });
