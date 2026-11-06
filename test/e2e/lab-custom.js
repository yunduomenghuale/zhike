#!/usr/bin/env node
/** Stage 4 真实浏览器端到端（本地 5273 / 8092 通用，BASE 可配置）。
 *
 * 覆盖：顶级「实验管理」→ 新建抽屉双 Tab → 上传「从动态接入说明里提取的最小 HTML」
 * → 创建成功即展示「成绩接口」Tab → 复制给 AI → 在线调试（blocking 提示项）
 * → 补充说明 → 实验页面 / 排课 / 发布 → 学生经 sandbox iframe 上报
 * → 学生端 external 只显示总分 + 用时、无步骤明细表。
 *
 * 用法：
 *   SETUP=D:/tmp/stage4-setup.json SHOT_PREFIX=stage4-local node test/e2e/lab-custom.js
 *   BASE=http://192.168.3.145:8092 SHOT_PREFIX=stage4-8092 node test/e2e/lab-custom.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe';
const PORT = Number(process.env.CDP_PORT || 9227);
const SETUP_PATH = process.argv[2] || process.env.SETUP || 'D:/tmp/stage4-setup.json';
const SHOT_DIR = path.resolve(__dirname, '../../test/screenshots');
const SHOT_PREFIX = process.env.SHOT_PREFIX || 'stage4-local';
const PROFILE = 'D:/tmp/zhike-e2e/chrome-profile-stage4';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const setup = JSON.parse(fs.readFileSync(SETUP_PATH, 'utf-8'));
// 浏览器一律走前端（本地 5273 直出 dist 并代理 /api；8092 走 nginx）。
// setup.base 是准备脚本用的后端地址，不能拿来当浏览器入口。
const BASE = process.env.BASE || 'http://127.0.0.1:5273';
const TITLE = setup.lab_title;

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
    const sid = where && where.sessionId;
    const r = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true,
    }, sid);
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
      .map((e) => {
        const en = e.params.entry || {};
        return `${en.text || ''}${en.url ? ' @ ' + en.url : ''}${en.lineNumber != null ? ':' + en.lineNumber : ''}`;
      })
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
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail !== undefined ? ' | ' + String(detail).slice(0, 220) : ''));
}

async function waitFor(cdp, expression, timeoutMs = 15000, where) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const v = await cdp.eval(expression, where).catch(() => null);
    if (v && v.__error === undefined) return v;
    await sleep(250);
  }
  return null;
}

async function login(cdp, username, password) {
  await cdp.eval('try { localStorage.clear() } catch (e) {}');
  await cdp.send('Page.navigate', { url: BASE + '/login' });
  await sleep(2200);
  for (let i = 0; i < 60; i++) {
    if (await cdp.eval('document.readyState') === 'complete') break;
    await sleep(150);
  }
  // 隧道/慢网络下 Vue 挂载晚于 readyState：轮询等登录表单出现（最多 ~20s），
  // 只补时序健壮性，不改变「表单必须渲染出两个输入框」的断言语义。
  let n = 0;
  for (let i = 0; i < 100; i++) {
    n = await cdp.eval(`document.querySelectorAll('.split-auth__form-box--login input').length`).catch(() => 0);
    if (n >= 2) break;
    await sleep(200);
  }
  if (n !== 2) return '/login(inputs=' + n + ')';
  await cdp.eval(`(() => {
    const setVal = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set;
      setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const inputs = document.querySelectorAll('.split-auth__form-box--login input');
    setVal(inputs[0], ${JSON.stringify(username)});
    setVal(inputs[1], ${JSON.stringify(password)});
  })()`);
  await sleep(300);
  await cdp.eval(`document.querySelector('.split-auth__form-box--login .auth-submit').click()`);
  for (let i = 0; i < 100; i++) {
    await sleep(200);
    const p = await cdp.eval('location.pathname').catch(() => '');
    if (p && p !== '/login') return p;
  }
  return await cdp.eval('location.pathname');
}

async function clickButton(scope, text) {
  // EP 抽屉关闭后仍留在 DOM 且 display:flex；必须遍历所有 scope 匹配项并用
  // offsetParent 过滤可见性，否则 querySelector 会命中第一个（已关闭的）抽屉。
  return await CDP.eval(`(() => {
    const S = ${JSON.stringify(scope)}, T = ${JSON.stringify(text)};
    const roots = S ? [...document.querySelectorAll(S)] : [document];
    const all = [];
    roots.forEach((r) => r.querySelectorAll('button, .el-button').forEach((e) => all.push(e)));
    const b = all.find((e) => e.getClientRects().length && (e.textContent || '').trim().includes(T));
    if (!b) return false;
    b.click(); return true;
  })()`);
}

async function clickTab(text) {
  return await CDP.eval(`(() => {
    const T = ${JSON.stringify(text)};
    const items = [...document.querySelectorAll('.el-tabs__item')].filter((e) => e.getClientRects().length);
    const t = items.find((e) => (e.textContent || '').trim() === T);
    if (!t) return false;
    t.click(); return true;
  })()`);
}

async function setFormInput(label, value) {
  return await CDP.eval(`(() => {
    const L = ${JSON.stringify(label)}, V = ${JSON.stringify(String(value))};
    const items = [...document.querySelectorAll('.el-form-item')].filter((e) => e.getClientRects().length);
    const item = items.find((e) => ((e.querySelector('.el-form-item__label') || {}).textContent || '').includes(L));
    if (!item) return 'NO_ITEM';
    const inp = item.querySelector('textarea') || item.querySelector('input.el-input__inner') || item.querySelector('input');
    if (!inp) return 'NO_INPUT';
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(inp), 'value').set;
    setter.call(inp, V);
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return 'OK';
  })()`);
}

async function selectFormOption(label, optionText) {
  const opened = await CDP.eval(`(() => {
    const L = ${JSON.stringify(label)};
    const items = [...document.querySelectorAll('.el-form-item')].filter((e) => e.getClientRects().length);
    const item = items.find((e) => ((e.querySelector('.el-form-item__label') || {}).textContent || '').includes(L));
    const w = item && item.querySelector('.el-select__wrapper');
    if (!w) return false;
    w.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    w.click();
    return true;
  })()`);
  if (!opened) return false;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    const ok = await CDP.eval(`(() => {
      const T = ${JSON.stringify(optionText)};
      const opts = [...document.querySelectorAll('.el-select-dropdown__item')]
        .filter((o) => o.getClientRects().length > 0);
      const t = opts.find((o) => (o.textContent || '').trim() === T)
        || opts.find((o) => (o.textContent || '').trim().includes(T));
      if (!t) return false;
      t.click(); return true;
    })()`);
    if (ok) return true;
  }
  return false;
}

async function api(method, urlPath, token, body) {
  const r = await fetch(BASE.replace(/\/$/, '') + urlPath, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const j = await r.json().catch(() => ({}));
  return { status: r.status, code: j.code, data: j.data, message: j.message };
}

let CDP;

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
  CDP = cdp;
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');
  await cdp.send('DOM.enable');
  try { await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }); } catch (e) {}
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  let labId = null;
  try {
    // ============ A：教师登录 + 顶级入口 ============
    const mark0 = cdp.events.length;
    const landed = await login(cdp, setup.teacher, setup.password);
    check('A1 教师真实登录成功', landed !== '/login' && !String(landed).startsWith('/login('), landed);
    const menu = await waitFor(cdp, `document.body.innerText.includes('实验管理') ? true : null`);
    check('A2 教师侧栏出现「实验管理」', !!menu);
    await cdp.send('Page.navigate', { url: BASE + '/teacher/labs' });
    const pageReady = await waitFor(cdp, `document.querySelector('.page-title')?.textContent?.trim() === '实验管理' ? true : null`);
    check('A3 顶级实验管理页渲染', !!pageReady);
    const hasCourseFilter = await cdp.eval(`!!document.querySelector('.filter-card .el-select')`);
    check('A4 课程筛选存在', !!hasCourseFilter);
    check('A5 新建实验按钮存在', await clickAvailable(cdp, '新建实验'));
    await cdp.shot(SHOT_PREFIX + '-library');

    // ============ B：新建抽屉（自定义上传默认第一）+ 上传「说明里的」HTML ============
    await clickButton(null, '新建实验');
    const drawerOpen = await waitFor(cdp, `(() => {
      const d = [...document.querySelectorAll('.el-drawer')].filter((e) => e.getClientRects().length);
      return d.some((e) => (e.textContent || '').includes('新建实验')) ? true : null;
    })()`);
    check('B1 新建抽屉打开', !!drawerOpen);
    const tabs = await cdp.eval(`[...document.querySelectorAll('.el-tabs__item')].filter((e)=>e.getClientRects().length).map((e)=>e.textContent.trim())`);
    check('B2 双 Tab：自定义上传排第一（教师反馈第 8 条）',
      tabs[0] === '自定义上传' && tabs.some((t) => t.includes('平台预置')), JSON.stringify(tabs));
    const activeTab0 = await cdp.eval(`[...document.querySelectorAll('.el-tabs__item.is-active')].filter((e)=>e.getClientRects().length).map((e)=>e.textContent.trim()).join('|')`);
    check('B3 自定义上传默认选中', String(activeTab0).includes('自定义上传'), activeTab0);
    const noTemplatePick = await cdp.eval(`(() => {
      const labels = [...document.querySelectorAll('.el-form-item__label')].filter((e) => e.getClientRects().length).map((e) => e.textContent.trim());
      return { hasTemplate: labels.some((l) => l.includes('实验模板')), labels };
    })()`);
    check('B3a 自定义上传不出现模板/满分等配置（教师反馈第 8 条）',
      noTemplatePick.hasTemplate === false
      && !noTemplatePick.labels.includes('实验满分') && !noTemplatePick.labels.includes('允许重做'),
      JSON.stringify(noTemplatePick.labels));
    await sleep(500);
    const uploader = await cdp.eval(`!!document.querySelector('.lab-html-upload')`);
    check('B3b 单 HTML 上传区可见', !!uploader);
    check('B4 选择所属课程', await selectFormOption('所属课程', setup.course_name));
    check('B5 填写实验名称', (await setFormInput('实验名称', TITLE)) === 'OK');

    await cdp.send('DOM.getDocument').then(async ({ root }) => {
      const q = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: 'input[type=file]' });
      if (q.nodeId) await cdp.send('DOM.setFileInputFiles', { files: [setup.fixture_path], nodeId: q.nodeId });
    });
    const picked = await waitFor(cdp, `(() => {
      const e = [...document.querySelectorAll('.lab-page-uploader .file-name')].filter((x)=>x.getClientRects().length);
      return e.length ? e[0].textContent.trim() : null;
    })()`);
    check('B6 上传「从动态说明提取的」HTML', !!picked && String(picked).includes('stage4-from-spec.html'), picked);
    await cdp.shot(SHOT_PREFIX + '-create');

    // ============ C：创建成功即打开「成绩接口」Tab（详情为弹窗，教师反馈第 4 条） ============
    await clickButton('.el-drawer', '创建实验');
    const detailReady = await waitFor(cdp, `(() => {
      const d = [...document.querySelectorAll('.el-dialog')].filter((e) => e.getClientRects().length);
      return d.some((e) => (e.textContent || '').includes(${JSON.stringify(TITLE)})) ? true : null;
    })()`, 25000);
    check('C1 创建成功并打开详情弹窗', !!detailReady);
    const activeTab = await cdp.eval(`[...document.querySelectorAll('.el-tabs__item.is-active')].filter((e)=>e.getClientRects().length).map((e)=>e.textContent.trim()).join('|')`);
    check('C2 自动切到「成绩接口」Tab', String(activeTab).includes('成绩接口'), activeTab);
    const endpoint = await cdp.eval(`document.querySelector('.lab-grading-panel .endpoint')?.textContent?.trim() || ''`);
    check('C3 成绩上报地址正确', endpoint === 'POST /api/lab-gate/grade/', endpoint);
    const md = await waitFor(cdp, `(() => {
      const p = document.querySelector('.lab-grading-panel .spec-markdown');
      return p && p.textContent.length > 1000 ? p.textContent : null;
    })()`);
    check('C4 动态 Markdown 含实验名/满分/schema/最小HTML/AI指令',
      !!md && md.includes(TITLE) && md.includes('100') && md.includes('请求与响应 schema')
      && md.includes('LabBridge.reportGrade(') && md.includes('可直接复制给 AI'));
    check('C5 动态说明无占位符残留且无补充说明段',
      !!md && !md.includes('@@') && !md.includes('教师补充说明'), md && md.slice(0, 80));
    check('C6 复制给 AI 可用', await clickButton('.lab-grading-panel', '复制给 AI'));
    const toast = await waitFor(cdp, `document.querySelector('.lab-grading-panel .copy-toast')?.textContent || null`, 6000);
    check('C6b 复制结果反馈', !!toast && String(toast).includes('接入说明'), toast);
    await cdp.shot(SHOT_PREFIX + '-grading');

    // ============ D：在线调试（blocking 提示项 / dry-run） ============
    check('D1 满分示例填充', await clickButton('.lab-grading-panel', '满分示例'));
    check('D2 发送调试请求', await clickButton('.lab-grading-panel', '发送调试请求'));
    const verdict = await waitFor(cdp, `document.querySelector('.debug-verdict')?.textContent?.trim() || null`, 15000);
    check('D3 调试通过且标注 dry-run', !!verdict && verdict.includes('调试通过') && verdict.includes('未产生真实提交'), verdict);
    const checks = await cdp.eval(`(() => {
      const all = [...document.querySelectorAll('.lab-grading-panel .check-item')];
      return { total: all.length, info: all.filter((e)=>e.classList.contains('info')).length,
               bad: all.filter((e)=>e.classList.contains('bad')).length,
               ok: all.filter((e)=>e.classList.contains('ok')).length };
    })()`);
    check('D4 提示项渲染为灰色「提示」而非红色失败（blocking=false）',
      checks && checks.info >= 1 && checks.bad === 0, JSON.stringify(checks));
    const preview = await cdp.eval(`document.querySelector('.debug-preview pre')?.textContent || ''`);
    check('D5 展示「若正式提交会写入」预览', preview.includes('external') && preview.includes('服务端'), preview.slice(0, 120));

    // D6 补：问号帮助弹窗（教师反馈第 5 条）
    check('D6 问号图标打开使用示例弹窗', await cdp.eval(`(() => {
      const icon = document.querySelector('.lab-grading-panel .help-icon');
      if (!icon) return false;
      icon.click(); return true;
    })()`));
    const helpReady = await waitFor(cdp, `(() => {
      const ds = [...document.querySelectorAll('.el-dialog')].filter((e) => e.getClientRects().length);
      return ds.some((e) => (e.textContent || '').includes('如何使用接入说明')) ? true : null;
    })()`, 8000);
    check('D6b 帮助弹窗含使用规则与提示词示例',
      !!helpReady && (await cdp.eval(`(() => {
        const ds = [...document.querySelectorAll('.el-dialog')].filter((e) => e.getClientRects().length);
        const d = ds.find((e) => (e.textContent || '').includes('如何使用接入说明'));
        return d && d.textContent.includes('LabBridge.reportGrade') && d.textContent.includes('提示词示例') ? true : null;
      })()`)));
    await cdp.eval(`(() => {
      const ds = [...document.querySelectorAll('.el-dialog')].filter((e) => e.getClientRects().length);
      const d = ds.find((e) => (e.textContent || '').includes('如何使用接入说明'));
      const b = d && [...d.querySelectorAll('button')].find((x) => (x.textContent || '').includes('关闭'));
      if (b) b.click(); return true;
    })()`);
    await sleep(600);
    await cdp.shot(SHOT_PREFIX + '-debug');

    // 找到本次实验 id（真实 API 查询，避免同名实验点错行）
    const labsRes = await api('GET', `/api/labs/?course=${setup.course_id}`, setup.teacher_token);
    const labRow = (labsRes.data?.results || []).find((l) => l.title === TITLE);
    check('D8 真实 API 能查到新建的自定义实验', !!labRow, labRow && labRow.id);
    labId = labRow && labRow.id;
    const subsBefore = await api('GET', `/api/lab-submissions/?lab=${labId}`, setup.teacher_token);
    check('D9 dry-run 未产生任何真实提交',
      (subsBefore.data?.results || []).length === 0, `count=${(subsBefore.data?.results || []).length}`);

    // ============ E：实验页面 / 排课 / 发布 / 徽标 ============
    check('E1 切到「实验页面」Tab', await clickTab('实验页面'));
    await sleep(600);
    const pageName = await cdp.eval(`document.querySelector('.page-alert')?.textContent || ''`);
    check('E1b 显示已上传页面文件名', pageName.includes('stage4-from-spec.html'), pageName.slice(0, 160));
    check('E2 切到「排课」Tab', await clickTab('排课'));
    await sleep(400);
    check('E2b 选择班级', await selectFormOption('班级', setup.class_name));
    check('E2c 保存排课', await clickButton('.el-dialog', '保存排课'));
    const scheduled = await waitFor(cdp, `(() => {
      const s = document.querySelector('.schedule-list');
      return s && s.textContent.includes(${JSON.stringify(setup.class_name)}) ? true : null;
    })()`, 15000);
    check('E2d 排课记录可见', !!scheduled);
    check('E3 切到「概览与成绩」Tab', await clickTab('概览与成绩'));
    await sleep(800);
    // 教师反馈第 6 条：概览页内嵌统计图表 + 成绩明细
    check('E3b 完成情况堆叠条渲染', !!await cdp.eval(`document.querySelector('.stack-bar')`));
    check('E3c 分数段分布图渲染', !!await cdp.eval(`document.querySelector('.bar-chart')`));
    check('E3d 成绩明细表并入概览', !!await cdp.eval(`(() => {
      const pane = [...document.querySelectorAll('.el-tab-pane')].find((p) => p.style.display !== 'none' && p.querySelector('.scores-title'));
      return pane && pane.querySelector('.el-table') ? true : null;
    })()`));
    await cdp.shot(SHOT_PREFIX + '-overview');
    await cdp.eval(`(() => {
      const b = [...document.querySelectorAll('.el-dialog__headerbtn')].filter((e)=>e.getClientRects().length)[0];
      if (b) b.click();
    })()`);
    await sleep(800);
    const rowText = await cdp.eval(`document.querySelector('.lab-row-${labId}')?.innerText || ''`);
    check('E4 列表徽标「最近通过」+ 草稿态',
      rowText.includes('最近通过') && rowText.includes('草稿'), rowText.slice(0, 160));
    check('E5 发布实验', await cdp.eval(`(() => {
      const row = document.querySelector('.lab-row-${labId}');
      if (!row) return false;
      const b = [...row.querySelectorAll('button')].find((e) => (e.textContent || '').trim() === '发布');
      if (!b) return false;
      b.click(); return true;
    })()`));
    const published = await waitFor(cdp, `(() => {
      const row = document.querySelector('.lab-row-${labId}');
      return row && row.innerText.includes('已发布') ? true : null;
    })()`, 15000);
    check('E5b 列表状态变为「已发布」', !!published);
    await cdp.shot(SHOT_PREFIX + '-published');

    // D6 补：越界报文（真实 API）→ 徽标「最近失败」→ 满分 →「最近通过」
    const bad = await api('POST', `/api/labs/${labId}/grade-debug/`, setup.teacher_token,
      { total_score: 101, elapsed_seconds: 10 });
    check('E6 越界报文 dry-run 判失败', bad.data && bad.data.passed === false, `passed=${bad.data && bad.data.passed}`);
    await cdp.send('Page.reload');
    await waitFor(cdp, `document.querySelector('.page-title')?.textContent?.trim() === '实验管理' ? true : null`, 20000);
    const failBadge = await waitFor(cdp, `(() => {
      const row = document.querySelector('.lab-row-${labId}');
      return row && row.innerText.includes('最近失败') ? true : null;
    })()`, 12000);
    check('E6b 列表徽标「最近失败」', !!failBadge);
    const good = await api('POST', `/api/labs/${labId}/grade-debug/`, setup.teacher_token,
      { total_score: 100, elapsed_seconds: 60 });
    check('E6c 满分报文 dry-run 判通过', good.data && good.data.passed === true);

    // ============ F：学生经 sandbox iframe 上报 + external 展示 ============
    const started = await api('POST', '/api/lab-submissions/start/', setup.student_token, { lab: labId });
    check('F1 学生开始实验拿到门控链接', started.status === 200 && !!started.data?.page_url,
      `status=${started.status} message=${started.message}`);
    const gateUrl = started.data && started.data.page_url;
    if (gateUrl) {
      const sinceF = cdp.events.length;
      await cdp.send('Page.navigate', { url: BASE.replace(/\/$/, '') + gateUrl });
      const frameSession = await cdp.attachIframe(sinceF);
      check('F2 sandbox iframe 独立上下文可定位', !!frameSession);
      const tasksReady = frameSession && await waitFor(cdp, `(() => {
        const b = document.getElementById('tasks');
        return b && b.children.length === 3 ? true : null;
      })()`, 20000, frameSession);
      check('F3 说明里的最小 HTML 正常运行（3 个任务渲染）', !!tasksReady);
      if (frameSession && tasksReady) {
        await cdp.eval(`(() => {
          document.querySelectorAll('input[type=checkbox]').forEach((c) => { if (!c.checked) c.click() });
          document.getElementById('finish').click();
          return true;
        })()`, frameSession);
        const reported = await waitFor(cdp, `(() => {
          const l = document.getElementById('log');
          return l && (l.textContent.includes('成绩已提交') || l.textContent.includes('"code": 0')) ? l.textContent.slice(0, 200) : null;
        })()`, 20000, frameSession);
        check('F4 页面经 LabBridge.reportGrade 真实上报成功', !!reported, reported);
      } else {
        check('F4 页面经 LabBridge.reportGrade 真实上报成功', false, 'iframe 未就绪');
      }
    } else {
      check('F2 sandbox iframe 独立上下文可定位', false, '无门控链接');
      check('F3 说明里的最小 HTML 正常运行（3 个任务渲染）', false, '无门控链接');
      check('F4 页面经 LabBridge.reportGrade 真实上报成功', false, '无门控链接');
    }

    // 切换学生账号，看学生端 external 展示
    const studentLanded = await login(cdp, setup.student, setup.password);
    check('F5 学生真实登录成功', studentLanded !== '/login' && !String(studentLanded).startsWith('/login('), studentLanded);
    await cdp.send('Page.navigate', { url: BASE + `/student/courses/${setup.course_id}/labs` });
    const card = await waitFor(cdp, `(() => {
      const c = [...document.querySelectorAll('article.lab-card')]
        .find((e) => (e.querySelector('.lab-title')?.textContent || '').trim() === ${JSON.stringify(TITLE)});
      return c ? c.innerText : null;
    })()`, 20000);
    check('F6 学生端看到该自定义实验且标「自定义」', !!card && card.includes('自定义'), String(card).slice(0, 180));
    const ext = await cdp.eval(`(() => {
      const c = [...document.querySelectorAll('article.lab-card')]
        .find((e) => (e.querySelector('.lab-title')?.textContent || '').trim() === ${JSON.stringify(TITLE)});
      if (!c) return null;
      return {
        text: c.innerText,
        hasBreakdown: !!c.querySelector('.lab-breakdown'),
        hasExternalNote: !!c.querySelector('.external-note'),
        total: c.querySelector('.lab-score-total')?.textContent?.trim() || '',
      };
    })()`);
    check('F7 external 只显示总分 + 用时、不渲染步骤表',
      !!ext && ext.hasBreakdown === false && ext.hasExternalNote === true && ext.text.includes('用时'),
      JSON.stringify(ext));
    check('F8 总分可见', !!ext && /100/.test(ext.total), ext && ext.total);
    const cardButtons = await cdp.eval(`(() => {
      const c = [...document.querySelectorAll('article.lab-card')]
        .find((e) => (e.querySelector('.lab-title')?.textContent || '').trim() === ${JSON.stringify(TITLE)});
      return c ? [...c.querySelectorAll('button')].map((b) => b.textContent.trim()) : [];
    })()`);
    check('F9 重做入口存在（Stage 6 最高分规则：重做只记录最高分，允许重做）',
      Array.isArray(cardButtons) && cardButtons.includes('重做实验'), JSON.stringify(cardButtons));
    await cdp.shot(SHOT_PREFIX + '-student');

    const errors = cdp.consoleErrors(mark0).filter((t) => !t.includes('favicon'));
    check('F10 全流程控制台无 error', errors.length === 0, errors.slice(0, 3).join(' / '));
  } catch (e) {
    check('EXCEPTION', false, String(e && e.stack || e).slice(0, 400));
  } finally {
    const pass = results.filter((r) => r.ok).length;
    const fail = results.length - pass;
    console.log(`\n总计 ${results.length} 项，通过 ${pass} 项，失败 ${fail} 项`);
    if (fail === 0) console.log('ALL_PASS');
    else {
      console.log('FAILED:');
      results.filter((r) => !r.ok).forEach((r) => console.log('  - ' + r.name));
      process.exitCode = 1;
    }
    try { ws.close(); } catch (e) {}
    chrome.kill();
  }
})();

async function clickAvailable(cdp, text) {
  return await cdp.eval(`(() => {
    const T = ${JSON.stringify(text)};
    return [...document.querySelectorAll('button, .el-button')]
      .filter((e) => e.getClientRects().length)
      .some((e) => (e.textContent || '').trim().includes(T));
  })()`);
}
