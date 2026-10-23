<template>
  <div class="page-container">
    <el-card shadow="never" class="data-card q-card">
      <!-- AI 生题进行中恢复横幅（离开页面不丢失：轮询继续，仅隐藏横幅） -->
      <el-alert
        v-if="aiTask && !isTerminal(aiTask.status) && !bannerHidden"
        class="ai-active-banner"
        type="info"
        :closable="true"
        @close="bannerHidden = true"
      >
        <template #title>
          <span class="ai-active-title">AI 生题进行中</span>
          <span class="ai-active-msg">{{ aiTask.progress?.message || '任务排队中…' }}</span>
        </template>
        <div class="ai-active-progress">
          <el-progress
            :percentage="progressPercent"
            :stroke-width="8"
            :show-text="true"
            :text-inside="true"
          />
          <span class="ai-active-tip">生成过程中离开页面不会丢失，完成后自动打开预览</span>
        </div>
      </el-alert>

      <div class="q-toolbar">
        <div class="q-toolbar-left">
          <el-select v-if="!inCourseWorkspace" v-model="courseId" size="large" class="module-select" popper-class="module-select-popper" placeholder="选择课程" style="width: 220px" @change="handleCourseChange">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="filterCatalog" size="large" class="module-select" popper-class="module-select-popper" placeholder="章节" clearable style="width: 170px" @change="load">
            <el-option v-for="c in flatCatalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
          <el-select v-model="filterType" size="large" class="module-select" popper-class="module-select-popper" placeholder="题型" clearable style="width: 130px" @change="load">
            <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
          <el-select v-model="filterStatus" size="large" class="module-select" popper-class="module-select-popper" placeholder="状态" clearable style="width: 130px" @change="load">
            <el-option label="草稿" value="draft" />
            <el-option label="已发布" value="published" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </div>
        <div class="q-toolbar-actions">
          <el-button v-if="courseId" class="q-btn-batch" :icon="Files" @click="openBatches">
            草稿批次<el-badge v-if="batchCount" :value="batchCount" class="q-batch-badge" type="primary" />
          </el-button>
          <el-button v-if="courseId" class="q-btn-ai" :icon="MagicStick" @click="aiGenVisible = true">AI 生成</el-button>
          <el-button v-if="courseId" class="q-btn-import" :icon="UploadFilled" @click="importVisible = true">导入题目</el-button>
          <el-button v-if="courseId" class="q-btn-primary" type="primary" :icon="Plus" @click="openEdit()">新建题目</el-button>
        </div>
      </div>

      <el-empty v-if="!courseId" :image-size="110">
        <template #description>
          <div class="empty-text">请先选择课程</div>
          <div class="empty-tip">选择课程后即可维护题库、AI 出题</div>
        </template>
      </el-empty>
      <template v-else>
        <TableSkeleton v-if="loading" :cols="6" />
        <el-empty v-else-if="!rows.length" :image-size="110">
          <template #description>
            <div class="empty-text">还没有题目</div>
            <div class="empty-tip">点击右上角「新建题目」「导入题目」或「AI 生成」开始建题</div>
          </template>
        </el-empty>
        <div v-else class="q-list animate-list">
          <div v-for="row in rows" :key="row.id" class="q-row">
            <div class="q-row-left">
              <span class="q-type-badge" :class="'qt-' + row.qtype">{{ row.qtype_display }}</span>
              <div class="q-copy">
                <div class="q-stem">{{ row.stem }}</div>
                <div class="q-meta">
                  <el-tag size="small" :type="difficultyTag(row.difficulty)" effect="light" round>{{ row.difficulty_display }}</el-tag>
                  <el-tag size="small" effect="plain" round>{{ row.catalog_title }}</el-tag>
                  <span class="q-score">{{ row.score }} 分</span>
                  <el-tag size="small" :type="statusTag(row.status)" effect="light" round>{{ row.status_display }}</el-tag>
                  <el-tag size="small" :type="sourceTag(row.source)[1]" effect="plain" round>
                    {{ sourceTag(row.source)[0] }}
                  </el-tag>
                </div>
              </div>
            </div>
            <div class="q-action-group">
              <button class="q-action-btn" @click="openEdit(row)"><el-icon><EditPen /></el-icon> 编辑</button>
              <button v-if="row.status !== 'published'" class="q-action-btn success" @click="setStatus(row, 'published')">
                <el-icon><Promotion /></el-icon> 发布
              </button>
              <button v-else class="q-action-btn muted" @click="setStatus(row, 'disabled')">
                <el-icon><Remove /></el-icon> 停用
              </button>
              <button class="q-action-btn danger" @click="openDelete(row)">
                <el-icon><Delete /></el-icon> 删除
              </button>
            </div>
          </div>
        </div>
        <el-pagination
          v-if="total > pageSize"
          class="pager"
          layout="prev, pager, next, total"
          :total="total" :page-size="pageSize" :current-page="page"
          @current-change="(p) => { page = p; load() }"
        />
      </template>
    </el-card>

    <!-- 新建/编辑题目（表单字段组件化，与草稿预览共用） -->
    <el-dialog v-model="editVisible" width="760px" align-center :show-close="false" class="question-form-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon question-create-icon"><el-icon><EditPen /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ form.id ? '编辑题目' : '新建题目' }}</div>
            <div class="creation-dialog-subtitle">题目基础信息</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="editVisible = false" />
        </div>
      </template>

      <!-- 表单字段组件化（与草稿预览共用）；el-form 容器已内置，此处仅作滚动区 -->
      <div class="question-creation-form">
        <QuestionFormFields ref="formFields" :model="form" :catalogs="flatCatalogs" show-catalog label-position="top" />
      </div>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="editVisible = false">取消</el-button>
          <el-button :loading="saving" @click="save(false)">{{ form.id ? '保存修改' : '创建题目' }}</el-button>
          <el-button v-if="!form.id || form.status !== 'published'" type="primary" :loading="saving" @click="save(true)">
            {{ form.id ? '保存并发布' : '创建并发布' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除题目"
      :item-name="deleteTarget?.stem"
      description="删除后，该题目将无法用于组卷或作业，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 草稿批次列表（文档导入 / AI 生题待入库池） -->
    <el-dialog v-model="batchesVisible" width="680px" align-center class="batch-dialog" :show-close="false">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon batch-create-icon"><el-icon><Files /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">草稿批次</div>
            <div class="creation-dialog-subtitle">导入 / AI 生成的待入库题目，离开页面也不会丢失</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="batchesVisible = false" />
        </div>
      </template>
      <div v-if="batchesLoading" class="batch-body"><el-skeleton :rows="3" animated /></div>
      <el-empty v-else-if="!batches.length" description="暂无待入库的草稿批次" :image-size="90" />
      <div v-else class="batch-list">
        <div v-for="b in batches" :key="b.id" class="batch-row">
          <div class="batch-row-main">
            <el-tag size="small" :type="b.origin === 'ai_gen' ? 'primary' : 'info'" effect="light" round>
              {{ b.origin === 'ai_gen' ? 'AI 生成' : '文档导入' }}
            </el-tag>
            <span class="batch-row-title">{{ b.catalog_title || '未设置章节' }}</span>
            <span class="batch-row-meta">{{ b.drafts?.length || 0 }} 题待入库</span>
            <span v-if="b.file_name" class="batch-row-meta" :title="b.file_name">{{ b.file_name }}</span>
          </div>
          <div class="batch-row-actions">
            <el-button link type="primary" @click="openPreview(b.id)">预览并入库</el-button>
            <el-button link type="danger" @click="discardBatch(b)">放弃</el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 导入题目 -->
    <QuestionImportDialog
      v-model:visible="importVisible"
      :course-id="courseId"
      :course-name="currentCourseName"
      :catalogs="flatCatalogs"
      @imported="onImported"
    />

    <!-- AI 多类型生题 -->
    <QuestionAiGenerateDialog
      v-model:visible="aiGenVisible"
      :course-id="courseId"
      :catalogs="flatCatalogs"
      @submitted="onAiSubmitted"
    />

    <!-- 草稿批次预览编辑与入库（导入 / AI 共用） -->
    <QuestionDraftPreview
      v-model:visible="previewVisible"
      :batch-id="previewBatchId"
      :catalogs="flatCatalogs"
      @saved="onBatchSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Delete, EditPen, MagicStick, Promotion, Remove, Close, Files, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import QuestionFormFields from '@/components/QuestionFormFields.vue'
import QuestionDraftPreview from '@/components/QuestionDraftPreview.vue'
import QuestionImportDialog from '@/components/QuestionImportDialog.vue'
import QuestionAiGenerateDialog from '@/components/QuestionAiGenerateDialog.vue'
import { useAiTaskPolling } from '@/composables/useAiTaskPolling'
import { listActiveAiTasks } from '@/api/ai-task'
import { listCourses, listCatalogs } from '@/api/course'
import { listQuestions, createQuestion, updateQuestion, deleteQuestion, listDraftBatches } from '@/api/question'
import { draftToForm } from '@/utils/questionDraft'

const qtypes = [
  { value: 'single', label: '单选题' },
  { value: 'multi', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
]

const route = useRoute()
const courses = ref([])
const courseId = ref(null)
const fixedCourseId = computed(() => Number(route.params.id) || null)
const inCourseWorkspace = computed(() => Boolean(fixedCourseId.value))
const rows = ref([])
const loading = ref(false)
const filterType = ref('')
const filterStatus = ref('')
const filterCatalog = ref(null)
const search = ref(String(route.query.search || ''))
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

const flatCatalogs = ref([]) // 扁平化章节：[{id, label}]
const currentCourseName = computed(() => courses.value.find((c) => c.id === courseId.value)?.name || '')

function difficultyTag(d) {
  return { easy: 'success', medium: 'warning', hard: 'danger' }[d] || 'info'
}
function statusTag(s) {
  return { published: 'success', disabled: 'info', draft: 'warning', pending: 'warning' }[s] || 'info'
}
// 题目来源三态：AI 生成 / 文档导入 / 手动录入
function sourceTag(s) {
  if (s === 'ai') return ['AI 生成', 'primary']
  if (s === 'import') return ['文档导入', 'warning']
  return ['手动录入', 'info']
}

async function loadCourses() {
  // 两个分支都加载课程列表：课程工作台视图（fixedCourseId）也要取课程名（导入提示行等场景）
  const data = await listCourses()
  courses.value = data.results ?? data
  if (fixedCourseId.value) {
    courseId.value = fixedCourseId.value
  } else if (courses.value.length) {
    courseId.value = courses.value[0].id
  }
  if (courseId.value) {
    load()
    loadCatalogs()
    refreshBatchCount()
  }
}

async function loadCatalogs() {
  if (!courseId.value) return
  const data = await listCatalogs({ course: courseId.value, tree: 1 })
  const tree = data.results ?? data
  const flat = []
  tree.forEach((ch) => {
    flat.push({ id: ch.id, label: ch.title })
    ;(ch.children || []).forEach((s) => flat.push({ id: s.id, label: `　└ ${s.title}` }))
  })
  flatCatalogs.value = flat
}

function handleCourseChange() {
  filterCatalog.value = null
  page.value = 1
  loadCatalogs()
  load()
  refreshBatchCount()
}

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const data = await listQuestions({
      course: courseId.value, qtype: filterType.value || undefined,
      catalog: filterCatalog.value || undefined,
      status: filterStatus.value || undefined, search: search.value || undefined, page: page.value,
    })
    rows.value = data.results ?? data
    total.value = data.total ?? rows.value.length
  } finally {
    loading.value = false
  }
}

// ---- 新建/编辑（表单字段由 QuestionFormFields 组件渲染） ----
const editVisible = ref(false)
const saving = ref(false)
const formFields = ref(null)
const form = reactive({})

function blankForm() {
  return {
    id: null, catalog: null, qtype: 'single', stem: '',
    options: [{ key: 'A', text: '' }, { key: 'B', text: '' }, { key: 'C', text: '' }, { key: 'D', text: '' }],
    answerKey: '', answerKeys: [], blanks: [{ text: '', score: 1 }], answerText: '',
    analysis: '', score: 5, difficulty: 'medium', status: 'draft',
  }
}

function openEdit(row) {
  if (!row && !flatCatalogs.value.length) return ElMessage.warning('请先在课程目录中创建章节')
  Object.assign(form, blankForm())
  if (row) {
    Object.assign(form, draftToForm({
      qtype: row.qtype, stem: row.stem, options: row.options,
      answer: row.answer, analysis: row.analysis, score: row.score, difficulty: row.difficulty,
    }))
    form.id = row.id
    form.catalog = row.catalog
    form.status = row.status || 'draft'
  }
  editVisible.value = true
}

async function save(publish = false) {
  if (!form.stem?.trim()) return ElMessage.warning('请填写题干')
  if (!form.catalog) return ElMessage.warning('请选择题目所属章节')
  const normalized = formFields.value?.normalize() || {}
  if (form.qtype === 'blank') {
    const filled = normalized.answer?.blanks || []
    if (!filled.length) return ElMessage.warning('请至少填写一个空的答案')
    if (filled.some((b) => !(Number(b.score) > 0))) return ElMessage.warning('每个空的分值必须大于 0')
  }
  // 新建默认草稿；“创建并发布/保存并发布”直接发布，减少后续单独点发布操作
  const status = publish ? 'published' : (form.id ? form.status || 'draft' : 'draft')
  const payload = {
    course: courseId.value, catalog: form.catalog,
    ...normalized, status,
  }
  saving.value = true
  try {
    if (form.id) {
      await updateQuestion(form.id, payload)
      ElMessage.success('已更新')
    } else {
      await createQuestion(payload)
      ElMessage.success(publish ? '已创建并发布' : '已创建（草稿）')
    }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function setStatus(row, status) {
  const updated = await updateQuestion(row.id, { status })
  ElMessage.success(status === 'published' ? '已发布' : '已停用')
  if (filterStatus.value && filterStatus.value !== status) {
    rows.value = rows.value.filter((item) => item.id !== row.id)
    total.value = Math.max(0, total.value - 1)
    return
  }
  rows.value = rows.value.map((item) => (
    item.id === row.id ? { ...item, ...(updated || {}), status } : item
  ))
}
function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteQuestion(deleteTarget.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    await load()
  } finally {
    deleting.value = false
  }
}

// ---- 草稿批次 ----
const batchesVisible = ref(false)
const batchesLoading = ref(false)
const batches = ref([])
const batchCount = ref(0)
const importVisible = ref(false) // 文档导入弹窗
const aiGenVisible = ref(false) // AI 多类型生题弹窗

async function refreshBatchCount() {
  if (!courseId.value) return
  try {
    const data = await listDraftBatches({ course: courseId.value, status: 'parsed' })
    batchCount.value = Number(data.count ?? data.total ?? (data.results || []).length)
  } catch {
    batchCount.value = 0
  }
}

async function openBatches() {
  batchesVisible.value = true
  batchesLoading.value = true
  try {
    const data = await listDraftBatches({ course: courseId.value, status: 'parsed' })
    batches.value = data.results ?? data
  } finally {
    batchesLoading.value = false
  }
}

async function discardBatch(b) {
  try {
    await ElMessageBox.confirm(
      '放弃后批次内未入库的题目将一并删除，此操作无法撤销。',
      '放弃该草稿批次？',
      { type: 'warning', confirmButtonText: '放弃', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const { deleteDraftBatch } = await import('@/api/question')
  await deleteDraftBatch(b.id)
  ElMessage.success('已放弃该批次')
  batches.value = batches.value.filter((item) => item.id !== b.id)
  refreshBatchCount()
}

// ---- 预览（导入 / AI 生题共用入口） ----
const previewVisible = ref(false)
const previewBatchId = ref(null)

function openPreview(batchId) {
  previewBatchId.value = batchId
  previewVisible.value = true
  batchesVisible.value = false
}
function onImported(batch) {
  openPreview(batch.id)
  refreshBatchCount()
}
function onBatchSaved() {
  load()
  refreshBatchCount()
  if (batchesVisible.value) openBatches()
}

// ---- AI 多类型生题（异步轮询 + 离开页面恢复） ----
const { task: aiTask, start: startPolling } = useAiTaskPolling()
const bannerHidden = ref(false)
const TERMINAL_STATUS = new Set(['success', 'failed'])
const isTerminal = (s) => TERMINAL_STATUS.has(s)
const progressPercent = computed(() => {
  const p = aiTask.value?.progress
  if (!p || !p.total) return 0
  return Math.round(((p.done || 0) / p.total) * 100)
})

function handleAiTask(taskId) {
  bannerHidden.value = false
  startPolling(taskId, {
    onSuccess: (t) => {
      if (t.result?.degraded) {
        ElMessage.warning('部分题型生成失败，已生成的题目可继续预览入库')
      }
      if (t.result?.batch_id) openPreview(t.result.batch_id)
      refreshBatchCount()
    },
    onFailed: (t) => {
      ElMessage.error(t.error || 'AI 生题失败，请重试')
    },
  })
}
function onAiSubmitted({ taskId }) {
  handleAiTask(taskId)
}

// 恢复入口：进入页面时如有进行中的生题任务，自动续轮询（进度横幅展示）
async function checkActiveAiTasks() {
  try {
    const list = await listActiveAiTasks()
    if (Array.isArray(list) && list.length) {
      handleAiTask(list[0].id)
    }
  } catch {
    // 恢复检查失败不阻塞页面（任务仍在后台执行，稍后可从草稿批次/再次进入恢复）
  }
}

onMounted(() => {
  loadCourses()
  checkActiveAiTasks()
})

watch(
  () => route.query.search,
  (value) => {
    search.value = String(value || '')
    page.value = 1
    load()
  },
)
</script>

<style scoped>
/* 透明容器（与目录/知识库一致） */
.q-card {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.q-card:hover {
  box-shadow: none;
}
.q-card :deep(.el-card__body) {
  padding: 0;
}

/* 工具栏：筛选左 / 操作右 */
.q-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 0 0 12px;
  margin-bottom: 12px;
}
.q-toolbar-left,
.q-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* AI 生题进行中横幅 */
.ai-active-banner {
  margin-bottom: 12px;
  border-radius: 14px;
}
.ai-active-title {
  font-weight: 700;
  margin-right: 10px;
}
.ai-active-msg {
  color: var(--gray-600);
}
.ai-active-progress {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 6px;
}
.ai-active-progress :deep(.el-progress) {
  flex: 1;
  max-width: 320px;
}
.ai-active-tip {
  color: #94a3b8;
  font-size: 12.5px;
}

.question-form-dialog :deep(.el-dialog),
.batch-dialog :deep(.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

.question-form-dialog :deep(.el-dialog__header),
.batch-dialog :deep(.el-dialog__header) {
  margin: 0;
  padding: 0;
}

.question-form-dialog :deep(.el-dialog__body),
.batch-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.question-form-dialog :deep(.el-dialog__footer),
.batch-dialog :deep(.el-dialog__footer) {
  padding: 0;
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

.question-create-icon {
  color: var(--primary-600);
  background: #eaf2ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}

.batch-create-icon {
  color: #7c3aed;
  background: #f5f3ff;
  box-shadow: inset 0 0 0 1px rgba(124, 58, 237, 0.12);
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

/* 新建/编辑题目弹窗滚动区（表单字段布局与控件皮肤已内置于 QuestionFormFields） */
.question-creation-form {
  max-height: calc(100vh - 200px);
  padding: 16px 22px 18px;
  overflow-y: auto;
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

.creation-dialog-footer :deep(.el-button--primary) {
  box-shadow: 0 9px 18px rgba(37, 99, 235, 0.22);
}

.q-btn-ai,
.q-btn-batch,
.q-btn-import {
  height: 40px;
  padding: 0 18px;
  border-radius: 12px;
  font-weight: 700;
}
.q-btn-ai {
  color: var(--primary-600);
  border-color: rgba(37, 99, 235, 0.24);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
}
.q-btn-ai:hover {
  color: var(--primary-600);
  border-color: rgba(37, 99, 235, 0.5);
  background: var(--primary-50);
}
.q-btn-batch {
  color: #7c3aed;
  border-color: rgba(124, 58, 237, 0.24);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
}
.q-btn-batch:hover {
  color: #7c3aed;
  border-color: rgba(124, 58, 237, 0.5);
  background: #f5f3ff;
}
.q-btn-import {
  color: #059669;
  border-color: rgba(5, 150, 105, 0.24);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
}
.q-btn-import:hover {
  color: #059669;
  border-color: rgba(5, 150, 105, 0.5);
  background: #ecfdf5;
}
.q-batch-badge {
  margin-left: 6px;
}
.q-btn-primary {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.q-btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.2);
}

/* 题目行卡片 */
.q-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.q-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.q-row:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.q-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.q-type-badge {
  flex: 0 0 auto;
  padding: 5px 12px;
  border-radius: 9px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--primary-600);
  background: var(--primary-50);
  white-space: nowrap;
}
.q-type-badge.qt-single { color: #2563eb; background: #eff6ff; }
.q-type-badge.qt-multi { color: #7c3aed; background: #f5f3ff; }
.q-type-badge.qt-judge { color: #059669; background: #ecfdf5; }
.q-type-badge.qt-blank { color: #ea580c; background: #fff7ed; }
.q-type-badge.qt-short { color: #0891b2; background: #ecfeff; }
.q-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.q-stem {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gray-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.q-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.q-score {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--gray-500);
}

.q-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.q-action-btn {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-600);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.q-action-btn:hover {
  background: #fff;
  box-shadow: var(--shadow-xs);
}
.q-action-btn.success { color: var(--success); }
.q-action-btn.muted { color: var(--gray-500); }
.q-action-btn.danger { color: var(--danger); }

/* 草稿批次列表 */
.batch-body {
  padding: 16px 22px 18px;
}
.batch-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 22px 18px;
}
.batch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 16px;
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  background: #fff;
}
.batch-row-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}
.batch-row-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--gray-900);
}
.batch-row-meta {
  color: #94a3b8;
  font-size: 12.5px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.batch-row-actions {
  flex: none;
}

@media (max-width: 768px) {
  .q-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .q-action-group {
    justify-content: space-between;
  }
}
</style>
