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
        @click="openGuide"
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
        <div class="lab-actions">
          <el-button type="primary" size="small" :loading="entering === row.id" @click="enter(row)">
            {{ submissionOf(row)?.status === 'submitted' ? '查看成绩' : '进入实验' }}
          </el-button>
          <el-button
            v-if="submissionOf(row)?.status === 'submitted'"
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listLabs, listLabSubmissions, startLab, generateLabReport, downloadLabReportUrl } from '@/api/labs'

const labs = ref([])
const submissions = ref([])
const loading = ref(false)
const entering = ref(null)
const reporting = ref(null)

function submissionOf(row) {
  return submissions.value.find((s) => s.lab === row.id)
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

function openGuide() {
  window.open('/labs/lab-guide.html', '_blank')
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
</style>
