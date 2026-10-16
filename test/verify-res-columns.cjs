/* 验证（Edge 无头 + CDP）：资源表列宽协调 + 操作列按钮全部平铺
 * 断言：
 *  ① 标题列不再被拉宽（≈186，≤205）
 *  ② 页面地址列收窄且短令牌完整不省略（列宽≈130，链接 scrollWidth ≤ clientWidth）
 *  ③ 操作列 4 个按钮全部可见、同一行、默认尺寸（高 32）
 *  ④ 无 ⋯ 下拉残留（.op-more 不存在）
 *  ⑤ 表格无横向滚动（body 宽 ≤ 容器宽）
 *  ⑥ 行高 ≤ 50px
 *  ⑦ 视频表按钮同样平铺（播放/发布/删除，无下拉）
 *  ⑧ 0 控制台错误 / 0 失败请求
 * 用法: node verify-res-columns.cjs <access_token> <app_url> <out_dir> [viewport=1440,1000]
 */
const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const token = process.argv[2];
const APP_URL = process.argv[3];
const outDir = process.argv[4] || os.tmpdir();
const VIEWPORT = process.argv[5] || '1440,1000';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-rescols-'));

if (!token || !APP_URL) {
  console.error('usage: node verify-res-columns.cjs <access_token> <app_url> <out_dir>');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = require('http').get(url, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
  });
}

async function main() {
  const edge = execFile(
    EDGE,
    [
      '--headless=new', '--remote-debugging-port=9227',
      `--user-data-dir=${userDataDir}`, '--no-proxy-server', '--no-first-run',
      '--no-default-browser-check', '--disable-extensions', `--window-size=${VIEWPORT}`,
      'about:blank',
    ],
    () => {},
  );
  edge.unref();

  let version = null;
  for (let i = 0; i < 40; i++) {
    try { version = await getJson('http://127.0.0.1:9227/json/version'); break; } catch { await sleep(500); }
  }
  if (!version) { console.error('edge devtools not ready'); process.exit(3); }

  const targets = await getJson('http://127.0.0.1:9227/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let msgId = 0;
  const pending = new Map();
  const consoleErrors = [];
  const pageErrors = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      consoleErrors.push(msg.params.args.map((a) => a.value || a.description || '').join(' '));
    } else if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description || ''));
    } else if (msg.method === 'Network.loadingFailed') {
      pageErrors.push({ url: msg.params.request?.url, error: msg.params.errorText });
    } else if (msg.method === 'Network.responseReceived' && msg.params.response.status >= 400) {
      pageErrors.push({ url: msg.params.response.url, status: msg.params.response.status });
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++msgId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result?.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem('access_token', ${JSON.stringify(token)});`,
  });

  const shot = async (name) => {
    const metrics = await send('Page.getLayoutMetrics');
    const size = metrics.cssContentSize || metrics.contentSize;
    const s = await send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: Math.min(size.width, 1440), height: Math.min(size.height, 2400), scale: 1 },
    });
    const p = path.join(outDir, name);
    fs.writeFileSync(p, Buffer.from(s.data, 'base64'));
    return p;
  };

  await send('Page.navigate', { url: `${APP_URL}/teacher/courses/5/resources` });
  let info = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    info = await evalJs(`(() => {
      const rows = document.querySelectorAll('.res-panel .compact-table .el-table__row');
      if (!rows.length) return JSON.stringify({ ready: false });
      const table = document.querySelector('.res-panel .compact-table');
      const headerCells = Array.from(table.querySelectorAll('.el-table__header th'));
      const row = rows[0];
      const cells = Array.from(row.querySelectorAll('.el-table__cell'));
      const cols = headerCells.map((th, i) => ({ label: th.textContent.trim(), width: Math.round(th.getBoundingClientRect().width) }));
      // 页面地址列：链接是否被省略
      const addrInner = row.querySelector('.res-url-link .el-link__inner');
      const addr = addrInner ? { scrollW: Math.round(addrInner.scrollWidth), clientW: addrInner.clientWidth, text: addrInner.textContent.trim() } : null;
      // 操作列按钮
      const opBtns = Array.from(row.querySelectorAll('.op-cell button'));
      const op = {
        count: opBtns.length,
        texts: opBtns.map((b) => b.textContent.trim()),
        tops: opBtns.map((b) => Math.round(b.getBoundingClientRect().top)),
        heights: opBtns.map((b) => Math.round(b.getBoundingClientRect().height)),
        widths: opBtns.map((b) => Math.round(b.getBoundingClientRect().width)),
        gaps: opBtns.slice(1).map((b, i) => Math.round(b.getBoundingClientRect().left - opBtns[i].getBoundingClientRect().right)),
        margins: opBtns.map((b) => getComputedStyle(b).marginLeft),
        lastBtnRight: opBtns.length ? Math.round(opBtns[opBtns.length - 1].getBoundingClientRect().right) : null,
        cellRight: Math.round(row.querySelector('.op-cell').getBoundingClientRect().right),
      };
      op.sameLine = new Set(op.tops).size === 1;
      op.noOverflow = (() => {
        const c = row.querySelector('.op-cell');
        return c.scrollWidth <= c.clientWidth + 1;
      })();
      // 操作列列头是否居中（文本块中心 vs 列中心）；fixed="right" 的列表头在独立 fixed header 里
      const opTh = Array.from(table.querySelectorAll('.el-table__header th, .el-table__fixed-right .el-table__header th')).find((t) => t.textContent.trim() === '操作');
      let headerCentered = null;
      if (opTh) {
        const rng = document.createRange();
        rng.selectNodeContents(opTh);
        const tr = rng.getBoundingClientRect();
        const cr = opTh.getBoundingClientRect();
        headerCentered = Math.abs((tr.left + tr.width / 2) - (cr.left + cr.width / 2)) <= 4;
      }
      // 视频表
      const vTable = document.querySelectorAll('.res-panel .compact-table')[1];
      const vOpBtns = vTable ? Array.from(vTable.querySelectorAll('.op-cell button')) : [];
      const vOpCell = vTable ? vTable.querySelector('.op-cell') : null;
      const video = {
        exists: !!vTable,
        opTexts: vOpBtns.map((b) => b.textContent.trim()),
        opTops: vOpBtns.map((b) => Math.round(b.getBoundingClientRect().top)),
        sameLine: new Set(vOpBtns.map((b) => Math.round(b.getBoundingClientRect().top))).size <= 1,
        noOverflow: vOpCell ? vOpCell.scrollWidth <= vOpCell.clientWidth + 1 : null,
        emptyHint: !!document.querySelector('.table-empty'),
      };
      return JSON.stringify({
        ready: true,
        cols,
        tableClientW: table.clientWidth,
        bodyW: Math.round(table.querySelector('.el-table__body').getBoundingClientRect().width),
        noScrollX: table.querySelector('.el-table__body').getBoundingClientRect().width <= table.clientWidth + 1,
        addr,
        op,
        headerCentered,
        video,
        moreBtnCount: document.querySelectorAll('.op-more').length,
        rowH: Math.round(row.getBoundingClientRect().height),
      });
    })()`);
    if (JSON.parse(info || '{}').ready) break;
  }
  const m = JSON.parse(info || '{}');
  const png = await shot('res-columns-final.png');

  const col = (label) => m.cols?.find((c) => c.label === label)?.width ?? null;
  const okTitle = col('标题') !== null && col('标题') <= 205;
  const okAddrW = col('页面地址') !== null && col('页面地址') <= 150 && col('页面地址') >= 115;
  const okAddrText = m.addr && m.addr.scrollW <= m.addr.clientW + 1 && /^page\/[0-9a-f]{8}…$/.test(m.addr.text);
  // 关键回归：按钮不被裁（单元格无溢出 + 最后一个按钮右缘不超单元格）+ 单行 + 默认尺寸 + 无 margin 叠加（间距=6）
  const okOp = m.op && m.op.count >= 4 && m.op.sameLine && m.op.heights.every((h) => h === 32) &&
    m.op.texts.includes('复制链接') && m.op.texts.includes('删除') &&
    m.op.noOverflow === true && m.op.lastBtnRight <= m.op.cellRight + 1 &&
    m.op.gaps.every((g) => g === 6) && m.op.margins.every((mg) => mg === '0px');
  const okOpW = col('操作') !== null && col('操作') >= 320 && col('操作') <= 340;
  const okHeaderCenter = m.headerCentered === true;
  const okNoMore = m.moreBtnCount === 0;
  const okNoScroll = m.noScrollX === true;
  const okRow = m.rowH > 0 && m.rowH <= 50;
  const okVideo = m.video.exists && m.video.opTexts.includes('删除') && m.video.sameLine && m.video.noOverflow === true;
  const okNoErr = consoleErrors.length === 0 && pageErrors.length === 0;

  const report = { ...m, png, consoleErrors, failedRequests: pageErrors.slice(0, 8) };
  console.log(JSON.stringify(report, null, 2));
  console.log('VERDICT_TITLE_NARROW=' + (okTitle ? 'PASS' : 'FAIL') + ` (width=${col('标题')})`);
  console.log('VERDICT_ADDR_NARROW_NO_ELLIPSIS=' + (okAddrW && okAddrText ? 'PASS' : 'FAIL') + ` (width=${col('页面地址')}, scrollW=${m.addr?.scrollW}, clientW=${m.addr?.clientW}, text=${m.addr?.text})`);
  console.log('VERDICT_OP_ALL_VISIBLE_NO_TRUNC=' + (okOp ? 'PASS' : 'FAIL') + ` (texts=${JSON.stringify(m.op?.texts)}, tops=${JSON.stringify(m.op?.tops)}, gaps=${JSON.stringify(m.op?.gaps)}, margins=${JSON.stringify(m.op?.margins)}, noOverflow=${m.op?.noOverflow}, lastBtnRight=${m.op?.lastBtnRight}, cellRight=${m.op?.cellRight})`);
  console.log('VERDICT_OP_WIDTH=' + (okOpW ? 'PASS' : 'FAIL') + ` (width=${col('操作')})`);
  console.log('VERDICT_OP_HEADER_CENTERED=' + (okHeaderCenter ? 'PASS' : 'FAIL') + ` (headerCentered=${m.headerCentered})`);
  console.log('VERDICT_NO_DROPDOWN_LEFT=' + (okNoMore ? 'PASS' : 'FAIL') + ` (moreBtnCount=${m.moreBtnCount})`);
  console.log('VERDICT_NO_SCROLLX=' + (okNoScroll ? 'PASS' : 'FAIL') + ` (bodyW=${m.bodyW}, clientW=${m.tableClientW})`);
  console.log('VERDICT_ROW_HEIGHT=' + (okRow ? 'PASS' : 'FAIL') + ` (height=${m.rowH})`);
  console.log('VERDICT_VIDEO_BTNS_VISIBLE=' + (okVideo ? 'PASS' : 'FAIL') + ` (texts=${JSON.stringify(m.video?.opTexts)}, exists=${m.video?.exists}, noOverflow=${m.video?.noOverflow})`);
  console.log('VERDICT_NO_CONSOLE_ERROR=' + (okNoErr ? 'PASS' : 'FAIL'));
  if (consoleErrors.length) console.log('consoleErrors=' + JSON.stringify(consoleErrors.slice(0, 5)));
  if (pageErrors.length) console.log('failedRequests=' + JSON.stringify(pageErrors.slice(0, 5)));

  ws.close();
  edge.kill();
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch {}
  const allOk = okTitle && okAddrW && okAddrText && okOp && okOpW && okHeaderCenter && okNoMore && okNoScroll && okRow && okVideo && okNoErr;
  console.log('VERDICT_ALL=' + (allOk ? 'PASS' : 'FAIL'));
  process.exit(allOk ? 0 : 4);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
