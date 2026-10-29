<template>
  <div class="page-container class-students">
    <!-- 页头：返回 + 班级信息 -->
    <div class="roster-head">
      <el-button text circle :icon="ArrowLeft" title="返回班级列表" @click="goBack" />
      <span class="roster-icon">
        <el-icon><School /></el-icon>
      </span>
      <div class="roster-heading">
        <div class="roster-title">{{ cls?.name || '学生名单' }}</div>
        <div class="roster-subtitle">{{ cls ? (cls.course_names?.join('、') || cls.course_name || '未关联课程') : ' ' }}</div>
      </div>
      <span class="roster-count">共 {{ students.length }} 名学生</span>
    </div>

    <!-- 工具栏：搜索 / 状态筛选 / 排序 + 添加学生 -->
    <div class="roster-toolbar">
      <div class="roster-toolbar-left">
        <el-input
          v-model="keyword"
          class="roster-search"
          placeholder="搜索学号或姓名（支持前缀，如 2024 圈全班）"
          :prefix-icon="Search"
          clearable
        />
        <el-select v-model="statusFilter" class="roster-filter" @change="resetPage">
          <el-option label="全部状态" value="all" />
          <el-option label="学习中" value="active" />
          <el-option label="未活跃" value="inactive" />
        </el-select>
        <el-select v-model="sortBy" class="roster-sort">
          <el-option label="按加入时间（最新优先）" value="joined_desc" />
          <el-option label="按加入时间（最早优先）" value="joined_asc" />
          <el-option label="按学号" value="username" />
          <el-option label="按姓名" value="name" />
        </el-select>
      </div>
      <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="addVisible = true">添加学生</el-button>
    </div>

    <TableSkeleton v-if="loading" :cols="5" />
    <el-empty v-else-if="!students.length" :description="isAdmin ? '暂无学生，可用右上角按钮添加或批量导入' : '暂无学生'" />
    <el-empty v-else-if="!pagedStudents.length" description="没有符合条件的学生" :image-size="60" />

    <template v-else>
      <el-table :data="pagedStudents" class="roster-table" scrollbar-always-on row-key="id">
        <el-table-column label="学生" min-width="200">
          <template #default="{ row }">
            <div class="stu-cell stu-cell-link" :title="'查看 ' + (row.student_name || row.username) + ' 的学习详情'" @click="openDetail(row)">
              <span class="stu-avatar-sm" :style="{ background: avatarBg(row.student_name || row.username) }">
                <img v-if="row.avatar" :src="row.avatar" class="stu-avatar-img" alt="" @error="$event.target.style.display = 'none'" />
                <template v-else>{{ (row.student_name || row.username || '?').charAt(0) }}</template>
              </span>
              <div class="stu-cell-text">
                <span class="stu-name">{{ row.student_name || '未填写姓名' }}</span>
                <span class="stu-username">{{ row.username }}</span>
              </div>
              <el-icon class="stu-link-ico"><ArrowRight /></el-icon>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="学号" prop="username" width="150" sortable :sort-method="sortText('username')" />
        <el-table-column label="加入时间" width="160" sortable :sort-method="sortJoined">
          <template #default="{ row }">{{ fmtJoined(row.joined_at) }}</template>
        </el-table-column>
        <el-table-column label="最近登录" width="160" sortable :sort-method="sortLastLogin">
          <template #default="{ row }">{{ row.last_login ? fmtJoined(row.last_login) : '—' }}</template>
        </el-table-column>
        <el-table-column label="学习状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.learn_status === 'active' ? 'success' : 'info'" effect="light" round>
              {{ row.learn_status === 'active' ? '学习中' : '未活跃' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button v-if="isAdmin" link type="danger" @click="openRemove(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="filteredStudents.length > pageSize"
        class="roster-pager"
        background
        layout="prev, pager, next, total"
        :total="filteredStudents.length"
        :page-size="pageSize"
        :current-page="page"
        @current-change="(v) => (page = v)"
      />
    </template>

    <!-- 添加学生：搜索候选 + 勾选批量添加 -->
    <el-dialog v-model="addVisible" width="720px" align-center title="添加学生" @closed="closeAdd">
      <div class="add-bar">
        <el-input
          v-model="addKeyword"
          placeholder="搜索学号或姓名（支持前缀，如 2024 圈全班）"
          :prefix-icon="User"
          clearable
          @input="onSearchInput"
          @clear="clearSearch"
        />
      </div>
      <div v-if="searchKeyword" class="cand-panel">
        <div class="cand-head">
          <el-checkbox
            :model-value="isAllChecked"
            :indeterminate="isIndeterminate"
            :disabled="!checkableCandidates.length"
            @change="toggleAll"
          >全选（{{ checkableCandidates.length }} 人可选）</el-checkbox>
          <span class="cand-hint">已选 {{ selectedIds.size }} 人</span>
          <el-button
            type="primary"
            size="small"
            :loading="adding"
            :disabled="!selectedIds.size"
            @click="doBatchAdd"
          >批量添加（{{ selectedIds.size }}）</el-button>
        </div>
        <div v-loading="searching" class="cand-list">
          <el-empty v-if="!searching && !candidates.length" description="未找到匹配的学生" :image-size="60" />
          <div
            v-for="c in candidates"
            :key="c.id"
            class="cand-row"
            :class="{ 'in-class': c.already_in, 'no-profile': !c.profile_complete }"
          >
            <el-checkbox
              :model-value="selectedIds.has(c.username)"
              :disabled="c.already_in"
              @change="toggleOne(c.username)"
            />
            <span class="cand-no">{{ c.username }}</span>
            <span class="cand-name">{{ c.real_name || '未填写姓名' }}</span>
            <span class="cand-cls" :class="{ empty: !c.current_class }">{{ c.current_class || '未分班' }}</span>
            <el-tag v-if="c.already_in" size="small" type="info" effect="plain">已在班</el-tag>
            <el-tag v-else-if="!c.profile_complete" size="small" type="warning">资料不全</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-else description="输入学号或姓名搜索学生，勾选后批量添加" :image-size="70" />
    </el-dialog>

    <DeleteConfirmDialog
      v-model="removeVisible"
      title="移出学生"
      :item-name="removeTarget?.student_name || removeTarget?.username"
      description="移出后，该学生将不再属于当前班级，需要重新添加或使用邀请码加入。"
      action-text="移出"
      confirm-text="确认移出"
      :loading="removing"
      @confirm="confirmRemove"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Plus, School, Search, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { useUserStore } from '@/store/user'
import {
  listClasses, listClassStudents, removeClassStudent, searchClassStudents, addStudentsBatch,
} from '@/api/classroom'

const route = useRoute()
const router = useRouter()
const classId = Number(route.params.classId)

// 名单可读；加人 / 移人是组织动作，只对管理员开放（教师看到的是只读名单）。
const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin())

const cls = ref(null)
const students = ref([])
const loading = ref(false)

const keyword = ref('')
const statusFilter = ref('all')
const sortBy = ref('joined_desc')
const page = ref(1)
const pageSize = 20

const AVATAR_COLORS = ['#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#f97316']
function avatarBg(name) {
  let hash = 0
  for (const ch of name || '') hash = (hash * 31 + ch.codePointAt(0)) >>> 0
  const color = AVATAR_COLORS[hash % AVATAR_COLORS.length]
  return `linear-gradient(135deg, ${color} 0%, ${color}cc 100%)`
}
function fmtJoined(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ---- 数据加载 ----
async function loadClass() {
  const data = await listClasses()
  const list = data.results ?? data
  cls.value = list.find((item) => item.id === classId) || null
}
async function loadStudents() {
  loading.value = true
  try {
    // page_size=100：单班上限受导入 500 行限制，一次拉全再本地筛选排序
    const data = await listClassStudents({ classroom: classId, page_size: 100 })
    students.value = data.results ?? data ?? []
  } finally {
    loading.value = false
  }
}

// ---- 筛选 / 排序 / 分页（本地） ----
const filteredStudents = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return students.value.filter((s) => {
    if (statusFilter.value !== 'all' && s.learn_status !== statusFilter.value) return false
    if (!kw) return true
    return (s.username || '').toLowerCase().includes(kw)
      || (s.student_name || '').toLowerCase().includes(kw)
  })
})
const sortedStudents = computed(() => {
  const list = [...filteredStudents.value]
  if (sortBy.value === 'joined_desc') list.sort((a, b) => new Date(b.joined_at) - new Date(a.joined_at))
  else if (sortBy.value === 'joined_asc') list.sort((a, b) => new Date(a.joined_at) - new Date(b.joined_at))
  else if (sortBy.value === 'username') list.sort((a, b) => String(a.username).localeCompare(String(b.username), 'zh-Hans-CN', { numeric: true }))
  else list.sort((a, b) => String(a.student_name || '').localeCompare(String(b.student_name || ''), 'zh-Hans-CN'))
  return list
})
const pagedStudents = computed(() => sortedStudents.value.slice((page.value - 1) * pageSize, page.value * pageSize))
function resetPage() { page.value = 1 }

// el-table 表头排序与下拉排序并存：列排序只做该列的单次比较
const sortText = (field) => (a, b) => String(a[field] || '').localeCompare(String(b[field] || ''), 'zh-Hans-CN', { numeric: true })
const sortJoined = (a, b) => new Date(a.joined_at) - new Date(b.joined_at)
const sortLastLogin = (a, b) => new Date(a.last_login || 0) - new Date(b.last_login || 0)

// ---- 学生详情 ----
const courseOptions = computed(() => {
  const ids = cls.value?.courses?.length
    ? cls.value.courses
    : (cls.value?.course ? [cls.value.course] : [])
  const names = cls.value?.course_names || []
  return ids.map((id, i) => ({ id, name: names[i] || cls.value?.course_name || `课程 ${id}` }))
})
function openDetail(stu) {
  const course = courseOptions.value[0]?.id
  router.push({
    name: isAdmin.value ? 'admin-class-student-detail' : 'class-student-detail',
    params: { classId, studentId: stu.student },
    query: course ? { course } : {},
  })
}

// ---- 移除 ----
const removeVisible = ref(false)
const removeTarget = ref(null)
const removing = ref(false)
function openRemove(row) {
  removeTarget.value = row
  removeVisible.value = true
}
async function confirmRemove() {
  if (!removeTarget.value) return
  removing.value = true
  try {
    await removeClassStudent(removeTarget.value.id)
    ElMessage.success('已移出')
    removeVisible.value = false
    removeTarget.value = null
    await loadStudents()
    await loadClass()
  } finally {
    removing.value = false
  }
}

// ---- 添加学生（搜索候选 + 勾选批量添加） ----
const addVisible = ref(false)
const addKeyword = ref('')
const adding = ref(false)
const searchKeyword = ref('')
const searching = ref(false)
const candidates = ref([])
const selectedIds = ref(new Set())
let searchTimer = null

function onSearchInput(val) {
  searchKeyword.value = (val || '').trim()
  clearTimeout(searchTimer)
  if (!searchKeyword.value) { candidates.value = []; selectedIds.value = new Set(); return }
  searchTimer = setTimeout(doSearch, 300)
}
function clearSearch() {
  searchKeyword.value = ''
  candidates.value = []
  selectedIds.value = new Set()
  clearTimeout(searchTimer)
}
function closeAdd() {
  addVisible.value = false
  addKeyword.value = ''
  clearSearch()
}
async function doSearch() {
  if (!searchKeyword.value) return
  searching.value = true
  try {
    const data = await searchClassStudents(classId, searchKeyword.value)
    candidates.value = data.results ?? data ?? []
    const still = new Set(candidates.value.filter((c) => !c.already_in).map((c) => c.username))
    selectedIds.value = new Set([...selectedIds.value].filter((u) => still.has(u)))
  } finally {
    searching.value = false
  }
}
const checkableCandidates = computed(() => candidates.value.filter((c) => !c.already_in))
const isAllChecked = computed(() =>
  checkableCandidates.value.length > 0 && checkableCandidates.value.every((c) => selectedIds.value.has(c.username)))
const isIndeterminate = computed(() => selectedIds.value.size > 0 && !isAllChecked.value)
function toggleOne(username) {
  const next = new Set(selectedIds.value)
  if (next.has(username)) next.delete(username)
  else next.add(username)
  selectedIds.value = next
}
function toggleAll(checked) {
  const next = new Set(selectedIds.value)
  checkableCandidates.value.forEach((c) => (checked ? next.add(c.username) : next.delete(c.username)))
  selectedIds.value = next
}
async function doBatchAdd() {
  if (!selectedIds.value.size) return
  adding.value = true
  try {
    const usernames = [...selectedIds.value]
    const data = await addStudentsBatch(classId, usernames)
    const incomplete = (data?.data?.incomplete) || []
    if (incomplete.length) ElMessage.warning(data?.message || `已添加，但 ${incomplete.length} 人资料不全`)
    else ElMessage.success(data?.message || `已添加 ${data?.data?.added ?? usernames.length} 人`)
    closeAdd()
    await loadStudents()
    await loadClass()
  } finally {
    adding.value = false
  }
}

function goBack() {
  router.push(isAdmin.value ? '/admin/classes' : '/teacher/classes')
}

onMounted(() => { loadClass(); loadStudents() })
</script>

<style scoped>
.class-students {
  display: flex;
  flex-direction: column;
}

/* ===== 页头 ===== */
.roster-head {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 16px;
  padding: 14px 18px;
  border: 1px solid rgba(37, 99, 235, 0.06);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.06);
}
.roster-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #eff6ff;
  color: #3b82f6;
  font-size: 19px;
}
.roster-heading {
  min-width: 0;
  flex: 1;
}
.roster-title {
  overflow: hidden;
  color: #0f172a;
  font-size: 16px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.roster-subtitle {
  overflow: hidden;
  margin-top: 2px;
  color: #94a3b8;
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.roster-count {
  flex-shrink: 0;
  color: #64748b;
  font-size: 13px;
  white-space: nowrap;
}

/* ===== 工具栏 ===== */
.roster-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 12px 16px;
  border: 1px solid #e5edf8;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
}
.roster-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.roster-search {
  width: min(320px, 40vw);
}
.roster-filter {
  width: 120px;
}
.roster-sort {
  width: 190px;
}

/* ===== 表格 ===== */
.roster-table {
  width: 100%;
}
/* 窄列 nowrap + 悬停 title（项目表格口径） */
.roster-table :deep(.cell) {
  white-space: nowrap;
}
.stu-cell {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
/* 姓名/学号区域整块可点进详情 */
.stu-cell-link {
  cursor: pointer;
}
.stu-cell-link:hover .stu-name {
  color: var(--primary-600);
}
.stu-link-ico {
  flex-shrink: 0;
  margin-left: auto;
  color: #cbd5e1;
  font-size: 13px;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease;
}
.stu-cell-link:hover .stu-link-ico {
  color: var(--primary-500);
  opacity: 1;
}
.stu-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
}
.stu-avatar-sm {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  font-size: 12.5px;
  font-weight: 700;
}
.stu-cell-text {
  display: grid;
  gap: 1px;
  min-width: 0;
}
.stu-name {
  overflow: hidden;
  color: #1e293b;
  font-size: 13.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stu-username {
  overflow: hidden;
  color: #94a3b8;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.roster-pager {
  justify-content: flex-end;
  margin-top: 14px;
}

/* ===== 添加学生弹窗 ===== */
.add-bar {
  margin-bottom: 14px;
}
.cand-panel {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
  overflow: hidden;
}
.cand-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
}
.cand-hint {
  flex: 1;
  color: #94a3b8;
  font-size: 12px;
}
.cand-list {
  max-height: 340px;
  overflow-y: auto;
}
.cand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.cand-row:last-child {
  border-bottom: none;
}
.cand-row.in-class {
  background: #f1f5f9;
  opacity: 0.7;
}
.cand-row.no-profile {
  background: #fffbeb;
}
.cand-row.no-profile .cand-name {
  color: #b45309;
}
.cand-no {
  min-width: 96px;
  color: #475569;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
}
.cand-name {
  flex: 1;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
}
.cand-cls {
  color: #64748b;
  font-size: 12px;
}
.cand-cls.empty {
  color: #cbd5e1;
}
.cand-list::-webkit-scrollbar {
  width: 5px;
}
.cand-list::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: rgba(37, 99, 235, 0.22);
}

@media (max-width: 900px) {
  .roster-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .roster-toolbar-left {
    flex-direction: column;
    align-items: stretch;
  }
  .roster-search,
  .roster-filter,
  .roster-sort {
    width: 100%;
  }
  .roster-count {
    display: none;
  }
}
</style>
