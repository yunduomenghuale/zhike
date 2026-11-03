<template>
  <!-- 管理端全局队列看板：通知铃铛「任务」页签内的弹窗（仅平台管理员可见）。
       图标统计卡 + 活跃/完成/失败三页任务明细（用户·课程·章节·类型·内容量）。 -->
  <span class="queue-board-entry">
    <el-button size="small" text type="primary" @click="open">全局队列看板</el-button>

    <el-dialog
      v-model="visible"
      width="920px"
      class="queue-board-dialog"
      :show-close="true"
      append-to-body
      @open="refresh"
    >
      <template #header>
        <div class="qb-header">
          <div class="qb-title">
            <span class="qb-title-text">AI 队列看板</span>
            <span class="qb-title-sub">全局任务运行视图</span>
          </div>
          <div class="qb-header-right">
            <span v-if="health" class="qb-worker">
              <span class="qb-dot" :class="{ idle: !health.worker_heartbeat_seconds_ago }"></span>
              {{ heartbeatAgo }}<template v-if="health.render_slot_mode"> · 渲染 {{ health.render_slot_mode }} ×{{ health.ai_render_concurrency }}</template>
            </span>
            <el-button size="small" :icon="Refresh" :loading="loading" circle @click="refresh" />
          </div>
        </div>
      </template>

      <div v-loading="loading" class="qb-body">
        <!-- 图标统计卡 -->
        <div class="qb-stats">
          <div class="qb-stat">
            <span class="qb-stat-icon" style="color:#2563eb;background:#eff6ff"><el-icon :size="20"><Clock /></el-icon></span>
            <div class="qb-stat-main">
              <div class="qb-stat-num">{{ board?.by_status?.pending ?? 0 }}</div>
              <div class="qb-stat-label">排队中</div>
            </div>
          </div>
          <div class="qb-stat">
            <span class="qb-stat-icon" style="color:#10b981;background:#ecfdf5"><el-icon :size="20"><Odometer /></el-icon></span>
            <div class="qb-stat-main">
              <div class="qb-stat-num">{{ board?.by_status?.running ?? 0 }}</div>
              <div class="qb-stat-label">执行中</div>
            </div>
          </div>
          <div class="qb-stat">
            <span class="qb-stat-icon" style="color:#ef4444;background:#fef2f2"><el-icon :size="20"><WarningFilled /></el-icon></span>
            <div class="qb-stat-main">
              <div class="qb-stat-num">{{ board?.by_status?.failed ?? 0 }}</div>
              <div class="qb-stat-label">失败待处理</div>
            </div>
          </div>
          <div class="qb-stat">
            <span class="qb-stat-icon" style="color:#8b5cf6;background:#f5f3ff"><el-icon :size="20"><Timer /></el-icon></span>
            <div class="qb-stat-main">
              <div class="qb-stat-num">{{ fmtWait(board?.avg_wait_seconds_24h) }}</div>
              <div class="qb-stat-label">近 24h 平均排队</div>
            </div>
          </div>
        </div>

        <el-tabs v-model="tab" class="qb-tabs">
          <el-tab-pane :label="`活跃任务 ${board?.active_tasks?.length ?? 0}`" name="active">
            <div v-if="!board?.active_tasks?.length" class="qb-empty">
              <el-empty description="当前无排队或执行中的任务" :image-size="90" />
            </div>
            <div v-for="t in board?.active_tasks || []" :key="t.id" class="qb-task">
              <div class="qb-task-row">
                <span class="qb-type-tag" :style="typeStyle(t.task_type)">{{ TYPE_LABEL[t.task_type] || t.task_type }}</span>
                <el-tag size="small" :type="statusTag(t.status)" effect="light" round>
                  {{ statusLabel(t) }}
                </el-tag>
                <span class="qb-task-id">#{{ t.id }}</span>
                <span v-if="t.attempts > 1" class="qb-attempts" :title="`第 ${t.attempts} 次尝试`">↻{{ t.attempts }}</span>
                <span class="qb-grow"></span>
                <span class="qb-time" :title="'提交于 ' + fmtTime(t.created_at)">{{ fmtTime(t.created_at) }}</span>
              </div>
              <div class="qb-task-row qb-task-meta">
                <span class="qb-meta-item"><el-icon :size="13"><User /></el-icon>{{ displayUser(t) }}</span>
                <span class="qb-meta-item qb-course" :title="courseTitle(t)"><el-icon :size="13"><Reading /></el-icon>{{ courseTitle(t) }}</span>
                <span class="qb-meta-item"><el-icon :size="13"><Document /></el-icon>{{ contentVolume(t) }}</span>
              </div>
              <div v-if="t.status === 'running' && t.progress?.total" class="qb-task-progress">
                <el-progress :percentage="pct(t)" :stroke-width="6" :show-text="false" />
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`最近完成 ${board?.recent_success?.length ?? 0}`" name="success">
            <div v-if="!board?.recent_success?.length" class="qb-empty">
              <el-empty description="暂无完成记录" :image-size="90" />
            </div>
            <div v-for="t in board?.recent_success || []" :key="t.id" class="qb-task">
              <div class="qb-task-row">
                <span class="qb-type-tag" :style="typeStyle(t.task_type)">{{ TYPE_LABEL[t.task_type] || t.task_type }}</span>
                <el-tag size="small" type="success" effect="light" round>已完成</el-tag>
                <span class="qb-task-id">#{{ t.id }}</span>
                <span class="qb-grow"></span>
                <span class="qb-time">{{ durationText(t) }}</span>
              </div>
              <div class="qb-task-row qb-task-meta">
                <span class="qb-meta-item"><el-icon :size="13"><User /></el-icon>{{ displayUser(t) }}</span>
                <span class="qb-meta-item qb-course" :title="courseTitle(t)"><el-icon :size="13"><Reading /></el-icon>{{ courseTitle(t) }}</span>
                <span class="qb-meta-item"><el-icon :size="13"><Document /></el-icon>{{ contentVolume(t) }}</span>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`失败记录 ${board?.recent_failed?.length ?? 0}`" name="failed">
            <div v-if="!board?.recent_failed?.length" class="qb-empty">
              <el-empty description="暂无失败任务" :image-size="90" />
            </div>
            <div v-for="t in board?.recent_failed || []" :key="t.id" class="qb-task">
              <div class="qb-task-row">
                <span class="qb-type-tag" :style="typeStyle(t.task_type)">{{ TYPE_LABEL[t.task_type] || t.task_type }}</span>
                <el-tag size="small" type="danger" effect="light" round>失败</el-tag>
                <span class="qb-task-id">#{{ t.id }}</span>
                <span v-if="t.attempts > 1" class="qb-attempts">↻{{ t.attempts }}</span>
                <span class="qb-grow"></span>
                <span class="qb-time">{{ fmtTime(t.finished_at || t.created_at) }}</span>
              </div>
              <div class="qb-task-row qb-task-meta">
                <span class="qb-meta-item"><el-icon :size="13"><User /></el-icon>{{ displayUser(t) }}</span>
                <span class="qb-meta-item qb-course" :title="courseTitle(t)"><el-icon :size="13"><Reading /></el-icon>{{ courseTitle(t) }}</span>
                <span class="qb-meta-item"><el-icon :size="13"><Document /></el-icon>{{ contentVolume(t) }}</span>
              </div>
              <div v-if="t.error" class="qb-error" :title="t.error">{{ t.error }}</div>
            </div>
          </el-tab-pane>
        </el-tabs>

        <div v-if="board?.top_errors?.length" class="qb-top-errors">
          <span class="qb-top-errors-label">失败原因 Top{{ board.top_errors.length }}：</span>
          <span v-for="(e, i) in board.top_errors" :key="i" class="qb-top-error-chip" :title="e.error">
            {{ e.error.slice(0, 32) }}{{ e.error.length > 32 ? '…' : '' }} ×{{ e.count }}
          </span>
        </div>
      </div>
    </el-dialog>
  </span>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Clock, Odometer, WarningFilled, Timer, Refresh, User, Reading, Document } from '@element-plus/icons-vue'
import { getQueueBoard, getWorkerHealth } from '@/api/ai-task'

const visible = ref(false)
const loading = ref(false)
const board = ref(null)
const health = ref(null)
const tab = ref('active')

const TYPE_LABEL = {
  script_gen: '讲稿', audio_gen: '配音', question_gen: 'AI 生题', chapter_summary: '章节总结',
  class_analytics: '学情分析', course_reuse: '课程复用', ppt_parse: '课件解析', embed_ingest: '向量入库',
}
const TYPE_COLOR = {
  script_gen: '#2563eb', audio_gen: '#10b981', question_gen: '#8b5cf6', chapter_summary: '#0ea5e9',
  class_analytics: '#14b8a6', course_reuse: '#f59e0b', ppt_parse: '#ef4444', embed_ingest: '#64748b',
}

const heartbeatAgo = computed(() => {
  const s = health.value?.worker_heartbeat_seconds_ago
  if (s == null) return 'worker 空闲'
  if (s < 60) return `心跳 ${Math.round(s)} 秒前`
  return `心跳 ${Math.round(s / 60)} 分钟前`
})

function typeStyle(t) {
  const c = TYPE_COLOR[t] || '#64748b'
  return { color: c, background: c + '14' }
}
function statusLabel(t) {
  if (t.status === 'pending') return t.queue_position ? `排队第 ${t.queue_position} 位` : '排队中'
  return '执行中'
}
function statusTag(s) {
  return s === 'running' ? 'primary' : 'warning'
}
function displayUser(t) {
  if (!t.user) return '系统/学生触发'
  return t.user.real_name ? `${t.user.real_name}（${t.user.username}）` : t.user.username
}
function courseTitle(t) {
  const parts = []
  if (t.course?.name) parts.push(t.course.name)
  if (t.catalog?.title) parts.push(t.catalog.title)
  return parts.length ? parts.join(' › ') : '—'
}
function contentVolume(t) {
  const p = t.progress || {}
  if (p.total) {
    const unit = t.task_type === 'audio_gen' || t.task_type === 'script_gen' ? ' 页' : ''
    const done = p.done != null ? `${p.done}/` : ''
    return `内容量 ${done}${p.total}${unit}`
  }
  return '内容量 —'
}
function pct(t) {
  const p = t.progress || {}
  if (!p.total) return 0
  return Math.min(100, Math.round(((p.done || 0) / p.total) * 100))
}
function fmtWait(sec) {
  if (sec == null) return '—'
  return sec < 60 ? `${Math.round(sec)}s` : `${(sec / 60).toFixed(1)}min`
}
function fmtTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function durationText(t) {
  if (t.started_at && t.finished_at) {
    const s = (new Date(t.finished_at) - new Date(t.started_at)) / 1000
    return `耗时 ${s < 60 ? Math.round(s) + 's' : (s / 60).toFixed(1) + 'min'}`
  }
  return fmtTime(t.finished_at)
}

async function refresh() {
  loading.value = true
  try {
    const [b, h] = await Promise.allSettled([getQueueBoard(), getWorkerHealth()])
    if (b.status === 'fulfilled') board.value = b.value?.data ?? b.value
    if (h.status === 'fulfilled') health.value = h.value?.data ?? h.value
  } finally {
    loading.value = false
  }
}
function open() {
  visible.value = true
}
</script>

<style scoped>
.queue-board-entry {
  display: inline-flex;
}
.qb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 28px;
}
.qb-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.qb-title-text {
  font-size: 17px;
  font-weight: 750;
  color: var(--el-text-color-primary);
}
.qb-title-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.qb-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.qb-worker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.qb-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-success);
}
.qb-dot.idle {
  background: var(--el-color-info);
}
.qb-body {
  min-height: 320px;
}
.qb-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 6px;
}
.qb-stat {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--el-bg-color);
}
.qb-stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 10px;
  flex-shrink: 0;
}
.qb-stat-num {
  font-size: 22px;
  font-weight: 750;
  line-height: 1.1;
  color: var(--el-text-color-primary);
}
.qb-stat-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.qb-tabs :deep(.el-tabs__item) {
  font-weight: 600;
}
.qb-empty {
  padding: 24px 0;
}
.qb-task {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
}
.qb-task-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.qb-type-tag {
  font-size: 12px;
  font-weight: 650;
  border-radius: 6px;
  padding: 2px 8px;
}
.qb-task-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.qb-attempts {
  font-size: 12px;
  color: var(--el-color-warning);
}
.qb-grow {
  flex: 1;
}
.qb-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.qb-task-meta {
  margin-top: 6px;
  flex-wrap: wrap;
}
.qb-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.qb-course {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qb-task-progress {
  margin-top: 8px;
}
.qb-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qb-top-errors {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qb-top-errors-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.qb-top-error-chip {
  font-size: 12px;
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-radius: 6px;
  padding: 2px 8px;
}
</style>
<style>
.queue-board-dialog {
  border-radius: 14px;
}
</style>
