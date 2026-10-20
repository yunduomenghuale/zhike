<template>
  <el-drawer
    :model-value="modelValue" size="min(1040px, 96vw)" :show-close="false"
    class="class-drawer" @close="$emit('update:modelValue', false)"
  >
    <template #header>
      <div class="drawer-head">
        <div class="drawer-title">
          <span class="entity-icon class"><el-icon><School /></el-icon></span>
          <div>
            <strong>{{ detail?.name || '班级详情' }}</strong>
            <small v-if="detail">{{ detail.teacher?.real_name || detail.teacher?.username }} · {{ detail.course_name || '未关联课程' }}</small>
          </div>
        </div>
        <div class="drawer-head-actions">
          <el-tag v-if="detail" size="small" effect="light" :type="detail.status === 'open' ? 'success' : 'info'">{{ detail.status_display }}</el-tag>
          <button class="drawer-close" type="button" title="关闭" @click="$emit('update:modelValue', false)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <el-alert v-if="loadError" type="error" show-icon :closable="false" :title="loadError" />

      <template v-if="detail">
        <section class="summary-grid">
          <div class="summary-card"><span>在读学生</span><strong>{{ detail.summary?.student_count ?? 0 }}</strong></div>
          <div class="summary-card"><span>平均练习正确率</span><strong>{{ detail.summary?.avg_accuracy === null || detail.summary?.avg_accuracy === undefined ? '—' : detail.summary.avg_accuracy + '%' }}</strong></div>
          <div class="summary-card"><span>平均考试得分</span><strong>{{ detail.summary?.avg_exam_score ?? '—' }}</strong></div>
          <div class="summary-card"><span>作业提交率</span><strong :class="rateClass(detail.summary?.homework_rate)">{{ detail.summary?.homework_rate === null || detail.summary?.homework_rate === undefined ? '—' : detail.summary.homework_rate + '%' }}</strong></div>
          <div class="summary-card"><span>实验完成率</span><strong :class="rateClass(detail.summary?.experiment_rate)">{{ detail.summary?.experiment_rate === null || detail.summary?.experiment_rate === undefined ? '—' : detail.summary.experiment_rate + '%' }}</strong></div>
          <div class="summary-card" :class="{ warn: detail.summary?.warning_count > 0 }"><span>预警学生</span><strong>{{ detail.summary?.warning_count ?? 0 }}</strong></div>
        </section>

        <section class="block">
          <h3>逐学生学习进度 <small>口径与教师端学情统计一致</small></h3>
          <div v-if="!detail.students?.length" class="empty">该班级暂无在读学生</div>
          <el-table v-else :data="detail.students" size="small" max-height="460">
            <el-table-column label="学生" min-width="140" class-name="name-cell">
              <template #default="{ row }">
                <strong>{{ row.name }}</strong>
                <small class="block">@{{ row.username }}</small>
              </template>
            </el-table-column>
            <el-table-column label="练习正确率" width="150" align="center">
              <template #default="{ row }">
                <span v-if="row.practice_total" :style="{ color: accColor(row.accuracy), fontWeight: 700 }">{{ row.accuracy === null ? '—' : row.accuracy + '%' }}</span>
                <span v-else class="muted">未练习</span>
                <small v-if="row.practice_total" class="block">{{ row.practice_correct }}/{{ row.practice_total }} 题</small>
              </template>
            </el-table-column>
            <el-table-column label="作业提交" width="100" align="center">
              <template #default="{ row }">
                <span :class="rateClass(row.homework_total ? (row.homework_submitted / row.homework_total) * 100 : null)">{{ row.homework_submitted }}/{{ row.homework_total }}</span>
              </template>
            </el-table-column>
            <el-table-column label="考试参加" width="140" align="center">
              <template #default="{ row }">
                <span :class="rateClass(row.exam_total ? (row.exam_taken / row.exam_total) * 100 : null)">{{ row.exam_taken }}/{{ row.exam_total }}</span>
                <small v-if="row.avg_exam_score !== null" class="block">均分 {{ row.avg_exam_score }}</small>
              </template>
            </el-table-column>
            <el-table-column label="实验完成" width="110" align="center">
              <template #default="{ row }">
                <span :class="rateClass(row.experiment_total ? (row.experiment_done / row.experiment_total) * 100 : null)">{{ row.experiment_done }}/{{ row.experiment_total }}</span>
                <small v-if="row.avg_experiment_score !== null" class="block">均分 {{ row.avg_experiment_score }}</small>
              </template>
            </el-table-column>
            <el-table-column label="最近学习" width="110">
              <template #default="{ row }">{{ fmtRelative(row.last_active) }}</template>
            </el-table-column>
            <el-table-column label="学情预警" min-width="220" class-name="warn-cell">
              <template #default="{ row }">
                <el-tag v-for="w in row.warnings" :key="w" type="danger" size="small" effect="light" round style="margin: 2px 4px 2px 0;">{{ w }}</el-tag>
                <el-tag v-if="!row.warnings.length" type="success" size="small" effect="light" round>正常</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Close, School } from '@element-plus/icons-vue'
import { getAdminClassDetail } from '@/api/admin'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  classId: { type: [Number, String], default: null },
})
defineEmits(['update:modelValue'])

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)

function accColor(acc) {
  if (acc === null || acc === undefined) return '#94a3b8'
  if (acc >= 80) return '#059669'
  if (acc >= 60) return '#d97706'
  return '#dc2626'
}
function rateClass(rate) {
  if (rate === null || rate === undefined) return ''
  if (rate >= 80) return 'rate ok'
  if (rate >= 50) return 'rate mid'
  return 'rate low'
}
function fmtRelative(value) {
  if (!value) return '从未学习'
  const diff = Date.now() - new Date(value).getTime()
  const days = Math.floor(diff / 86400000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 30) return `${days} 天前`
  return `${Math.floor(days / 30)} 个月前`
}

watch(
  () => [props.modelValue, props.classId],
  async ([visible]) => {
    if (!visible || !props.classId) return
    loading.value = true
    loadError.value = ''
    detail.value = null
    try {
      detail.value = await getAdminClassDetail(props.classId)
    } catch {
      loadError.value = '班级详情加载失败，请稍后重试。'
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
.entity-icon.class { color: #10b981; background: #ecfdf5; }
.drawer-close {
  width: 34px; height: 34px; border: 1px solid #e5edf8; border-radius: 10px;
  background: #fff; color: #64748b; cursor: pointer; display: grid; place-items: center; font-size: 16px;
}
.drawer-close:hover { color: #2563eb; border-color: #bfdbfe; background: #f8fbff; }
.drawer-body { color: #0f172a; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 22px; }
.summary-card { padding: 14px 16px; border: 1px solid #e5edf8; border-radius: 14px; background: #fff; display: grid; gap: 6px; }
.summary-card span { color: #718096; font-size: 12px; font-weight: 700; }
.summary-card strong { font-size: 20px; line-height: 1; }
.summary-card.warn { border-color: #fecaca; background: #fef2f2; }
.summary-card.warn span { color: #b91c1c; }
.summary-card.warn strong { color: #dc2626; }
.block h3 { margin: 0 0 12px; font-size: 15px; display: flex; align-items: baseline; gap: 8px; }
.block h3 small { color: #94a3b8; font-size: 12px; font-weight: 500; }
.empty { padding: 26px 0; text-align: center; color: #94a3b8; font-size: 13px; border: 1px dashed #e2e8f0; border-radius: 14px; }
.rate { font-weight: 700; }
.rate.ok { color: #059669; }
.rate.mid { color: #d97706; }
.rate.low { color: #dc2626; }
.muted { color: #94a3b8; }
.block :deep(.el-table__cell) { padding: 7px 0; }
</style>

<style>
.class-drawer.el-drawer { border-radius: 22px 0 0 22px; overflow: hidden; }
.class-drawer .el-drawer__header { margin: 0; padding: 18px 22px; border-bottom: 1px solid #edf2f7; color: #0f172a; }
.class-drawer .el-drawer__body { padding: 20px 22px 28px; }
/* 预防：name-cell 次级行 class="block" 与 scoped 段落容器撞名风险，显式 margin 复位；
   flex 列布局消除模板空白文本节点的匿名行盒 */
.class-drawer .name-cell .cell { white-space: normal; word-break: break-all; display: flex; flex-direction: column; align-items: flex-start; }
.class-drawer .name-cell .block { display: block; margin: 3px 0 0; color: #94a3b8; font-size: 12px; font-weight: 400; }
.class-drawer .warn-cell .cell { white-space: normal; }
</style>
