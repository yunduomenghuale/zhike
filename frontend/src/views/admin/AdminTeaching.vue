<template>
  <div class="page-container admin-teaching">
    <header class="page-head">
      <div><div class="eyebrow">TEACHING GOVERNANCE</div><h1>教学监管</h1><p>跨教师查看课程、班级及其关联规模。</p></div>
      <div class="scope-note"><el-icon><View /></el-icon><span>全平台数据视图</span></div>
    </header>

    <section class="teaching-card">
      <el-tabs v-model="activeTab" class="admin-tabs" @tab-change="switchTab">
        <el-tab-pane name="courses"><template #label><span class="tab-label"><el-icon><Reading /></el-icon>课程监管</span></template></el-tab-pane>
        <el-tab-pane name="classes"><template #label><span class="tab-label"><el-icon><School /></el-icon>班级监管</span></template></el-tab-pane>
      </el-tabs>

      <div class="toolbar">
        <el-input v-model="search" clearable :prefix-icon="Search" :placeholder="activeTab === 'courses' ? '搜索课程或教师' : '搜索班级或教师'" @keyup.enter="applyFilters" @clear="applyFilters" />
        <el-select v-if="activeTab === 'courses'" v-model="statusFilter" clearable placeholder="全部状态" @change="applyFilters">
          <el-option label="启用" value="active" /><el-option label="停用" value="inactive" /><el-option label="归档" value="archived" />
        </el-select>
        <el-select v-else v-model="statusFilter" clearable placeholder="全部状态" @change="applyFilters">
          <el-option label="开课中" value="open" /><el-option label="已结课" value="closed" />
        </el-select>
        <el-button :icon="Search" @click="applyFilters">查询</el-button>
        <span>共 {{ total }} 条</span>
      </div>

      <el-table v-if="activeTab === 'courses'" v-loading="loading" :data="rows" row-key="id">
        <el-table-column label="课程" min-width="250">
          <template #default="{ row }"><div class="entity"><span class="entity-icon course"><el-icon><Reading /></el-icon></span><div><strong>{{ row.name }}</strong><small>{{ row.term || '未设置学期' }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="授课教师" min-width="160"><template #default="{ row }"><strong>{{ row.teacher_name || '未填写姓名' }}</strong><small class="block">@{{ row.teacher_username }}</small></template></el-table-column>
        <el-table-column label="关联班级" width="120" align="center"><template #default="{ row }"><b class="number">{{ row.class_count }}</b> 个</template></el-table-column>
        <el-table-column label="覆盖学生" width="120" align="center"><template #default="{ row }"><b class="number">{{ row.student_count }}</b> 人</template></el-table-column>
        <el-table-column label="课程状态" width="150">
          <template #default="{ row }"><el-select :model-value="row.status" size="small" @change="(value) => changeCourseStatus(row, value)"><el-option label="启用" value="active" /><el-option label="停用" value="inactive" /><el-option label="归档" value="archived" /></el-select></template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="130"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      </el-table>

      <el-table v-else v-loading="loading" :data="rows" row-key="id">
        <el-table-column label="班级" min-width="250"><template #default="{ row }"><div class="entity"><span class="entity-icon class"><el-icon><School /></el-icon></span><div><strong>{{ row.name }}</strong><small>{{ dateRange(row) }}</small></div></div></template></el-table-column>
        <el-table-column label="负责人" min-width="170"><template #default="{ row }"><strong>{{ row.teacher_name || '未填写姓名' }}</strong><small class="block">@{{ row.teacher_username }}</small></template></el-table-column>
        <el-table-column label="关联课程" width="130" align="center"><template #default="{ row }"><b class="number">{{ row.course_count }}</b> 门</template></el-table-column>
        <el-table-column label="班级学生" width="130" align="center"><template #default="{ row }"><b class="number">{{ row.student_count }}</b> 人</template></el-table-column>
        <el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="row.status === 'open' ? 'success' : 'info'" effect="light">{{ row.status_display }}</el-tag></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" class="pager" background layout="prev, pager, next, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="changePage" />
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Reading, School, Search, View } from '@element-plus/icons-vue'
import { listAdminClasses, listAdminCourses, updateAdminCourseStatus } from '@/api/admin'

const activeTab = ref('courses'), search = ref(''), statusFilter = ref('')
const loading = ref(false), rows = ref([]), total = ref(0), page = ref(1), pageSize = 10
function formatDate(value) { return value ? new Date(value).toLocaleDateString('zh-CN') : '—' }
function dateRange(row) { return `${row.start_at || '未设置'} 至 ${row.end_at || '未设置'}` }
function applyFilters() { page.value = 1; load() }
function switchTab() { search.value = ''; statusFilter.value = ''; page.value = 1; load() }
function changePage(value) { page.value = value; load() }
async function load() {
  loading.value = true
  try {
    const params = { search: search.value, status: statusFilter.value, page: page.value, page_size: pageSize }
    const res = activeTab.value === 'courses' ? await listAdminCourses(params) : await listAdminClasses(params)
    rows.value = res.items; total.value = res.total
  } finally { loading.value = false }
}
async function changeCourseStatus(row, value) {
  const previous = row.status
  row.status = value
  try { const updated = await updateAdminCourseStatus(row.id, value); Object.assign(row, updated); ElMessage.success('课程状态已更新') } catch { row.status = previous }
}
onMounted(load)
</script>

<style scoped>
.admin-teaching{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}.scope-note{height:40px;padding:0 14px;border:1px solid #dbeafe;border-radius:20px;background:#eff6ff;color:#2563eb;display:flex;align-items:center;gap:7px;font-weight:700;font-size:13px}
.teaching-card{overflow:hidden;border:1px solid #e5edf8;border-radius:22px;background:#fff;box-shadow:0 18px 42px rgba(37,99,235,.07)}.admin-tabs{padding:0 20px}.admin-tabs :deep(.el-tabs__header){margin:0}.admin-tabs :deep(.el-tabs__content){display:none}.tab-label{height:58px;display:flex;align-items:center;gap:7px;font-weight:750}
.toolbar{min-height:66px;margin:0 -20px;padding:12px 20px;border-bottom:1px solid #edf2f7;background:#fbfdff;display:flex;align-items:center;gap:10px}.toolbar :deep(.el-input){width:min(380px,38vw)}.toolbar :deep(.el-select){width:140px}.toolbar>span{margin-left:auto;color:#94a3b8;font-size:13px}
.entity{display:flex;align-items:center;gap:12px}.entity>div{min-width:0;display:grid;gap:4px}.entity strong,.entity small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.entity small,.block{color:#94a3b8;font-size:12px}.block{display:block;margin-top:4px}.entity-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;flex:0 0 auto;font-size:19px}.entity-icon.course{color:#2563eb;background:#eff6ff}.entity-icon.class{color:#10b981;background:#ecfdf5}.number{color:#2563eb;font-size:18px}.pager{justify-content:flex-end;padding:16px 18px;border-top:1px solid #eef2f7}
@media(max-width:720px){.page-head{align-items:flex-start;flex-direction:column}.toolbar{align-items:stretch;flex-wrap:wrap}.toolbar :deep(.el-input){width:100%}.toolbar>span{width:100%;margin-left:0}}
</style>
