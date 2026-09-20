<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">虚拟实验</div>
        <div class="page-subtitle">在开放时间内完成实验步骤并提交，提交后即时出分</div>
      </div>
      <el-button
        type="warning"
        plain
        size="small"
        @click="guideDialog.open()"
      >
        实验必读
      </el-button>
    </div>

    <TableSkeleton v-if="loading" :cols="5" />
    <div v-else-if="labs.length" class="lab-list">
      <article v-for="row in labs" :key="row.id" class="lab-card">
        <div class="lab-card-head">
          <span class="lab-badge">实验</span>
          <div class="lab-title">{{ row.title }}</div>
          <el-tag v-if="submissionOf(row)" :type="submissionOf(row).total_score != null ? 'success' : 'info'" size="small">
            {{ submissionOf(row).total_score != null ? `${submissionOf(row).total_score} 分` : '进行中' }}
          </el-tag>
        </div>
        <div class="lab-desc">{{ row.description || '按步骤完成华为命令配置' }}</div>
        <div class="lab-meta">
          <span>{{ row.course_name }}</span>
          <span>标准时长 {{ row.standard_minutes_display }} 分钟</span>
          <span>满分 {{ row.total_score }} 分</span>
          <span v-if="submissionOf(row)?.reviewed">教师已复核</span>
        </div>

        <!-- 成绩明细（已提交的实验：即时展示评分构成） -->
        <div v-if="isSubmitted(row) && breakdownOf(row)" class="lab-score">
          <div class="lab-score-head">
            <span class="lab-score-total">
              {{ submissionOf(row).total_score }}
              <em>/ {{ row.total_score }} 分</em>
            </span>
            <span class="lab-score-meta">
              步骤通过 {{ breakdownOf(row).passed_steps }}/{{ breakdownOf(row).total_steps }}
              · 错误 {{ breakdownOf(row).error_count }} 次
              · 用时 {{ breakdownOf(row).elapsed_minutes }} 分钟（标准 {{ breakdownOf(row).standard_minutes }}）
            </span>
            <el-tag v-if="submissionOf(row).reviewed" size="small" type="info" effect="plain">教师已复核</el-tag>
          </div>

          <div class="lab-breakdown">
            <div v-for="item in breakdownItems(row)" :key="item.key" class="bk-item">
              <div class="bk-label">{{ item.label }}</div>
              <div class="bk-value" :class="{ zero: Number(item.value) <= 0 }">
                {{ item.value }}<em> / {{ item.max }}</em>
              </div>
              <div class="bk-bar">
                <span :style="{ width: item.percent + '%', background: item.color }"></span>
              </div>
            </div>
          </div>
          <div class="lab-score-note">{{ breakdownNote(row) }}</div>
          <div v-if="reviewCommentOf(row)" class="lab-review">
            <span class="lab-review-title">教师评语</span>
            <span class="lab-review-text">{{ reviewCommentOf(row) }}</span>
          </div>
        </div>

        <div class="lab-actions">
          <el-button type="primary" size="small" :loading="entering === row.id" @click="enter(row)">
            {{ isSubmitted(row) ? '查看成绩' : '进入实验' }}
          </el-button>
          <el-button
            v-if="isSubmitted(row)"
            size="small"
            :loading="reporting === row.id"
            @click="downloadReport(row)"
          >
            下载实验报告
          </el-button>
        </div>
      </article>
    </div>
    <el-empty v-else description="暂无可参加的虚拟实验" />

    <!-- 实验必读（学生只读浏览） -->
    <LabGuideDialog ref="guideDialog" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import LabGuideDialog from '@/components/LabGuideDialog.vue'
import { listLabs, listLabSubmissions, startLab, generateLabReport, downloadLabReportUrl } from '@/api/labs'

const labs = ref([])
const submissions = ref([])
const loading = ref(false)
const entering = ref(null)
const reporting = ref(null)
const guideDialog = ref(null)

function submissionOf(row) {
  return submissions.value.find((s) => s.lab === row.id)
}

function isSubmitted(row) {
  const sub = submissionOf(row)
  return !!sub && sub.status === 'submitted'
}

function breakdownOf(row) {
  const sub = submissionOf(row)
  const bk = sub?.score_breakdown
  if (!bk || bk.total == null) return null
  return bk
}

function num(v) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.round(n * 10) / 10 : 0
}

/** 评分构成：基础分（步骤分×折算比）+ 准确性 + 效率 + 完成度 + 附加题分。 */
function breakdownItems(row) {
  const bk = breakdownOf(row)
  if (!bk) return []
  const sub = submissionOf(row)
  const items = [
    { key: 'base', label: '基础分', value: num(bk.base), max: num(bk.max_base), color: '#3b82f6' },
    { key: 'accuracy', label: '操作准确性', value: num(bk.accuracy), max: 5, color: '#10b981' },
    { key: 'efficiency', label: '完成效率', value: num(bk.efficiency), max: 5, color: '#f59e0b' },
    { key: 'completion', label: '完成度', value: num(bk.completion), max: 10, color: '#8b5cf6' },
  ]
  if (num(bk.question_total) > 0) {
    items.push({
      key: 'question',
      label: '附加题得分',
      value: num(bk.question_total),
      max: num(bk.question_total),
      color: '#0d9488',
      noBar: true,
    })
  }
  return items.map((it) => ({
    ...it,
    percent: it.noBar ? 100 : it.max > 0 ? Math.min(100, Math.round((it.value / it.max) * 100)) : 0,
  }))
}

function breakdownNote(row) {
  const bk = breakdownOf(row)
  if (!bk) return ''
  const parts = []
  if (num(bk.accuracy) >= 5) parts.push('全程无错误操作')
  else if (num(bk.error_count) > 0) parts.push(`共 ${bk.error_count} 次错误操作，每次扣 1 分`)
  if (num(bk.efficiency) >= 5) parts.push('用时未超标准时长')
  else parts.push('超时每 3 分钟扣 1 分')
  return parts.join('；')
}

function reviewCommentOf(row) {
  const bk = breakdownOf(row)
  const comment = bk?.review_comment
  return comment && String(comment).trim() ? String(comment).trim() : ''
}

async function load() {
  loading.value = true
  try {
    const [labRes, subRes] = await Promise.all([listLabs(), listLabSubmissions()])
    labs.value = labRes.results ?? labRes
    submissions.value = subRes.results ?? subRes
  } finally {
    loading.value = false
  }
}

async function enter(row) {
  entering.value = row.id
  try {
    const data = await startLab(row.id)
    const token = data.attempt_token
    if (data.page_url && token) {
      window.open(`${data.page_url}?token=${encodeURIComponent(token)}`, '_blank')
    } else {
      ElMessage.warning('实验页面暂未部署，请联系管理员')
    }
  } catch (e) {
    ElMessage.error(e?.message || '进入实验失败')
  } finally {
    entering.value = null
  }
}

async function downloadReport(row) {
  const sub = submissionOf(row)
  if (!sub) return
  reporting.value = row.id
  try {
    await generateLabReport(sub.id)
  } catch {
    // 无结论等场景后端会返回错误消息；仍尝试直接下载已生成报告
  }
  window.open(downloadLabReportUrl(sub.id, 'pdf'), '_blank')
  reporting.value = null
}

onMounted(load)
</script>

<style scoped>
.lab-list { display: grid; gap: 14px; }
.lab-card { border: 1px solid #e4e7ed; border-radius: 10px; padding: 16px 18px; background: #fff; }
.lab-card-head { display: flex; align-items: center; gap: 10px; }
.lab-badge { background: #ecf5ff; color: #409eff; font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.lab-title { font-size: 16px; font-weight: 600; flex: 1; }
.lab-desc { color: #6b7280; font-size: 13px; margin: 8px 0; }
.lab-meta { display: flex; gap: 16px; color: #94a3b8; font-size: 12px; margin-bottom: 10px; }

/* 成绩明细 */
.lab-score {
  margin: 4px 0 14px;
  padding: 14px 16px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}
.lab-score-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.lab-score-total {
  color: #2563eb;
  font-size: 22px;
  font-weight: 750;
  line-height: 1;
}
.lab-score-total em {
  color: #94a3b8;
  font-size: 13px;
  font-style: normal;
  font-weight: 500;
}
.lab-score-meta { color: #64748b; font-size: 12.5px; }
.lab-breakdown {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px 18px;
}
.bk-item { display: grid; gap: 5px; }
.bk-label { color: #94a3b8; font-size: 12px; }
.bk-value { color: #1e293b; font-size: 15px; font-weight: 700; }
.bk-value.zero { color: #cbd5e1; }
.bk-value em { color: #94a3b8; font-size: 12px; font-style: normal; font-weight: 500; }
.bk-bar {
  height: 4px;
  border-radius: 2px;
  background: #e8edf4;
  overflow: hidden;
}
.bk-bar span { display: block; height: 100%; border-radius: 2px; transition: width 0.4s ease; }
.lab-score-note { margin-top: 10px; color: #94a3b8; font-size: 12px; }
.lab-review {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
  font-size: 13px;
}
.lab-review-title { flex-shrink: 0; color: #8b5cf6; font-weight: 650; }
.lab-review-text { color: #475569; line-height: 1.6; }
.lab-actions { display: flex; gap: 10px; margin-top: 4px; }
</style>
