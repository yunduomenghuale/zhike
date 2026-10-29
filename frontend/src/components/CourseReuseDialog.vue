<template>
  <el-dialog
    v-model="visible"
    width="680px"
    align-center
    :show-close="false"
    :close-on-click-modal="!running"
    class="reuse-dialog"
    @closed="handleClosed"
  >
    <template #header>
      <div class="reuse-head">
        <span class="reuse-head-icon">
          <el-icon><CopyDocument /></el-icon>
        </span>
        <div class="reuse-head-text">
          <div class="reuse-title">复用课程</div>
          <div class="reuse-subtitle">
            {{ course?.name || '' }}
            <span v-if="course?.term"> · {{ course.term }}</span>
          </div>
        </div>
        <el-button text circle class="reuse-close" :icon="Close" @click="close" />
      </div>
    </template>

    <div class="reuse-body">
      <TableSkeleton v-if="loading" :rows="4" />

      <el-alert
        v-else-if="loadError"
        type="error"
        show-icon
        :closable="false"
        :title="loadError"
        class="reuse-alert"
      >
        <el-button link type="primary" @click="loadPreview">重试</el-button>
      </el-alert>

      <!-- 步骤一：确认要复制的资产与目标课程 -->
      <template v-else-if="step === 'form'">
        <section class="asset-block">
          <div class="asset-head">
            <span class="asset-title">将复制的资产</span>
            <span class="asset-size">约 {{ preview?.assets?.media_human || '0 B' }}</span>
          </div>
          <div class="asset-grid">
            <div v-for="item in assetRows" :key="item.key" class="asset-item">
              <span class="asset-value">{{ item.value }}</span>
              <span class="asset-label">{{ item.label }}</span>
            </div>
          </div>
          <div class="asset-note">
            复制为独立副本（课件文件、页图、配音、资料逐份拷贝），删除原课程不影响新课程；
            知识库片段连同向量一并带走，复用后立即可检索，不再重复嵌入计费。
          </div>
        </section>

        <el-form label-position="top" class="reuse-form">
          <el-form-item label="新课程名称">
            <el-input v-model="form.name" maxlength="200" show-word-limit placeholder="请输入新课程名称" />
          </el-form-item>
          <div class="reuse-form-row">
            <el-form-item label="学期">
              <el-select v-model="form.termId" placeholder="沿用原课程学期" clearable class="reuse-select">
                <el-option v-for="term in terms" :key="term.id" :label="term.name" :value="term.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="题库">
              <label class="reuse-check">
                <el-checkbox v-model="form.includeQuestions" :disabled="!questionCount" />
                <span class="reuse-check-text">
                  一并复制 {{ questionCount }} 道题
                  <em v-if="!questionCount">（本课程暂无题目）</em>
                </span>
              </label>
            </el-form-item>
          </div>
        </el-form>

        <el-alert
          type="info"
          show-icon
          :closable="false"
          class="reuse-tip"
          title="复用产物默认「停用」：教师核对无误后再启用，学生端才会出现这门课"
        />
      </template>

      <!-- 步骤二：任务执行中 -->
      <template v-else-if="step === 'running'">
        <div class="reuse-progress">
          <div class="progress-mark">
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>
          <div class="progress-main">
            <div class="progress-title">{{ progressText }}</div>
            <el-progress :percentage="overallPercent" :show-text="false" :stroke-width="8" />
            <div class="progress-sub">
              {{ runningHint }}
            </div>
          </div>
        </div>
      </template>

      <!-- 步骤三：完成 -->
      <template v-else-if="step === 'done'">
        <div class="reuse-result">
          <div class="result-mark">
            <el-icon><Select /></el-icon>
          </div>
          <div class="result-main">
            <div class="result-title">复用完成：{{ result?.course_name }}</div>
            <div class="result-sub">
              {{ resultSummary }}
            </div>
            <div class="result-sub">新课程为「停用」状态，确认内容无误后启用即可对学生开放。</div>
          </div>
        </div>
      </template>

      <!-- 步骤四：失败 -->
      <template v-else>
        <el-alert
          type="error"
          show-icon
          :closable="false"
          :title="failMessage"
          class="reuse-alert"
          description="已回滚：不会留下半成品课程，也不会残留复制的文件。可调整后重试。"
        />
      </template>
    </div>

    <template #footer>
      <div class="reuse-footer">
        <template v-if="step === 'form'">
          <el-button @click="close">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submit">开始复用</el-button>
        </template>
        <template v-else-if="step === 'running'">
          <span class="footer-hint">任务在后台继续，关闭弹窗不影响执行</span>
          <el-button @click="close">关闭</el-button>
        </template>
        <template v-else-if="step === 'done'">
          <el-button @click="close">关闭</el-button>
          <el-button type="primary" @click="goCourse">查看新课程</el-button>
        </template>
        <template v-else>
          <el-button @click="close">关闭</el-button>
          <el-button type="primary" @click="step = 'form'">返回修改</el-button>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Close, CopyDocument, Loading, Select } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import TableSkeleton from '@/components/TableSkeleton.vue'
import { getReusePreview, reuseCourse } from '@/api/course'
import { useAiTaskPolling } from '@/composables/useAiTaskPolling'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  course: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'done'])

const router = useRouter()
const { task, start: startPolling, stop: stopPolling } = useAiTaskPolling()

const step = ref('form') // form | running | done | failed
const loading = ref(false)
const loadError = ref('')
const submitting = ref(false)
const preview = ref(null)

const form = reactive({ name: '', termId: null, includeQuestions: false })

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const running = computed(() => step.value === 'running')

const terms = computed(() => preview.value?.terms || [])
const questionCount = computed(() => preview.value?.assets?.question_count || 0)

const assetRows = computed(() => {
  const a = preview.value?.assets || {}
  return [
    { key: 'catalog', label: '章节', value: a.catalog_count || 0 },
    { key: 'ppt', label: '课件', value: a.ppt_count || 0 },
    { key: 'pages', label: '课件页', value: a.ppt_pages || 0 },
    { key: 'script', label: '讲稿页', value: a.script_pages || 0 },
    { key: 'audio', label: '配音', value: a.audio_count || 0 },
    { key: 'material', label: '教辅资料', value: a.material_count || 0 },
    { key: 'chunk', label: '知识库片段', value: a.chunk_count || 0 },
    { key: 'resource', label: '教学资源', value: a.resource_count || 0 },
  ]
})

// 阶段顺序与后端 reuse.py 的 report() 调用一致；用于把「每阶段各自的 done/total」
// 折算成一条整体进度条（否则进度条会在切阶段时回退，看着像卡住）
const STAGE_ORDER = ['catalog', 'ppt', 'video', 'material', 'chunk', 'resource', 'question']
const STAGE_LABEL = {
  catalog: '复制章节结构',
  ppt: '复制课件与页图',
  video: '复制讲稿与配音',
  material: '复制教辅资料',
  chunk: '复制知识库片段',
  resource: '复制教学资源',
  question: '复制题目',
  done: '完成',
}

const stageList = computed(() => {
  const stages = STAGE_ORDER.filter((s) => s !== 'question')
  return form.includeQuestions ? [...stages, 'question'] : stages
})

const progressStage = computed(() => task.value?.progress?.stage || '')
const progressText = computed(
  () => task.value?.progress?.message || STAGE_LABEL[progressStage.value] || '正在准备…',
)

const overallPercent = computed(() => {
  if (step.value === 'done' || progressStage.value === 'done') return 100
  const index = stageList.value.indexOf(progressStage.value)
  const base = index < 0 ? 0 : index
  const progress = task.value?.progress || {}
  const fraction = progress.total ? Math.min(1, (progress.done || 0) / progress.total) : 0
  return Math.min(99, Math.round(((base + fraction) / stageList.value.length) * 100))
})

const runningHint = computed(() => {
  const progress = task.value?.progress || {}
  if (progress.total) return `第 ${progress.done} / ${progress.total} 项`
  return '正在分配任务…'
})

const result = computed(() => task.value?.result || null)

const resultSummary = computed(() => {
  const copied = result.value?.copied || {}
  const parts = [
    copied.catalog ? `${copied.catalog} 个章节` : '',
    copied.ppt ? `${copied.ppt} 个课件` : '',
    copied.video ? `${copied.video} 份讲稿` : '',
    copied.material ? `${copied.material} 份资料` : '',
    copied.chunk ? `${copied.chunk} 条片段` : '',
    copied.resource ? `${copied.resource} 个资源` : '',
    copied.question ? `${copied.question} 道题` : '',
  ].filter(Boolean)
  const size = result.value?.media_human ? `，占用 ${result.value.media_human}` : ''
  return parts.length ? `${parts.join('、')}${size}` : `复制完成${size}`
})

const failMessage = computed(
  () => task.value?.error || '复用失败，请稍后重试',
)

function close() {
  visible.value = false
}

function handleClosed() {
  stopPolling()
  if (step.value === 'done') emit('done')
  step.value = 'form'
  loadError.value = ''
  preview.value = null
}

async function loadPreview() {
  if (!props.course?.id) return
  loading.value = true
  loadError.value = ''
  try {
    const data = await getReusePreview(props.course.id)
    preview.value = data
    form.name = data.default_name || `${data.course?.name || ''}（复用）`
    form.termId = data.course?.term_id ?? null
    form.includeQuestions = (data.assets?.question_count || 0) > 0
  } catch (error) {
    loadError.value = error?.message || '资产清单加载失败'
  } finally {
    loading.value = false
  }
}

function onSuccess(data) {
  step.value = 'done'
  ElMessage.success(`${data?.result?.course_name || '新课程'} 复用完成`)
  emit('done')
}

function onFailed(data) {
  step.value = 'failed'
  ElMessage.error(data?.error || '复用失败')
}

async function submit() {
  const name = form.name.trim()
  if (!name) return ElMessage.warning('请填写新课程名称')
  submitting.value = true
  step.value = 'running'
  try {
    const res = await reuseCourse(props.course.id, {
      name,
      term_id: form.termId,
      include_questions: form.includeQuestions,
    })
    startPolling(res.task_id, { onSuccess, onFailed })
  } catch (error) {
    // 409 = 该课程已有复用任务在跑：直接接上那一条，不要把用户挡在外面
    if (error?.code === 409 && error?.data?.task_id) {
      ElMessage.info('该课程已有复用任务在执行，正在显示它的进度')
      startPolling(error.data.task_id, { onSuccess, onFailed })
    } else {
      step.value = 'form'
    }
  } finally {
    submitting.value = false
  }
}

function goCourse() {
  const id = result.value?.course_id
  visible.value = false
  if (id) router.push({ name: 'course-chapters', params: { id } })
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      step.value = 'form'
      form.includeQuestions = false
      loadPreview()
    }
  },
)
</script>

<style scoped>
.reuse-dialog :deep(.el-dialog),
:global(.reuse-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 20px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

/* 头部/底部/主体都由本组件自己排版，EP 的默认内边距会叠出一圈多余留白 */
.reuse-dialog :deep(.el-dialog__header),
:global(.reuse-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}

.reuse-dialog :deep(.el-dialog__body),
:global(.reuse-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}

.reuse-dialog :deep(.el-dialog__footer),
:global(.reuse-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}

.reuse-head {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 84px;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 60%);
}

.reuse-head-icon {
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: #eaf2ff;
  color: var(--primary-600);
  font-size: 21px;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}

.reuse-head-text {
  min-width: 0;
  flex: 1;
}

.reuse-title {
  color: #0f172a;
  font-size: 19px;
  font-weight: 760;
  line-height: 1.25;
}

.reuse-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reuse-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
}

.reuse-body {
  padding: 20px 24px 4px;
  max-height: 62vh;
  overflow-y: auto;
}

.asset-block {
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  padding: 14px 16px 12px;
  background: #fbfdff;
}

.asset-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.asset-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-900);
}

.asset-size {
  font-size: 13px;
  font-weight: 650;
  color: var(--primary-600);
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.asset-item {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(226, 232, 240, 0.9);
  min-width: 0;
}

.asset-value {
  font-size: 18px;
  font-weight: 760;
  line-height: 1.1;
  color: var(--gray-900);
  font-variant-numeric: tabular-nums;
}

.asset-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.reuse-form {
  margin-top: 16px;
}

.reuse-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.reuse-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

.reuse-form-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 16px;
}

.reuse-select {
  width: 100%;
}

.reuse-check {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  cursor: pointer;
}

.reuse-check-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.reuse-check-text em {
  font-style: normal;
  color: var(--el-text-color-placeholder);
}

.reuse-tip {
  margin-top: 2px;
}

.reuse-alert {
  margin-bottom: 12px;
}

.reuse-progress,
.reuse-result {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 22px 4px 26px;
}

.progress-mark,
.result-mark {
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  font-size: 22px;
}

.progress-mark {
  background: var(--el-color-primary-light-9);
  color: var(--primary-600);
}

.result-mark {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.progress-main,
.result-main {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 8px;
}

.progress-title,
.result-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--gray-900);
}

.progress-sub,
.result-sub {
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.reuse-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 24px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}

.footer-hint {
  margin-right: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .reuse-dialog :deep(.el-dialog) {
    width: calc(100% - 28px) !important;
  }

  .asset-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .reuse-form-row {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
