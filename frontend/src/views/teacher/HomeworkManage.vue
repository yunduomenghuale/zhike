<template>
  <div class="page-container homework-page">
    <div class="page-header">
      <div>
        <div class="page-title">作业管理</div>
        <div class="page-subtitle">发布作业、查看提交情况并批改评分</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <div class="toolbar module-toolbar">
        <div class="toolbar-left">
          <el-select v-model="classId" class="module-select" placeholder="选择班级" style="width: 280px" @change="load">
            <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openEdit()">发布作业</el-button>
        </div>
      </div>

      <el-empty v-if="!classId" description="请先选择班级" />
      <template v-else>
        <TableSkeleton v-if="loading" :cols="5" />
        <el-empty v-else-if="!rows.length" :image-size="110">
          <template #description>
            <div class="hw-empty-text">还没有作业</div>
            <div class="hw-empty-tip">点击右上角「发布作业」开始布置</div>
          </template>
        </el-empty>
        <div v-else class="hw-list">
          <div v-for="row in rows" :key="row.id" class="hw-row">
            <div class="hw-row-left">
              <span class="hw-mode-badge" :class="'hm-' + row.mode">{{ row.mode_display }}</span>
              <div class="hw-copy">
                <div class="hw-title">{{ row.title }}</div>
                <div class="hw-meta">
                  <span class="hw-meta-item">
                    <el-icon><Clock /></el-icon>{{ row.deadline ? new Date(row.deadline).toLocaleString() : '不限截止' }}
                  </span>
                  <span class="hw-score">{{ row.total_score }} 分</span>
                  <span class="hw-meta-item">已交 {{ row.submission_count }}</span>
                  <el-tag size="small" :type="{ published: 'success', draft: 'warning', closed: 'info' }[row.status]" effect="light" round>
                    {{ row.status_display }}
                  </el-tag>
                </div>
              </div>
            </div>
            <div class="hw-action-group">
              <button class="hw-action-btn" @click="openSubmissions(row)"><el-icon><View /></el-icon> 批改</button>
              <button v-if="row.status === 'draft'" class="hw-action-btn success" @click="setStatus(row, 'published')">
                <el-icon><Promotion /></el-icon> 发布
              </button>
              <button class="hw-action-btn" @click="openEdit(row)"><el-icon><EditPen /></el-icon> 编辑</button>
              <button class="hw-action-btn danger" @click="openDelete(row)"><el-icon><Delete /></el-icon> 删除</button>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    <!-- 发布/编辑作业 -->
    <el-dialog v-model="editVisible" width="980px" align-center :show-close="false" class="homework-form-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon homework-create-icon"><el-icon><Document /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ form.id ? '编辑作业' : '发布作业' }}</div>
            <div class="creation-dialog-subtitle">从题库选题，或继续使用文本/附件作业</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="editVisible = false" />
        </div>
      </template>

      <el-form :model="form" label-position="top" class="homework-creation-form">
        <div class="creation-form-grid">
          <!-- 左列：基础信息 -->
          <div class="form-col form-col-left">
            <el-form-item label="作业模式">
              <el-radio-group v-model="form.mode" :disabled="isFrozen" @change="onModeChange">
                <el-radio-button value="questions">题库选题</el-radio-button>
                <el-radio-button value="attachment">文本 / 附件</el-radio-button>
              </el-radio-group>
              <span v-if="isFrozen" class="freeze-tip">已发布，题目快照已冻结</span>
            </el-form-item>
            <el-form-item label="作业标题"><el-input v-model="form.title" placeholder="请输入作业标题" /></el-form-item>
            <el-form-item label="作业说明"><el-input v-model="form.description" type="textarea" :rows="3" resize="none" placeholder="请输入作业要求说明" /></el-form-item>
            <el-form-item label="截止时间">
              <el-date-picker
                v-model="form.deadline"
                type="datetime"
                placeholder="选择截止时间"
                format="YYYY年MM月DD日 HH:mm"
                value-format="YYYY-MM-DDTHH:mm:ss"
                popper-class="platform-datetime-popper"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item v-if="form.mode === 'attachment'" label="满分"><el-input-number v-model="form.total_score" :min="1" :max="200" /></el-form-item>
            <el-form-item label="发布状态">
              <el-radio-group v-model="form.status" class="homework-status-switch">
                <el-radio-button value="draft">保存草稿</el-radio-button>
                <el-radio-button value="published">立即发布</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </div>

          <!-- 右列：题库选题 / 附件 -->
          <div class="form-col form-col-right">
            <el-form-item v-if="form.mode === 'attachment'" label="作业附件">
              <el-upload :auto-upload="false" :limit="1" :on-change="onHomeworkFile" :on-remove="() => { homeworkFile = null }">
                <el-button>选择文件</el-button>
              </el-upload>
            </el-form-item>
            <template v-else>
              <div class="col-label">题目选择</div>
              <div class="question-builder">
                <el-alert
                  v-if="isFrozen"
                  type="success"
                  :closable="false"
                  show-icon
                  title="该作业已经发布，以下题目与答案均使用已冻结快照。"
                />
                <template v-else>
                  <div class="question-filters">
                    <el-select v-model="questionFilters.catalog" clearable placeholder="全部章节" @change="loadQuestionOptions">
                      <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                    </el-select>
                    <el-select v-model="questionFilters.qtype" clearable placeholder="全部题型" @change="loadQuestionOptions">
                      <el-option label="单选题" value="single" /><el-option label="多选题" value="multi" />
                      <el-option label="判断题" value="judge" /><el-option label="填空题" value="blank" />
                      <el-option label="简答题" value="short" />
                    </el-select>
                    <el-select v-model="questionFilters.difficulty" clearable placeholder="全部难度" @change="loadQuestionOptions">
                      <el-option label="简单" value="easy" /><el-option label="中等" value="medium" /><el-option label="困难" value="hard" />
                    </el-select>
                  </div>
                  <el-table :data="questionOptions" height="200" v-loading="questionLoading" class="question-pool-table">
                    <el-table-column prop="stem" label="题干" min-width="240" show-overflow-tooltip />
                    <el-table-column prop="qtype_display" label="题型" width="82" />
                    <el-table-column prop="difficulty_display" label="难度" width="72" />
                    <el-table-column label="操作" width="72" align="center">
                      <template #default="{ row }">
                        <el-button link :type="isSelected(row.id) ? 'danger' : 'primary'" @click="toggleQuestion(row)">
                          {{ isSelected(row.id) ? '移除' : '添加' }}
                        </el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </template>

                <div class="selected-header">
                  <strong>已选 {{ selectedQuestions.length }} 题</strong>
                  <span>总分 {{ selectedTotal }} 分（自动计算）</span>
                </div>
                <el-empty v-if="!selectedQuestions.length" description="请从当前课程题库添加题目" :image-size="54" />
                <div v-else class="selected-list">
                  <div v-for="(item, index) in selectedQuestions" :key="item.question" class="selected-item">
                    <span class="question-order">{{ index + 1 }}</span>
                    <span class="selected-stem">{{ item.stem }}</span>
                    <el-tag size="small" effect="plain">{{ item.qtype_display }}</el-tag>
                    <el-input-number v-model="item.score" :min="0.5" :max="100" :step="0.5" size="small" />
                    <span class="score-unit">分</span>
                    <template v-if="!isFrozen">
                      <el-button link :disabled="index === 0" @click="moveQuestion(index, -1)">上移</el-button>
                      <el-button link :disabled="index === selectedQuestions.length - 1" @click="moveQuestion(index, 1)">下移</el-button>
                      <el-button link type="danger" @click="selectedQuestions.splice(index, 1)">删除</el-button>
                    </template>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">{{ form.id ? '保存修改' : '保存作业' }}</el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除作业"
      :item-name="deleteTarget?.title"
      description="删除后将无法从当前课程工作区继续访问，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 提交与批改 -->
    <el-drawer v-model="subVisible" :title="`${currentHw?.title} · 提交批改`" size="52%">
      <el-table :data="submissions" v-loading="subLoading" stripe>
        <el-table-column prop="student_name" label="学生" width="110" />
        <el-table-column label="提交内容" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ currentHw?.mode === 'questions' ? `客观题 ${row.objective_score} 分` : (row.content || '附件提交') }}
          </template>
        </el-table-column>
        <el-table-column label="逾期" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_late" type="danger" size="small" effect="light">逾期</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="得分" width="80" align="center">
          <template #default="{ row }">{{ row.score ?? '未批' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openGrade(row)">批改</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!subLoading && !submissions.length" description="还没有学生提交" />
    </el-drawer>

    <!-- 批改弹窗 -->
    <el-dialog v-model="gradeVisible" title="批改作业" width="720px" align-center>
      <div v-if="currentHw?.mode === 'questions'" class="answer-review-list">
        <div v-for="(item, index) in gradeForm.answerItems" :key="item.id" class="answer-review-item">
          <div class="answer-review-head">
            <strong>{{ index + 1 }}. {{ item.snapshot.stem }}</strong>
            <span>{{ item.score ?? '待批' }} / {{ item.fullScore }} 分</span>
          </div>
          <div class="student-answer">学生答案：{{ formatAnswer(item.student_answer) || '未作答' }}</div>
          <div v-if="item.needs_manual_grading" class="manual-grade-row">
            <el-input-number v-model="item.manualScore" :min="0" :max="item.fullScore" :step="0.5" />
            <el-input v-model="item.comment" placeholder="本题评语（选填）" />
          </div>
          <el-tag v-else :type="item.is_correct ? 'success' : 'danger'" size="small">
            {{ item.is_correct ? '自动判定正确' : '自动判定错误' }}
          </el-tag>
        </div>
      </div>
      <div v-else class="grade-content">
        <div class="grade-label">学生提交</div>
        <div class="grade-text">{{ gradeForm.content || '（无文本内容）' }}</div>
      </div>
      <el-form :model="gradeForm" label-width="70px">
        <el-form-item v-if="currentHw?.mode !== 'questions'" label="得分">
          <el-input-number v-model="gradeForm.score" :min="0" :max="Number(currentHw?.total_score) || 100" />
          <span class="total-hint">/ {{ currentHw?.total_score }} 分</span>
        </el-form-item>
        <el-form-item label="评语"><el-input v-model="gradeForm.comment" type="textarea" :rows="3" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="gradeVisible = false">取消</el-button>
          <el-button type="primary" :loading="grading" @click="doGrade">提交批改</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Delete, EditPen, View, Document, Close, Promotion, Clock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listClasses } from '@/api/classroom'
import { listCatalogs } from '@/api/course'
import { listQuestions } from '@/api/question'
import {
  listHomeworks, createHomework, updateHomework, deleteHomework,
  listSubmissions, gradeSubmission,
} from '@/api/homework'

const classes = ref([])
const classId = ref(null)
const rows = ref([])
const loading = ref(false)
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)

function classCourseNames(item) {
  return item.course_names?.join('、') || item.course_name || '未关联课程'
}

function activeCourseId() {
  const classroom = classes.value.find((item) => item.id === classId.value)
  return fixedCourseId.value || classroom?.course || null
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    load()
  } else {
    classId.value = null
    rows.value = []
  }
}
async function load() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await listHomeworks({ classroom: classId.value, course: activeCourseId() })
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

// ---- 发布/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})
const isFrozen = computed(() => Boolean(form.id) && form.status !== 'draft')
const selectedQuestions = ref([])
const selectedTotal = computed(() => selectedQuestions.value.reduce((sum, item) => sum + Number(item.score || 0), 0))
const homeworkFile = ref(null)
const catalogOptions = ref([])
const questionOptions = ref([])
const questionLoading = ref(false)
const questionFilters = reactive({ catalog: null, qtype: '', difficulty: '' })

function flattenCatalogs(items, depth = 0) {
  return (items || []).flatMap((item) => [
    { id: item.id, label: `${'　'.repeat(depth)}${item.title}` },
    ...flattenCatalogs(item.children, depth + 1),
  ])
}

async function loadCatalogOptions() {
  const course = activeCourseId()
  if (!course) return
  const data = await listCatalogs({ course, tree: 1, page_size: 100 })
  catalogOptions.value = flattenCatalogs(data.results ?? data)
}

async function loadQuestionOptions() {
  if (form.mode !== 'questions' || isFrozen.value) return
  questionLoading.value = true
  try {
    const params = { course: activeCourseId(), status: 'published', page_size: 100 }
    if (questionFilters.catalog) params.catalog = questionFilters.catalog
    if (questionFilters.qtype) params.qtype = questionFilters.qtype
    if (questionFilters.difficulty) params.difficulty = questionFilters.difficulty
    const data = await listQuestions(params)
    questionOptions.value = data.results ?? data
  } finally {
    questionLoading.value = false
  }
}

function onModeChange(mode) {
  if (mode === 'questions') {
    loadCatalogOptions()
    loadQuestionOptions()
  }
}

function isSelected(id) {
  return selectedQuestions.value.some((item) => Number(item.question) === Number(id))
}

function toggleQuestion(question) {
  const index = selectedQuestions.value.findIndex((item) => Number(item.question) === Number(question.id))
  if (index >= 0) selectedQuestions.value.splice(index, 1)
  else selectedQuestions.value.push({
    question: question.id,
    stem: question.stem,
    qtype_display: question.qtype_display,
    difficulty_display: question.difficulty_display,
    score: Number(question.score) || 5,
  })
}

function moveQuestion(index, offset) {
  const target = index + offset
  if (target < 0 || target >= selectedQuestions.value.length) return
  const [item] = selectedQuestions.value.splice(index, 1)
  selectedQuestions.value.splice(target, 0, item)
}

function onHomeworkFile(file) {
  homeworkFile.value = file.raw
}

function openEdit(row) {
  Object.assign(form, {
    id: row?.id || null,
    title: row?.title || '',
    description: row?.description || '',
    deadline: row?.deadline || '',
    total_score: Number(row?.total_score) || 100,
    mode: row?.mode || 'questions',
    status: row?.status || 'draft',
  })
  homeworkFile.value = null
  selectedQuestions.value = (row?.questions || []).map((item) => ({
    question: item.question,
    stem: item.snapshot?.stem || '题目快照',
    qtype_display: item.snapshot?.qtype_display || item.snapshot?.qtype || '',
    difficulty_display: item.snapshot?.difficulty_display || '',
    score: Number(item.score),
  }))
  questionFilters.catalog = null
  questionFilters.qtype = ''
  questionFilters.difficulty = ''
  editVisible.value = true
  if ((row?.mode || 'questions') === 'questions') {
    loadCatalogOptions()
    loadQuestionOptions()
  }
}
async function save() {
  if (!form.title) return ElMessage.warning('请填写标题')
  const courseId = activeCourseId()
  if (!courseId) return ElMessage.warning('该班级尚未关联课程')
  if (form.mode === 'questions' && !selectedQuestions.value.length) return ElMessage.warning('请至少选择一道题')
  let payload = {
    title: form.title, description: form.description, deadline: form.deadline || null, status: form.status,
  }
  if (!isFrozen.value) {
    payload = { ...payload, course: courseId, classroom: classId.value, mode: form.mode }
    if (form.mode === 'questions') {
      payload.question_items = selectedQuestions.value.map((item) => ({ question: item.question, score: item.score }))
    } else {
      payload.total_score = form.total_score
    }
  }
  if (form.mode === 'attachment' && homeworkFile.value) {
    const body = new FormData()
    Object.entries(payload).forEach(([key, value]) => {
      if (value !== null && value !== undefined) body.append(key, value)
    })
    body.append('attachment', homeworkFile.value)
    payload = body
  }
  saving.value = true
  try {
    if (form.id) { await updateHomework(form.id, payload); ElMessage.success('已更新') }
    else { await createHomework(payload); ElMessage.success('已保存') }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}
async function setStatus(row, status) {
  await updateHomework(row.id, { ...row, status })
  ElMessage.success('已发布')
  load()
}
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteHomework(deleteTarget.value.id)
    ElMessage.success('作业已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    load()
  } finally {
    deleting.value = false
  }
}

// ---- 提交与批改 ----
const subVisible = ref(false)
const subLoading = ref(false)
const submissions = ref([])
const currentHw = ref(null)
async function openSubmissions(row) {
  currentHw.value = row
  subVisible.value = true
  subLoading.value = true
  try {
    const data = await listSubmissions({ homework: row.id })
    submissions.value = data.results ?? data
  } finally {
    subLoading.value = false
  }
}

const gradeVisible = ref(false)
const grading = ref(false)
const gradeForm = reactive({ id: null, content: '', score: 0, comment: '' })
function openGrade(row) {
  Object.assign(gradeForm, {
    id: row.id,
    content: row.content,
    score: Number(row.score) || 0,
    comment: row.comment || '',
    answerItems: (row.answer_items || []).map((item) => ({
      ...item,
      fullScore: Number(currentHw.value?.questions?.find((q) => q.id === item.homework_question)?.score || 0),
      manualScore: item.score == null ? 0 : Number(item.score),
      comment: item.comment || '',
    })),
  })
  gradeVisible.value = true
}
function formatAnswer(answer) {
  if (!answer) return ''
  if (answer.key != null) return String(answer.key)
  if (answer.keys) return answer.keys.join('、')
  if (answer.blanks) return answer.blanks.join(' / ')
  if (answer.text != null) return String(answer.text)
  return JSON.stringify(answer)
}
async function doGrade() {
  grading.value = true
  try {
    const payload = { score: gradeForm.score, comment: gradeForm.comment }
    if (currentHw.value?.mode === 'questions') {
      payload.answer_scores = Object.fromEntries(
        gradeForm.answerItems
          .filter((item) => item.needs_manual_grading)
          .map((item) => [item.id, { score: item.manualScore, comment: item.comment }]),
      )
    }
    await gradeSubmission(gradeForm.id, payload)
    ElMessage.success('批改完成')
    gradeVisible.value = false
    openSubmissions(currentHw.value)
  } finally {
    grading.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.homework-page :deep(.data-card) { padding: 0; }
.homework-page :deep(.data-card > .el-card__body) { padding: 0; }
.module-toolbar {
  margin: 0 0 12px;
  padding: 0 0 12px;
  border-bottom: 0;
}
.module-select :deep(.el-select__wrapper) {
  min-height: 40px;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
}
.module-select :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #60a5fa, 0 0 0 3px rgba(96, 165, 250, 0.12);
}
.module-primary-button {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  box-shadow: 0 11px 22px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.module-table {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: transparent;
  background: transparent;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  padding: 0 14px 10px;
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  background: transparent;
}
.module-table :deep(td.el-table__cell) {
  padding: 17px 14px;
  border-bottom: 10px solid transparent;
  color: #334155;
  background: rgba(255, 255, 255, 0.8);
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #fff; }
.module-table :deep(.el-table__body tr > td.el-table__cell:first-child) { border-top-left-radius: 15px; border-bottom-left-radius: 15px; }
.module-table :deep(.el-table__body tr > td.el-table__cell:last-child) { border-top-right-radius: 15px; border-bottom-right-radius: 15px; }

/* 作业卡片行（与题库列表一致） */
.hw-empty-text { color: var(--gray-700, #334155); font-size: 15px; font-weight: 700; }
.hw-empty-tip { margin-top: 4px; color: var(--gray-400, #94a3b8); font-size: 13px; }
.hw-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hw-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100, #e5e9f0);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.hw-row:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.hw-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.hw-mode-badge {
  flex: 0 0 auto;
  padding: 5px 12px;
  border-radius: 9px;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
  color: #2563eb;
  background: #eff6ff;
}
.hw-mode-badge.hm-questions { color: #2563eb; background: #eff6ff; }
.hw-mode-badge.hm-attachment { color: #7c3aed; background: #f5f3ff; }
.hw-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.hw-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gray-900, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.hw-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hw-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
}
.hw-score {
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
  font-weight: 700;
}
.hw-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.hw-action-btn {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-600, #2563eb);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.hw-action-btn:hover {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.hw-action-btn.success { color: var(--success, #16a34a); }
.hw-action-btn.danger { color: var(--danger, #dc2626); }

@media (max-width: 768px) {
  .hw-row { flex-direction: column; align-items: stretch; gap: 12px; }
  .hw-action-group { justify-content: space-between; }
}

/* 深色模式 */
html.dark .hw-row { background: #1e293b; border-color: #334155; }
html.dark .hw-title { color: #f1f5f9; }
html.dark .hw-action-group { background: #0f172a; }
html.dark .hw-action-btn:hover { background: #334155; }
.homework-form-dialog :deep(.el-dialog),
:global(.homework-form-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.homework-form-dialog :deep(.el-dialog__header),
:global(.homework-form-dialog.el-dialog .el-dialog__header),
.homework-form-dialog :deep(.el-dialog__footer),
:global(.homework-form-dialog.el-dialog .el-dialog__footer) {
  margin: 0;
  padding: 0;
}
.homework-form-dialog :deep(.el-dialog__body),
:global(.homework-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 82px;
  padding: 18px 22px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
.creation-dialog-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 15px;
  font-size: 21px;
}
.homework-create-icon {
  color: #2563eb;
  background: #eaf2ff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.creation-dialog-heading { min-width: 0; }
.creation-dialog-title {
  color: #14213d;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  margin-left: auto;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #2563eb;
  background: #eff6ff;
}
.homework-creation-form { padding: 20px 24px 22px; }
.creation-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 300px) minmax(0, 1fr);
  gap: 0 24px;
  align-items: start;
}
.form-col { min-width: 0; }
.col-label {
  margin-bottom: 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}
.homework-creation-form :deep(.el-form-item) { margin-bottom: 18px; }
.homework-creation-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}
.homework-creation-form :deep(.el-input__wrapper),
.homework-creation-form :deep(.el-date-editor.el-input),
.homework-creation-form :deep(.el-input-number) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
}
.homework-creation-form :deep(.el-input__wrapper:focus-within),
.homework-creation-form :deep(.el-date-editor.el-input:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.homework-creation-form :deep(.el-input-number) { width: 100%; }
.homework-creation-form :deep(.el-textarea__inner) {
  min-height: 104px !important;
  padding: 11px 13px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
  line-height: 1.65;
}
.homework-creation-form :deep(.el-textarea__inner:focus) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.homework-status-switch :deep(.el-radio-button__inner) {
  min-width: 104px;
  padding: 10px 16px;
  border-color: #dbe5f2;
  color: #64748b;
  background: #f8fbff;
  box-shadow: none;
}
.homework-status-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: #3b82f6;
  color: #2563eb;
  background: #eff6ff;
  box-shadow: -1px 0 0 0 #3b82f6;
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: rgba(248, 250, 252, 0.82);
}
.creation-dialog-footer :deep(.el-button) {
  min-width: 88px;
  height: 38px;
  border-radius: 10px;
  font-weight: 700;
}
:global(.platform-datetime-popper.el-popper) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.48) !important;
  border-radius: 18px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.18), 0 0 0 6px rgba(219, 234, 254, 0.16) !important;
}
:global(.platform-datetime-popper .el-picker-panel) {
  border: 0;
  border-radius: 18px;
  color: #334155;
  background: transparent;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker__time-header) {
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper) {
  min-height: 36px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
:global(.platform-datetime-popper .el-date-picker__header) {
  margin: 14px 18px 8px;
}
:global(.platform-datetime-popper .el-date-picker__header-label) {
  color: #334155;
  font-size: 15px;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn) {
  width: 28px;
  height: 28px;
  margin: 0 1px;
  border-radius: 8px;
  color: #64748b;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table th) {
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-date-table td .el-date-table-cell) {
  width: 34px;
  height: 34px;
  margin: 1px auto;
  border-radius: 10px;
}
:global(.platform-datetime-popper .el-date-table td.available:hover .el-date-table-cell) {
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table td.available:hover span),
:global(.platform-datetime-popper .el-date-table td.today span) {
  color: #2563eb;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) .el-date-table-cell) {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.24);
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) span) {
  color: #fff;
}
:global(.platform-datetime-popper .el-picker-panel__footer) {
  padding: 10px 14px 12px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button) {
  min-width: 64px;
  height: 34px;
  border-radius: 9px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button--text) {
  color: #64748b;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button--primary) {
  border-color: #3b82f6;
  color: #fff;
  background: #3b82f6;
}
:global(.platform-datetime-popper .el-time-panel) {
  overflow: hidden;
  border: 1px solid #dbe5f2;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
}
:global(.platform-datetime-popper .el-time-panel__content::before),
:global(.platform-datetime-popper .el-time-panel__content::after) {
  border-color: #e5edf7;
}
:global(.platform-datetime-popper .el-time-spinner__item) {
  color: #64748b;
}
:global(.platform-datetime-popper .el-time-spinner__item:hover:not(.is-disabled):not(.is-active)) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-time-spinner__item.is-active:not(.is-disabled)) {
  color: #2563eb;
  font-weight: 800;
}
:global(.platform-datetime-popper .el-time-panel__footer) {
  height: auto;
  padding: 9px 10px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-time-panel__btn) {
  min-width: 58px;
  height: 32px;
  margin: 0 2px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-time-panel__btn.confirm) {
  color: #fff;
  background: #3b82f6;
}
@media (max-width: 720px) {
  .homework-form-dialog :deep(.el-dialog),
  :global(.homework-form-dialog.el-dialog) { width: calc(100% - 28px) !important; }
  .creation-form-grid { grid-template-columns: 1fr; }
  .form-span-full { grid-column: auto; }
  .creation-dialog-header { padding: 16px 18px; }
  .homework-creation-form { padding: 18px; }
  .creation-dialog-footer { padding: 14px 18px 16px; }
}
.grade-content {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
}
.grade-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.grade-text {
  white-space: pre-wrap;
  line-height: 1.6;
}
.total-hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}
.freeze-tip { margin-left: 12px; color: #16a34a; font-size: 13px; }
.question-builder {
  display: grid;
  gap: 12px;
  margin-bottom: 0;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #f8fafc;
}
.question-filters {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.question-pool-table { border: 1px solid #e2e8f0; border-radius: 10px; }
.selected-header { display: flex; align-items: center; justify-content: space-between; color: #334155; }
.selected-header span { color: #2563eb; font-weight: 700; }
.selected-list { display: grid; gap: 8px; max-height: 150px; overflow: auto; }
.selected-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 10px;
  background: #fff;
}
.question-order {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
  font-weight: 800;
}
.selected-stem { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-item :deep(.el-input-number) { width: 100px; }
.score-unit { color: #64748b; font-size: 12px; }
.answer-review-list { display: grid; gap: 12px; max-height: 55vh; overflow: auto; margin-bottom: 18px; }
.answer-review-item {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
.answer-review-head { display: flex; justify-content: space-between; gap: 16px; line-height: 1.55; }
.answer-review-head span { flex: none; color: #2563eb; }
.student-answer { color: #475569; white-space: pre-wrap; }
.manual-grade-row { display: grid; grid-template-columns: 140px 1fr; gap: 10px; }
</style>
