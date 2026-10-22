import { onUnmounted, ref } from 'vue'
import { getAiTask } from '@/api/ai-task'

// AI 异步任务轮询：提交后由本 composable 以固定间隔拉取任务状态，
// 终态（success/failed）或超时后自动停止。组件卸载时停止，避免泄漏。
const POLL_INTERVAL = 2500
const POLL_TIMEOUT = 10 * 60 * 1000
const TERMINAL = new Set(['success', 'failed'])

export function useAiTaskPolling() {
  const task = ref(null)
  let timer = null
  // 任务代数：切班/重新生成时递增，旧任务的迟到响应全部丢弃
  let seq = 0
  let startedAt = 0

  function stop() {
    // 递增代数：在途 tick 的迟到响应全部作废（防切班/卸载后旧任务写回）
    seq += 1
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function schedule(mySeq, taskId, handlers) {
    if (mySeq !== seq) return
    timer = setTimeout(() => tick(mySeq, taskId, handlers), POLL_INTERVAL)
  }

  async function tick(mySeq, taskId, handlers) {
    if (mySeq !== seq) return
    let data = null
    try {
      data = await getAiTask(taskId)
    } catch {
      // 网络抖动：任务仍在后台执行，保留现有状态下一轮再试
    }
    if (mySeq !== seq) return
    if (data) {
      task.value = data
      if (TERMINAL.has(data.status)) {
        stop()
        if (data.status === 'success') handlers.onSuccess?.(data)
        else handlers.onFailed?.(data)
        return
      }
    }
    if (Date.now() - startedAt > POLL_TIMEOUT) {
      // 服务重启会杀死后台线程但任务行停留在 running：超时兜底，避免无限轮询
      stop()
      const timedOut = {
        ...(task.value || { id: taskId }),
        status: 'failed',
        error: '分析超时（超过 10 分钟），请重试',
      }
      task.value = timedOut
      handlers.onFailed?.(timedOut)
      return
    }
    schedule(mySeq, taskId, handlers)
  }

  /**
   * 开始轮询一个任务。重复调用会取消上一轮的轮询。
   * @param {number} taskId
   * @param {{ onSuccess?: Function, onFailed?: Function }} handlers
   */
  function start(taskId, handlers = {}) {
    // 顺序要紧：先 stop() 停旧轮询（其递增的代数令在途 tick 的迟到响应作废），
    // 再开新代数——若先取 mySeq 再 stop()，schedule 的代数守卫会永远成立，
    // 首个 tick 永远不会被调度（轮询静默失效，P2f E2E 实证：后端零请求）。
    stop()
    seq += 1
    const mySeq = seq
    task.value = null
    startedAt = Date.now()
    schedule(mySeq, taskId, handlers)
  }

  onUnmounted(stop)

  return { task, start, stop }
}
