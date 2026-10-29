<template>
  <div class="page-container class-manage">
    <div class="class-toolbar">
      <template v-if="isAdmin">
        <el-button type="primary" :icon="Plus" @click="openEdit()">新建班级</el-button>
        <el-button :icon="Upload" @click="importVisible = true">批量导入班级</el-button>
      </template>
      <span v-else class="class-hint">
        <el-icon><InfoFilled /></el-icon>
        班级由学校统一分配，如需调整请联系管理员
      </span>
    </div>

    <TableSkeleton v-if="loading" :cols="4" />

    <div v-else-if="rows.length" class="class-list animate-list">
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
          <span class="meta-item">
            <span class="meta-label">学生</span>
            <strong>{{ row.student_count || 0 }} 人</strong>
          </span>
          <span v-if="isAdmin && row.code" class="meta-item">
            <span class="meta-label">编码</span>
            <strong class="meta-code">{{ row.code }}</strong>
          </span>
          <el-tag :type="classStatusMeta(row.status).type" effect="light" round>
            {{ classStatusMeta(row.status).label }}
          </el-tag>
        </div>

        <div class="class-actions">
          <el-button link type="primary" :icon="User" @click="openStudents(row)">学生</el-button>
          <template v-if="isAdmin">
            <span class="action-divider"></span>
            <el-button text circle :icon="EditPen" title="编辑班级" @click="openEdit(row)" />
            <el-button text circle type="danger" :icon="Delete" title="删除班级" @click="openDelete(row, 'class')" />
          </template>
        </div>
      </article>
    </div>

    <el-empty v-else :description="isAdmin ? '还没有班级，点击右上角新建' : '暂无可管理的班级'" />

    <el-pagination
      v-if="total > pageSize"
      class="class-pager"
      background
      layout="prev, pager, next, total"
      :total="total"
      :page-size="pageSize"
      :current-page="page"
      @current-change="changePage"
    />

    <!-- 新建/编辑班级 -->
    <el-dialog v-model="editVisible" width="620px" align-center :show-close="false" class="class-form-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon class-create-icon">
            <el-icon><School /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ form.id ? '编辑班级' : '新建班级' }}</div>
            <div class="creation-dialog-subtitle">
              {{ form.id ? (form.creator_name ? `建班人：${form.creator_name}` : '班级基础信息') : '编码用于批量导入匹配，请与学籍系统保持一致' }}
            </div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="editVisible = false" />
        </div>
      </template>

      <el-form :model="form" label-position="top" class="creation-form class-creation-form">
        <div class="creation-form-grid">
          <el-form-item label="班级编码">
            <el-input v-model="form.code" placeholder="如 CS-2401" maxlength="32" />
          </el-form-item>
          <el-form-item label="班级名称">
            <el-input v-model="form.name" placeholder="如 计算机2401班" />
          </el-form-item>
          <el-form-item label="届别（入学年份）">
            <el-input-number v-model="form.enrollment_year" :min="2000" :max="2100" :controls="false"
              placeholder="如 2024" style="width: 100%" />
          </el-form-item>
          <el-form-item label="学制（年）">
            <el-input-number v-model="form.duration_years" :min="2" :max="8" :controls="false" style="width: 100%" />
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
              <el-radio-button v-for="opt in CLASS_STATUS_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</el-radio-button>
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

    <!-- 班级批量导入（仅管理端可见）：上传 → 预览 → 结果 -->
    <ImportWizard v-if="isAdmin" v-model="importVisible" kind="class" @done="reloadAfterImport" />

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除班级"
      :item-name="deleteTarget?.name"
      description="删除后，该班级及其成员关系将无法继续访问，此操作无法撤销。"
      action-text="删除"
      confirm-text="确认删除"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Delete, EditPen, User, School, Close, InfoFilled, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import ImportWizard from '@/components/admin/ImportWizard.vue'
import { CLASS_STATUS_OPTIONS, classStatusMeta } from '@/utils/classStatus'
import { listCourses } from '@/api/course'
import { compareCourseName } from '@/utils/course-sort'
import { useUserStore } from '@/store/user'
import {
  listClasses, createClass, updateClass, deleteClass,
} from '@/api/classroom'

// 组织层（建班 / 改班 / 删班）只对管理员开放；教师进这个页面看到的是只读名单。
const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin())

const courses = ref([])
const rows = ref([])
const loading = ref(false)
// 班级批量导入向导（仅管理员可见）
const importVisible = ref(false)
// 服务端分页：批量导入一次最多 200 个班，列表必须能翻页（后端单页上限 100）
const total = ref(0)
const page = ref(1)
const pageSize = 20

async function loadCourses() {
  const data = await listCourses()
  courses.value = data.results ?? data
}
async function load() {
  loading.value = true
  try {
    const data = await listClasses({ page: page.value, page_size: pageSize })
    rows.value = sortClassCourses(data.results ?? data)
    total.value = typeof data.total === 'number' ? data.total : rows.value.length
  } finally {
    loading.value = false
  }
}
function changePage(value) {
  page.value = value
  load()
}
// 导入完成：跳到最后一页——列表按 id 升序，新建的班在末尾，
// 停在第一页会让管理员「导完看不到新建的班」。
async function reloadAfterImport() {
  await load()
  const last = Math.max(1, Math.ceil(total.value / pageSize))
  if (last !== page.value) {
    page.value = last
    await load()
  }
}

// 班级卡片课程显示统一按「首字母」排序（比较规则见 utils/course-sort）。
// courses 与 course_names 必须成对重排，否则下标错位会串课程（courseOptions、
// openEdit 已选课程等按下标取名的消费方都依赖这个对齐）。
function sortClassCourses(list) {
  if (!Array.isArray(list)) return list
  return list.map((row) => {
    const names = row?.course_names
    const ids = row?.courses
    if (!Array.isArray(names) || names.length < 2) return row
    if (!Array.isArray(ids) || ids.length !== names.length) return row
    const pairs = names.map((name, i) => ({ id: ids[i], name }))
    pairs.sort((a, b) => compareCourseName(a.name, b.name))
    return {
      ...row,
      courses: pairs.map((p) => p.id),
      course_names: pairs.map((p) => p.name),
      course: pairs[0].id,
      course_name: pairs[0].name,
    }
  })
}

// ---- 新建/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})
function openEdit(row) {
  Object.assign(form, {
    id: row?.id || null,
    code: row?.code || '',
    courses: row?.courses?.length
      ? [...row.courses]
      : (row?.course ? [row.course] : (courses.value[0]?.id ? [courses.value[0].id] : [])),
    name: row?.name || '',
    enrollment_year: row?.enrollment_year || null,
    duration_years: row?.duration_years || 4,
    creator_name: row?.teacher_name || '',
    dateRange: row?.start_at && row?.end_at ? [row.start_at, row.end_at] : [],
    status: row?.status || 'active',
  })
  editVisible.value = true
}
async function save() {
  if (!form.code?.trim()) return ElMessage.warning('请填写班级编码')
  if (!form.courses?.length) return ElMessage.warning('请至少选择一门课程')
  if (!form.name) return ElMessage.warning('请填写班级名称')
  const payload = {
    code: form.code.trim().toUpperCase(),
    courses: form.courses, name: form.name, status: form.status,
    enrollment_year: form.enrollment_year || null,
    duration_years: form.duration_years || 4,
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

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteClass(deleteTarget.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    await load()
  } finally {
    deleting.value = false
  }
}
// ---- 学生名单（独立页面：列表 + 筛选 + 排序） ----
const router = useRouter()
function openStudents(row) {
  // 管理员与教师共用同一个名单页，路由名不同（侧边栏高亮跟着各自菜单走）
  const name = isAdmin.value ? 'admin-class-students' : 'class-students'
  router.push({ name, params: { classId: row.id } })
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

/* 分页：批量导入后班级数会超过单页上限，翻页入口放在列表下方右对齐 */
.class-pager {
  justify-content: flex-end;
  padding-top: 18px;
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

.class-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 14px;
  margin-right: auto;
  border-radius: 10px;
  background: #f8fafc;
  color: #94a3b8;
  font-size: 13px;
}

.meta-code {
  color: #2563eb;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
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
