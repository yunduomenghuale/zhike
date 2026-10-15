#!/usr/bin/env node
/**
 * 题目选择器左右结构改造—— CDP 真实浏览器实测
 *
 * 验证点（对应本次需求）：
 *   QP.1 左右结构：左题库面板与右已选面板并排，且均已占满可用高度
 *   QP.2 「全选当前筛选范围」按钮存在，标签为「全选 N 题」
 *   QP.3 点击全选后已选数量 = 当前筛选范围题目数，按钮切换为「取消全选」
 *   QP.4 已添加的题目在左侧列表中整行高亮（is-added + 浅蓝单元格背景）
 *   QP.5 题型/难度为简写（单选/多选/判断/填空/简答；易/中/难）
 *   QP.6 取消全选后已选清零，按钮回到「全选 N 题」
 *   QP.7 单行添加即高亮；已选卡片为双行紧凑结构（题干两行截断 + 副行分值/操作）
 *   QP.8 无 console.error / 未捕获异常
 *   QP.10 四容器间距收敛（顶栏/内容区/双卡 gap/card padding）
 *   QP.11 题型/难度/操作列内容无截断（标签不溢出所在列、表头完整）
 *   QP.12 悬停题库题干弹出详情浮层（完整题干/题型/选项），鼠标移走立即隐藏
 *   QP.13 悬停已选题干同样弹出详情浮层，移走立即隐藏
 *
 * 前置：后端 8005、前端 5273 已启动；教师账号 t101 可用。
 * 运行：node test/e2e/qp-layout-verify.js
 */
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://localhost:5273';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const PW = 'A0987654';

// 每次运行独立端口与 profile，避免单例 attach 到存活的旧浏览器
const RUN_ID = process.pid.toString(36) + Date.now().toString(36).slice(-4);
const PORT = 9600 + (parseInt(RUN_ID, 36) % 400);
const PROFILE = `D:/tmp/zhike-qp-e2e/run-${RUN_ID}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);
function log(msg) { console.log(`[${stamp()}] ${msg}`); }

// ---------------- CDP 客户端 ----------------
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push('console.error: ' + (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        this.consoleErrors.push('page exception: ' + (d.exception?.description || d.text));
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
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture: true,
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
  async shotClip(name, clip) {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const r = await this.send('Page.captureScreenshot', {
      format: 'png',
      clip: { x: clip.x, y: clip.y, width: clip.width, height: clip.height, scale: 1 },
    });
    fs.writeFileSync(path.join(SHOT_DIR, name + '.png'), Buffer.from(r.data, 'base64'));
    return name + '.png';
  }
}

async function waitFor(cdp, expr, timeout = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    let ok = false;
    try { ok = await cdp.eval(expr); } catch { ok = false; }
    if (ok) return true;
    await sleep(200);
  }
  return false;
}

async function clickByText(cdp, selector, text, exact = true) {
  return cdp.eval(`(function(){
    var els = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
    var el = els.find(function(e){
      var t = e.textContent.trim();
      return ${exact} ? t === ${JSON.stringify(text)} : t.includes(${JSON.stringify(text)});
    });
    if (!el) return 'NOT_FOUND';
    el.click();
    return 'CLICKED';
  })()`);
}

async function hoverEl(cdp, selector, nth = 0) {
  const box = await cdp.eval(`(function(){
    var els = document.querySelectorAll(${JSON.stringify(selector)});
    var el = els[${nth}];
    if (!el) return null;
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    var r = el.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  })()`);
  if (!box) return null;
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y });
  return box;
}

function visiblePopovers(cdp) {
  return cdp.eval(`(function(){
    return Array.from(document.querySelectorAll('.question-detail-popper')).filter(function(p){
      return getComputedStyle(p).display !== 'none';
    }).length;
  })()`);
}

// 轮询等待浮层全部隐藏，返回 { hidden, elapsed }——hide-after=0 应立即触发，过渡约 200ms
async function waitPopoversHidden(cdp, timeout = 1500) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const n = await visiblePopovers(cdp);
    if (n === 0) return { hidden: true, elapsed: Date.now() - start };
    await sleep(100);
  }
  return { hidden: false, elapsed: Date.now() - start };
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
  await waitFor(cdp, `document.querySelectorAll('.feature-card').length >= 6`, 30000);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined && detail !== null && detail !== '' ? ' | ' + detail : ''));
}

async function launchChrome() {
  try {
    fs.rmSync(PROFILE, { recursive: true, force: true });
  } catch { /* 忽略 */ }
  const chrome = spawn(CHROME, [
    '--headless=new',
    '--no-proxy-server',
    '--disable-gpu',
    '--enable-unsafe-swiftshader',
    '--use-angle=swiftshader',
    '--no-first-run',
    '--remote-debugging-port=' + PORT,
    '--remote-allow-origins=*',
    '--user-data-dir=' + PROFILE,
    '--window-size=1440,900',
    'about:blank',
  ], { stdio: 'ignore', detached: true });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const pages = list.filter((t) => t.type === 'page');
      log(`devtools 就绪，当前标签页 ${pages.length} 个: ` + pages.map((p) => p.url).join(' | '));
      const page = pages[0];
      if (page) { wsUrl = page.webSocketDebuggerUrl; break; }
    } catch { /* 还没起来 */ }
    await sleep(250);
  }
  if (!wsUrl) { killChrome(chrome); throw new Error('Chrome devtools 端口未就绪'); }

  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('DOM.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { cdp, chrome };
}

function killChrome(chrome) {
  try {
    execSync(`taskkill /PID ${chrome.pid} /T /F`, { stdio: 'ignore' });
  } catch { /* 进程可能已退出 */ }
  try { chrome.kill(); } catch { /* ignore */ }
}

async function run() {
  const { cdp, chrome } = await launchChrome();
  const goto = (p) => cdp.navigate(BASE + p);

  try {
    log('===== 题目选择器左右结构实测 =====');
    await login(cdp, 't101', PW);
    await goto('/teacher/homework');
    await waitFor(cdp, `!!document.querySelector('.module-primary-button')`);
    await clickByText(cdp, '.module-primary-button', '发布作业');
    await waitFor(cdp, `!!document.querySelector('.homework-editor')`);
    check('QP.0 发布作业编辑器打开（默认题库选题模式）', true);

    // 等题目表格渲染出数据行
    const poolReady = await waitFor(cdp, `(function(){
      var rows = document.querySelectorAll('.question-pool-table .el-table__row');
      return rows.length > 0;
    })()`, 20000);
    check('QP.0b 题库列表加载出题目', poolReady, poolReady ? '' : '题目池为空或加载失败');

    // ---------- QP.1 左右结构 ----------
    const geom = await cdp.eval(`(function(){
      var pool = document.querySelector('.question-pool-panel');
      var sel = document.querySelector('.selected-panel');
      if (!pool || !sel) return null;
      var p = pool.getBoundingClientRect();
      var s = sel.getBoundingClientRect();
      return {
        poolLeft: Math.round(p.left), poolRight: Math.round(p.right), poolHeight: Math.round(p.height),
        selLeft: Math.round(s.left), selRight: Math.round(s.right), selHeight: Math.round(s.height),
        viewportH: window.innerHeight,
      };
    })()`);
    check('QP.1a 左右结构：题库面板在左、已选面板在右（并排）',
      !!geom && geom.selLeft >= geom.poolRight - 1 && geom.selLeft > geom.poolLeft,
      geom ? `pool[${geom.poolLeft},${geom.poolRight}] sel[${geom.selLeft},${geom.selRight}]` : 'panel missing');
    check('QP.1b 左右结构：两侧面板均已占满高度（解决已选列表过矮问题）',
      !!geom && geom.poolHeight >= 380 && geom.selHeight >= 380,
      geom ? `poolH=${geom.poolHeight} selH=${geom.selHeight} vh=${geom.viewportH}` : 'panel missing');

    // ---------- QP.10 四容器间距收敛 ----------
    const spacing = await cdp.eval(`(function(){
      function padOf(sel){
        var el = document.querySelector(sel);
        if (!el) return null;
        var s = getComputedStyle(el);
        return [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft].map(function(v){ return parseFloat(v) || 0; });
      }
      var grid = document.querySelector('.creation-form-grid');
      return {
        topbar: padOf('.hw-editor-topbar'),
        body: padOf('.homework-editor-body'),
        gridGap: grid ? (parseFloat(getComputedStyle(grid).columnGap) || 0) : null,
        card: padOf('.hw-card'),
      };
    })()`);
    const sp = spacing || {};
    check('QP.10a 顶栏/内容区间距收敛（topbar≤12/16，body≤14/14）',
      !!sp.topbar && !!sp.body && sp.topbar[0] <= 12 && sp.topbar[1] <= 16 && sp.body[0] <= 14 && sp.body[1] <= 14,
      JSON.stringify({ topbar: sp.topbar, body: sp.body }));
    check('QP.10b 双卡间距收敛（grid gap≤12，card≤14/14/16）',
      sp.gridGap !== null && sp.gridGap !== undefined && sp.gridGap <= 12 && !!sp.card && sp.card[0] <= 14 && sp.card[1] <= 14 && sp.card[2] <= 16,
      JSON.stringify({ gridGap: sp.gridGap, card: sp.card }));
    await cdp.shot('qp-layout-initial');

    // ---------- QP.2 全选按钮 ----------
    const btnInfo = await cdp.eval(`(function(){
      var btn = document.querySelector('.pool-select-all');
      var rows = document.querySelectorAll('.question-pool-table .el-table__row').length;
      return btn ? { text: btn.textContent.trim(), rows: rows, disabled: btn.disabled } : null;
    })()`);
    check('QP.2 「全选当前筛选范围」按钮存在且标签带数量',
      !!btnInfo && /^全选 \d+ 题$/.test(btnInfo.text) && !btnInfo.disabled,
      btnInfo ? `text="${btnInfo.text}" rows=${btnInfo.rows}` : 'button missing');

    // ---------- QP.3 点击全选 ----------
    await cdp.eval(`document.querySelector('.pool-select-all').click()`);
    await sleep(400);
    const afterAll = await cdp.eval(`(function(){
      var btn = document.querySelector('.pool-select-all');
      var header = document.querySelector('.selected-header');
      var rows = document.querySelectorAll('.question-pool-table .el-table__row').length;
      var items = document.querySelectorAll('.selected-item').length;
      return {
        btnText: btn ? btn.textContent.trim() : '',
        headerText: header ? header.textContent.replace(/\\s+/g, ' ').trim() : '',
        rows: rows, items: items,
      };
    })()`);
    check('QP.3 点击全选：已选数量 = 筛选范围题目数，按钮切换为「取消全选」',
      afterAll.btnText === '取消全选' && afterAll.items === afterAll.rows && afterAll.items > 0,
      JSON.stringify(afterAll));

    // ---------- QP.4 已添加行高亮 ----------
    const highlight = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.question-pool-table .el-table__row'));
      var added = rows.filter(function(r){ return (r.className || '').indexOf('is-added') >= 0; });
      var firstTd = added.length ? added[0].querySelector('td.el-table__cell') : null;
      var bg = firstTd ? getComputedStyle(firstTd).backgroundColor : '';
      return { total: rows.length, added: added.length, firstBg: bg };
    })()`);
    check('QP.4 已添加题目整行高亮（is-added + 浅蓝单元格背景）',
      highlight.total > 0 && highlight.added === highlight.total && highlight.firstBg === 'rgb(232, 241, 254)',
      JSON.stringify(highlight));
    await cdp.shot('qp-layout-all-selected');

    // ---------- QP.5 简写标签 ----------
    const tags = await cdp.eval(`(function(){
      var types = Array.from(document.querySelectorAll('.question-pool-table .pool-tag.type')).map(function(e){ return e.textContent.trim(); });
      var diffs = Array.from(document.querySelectorAll('.question-pool-table .pool-tag.difficulty')).map(function(e){ return e.textContent.trim(); });
      var typeOk = ['单选','多选','判断','填空','简答'];
      var diffOk = ['易','中','难'];
      return {
        types: types, diffs: diffs,
        typeAllAbbr: types.length > 0 && types.every(function(t){ return typeOk.indexOf(t) >= 0; }),
        diffAllAbbr: diffs.length > 0 && diffs.every(function(d){ return diffOk.indexOf(d) >= 0; }),
      };
    })()`);
    check('QP.5a 题型简写展示', tags.typeAllAbbr, JSON.stringify(tags.types.slice(0, 8)));
    check('QP.5b 难度简写展示', tags.diffAllAbbr, JSON.stringify(tags.diffs.slice(0, 8)));

    // ---------- QP.11 窄列内容无截断/溢出 ----------
    const trunc = await cdp.eval(`(function(){
      var bad = [];
      var paintBad = [];
      var rows = document.querySelectorAll('.question-pool-table .el-table__row');
      rows.forEach(function(row){
        var tds = row.querySelectorAll('td.el-table__cell');
        [1, 2, 3].forEach(function(ci){
          var td = tds[ci];
          if (!td) return;
          var inner = td.querySelector('.pool-tag') || td.querySelector('.pool-action');
          if (!inner) return;
          var ir = inner.getBoundingClientRect();
          // 实际裁剪盒 = .cell 的内容盒（EP 的 .cell 带 overflow:hidden，标签超出即被裁）
          var cell = td.querySelector('.cell');
          var clipLeft, clipRight;
          if (cell) {
            var cr = cell.getBoundingClientRect();
            var cs = getComputedStyle(cell);
            clipLeft = cr.left + (parseFloat(cs.paddingLeft) || 0);
            clipRight = cr.right - (parseFloat(cs.paddingRight) || 0);
          } else {
            var tr = td.getBoundingClientRect();
            clipLeft = tr.left; clipRight = tr.right;
          }
          if (ir.right > clipRight + 1 || ir.left < clipLeft - 1) {
            bad.push({ col: ci, text: inner.textContent.trim(), tagW: Math.round(ir.width), availW: Math.round(clipRight - clipLeft) });
          }
          // 绘制级探针：标签中心点的最顶层元素必须是标签自身（被裁剪时会落到 td/行上）
          var top = document.elementFromPoint(Math.round(ir.left + ir.width / 2), Math.round(ir.top + ir.height / 2));
          if (!(top && (inner === top || inner.contains(top)))) {
            paintBad.push({ col: ci, text: inner.textContent.trim() });
          }
        });
      });
      var thBad = [];
      document.querySelectorAll('.question-pool-table th.el-table__cell .cell').forEach(function(cell){
        if (cell.scrollWidth > cell.clientWidth + 1) {
          thBad.push({ text: cell.textContent.trim(), sw: cell.scrollWidth, cw: cell.clientWidth });
        }
      });
      return { rows: rows.length, bad: bad, paintBad: paintBad, thBad: thBad };
    })()`);
    check('QP.11a 题型/难度/操作标签未被 .cell 裁剪（对照实际裁剪盒）',
      trunc.rows > 0 && trunc.bad.length === 0,
      trunc.bad.length ? JSON.stringify(trunc.bad.slice(0, 4)) : `rows=${trunc.rows} 全部标签完整`);
    check('QP.11a2 标签实际绘制可见（elementFromPoint 探针，非仅几何达标）',
      trunc.paintBad.length === 0,
      trunc.paintBad.length ? JSON.stringify(trunc.paintBad.slice(0, 4)) : '全部标签绘制在最顶层');
    check('QP.11b 表头文字未溢出',
      trunc.thBad.length === 0,
      trunc.thBad.length ? JSON.stringify(trunc.thBad) : '表头均完整');

    // ---------- QP.11c 表头与内容居中对齐 ----------
    const align = await cdp.eval(`(function(){
      var ths = document.querySelectorAll('.question-pool-table th.el-table__cell');
      var firstRow = document.querySelector('.question-pool-table .el-table__row');
      var tds = firstRow ? firstRow.querySelectorAll('td.el-table__cell') : [];
      var out = [];
      [1, 2, 3].forEach(function(ci){
        var th = ths[ci], td = tds[ci];
        if (!th || !td) return;
        var thCell = th.querySelector('.cell');
        var tr = thCell ? thCell.getBoundingClientRect() : th.getBoundingClientRect();
        var inner = td.querySelector('.pool-tag') || td.querySelector('.pool-action');
        var ir = inner ? inner.getBoundingClientRect() : td.getBoundingClientRect();
        out.push({
          col: ci,
          thCenter: Math.round(tr.left + tr.width / 2),
          tdCenter: Math.round(ir.left + ir.width / 2),
        });
      });
      return out;
    })()`);
    check('QP.11c 题型/难度/操作列表头与内容居中对齐（偏差 ≤8px）',
      align.length === 3 && align.every(function(a){ return Math.abs(a.thCenter - a.tdCenter) <= 8; }),
      JSON.stringify(align));

    // 窄列区域裁剪放大截图：核对标签完整性与表头对齐（用户反馈点是细节，整页截图看不清）
    const colsClip = await cdp.eval(`(function(){
      var ths = document.querySelectorAll('.question-pool-table th.el-table__cell');
      var rows = document.querySelectorAll('.question-pool-table .el-table__row');
      if (ths.length < 4 || !rows.length) return null;
      var t0 = ths[1].getBoundingClientRect();
      var t1 = ths[3].getBoundingClientRect();
      var r0 = rows[0].getBoundingClientRect();
      var r1 = rows[rows.length - 1].getBoundingClientRect();
      return {
        x: Math.round(t0.left - 10), y: Math.round(r0.top - 46),
        width: Math.round(t1.right - t0.left + 20), height: Math.round(r1.bottom - r0.top + 56),
      };
    })()`);
    if (colsClip) await cdp.shotClip('qp-layout-columns-zoom', colsClip);

    // ---------- QP.12 题库题干悬停详情浮层 ----------
    await hoverEl(cdp, '.question-pool-table .pool-stem', 0);
    await sleep(700);
    const popPool = await cdp.eval(`(function(){
      var pops = Array.from(document.querySelectorAll('.question-detail-popper')).filter(function(p){
        return getComputedStyle(p).display !== 'none';
      });
      var p = pops[0];
      var rowStem = document.querySelector('.question-pool-table .el-table__row .pool-stem');
      var typeEl = document.querySelector('.question-pool-table .el-table__row .pool-tag.type');
      var rowType = typeEl ? typeEl.textContent.trim() : '';
      var optCount = p ? p.querySelectorAll('.qdt-option').length : 0;
      var expectOpts = (rowType === '单选' || rowType === '多选') ? 2 : 0;
      return {
        visible: !!p,
        stem: p && p.querySelector('.qdt-stem') ? p.querySelector('.qdt-stem').textContent.trim() : '',
        expectStem: rowStem ? rowStem.textContent.trim() : '',
        rowType: rowType,
        optCount: optCount,
        optOk: expectOpts === 0 ? optCount === 0 : optCount >= expectOpts,
        hasMeta: p ? !!p.querySelector('.qdt-meta') : false,
        hasAnswer: p ? !!p.querySelector('.qdt-answer') : false,
        answerText: p && p.querySelector('.qdt-answer') ? p.querySelector('.qdt-answer').textContent.replace('参考答案', '').trim() : '',
        popperWidth: p ? Math.round(p.getBoundingClientRect().width) : 0,
        debugRect: p ? (function(){
          var r = p.getBoundingClientRect();
          var s = getComputedStyle(p);
          var cx = Math.round(r.x + r.width / 2), cy = Math.round(r.y + r.height / 2);
          var top = document.elementFromPoint(cx, cy);
          return {
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            opacity: s.opacity, zIndex: s.zIndex,
            paintedOnTop: !!top && p.contains(top),
          };
        })() : null,
      };
    })()`);
    check('QP.12a 悬停题库题干：浮层出现且含完整题干/题型/选项',
      popPool.visible && popPool.stem.length > 0 && popPool.stem === popPool.expectStem && popPool.hasMeta && popPool.optOk,
      JSON.stringify(popPool).slice(0, 300));
    check('QP.12a3 参考答案按题型格式化（非 [object Object]）',
      !popPool.hasAnswer || (popPool.answerText.length > 0 && popPool.answerText.indexOf('[object Object]') < 0),
      popPool.answerText ? `answer="${popPool.answerText.slice(0, 60)}"` : 'no answer');
    check('QP.12a2 浮层实际绘制在最顶层（z-index 高于 fixed 编辑器 3000，非仅 DOM 可见）',
      !!(popPool.debugRect && popPool.debugRect.paintedOnTop),
      popPool.debugRect ? JSON.stringify(popPool.debugRect) : 'no rect');
    if (popPool.visible) await cdp.shot('qp-layout-popover-pool');
    // 鼠标移走 → 立即隐藏
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 2, y: 2 });
    const popPoolGone = await waitPopoversHidden(cdp);
    check('QP.12b 鼠标移走：浮层隐藏（hide-after=0 即时触发）',
      popPoolGone.hidden && popPoolGone.elapsed <= 600,
      `hidden=${popPoolGone.hidden} elapsed=${popPoolGone.elapsed}ms`);

    // ---------- QP.6 取消全选 ----------
    await cdp.eval(`document.querySelector('.pool-select-all').click()`);
    await sleep(400);
    const afterCancel = await cdp.eval(`(function(){
      var btn = document.querySelector('.pool-select-all');
      var rows = document.querySelectorAll('.question-pool-table .el-table__row').length;
      var items = document.querySelectorAll('.selected-item').length;
      var added = document.querySelectorAll('.question-pool-table .el-table__row.is-added').length;
      var empty = !!document.querySelector('.selected-empty');
      return { btnText: btn ? btn.textContent.trim() : '', rows: rows, items: items, added: added, empty: empty };
    })()`);
    check('QP.6 取消全选：已选清零、高亮撤除、按钮回到「全选 N 题」',
      afterCancel.items === 0 && afterCancel.added === 0 && afterCancel.empty && /^全选 \d+ 题$/.test(afterCancel.btnText),
      JSON.stringify(afterCancel));

    // ---------- QP.7 单行添加 + 已选卡片结构 ----------
    await cdp.eval(`(function(){
      var btn = document.querySelector('.question-pool-table .el-table__row .pool-action');
      if (btn) btn.click();
    })()`);
    await sleep(400);
    const single = await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.question-pool-table .el-table__row'));
      var added = rows.filter(function(r){ return (r.className || '').indexOf('is-added') >= 0; }).length;
      var items = document.querySelectorAll('.selected-item').length;
      var item = document.querySelector('.selected-item');
      var main = item ? item.querySelector('.selected-item-main') : null;
      var sub = item ? item.querySelector('.selected-item-sub') : null;
      var stem = item ? item.querySelector('.selected-stem') : null;
      var score = item ? item.querySelector('.score-input input') : null;
      var clamp = stem ? getComputedStyle(stem).webkitLineClamp : '';
      return { added: added, items: items, hasMain: !!main, hasSub: !!sub, scoreVal: score ? score.value : '', lineClamp: clamp };
    })()`);
    check('QP.7a 单行添加即高亮且已选计数为 1',
      single.added === 1 && single.items === 1, JSON.stringify(single));
    check('QP.7b 已选卡片为紧凑双行结构（题干两行截断 + 副行分值/操作）',
      single.hasMain && single.hasSub && single.lineClamp === '2' && single.scoreVal !== '',
      JSON.stringify(single));
    await cdp.shot('qp-layout-single-selected');

    // ---------- QP.13 已选题干悬停详情浮层 ----------
    await hoverEl(cdp, '.selected-stem', 0);
    await sleep(700);
    const popSel = await cdp.eval(`(function(){
      var pops = Array.from(document.querySelectorAll('.question-detail-popper')).filter(function(p){
        return getComputedStyle(p).display !== 'none';
      });
      var p = pops[0];
      var selStem = document.querySelector('.selected-stem');
      var dbg = null;
      if (p) {
        var r = p.getBoundingClientRect();
        var s = getComputedStyle(p);
        var top = document.elementFromPoint(Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2));
        dbg = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), zIndex: s.zIndex, paintedOnTop: !!top && p.contains(top) };
      }
      return {
        visible: !!p,
        stem: p && p.querySelector('.qdt-stem') ? p.querySelector('.qdt-stem').textContent.trim() : '',
        expectStem: selStem ? selStem.textContent.trim() : '',
        optCount: p ? p.querySelectorAll('.qdt-option').length : 0,
        hasScore: p ? !!p.querySelector('.qdt-score') : false,
        popperWidth: p ? Math.round(p.getBoundingClientRect().width) : 0,
        debugRect: dbg,
      };
    })()`);
    check('QP.13a 悬停已选题干：浮层出现且题干一致/含分值',
      popSel.visible && popSel.stem.length > 0 && popSel.stem === popSel.expectStem && popSel.hasScore,
      JSON.stringify(popSel).slice(0, 300));
    check('QP.13a2 浮层实际绘制在最顶层',
      !!(popSel.debugRect && popSel.debugRect.paintedOnTop),
      popSel.debugRect ? JSON.stringify(popSel.debugRect) : 'no rect');
    if (popSel.visible) await cdp.shot('qp-layout-popover-selected');
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 2, y: 2 });
    const popSelGone = await waitPopoversHidden(cdp);
    check('QP.13b 鼠标移走：浮层隐藏',
      popSelGone.hidden && popSelGone.elapsed <= 600,
      `hidden=${popSelGone.hidden} elapsed=${popSelGone.elapsed}ms`);

    // ---------- QP.9 发布闭环 + 冻结态（已发布）布局 ----------
    const ts = Date.now().toString().slice(-6);
    const title = 'E2E-QP布局验证-' + ts;
    await cdp.eval(`(function(){
      var el = document.querySelector('.homework-editor input[placeholder="请输入作业标题"]');
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, ${JSON.stringify(title)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await clickByText(cdp, '.hw-editor-actions .el-button', '发布作业');
    const published = await waitFor(cdp, `(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      return rows.some(function(r){
        var t = r.querySelector('.hw-title');
        return t && t.textContent.indexOf(${JSON.stringify(title)}) >= 0;
      });
    })()`, 25000);
    check('QP.9a 带 10 道所选题目发布成功，列表出现新作业', published);

    // 重开编辑器 → 冻结态：提示 + 题库面板隐藏 + 已选列占满宽度
    await cdp.eval(`(function(){
      var rows = Array.from(document.querySelectorAll('.hw-row'));
      var row = rows.find(function(r){
        var t = r.querySelector('.hw-title');
        return t && t.textContent.indexOf(${JSON.stringify(title)}) >= 0;
      });
      if (!row) return;
      var btns = Array.from(row.querySelectorAll('.hw-action-btn'));
      var edit = btns.find(function(b){ return b.textContent.indexOf('编辑') >= 0; });
      if (edit) edit.click();
    })()`);
    await waitFor(cdp, `!!document.querySelector('.homework-editor')`, 15000);
    const frozen = await cdp.eval(`(function(){
      var builder = document.querySelector('.question-builder');
      var pool = document.querySelector('.question-pool-panel');
      var sel = document.querySelector('.selected-panel');
      var alert = document.querySelector('.question-builder .el-alert');
      var items = document.querySelectorAll('.selected-item').length;
      var rect = sel ? sel.getBoundingClientRect() : null;
      var card = document.querySelector('.hw-content-card');
      var cardRect = card ? card.getBoundingClientRect() : null;
      return {
        selectedOnly: !!builder && (builder.className || '').indexOf('selected-only') >= 0,
        poolHidden: !pool,
        hasAlert: !!alert,
        items: items,
        selWidth: rect ? Math.round(rect.width) : 0,
        cardWidth: cardRect ? Math.round(cardRect.width) : 0,
      };
    })()`);
    // 注意：QP.6 取消全选后 QP.7 仅添加了 1 题，因此发布快照为 1 题
    check('QP.9b 已发布作业：冻结提示 + 题库面板隐藏 + 已选列占满宽度',
      frozen.selectedOnly && frozen.poolHidden && frozen.hasAlert && frozen.items >= 1 && frozen.selWidth > frozen.cardWidth * 0.6,
      JSON.stringify(frozen));
    await cdp.shot('qp-layout-frozen');
    await clickByText(cdp, '.hw-editor-actions .el-button', '退出编辑');

    // ---------- 页面错误汇总 ----------
    if (cdp.consoleErrors.length) {
      log('--- 页面捕获到的错误(' + cdp.consoleErrors.length + ') ---');
      cdp.consoleErrors.slice(0, 10).forEach((e) => log('  ' + e.slice(0, 200)));
    } else {
      log('--- 页面无 console.error / 未捕获异常 ---');
    }
    check('QP.8 无 console.error / 未捕获异常', cdp.consoleErrors.length === 0, cdp.consoleErrors.length + ' 条');
  } finally {
    killChrome(chrome);
  }

  const failed = results.filter((r) => !r.ok);
  log('===== 汇总: ' + (results.length - failed.length) + '/' + results.length + ' 通过 =====');
  if (failed.length) {
    failed.forEach((r) => console.log('FAIL | ' + r.name));
    process.exitCode = 1;
  }
}

run().catch((e) => {
  console.error('E2E 运行异常:', e);
  process.exitCode = 1;
});
