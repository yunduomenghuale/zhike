#!/usr/bin/env node
/**
 * 管理端「大模型配置」页重排序卡片验证（AdminAISettings.vue 增加 rerank 能力后）
 *
 * 验证点：
 * 1. 页面加载出 4 张能力卡片（对话/向量/重排序/语音），重排序卡片在列；
 * 2. 重排序卡片：服务商下拉为 通义千问 + 系统内置模型、模型默认 gte-rerank-v2、启用开关可用；
 * 3. 生效配置表 4 行，重排序行显示 通义千问 · gte-rerank-v2 · 管理端配置（非 Mock）；
 * 4. 顶部运行时徽标为「4/4 项能力已对接真实模型」；
 * 5. 无 JS 异常；截图留证。
 *
 * 前置：后端 8005、前端 5273 已启动；dev 库 admin=A0987654；
 *       rerank 已保存为数据库配置（provider=tongyi, model=gte-rerank-v2）。
 * 运行：node test/e2e/admin-ai-settings-rerank-verify.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = 9223;
const BASE = 'http://localhost:5273';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-admin';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');

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
  if (!ok) throw new Error('登录失败或未跳转工作台: ' + username);
}

async function launchChrome() {
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch { /* 复用旧 profile */ }
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-proxy-server', '--disable-gpu',
    '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE, '--window-size=1440,1000', 'about:blank',
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
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
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
    await login(cdp, 'admin', 'A0987654');

    await cdp.navigate(BASE + '/admin/ai-settings');
    const pageOk = await waitFor(cdp, `document.body.innerText.includes('大模型配置')`, 15000);
    check('A1 进入管理端大模型配置页', pageOk, await cdp.eval('location.pathname'));

    // 1. 四张能力卡片
    const cardsOk = await waitFor(cdp, `document.querySelectorAll('.config-card').length === 4`, 15000);
    check('A2 能力卡片共 4 张（对话/向量/重排序/语音）', cardsOk,
      cardsOk ? '4 cards' : 'cards=' + await cdp.eval('document.querySelectorAll(".config-card").length'));

    const titles = await cdp.eval(`Array.from(document.querySelectorAll('.config-card .card-title h2')).map(function(h){return h.textContent.trim()})`);
    check('A3 卡片顺序含「重排序」', JSON.stringify(titles) === JSON.stringify(['对话生成', '向量化', '重排序', '语音合成']), JSON.stringify(titles));

    // 2. 重排序卡片明细
    const rerankCard = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      if (!card) return null;
      var desc = card.querySelector('.card-title p').textContent.trim();
      var items = Array.from(card.querySelectorAll('.el-form-item'));
      var modelItem = items.find(function(i){ return i.textContent.includes('重排序模型'); });
      var modelInput = modelItem ? modelItem.querySelector('input') : null;
      // 选中值渲染在 .el-select__placeholder（另有隐藏的 input wrapper 也带 selected-item class，取文本非空者）
      var selected = Array.from(card.querySelectorAll('.el-select__selected-item')).filter(function(el){ return el.textContent.trim(); })[0];
      return {
        desc: desc,
        model: modelInput ? modelInput.value : null,
        providerText: selected ? selected.textContent.trim() : '',
        switchExists: !!card.querySelector('.el-switch'),
      };
    })()`);
    check('A4 重排序卡片存在且描述说明用途', !!rerankCard && (rerankCard.desc.includes('精排') || rerankCard.desc.includes('噪声')), rerankCard && rerankCard.desc);
    check('A5 重排序模型默认 gte-rerank-v2', !!rerankCard && rerankCard.model === 'gte-rerank-v2', rerankCard && rerankCard.model);
    check('A6 重排序服务商显示通义千问', !!rerankCard && rerankCard.providerText.includes('通义千问'), rerankCard && rerankCard.providerText);
    check('A7 重排序卡片有启用开关', !!rerankCard && rerankCard.switchExists);

    // 服务商下拉仅通义千问一项（白名单收窄）。
    // 选项 popper 常驻 DOM（display:none），经 input 的 aria-controls 精准定位该 select 的 popper，
    // 避免误取其他卡片的下拉；再模拟 mousedown/mouseup/click 真点开验证可见性。
    const options = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var input = card.querySelector('.el-select__input');
      var popper = input && input.getAttribute('aria-controls') ? document.getElementById(input.getAttribute('aria-controls')) : null;
      if (!popper) return null;
      return Array.from(popper.querySelectorAll('.el-select-dropdown__item')).map(function(o){return o.textContent.trim()});
    })()`);
    check('A8 重排序服务商下拉为「通义千问 + 系统内置模型」', !!options && JSON.stringify(options) === JSON.stringify(['通义千问', '系统内置模型']), JSON.stringify(options));

    const opened = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var input = card.querySelector('.el-select__input');
      var popper = input && input.getAttribute('aria-controls') ? document.getElementById(input.getAttribute('aria-controls')) : null;
      if (!popper) return 'no-popper';
      var wrapper = card.querySelector('.el-select__wrapper');
      wrapper.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      wrapper.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      wrapper.click();
      return new Promise(function(res){ setTimeout(function(){
        res(getComputedStyle(popper).display !== 'none' ? 'visible' : 'hidden');
      }, 600); });
    })()`);
    check('A9 点击后下拉真实展开（白名单交互正常）', opened === 'visible', opened);
    await sleep(300);

    // 下拉保持展开中，真实点击「系统内置模型」选项，验证 local 表单联动：
    // 接口地址/API Key 禁用、模型预填 Qwen3-Reranker、出现「无需接口地址与 Key」提示
    const localRect = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var input = card.querySelector('.el-select__input');
      var popper = document.getElementById(input.getAttribute('aria-controls'));
      var item = Array.from(popper.querySelectorAll('.el-select-dropdown__item')).find(function(o){ return o.textContent.includes('系统内置模型'); });
      if (!item) return null;
      var r = item.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    check('A9b 下拉中存在「系统内置模型」选项', !!localRect, JSON.stringify(localRect));
    if (localRect) {
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: Math.round(localRect.x), y: Math.round(localRect.y), button: 'left', clickCount: 1 });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: Math.round(localRect.x), y: Math.round(localRect.y), button: 'left', clickCount: 1 });
      await sleep(500);
    }
    const localState = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      function field(label){
        var item = Array.from(card.querySelectorAll('.el-form-item')).find(function(f){
          var l = f.querySelector('.el-form-item__label');
          return l && l.textContent.trim().indexOf(label) === 0;
        });
        if (!item) return null;
        var input = item.querySelector('input');
        return { disabled: input ? input.disabled : null, value: input ? input.value : '' };
      }
      return {
        url: field('接口地址'),
        model: field('重排序模型'),
        key: field('API Key'),
        note: card.textContent.includes('无需接口地址与 Key'),
      };
    })()`);
    check('A9c 选系统内置模型后接口地址禁用且清空', !!localState && localState.url && localState.url.disabled === true && localState.url.value === '', JSON.stringify(localState && localState.url));
    check('A9d 模型预填 Qwen/Qwen3-Reranker-0.6B', !!localState && localState.model && localState.model.value === 'Qwen/Qwen3-Reranker-0.6B', JSON.stringify(localState && localState.model));
    check('A9e API Key 禁用', !!localState && localState.key && localState.key.disabled === true, JSON.stringify(localState && localState.key));
    check('A9f 卡片出现「无需接口地址与 Key」提示', !!localState && localState.note === true, String(localState && localState.note));

    // 切回「通义千问」（不保存，仅还原表单，保证后续生效表断言与截图不受脏表单干扰）
    const selRect = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var r = card.querySelector('.el-select__wrapper').getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: Math.round(selRect.x), y: Math.round(selRect.y), button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: Math.round(selRect.x), y: Math.round(selRect.y), button: 'left', clickCount: 1 });
    await sleep(500);
    const tongyiRect = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var input = card.querySelector('.el-select__input');
      var popper = document.getElementById(input.getAttribute('aria-controls'));
      var item = Array.from(popper.querySelectorAll('.el-select-dropdown__item')).find(function(o){ return o.textContent.trim() === '通义千问'; });
      if (!item) return null;
      var r = item.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    if (tongyiRect) {
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: Math.round(tongyiRect.x), y: Math.round(tongyiRect.y), button: 'left', clickCount: 1 });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: Math.round(tongyiRect.x), y: Math.round(tongyiRect.y), button: 'left', clickCount: 1 });
      await sleep(500);
    }
    const backState = await cdp.eval(`(function(){
      var cards = Array.from(document.querySelectorAll('.config-card'));
      var card = cards.find(function(c){ return c.querySelector('.card-title h2').textContent.includes('重排序'); });
      var item = Array.from(card.querySelectorAll('.el-form-item')).find(function(f){
        var l = f.querySelector('.el-form-item__label');
        return l && l.textContent.trim().indexOf('重排序模型') === 0;
      });
      var input = item && item.querySelector('input');
      return input ? input.value : '';
    })()`);
    check('A9g 切回通义千问后模型恢复 gte-rerank-v2', backState === 'gte-rerank-v2', backState);

    // 收起下拉：合成事件 el-select 不买账，用 CDP 真实鼠标点击页面头部空白处
    // （outside-click 监听 mousedown，必须真实事件流才触发）
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 720, y: 55, button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 720, y: 55, button: 'left', clickCount: 1 });
    await sleep(500);
    // 布局滚动发生在内部容器（非 window）：把所有可滚动容器都置顶，
    // 保证截图覆盖「页头 + 生效配置表 + 四张卡片」全貌
    await cdp.eval(`(function(){
      window.scrollTo(0, 0);
      Array.from(document.querySelectorAll('*')).forEach(function(el){
        if (el.scrollHeight > el.clientHeight + 50 && getComputedStyle(el).overflowY !== 'visible') {
          el.scrollTop = 0;
        }
      });
    })()`);
    await sleep(500);

    // 3. 生效配置表
    const tableOk = await waitFor(cdp, `document.querySelectorAll('.effective-table .el-table__row').length === 4`, 10000);
    check('A10 生效配置表 4 行', tableOk);
    const rerankRow = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.effective-table .el-table__row'));
      var row = rows.find(function(r){ return r.textContent.includes('重排序'); });
      if (!row) return null;
      var cells = Array.from(row.querySelectorAll('.el-table__cell')).map(function(c){return c.textContent.replace(/\\s+/g,' ').trim()});
      return cells;
    })()`);
    const rowText = rerankRow ? rerankRow.join(' | ') : '';
    check('A11 生效表重排序行：通义千问 · gte-rerank-v2', !!rerankRow && rowText.includes('通义千问') && rowText.includes('gte-rerank-v2'), rowText);
    check('A12 生效表重排序行：来源=管理端配置（非 Mock 运行时）', !!rerankRow && rowText.includes('管理端配置') && !rowText.includes('模拟模式'), rowText);

    // 4. 顶部徽标
    const badge = await cdp.eval(`(document.querySelector('.runtime-badge')||{textContent:''}).textContent.replace(/\\s+/g,' ').trim()`);
    check('A13 运行时徽标 4/4 真实模型', badge.includes('4/4') && badge.includes('真实模型'), badge);

    // 5. 无 JS 异常 + 截图
    check('A14 无 JS 异常', cdp.exceptions.length === 0, cdp.exceptions.slice(0, 2).join(' ; ') || 'clean');
    const shot = await cdp.shot('admin-ai-settings-rerank');
    check('A15 截图留证', !!shot, shot);
  } finally {
    chrome.kill();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项：');
    failed.forEach((f) => console.log('  - ' + f.name));
    process.exit(1);
  }
}

run().catch((err) => {
  console.error('E2E 执行异常：', err);
  process.exit(1);
});
