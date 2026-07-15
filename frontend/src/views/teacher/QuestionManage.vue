<template>
  <div class="page-container">
    <el-card shadow="never" class="data-card q-card">
      <div class="q-toolbar">
        <div class="q-toolbar-left">
          <el-select v-if="!inCourseWorkspace" v-model="courseId" size="large" class="q-filter-select q-course-select" popper-class="q-filter-popper" placeholder="选择课程" style="width: 220px" @change="handleCourseChange">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="filterCatalog" size="large" class="q-filter-select" popper-class="q-filter-popper" placeholder="章节" clearable style="width: 170px" @change="load">
            <el-option v-for="c in flatCatalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
          <el-select v-model="filterType" size="large" class="q-filter-select" popper-class="q-filter-popper" placeholder="题型" clearable style="width: 130px" @change="load">
            <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
          <el-select v-model="filterStatus" size="large" class="q-filter-select" popper-class="q-filter-popper" placeholder="状态" clearable style="width: 130px" @change="load">
            <el-option label="草稿" value="draft" />
            <el-option label="已发布" value="published" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </div>
        <div class="q-toolbar-actions">
          <el-button v-if="courseId" class="q-btn-ai" :icon="MagicStick" @click="openAi">AI 生成</el-button>
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
            <div class="empty-tip">点击右上角「新建题目」或「AI 生成」开始建题</div>
          </template>
        </el-empty>
        <div v-else class="q-list">
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
                  <el-tag size="small" :type="row.source === 'ai' ? 'primary' : 'info'" effect="plain" round>
                    {{ row.source === 'ai' ? 'AI 生成' : '手动录入' }}
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

    <!-- 新建/编辑题目 -->
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

      <el-form :model="form" label-position="top" class="question-creation-form">
        <div class="form-row">
          <el-form-item label="题型" class="question-type-field">
            <el-select v-model="form.qtype" style="width: 160px" @change="onTypeChange">
              <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="所属章节（必选）" class="form-row-grow">
            <el-select v-model="form.catalog" placeholder="请选择题目所属章节" style="width: 100%">
              <el-option v-for="c in flatCatalogs" :key="c.id" :label="c.label" :value="c.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="题干">
          <el-input v-model="form.stem" type="textarea" :rows="2" placeholder="请输入题干" />
        </el-form-item>

        <!-- 选项（单选/多选） -->
        <el-form-item v-if="form.qtype === 'single' || form.qtype === 'multi'" label="选项">
          <div class="opt-editor">
            <div v-for="(opt, i) in form.options" :key="opt.key" class="opt-row">
              <el-tag>{{ opt.key }}</el-tag>
              <el-input v-model="opt.text" placeholder="选项内容" />
              <el-button
                size="small"
                :type="isCorrect(opt.key) ? 'success' : ''"
                :plain="!isCorrect(opt.key)"
                @click="toggleCorrect(opt.key)"
              >{{ isCorrect(opt.key) ? '✓ 正确答案' : '设为答案' }}</el-button>
              <el-button link type="danger" :icon="Delete" @click="form.options.splice(i, 1)" />
            </div>
            <el-button link type="primary" :icon="Plus" @click="addOption">添加选项</el-button>
          </div>
        </el-form-item>

        <!-- 判断题答案 -->
        <el-form-item v-else-if="form.qtype === 'judge'" label="答案">
          <el-radio-group v-model="form.answerKey">
            <el-radio value="A">正确</el-radio>
            <el-radio value="B">错误</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 填空答案 -->
        <el-form-item v-else-if="form.qtype === 'blank'" label="答案">
          <div class="opt-editor">
            <div v-for="(b, i) in form.blanks" :key="i" class="opt-row">
              <span class="blank-idx">第{{ i + 1 }}空</span>
              <el-input v-model="form.blanks[i]" placeholder="正确答案" />
              <el-button link type="danger" :icon="Delete" @click="form.blanks.splice(i, 1)" />
            </div>
            <el-button link type="primary" :icon="Plus" @click="form.blanks.push('')">添加空</el-button>
          </div>
        </el-form-item>

        <el-form-item label="解析">
          <el-input v-model="form.analysis" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item label="分值/难度">
          <el-input-number v-model="form.score" :min="1" :max="100" />
          <el-select v-model="form.difficulty" style="width: 120px; margin-left: 12px">
            <el-option label="简单" value="easy" />
            <el-option label="中等" value="medium" />
            <el-option label="困难" value="hard" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">{{ form.id ? '保存修改' : '创建题目' }}</el-button>
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

    <!-- AI 生成 -->
    <el-dialog v-model="aiVisible" width="560px" align-center class="ai-dialog" :show-close="false">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon ai-create-icon"><el-icon><MagicStick /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">AI 自动出题</div>
            <div class="creation-dialog-subtitle">智能生成题目</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="aiVisible = false" />
        </div>
      </template>

      <div class="ai-hint">
        <el-icon class="ai-hint-icon"><InfoFilled /></el-icon>
        <span>生成的题目为<b>草稿</b>，可先编辑再发布。未配置真实大模型时返回示例题。</span>
      </div>

      <el-form label-position="top" class="ai-form">
        <el-form-item label="章节">
          <el-select v-model="ai.catalog" placeholder="选择章节（基于其 PPT 出题）" style="width: 100%">
            <el-option v-for="c in flatCatalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="题型">
          <el-select v-model="ai.qtype" style="width: 200px">
            <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="ai.count" :min="1" :max="20" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="aiVisible = false">取消</el-button>
          <el-button class="q-btn-primary" type="primary" :icon="MagicStick" :loading="aiLoading" @click="doGenerate">生成题目</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Delete, EditPen, MagicStick, Promotion, Remove, InfoFilled, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listCourses, listCatalogs } from '@/api/course'
import {
  listQuestions, createQuestion, updateQuestion, deleteQuestion, generateQuestions,
} from '@/api/question'

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

function difficultyTag(d) {
  return { easy: 'success', medium: 'warning', hard: 'danger' }[d] || 'info'
}
function statusTag(s) {
  return { published: 'success', disabled: 'info', draft: 'warning', pending: 'warning' }[s] || 'info'
}

async function loadCourses() {
  if (fixedCourseId.value) {
    courseId.value = fixedCourseId.value
    load()
    loadCatalogs()
    return
  }
  const data = await listCourses()
  courses.value = data.results ?? data
  if (courses.value.length) {
    courseId.value = courses.value[0].id
    load()
    loadCatalogs()
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

// ---- 新建/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})

function blankForm() {
  return {
    id: null, catalog: null, qtype: 'single', stem: '',
    options: [{ key: 'A', text: '' }, { key: 'B', text: '' }, { key: 'C', text: '' }, { key: 'D', text: '' }],
    answerKey: '', answerKeys: [], blanks: [''],
    analysis: '', score: 5, difficulty: 'medium',
  }
}

function openEdit(row) {
  if (!row && !flatCatalogs.value.length) return ElMessage.warning('请先在课程目录中创建章节')
  Object.assign(form, blankForm())
  if (row) {
    form.id = row.id
    form.catalog = row.catalog
    form.qtype = row.qtype
    form.stem = row.stem
    form.options = (row.options && row.options.length) ? JSON.parse(JSON.stringify(row.options)) : form.options
    form.answerKey = row.answer?.key || ''
    form.answerKeys = row.answer?.keys || []
    form.blanks = row.answer?.blanks?.length ? [...row.answer.blanks] : ['']
    form.analysis = row.analysis || ''
    form.score = Number(row.score) || 5
    form.difficulty = row.difficulty || 'medium'
  }
  editVisible.value = true
}

function onTypeChange() {
  form.answerKey = ''
  form.answerKeys = []
}

function isCorrect(key) {
  return form.qtype === 'single' ? form.answerKey === key : form.answerKeys.includes(key)
}
function toggleCorrect(key) {
  if (form.qtype === 'single') {
    form.answerKey = key
  } else {
    const idx = form.answerKeys.indexOf(key)
    if (idx >= 0) form.answerKeys.splice(idx, 1)
    else form.answerKeys.push(key)
  }
}
function addOption() {
  const key = String.fromCharCode(65 + form.options.length)
  form.options.push({ key, text: '' })
}

function buildAnswer() {
  if (form.qtype === 'single' || form.qtype === 'judge') return { key: form.answerKey }
  if (form.qtype === 'multi') return { keys: form.answerKeys }
  if (form.qtype === 'blank') return { blanks: form.blanks.filter((b) => b !== '') }
  return {}
}
function buildOptions() {
  if (form.qtype === 'single' || form.qtype === 'multi') return form.options.filter((o) => o.text !== '')
  if (form.qtype === 'judge') return [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }]
  return []
}

async function save() {
  if (!form.stem) return ElMessage.warning('请填写题干')
  if (!form.catalog) return ElMessage.warning('请选择题目所属章节')
  const payload = {
    course: courseId.value, catalog: form.catalog, qtype: form.qtype, stem: form.stem,
    options: buildOptions(), answer: buildAnswer(), analysis: form.analysis,
    score: form.score, difficulty: form.difficulty,
  }
  saving.value = true
  try {
    if (form.id) {
      await updateQuestion(form.id, payload)
      ElMessage.success('已更新')
    } else {
      await createQuestion(payload)
      ElMessage.success('已创建（草稿）')
    }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function setStatus(row, status) {
  await updateQuestion(row.id, { status })
  ElMessage.success(status === 'published' ? '已发布' : '已停用')
  load()
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

// ---- AI 生成 ----
const aiVisible = ref(false)
const aiLoading = ref(false)
const ai = reactive({ qtype: 'single', count: 5, catalog: null })
function openAi() {
  if (!flatCatalogs.value.length) return ElMessage.warning('请先在课程目录中创建章节')
  ai.qtype = 'single'
  ai.count = 5
  ai.catalog = null
  aiVisible.value = true
}
async function doGenerate() {
  if (!ai.catalog) return ElMessage.warning('请选择题目所属章节')
  aiLoading.value = true
  try {
    const res = await generateQuestions({
      course: courseId.value, catalog: ai.catalog, count: ai.count,
      qtype: ai.qtype,
    })
    ElMessage.success(`已生成 ${res.length} 道草稿题目，请审核后发布`)
    aiVisible.value = false
    load()
  } finally {
    aiLoading.value = false
  }
}

onMounted(loadCourses)

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

.q-filter-select :deep(.el-select__wrapper) {
  min-height: 40px;
  padding: 0 12px;
  border-radius: 12px;
  background: rgba(248, 251, 255, 0.92);
  box-shadow: inset 0 0 0 1px #dbe5f2, 0 4px 12px rgba(37, 99, 235, 0.035);
  transition: background-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.q-filter-select:hover :deep(.el-select__wrapper) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe, 0 6px 16px rgba(37, 99, 235, 0.07);
}

.q-filter-select :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.11);
}

.q-filter-select :deep(.el-select__placeholder),
.q-filter-select :deep(.el-select__selected-item) {
  color: #64748b;
  font-weight: 600;
}

.q-filter-select :deep(.el-select__caret) {
  color: #94a3b8;
  font-size: 15px;
}

:global(.q-filter-popper.el-popper) {
  overflow: hidden;
  padding: 6px;
  border: 1px solid rgba(191, 219, 254, 0.85);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.13), 0 0 0 4px rgba(219, 234, 254, 0.28);
}

:global(.q-filter-popper .el-popper__arrow) {
  display: none;
}

:global(.q-filter-popper .el-select-dropdown__list) {
  padding: 0;
}

:global(.q-filter-popper .el-select-dropdown__item) {
  height: 38px;
  margin: 1px 0;
  padding: 0 12px;
  border-radius: 9px;
  color: #475569;
  font-weight: 600;
  line-height: 38px;
  transition: background-color 0.16s ease, color 0.16s ease;
}

:global(.q-filter-popper .el-select-dropdown__item.hover),
:global(.q-filter-popper .el-select-dropdown__item:hover) {
  background: #eff6ff;
  color: var(--primary-600);
}

:global(.q-filter-popper .el-select-dropdown__item.is-selected) {
  background: #dbeafe;
  color: var(--primary-700);
  font-weight: 700;
}

.question-form-dialog :deep(.el-dialog),
.ai-dialog :deep(.el-dialog),
:global(.question-form-dialog.el-dialog),
:global(.ai-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

.question-form-dialog :deep(.el-dialog__header),
.ai-dialog :deep(.el-dialog__header),
:global(.question-form-dialog.el-dialog .el-dialog__header),
:global(.ai-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}

.question-form-dialog :deep(.el-dialog__body),
:global(.question-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}

.question-form-dialog :deep(.el-dialog__footer),
.ai-dialog :deep(.el-dialog__footer),
:global(.question-form-dialog.el-dialog .el-dialog__footer),
:global(.ai-dialog.el-dialog .el-dialog__footer) {
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

.ai-create-icon {
  color: #fff;
  background: linear-gradient(140deg, #60a5fa, #2563eb);
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.4);
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

.question-creation-form {
  max-height: calc(100vh - 200px);
  padding: 16px 22px 18px;
  overflow-y: auto;
}

/* 题型 + 章节 并排一行，压缩纵向高度 */
.form-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.form-row-grow {
  flex: 1;
  min-width: 200px;
}

.question-creation-form :deep(.el-form-item),
.ai-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.question-creation-form :deep(.el-form-item__label),
.ai-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

.question-creation-form :deep(.el-input__wrapper),
.question-creation-form :deep(.el-select__wrapper),
.question-creation-form :deep(.el-input-number),
.ai-form :deep(.el-input__wrapper),
.ai-form :deep(.el-select__wrapper),
.ai-form :deep(.el-input-number) {
  min-height: 38px;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
}

.question-creation-form :deep(.el-textarea__inner) {
  padding: 11px 13px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
}

.question-creation-form :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.question-type-field {
  width: 160px;
  flex: 0 0 160px;
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

.q-btn-ai {
  height: 40px;
  padding: 0 18px;
  border-radius: 12px;
  font-weight: 700;
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

/* 深色模式 */
html.dark .q-row {
  background: #1e293b;
  border-color: #334155;
}
html.dark .q-stem { color: #f1f5f9; }
html.dark .q-action-group { background: #0f172a; }
html.dark .q-action-btn:hover { background: #334155; }

/* AI 出题内容区沿用创建弹窗骨架。 */
.ai-dialog :deep(.el-dialog__body) {
  padding: 18px 24px 4px;
}
.ai-hint {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 18px;
  padding: 11px 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.9), rgba(219, 234, 254, 0.5));
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
}
.ai-hint b { color: var(--primary-700); font-weight: 700; }
.ai-hint-icon { flex: 0 0 auto; font-size: 17px; color: var(--primary-600); }

html.dark .ai-hint {
  border-color: rgba(96, 165, 250, 0.2);
  background: rgba(37, 99, 235, 0.12);
  color: #cbd5e1;
}

.opt-editor {
  width: 100%;
}
.opt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.blank-idx {
  color: #64748b;
  font-size: 13px;
  white-space: nowrap;
}
</style>
