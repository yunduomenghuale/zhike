<template>
  <div class="page-container homework-page" :class="{ 'detail-open': detailMode }">
    <div v-if="!detailMode" class="page-header">
      <div>
        <div class="page-title">我的作业</div>
        <div class="page-subtitle">查看老师发布的作业，在线提交并查看批改结果</div>
      </div>
    </div>

    <div class="student-card-shell" :class="{ 'is-workspace': detailMode }">
      <template v-if="detailMode">
        <section class="homework-workspace">
          <header class="workspace-header">
            <button type="button" class="workspace-back" @click="closeWorkspace">
              <el-icon><ArrowLeft /></el-icon>返回作业列表
            </button>
            <div class="workspace-heading">
              <div class="workspace-title-row">
                <h2>{{ current?.title }}</h2>
                <span :class="['student-status', statusInfo(current).tone]">{{ statusInfo(current).label }}</span>
              </div>
              <div class="workspace-meta">
                <span><el-icon><Clock /></el-icon>{{ formatTime(current?.start_time, '立即开始') }}</span>
                <span>截止 {{ formatTime(current?.deadline, '不限') }}</span>
                <strong>{{ current?.total_score }} 分</strong>
              </div>
            </div>
          </header>

          <div v-if="current?.description" class="assignment-brief">
            <div class="section-kicker">作业说明</div>
            <div class="assignment-description">{{ current.description }}</div>
          </div>

          <section v-if="current?.attachment" class="assignment-resource">
            <div class="resource-heading">
              <div>
                <div class="section-kicker">作业资料</div>
                <div class="resource-title">教师附件</div>
              </div>
              <div class="resource-actions">
                <a
                  class="resource-action"
                  :href="current.attachment"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <el-icon><View /></el-icon>打开文件
                </a>
                <a class="resource-action primary" :href="current.attachment" download>
                  <el-icon><Download /></el-icon>下载附件
                </a>
              </div>
            </div>
            <div class="resource-file">
              <span class="resource-file-icon"><el-icon><Document /></el-icon></span>
              <div>
                <strong>{{ teacherAttachmentName }}</strong>
                <span>{{ isTeacherAttachmentPdf ? 'PDF 文档，可在下方直接预览' : '教师提供的作业文件' }}</span>
              </div>
            </div>
            <iframe
              v-if="isTeacherAttachmentPdf"
              class="resource-preview"
              :src="current.attachment"
              title="作业附件 PDF 预览"
            ></iframe>
          </section>

          <template v-if="detailMode === 'submit'">
            <div v-if="current?.mode === 'questions'" class="homework-question-list">
              <div v-for="(item, index) in current.questions" :key="item.id" class="homework-question-card">
                <div class="question-title">
                  <div class="question-heading">
                    <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span>{{ item.snapshot.stem }}</span>
                  </div>
                  <span class="question-score">{{ item.score }} 分</span>
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
                <el-input v-else v-model="answerOf(item.id).text" type="textarea" :rows="5" placeholder="请输入答案" />
              </div>
            </div>

            <div v-else class="attachment-answer">
              <div class="section-kicker">我的作答</div>
              <el-input v-model="submitForm.content" type="textarea" :rows="10" placeholder="在此输入作业内容…" />
              <div class="upload-section">
                <div>
                  <div class="upload-title">作业附件</div>
                  <div class="upload-tip">可选，最多上传一个文件</div>
                </div>
                <el-upload :auto-upload="false" :limit="1" :on-change="onSubmitFile" :on-remove="() => { submitFile = null }">
                  <el-button>选择文件</el-button>
                </el-upload>
              </div>
            </div>

            <footer class="workspace-footer">
              <div v-if="current?.mode === 'questions'" class="answer-progress">
                已完成 <strong>{{ answeredCount }}</strong> / {{ questionTotal }} 题
              </div>
              <div v-else class="answer-progress">完成作业后，请检查内容再提交</div>
              <el-button type="primary" size="large" :loading="submitting" @click="doSubmit">
                <el-icon><Check /></el-icon>确认提交
              </el-button>
            </footer>
          </template>

          <template v-else>
            <div v-if="viewData?.correct_status !== 'submitted'" class="result-summary">
              <div>
                <span>本次得分</span>
                <strong>{{ viewData?.score ?? '-' }}</strong>
                <small>/ {{ current?.total_score }} 分</small>
              </div>
              <span class="result-state">已批改</span>
            </div>
            <div v-else class="pending-review">
              <span class="pending-dot"></span>
              <div><strong>作业已提交</strong><span>老师批改后会在这里显示成绩与评语</span></div>
            </div>

            <div class="view-block">
              <div class="section-kicker">我的提交</div>
              <div v-if="current?.mode === 'questions'" class="answer-result-list">
                <div v-for="(item, index) in viewData?.answer_items" :key="item.id" class="answer-result-item">
                  <div class="result-question-title">
                    <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
                    <strong>{{ item.snapshot.stem }}</strong>
                  </div>
                  <div class="submitted-answer">我的答案：{{ formatAnswer(item.student_answer) || '未作答' }}</div>
                  <el-tag v-if="item.needs_manual_grading && item.score == null" type="warning" size="small">等待教师批改</el-tag>
                  <el-tag v-else :type="item.is_correct === false ? 'danger' : 'success'" size="small">
                    得分 {{ item.score ?? 0 }} 分
                  </el-tag>
                </div>
              </div>
              <div v-else class="view-text">{{ viewData?.content || '附件提交' }}</div>
            </div>

            <div v-if="viewData?.correct_status !== 'submitted' && viewData?.comment" class="teacher-comment">
              <div class="section-kicker">老师评语</div>
              <div class="view-text">{{ viewData.comment }}</div>
            </div>
          </template>
        </section>
      </template>

      <template v-else>
        <TableSkeleton v-if="loading" :cols="5" />
        <div v-else-if="filteredRows.length" class="student-list course-standard-list">
          <article v-for="row in filteredRows" :key="row.id" class="student-row course-standard-row">
            <div class="student-row-left">
              <div class="student-row-copy">
                <div class="student-row-title">{{ row.title }}</div>
                <div class="student-row-meta">
                  <span><el-icon><Clock /></el-icon>{{ formatTime(row.start_time, '立即开始') }}</span>
                  <span>截止 {{ formatTime(row.deadline, '不限') }}</span>
                  <strong>{{ row.total_score }} 分</strong>
                  <span :class="['student-status', statusInfo(row).tone]">{{ statusInfo(row).label }}</span>
                </div>
              </div>
            </div>
            <div class="student-action-group course-standard-actions">
              <button
                v-if="!subOf(row)"
                class="student-action-btn course-standard-action-btn primary"
                type="button"
                :disabled="!hasStarted(row)"
                @click="openSubmit(row)"
              >
                <el-icon><View /></el-icon>{{ hasStarted(row) ? '查看作业' : '未开始' }}
              </button>
              <button v-else class="student-action-btn course-standard-action-btn" type="button" @click="openView(row)">
                <el-icon><View /></el-icon>查看结果
              </button>
            </div>
          </article>
        </div>
        <el-empty v-else :description="rows.length ? '没有匹配的作业' : '暂无作业'" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Check, Clock, Document, Download, View } from '@element-plus/icons-vue'
import { listHomeworks, listSubmissions, submitHomework } from '@/api/homework'

const route = useRoute()
const rows = ref([])
const loading = ref(false)
const subMap = ref({}) // homeworkId -> submission

const fixedCourseId = computed(() => Number(route.params.id) || null)
const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())
const filteredRows = computed(() => {
  if (!keyword.value) return rows.value
  return rows.value.filter((row) => [
    row.title,
    row.description,
    row.status_display,
  ].some((text) => String(text || '').toLowerCase().includes(keyword.value)))
})

function subOf(row) {
  return subMap.value[row.id]
}

function hasStarted(row) {
  return !row.start_time || new Date(row.start_time).getTime() <= Date.now()
}

function formatTime(value, fallback) {
  return value ? new Date(value).toLocaleString() : fallback
}

function statusInfo(row) {
  if (!row) return { label: '', tone: 'muted' }
  const sub = subOf(row)
  if (!hasStarted(row)) return { label: '未开始', tone: 'muted' }
  if (!sub) return { label: '未提交', tone: 'muted' }
  if (sub.correct_status === 'submitted') return { label: '待批改', tone: 'warn' }
  return { label: `已批改 ${sub.score} 分`, tone: 'success' }
}

async function load() {
  loading.value = true
  try {
    const params = fixedCourseId.value ? { course: fixedCourseId.value } : undefined
    const [hw, subs] = await Promise.all([listHomeworks(params), listSubmissions()])
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
const detailMode = ref(null)
const submitting = ref(false)
const current = ref(null)
const submitForm = reactive({ content: '', answers: {} })
const submitFile = ref(null)
const teacherAttachmentName = computed(() => {
  const url = String(current.value?.attachment || '')
  const rawName = url.split('/').pop()?.split('?')[0] || '作业附件'
  try {
    return decodeURIComponent(rawName)
  } catch {
    return rawName
  }
})
const isTeacherAttachmentPdf = computed(() => teacherAttachmentName.value.toLowerCase().endsWith('.pdf'))
const questionTotal = computed(() => current.value?.questions?.length || 0)
const answeredCount = computed(() => (current.value?.questions || []).filter((item) => {
  const answer = submitForm.answers[item.id] || {}
  const qtype = item.snapshot?.qtype
  if (qtype === 'multi') return Boolean(answer.keys?.length)
  if (qtype === 'blank') return Boolean(answer.blanks?.length) && answer.blanks.every((value) => String(value || '').trim())
  if (qtype === 'short') return Boolean(String(answer.text || '').trim())
  return Boolean(String(answer.key || '').trim())
}).length)

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
  if (!hasStarted(row)) {
    return ElMessage.warning('作业尚未开始')
  }
  current.value = row
  submitForm.content = ''
  submitForm.answers = Object.fromEntries((row.questions || []).map((item) => [item.id, initialAnswer(item)]))
  submitFile.value = null
  detailMode.value = 'submit'
}
function onSubmitFile(file) {
  submitFile.value = file.raw
}
async function doSubmit() {
  if (current.value.mode === 'questions' && answeredCount.value < questionTotal.value) {
    return ElMessage.warning(`还有 ${questionTotal.value - answeredCount.value} 道题未作答`)
  }
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
    closeWorkspace()
    await load()
  } finally {
    submitting.value = false
  }
}

// ---- 查看 ----
const viewData = ref(null)
function openView(row) {
  current.value = row
  viewData.value = subOf(row)
  detailMode.value = 'view'
}

function closeWorkspace() {
  detailMode.value = null
  current.value = null
  viewData.value = null
  submitFile.value = null
}

function formatAnswer(answer) {
  if (!answer) return ''
  if (answer.key != null) return String(answer.key)
  if (answer.keys) return answer.keys.join('、')
  if (answer.blanks) return answer.blanks.join(' / ')
  if (answer.text != null) return String(answer.text)
  return JSON.stringify(answer)
}

watch(fixedCourseId, () => {
  closeWorkspace()
  load()
})

onMounted(load)
</script>

<style scoped>
.homework-page.detail-open {
  padding: 0 !important;
}

.student-list {
  display: flex;
  flex-direction: column;
}
.student-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.student-row-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}
.student-row-copy {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 12px;
}
.student-row-title {
  max-width: 420px;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.student-row-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  color: #64748b;
  font-size: 12.5px;
}
.student-row-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.student-status {
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-weight: 700;
}
.student-status.muted {
  color: #64748b;
  background: #f1f5f9;
}
.student-status.warn {
  color: #d97706;
  background: #fff7ed;
}
.student-status.success {
  color: #16a34a;
  background: #f0fdf4;
}
.student-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  color: #2563eb;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.student-action-btn:hover {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.student-action-btn:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}
.student-action-btn.primary {
  color: #2563eb;
}

.homework-workspace {
  min-height: calc(100vh - 108px);
  position: relative;
  padding-bottom: 88px;
}

.workspace-header {
  padding: 22px 24px 20px;
  border-bottom: 1px solid #e8edf5;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.88), rgba(255, 255, 255, 0.96) 60%);
}

.workspace-back {
  min-height: 36px;
  padding: 0 12px;
  border: 0;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #475569;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: inset 0 0 0 1px #e2e8f0;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.workspace-back:hover {
  color: #2563eb;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.28);
}

.workspace-heading {
  margin-top: 18px;
}

.workspace-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.workspace-title-row h2 {
  min-width: 0;
  margin: 0;
  color: #0f172a;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.4;
}

.workspace-meta {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 16px;
  color: #64748b;
  font-size: 13px;
}

.workspace-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.workspace-meta strong {
  color: #2563eb;
}

.assignment-brief,
.assignment-resource,
.attachment-answer,
.view-block,
.teacher-comment,
.result-summary,
.pending-review {
  margin-right: 24px;
  margin-left: 24px;
}

.assignment-brief {
  margin-top: 20px;
  padding: 16px 18px;
  border: 1px solid #e6edf8;
  border-radius: 14px;
  background: #f8fbff;
}

.section-kicker {
  margin-bottom: 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.04em;
}

.assignment-description {
  white-space: pre-wrap;
  color: #526076;
  font-size: 13.5px;
  line-height: 1.75;
}

.assignment-resource {
  margin-top: 20px;
  padding: 18px;
  border: 1px solid #dbeafe;
  border-radius: 16px;
  background: linear-gradient(145deg, #f8fbff, #fff 64%);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.05);
}

.resource-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.resource-heading .section-kicker {
  margin-bottom: 3px;
}

.resource-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 750;
}

.resource-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-action {
  min-height: 36px;
  padding: 0 13px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #2563eb;
  background: #fff;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  transition: border-color 0.16s ease, background-color 0.16s ease, transform 0.16s ease;
}

.resource-action:hover {
  border-color: #93c5fd;
  background: #eff6ff;
  transform: translateY(-1px);
}

.resource-action.primary {
  border-color: #2563eb;
  color: #fff;
  background: #2563eb;
}

.resource-action.primary:hover {
  border-color: #1d4ed8;
  background: #1d4ed8;
}

.resource-file {
  margin-top: 14px;
  padding: 13px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.88);
}

.resource-file-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #2563eb;
  background: #eff6ff;
  font-size: 20px;
}

.resource-file > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.resource-file strong {
  overflow: hidden;
  color: #334155;
  font-size: 13.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-file span:not(.resource-file-icon) {
  color: #94a3b8;
  font-size: 12px;
}

.resource-preview {
  width: 100%;
  height: min(52vh, 520px);
  min-height: 360px;
  margin-top: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  display: block;
  background: #f8fafc;
}

.view-block {
  margin-top: 22px;
}

.view-text {
  white-space: pre-wrap;
  padding: 16px 18px;
  border: 1px solid #e8edf5;
  border-radius: 14px;
  background: #f8fafc;
  color: #475569;
  font-size: 13.5px;
  line-height: 1.75;
}

.homework-question-list {
  display: grid;
  gap: 16px;
  padding: 20px 24px 0;
}

.homework-question-card,
.answer-result-item {
  padding: 20px;
  border: 1px solid #e5eaf2;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.04);
}

.question-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  color: #0f172a;
  font-weight: 700;
  line-height: 1.6;
}

.question-heading,
.result-question-title {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.question-index {
  min-width: 34px;
  height: 28px;
  padding: 0 8px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 800;
}

.question-score {
  height: 26px;
  padding: 0 9px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  color: #64748b;
  background: #f1f5f9;
  font-size: 12px;
  font-weight: 700;
}

.homework-question-card :deep(.el-radio-group),
.homework-question-card :deep(.el-checkbox-group) {
  display: grid;
  gap: 9px;
}

.homework-question-card :deep(.el-radio),
.homework-question-card :deep(.el-checkbox) {
  width: 100%;
  min-height: 44px;
  margin: 0;
  padding: 9px 12px;
  border: 1px solid #e8edf5;
  border-radius: 11px;
  background: #f8fafc;
  transition: border-color 0.16s ease, background-color 0.16s ease;
}

.homework-question-card :deep(.el-radio:hover),
.homework-question-card :deep(.el-checkbox:hover) {
  border-color: rgba(37, 99, 235, 0.3);
  background: #f8fbff;
}

.homework-question-card :deep(.el-radio.is-checked),
.homework-question-card :deep(.el-checkbox.is-checked) {
  border-color: rgba(37, 99, 235, 0.45);
  background: #eff6ff;
}

.homework-question-card :deep(.el-radio__label),
.homework-question-card :deep(.el-checkbox__label) {
  white-space: normal;
  color: #475569;
  line-height: 1.55;
}

.homework-question-card :deep(.el-radio.is-checked .el-radio__label),
.homework-question-card :deep(.el-checkbox.is-checked .el-checkbox__label) {
  color: #1d4ed8;
}

.blank-answer-list,
.answer-result-list {
  display: grid;
  gap: 12px;
}

.attachment-answer {
  margin-top: 20px;
  padding: 20px;
  border: 1px solid #e5eaf2;
  border-radius: 16px;
  background: #fff;
}

.upload-section {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px dashed #cbd5e1;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: #f8fafc;
}

.upload-title {
  color: #334155;
  font-size: 13.5px;
  font-weight: 700;
}

.upload-tip {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12px;
}

.workspace-footer {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  min-height: 72px;
  padding: 12px 24px;
  border-top: 1px solid #e5eaf2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.04);
  backdrop-filter: blur(16px);
}

.answer-progress {
  color: #64748b;
  font-size: 13px;
}

.answer-progress strong {
  color: #2563eb;
  font-size: 16px;
}

.result-summary {
  margin-top: 20px;
  min-height: 104px;
  padding: 18px 20px;
  border: 1px solid #dbeafe;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: linear-gradient(135deg, #eff6ff, #fff);
}

.result-summary div {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.result-summary span,
.result-summary small {
  color: #64748b;
  font-size: 13px;
}

.result-summary strong {
  color: #2563eb;
  font-size: 34px;
  line-height: 1;
}

.result-summary .result-state {
  height: 30px;
  padding: 0 11px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  color: #15803d;
  background: #dcfce7;
  font-weight: 700;
}

.pending-review {
  margin-top: 20px;
  min-height: 82px;
  padding: 16px 18px;
  border: 1px solid #fde7bd;
  border-radius: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: #fffbeb;
}

.pending-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: #f59e0b;
  box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.13);
}

.pending-review div {
  display: grid;
  gap: 4px;
}

.pending-review strong {
  color: #92400e;
  font-size: 14px;
}

.pending-review div span {
  color: #a16207;
  font-size: 12.5px;
}

.answer-result-item {
  display: grid;
  gap: 9px;
}

.result-question-title strong {
  color: #0f172a;
  line-height: 1.65;
}

.submitted-answer {
  color: #475569;
  font-size: 13.5px;
}

.answer-result-item .el-tag {
  justify-self: start;
}

.teacher-comment {
  margin-top: 22px;
}

@media (max-width: 768px) {
  .student-row {
    flex-direction: column;
    align-items: stretch;
  }
  .student-action-group {
    justify-content: flex-end;
  }

  .homework-workspace {
    min-height: 100vh;
    padding-bottom: 108px;
  }

  .workspace-header {
    padding: 18px 16px;
  }

  .workspace-title-row h2 {
    width: 100%;
    order: -1;
    font-size: 19px;
  }

  .assignment-brief,
  .assignment-resource,
  .attachment-answer,
  .view-block,
  .teacher-comment,
  .result-summary,
  .pending-review {
    margin-right: 16px;
    margin-left: 16px;
  }

  .homework-question-list {
    padding-right: 16px;
    padding-left: 16px;
  }

  .homework-question-card,
  .answer-result-item,
  .attachment-answer {
    padding: 16px;
  }

  .question-title {
    gap: 10px;
  }

  .question-heading {
    gap: 8px;
  }

  .upload-section {
    align-items: stretch;
    flex-direction: column;
  }

  .resource-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .resource-actions {
    width: 100%;
  }

  .resource-action {
    flex: 1;
    justify-content: center;
  }

  .resource-preview {
    min-height: 440px;
  }

  .workspace-footer {
    min-height: 96px;
    padding: 12px 16px;
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .workspace-footer .el-button {
    width: 100%;
    margin: 0;
  }
}
</style>
