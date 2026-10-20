<template>
  <div class="page-container admin-audit">
    <header class="page-head">
      <div>
        <div class="eyebrow">AUDIT TRAIL</div>
        <h1>操作审计</h1>
        <p>管理端全部干预动作留痕：谁、在什么时间、对什么对象、做了什么变更。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Download" :loading="exporting" @click="exportCsv">导出 CSV</el-button>
      </div>
    </header>

    <section class="audit-card">
      <div class="toolbar">
        <el-select v-model="actionFilter" clearable placeholder="全部动作" class="filter-select" @change="applyFilters">
          <el-option v-for="item in actionOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索对象名称或操作人" class="filter-input" @keyup.enter="applyFilters" @clear="applyFilters" />
        <el-date-picker
          v-model="dateRange" type="daterange" size="default" range-separator="至"
          start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD"
          :shortcuts="dateShortcuts" @change="applyFilters"
        />
        <el-button :icon="Search" @click="applyFilters">查询</el-button>
        <span>共 {{ total }} 条</span>
      </div>

      <el-table v-loading="loading" :data="rows" row-key="id" scrollbar-always-on>
        <el-table-column label="时间" width="140">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作人" width="80">
          <template #default="{ row }">{{ row.actor_name }}</template>
        </el-table-column>
        <el-table-column label="动作" width="112">
          <template #default="{ row }"><el-tag size="small" effect="light" :type="actionType(row.action)">{{ row.action_display }}</el-tag></template>
        </el-table-column>
        <el-table-column label="对象" min-width="136">
          <template #default="{ row }">
            <span class="target-type">{{ targetTypeText(row.target_type) }}</span>
            <strong :title="row.target_label">{{ row.target_label || '—' }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="变更内容" min-width="200">
          <template #default="{ row }">
            <div v-if="changeList(row).length" class="change-list">
              <span v-for="c in changeList(row)" :key="c" class="change-item">{{ c }}</span>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="112" show-overflow-tooltip>
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" class="pager" background layout="prev, pager, next, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="changePage" />
      <div v-if="!loading && !rows.length" class="empty">暂无审计记录</div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { exportAdminActionLogs, listAdminActionLogs } from '@/api/admin'

const actionOptions = [
  { value: 'course_status', label: '课程状态变更' },
  { value: 'class_status', label: '班级状态变更' },
  { value: 'user_create', label: '创建账号' },
  { value: 'user_update', label: '编辑账号' },
  { value: 'user_reset_pwd', label: '重置密码' },
  { value: 'user_import', label: '批量导入账号' },
  { value: 'ai_config_save', label: '保存AI配置' },
  { value: 'ai_config_test', label: 'AI连接测试' },
  { value: 'vector_rebuild', label: '重建向量库' },
]

const actionFilter = ref(''), keyword = ref(''), dateRange = ref(null)
const loading = ref(false), exporting = ref(false)
const rows = ref([]), total = ref(0), page = ref(1), pageSize = 15

const dateShortcuts = [
  { text: '最近 7 天', value: () => {
    const end = new Date(); const start = new Date(); start.setTime(start.getTime() - 3600 * 1000 * 24 * 7)
    return [start, end]
  } },
  { text: '最近 30 天', value: () => {
    const end = new Date(); const start = new Date(); start.setTime(start.getTime() - 3600 * 1000 * 24 * 30)
    return [start, end]
  } },
]

function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function actionType(action) {
  return { user_create: 'success', user_update: 'warning', user_reset_pwd: 'warning', user_import: 'success', ai_config_save: 'info', ai_config_test: 'info', vector_rebuild: 'info' }[action] || 'primary'
}
function targetTypeText(type) {
  return { course: '课程', class: '班级', user: '账号', ai_config: 'AI配置', vector: '向量库' }[type] || type || '—'
}
function changeList(row) {
  // AI 配置保存（单一审计轨）：字段级 diff 按能力分组存 new_value.changes
  if (row.action === 'ai_config_save' && row.new_value && row.new_value.changes) {
    const lines = []
    for (const group of row.new_value.changes) {
      const capability = group.capability_display || group.capability || ''
      for (const c of group.changes || []) {
        lines.push(`${capability}·${c.label}：${c.old || '空'} → ${c.new || '空'}`)
      }
    }
    if (lines.length) return lines
    // 合并前存量行只有 capabilities 列表，退化为「保存能力」一行
    if (row.new_value.capabilities?.length) {
      return [`保存能力：${row.new_value.capabilities.join('、')}`]
    }
    return []
  }
  const { old_value: oldV, new_value: newV } = row
  if (!oldV && !newV) return []
  if (typeof oldV === 'object' && typeof newV === 'object' && oldV && newV) {
    const keys = [...new Set([...Object.keys(oldV), ...Object.keys(newV)])]
    return keys
      .filter((k) => oldV[k] !== newV[k])
      .map((k) => `${k}：${oldV[k] ?? '空'} → ${newV[k] ?? '空'}`)
  }
  return [`${oldV ?? '空'} → ${newV ?? '空'}`]
}

function buildParams() {
  const params = { page: page.value, page_size: pageSize }
  if (actionFilter.value) params.action = actionFilter.value
  if (keyword.value.trim()) params.keyword = keyword.value.trim()
  if (dateRange.value?.length === 2) {
    params.start = dateRange.value[0]
    params.end = dateRange.value[1]
  }
  return params
}

function applyFilters() { page.value = 1; load() }
function changePage(value) { page.value = value; load() }

async function load() {
  loading.value = true
  try {
    const res = await listAdminActionLogs(buildParams())
    rows.value = res.items || []
    total.value = res.total || 0
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const params = buildParams()
    delete params.page
    delete params.page_size
    const blob = await exportAdminActionLogs(params)
    if (blob?.type && blob.type.includes('application/json')) {
      const text = await blob.text()
      let message = '导出失败'
      try { message = JSON.parse(text).message || message } catch { /* 保留默认文案 */ }
      ElMessage.error(message)
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `admin_action_logs_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载（单次上限 5 万行）')
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.admin-audit { color: #0f172a; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.eyebrow { margin-bottom: 6px; color: #2563eb; font-size: 12px; font-weight: 850; letter-spacing: .16em; }
h1, p { margin: 0; } h1 { font-size: 30px; line-height: 1.2; } .page-head p { margin-top: 7px; color: #8190a8; }
.head-actions { display: flex; gap: 10px; }
.audit-card { overflow: hidden; border: 1px solid #e5edf8; border-radius: 22px; background: #fff; box-shadow: 0 18px 42px rgba(37, 99, 235, .07); }
/* 审计行无点击动作，关掉行悬停高亮（否则用户会误以为"选中了整行"） */
.audit-card :deep(.el-table) { --el-table-row-hover-bg-color: transparent; }
.toolbar { min-height: 66px; padding: 12px 20px; border-bottom: 1px solid #edf2f7; background: #fbfdff; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.toolbar .filter-select { width: 160px; }
.toolbar .filter-input { width: min(300px, 30vw); }
.toolbar > span { margin-left: auto; color: #94a3b8; font-size: 13px; }
.target-type { display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 999px; background: #eff6ff; color: #2563eb; font-size: 11px; font-weight: 700; }
.target-type + strong { font-size: 13px; }
.change-list { display: flex; flex-wrap: wrap; gap: 5px; }
/* 长无空格内容（如接口地址 URL）必须能任意断行且收缩到列宽内：
   overflow-wrap:anywhere 会影响 min-content（break-word 不会），flex 项才能真正收缩不溢出单元格 */
.change-item { max-width: 100%; overflow-wrap: anywhere; padding: 2px 9px; border-radius: 8px; background: #f8fafc; border: 1px solid #eef2f7; color: #475569; font-size: 12px; }
.muted { color: #cbd5e1; }
.pager { justify-content: flex-end; padding: 16px 18px; border-top: 1px solid #eef2f7; }
.empty { padding: 40px 0; text-align: center; color: #94a3b8; font-size: 13px; }
@media (max-width: 720px) {
  .page-head { align-items: flex-start; flex-direction: column; }
  .toolbar .filter-input { width: 100%; }
  .toolbar > span { width: 100%; margin-left: 0; }
}
</style>
