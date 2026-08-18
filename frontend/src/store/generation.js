import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { generateScript, generateAudio } from '@/api/course'

const SCRIPT_BATCH_SIZE = 6
const AUDIO_BATCH_SIZE = 3

/**
 * 全局 AI 生成任务（讲解稿/配音分批循环）。
 *
 * 循环放在 store 而非组件中执行：路由切换导致组件卸载时，分批循环继续进行、
 * 进度状态保留；返回页面后按钮仍实时显示「讲稿 x/y」「配音 x/y」。
 * 每批结果由后端落库，即使浏览器关闭也不丢已生成进度（增量续传）。
 */
export const useGenerationStore = defineStore('generation', () => {
  // catalogId -> { done, total }；键存在即任务进行中
  const scriptTasks = reactive({})
  const audioTasks = reactive({})

  async function runScript(catalogId) {
    const id = Number(catalogId)
    if (scriptTasks[id]) return
    scriptTasks[id] = { done: 0, total: 0 }
    try {
      for (;;) {
        const res = await generateScript(id, { limit: SCRIPT_BATCH_SIZE })
        scriptTasks[id] = { done: res.script_pages, total: res.pages }
        if (res.done) break
      }
      ElMessage.success(`已生成 ${scriptTasks[id].total} 页讲解稿`)
    } catch {
      // 拦截器已弹接口错误，这里补充进度说明（增量语义，可安全重试）
      const p = scriptTasks[id] || { done: 0, total: 0 }
      ElMessage.warning(`讲解稿生成中断：已完成 ${p.done}/${p.total} 页，可再次点击继续`)
    } finally {
      delete scriptTasks[id]
    }
  }

  async function runAudio(catalogId) {
    const id = Number(catalogId)
    if (audioTasks[id]) return
    audioTasks[id] = { done: 0, total: 0 }
    try {
      for (;;) {
        const res = await generateAudio(id, AUDIO_BATCH_SIZE)
        audioTasks[id] = { done: res.audio_pages, total: res.total_pages }
        if (res.done) break
      }
      ElMessage.success(`已完成 ${audioTasks[id].total} 页配音`)
    } catch {
      const p = audioTasks[id] || { done: 0, total: 0 }
      ElMessage.warning(`配音中断：已完成 ${p.done}/${p.total} 页，可再次点击「配音」继续补齐`)
    } finally {
      delete audioTasks[id]
    }
  }

  return { scriptTasks, audioTasks, runScript, runAudio }
})
