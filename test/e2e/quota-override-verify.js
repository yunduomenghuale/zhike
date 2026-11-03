#!/usr/bin/env node
/** 配额页用户级覆盖 E2E（8092 真实环境）：表单存在 → 远程搜索 → 添加 → 刷新断言 → 删除还原 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9225;
const BASE = 'http://192.168.3.145:8092';
const PROFILE = 'D:/tmp/zhike-e2e/quota-override-profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let PASS = 0, FAIL = 0;
const check = (l, ok, d = '') => { ok ? PASS++ : FAIL++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${l}${d ? '  | ' + d : ''}`); };
class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { const p = this.pending.get(m.id); this.pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); }
      if (m.method === 'Network.requestWillBeSent' && m.params.request.url.includes('/admin-panel/ai-quota')) {
        console.log('NET>', m.params.request.method, (m.params.request.postData || '').slice(0, 110));
      }
      if (m.method === 'Network.responseReceived' && m.params.response.url.includes('/admin-panel/ai-quota')) {
        console.log('NET< status', m.params.response.status);
      }
      if (m.method === 'Runtime.exceptionThrown') {
        console.log('EXC>', (m.params.exceptionDetails?.exception?.description || '').slice(0, 160));
      }
    });
  }
  send(method, params = {}) {
    return new Promise((res, rej) => {
      const id = ++this.id; this.pending.set(id, { resolve: res, reject: rej });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
    });
  }
}
async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--no-first-run', '--window-size=1440,900'], { stdio: 'ignore' });
  await sleep(3500);
  const targets = await fetch(`http://127.0.0.1:${PORT}/json`).then((r) => r.json());
  const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable'); await cdp.send('Network.enable');
  const evalJs = async (expr) => {
    const r = await cdp.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 200));
    return r.result.value;
  };
  try {
    await evalJs(`localStorage.clear()`);
    await cdp.send('Page.navigate', { url: `${BASE}/login` });
    await sleep(2800);
    await evalJs(`(() => {
      document.querySelectorAll('input').forEach(i => {
        if (i.placeholder && i.placeholder.includes('用户名')) { i.value = 'test_admin'; i.dispatchEvent(new Event('input', { bubbles: true })); }
        if (i.type === 'password') { i.value = 'Test123456!'; i.dispatchEvent(new Event('input', { bubbles: true })); }
      });
      [...document.querySelectorAll('button')].find(x => x.textContent.includes('立即登录'))?.click();
      return 'ok';
    })()`);
    await sleep(3500);
    await cdp.send('Page.navigate', { url: `${BASE}/admin/ai-settings` });
    await sleep(3200);
    check('C1 配额区有添加覆盖表单', await evalJs(`!!document.querySelector('.quota-add')`));

    await evalJs(`document.querySelector('.quota-add-user .el-select__wrapper')?.click(); 'ok'`);
    await sleep(900);
    await cdp.send('Input.insertText', { text: 'T0001' });
    await sleep(2200);
    const opts = await evalJs(`[...document.querySelectorAll('.el-select-dropdown')].filter(d => d.offsetParent !== null).map(d => [...d.querySelectorAll('.el-select-dropdown__item')].map(o => o.textContent.trim())).flat()`);
    check('C2 远程搜索出用户', opts.some((t) => t.includes('T0001') || t.includes('张教授')), JSON.stringify(opts));
    await evalJs(`[...document.querySelectorAll('.el-select-dropdown')].filter(d => d.offsetParent !== null).map(d => [...d.querySelectorAll('.el-select-dropdown__item')].find(o => o.textContent.includes('T0001'))?.click()); 'ok'`);
    await sleep(700);

    await evalJs(`(() => { document.querySelector('.quota-add-num input')?.focus(); return 'ok'; })()`);
    await sleep(300);
    await cdp.send('Input.insertText', { text: '5' });
    await sleep(500);
    const btn = await evalJs(`(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === '添加覆盖'); return { exists: !!b, disabled: b ? b.disabled : null }; })()`);
    console.log('BTN', JSON.stringify(btn));
    await evalJs(`[...document.querySelectorAll('button')].find(x => x.textContent.trim() === '添加覆盖')?.click(); 'ok'`);
    await sleep(2500);

    await cdp.send('Page.navigate', { url: `${BASE}/admin/ai-settings` });
    await sleep(3500);
    const tags = await evalJs(`[...document.querySelectorAll('.quota-tag')].map(t => t.textContent.trim())`);
    check('C3 添加后覆盖 tag 出现', tags.some((t) => t.includes('5/日')), JSON.stringify(tags));

    await evalJs(`document.querySelector('.quota-tag .el-tag__close')?.click(); 'ok'`);
    await sleep(2500);
    await cdp.send('Page.navigate', { url: `${BASE}/admin/ai-settings` });
    await sleep(3500);
    const tagsAfter = await evalJs(`[...document.querySelectorAll('.quota-tag')].map(t => t.textContent.trim())`);
    check('C4 删除后覆盖清空', !tagsAfter.some((t) => t.includes('5/日')), JSON.stringify(tagsAfter));
    await cdp.send('Page.captureScreenshot', { format: 'png' }).then((r) => fs.writeFileSync(path.resolve(__dirname, '../screenshots/quota-override.png'), Buffer.from(r.data, 'base64')));
  } finally { ws.close(); chrome.kill(); }
  console.log(`\n===== ${PASS}/${PASS + FAIL} PASS =====`);
  process.exit(FAIL ? 1 : 0);
}
main().catch((e) => { console.error('E2E error:', e.message); process.exit(1); });
