#!/usr/bin/env node
/**
 * 课程列表 UI 回归：操作按钮尺寸/常驻 + 学期选择器布局。
 *
 * 现场两轮反馈固化成的检查（后续改样式先跑这个）：
 *   1. 卡片右上角 编辑/授课班级/复用/删除 四个按钮常驻、热区 ≥36px
 *   2. 新建课程弹窗「学期」两个下拉同一行、年份完整显示（不出现 "202…"）
 *   3. 按钮不与课程标题/简介重叠
 *
 * 前置：后端 8005、前端 5273、admin/A0987654
 * 运行：node test/e2e/verify-course-ui.js
 */
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

const CHROME = process.env.CHROME_PATH || 'C:/Users/张文飞/AppData/Local/Google/Chrome/Application/chrome.exe'
const BASE = 'http://localhost:5273'
const ROOT = path.resolve(__dirname, '../..')
const SHOT = path.join(ROOT, 'test/screenshots')
const PORT = 9971
const PROFILE = 'D:/tmp/zhike-verify-course-ui'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failures = 0
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  | ' + extra : ''}`)
  if (!ok) failures += 1
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map()
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result)
      }
    })
  }
  send(method, params = {}) {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error('eval failed: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text))
    return r.result.value
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(path.join(SHOT, name), Buffer.from(r.data, 'base64'))
  }
}

async function waitFor(tab, expr, timeout = 20000, poll = 250) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    try { if (await tab.eval(expr)) return true } catch { /* retry */ }
    await sleep(poll)
  }
  return false
}

async function main() {
  fs.mkdirSync(SHOT, { recursive: true })
  fs.rmSync(PROFILE, { recursive: true, force: true })
  const proc = spawn(CHROME, [
    `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
    `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', '--force-device-scale-factor=1', 'about:blank',
  ], { stdio: 'ignore', detached: true })
  let wsUrl = null
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`)
      const page = (await res.json()).filter((t) => t.type === 'page')[0]
      if (page) { wsUrl = page.webSocketDebuggerUrl; break }
    } catch { /* retry */ }
    await sleep(250)
  }
  if (!wsUrl) throw new Error('Chrome devtools 端口未就绪')
  const ws = new WebSocket(wsUrl)
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', () => rej(new Error('ws 失败'))) })
  const tab = new Cdp(ws)
  await tab.send('Page.enable')
  await tab.send('Runtime.enable')
  await tab.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
  try {
    await tab.send('Page.navigate', { url: `${BASE}/login` })
    await waitFor(tab, `location.href.startsWith('http')`)
    await tab.eval(`localStorage.clear()`)
    await tab.send('Page.navigate', { url: `${BASE}/login` })
    await waitFor(tab, `document.querySelectorAll('input').length >= 2`, 20000)
    await tab.eval(`(() => {
      const inputs = document.querySelectorAll('input')
      inputs[0].value = 'admin'; inputs[0].dispatchEvent(new Event('input', { bubbles: true }))
      const pwd = document.querySelector('input[type="password"]')
      pwd.value = 'A0987654'; pwd.dispatchEvent(new Event('input', { bubbles: true }))
    })()`)
    await sleep(200)
    await tab.eval(`document.querySelector('button[type="submit"], .el-button--primary').click()`)
    check('admin 登录', await waitFor(tab, `!location.pathname.startsWith('/login')`, 20000))

    await tab.send('Page.navigate', { url: `${BASE}/teacher/courses` })
    check('课程卡片渲染', await waitFor(tab, `document.querySelector('.course-card') !== null`, 25000))
    await sleep(1200)

    // 1) 操作按钮：常驻 + 尺寸 + 不重叠
    const btn = await tab.eval(`(() => {
      const actions = document.querySelector('.course-actions')
      if (!actions) return null
      const cs = getComputedStyle(actions)
      const buttons = [...actions.querySelectorAll('button')]
      const rect = actions.getBoundingClientRect()
      const firstBtn = buttons[0]?.getBoundingClientRect()
      const titleEl = actions.closest('.course-card')?.querySelector('.course-name')
      const title = titleEl?.getBoundingClientRect()
      // 元素矩形含 padding，真正要判断的是文本内容区右边界
      const titlePadRight = titleEl ? parseFloat(getComputedStyle(titleEl).paddingRight) || 0 : 0
      const contentRight = title ? title.right - titlePadRight : 0
      const overlapsTitle = !!(title && firstBtn) && contentRight > rect.left
      return JSON.stringify({
        count: buttons.length,
        opacity: cs.opacity,
        pointer: cs.pointerEvents,
        btnW: firstBtn ? Math.round(firstBtn.width) : 0,
        btnH: firstBtn ? Math.round(firstBtn.height) : 0,
        overlapsTitle,
        contentRight: Math.round(contentRight),
        actionsLeft: Math.round(rect.left),
        contentRight: Math.round(contentRight),
        actionsLeft: Math.round(rect.left),
      })
    })()`)
    const info = btn ? JSON.parse(btn) : null
    check('四个操作按钮都在', info?.count === 4, JSON.stringify(info))
    check('按钮常驻可见（opacity=1）', info?.opacity === '1' && info?.pointer === 'auto')
    check('按钮热区 ≥ 36px', (info?.btnW || 0) >= 36 && (info?.btnH || 0) >= 36, `${info?.btnW}×${info?.btnH}`)
    check('按钮不与课程标题重叠', info?.overlapsTitle === false)
    await tab.shot('verify-01-course-actions.png')

    // 2) 新建课程弹窗：学期两下拉同行、年份完整
    await tab.eval(`document.querySelector('.course-add-card')?.click()`)
    check('新建课程弹窗打开', await waitFor(tab, `document.querySelector('.course-creation-form') !== null`, 8000))
    await sleep(600)
    const term = await tab.eval(`(() => {
      const picker = document.querySelector('.term-picker')
      if (!picker) return null
      const year = picker.querySelector('.term-picker-year')
      const season = picker.querySelector('.term-picker-season')
      const yRect = year?.getBoundingClientRect()
      const sRect = season?.getBoundingClientRect()
      return JSON.stringify({
        yearW: yRect ? Math.round(yRect.width) : 0,
        seasonW: sRect ? Math.round(sRect.width) : 0,
        sameRow: !!(yRect && sRect && Math.abs(yRect.top - sRect.top) < 6),
        yearText: year?.innerText.trim() || '',
      })
    })()`)
    const t = term ? JSON.parse(term) : null
    check('年份与季节同一行', t?.sameRow === true, JSON.stringify(t))
    check('年份下拉宽度 ≥ 140px（不截断）', (t?.yearW || 0) >= 140, `${t?.yearW}px`)
    check('年份显示完整值', /\d{4}\s*年/.test(t?.yearText || ''), t?.yearText || '')
    await tab.shot('verify-02-course-term.png')

    console.log(failures ? `\n共 ${failures} 项失败` : '\n全部通过')
  } finally {
    try { proc.kill() } catch { /* ignore */ }
  }
  process.exit(failures ? 1 : 0)
}

main().catch((e) => { console.error('验证失败:', e.message); process.exit(2) })
