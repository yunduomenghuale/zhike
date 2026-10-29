<template>
  <el-drawer
    :model-value="modelValue" size="min(880px, 94vw)" :show-close="false"
    class="course-drawer" @close="$emit('update:modelValue', false)"
  >
    <template #header>
      <div class="drawer-head">
        <div class="drawer-title">
          <span class="entity-icon course"><el-icon><Reading /></el-icon></span>
          <div>
            <strong>{{ detail?.name || '课程详情' }}</strong>
            <small v-if="detail">{{ detail.term || '未设置学期' }} · {{ detail.teacher?.real_name || detail.teacher?.username || '未知教师' }}</small>
          </div>
        </div>
        <div class="drawer-head-actions">
          <el-tag v-if="detail" size="small" effect="light" :type="statusType(detail.status)">{{ detail.status_display }}</el-tag>
          <button class="drawer-close" type="button" title="关闭" @click="$emit('update:modelValue', false)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <el-alert v-if="loadError" type="error" show-icon :closable="false" :title="loadError" />

      <template v-if="detail">
        <section class="stat-grid">
          <div v-for="item in statCards" :key="item.label" class="stat-card" :class="{ warn: item.warn }">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </section>

        <section class="block">
          <h3>章节结构</h3>
          <div v-if="!treeRows.length" class="empty">该课程尚未创建章节</div>
          <div v-else class="tree">
            <div v-for="row in treeRows" :key="row.id" class="tree-row" :class="{ child: row.depth > 0 }">
              <span class="tree-title">{{ row.title }}</span>
              <span v-if="!row.is_published" class="tree-flag draft">未发布</span>
              <span class="tree-meta">
                <el-tag v-if="row.ppt_status === 'failed'" size="small" type="danger" effect="plain">课件解析失败</el-tag>
                <el-tag v-else-if="row.ppt_status" size="small" effect="plain" :type="row.ppt_status === 'done' ? 'success' : 'warning'">
                  课件{{ row.ppt_pages }}页 · {{ row.ppt_status_display || pptStatusText(row.ppt_status) }}
                </el-tag>
                <el-tag v-if="row.video_status" size="small" effect="plain" :type="videoTagType(row)">
                  视频{{ row.video_status_display || videoStatusText(row.video_status) }}{{ row.video_published ? ' · 已发布' : '' }}
                </el-tag>
                <el-tag v-if="row.question_count" size="small" effect="plain">{{ row.question_count }} 题</el-tag>
              </span>
            </div>
          </div>
        </section>

        <section class="block">
          <h3>作业发布与提交 <small v-if="detail.homeworks?.length">共 {{ detail.homeworks.length }} 份</small></h3>
          <div v-if="!detail.homeworks?.length" class="empty">暂无作业</div>
          <el-table v-else :data="detail.homeworks" size="small" max-height="260">
            <el-table-column label="作业" min-width="210" class-name="name-cell">
              <template #default="{ row }">
                <strong>{{ row.title }}</strong>
                <small class="block">{{ row.class_name }}</small>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" effect="light" :type="homeworkStatusType(row.status)">{{ row.status_display }}</el-tag></template>
            </el-table-column>
            <el-table-column label="截止时间" width="170">
              <template #default="{ row }">
                <span :class="{ muted: !row.deadline }">{{ deadlineText(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="提交进度" width="170" class-name="progress-cell">
              <template #default="{ row }">
                <span class="rate" :class="rateTone(row.submitted, row.total)">
                  {{ row.submitted }}/{{ row.total }}
                  <small v-if="row.pending_grading">（{{ row.pending_grading }} 份待批改）</small>
                </span>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="block">
          <h3>考试与成绩 <small v-if="detail.exams?.length">共 {{ detail.exams.length }} 场</small></h3>
          <div v-if="!detail.exams?.length" class="empty">暂无考试</div>
          <el-table v-else :data="detail.exams" size="small" max-height="260">
            <el-table-column label="考试" min-width="210" class-name="name-cell">
              <template #default="{ row }">
                <strong>{{ row.name }}</strong>
                <small class="block">{{ row.class_name }}</small>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" effect="light" :type="examStatusType(row.status)">{{ row.status_display }}</el-tag></template>
            </el-table-column>
            <el-table-column label="考试时间" width="215">
              <template #default="{ row }">
                <span class="window-text">{{ examWindowText(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="交卷进度" width="170" class-name="progress-cell">
              <template #default="{ row }">
                <span class="rate" :class="rateTone(row.taken, row.total)">
                  {{ row.taken }}/{{ row.total }}
                  <small v-if="row.unreleased">（{{ row.unreleased }} 人未发布成绩）</small>
                </span>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="block">
          <h3>关联班级进度</h3>
          <div v-if="!detail.classes?.length" class="empty">该课程尚未关联班级</div>
          <el-table v-else :data="detail.classes" size="small">
            <el-table-column label="班级" min-width="150" class-name="name-cell">
              <template #default="{ row }">
                <el-link type="primary" :underline="false" @click="$emit('open-class', row.id)">{{ row.name }}</el-link>
                <small class="block">{{ row.teacher_name }}</small>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="95">
              <template #default="{ row }"><el-tag size="small" effect="light" :type="classStatusMeta(row.status).type">{{ classStatusMeta(row.status).label }}</el-tag></template>
            </el-table-column>
            <el-table-column label="学生" width="85" align="center">
              <template #default="{ row }">{{ row.student_count }}</template>
            </el-table-column>
            <el-table-column label="作业提交率" width="125" align="center">
              <template #default="{ row }"><span class="rate" :class="rateTone(row.homework_rate, 100)">{{ row.homework_rate === null ? '—' : row.homework_rate + '%' }}</span></template>
            </el-table-column>
            <el-table-column label="考试完成率" width="125" align="center">
              <template #default="{ row }"><span class="rate" :class="rateTone(row.exam_rate, 100)">{{ row.exam_rate === null ? '—' : row.exam_rate + '%' }}</span></template>
            </el-table-column>
            <el-table-column label="预警人数" width="105" align="center">
              <template #default="{ row }">
                <span v-if="row.warning_count" class="warn-count">{{ row.warning_count }}</span>
                <span v-else class="rate ok">0</span>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Close, Reading } from '@element-plus/icons-vue'
import { getAdminCourseDetail } from '@/api/admin'
import { classStatusMeta } from '@/utils/classStatus'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courseId: { type: [Number, String], default: null },
})
defineEmits(['update:modelValue', 'open-class'])

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)

// 章节树扁平化为带层级的行列表（根 + 一级子章节，模板不再重复两套 markup）
const treeRows = computed(() => {
  const out = []
  const walk = (nodes, depth) => {
    for (const n of nodes || []) {
      out.push({ ...n, depth })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(detail.value?.catalog_tree, 0)
  return out
})

const statCards = computed(() => {
  const s = detail.value?.stats || {}
  return [
    { label: '章节', value: s.catalogs ?? '—' },
    { label: '课件', value: s.ppts ?? '—' },
    { label: '视频', value: s.videos ?? '—' },
    { label: '题库题目', value: s.questions ?? '—' },
    { label: '作业', value: `${s.homework_active ?? 0}/${s.homework_total ?? 0}` },
    { label: '考试', value: `${s.exam_active ?? 0}/${s.exam_total ?? 0}` },
    { label: '解析失败课件', value: s.ppt_failed ?? 0, warn: (s.ppt_failed ?? 0) > 0 },
  ]
})

function statusType(status) { return status === 'active' ? 'success' : status === 'archived' ? 'info' : 'warning' }
function homeworkStatusType(status) { return status === 'published' ? 'success' : status === 'closed' ? 'info' : 'warning' }
function examStatusType(status) {
  return { published: 'success', finished: 'info', draft: 'warning', ongoing: 'danger' }[status] || 'info'
}
// 状态文案兜底映射（后端已返回 display 字段，这里是兼容旧数据的保护）
function pptStatusText(status) {
  return { pending: '待解析', parsing: '解析中', done: '已解析', failed: '解析失败' }[status] || status
}
function videoStatusText(status) {
  return {
    draft: '草稿', script_ready: '讲解稿就绪', audio_ready: '配音就绪',
    composing: '合成中', done: '已合成', failed: '生成失败',
  }[status] || status
}
function videoTagType(row) {
  if (row.video_status === 'failed') return 'danger'
  if (row.video_status === 'done') return 'success'
  return 'warning'
}
function rateTone(part, total) {
  if (!part || !total) return 'none'
  const ratio = part / total
  return ratio >= 0.8 ? 'ok' : ratio >= 0.5 ? 'mid' : 'low'
}
function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
// 作业截止：空 = 不限制截止时间（与教师端发布语义一致）
function deadlineText(row) {
  return row.deadline ? formatDateTime(row.deadline) : '不限制截止时间'
}
// 考试窗口：开始空 = 此刻起可考，结束空 = 不限制截止（见 exams/views 鉴权逻辑）
function examWindowText(row) {
  const start = row.start_at ? formatDateTime(row.start_at) : '此刻开始'
  const end = row.end_at ? formatDateTime(row.end_at) : '不限制截止'
  return `${start} 至 ${end}`
}

watch(
  () => [props.modelValue, props.courseId],
  async (visible) => {
    if (!visible[0] || !props.courseId) return
    loading.value = true
    loadError.value = ''
    detail.value = null
    try {
      detail.value = await getAdminCourseDetail(props.courseId)
    } catch {
      loadError.value = '课程详情加载失败，请稍后重试。'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.drawer-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; }
.drawer-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.drawer-title > div { display: grid; gap: 4px; min-width: 0; }
.drawer-title strong { color: #0f172a; font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.drawer-title small { color: #94a3b8; font-size: 12px; }
.drawer-head-actions { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.entity-icon { width: 42px; height: 42px; border-radius: 13px; display: grid; place-items: center; flex: 0 0 auto; font-size: 19px; }
.entity-icon.course { color: #2563eb; background: #eff6ff; }
.drawer-close {
  width: 34px; height: 34px; border: 1px solid #e5edf8; border-radius: 10px;
  background: #fff; color: #64748b; cursor: pointer; display: grid; place-items: center; font-size: 16px;
}
.drawer-close:hover { color: #2563eb; border-color: #bfdbfe; background: #f8fbff; }
.drawer-body { color: #0f172a; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin-bottom: 22px; }
.stat-card { padding: 14px 16px; border: 1px solid #e5edf8; border-radius: 14px; background: #fff; display: grid; gap: 6px; }
.stat-card span { color: #718096; font-size: 12px; font-weight: 700; }
.stat-card strong { font-size: 20px; line-height: 1; }
.stat-card.warn { border-color: #fecaca; background: #fef2f2; }
.stat-card.warn span { color: #b91c1c; }
.stat-card.warn strong { color: #dc2626; }
.block { margin-bottom: 26px; }
.block h3 { margin: 0 0 12px; font-size: 15px; display: flex; align-items: baseline; gap: 8px; }
.block h3 small { color: #94a3b8; font-size: 12px; font-weight: 500; }
.empty { padding: 26px 0; text-align: center; color: #94a3b8; font-size: 13px; border: 1px dashed #e2e8f0; border-radius: 14px; }
.tree { display: grid; gap: 8px; }
.tree-row { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: 1px solid #eef2f7; border-radius: 12px; background: #fff; flex-wrap: wrap; }
.tree-row.child { background: #f8fafc; }
.tree-title { font-weight: 650; font-size: 13.5px; }
.tree-flag { font-size: 11px; padding: 1px 7px; border-radius: 999px; }
.tree-flag.draft { color: #b45309; background: #fef3c7; }
.tree-meta { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.rate { font-weight: 700; }
.rate small { font-weight: 500; color: #94a3b8; }
.rate.ok { color: #059669; }
.rate.mid { color: #d97706; }
.rate.low { color: #dc2626; }
.rate.none { color: #94a3b8; font-weight: 500; }
.warn-count { color: #dc2626; font-weight: 800; }
.muted { color: #94a3b8; }
.window-text { color: #475569; }
.block :deep(.el-table__cell) { padding: 7px 0; }
</style>

<style>
/* 抽屉内名称列允许换行（EP 默认 nowrap+省略号会把标题裁断）；drawer 样式无法被 scoped 覆盖，走全局 */
.course-drawer.el-drawer { border-radius: 22px 0 0 22px; overflow: hidden; }
.course-drawer .el-drawer__header { margin: 0; padding: 18px 22px; border-bottom: 1px solid #edf2f7; color: #0f172a; }
.course-drawer .el-drawer__body { padding: 20px 22px 28px; }
/* name-cell 次级行 class="block" 与 scoped 段落容器 .block{margin-bottom:26px} 撞名会撑高行，
   显式 margin 复位；flex 列布局消除模板空白文本节点的匿名行盒 */
.course-drawer .name-cell .cell { white-space: normal; word-break: break-all; display: flex; flex-direction: column; align-items: flex-start; }
.course-drawer .name-cell .block { display: block; margin: 3px 0 0; color: #94a3b8; font-size: 12px; font-weight: 400; }
.course-drawer .progress-cell .cell { white-space: normal; }
</style>
