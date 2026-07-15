<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">我的作业</div>
        <div class="page-subtitle">查看老师发布的作业，在线提交并查看批改结果</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <TableSkeleton v-if="loading" :cols="5" />
      <el-table v-else :data="rows" stripe>
        <el-table-column prop="title" label="作业标题" min-width="180" />
        <el-table-column label="截止时间" width="180">
          <template #default="{ row }">{{ row.deadline ? new Date(row.deadline).toLocaleString() : '不限' }}</template>
        </el-table-column>
        <el-table-column prop="total_score" label="满分" width="80" align="center" />
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="!subOf(row)" type="info" effect="plain">未提交</el-tag>
            <el-tag v-else-if="subOf(row).correct_status === 'submitted'" type="warning" effect="light">待批改</el-tag>
            <el-tag v-else type="success" effect="light">已批改 {{ subOf(row).score }}分</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button v-if="!subOf(row)" type="primary" size="small" @click="openSubmit(row)">提交</el-button>
            <el-button v-else size="small" @click="openView(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无作业" />
    </el-card>

    <!-- 提交作业 -->
    <el-dialog v-model="submitVisible" title="提交作业" width="500px" align-center>
      <div class="hw-desc" v-if="current?.description">{{ current.description }}</div>
      <el-form :model="submitForm">
        <el-form-item>
          <el-input v-model="submitForm.content" type="textarea" :rows="6" placeholder="在此输入作业内容…" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="submitVisible = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="doSubmit">提交</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 查看批改 -->
    <el-dialog v-model="viewVisible" title="作业详情" width="500px" align-center>
      <div class="view-block">
        <div class="view-label">我的提交</div>
        <div class="view-text">{{ viewData?.content || '（无内容）' }}</div>
      </div>
      <template v-if="viewData?.correct_status !== 'submitted'">
        <div class="view-score">
          得分：<span class="score-num">{{ viewData?.score ?? '-' }}</span> / {{ current?.total_score }}
        </div>
        <div class="view-block" v-if="viewData?.comment">
          <div class="view-label">老师评语</div>
          <div class="view-text">{{ viewData.comment }}</div>
        </div>
      </template>
      <el-empty v-else description="老师尚未批改" :image-size="70" />
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listHomeworks, listSubmissions, submitHomework } from '@/api/homework'

const rows = ref([])
const loading = ref(false)
const subMap = ref({}) // homeworkId -> submission

function subOf(row) {
  return subMap.value[row.id]
}

async function load() {
  loading.value = true
  try {
    const [hw, subs] = await Promise.all([listHomeworks(), listSubmissions()])
    rows.value = hw.results ?? hw
    const list = subs.results ?? subs
    const map = {}
    list.forEach((s) => { map[s.homework] = s })
    subMap.value = map
  } finally {
    loading.value = false
  }
}

// ---- 提交 ----
const submitVisible = ref(false)
const submitting = ref(false)
const current = ref(null)
const submitForm = reactive({ content: '' })
function openSubmit(row) {
  current.value = row
  submitForm.content = ''
  submitVisible.value = true
}
async function doSubmit() {
  if (!submitForm.content.trim()) return ElMessage.warning('请输入作业内容')
  submitting.value = true
  try {
    await submitHomework({ homework: current.value.id, content: submitForm.content })
    ElMessage.success('提交成功')
    submitVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

// ---- 查看 ----
const viewVisible = ref(false)
const viewData = ref(null)
function openView(row) {
  current.value = row
  viewData.value = subOf(row)
  viewVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.hw-desc {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 14px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}
.view-block {
  margin-bottom: 14px;
}
.view-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.view-text {
  white-space: pre-wrap;
  line-height: 1.6;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 10px 14px;
}
.view-score {
  font-size: 15px;
  margin-bottom: 14px;
}
.score-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--el-color-primary);
}
</style>
