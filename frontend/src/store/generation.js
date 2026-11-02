import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateScript, generateAudio } from '@/api/course'
import { getAiTask, listActiveAiTasks, cancelAiTask, retryAiTask } from '@/api/ai-task'

// 队列化后的生成 store：浏览器不再是执行器（旧版 localStorage 分批循环已删除）。
// 提交即入队秒返，服务端 ai_worker 整章执行；本 store 只做：
//   1) 提交（连点防抖——服务端的唯一索引兜底，前端不该制造并发请求）；
//   2) 节流轮询（C10）：有任务才 2.5s 轮询、无任务完全停轮询、document.hidden 暂停；
//   3) 恢复：服务端是唯一真相（/ai-tasks/active/），刷新/关页/多标签页天然一致，
//      不再有标签页认领（runnerId）那套本地协商。
const POLL_MS = 2500
const LEGACY_KEY = 'zhike:generation-tasks' // 旧前端续跑记录：启动即清（坑 22）

const TYPE_LABEL = {
  script_gen: '讲稿',
  audio_gen: '配音',
  question_gen: 'AI 生题',
  chapter_summary: '章节总结',
  class_analytics: '学情分析',
  course_reuse: '课程复用',
  ppt_parse: '课件解析',
  embed_ingest: '向量入库',
}

function bucket(kind) {
  return kind === 'script' ? 'scriptTasks' : 'audioTasks'
}

export const useGenerationStore = defineStore('generation', () => {
  // catalogId -> { taskId, status, done, total, queued, queuePosition }
  // 键存在即「该章节生成进行中」——按钮据此显示进度/排队态（坑 25）
  const scriptTasks = reactive({})
  const audioTasks = reactive({})
  // 任务中心跟踪集合 taskId -> { kind, catalogId, taskType, status, done, total,
  //   queuePosition, courseName, catalogTitle, error }；含刚终结的任务（供重试/查看）
  const tracked = reactive({})
  const completedTick = ref(0)
  const activeCount = computed(
    () => Object.values(tracked).filter((t) => t.status === 'pending' || t.status === 'running').length,
  )

  let pollTimer = null
  let restored = false

  // ---- 跟踪与状态推进 -------------------------------------------------------
  function trackTask(kind, catalogId, info) {
    tracked[info.taskId] = {
      kind,
      catalogId: Number(catalogId),
      taskType: info.taskType || (kind === 'script' ? 'script_gen' : 'audio_gen'),
      status: info.status || 'pending',
      done: info.done || 0,
      total: info.total || 0,
      queuePosition: info.queuePosition || null,
      courseName: info.courseName || '',
      catalogTitle: info.catalogTitle || '',
      error: info.error || '',
      fell: false,
    }
    syncBucket(kind, catalogId)
    ensurePolling()
  }

  // bucket（章节维度的按钮态）从 tracked 派生：同章节同 kind 取最新任务
  function syncBucket(kind, catalogId) {
    const map = bucket(kind) === 'scriptTasks' ? scriptTasks : audioTasks
    const task = Object.values(tracked)
      .filter((t) => t.kind === kind && t.catalogId === Number(catalogId))
      .sort((a, b) => b.taskId - a.taskId)[0]
    if (!task || task.status === 'success') {
      delete map[catalogId]
      return
    }
    map[catalogId] = {
      taskId: task.taskId,
      status: task.status,
      done: task.done,
      total: task.total,
      queued: task.status === 'pending',
      queuePosition: task.queuePosition,
      error: task.error,
    }
  }

  function applyDetail(taskId, detail) {
    const item = tracked[taskId]
    if (!item) return
    const progress = detail.progress || {}
    // 进度只增不减（轮询途中页面也可能在刷新数据）
    item.done = Math.max(item.done, Number(progress.done) || 0)
    item.total = item.total || Number(progress.total) || 0
    item.queuePosition = detail.queue_position ?? item.queuePosition
    item.status = detail.status
    if (detail.error) item.error = detail.error
    syncBucket(item.kind, item.catalogId)
  }

  function finishTask(taskId, detail) {
    const item = tracked[taskId]
    if (!item || item.fell) return
    item.fell = true
    item.status = detail.status
    const label = TYPE_LABEL[item.taskType] || '任务'
    if (detail.status === 'success') {
      completedTick.value += 1
      const total = Number((detail.progress || {}).total) || item.total
      ElMessage.success(item.kind === 'script' ? `已生成 ${total} 页讲解稿` : `已完成 ${total} 页配音`)
    } else {
      const reason = detail.error || (detail.status === 'cancelled' ? '已取消' : '生成失败')
      ElMessage.warning({ message: `${label}${reason}：可在任务中心重试`, duration: 6000, showClose: true })
    }
    syncBucket(item.kind, item.catalogId)
  }

  // ---- 节流轮询（C10）------------------------------------------------------
  function ensurePolling() {
    if (pollTimer || document.hidden) return
    pollTimer = setInterval(pollOnce, POLL_MS)
  }
  function stopPollingIfIdle() {
    const anyActive = Object.values(tracked).some(
      (t) => (t.status === 'pending' || t.status === 'running') && !t.fell,
    )
    if (!anyActive && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }
  async function pollOnce() {
    const ids = Object.keys(tracked).filter((id) => {
      const t = tracked[id]
      return !t.fell && (t.status === 'pending' || t.status === 'running')
    })
    if (!ids.length) {
      stopPollingIfIdle()
      return
    }
    await Promise.all(
      ids.map(async (id) => {
        try {
          const detail = await getAiTask(id)
          if (detail.status === 'success' || detail.status === 'failed' || detail.status === 'cancelled') {
            finishTask(id, detail)
          } else {
            applyDetail(id, detail)
          }
        } catch {
          /* 单任务轮询失败静默：下一轮再试 */
        }
      }),
    )
  }
  // 页面隐藏时暂停轮询，回前台立刻补一拍（C10 第二层）
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    } else {
      pollOnce()
      ensurePolling()
    }
  })

  // ---- 提交（连点防抖：键存在即忽略，服务端唯一索引兜底）--------------------
  function normalizeSubmit(kind, catalogId, res, taskType) {
    const isScript = kind === 'script'
    return {
      taskId: res.task_id,
      taskType,
      status: res.status || 'pending',
      done: isScript ? res.script_pages || 0 : res.audio_pages || 0,
      total: isScript ? res.pages || 0 : res.total_pages || 0,
      queuePosition: res.queue_position ?? null,
      dedupeHit: !!res.dedupe_hit,
    }
  }

  async function runScript(catalogId) {
    const id = Number(catalogId)
    if (scriptTasks[id]) return // 已在跟踪（连点防抖，T4）
    try {
      const res = await generateScript(id, {})
      const info = normalizeSubmit('script', id, res, 'script_gen')
      trackTask('script', id, info)
      if (info.dedupeHit) ElMessage.info('该章节已有进行中的讲稿任务')
      return res
    } catch (error) {
      return handleSubmitError(error, 'script', id)
    }
  }

  async function runAudio(catalogId) {
    const id = Number(catalogId)
    if (audioTasks[id]) return
    try {
      const res = await generateAudio(id, {})
      const info = normalizeSubmit('audio', id, res, 'audio_gen')
      trackTask('audio', id, info)
      if (info.dedupeHit) ElMessage.info('该章节已有进行中的配音任务')
      return res
    } catch (error) {
      return handleSubmitError(error, 'audio', id)
    }
  }

  // 409：两种语义——task_running（同 kind 的生成正在跑）并入继续跟踪；
  // wait_script（配音撞上讲稿，data.task_id 是讲稿任务）按 script kind 跟踪，
  // 让讲稿按钮推进度，配音按钮保持可点（不残留假态）。拦截器已全局静默。
  function handleSubmitError(error, kind, catalogId) {
    const data = error?.data || {}
    if (error?.code === 409 && data.task_id) {
      const isWaitScript = data.code === 'wait_script'
      trackTask(isWaitScript ? 'script' : kind, catalogId, {
        taskId: data.task_id,
        taskType: isWaitScript ? 'script_gen' : kind === 'script' ? 'script_gen' : 'audio_gen',
        status: 'running',
      })
      ElMessage.info(error.message || '任务正在进行中')
      return undefined
    }
    // 410（旧端点垫片）/400/网络错：拦截器已弹提示；不上抛——旧调用方按
    // 「提交后照常刷新」的契约使用本函数， rejection 会变成 unhandled
    return undefined
  }

  // ---- 任务中心操作 ---------------------------------------------------------
  async function cancelTask(taskId) {
    try {
      const res = await cancelAiTask(taskId)
      const item = tracked[taskId]
      if (item) {
        item.status = res.status
        item.queuePosition = null
        syncBucket(item.kind, item.catalogId)
      }
      stopPollingIfIdle()
    } catch {
      /* 拦截器已提示 */
    }
  }

  async function retryTask(taskId) {
    try {
      const res = await retryAiTask(taskId)
      const item = tracked[taskId]
      if (item) {
        item.status = res.status
        item.error = ''
        item.fell = false
        item.done = 0
        syncBucket(item.kind, item.catalogId)
        ensurePolling()
      }
    } catch {
      /* 拦截器已提示 */
    }
  }

  function dismissTask(taskId) {
    delete tracked[taskId]
  }

  // ---- 启动恢复：服务端是唯一真相（坑 22：先清旧前端续跑记录）--------------
  async function refreshActive() {
    try {
      const list = await listActiveAiTasks({ task_type: 'all' })
      for (const t of list || []) {
        if (!t.catalog || !(t.task_type === 'script_gen' || t.task_type === 'audio_gen')) continue
        const kind = t.task_type === 'script_gen' ? 'script' : 'audio'
        if (tracked[t.id]) continue
        trackTask(kind, t.catalog, {
          taskId: t.id,
          taskType: t.task_type,
          status: t.status,
          done: (t.progress || {}).done || 0,
          total: (t.progress || {}).total || 0,
          queuePosition: t.queue_position ?? null,
          courseName: t.course_name || '',
          catalogTitle: t.catalog_title || '',
        })
      }
    } catch {
      /* 未登录/网络错静默：下次提交或手动打开任务中心时再拉 */
    }
  }

  function restoreTasks() {
    if (restored) return
    restored = true
    // 一次性废掉旧前端的 localStorage 续跑记录（队列化后服务端即真相，
    // 旧记录只会让按钮显示过期页数；垫片删除前每次启动都清，幂等无害）
    try {
      localStorage.removeItem(LEGACY_KEY)
    } catch {
      /* 存储不可用时忽略 */
    }
    if (!localStorage.getItem('access_token')) return
    refreshActive()
  }

  return {
    scriptTasks,
    audioTasks,
    tracked,
    completedTick,
    activeCount,
    runScript,
    runAudio,
    restoreTasks,
    refreshActive,
    cancelTask,
    retryTask,
    dismissTask,
  }
})
