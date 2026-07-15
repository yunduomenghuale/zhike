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
        <el-table-column label="模式" width="120" align="center">
          <template #default="{ row }"><el-tag effect="plain">{{ row.mode_display }}</el-tag></template>
        </el-table-column>
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
    <el-dialog v-model="submitVisible" title="提交作业" width="760px" align-center>
      <div class="hw-desc" v-if="current?.description">{{ current.description }}</div>
      <div v-if="current?.mode === 'questions'" class="homework-question-list">
        <div v-for="(item, index) in current.questions" :key="item.id" class="homework-question-card">
          <div class="question-title">
            <span>{{ index + 1 }}. {{ item.snapshot.stem }}</span>
            <el-tag size="small" effect="plain">{{ item.score }} 分</el-tag>
          </div>
          <el-radio-group v-if="['single', 'judge'].includes(item.snapshot.qtype)" v-model="answerOf(item.id).key">
            <el-radio v-for="option in item.snapshot.options" :key="option.key" :value="option.key">
              {{ option.key }}. {{ option.text }}
            </el-radio>
          </el-radio-group>
          <el-checkbox-group v-else-if="item.snapshot.qtype === 'multi'" v-model="answerOf(item.id).keys">
            <el-checkbox v-for="option in item.snapshot.options" :key="option.key" :value="option.key">
              {{ option.key }}. {{ option.text }}
            </el-checkbox>
          </el-checkbox-group>
          <div v-else-if="item.snapshot.qtype === 'blank'" class="blank-answer-list">
            <el-input
              v-for="(_, blankIndex) in answerOf(item.id).blanks"
              :key="blankIndex"
              v-model="answerOf(item.id).blanks[blankIndex]"
              :placeholder="`第 ${blankIndex + 1} 空`"
            />
          </div>
          <el-input v-else v-model="answerOf(item.id).text" type="textarea" :rows="4" placeholder="请输入答案" />
        </div>
      </div>
      <el-form v-else :model="submitForm">
        <el-form-item>
          <el-input v-model="submitForm.content" type="textarea" :rows="6" placeholder="在此输入作业内容…" />
        </el-form-item>
        <el-form-item label="附件（选填）">
          <el-upload :auto-upload="false" :limit="1" :on-change="onSubmitFile" :on-remove="() => { submitFile = null }">
            <el-button>选择文件</el-button>
          </el-upload>
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
        <div v-if="current?.mode === 'questions'" class="answer-result-list">
          <div v-for="(item, index) in viewData?.answer_items" :key="item.id" class="answer-result-item">
            <div><strong>{{ index + 1 }}. {{ item.snapshot.stem }}</strong></div>
            <div>我的答案：{{ formatAnswer(item.student_answer) || '未作答' }}</div>
            <el-tag v-if="item.needs_manual_grading && item.score == null" type="warning" size="small">等待教师批改</el-tag>
            <el-tag v-else :type="item.is_correct === false ? 'danger' : 'success'" size="small">
              得分 {{ item.score ?? 0 }} 分
            </el-tag>
          </div>
        </div>
        <div v-else class="view-text">{{ viewData?.content || '附件提交' }}</div>
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
const submitForm = reactive({ content: '', answers: {} })
const submitFile = ref(null)
function initialAnswer(item) {
  const qtype = item.snapshot?.qtype
  if (qtype === 'multi') return { keys: [] }
  if (qtype === 'blank') {
    const count = Math.max(1, item.snapshot?.answer_blank_count || (item.snapshot?.stem?.match(/_{2,}|（\s*）|\(\s*\)/g) || []).length)
    return { blanks: Array.from({ length: count }, () => '') }
  }
  if (qtype === 'short') return { text: '' }
  return { key: '' }
}
function answerOf(id) {
  return submitForm.answers[id]
}
function openSubmit(row) {
  current.value = row
  submitForm.content = ''
  submitForm.answers = Object.fromEntries((row.questions || []).map((item) => [item.id, initialAnswer(item)]))
  submitFile.value = null
  submitVisible.value = true
}
function onSubmitFile(file) {
  submitFile.value = file.raw
}
async function doSubmit() {
  if (current.value.mode !== 'questions' && !submitForm.content.trim() && !submitFile.value) {
    return ElMessage.warning('请输入作业内容或上传附件')
  }
  submitting.value = true
  try {
    let payload
    if (current.value.mode === 'questions') {
      payload = { homework: current.value.id, answers: submitForm.answers }
    } else if (submitFile.value) {
      payload = new FormData()
      payload.append('homework', current.value.id)
      payload.append('content', submitForm.content)
      payload.append('attachment', submitFile.value)
    } else {
      payload = { homework: current.value.id, content: submitForm.content }
    }
    await submitHomework(payload)
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

function formatAnswer(answer) {
  if (!answer) return ''
  if (answer.key != null) return String(answer.key)
  if (answer.keys) return answer.keys.join('、')
  if (answer.blanks) return answer.blanks.join(' / ')
  if (answer.text != null) return String(answer.text)
  return JSON.stringify(answer)
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
.homework-question-list {
  display: grid;
  gap: 14px;
  max-height: 60vh;
  overflow: auto;
  padding-right: 4px;
}
.homework-question-card,
.answer-result-item {
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-fill-color-extra-light);
}
.question-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  font-weight: 700;
  line-height: 1.6;
}
.homework-question-card :deep(.el-radio-group),
.homework-question-card :deep(.el-checkbox-group) {
  display: grid;
  gap: 8px;
}
.blank-answer-list,
.answer-result-list {
  display: grid;
  gap: 10px;
}
.answer-result-item {
  display: grid;
  gap: 9px;
}
.answer-result-item .el-tag { justify-self: start; }
</style>
