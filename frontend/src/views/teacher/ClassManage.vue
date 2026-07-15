<template>
  <div class="page-container class-manage">
    <div class="class-toolbar">
      <el-button type="primary" :icon="Plus" @click="openEdit()">新建班级</el-button>
    </div>

    <TableSkeleton v-if="loading" :cols="4" />

    <div v-else-if="rows.length" class="class-list">
      <article v-for="row in rows" :key="row.id" class="class-row">
        <div class="class-primary">
          <span class="class-icon">
            <el-icon><School /></el-icon>
          </span>
          <span class="class-title-wrap">
            <strong class="class-name">{{ row.name }}</strong>
            <span class="class-course">{{ row.course_names?.join('、') || row.course_name || '未关联课程' }}</span>
          </span>
        </div>

        <div class="class-meta">
          <span class="invite-chip">
            <span class="invite-chip-label">邀请码</span>
            <code>{{ row.invite_code }}</code>
          </span>
          <span class="meta-item">
            <span class="meta-label">学生</span>
            <strong>{{ row.student_count || 0 }} 人</strong>
          </span>
          <el-tag :type="row.status === 'open' ? 'success' : 'info'" effect="light" round>
            {{ row.status === 'open' ? '开课中' : '已结课' }}
          </el-tag>
        </div>

        <div class="class-actions">
          <el-button link type="primary" :icon="User" @click="openStudents(row)">学生</el-button>
          <el-button link type="primary" :icon="Refresh" @click="regenCode(row)">换邀请码</el-button>
          <span class="action-divider"></span>
          <el-button text circle :icon="EditPen" title="编辑班级" @click="openEdit(row)" />
          <el-button text circle type="danger" :icon="Delete" title="删除班级" @click="openDelete(row, 'class')" />
        </div>
      </article>
    </div>

    <el-empty v-else description="还没有班级，点击右上角新建" />

    <!-- 新建/编辑班级 -->
    <el-dialog v-model="editVisible" width="620px" align-center :show-close="false" class="class-form-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon class-create-icon">
            <el-icon><School /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ form.id ? '编辑班级' : '新建班级' }}</div>
            <div class="creation-dialog-subtitle">班级基础信息</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="editVisible = false" />
        </div>
      </template>

      <el-form :model="form" label-position="top" class="creation-form class-creation-form">
        <div class="creation-form-grid">
          <el-form-item label="班级名称" class="form-span-full">
            <el-input v-model="form.name" placeholder="如 计科2201班" />
          </el-form-item>
          <el-form-item label="关联课程" class="form-span-full">
            <el-select
              v-model="form.courses"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              placeholder="选择一门或多门课程"
              style="width: 100%"
            >
              <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="开课 / 结课" class="form-span-full">
            <el-date-picker v-model="form.dateRange" type="daterange" range-separator="至"
              start-placeholder="开课" end-placeholder="结课" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="状态" class="form-span-full class-status-item">
            <el-radio-group v-model="form.status" class="class-status-switch">
              <el-radio-button value="open">开课中</el-radio-button>
              <el-radio-button value="closed">已结课</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">{{ form.id ? '保存修改' : '创建班级' }}</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 学生名单 -->
    <el-drawer v-model="studentsVisible" :title="`${currentClass?.name} · 学生名单`" size="46%">
      <div class="add-bar">
        <el-input v-model="addName" placeholder="输入学生用户名手动添加" :prefix-icon="User" @keyup.enter="doAddStudent" />
        <el-button type="primary" :loading="adding" @click="doAddStudent">添加</el-button>
      </div>
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
        :title="`邀请码：${currentClass?.invite_code} —— 学生也可在「我的班级」输入邀请码自助加入`" />
      <el-table :data="students" v-loading="studentsLoading" stripe>
        <el-table-column prop="student_name" label="姓名" width="120" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column label="加入时间" min-width="160">
          <template #default="{ row }">{{ row.joined_at ? new Date(row.joined_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="danger" :icon="Delete" @click="openDelete(row, 'student')">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!studentsLoading && !students.length" description="暂无学生，用邀请码或上方手动添加" />
    </el-drawer>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      :title="deleteTarget?.type === 'student' ? '移出学生' : '删除班级'"
      :item-name="deleteTarget?.type === 'student'
        ? (deleteTarget?.row?.student_name || deleteTarget?.row?.username)
        : deleteTarget?.row?.name"
      :description="deleteTarget?.type === 'student'
        ? '移出后，该学生将不再属于当前班级，需要重新添加或使用邀请码加入。'
        : '删除后，该班级及其成员关系将无法继续访问，此操作无法撤销。'"
      :action-text="deleteTarget?.type === 'student' ? '移出' : '删除'"
      :confirm-text="deleteTarget?.type === 'student' ? '确认移出' : '确认删除'"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Plus, Delete, EditPen, User, Refresh, School, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listCourses } from '@/api/course'
import {
  listClasses, createClass, updateClass, deleteClass, regenerateCode,
  addStudent, listClassStudents, removeClassStudent,
} from '@/api/classroom'

const courses = ref([])
const rows = ref([])
const loading = ref(false)

async function loadCourses() {
  const data = await listCourses()
  courses.value = data.results ?? data
}
async function load() {
  loading.value = true
  try {
    const data = await listClasses()
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

// ---- 新建/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})
function openEdit(row) {
  Object.assign(form, {
    id: row?.id || null,
    courses: row?.courses?.length
      ? [...row.courses]
      : (row?.course ? [row.course] : (courses.value[0]?.id ? [courses.value[0].id] : [])),
    name: row?.name || '',
    dateRange: row?.start_at && row?.end_at ? [row.start_at, row.end_at] : [],
    status: row?.status || 'open',
  })
  editVisible.value = true
}
async function save() {
  if (!form.courses?.length) return ElMessage.warning('请至少选择一门课程')
  if (!form.name) return ElMessage.warning('请填写班级名称')
  const payload = {
    courses: form.courses, name: form.name, status: form.status,
    start_at: form.dateRange?.[0] || null, end_at: form.dateRange?.[1] || null,
  }
  saving.value = true
  try {
    if (form.id) { await updateClass(form.id, payload); ElMessage.success('已更新') }
    else { await createClass(payload); ElMessage.success('已创建') }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

function openDelete(row, type) {
  deleteTarget.value = { row, type }
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    if (deleteTarget.value.type === 'student') {
      await removeClassStudent(deleteTarget.value.row.id)
      ElMessage.success('已移出')
      await loadStudents()
    } else {
      await deleteClass(deleteTarget.value.row.id)
      ElMessage.success('已删除')
    }
    deleteVisible.value = false
    deleteTarget.value = null
    await load()
  } finally {
    deleting.value = false
  }
}
async function regenCode(row) {
  const res = await regenerateCode(row.id)
  ElMessage.success(`新邀请码：${res.invite_code}`)
  load()
}

// ---- 学生名单 ----
const studentsVisible = ref(false)
const studentsLoading = ref(false)
const students = ref([])
const currentClass = ref(null)
const addName = ref('')
const adding = ref(false)

async function openStudents(row) {
  currentClass.value = row
  studentsVisible.value = true
  loadStudents()
}
async function loadStudents() {
  studentsLoading.value = true
  try {
    const data = await listClassStudents({ classroom: currentClass.value.id })
    students.value = data.results ?? data
  } finally {
    studentsLoading.value = false
  }
}
async function doAddStudent() {
  const name = addName.value.trim()
  if (!name) return
  adding.value = true
  try {
    await addStudent(currentClass.value.id, name)
    ElMessage.success('已添加')
    addName.value = ''
    loadStudents()
    load()
  } finally {
    adding.value = false
  }
}
onMounted(() => { loadCourses(); load() })
</script>

<style scoped>
.class-manage {
  display: flex;
  flex-direction: column;
}

.class-toolbar {
  min-height: 52px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding-bottom: 18px;
}

.class-toolbar :deep(.el-button) {
  height: 40px;
  padding: 0 18px;
  border-radius: 10px;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.16);
}

.class-list {
  display: grid;
  gap: 14px;
  padding-top: 20px;
}

.class-row {
  min-height: 80px;
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(360px, auto) auto;
  align-items: center;
  gap: 24px;
  padding: 14px 18px;
  border: 1px solid rgba(37, 99, 235, 0.06);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.06);
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.class-row:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.34);
  box-shadow: 0 16px 34px rgba(37, 99, 235, 0.1);
}

.class-primary {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 14px;
}

.class-icon {
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #eff6ff;
  color: #3b82f6;
  font-size: 21px;
}

.class-title-wrap {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.class-name {
  overflow: hidden;
  color: #0f172a;
  font-size: 16px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.class-course {
  overflow: hidden;
  color: #64748b;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.class-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 18px;
}

.meta-item {
  display: grid;
  gap: 4px;
  color: #334155;
  font-size: 13px;
  line-height: 1.2;
}

.meta-label {
  color: #94a3b8;
  font-size: 12px;
}

.invite-chip {
  height: 34px;
  display: inline-flex;
  align-items: center;
  overflow: hidden;
  border-radius: 999px;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.1);
}

.invite-chip-label {
  padding: 0 8px 0 12px;
  color: #94a3b8;
  font-size: 12px;
}

.invite-chip code {
  align-self: stretch;
  display: inline-flex;
  align-items: center;
  padding: 0 12px 0 9px;
  border-left: 1px solid rgba(59, 130, 246, 0.12);
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.3px;
}

.class-actions {
  min-height: 46px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
}

.action-divider {
  width: 1px;
  height: 26px;
  margin: 0 4px;
  background: #e2e8f0;
}

.class-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.class-actions :deep(.el-button.is-circle) {
  width: 32px;
  height: 32px;
}

.class-form-dialog :deep(.el-dialog),
:global(.class-form-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

.class-form-dialog :deep(.el-dialog__header),
:global(.class-form-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}

.class-form-dialog :deep(.el-dialog__body),
:global(.class-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}

.class-form-dialog :deep(.el-dialog__footer),
:global(.class-form-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}

.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 86px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}

.creation-dialog-icon {
  width: 44px;
  height: 44px;
  display: grid;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  font-size: 21px;
}

.class-create-icon {
  background: #e8f4ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}

.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}

.creation-dialog-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.25;
}

.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
}

.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}

.class-creation-form {
  padding: 22px 24px 26px;
}

.creation-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 16px;
}

.form-span-full {
  grid-column: 1 / -1;
}

.creation-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.creation-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

.creation-form :deep(.el-input__wrapper),
.creation-form :deep(.el-select__wrapper),
.creation-form :deep(.el-date-editor.el-input__wrapper) {
  min-height: 44px;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
  transition: box-shadow 0.2s ease, background-color 0.2s ease;
}

.creation-form :deep(.el-input__wrapper:hover),
.creation-form :deep(.el-select__wrapper:hover),
.creation-form :deep(.el-date-editor.el-input__wrapper:hover) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}

.creation-form :deep(.el-input__wrapper.is-focus),
.creation-form :deep(.el-select__wrapper.is-focused),
.creation-form :deep(.el-date-editor.is-active) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.class-status-item {
  margin-bottom: 0 !important;
}

.class-status-switch :deep(.el-radio-button__inner) {
  min-width: 104px;
  padding: 10px 18px;
  border-color: #dbe5f2;
  background: #f8fbff;
  box-shadow: none;
  color: #64748b;
  font-weight: 650;
}

.class-status-switch :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: 10px 0 0 10px;
}

.class-status-switch :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 10px 10px 0;
}

.class-status-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: var(--primary-500);
  background: var(--primary-50);
  box-shadow: -1px 0 0 0 var(--primary-500);
  color: var(--primary-600);
}

.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 20px;
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

.add-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

@media (max-width: 1280px) {
  .class-row {
    grid-template-columns: minmax(220px, 1fr) auto;
  }

  .class-meta {
    justify-content: flex-start;
  }

  .class-actions {
    grid-column: 1 / -1;
    justify-self: end;
  }
}

@media (max-width: 720px) {
  .class-form-dialog :deep(.el-dialog),
  :global(.class-form-dialog.el-dialog) {
    width: calc(100% - 28px) !important;
  }

  .creation-form-grid {
    grid-template-columns: 1fr;
  }

  .form-span-full {
    grid-column: auto;
  }

  .creation-dialog-header {
    min-height: 76px;
    padding: 18px 18px 16px;
  }

  .class-creation-form {
    padding: 18px 18px 22px;
  }

  .creation-dialog-footer {
    padding: 14px 18px 18px;
  }

  .class-row {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .class-meta {
    flex-wrap: wrap;
  }

  .class-actions {
    grid-column: auto;
    width: 100%;
    justify-content: flex-end;
    box-sizing: border-box;
  }
}
</style>
