import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateScript, generateAudio, listVideos } from '@/api/course'

const SCRIPT_BATCH_SIZE = 6
const AUDIO_BATCH_SIZE = 3
// 批内轮询间隔：后端每个小块/每页完成即落库，轮询让按钮进度在请求进行中也实时推进
const PROGRESS_POLL_MS = 2500

// 从服务端拉取某个章节的真实生成进度（讲稿/配音）。
// 用途：1) 刷新恢复时用真实进度纠正 localStorage 旧种子（批次响应可能在刷新途中
// 丢失，旧记录会落后于数据库，表现为按钮页数比左侧标签少一截）；
// 2) 循环期间轮询，进度只增不减地追赶数据库。
async function fetchServerProgress(kind, catalogId) {
  try {
    const data = await listVideos({ catalog: catalogId })
    const list = Array.isArray(data?.results) ? data : Array.isArray(data) ? data : []
    const video = list[0]
    if (!video) return null
    const scripts = Array.isArray(video.scripts) ? video.scripts : []
    if (kind === 'audio') {
      return {
        done: scripts.filter((s) => s.audio_url).length,
        total: scripts.filter((s) => String(s.script || '').trim()).length,
      }
    }
    return {
      done: scripts.filter((s) => String(s.script || '').trim()).length,
      total: scripts.length,
    }
  } catch {
    return null // 轮询/种子拉取失败静默：批次响应与旧记录仍是有效兜底
  }
}

// 生成任务持久化：刷新/关闭页面不丢任务，重新打开自动续跑。
// 记录含 runnerId（标签页认领）与 updatedAt（心跳），防止多标签页同时恢复导致重复生成：
// 心跳新鲜且属于其他标签页 → 让位；心跳过期或已被释放（beforeunload 释放）→ 本页接管。
const STORAGE_KEY = 'zhike:generation-tasks'
const STALE_MS = 60000
const TAB_ID = Math.random().toString(36).slice(2)

function readRecords() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}
function writeRecords(records) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(records))
  } catch {
    /* 存储不可用（隐私模式等）时静默降级为不持久化 */
  }
}
function saveRecord(kind, catalogId, progress) {
  const records = readRecords()
  records[`${kind}:${catalogId}`] = {
    kind,
    catalogId: Number(catalogId),
    done: progress?.done || 0,
    total: progress?.total || 0,
    runnerId: TAB_ID,
    updatedAt: Date.now(),
  }
  writeRecords(records)
}
function clearRecord(kind, catalogId) {
  const records = readRecords()
  delete records[`${kind}:${catalogId}`]
  writeRecords(records)
}
// 记录仍归本标签页所有（或已被释放/清除）时才继续——其他标签页接管后本页让位
function stillMine(kind, catalogId) {
  const record = readRecords()[`${kind}:${catalogId}`]
  return !record || !record.runnerId || record.runnerId === TAB_ID
}
// 页面卸载前释放本标签页的认领（保留进度）：刷新后新页面可立即接管，不必等心跳过期
function releaseMyClaims() {
  const records = readRecords()
  let changed = false
  for (const record of Object.values(records)) {
    if (record && record.runnerId === TAB_ID) {
      record.runnerId = null
      changed = true
    }
  }
  if (changed) writeRecords(records)
}
let unloadHooked = false
function hookUnloadRelease() {
  if (unloadHooked) return
  unloadHooked = true
  window.addEventListener('beforeunload', releaseMyClaims)
  // bfcache 场景（前进/后退缓存）同样需要释放
  window.addEventListener('pagehide', releaseMyClaims)
}

/**
 * 全局 AI 生成任务（讲解稿/配音分批循环）。
 *
 * 循环放在 store 而非组件中执行：路由切换导致组件卸载时，分批循环继续进行、
 * 进度状态保留；返回页面后按钮仍实时显示「讲稿 x/y」「配音 x/y」。
 * 每批结果由后端落库，即使浏览器关闭也不丢已生成进度（增量续传）。
 * 任务记录持久化在 localStorage：刷新/关闭页面后重新打开会自动从断点续跑，
 * 按钮上的进度用记录中的最近值立即占位，再由真实响应刷新。
 * 实时性：后端批内按小块/逐页增量落库，前端循环期间每 2.5s 轮询服务端进度
 * （只增不减），请求进行中按钮页数也持续推进，不再「卡一批、跳一大截」。
 */
export const useGenerationStore = defineStore('generation', () => {
  // catalogId -> { done, total }；键存在即任务进行中
  const scriptTasks = reactive({})
  const audioTasks = reactive({})
  // 任务完成信号：恢复的任务在后台跑完后，页面据此刷新数据（按钮从任务态回到持久化进度）
  const completedTick = ref(0)
  // 进行中的循环（与展示态分离：恢复任务时先占位展示，再进循环）
  const runningScript = new Set()
  const runningAudio = new Set()
  let restored = false

  hookUnloadRelease()

  async function runScript(catalogId) {
    const id = Number(catalogId)
    if (runningScript.has(id)) return
    runningScript.add(id)
    if (!scriptTasks[id]) scriptTasks[id] = { done: 0, total: 0 }
    // 恢复/首启都以服务端真实进度为种子：刷新页面后 localStorage 记录可能落后于
    // 数据库（批次响应在刷新途中丢失），先用真实值纠正，避免按钮显示过期页数
    const seed = await fetchServerProgress('script', id)
    if (scriptTasks[id]) {
      scriptTasks[id] = {
        done: Math.max(scriptTasks[id].done, seed?.done || 0),
        total: scriptTasks[id].total || seed?.total || 0,
      }
    }
    saveRecord('script', id, scriptTasks[id])
    // 批内轮询：请求进行中后端也在增量落库，轮询把最新页数同步进按钮（只增不减）
    const poll = setInterval(async () => {
      const p = await fetchServerProgress('script', id)
      if (!p || !scriptTasks[id]) return
      if (p.done > scriptTasks[id].done || (p.total && !scriptTasks[id].total)) {
        scriptTasks[id] = {
          done: Math.max(scriptTasks[id].done, p.done),
          total: scriptTasks[id].total || p.total,
        }
        saveRecord('script', id, scriptTasks[id])
      }
    }, PROGRESS_POLL_MS)
    try {
      for (;;) {
        if (!stillMine('script', id)) return // 已被其他标签页接管，静默让位
        const res = await generateScript(id, { limit: SCRIPT_BATCH_SIZE })
        scriptTasks[id] = { done: res.script_pages, total: res.pages }
        saveRecord('script', id, scriptTasks[id])
        if (res.done) break
      }
      if (!stillMine('script', id)) return
      clearRecord('script', id)
      completedTick.value += 1
      ElMessage.success(`已生成 ${scriptTasks[id].total} 页讲解稿`)
    } catch {
      // 失败不保留记录（不自动续跑）：用户看到提示后可手动再次点击，与既有交互一致
      clearRecord('script', id)
      // 拦截器已弹接口错误，这里补充进度说明（增量语义，可安全重试）
      const p = scriptTasks[id] || { done: 0, total: 0 }
      ElMessage.warning(`讲解稿生成中断：已完成 ${p.done}/${p.total} 页，可再次点击继续`)
    } finally {
      clearInterval(poll)
      runningScript.delete(id)
      delete scriptTasks[id]
    }
  }

  async function runAudio(catalogId) {
    const id = Number(catalogId)
    if (runningAudio.has(id)) return
    runningAudio.add(id)
    if (!audioTasks[id]) audioTasks[id] = { done: 0, total: 0 }
    // 同讲稿：恢复时先以服务端真实进度纠正种子，再进循环
    const seed = await fetchServerProgress('audio', id)
    if (audioTasks[id]) {
      audioTasks[id] = {
        done: Math.max(audioTasks[id].done, seed?.done || 0),
        total: audioTasks[id].total || seed?.total || 0,
      }
    }
    saveRecord('audio', id, audioTasks[id])
    const poll = setInterval(async () => {
      const p = await fetchServerProgress('audio', id)
      if (!p || !audioTasks[id]) return
      if (p.done > audioTasks[id].done || (p.total && !audioTasks[id].total)) {
        audioTasks[id] = {
          done: Math.max(audioTasks[id].done, p.done),
          total: audioTasks[id].total || p.total,
        }
        saveRecord('audio', id, audioTasks[id])
      }
    }, PROGRESS_POLL_MS)
    try {
      for (;;) {
        if (!stillMine('audio', id)) return
        const res = await generateAudio(id, AUDIO_BATCH_SIZE)
        audioTasks[id] = { done: res.audio_pages, total: res.total_pages }
        saveRecord('audio', id, audioTasks[id])
        if (res.done) break
      }
      if (!stillMine('audio', id)) return
      clearRecord('audio', id)
      completedTick.value += 1
      ElMessage.success(`已完成 ${audioTasks[id].total} 页配音`)
    } catch {
      clearRecord('audio', id)
      const p = audioTasks[id] || { done: 0, total: 0 }
      ElMessage.warning(`配音中断：已完成 ${p.done}/${p.total} 页，可再次点击「配音」继续补齐`)
    } finally {
      clearInterval(poll)
      runningAudio.delete(id)
      delete audioTasks[id]
    }
  }

  // 页面加载后恢复未完成任务（由根组件 App.vue 挂载时调用一次，覆盖所有布局）：
  // 刷新/关闭前正在跑的任务从断点续跑；按钮进度先用记录值占位，再由响应刷新。
  function restoreTasks() {
    if (restored) return
    restored = true
    // 未登录页（如登录页）不恢复：无凭证时生成接口必然 401
    if (!localStorage.getItem('access_token')) return
    resumeRecords()
  }

  function resumeRecords() {
    const skipped = []
    for (const record of Object.values(readRecords())) {
      if (!record || !record.catalogId || !record.kind) continue
      // 其他标签页正在跑（心跳新鲜）→ 让位，避免重复生成
      if (record.runnerId && record.runnerId !== TAB_ID && Date.now() - (record.updatedAt || 0) < STALE_MS) {
        skipped.push(record)
        continue
      }
      const seed = { done: record.done || 0, total: record.total || 0 }
      if (record.kind === 'script') {
        scriptTasks[record.catalogId] = seed
        runScript(record.catalogId)
      } else if (record.kind === 'audio') {
        audioTasks[record.catalogId] = seed
        runAudio(record.catalogId)
      }
    }
    // 被让位的记录：等其心跳过期后再尝试接管（覆盖 beforeunload 未触发的崩溃/强杀场景）
    if (skipped.length) setTimeout(resumeRecords, STALE_MS + 5000)
  }

  return { scriptTasks, audioTasks, completedTick, runScript, runAudio, restoreTasks }
})
