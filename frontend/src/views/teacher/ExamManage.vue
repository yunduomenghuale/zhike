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
          <el-select v-model="classId" class="module-select" placeholder="选择班级" style="width: 280px" @change="loadExams">
            <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openCreate">新建考试</el-button>
        </div>
      </div>

      <el-empty v-if="!classId" description="请先选择班级">
        <template #description>
          <div class="empty-text">请先选择班级</div>
          <div class="empty-tip">选择班级后即可查看与管理该班级的考试</div>
        </template>
      </el-empty>

      <TableSkeleton v-else-if="loading" :cols="6" />
      <el-table v-else :data="exams" class="module-table" stripe>
        <el-table-column prop="name" label="考试名称" min-width="160" />
        <el-table-column prop="duration" label="时长(分)" width="90" align="center" />
        <el-table-column prop="total_score" label="总分" width="80" align="center" />
        <el-table-column label="模式" min-width="180">
          <template #default="{ row }">
            <el-tag v-if="row.shuffle_questions" size="small" type="primary" effect="plain" round style="margin-right: 4px">题目乱序</el-tag>
            <el-tag v-if="row.shuffle_options" size="small" type="warning" effect="plain" round style="margin-right: 4px">选项乱序</el-tag>
            <el-tag v-if="row.per_student_paper" size="small" type="info" effect="plain" round>一人一卷</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="{ published: 'success', finished: 'info', draft: 'warning' }[row.status]" effect="light" round>
              {{ row.status_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" :icon="EditPen" @click="openCompose(row)">组卷</el-button>
            <el-button v-if="row.status === 'draft'" link type="success" :icon="VideoPlay" @click="setStatus(row, 'published')">发布</el-button>
            <el-button v-if="row.status === 'published'" link type="info" :icon="CircleClose" @click="setStatus(row, 'finished')">结束</el-button>
            <el-button link type="primary" :icon="View" @click="openMonitor(row)">监控</el-button>
            <el-button link type="danger" :icon="Delete" @click="openDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建考试 -->
    <el-dialog v-model="createVisible" width="640px" align-center :show-close="false" class="exam-create-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon exam-create-icon"><el-icon><Document /></el-icon></span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">新建考试</div>
            <div class="creation-dialog-subtitle">设置考试规则与发布方式</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="createVisible = false" />
        </div>
      </template>
      <el-form :model="form" label-position="top" class="exam-creation-form">
        <div class="creation-form-grid">
          <el-form-item label="考试名称" class="form-span-full"><el-input v-model="form.name" placeholder="请输入考试名称" /></el-form-item>
          <el-form-item label="考试时长（分钟)"><el-input-number v-model="form.duration" :min="1" /></el-form-item>
          <el-form-item label="发布状态"><div class="exam-status-note">创建后先保存为草稿，可完成组卷后发布。</div></el-form-item>
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
          <el-button type="primary" :loading="saving" @click="save">创建</el-button>
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

    <!-- 随机组卷 -->
    <el-dialog v-model="composeVisible" title="随机组卷" width="680px" align-center class="exam-compose-dialog">
      <el-alert type="info" :closable="false" show-icon description="按题型/难度从课程题库随机抽题；请确保题库中已有【已发布】状态的题目。" style="margin-bottom: 16px" />
      <el-table :data="rules" border size="small">
        <el-table-column label="题型" width="130">
          <template #default="{ row }">
            <el-select v-model="row.qtype" size="small">
              <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="难度" width="120">
          <template #default="{ row }">
            <el-select v-model="row.difficulty" size="small" clearable placeholder="不限">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="110">
          <template #default="{ row }"><el-input-number v-model="row.count" :min="1" size="small" /></template>
        </el-table-column>
        <el-table-column label="每题分" width="110">
          <template #default="{ row }"><el-input-number v-model="row.score" :min="1" size="small" /></template>
        </el-table-column>
        <el-table-column width="70" align="center">
          <template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="rules.splice($index, 1)"></el-button></template>
        </el-table-column>
      </el-table>
      <el-button link type="primary" :icon="Plus" style="margin-top: 12px" @click="addRule">添加规则</el-button>
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

// ---- 新建 ----
const createVisible = ref(false)
const saving = ref(false)
const form = reactive({})
function openCreate() {
  Object.assign(form, {
    name: '', duration: 60,
    shuffle_questions: true, shuffle_options: true,
    per_student_paper: false, show_analysis_after: true, allow_resubmit: false,
    anti: { detect_blur: true, forbid_copy: true, forbid_paste: true, forbid_contextmenu: true },
  })
  createVisible.value = true
}
async function save() {
  if (!form.name) return ElMessage.warning('请填写考试名称')
  const cls = classes.value.find((c) => c.id === classId.value)
  const courseId = fixedCourseId.value || cls?.course
  if (!courseId) return ElMessage.warning('该班级尚未关联课程')
  saving.value = true
  try {
    await createExam({
      course: courseId, classroom: classId.value,
      name: form.name, duration: form.duration,
      shuffle_questions: form.shuffle_questions, shuffle_options: form.shuffle_options,
      per_student_paper: form.per_student_paper, show_analysis_after: form.show_analysis_after,
      allow_resubmit: form.allow_resubmit, anti_cheat: form.anti, status: 'draft',
    })
    ElMessage.success('已创建')
    createVisible.value = false
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
const rules = ref([])
function openCompose(row) {
  currentExam.value = row
  rules.value = [{ qtype: 'single', difficulty: '', count: 5, score: 2 }]
  composeVisible.value = true
}
function addRule() {
  rules.value.push({ qtype: 'single', difficulty: '', count: 1, score: 2 })
}
async function doCompose() {
  composing.value = true
  try {
    const res = await composePaper(currentExam.value.id, { mode: 'random', rules: rules.value })
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
.exam-page :deep(.data-card) { padding: 0; }
.exam-page :deep(.data-card > .el-card__body) { padding: 0; }
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
.exam-creation-form :deep(.el-input-number) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
}
.exam-creation-form :deep(.el-input-number) { width: 100%; }
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
</style>
