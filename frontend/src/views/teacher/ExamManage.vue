<template>
  <div class="page-container exam-page">
    <div class="page-header">
      <div>
        <div class="page-title">考试管理</div>
        <div class="page-subtitle">创建考试、随机组卷、发布考试并实时监控学生答题情况</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <div class="toolbar module-toolbar">
        <div class="toolbar-left">
          <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="loadExams">
            <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openCreate">新建考试</el-button>
        </div>
      </div>

      <div class="exam-list-shell">
        <el-empty v-if="!classId" description="请先选择班级">
          <template #description>
            <div class="empty-text">请先选择班级</div>
            <div class="empty-tip">选择班级后即可查看与管理该班级的考试</div>
          </template>
        </el-empty>

        <TableSkeleton v-else-if="loading" :cols="6" />
        <div v-else class="exam-card-list animate-list">
          <el-empty v-if="!exams.length" description="暂无考试" :image-size="96" />
          <template v-else>
            <article v-for="row in exams" :key="row.id" class="exam-list-card" :class="{ 'is-published': row.status === 'published' }">
              <div class="exam-card-main">
                <span class="exam-kind-badge">考试</span>
                <div class="exam-card-content">
                  <div class="exam-card-title">{{ row.name }}</div>
                  <div class="exam-card-meta">
                    <span v-if="formatExamWindow(row)" class="exam-meta-pill slate">{{ formatExamWindow(row) }}</span>
                    <span class="exam-meta-pill duration">{{ row.duration }} 分钟</span>
                    <span class="exam-score">{{ row.total_score || 0 }} 分</span>
                    <span class="exam-status-pill" :class="row.status">{{ row.status_display }}</span>
                    <span v-if="row.shuffle_questions" class="exam-meta-pill blue">题目乱序</span>
                    <span v-if="row.shuffle_options" class="exam-meta-pill orange">选项乱序</span>
                    <span v-if="row.per_student_paper" class="exam-meta-pill slate">一人一卷</span>
                  </div>
                </div>
              </div>
              <div class="exam-card-actions">
                <el-button link type="primary" :icon="EditPen" @click="openEdit(row)">编辑</el-button>
                <el-button link type="primary" :icon="EditPen" @click="openCompose(row)">组卷</el-button>
                <el-button v-if="row.status === 'draft'" link type="success" :icon="VideoPlay" @click="setStatus(row, 'published')">发布</el-button>
                <el-button v-if="row.status === 'published'" link type="info" :icon="CircleClose" @click="setStatus(row, 'finished')">结束</el-button>
                <el-button link type="primary" :icon="View" @click="openMonitor(row)">监控</el-button>
                <el-button link type="danger" :icon="Delete" @click="openDelete(row)">删除</el-button>
              </div>
            </article>
          </template>
        </div>
      </div>
    </el-card>

    <!-- 新建考试 -->
    <el-dialog v-model="createVisible" width="720px" align-center :show-close="false" class="exam-create-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon exam-create-icon"><el-icon><Document /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ editingExam ? '编辑考试' : '新建考试' }}</div>
            <div class="creation-dialog-subtitle">设置考试时间、时长与防作弊规则</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="createVisible = false" />
        </div>
      </template>
      <el-form :model="form" label-position="top" class="exam-creation-form">
        <div class="creation-form-grid">
          <el-form-item label="考试名称" class="form-span-full"><el-input v-model="form.name" placeholder="请输入考试名称" /></el-form-item>
          <el-form-item label="考试时长（分钟）"><el-input-number v-model="form.duration" :min="1" /></el-form-item>
          <el-form-item label="满分"><el-input-number v-model="form.total_score" :min="0" :precision="1" /></el-form-item>
          <el-form-item label="开始时间">
            <el-date-picker
              v-model="form.start_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              format="YYYY年MM月DD日 HH:mm"
              placeholder="选择开始时间"
              popper-class="exam-datetime-popper"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="结束时间">
            <el-date-picker
              v-model="form.end_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              format="YYYY年MM月DD日 HH:mm"
              placeholder="选择结束时间"
              popper-class="exam-datetime-popper"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="发布状态" class="form-span-full"><div class="exam-status-note">{{ editingExam ? '修改考试基础信息后，会同步影响学生端考试入口展示。' : '创建后先保存为草稿，可完成组卷后发布。' }}</div></el-form-item>
          <el-form-item label="考试模式" class="form-span-full setting-item">
          <div class="checkbox-group">
            <el-checkbox v-model="form.shuffle_questions">题目乱序</el-checkbox>
            <el-checkbox v-model="form.shuffle_options">选项乱序</el-checkbox>
            <el-checkbox v-model="form.per_student_paper">每人不同卷</el-checkbox>
            <el-checkbox v-model="form.show_analysis_after">考后看解析</el-checkbox>
            <el-checkbox v-model="form.allow_resubmit">允许重交</el-checkbox>
          </div>
        </el-form-item>
          <el-form-item label="防作弊" class="form-span-full setting-item">
          <div class="checkbox-group">
            <el-checkbox v-model="form.anti.detect_blur">记录切屏</el-checkbox>
            <el-checkbox v-model="form.anti.forbid_copy">禁止复制</el-checkbox>
            <el-checkbox v-model="form.anti.forbid_paste">禁止粘贴</el-checkbox>
            <el-checkbox v-model="form.anti.forbid_contextmenu">禁止右键</el-checkbox>
          </div>
        </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">{{ editingExam ? '保存修改' : '创建' }}</el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除考试"
      :item-name="deleteTarget?.name"
      description="删除后将无法继续组卷、发布或查看该考试，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 组卷 -->
    <el-dialog v-model="composeVisible" title="组卷" width="980px" align-center class="exam-compose-dialog">
      <el-tabs v-model="composeMode" class="compose-tabs">
        <el-tab-pane label="随机抽题" name="random">
          <el-alert type="info" :closable="false" show-icon description="按题型/难度从课程题库随机抽题；请确保题库中已有【已发布】状态的题目。" style="margin-bottom: 16px" />
          <el-table :data="rules" class="compose-rule-table" size="small">
            <el-table-column label="题型" width="150">
              <template #default="{ row }">
                <el-select v-model="row.qtype" size="small" popper-class="exam-compose-popper">
                  <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="难度" width="140">
              <template #default="{ row }">
                <el-select v-model="row.difficulty" size="small" clearable placeholder="不限" popper-class="exam-compose-popper">
                  <el-option label="简单" value="easy" />
                  <el-option label="中等" value="medium" />
                  <el-option label="困难" value="hard" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="130">
              <template #default="{ row }"><el-input-number v-model="row.count" :min="1" size="small" /></template>
            </el-table-column>
            <el-table-column label="每题分" width="130">
              <template #default="{ row }"><el-input-number v-model="row.score" :min="1" size="small" /></template>
            </el-table-column>
            <el-table-column width="80" align="center">
              <template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="rules.splice($index, 1)"></el-button></template>
            </el-table-column>
          </el-table>
          <el-button link type="primary" :icon="Plus" style="margin-top: 12px" @click="addRule">添加规则</el-button>
        </el-tab-pane>

        <el-tab-pane label="题库选题" name="manual">
          <div class="compose-filter-row">
            <el-select v-model="manualFilters.catalog" clearable placeholder="全部章节" popper-class="exam-compose-popper" @change="loadManualQuestions">
              <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
            </el-select>
            <el-select v-model="manualFilters.qtype" clearable placeholder="全部题型" popper-class="exam-compose-popper" @change="loadManualQuestions">
              <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
            <el-select v-model="manualFilters.difficulty" clearable placeholder="全部难度" popper-class="exam-compose-popper" @change="loadManualQuestions">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
          </div>
          <div class="compose-manual-grid">
            <el-table :data="manualQuestions" v-loading="manualLoading" class="compose-question-table" height="300" size="small">
              <el-table-column prop="stem" label="题干" min-width="300" show-overflow-tooltip />
              <el-table-column prop="qtype_display" label="题型" width="90" align="center" />
              <el-table-column prop="difficulty_display" label="难度" width="90" align="center" />
              <el-table-column label="操作" width="90" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="isManualSelected(row.id)" @click="addManualQuestion(row)">
                    {{ isManualSelected(row.id) ? '已选' : '加入' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="selected-paper-box">
              <div class="selected-paper-head">
                <strong>已选 {{ manualSelected.length }} 题</strong>
                <span>总分 {{ manualTotal }}</span>
              </div>
              <el-empty v-if="!manualSelected.length" description="从左侧题库加入题目" :image-size="72" />
              <div v-else class="paper-question-list">
                <div v-for="(item, index) in manualSelected" :key="item.question_id" class="paper-question-item">
                  <span class="paper-question-order">{{ index + 1 }}</span>
                  <span class="paper-question-stem">{{ item.stem }}</span>
                  <el-input-number v-model="item.score" class="compose-score-input" :min="1" size="small" controls-position="right" />
                  <el-button link type="danger" @click="manualSelected.splice(index, 1)">移除</el-button>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="自写题目" name="custom">
          <el-form :model="draftQuestion" label-position="top" class="compose-custom-form">
            <div class="custom-question-grid">
              <el-form-item label="章节">
                <el-select v-model="draftQuestion.catalog" placeholder="选择章节" popper-class="exam-compose-popper">
                  <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="题型">
                <el-select v-model="draftQuestion.qtype" popper-class="exam-compose-popper" @change="resetDraftAnswer">
                  <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="难度">
                <el-select v-model="draftQuestion.difficulty" popper-class="exam-compose-popper">
                  <el-option label="简单" value="easy" />
                  <el-option label="中等" value="medium" />
                  <el-option label="困难" value="hard" />
                </el-select>
              </el-form-item>
              <el-form-item label="分值">
                <el-input-number v-model="draftQuestion.score" :min="1" />
              </el-form-item>
              <el-form-item label="题干" class="custom-span-full">
                <el-input v-model="draftQuestion.stem" type="textarea" :rows="3" resize="none" placeholder="请输入题干" />
              </el-form-item>
              <template v-if="['single', 'multi'].includes(draftQuestion.qtype)">
                <el-form-item v-for="option in draftQuestion.options" :key="option.key" :label="`选项 ${option.key}`">
                  <el-input v-model="option.text" />
                </el-form-item>
              </template>
              <el-form-item label="答案" class="custom-span-full">
                <el-select v-if="draftQuestion.qtype === 'single'" v-model="draftQuestion.answerKey" placeholder="选择正确答案" popper-class="exam-compose-popper">
                  <el-option v-for="option in draftQuestion.options" :key="option.key" :label="option.key" :value="option.key" />
                </el-select>
                <el-select v-else-if="draftQuestion.qtype === 'multi'" v-model="draftQuestion.answerKeys" multiple placeholder="选择正确答案" popper-class="exam-compose-popper">
                  <el-option v-for="option in draftQuestion.options" :key="option.key" :label="option.key" :value="option.key" />
                </el-select>
                <el-select v-else-if="draftQuestion.qtype === 'judge'" v-model="draftQuestion.answerKey" placeholder="选择正确答案" popper-class="exam-compose-popper">
                  <el-option label="正确" value="true" />
                  <el-option label="错误" value="false" />
                </el-select>
                <el-input v-else v-model="draftQuestion.answerText" placeholder="填空题可用 / 分隔多个答案，简答题填写参考答案" />
              </el-form-item>
              <el-form-item label="解析" class="custom-span-full">
                <el-input v-model="draftQuestion.analysis" type="textarea" :rows="2" resize="none" placeholder="可选" />
              </el-form-item>
            </div>
            <div class="custom-compose-actions">
              <el-button type="primary" :loading="creatingQuestion" @click="saveDraftQuestion">保存到题库并加入试卷</el-button>
            </div>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="composeVisible = false">取消</el-button>
          <el-button type="primary" :loading="composing" @click="doCompose">生成试卷</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 监控 -->
    <el-drawer v-model="monitorVisible" title="考试监控" size="52%">
      <el-table :data="monitorRows" v-loading="monitorLoading" stripe>
        <el-table-column prop="student_name" label="学生" width="120" />
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }"><el-tag effect="light" round>{{ row.status_display }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="objective_score" label="客观题分" width="100" align="center" />
        <el-table-column prop="total_score" label="总分" width="90" align="center" />
        <el-table-column label="异常" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.abnormal" type="danger" size="small" effect="light" round>异常</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" min-width="160">
          <template #default="{ row }">{{ row.submitted_at ? new Date(row.submitted_at).toLocaleString() : '-' }}</template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  Plus, EditPen, VideoPlay, CircleClose, View, Delete, Document, Close,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listClasses } from '@/api/classroom'
import { listExams, createExam, updateExam, deleteExam, composePaper, monitorExam } from '@/api/exam'
import { listCatalogs } from '@/api/course'
import { listQuestions, createQuestion } from '@/api/question'

const qtypes = [
  { value: 'single', label: '单选题' },
  { value: 'multi', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
]

const classes = ref([])
const classId = ref(null)
const exams = ref([])
const loading = ref(false)
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)

function classCourseNames(item) {
  return item.course_names?.join('、') || item.course_name || '未关联课程'
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    loadExams()
  } else {
    classId.value = null
    exams.value = []
  }
}
async function loadExams() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await listExams({ classroom: classId.value })
    exams.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatExamWindow(row) {
  const start = formatDateTime(row.start_at)
  const end = formatDateTime(row.end_at)
  if (start && end) return `${start} - ${end}`
  return start || end
}

// ---- 新建 ----
const createVisible = ref(false)
const saving = ref(false)
const editingExam = ref(null)
const form = reactive({})
function openCreate() {
  editingExam.value = null
  Object.assign(form, {
    id: null, course: null, classroom: classId.value,
    name: '', start_at: '', end_at: '', duration: 60, total_score: 100, status: 'draft',
    shuffle_questions: true, shuffle_options: true,
    per_student_paper: false, show_analysis_after: true, allow_resubmit: false,
    anti: { detect_blur: true, forbid_copy: true, forbid_paste: true, forbid_contextmenu: true },
  })
  createVisible.value = true
}
function openEdit(row) {
  editingExam.value = row
  Object.assign(form, {
    id: row.id,
    course: row.course,
    classroom: row.classroom,
    name: row.name,
    start_at: row.start_at || '',
    end_at: row.end_at || '',
    duration: row.duration,
    total_score: row.total_score,
    status: row.status,
    shuffle_questions: row.shuffle_questions,
    shuffle_options: row.shuffle_options,
    per_student_paper: row.per_student_paper,
    show_analysis_after: row.show_analysis_after,
    allow_resubmit: row.allow_resubmit,
    anti: {
      detect_blur: true,
      forbid_copy: true,
      forbid_paste: true,
      forbid_contextmenu: true,
      ...(row.anti_cheat || {}),
    },
  })
  createVisible.value = true
}
async function save() {
  if (!form.name) return ElMessage.warning('请填写考试名称')
  const cls = classes.value.find((c) => c.id === classId.value)
  const courseId = form.course || fixedCourseId.value || cls?.course
  if (!courseId) return ElMessage.warning('该班级尚未关联课程')
  if (form.start_at && form.end_at && new Date(form.end_at) <= new Date(form.start_at)) {
    return ElMessage.warning('结束时间必须晚于开始时间')
  }
  const payload = {
    course: courseId,
    classroom: form.classroom || classId.value,
    name: form.name,
    start_at: form.start_at || null,
    end_at: form.end_at || null,
    duration: form.duration,
    total_score: form.total_score || 0,
    shuffle_questions: form.shuffle_questions,
    shuffle_options: form.shuffle_options,
    per_student_paper: form.per_student_paper,
    show_analysis_after: form.show_analysis_after,
    allow_resubmit: form.allow_resubmit,
    anti_cheat: form.anti,
    status: form.status || 'draft',
  }
  saving.value = true
  try {
    if (editingExam.value) {
      await updateExam(form.id, payload)
      ElMessage.success('已保存修改')
    } else {
      await createExam(payload)
      ElMessage.success('已创建')
    }
    createVisible.value = false
    editingExam.value = null
    loadExams()
  } finally {
    saving.value = false
  }
}

async function setStatus(row, status) {
  await updateExam(row.id, { ...row, status })
  ElMessage.success(status === 'published' ? '已发布' : '已结束')
  loadExams()
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
    await deleteExam(deleteTarget.value.id)
    ElMessage.success('考试已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    loadExams()
  } finally {
    deleting.value = false
  }
}

// ---- 组卷 ----
const composeVisible = ref(false)
const composing = ref(false)
const currentExam = ref(null)
const composeMode = ref('random')
const rules = ref([])
const catalogOptions = ref([])
const manualQuestions = ref([])
const manualSelected = ref([])
const manualLoading = ref(false)
const creatingQuestion = ref(false)
const manualFilters = reactive({ catalog: null, qtype: '', difficulty: '' })
const draftQuestion = reactive({})
const manualTotal = computed(() => manualSelected.value.reduce((sum, item) => sum + Number(item.score || 0), 0))

function flattenCatalogs(items, depth = 0) {
  return (items || []).flatMap((item) => [
    { id: item.id, label: `${'　'.repeat(depth)}${item.title}` },
    ...flattenCatalogs(item.children, depth + 1),
  ])
}

function activeExamCourseId() {
  const cls = classes.value.find((c) => c.id === classId.value)
  return currentExam.value?.course || fixedCourseId.value || cls?.course
}

async function loadCatalogOptions() {
  const course = activeExamCourseId()
  if (!course) return
  const data = await listCatalogs({ course, tree: 1, page_size: 100 })
  catalogOptions.value = flattenCatalogs(data.results ?? data)
  if (!draftQuestion.catalog && catalogOptions.value.length) {
    draftQuestion.catalog = catalogOptions.value[0].id
  }
}

async function loadManualQuestions() {
  const course = activeExamCourseId()
  if (!course) return
  manualLoading.value = true
  try {
    const params = { course, status: 'published', page_size: 1000 }
    if (manualFilters.catalog) params.catalog = manualFilters.catalog
    if (manualFilters.qtype) params.qtype = manualFilters.qtype
    if (manualFilters.difficulty) params.difficulty = manualFilters.difficulty
    const data = await listQuestions(params)
    manualQuestions.value = data.results ?? data
  } finally {
    manualLoading.value = false
  }
}

function resetDraftAnswer() {
  Object.assign(draftQuestion, {
    options: [
      { key: 'A', text: '' },
      { key: 'B', text: '' },
      { key: 'C', text: '' },
      { key: 'D', text: '' },
    ],
    answerKey: '',
    answerKeys: [],
    answerText: '',
  })
}

function resetDraftQuestion() {
  Object.assign(draftQuestion, {
    catalog: catalogOptions.value[0]?.id || null,
    qtype: 'single',
    difficulty: 'medium',
    score: 5,
    stem: '',
    analysis: '',
  })
  resetDraftAnswer()
}

function isManualSelected(id) {
  return manualSelected.value.some((item) => Number(item.question_id) === Number(id))
}

function addManualQuestion(question) {
  if (isManualSelected(question.id)) return
  manualSelected.value.push({
    question_id: question.id,
    stem: question.stem,
    score: Number(question.score) || 5,
  })
}

function buildDraftAnswer() {
  if (draftQuestion.qtype === 'single') return { key: draftQuestion.answerKey }
  if (draftQuestion.qtype === 'multi') return { keys: draftQuestion.answerKeys }
  if (draftQuestion.qtype === 'judge') return { key: draftQuestion.answerKey === 'true' }
  if (draftQuestion.qtype === 'blank') {
    return { blanks: String(draftQuestion.answerText || '').split('/').map((item) => item.trim()).filter(Boolean) }
  }
  return { text: draftQuestion.answerText || '' }
}

function buildDraftOptions() {
  if (draftQuestion.qtype === 'judge') {
    return [{ key: true, text: '正确' }, { key: false, text: '错误' }]
  }
  if (['single', 'multi'].includes(draftQuestion.qtype)) {
    return draftQuestion.options.filter((item) => item.text.trim())
  }
  return []
}

async function saveDraftQuestion() {
  const course = activeExamCourseId()
  if (!course) return ElMessage.warning('该班级尚未关联课程')
  if (!draftQuestion.catalog) return ElMessage.warning('请选择章节')
  if (!draftQuestion.stem?.trim()) return ElMessage.warning('请填写题干')
  const options = buildDraftOptions()
  if (['single', 'multi'].includes(draftQuestion.qtype) && options.length < 2) {
    return ElMessage.warning('选择题至少填写两个选项')
  }
  const answer = buildDraftAnswer()
  if (draftQuestion.qtype === 'single' && !answer.key) return ElMessage.warning('请选择正确答案')
  if (draftQuestion.qtype === 'multi' && !answer.keys.length) return ElMessage.warning('请选择正确答案')
  if (draftQuestion.qtype === 'judge' && answer.key === '') return ElMessage.warning('请选择正确答案')
  creatingQuestion.value = true
  try {
    const question = await createQuestion({
      course,
      catalog: draftQuestion.catalog,
      qtype: draftQuestion.qtype,
      stem: draftQuestion.stem,
      options,
      answer,
      analysis: draftQuestion.analysis,
      score: draftQuestion.score,
      difficulty: draftQuestion.difficulty,
      source: 'manual',
      status: 'published',
    })
    addManualQuestion(question)
    composeMode.value = 'manual'
    await loadManualQuestions()
    resetDraftQuestion()
    ElMessage.success('题目已加入试卷')
  } finally {
    creatingQuestion.value = false
  }
}

function openCompose(row) {
  currentExam.value = row
  composeMode.value = 'random'
  rules.value = [{ qtype: 'single', difficulty: '', count: 5, score: 2 }]
  manualSelected.value = []
  manualFilters.catalog = null
  manualFilters.qtype = ''
  manualFilters.difficulty = ''
  resetDraftQuestion()
  composeVisible.value = true
  loadCatalogOptions()
  loadManualQuestions()
}
function addRule() {
  rules.value.push({ qtype: 'single', difficulty: '', count: 1, score: 2 })
}
async function doCompose() {
  if (composeMode.value !== 'random' && !manualSelected.value.length) {
    return ElMessage.warning('请先选择或新建题目')
  }
  composing.value = true
  try {
    const payload = composeMode.value === 'random'
      ? { mode: 'random', rules: rules.value }
      : { mode: 'manual', questions: manualSelected.value.map((item) => ({ question_id: item.question_id, score: item.score })) }
    const res = await composePaper(currentExam.value.id, payload)
    ElMessage.success(`组卷完成，共 ${res.question_items.length} 题，总分 ${res.total_score}`)
    composeVisible.value = false
    loadExams()
  } finally {
    composing.value = false
  }
}

// ---- 监控 ----
const monitorVisible = ref(false)
const monitorLoading = ref(false)
const monitorRows = ref([])
async function openMonitor(row) {
  monitorVisible.value = true
  monitorLoading.value = true
  try {
    monitorRows.value = await monitorExam(row.id)
  } finally {
    monitorLoading.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.exam-page :deep(.data-card) {
  padding: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.exam-page :deep(.data-card > .el-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0;
}
.module-toolbar {
  margin: 0 0 16px;
  padding: 0;
  border-bottom: 0;
}
.module-primary-button {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  font-weight: 800;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  box-shadow: 0 11px 22px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.exam-list-shell {
  flex: 1;
  overflow: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.exam-card-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0 0 8px;
}
.exam-list-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100, #e5e9f0);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.exam-list-card:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.exam-card-main {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.exam-kind-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 32px;
  padding: 0 12px;
  border-radius: 9px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
}
.exam-card-content {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}
.exam-card-title {
  overflow: hidden;
  color: #0f172a;
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exam-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  color: #64748b;
  font-size: 12.5px;
  font-weight: 600;
}
.exam-meta-pill,
.exam-status-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}
.exam-meta-pill.duration {
  color: #475569;
  background: #f1f5f9;
}
.exam-score {
  color: #64748b;
  font-weight: 700;
}
.exam-status-pill.draft {
  color: #d97706;
  border: 1px solid #fed7aa;
  background: #fff7ed;
}
.exam-status-pill.published {
  color: #16a34a;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
}
.exam-status-pill.finished {
  color: #64748b;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
}
.exam-meta-pill.blue {
  color: #2563eb;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}
.exam-meta-pill.orange {
  color: #d97706;
  border: 1px solid #fed7aa;
  background: #fff7ed;
}
.exam-meta-pill.slate {
  color: #475569;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
}
.exam-card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.exam-card-actions :deep(.el-button.is-link) {
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}
.exam-card-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.exam-card-actions :deep(.el-button.is-link:hover) {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.exam-card-actions :deep(.el-button--success.is-link:hover) {
  background: #ecfdf5;
}
.exam-card-actions :deep(.el-button--danger.is-link:hover) {
  background: #fff1f2;
}
.exam-card-list :deep(.el-empty) {
  min-height: 430px;
}
.module-table {
  --el-table-border-color: #edf2f8;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: #fff;
  --el-table-row-hover-bg-color: #f8fbff;
  overflow: hidden;
  background: #fff;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  height: 58px;
  padding: 0 24px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 13px;
  font-weight: 850;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.module-table :deep(td.el-table__cell) {
  height: 76px;
  padding: 14px 24px;
  border-bottom: 1px solid #edf2f8;
  color: #334155;
  font-weight: 700;
  background: #fff;
}
.module-table :deep(.el-table__body tr:nth-child(even) > td.el-table__cell) {
  background: #fbfdff;
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: #f8fbff;
}
.module-table :deep(.el-tag) {
  height: 26px;
  padding: 0 10px;
  border-radius: 9px;
  font-weight: 760;
}
.module-table :deep(.el-button.is-link) {
  height: 30px;
  padding: 0 8px;
  border-radius: 9px;
  font-weight: 780;
  text-decoration: none;
}
.module-table :deep(.el-button.is-link:hover) {
  background: #eff6ff;
}
.module-table :deep(.el-button--success.is-link:hover) {
  background: #ecfdf5;
}
.module-table :deep(.el-button--danger.is-link:hover) {
  background: #fff1f2;
}
.exam-list-shell :deep(.el-empty) {
  min-height: 420px;
}
.exam-create-dialog :deep(.el-dialog),
:global(.exam-create-dialog.el-dialog),
.exam-compose-dialog :deep(.el-dialog),
:global(.exam-compose-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.exam-create-dialog :deep(.el-dialog__header),
:global(.exam-create-dialog.el-dialog .el-dialog__header),
.exam-create-dialog :deep(.el-dialog__footer),
:global(.exam-create-dialog.el-dialog .el-dialog__footer) { margin: 0; padding: 0; }
.exam-create-dialog :deep(.el-dialog__body),
:global(.exam-create-dialog.el-dialog .el-dialog__body) { padding: 0; }
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 82px;
  padding: 18px 22px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #fff 0%, #f6faff 100%);
}
.creation-dialog-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 15px;
  color: #2563eb;
  background: #eaf2ff;
  font-size: 21px;
}
.creation-dialog-heading { min-width: 0; }
.creation-dialog-title { color: #14213d; font-size: 19px; font-weight: 800; line-height: 1.25; }
.creation-dialog-subtitle { margin-top: 4px; color: #94a3b8; font-size: 13px; }
.creation-dialog-close { width: 32px; height: 32px; margin-left: auto; color: #94a3b8; }
.creation-dialog-close:hover { color: #2563eb; background: #eff6ff; }
.exam-creation-form { padding: 22px 24px 26px; }
.creation-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-span-full { grid-column: 1 / -1; }
.exam-creation-form :deep(.el-form-item) { margin-bottom: 18px; }
.exam-creation-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}
.exam-creation-form :deep(.el-input__wrapper),
.exam-creation-form :deep(.el-input-number),
.exam-creation-form :deep(.el-date-editor.el-input) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
}
.exam-creation-form :deep(.el-input-number) { width: 100%; }
:global(.exam-datetime-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.48) !important;
  border-radius: 18px !important;
  background: #fff !important;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.18), 0 0 0 6px rgba(219, 234, 254, 0.16) !important;
}
:global(.exam-datetime-popper .el-popper__arrow) {
  display: none;
}
:global(.exam-datetime-popper .el-picker-panel) {
  border: 0;
  border-radius: 18px;
  color: #334155;
  background: #fff;
  box-shadow: none;
}
:global(.exam-datetime-popper .el-date-picker) {
  width: 560px;
}
:global(.exam-datetime-popper .el-date-picker__time-header) {
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input:first-child) {
  width: 214px;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input:last-child) {
  width: 150px;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input__wrapper) {
  min-height: 36px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input__wrapper:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
:global(.exam-datetime-popper .el-date-picker__header) {
  width: 320px;
  margin: 14px 18px 8px;
}
:global(.exam-datetime-popper .el-date-picker__header-label) {
  color: #334155;
  font-size: 15px;
  font-weight: 750;
}
:global(.exam-datetime-popper .el-picker-panel__icon-btn) {
  width: 28px;
  height: 28px;
  margin: 0 1px;
  border-radius: 8px;
  color: #64748b;
}
:global(.exam-datetime-popper .el-picker-panel__icon-btn:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-date-table th) {
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-picker-panel__content) {
  width: 320px;
  margin: 12px 218px 12px 18px;
}
:global(.exam-datetime-popper .el-date-table td .el-date-table-cell) {
  width: 34px;
  height: 34px;
  margin: 1px auto;
  border-radius: 10px;
}
:global(.exam-datetime-popper .el-date-table td.available:hover .el-date-table-cell) {
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-date-table td.available:hover span),
:global(.exam-datetime-popper .el-date-table td.today span) {
  color: #2563eb;
  font-weight: 750;
}
:global(.exam-datetime-popper .el-date-table td.current:not(.disabled) .el-date-table-cell) {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.24);
}
:global(.exam-datetime-popper .el-date-table td.current:not(.disabled) span) {
  color: #fff;
}
:global(.exam-datetime-popper .el-picker-panel__footer) {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px 12px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-picker-panel__footer .el-button) {
  min-width: 64px;
  height: 34px;
  border-radius: 9px;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-picker-panel__footer .el-button--primary) {
  border-color: #3b82f6;
  color: #fff;
  background: #3b82f6;
}
:global(.exam-datetime-popper .el-time-panel) {
  top: 74px !important;
  right: 16px !important;
  left: auto !important;
  width: 178px !important;
  overflow: hidden;
  border: 1px solid #dbe5f2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12);
}
:global(.exam-datetime-popper .el-time-panel::before) {
  content: "选择时间";
  display: block;
  height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid #edf2f8;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 38px;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-time-panel__content) {
  height: 194px;
}
:global(.exam-datetime-popper .el-time-panel__content::before),
:global(.exam-datetime-popper .el-time-panel__content::after) {
  border-color: #e5edf7;
}
:global(.exam-datetime-popper .el-time-spinner__item) {
  color: #64748b;
}
:global(.exam-datetime-popper .el-time-spinner__item:hover:not(.is-disabled):not(.is-active)) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-time-spinner__item.is-active:not(.is-disabled)) {
  color: #2563eb;
  font-weight: 800;
}
:global(.exam-datetime-popper .el-time-panel__footer) {
  height: auto;
  padding: 9px 10px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-time-panel__btn) {
  min-width: 58px;
  height: 32px;
  margin: 0 2px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-time-panel__btn.confirm) {
  color: #fff;
  background: #3b82f6;
}
.setting-item {
  padding: 13px 14px 7px;
  border: 1px solid #e4edf7;
  border-radius: 12px;
  background: #f8fbff;
}
.checkbox-group { gap: 12px 18px; padding-top: 2px; }
.checkbox-group :deep(.el-checkbox) { margin-right: 0; color: #475569; font-weight: 600; }
.exam-status-note { min-height: 42px; display: flex; align-items: center; color: #94a3b8; font-size: 12px; line-height: 1.5; }
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: rgba(248, 250, 252, 0.82);
}
.creation-dialog-footer :deep(.el-button) { min-width: 88px; height: 38px; border-radius: 10px; font-weight: 700; }
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding-top: 6px;
}

.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}

.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}

.text-muted {
  color: #94a3b8;
}
.exam-compose-dialog :deep(.el-dialog__header),
:global(.exam-compose-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 20px 24px 14px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
.exam-compose-dialog :deep(.el-dialog__title),
:global(.exam-compose-dialog.el-dialog .el-dialog__title) {
  color: #0f172a;
  font-size: 20px;
  font-weight: 850;
}
.exam-compose-dialog :deep(.el-dialog__body),
:global(.exam-compose-dialog.el-dialog .el-dialog__body) {
  padding: 18px 22px 20px;
  background: #ffffff;
}
.exam-compose-dialog :deep(.el-dialog__footer),
:global(.exam-compose-dialog.el-dialog .el-dialog__footer) {
  margin: 0;
  padding: 14px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
.exam-compose-dialog :deep(.dialog-footer .el-button) {
  min-width: 92px;
  height: 38px;
  border-radius: 11px;
  font-weight: 760;
}
.compose-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}
.compose-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.compose-tabs :deep(.el-tabs__nav) {
  gap: 8px;
}
.compose-tabs :deep(.el-tabs__active-bar) {
  display: none;
}
.compose-tabs :deep(.el-tabs__item) {
  height: 38px;
  padding: 0 18px !important;
  border: 1px solid #dbeafe;
  border-radius: 11px;
  color: #64748b;
  background: #f8fbff;
  font-weight: 780;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.compose-tabs :deep(.el-tabs__item:hover) {
  border-color: #bfdbfe;
  color: #2563eb;
  background: #eff6ff;
}
.compose-tabs :deep(.el-tabs__item.is-active) {
  border-color: transparent;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}
.compose-tabs :deep(.el-alert) {
  border: 1px solid #dbeafe;
  border-radius: 13px;
  background: #f8fbff;
}
.compose-filter-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.compose-filter-row :deep(.el-select__wrapper),
.compose-custom-form :deep(.el-select__wrapper),
.compose-custom-form :deep(.el-input__wrapper),
.compose-custom-form :deep(.el-textarea__inner),
.compose-custom-form :deep(.el-input-number),
.compose-rule-table :deep(.el-select__wrapper),
.compose-rule-table :deep(.el-input-number) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: none;
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.compose-filter-row :deep(.el-select__wrapper:hover),
.compose-filter-row :deep(.el-select__wrapper.is-focused),
.compose-custom-form :deep(.el-select__wrapper:hover),
.compose-custom-form :deep(.el-select__wrapper.is-focused),
.compose-custom-form :deep(.el-input__wrapper:hover),
.compose-custom-form :deep(.el-input__wrapper.is-focus),
.compose-custom-form :deep(.el-textarea__inner:focus),
.compose-rule-table :deep(.el-select__wrapper:hover),
.compose-rule-table :deep(.el-select__wrapper.is-focused) {
  border-color: #bfdbfe;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.09);
}
.compose-rule-table,
.compose-question-table {
  overflow: hidden;
  border: 1px solid #e5edf7;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.045);
}
.compose-rule-table :deep(.el-table__inner-wrapper::before),
.compose-question-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.compose-rule-table :deep(th.el-table__cell),
.compose-question-table :deep(th.el-table__cell) {
  height: 44px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 13px;
  font-weight: 820;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.compose-rule-table :deep(td.el-table__cell),
.compose-question-table :deep(td.el-table__cell) {
  height: 54px;
  border-bottom-color: #edf2f8;
  color: #334155;
}
.compose-rule-table :deep(.el-table__row:hover > td.el-table__cell),
.compose-question-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: #f8fbff;
}
.compose-rule-table :deep(.el-input-number),
.compose-rule-table :deep(.el-input-number .el-input__wrapper) {
  width: 96px;
}
.compose-manual-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
  gap: 14px;
  align-items: stretch;
}
.selected-paper-box {
  display: flex;
  flex-direction: column;
  min-height: 300px;
  padding: 14px;
  border: 1px solid #e2ebf7;
  border-radius: 16px;
  background: rgba(248, 251, 255, 0.78);
}
.selected-paper-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  color: #334155;
  font-size: 15px;
}
.selected-paper-head strong {
  font-weight: 820;
}
.selected-paper-head span {
  color: #2563eb;
  font-weight: 820;
}
.paper-question-list {
  display: grid;
  align-content: start;
  gap: 8px;
  max-height: 248px;
  overflow: auto;
}
.paper-question-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 82px auto;
  align-items: center;
  gap: 9px;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid #e5edf7;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 5px 14px rgba(37, 99, 235, 0.035);
}
.paper-question-order {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 9px;
  color: #2563eb;
  background: #eff6ff;
  font-weight: 850;
  box-shadow: inset 0 0 0 1px rgba(191, 219, 254, 0.72);
}
.paper-question-stem {
  overflow: hidden;
  color: #1f2937;
  font-size: 14px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.compose-score-input {
  width: 82px;
}
.compose-score-input :deep(.el-input__wrapper) {
  min-height: 34px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
.compose-score-input :deep(.el-input__inner) {
  color: #334155;
  font-weight: 750;
  text-align: center;
}
.compose-custom-form {
  padding: 4px 2px 0;
}
.custom-question-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 14px;
}
.custom-span-full {
  grid-column: 1 / -1;
}
.compose-custom-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
.compose-custom-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 780;
  line-height: 1.35;
}
.custom-compose-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
.custom-compose-actions :deep(.el-button) {
  height: 38px;
  border-radius: 11px;
  font-weight: 780;
}
:global(.exam-compose-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid #bfdbfe !important;
  border-radius: 16px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 18px 38px rgba(37, 99, 235, 0.14), 0 0 0 5px rgba(219, 234, 254, 0.24) !important;
}
:global(.exam-compose-popper .el-popper__arrow) {
  display: none;
}
:global(.exam-compose-popper .el-select-dropdown) {
  border: 0;
  border-radius: 16px;
  background: transparent;
  box-shadow: none;
}
:global(.exam-compose-popper .el-select-dropdown__list) {
  padding: 8px 0;
}
:global(.exam-compose-popper .el-select-dropdown__item) {
  height: 42px;
  padding: 0 18px;
  color: #475569;
  font-size: 14px;
  font-weight: 760;
  line-height: 42px;
}
:global(.exam-compose-popper .el-select-dropdown__item.is-hovering),
:global(.exam-compose-popper .el-select-dropdown__item:hover),
:global(.exam-compose-popper .el-select-dropdown__item.is-selected) {
  color: #2563eb;
  background: #eff6ff;
}
@media (max-width: 1120px) {
  .exam-list-card {
    grid-template-columns: 1fr;
  }

  .exam-card-actions {
    justify-content: flex-start;
    width: 100%;
    min-width: 0;
  }
}
@media (max-width: 920px) {
  .compose-manual-grid,
  .compose-filter-row,
  .custom-question-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .exam-page :deep(.data-card > .el-card__body) {
    padding: 20px 18px 24px;
  }

  .exam-card-main {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .exam-list-card {
    padding: 18px;
  }

  .exam-card-actions {
    flex-wrap: wrap;
    min-height: auto;
    padding: 10px;
  }
}
</style>
