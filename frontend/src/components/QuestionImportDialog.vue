<template>
  <!--
    文档导入弹窗：上传题目文档 → 后端规则解析 → 建草稿批次。
    导入成功后由父层打开 QuestionDraftPreview 预览编辑入库。
  -->
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => emit('update:visible', v)"
    width="560px"
    align-center
    class="import-dialog"
    :show-close="false"
    :close-on-click-modal="false"
  >
    <template #header>
      <div class="creation-dialog-header">
        <span class="creation-dialog-icon import-create-icon"><el-icon><UploadFilled /></el-icon></span>
        <div class="creation-dialog-heading">
          <div class="creation-dialog-title">导入题目文档</div>
          <div class="creation-dialog-subtitle">上传文档，系统解析为可编辑的题目草稿</div>
        </div>
        <el-button text circle class="creation-dialog-close" :icon="Close" @click="emit('update:visible', false)" />
      </div>
    </template>

    <div class="import-body">
      <!-- 课程上下文：导入操作已在某课程下，自动关联无需选择（原「目标课程」字段已移除） -->
      <div class="import-course-hint">
        <el-icon><School /></el-icon>
        <span>导入到课程：<b>{{ courseName || '当前课程' }}</b>（自动关联当前课程）</span>
      </div>
      <el-form label-position="top" class="import-form">
        <el-form-item label="目标章节（可选）">
          <el-select v-model="catalog" class="module-select" popper-class="module-select-popper" placeholder="可稍后在预览中设置，不影响解析" style="width: 100%" clearable :disabled="!!task">
            <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途分类">
          <el-select
            v-model="scenes"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="2"
            class="module-select"
            popper-class="module-select-popper"
            placeholder="导入的题目默认用于哪些场景"
            style="width: 100%"
            :disabled="!!task"
          >
            <el-option v-for="s in SCENE_OPTIONS" :key="s.code" :label="s.label" :value="s.code" />
          </el-select>
          <div class="import-scenes-tip">默认「章节练习+作业」；如导入的是试卷请勾选「考试」，考试题不会出现在学生练习中</div>
        </el-form-item>
        <el-form-item label="题目文件">
          <!-- 选择即上传解析，样式与流程对齐章节课件上传（CourseCatalog .ppt-upload） -->
          <el-upload
            drag
            :show-file-list="false"
            :before-upload="handleFile"
            accept=".pdf,.doc,.docx,.txt,.md"
            :disabled="!!task"
            class="import-uploader"
          >
            <div class="import-upload-inner">
              <div class="import-upload-icon">
                <el-icon><UploadFilled /></el-icon>
              </div>
              <div class="import-upload-title">{{ task ? '正在上传解析…' : '拖入或选择题目文件' }}</div>
              <div class="import-upload-desc">支持 pdf / doc / docx / txt / md，单个文件不超过 10MB</div>
            </div>
          </el-upload>
          <div v-if="task" class="import-upload-progress">
            <div class="import-upload-progress-head">
              <span class="import-upload-progress-stage">
                <el-icon v-if="task.phase !== 'done' && task.phase !== 'failed'" class="is-loading"><Loading /></el-icon>
                {{ stageText }}
              </span>
            </div>
            <div class="import-upload-progress-bar-row">
              <el-progress
                class="import-upload-progress-bar"
                :percentage="progressPercent"
                :stroke-width="10"
                :show-text="false"
                :status="task.phase === 'failed' ? 'exception' : undefined"
              />
              <span
                v-if="progressNum"
                class="import-upload-progress-num"
                :class="{ 'is-failed': task.phase === 'failed' }"
              >{{ progressNum }}</span>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <div class="import-hint">
        <el-icon class="import-hint-icon"><InfoFilled /></el-icon>
        <span>建议文档包含题号、选项、答案等结构（如「1. 题干 / A. 选项 / 答案：A」）；解析为<b>草稿</b>后可在预览中逐题编辑、核对告警，确认后再批量入库，上传文件在题目入库后自动删除。</span>
      </div>
    </div>

    <template #footer>
      <div class="creation-dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, InfoFilled, Loading, School, UploadFilled } from '@element-plus/icons-vue'
import { importQuestions } from '@/api/question'
import { DEFAULT_SCENES, SCENE_OPTIONS } from '@/utils/questionDraft'

const SUPPORTED_EXT = ['.pdf', '.doc', '.docx', '.txt', '.md']
const MAX_SIZE = 10 * 1024 * 1024

const props = defineProps({
  visible: { type: Boolean, default: false },
  courseId: { type: [Number, String], default: null },
  courseName: { type: String, default: '' },
  catalogs: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'imported'])

const catalog = ref(null)
const scenes = ref([...DEFAULT_SCENES])
// 上传解析任务（对齐课件上传的 uploadTasks 单任务口径）：选择即上传，阶段化进度
const task = ref(null) // { phase: 'upload'|'parse'|'done'|'failed', percent, error }

watch(() => props.visible, (v) => {
  if (v) {
    catalog.value = null
    scenes.value = [...DEFAULT_SCENES]
    task.value = null
  }
})

const stageText = computed(() => {
  switch (task.value?.phase) {
    case 'upload': return '正在上传题目文件…'
    case 'parse': return '正在解析题目结构…'
    case 'done': return '解析完成'
    case 'failed': {
      const err = task.value?.error
      return err ? `解析失败：${err}` : '解析失败'
    }
    default: return '正在处理…'
  }
})
const progressPercent = computed(() => {
  const t = task.value
  if (!t) return 0
  if (t.phase === 'done' || t.phase === 'failed') return 100
  if (t.phase === 'parse') return 99
  return t.percent
})
const progressNum = computed(() => {
  const t = task.value
  if (!t || t.phase !== 'upload') return ''
  return `${t.percent}%`
})

// 选择即上传解析（before-upload 返回 false 阻断 el-upload 自带请求，与课件上传同模式）
function handleFile(raw) {
  const ext = '.' + (raw.name.split('.').pop() || '').toLowerCase()
  if (!SUPPORTED_EXT.includes(ext)) {
    ElMessage.warning(`暂不支持该文件格式，支持：${SUPPORTED_EXT.join(' / ')}`)
    return false
  }
  if (raw.size > MAX_SIZE) {
    ElMessage.warning('文件超过 10MB 上限，请压缩或拆分后重试')
    return false
  }
  if (!props.courseId) {
    ElMessage.warning('请先选择课程')
    return false
  }
  startImport(raw)
  return false
}

async function startImport(raw) {
  task.value = { phase: 'upload', percent: 0, error: '' }
  const form = new FormData()
  form.append('file', raw)
  form.append('course', props.courseId)
  if (catalog.value) form.append('catalog', catalog.value)
  if (scenes.value.length) form.append('scenes', JSON.stringify(scenes.value))
  try {
    const batch = await importQuestions(form, (e) => {
      const t = task.value
      if (!t || !e.total) return
      t.percent = Math.min(99, Math.round((e.loaded / e.total) * 100))
      if (e.loaded >= e.total && t.phase === 'upload') {
        t.phase = 'parse' // 字节传完，进入服务端解析
      }
    })
    if (task.value) {
      task.value.phase = 'done'
      task.value.percent = 100
    }
    ElMessage.success(`已识别 ${batch.drafts?.length || 0} 道题目，请预览编辑后入库`)
    emit('imported', batch)
    emit('update:visible', false)
  } catch (err) {
    // 错误消息由 request 拦截器统一提示；进度面板同步失败态，短暂展示后复位
    const message = err?.response?.data?.message || err?.message || '请重试'
    if (task.value) {
      task.value.phase = 'failed'
      task.value.error = message
    }
    await new Promise((resolve) => setTimeout(resolve, 1600))
    task.value = null
  }
}
</script>

<style scoped>
.import-dialog :deep(.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.import-dialog :deep(.el-dialog__header) {
  margin: 0;
  padding: 0;
}
.import-dialog :deep(.el-dialog__body) {
  padding: 0;
}
.import-dialog :deep(.el-dialog__footer) {
  padding: 0;
}

.import-body {
  padding: 16px 22px 18px;
}
.import-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.import-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

/* 课程提示行（导入到课程，自动关联） */
.import-course-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
  padding: 9px 13px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #475569;
  font-size: 13px;
}
.import-course-hint b {
  color: #0f172a;
  font-weight: 700;
}
.import-course-hint .el-icon {
  flex: 0 0 auto;
  font-size: 15px;
  color: var(--primary-600);
}
.import-scenes-tip {
  margin-top: 6px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

/* 上传区：样式与流程对齐章节课件上传（CourseCatalog .ppt-upload 体系） */
.import-uploader {
  width: 100%;
}
.import-uploader :deep(.el-upload) {
  width: 100%;
}
.import-uploader :deep(.el-upload-dragger) {
  width: 100%;
  height: 176px;
  border-radius: 8px;
  border: 1px dashed var(--el-color-primary-light-3);
  background: linear-gradient(180deg, #ffffff 0%, var(--el-color-primary-light-9) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.import-uploader :deep(.el-upload-dragger:hover) {
  border-color: var(--el-color-primary);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}
.import-upload-inner {
  display: grid;
  justify-items: center;
  gap: 8px;
}
.import-upload-icon {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
  font-size: 24px;
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(15, 23, 42, 0.08));
}
.import-upload-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.import-upload-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* 进度面板：对齐 .ppt-upload-progress */
.import-upload-progress {
  margin-top: 12px;
  padding: 12px 14px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.import-upload-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.import-upload-progress-stage {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.import-upload-progress-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.import-upload-progress-bar {
  flex: 1;
  min-width: 0;
}
.import-upload-progress-num {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
  color: var(--el-color-primary);
}
.import-upload-progress-num.is-failed {
  color: var(--el-color-danger);
}

.import-hint {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 14px;
  padding: 11px 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.9), rgba(219, 234, 254, 0.5));
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
}
.import-hint b { color: var(--primary-700); font-weight: 700; }
.import-hint-icon { flex: 0 0 auto; font-size: 17px; color: var(--primary-600); margin-top: 2px; }

.import-create-icon {
  color: #fff;
  background: linear-gradient(140deg, #34d399, #059669);
  box-shadow: 0 10px 20px rgba(5, 150, 105, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 66px;
  padding: 15px 22px 13px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.creation-dialog-icon {
  width: 38px;
  height: 38px;
  display: grid;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  font-size: 18px;
}
.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}
.creation-dialog-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 760;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12.5px;
  line-height: 1.3;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 22px 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}
.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}
</style>
