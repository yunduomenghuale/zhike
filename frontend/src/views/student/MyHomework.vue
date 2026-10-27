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
                <span class="meta-chip">
                  <el-icon><Clock /></el-icon>
                  <span class="meta-chip-label">开始</span>
                  {{ formatTime(current?.start_time, '立即开始') }}
                </span>
                <span class="meta-chip">
                  <el-icon><Clock /></el-icon>
                  <span class="meta-chip-label">截止</span>
                  {{ formatTime(current?.deadline, '不限') }}
                </span>
                <span class="meta-chip score">
                  <el-icon><Trophy /></el-icon>
                  <span class="meta-chip-label">满分</span>
                  {{ current?.total_score }} 分
                </span>
              </div>
            </div>
          </header>

          <div v-if="current?.description" class="assignment-brief">
            <div class="section-kicker">作业说明</div>
            <div class="assignment-description">{{ current.description }}</div>
          </div>

          <div :class="{ 'submit-cols': splitAnswer }">
            <section v-if="teacherAttachments.length" class="assignment-resource">
              <div class="resource-heading">
                <div>
                  <div class="section-kicker">作业资料</div>
                  <div class="resource-title">教师附件（{{ teacherAttachments.length }}）</div>
                </div>
              </div>
              <div class="resource-file-list">
                <div v-for="file in teacherAttachments" :key="file.url" class="resource-file">
                  <span class="resource-file-icon"><el-icon><Document /></el-icon></span>
                  <div>
                    <strong>{{ file.name }}</strong>
                    <span>{{ isPdfName(file.name) ? 'PDF 文档，可直接在线预览' : '教师提供的作业文件' }}{{ file.size ? ` · ${formatFileSize(file.size)}` : '' }}</span>
                  </div>
                  <div class="resource-file-actions">
                    <a class="resource-action" :href="file.url" target="_blank" rel="noopener noreferrer">
                      <el-icon><View /></el-icon>打开文件
                    </a>
                    <a class="resource-action primary" :href="file.url" download>
                      <el-icon><Download /></el-icon>下载
                    </a>
                  </div>
                </div>
              </div>
              <!-- PDF 无工具栏连续滚动预览：与教师端同一组件，上下滚动查看 -->
              <PdfScrollPreview
                v-if="previewTeacherUrl"
                class="resource-preview"
                :homework-id="current.id"
                :url="previewTeacherUrl"
                max-height="min(52vh, 520px)"
              />
            </section>

            <template v-if="detailMode === 'submit'">
            <div v-if="current?.mode === 'questions'" class="homework-question-list">
              <div v-for="(item, index) in current.questions" :key="item.id" class="homework-question-card">
                <div class="question-title">
                  <div class="question-heading">
                    <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span class="question-type-tag" :class="`qt-${item.snapshot.qtype}`">{{ abbrQtype(item.snapshot) }}</span>
                    <span>{{ item.snapshot.stem }}</span>
                  </div>
                  <span class="question-score">{{ item.score }} 分</span>
                </div>
                <QuestionImage :question="item.snapshot" />
                <el-radio-group v-if="['single', 'judge'].includes(item.snapshot.qtype)" v-model="answerOf(item.id).key">
                  <el-radio v-for="option in optionsOf(item)" :key="option.key" :value="option.key">
                    {{ option.key }}. {{ option.text }}
                  </el-radio>
                </el-radio-group>
                <el-checkbox-group v-else-if="item.snapshot.qtype === 'multi'" v-model="answerOf(item.id).keys">
                  <el-checkbox v-for="option in optionsOf(item)" :key="option.key" :value="option.key">
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
              <div class="answer-dock">
                <el-input
                  v-model="submitForm.content"
                  type="textarea"
                  resize="none"
                  class="answer-dock-textarea"
                  placeholder="在此输入作业内容…"
                />
                <div class="answer-dock-bar">
                  <div class="upload-info">
                    <div class="upload-title">作业附件</div>
                    <div class="upload-tip">支持图片与文档，可多选，单个不超过 20MB；选择后立即上传</div>
                  </div>
                  <div class="upload-side">
                    <el-upload
                      ref="uploadRef"
                      :auto-upload="false"
                      multiple
                      :limit="9"
                      :show-file-list="false"
                      accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip,.rar"
                      :on-change="onSubmitFile"
                      :on-exceed="onExceedFile"
                    >
                      <el-button class="upload-btn" :icon="Upload">选择文件</el-button>
                    </el-upload>
                  </div>
                </div>
                <!-- 已选文件：图片缩略图预览 + 上传进度/状态 + 失败重试 + 大小统计 -->
                <div v-if="submitFiles.length" class="submit-file-list">
                  <div v-for="(file, index) in submitFiles" :key="file.key" class="submit-file-item" :class="`is-${file.status}`">
                    <el-image
                      v-if="file.isImage"
                      :src="file.previewUrl"
                      fit="cover"
                      class="submit-file-thumb"
                      :preview-src-list="submitImageUrls"
                    />
                    <span v-else class="submit-file-icon"><el-icon><Document /></el-icon></span>
                    <div class="submit-file-info">
                      <div class="submit-file-name" :title="file.name">{{ file.name }}</div>
                      <div class="submit-file-meta">
                        <span>{{ formatFileSize(file.size) }}</span>
                        <span v-if="file.status === 'uploading'" class="submit-file-status is-uploading">上传中 {{ file.progress }}%</span>
                        <span v-else-if="file.status === 'success'" class="submit-file-status is-success">已上传</span>
                        <span v-else-if="file.status === 'error'" class="submit-file-status is-error">上传失败</span>
                      </div>
                      <div v-if="file.status === 'uploading'" class="submit-progress-track">
                        <div class="submit-progress-bar" :style="{ width: file.progress + '%' }"></div>
                      </div>
                      <div v-else-if="file.status === 'error'" class="submit-file-error">{{ file.error || '上传失败，请重试' }}</div>
                    </div>
                    <div class="submit-file-actions">
                      <el-button v-if="file.status === 'error'" link type="primary" @click="retrySubmitFile(file)">重试</el-button>
                      <el-button link type="danger" @click="removeSubmitFile(index)">移除</el-button>
                    </div>
                  </div>
                  <div class="submit-file-summary">
                    已选 {{ submitFiles.length }} 个文件，{{ submitUploadedCount }} 个已上传（单个上限 20MB，最多 9 个）
                  </div>
                </div>
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
            <div v-if="viewData?.correct_status === 'returned'" class="result-summary">
              <div>
                <span>本次得分</span>
                <strong>{{ viewData?.score ?? '-' }}</strong>
                <small>/ {{ current?.total_score }} 分</small>
              </div>
              <span class="result-state">已发布成绩</span>
            </div>
            <div v-else class="pending-review">
              <span class="pending-dot"></span>
              <div v-if="viewData?.correct_status === 'graded'"><strong>老师已批改完成</strong><span>成绩发布后这里会显示得分与评语</span></div>
              <div v-else><strong>作业已提交</strong><span>答案与解析已开放学习，主观题批改后公布总成绩与评语</span></div>
            </div>

            <div class="view-block">
              <div class="section-kicker">我的提交</div>
              <div v-if="current?.mode === 'questions'" class="answer-result-list">
                <div v-for="(item, index) in viewData?.answer_items" :key="item.id" class="answer-result-item">
                  <div class="result-question-title">
                    <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span class="question-type-tag" :class="`qt-${item.snapshot.qtype}`">{{ abbrQtype(item.snapshot) }}</span>
                    <strong>{{ item.snapshot.stem }}</strong>
                  </div>
                  <QuestionImage :question="item.snapshot" />
                  <div class="submitted-answer">我的答案：{{ formatAnswer(item.student_answer, item.snapshot) || '未作答' }}</div>
                  <!-- 提交即可学习：客观题答案/解析/得分即时可见；主观题得分待批改，解析同样开放 -->
                  <div v-if="correctAnswerText(item.snapshot)" class="correct-answer">{{ answerLabel(item) }}：{{ correctAnswerText(item.snapshot) }}</div>
                  <div v-if="item.snapshot.analysis" class="answer-analysis">解析：{{ item.snapshot.analysis }}</div>
                  <div class="result-score-row">
                    <template v-if="item.needs_manual_grading">
                      <el-tag v-if="item.score == null" type="warning" size="small">等待教师批改</el-tag>
                      <el-tag v-else type="success" size="small">得分 {{ item.score }} 分</el-tag>
                    </template>
                    <el-tag v-else :type="objectiveResultTag(item).type" size="small">
                      {{ objectiveResultTag(item).text }} · 得分 {{ item.score ?? 0 }} 分
                    </el-tag>
                  </div>
                  <div v-if="item.comment" class="answer-comment">老师评语：{{ item.comment }}</div>
                </div>
              </div>
              <template v-else>
                <div class="view-text">{{ viewData?.content || '附件提交' }}</div>
                <div v-if="submittedAttachments.length" class="submitted-attachments">
                  <div class="section-kicker">提交的附件</div>
                  <div class="submitted-attachment-list">
                    <template v-for="(file, fileIndex) in submittedAttachments" :key="fileIndex">
                      <el-image
                        v-if="isImageFile(file.name)"
                        :src="file.url"
                        fit="cover"
                        class="submitted-attachment-thumb"
                        :preview-src-list="submittedImageUrls"
                      />
                      <a v-else class="submitted-attachment-file" :href="file.url" target="_blank" rel="noopener">
                        <el-icon><Document /></el-icon>
                        <span class="submitted-attachment-name" :title="file.name">{{ file.name }}</span>
                        <small>{{ file.size ? formatFileSize(file.size) : '' }}</small>
                      </a>
                    </template>
                  </div>
                </div>
              </template>
            </div>

            <div v-if="viewData?.correct_status === 'returned' && viewData?.comment" class="teacher-comment">
              <div class="section-kicker">老师评语</div>
              <div class="view-text">{{ viewData.comment }}</div>
            </div>
          </template>
          </div>
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
import { computed, markRaw, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Check, Clock, Document, Download, Trophy, Upload, View } from '@element-plus/icons-vue'
import PdfScrollPreview from '@/components/PdfScrollPreview.vue'
import QuestionImage from '@/components/QuestionImage.vue'
import { uploadWithProgress, isImageFile, fileNameFromUrl } from '@/utils/upload'
import { abbrQtype } from '@/utils/question-abbr'
import { blankAnswerText } from '@/utils/blank-answer'
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

// 题目选项：判断题快照缺 options 时回退默认对错项（兼容历史数据；答案 key 为 T/F 时用 T/F 选项保持一致）
function optionsOf(item) {
  const snapshot = item?.snapshot || {}
  if (Array.isArray(snapshot.options) && snapshot.options.length) return snapshot.options
  if (snapshot.qtype === 'judge') {
    const key = String(snapshot.answer?.key || '').toUpperCase()
    if (key === 'T' || key === 'F') return [{ key: 'T', text: '正确' }, { key: 'F', text: '错误' }]
    return [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }]
  }
  return []
}

function statusInfo(row) {
  if (!row) return { label: '', tone: 'muted' }
  const sub = subOf(row)
  if (!hasStarted(row)) return { label: '未开始', tone: 'muted' }
  if (!sub) return { label: '未提交', tone: 'muted' }
  if (sub.correct_status === 'submitted') return { label: '待批改', tone: 'warn' }
  if (sub.correct_status === 'graded') return { label: '已批改，待发布成绩', tone: 'warn' }
  return { label: `已发布 ${sub.score} 分`, tone: 'success' }
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
// 多附件提交：[{key, raw, name, size, isImage, previewUrl}]
const submitFiles = ref([])
const uploadRef = ref(null)
const SUBMIT_ALLOWED_EXT = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.zip', '.rar', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
const submitImageUrls = computed(() => submitFiles.value.filter((f) => f.isImage).map((f) => f.previewUrl))
let submitFileSeq = 0

function isPdfName(name) {
  return String(name || '').toLowerCase().endsWith('.pdf')
}
function formatFileSize(bytes) {
  const size = Number(bytes || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}
// 教师作业附件（多附件）：后端序列化直接返回原文件名（存储文件名为 uuid）
const teacherAttachments = computed(() => (current.value?.attachments || []).map((item) => ({ ...item })))
// 自动在线预览第一个 PDF 附件（无工具栏连续滚动，与教师端一致）
const previewTeacherUrl = computed(() => {
  const pdf = teacherAttachments.value.find((item) => isPdfName(item.name))
  return pdf?.url || ''
})
function correctAnswerText(snapshot) {
  const answer = snapshot?.answer || {}
  const options = snapshot?.options || []
  // 带选项内容展示，避免只显示 A/B/C/D 字母造成困惑
  const label = (key) => {
    const opt = options.find((o) => o.key === key)
    return opt ? `${key}. ${opt.text}` : String(key)
  }
  if (answer.key != null && String(answer.key) !== '') return label(answer.key)
  if (answer.keys?.length) return answer.keys.map(label).join('、')
  if (answer.blanks?.length) return blankAnswerText(answer)
  if (answer.text != null && String(answer.text).trim()) return String(answer.text)
  return ''
}
// 客观题结果徽章：全对「答对」、部分空命中「部分正确」（填空题按空赋分）、全错「答错」
function objectiveResultTag(item) {
  if (item.is_correct !== false) return { type: 'success', text: '答对' }
  if (Number(item.score) > 0) return { type: 'warning', text: '部分正确' }
  return { type: 'danger', text: '答错' }
}

function onSubmitFile(file) {
  const raw = file?.raw
  if (!raw) return
  const name = String(raw.name || '')
  const ext = name.includes('.') ? `.${name.split('.').pop().toLowerCase()}` : ''
  if (!SUBMIT_ALLOWED_EXT.includes(ext)) {
    ElMessage.warning('不支持该文件格式，支持图片与 PDF、Office 文档、TXT、压缩包')
    return
  }
  if (Number(raw.size || 0) > 20 * 1024 * 1024) {
    ElMessage.warning('单个附件大小不能超过 20MB')
    return
  }
  if (submitFiles.value.length >= 9) {
    ElMessage.warning('一次最多上传 9 个附件')
    return
  }
  const isImage = isImageFile(name)
  // reactive 任务：status/progress 变更才能触发重渲染；raw 文件对象 markRaw 防代理破坏 FormData
  const task = reactive({
    key: `f${(submitFileSeq += 1)}`,
    raw: markRaw(raw),
    name,
    size: Number(raw.size || 0),
    isImage,
    previewUrl: isImage ? URL.createObjectURL(raw) : '',
    // 上传流程状态：pending 排队 / uploading 上传中 / success 已暂存 / error 失败
    status: 'pending',
    progress: 0,
    error: '',
    staged: null,
  })
  submitFiles.value.push(task)
  // 选择即暂存上传：进度/状态/结果即时展示，提交时仅传引用（uploaded）
  stageSubmitFile(task)
}

// 暂存上传到服务端（提交前落地，提交仅引用）；失败可原任务重试
async function stageSubmitFile(task) {
  if (!task || task.status === 'uploading') return
  task.status = 'uploading'
  task.progress = 0
  task.error = ''
  try {
    const body = new FormData()
    body.append('attachments', task.raw)
    const payload = await uploadWithProgress(
      'POST',
      '/api/homework-submissions/attachments/',
      body,
      (percent) => { task.progress = percent },
    )
    const added = payload?.data?.added || []
    task.staged = added[0] || null
    task.status = 'success'
    task.progress = 100
  } catch (error) {
    task.status = 'error'
    task.error = error?.message || '上传失败，请重试'
  }
}

function retrySubmitFile(task) {
  stageSubmitFile(task)
}

function removeSubmitFile(index) {
  const [removed] = submitFiles.value.splice(index, 1)
  if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
  // 已暂存到服务端的文件在此成为孤儿，由 cleanup_submission_staging 管理命令定期清理
}

function releaseSubmitPreviews() {
  submitFiles.value.forEach((f) => {
    if (f.previewUrl) URL.revokeObjectURL(f.previewUrl)
  })
  submitFiles.value = []
}

function onExceedFile() {
  ElMessage.warning('一次最多上传 9 个附件')
}
const submitUploadedCount = computed(() => submitFiles.value.filter((f) => f.status === 'success').length)

// 附件 PDF 作业：左资料右作答的分栏布局（仅提交页、附件/文本作业且有 PDF 可预览）
const splitAnswer = computed(() => (
  detailMode.value === 'submit'
  && current.value?.mode !== 'questions'
  && Boolean(previewTeacherUrl.value)
))
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
  releaseSubmitPreviews()
  uploadRef.value?.clearFiles?.()
  detailMode.value = 'submit'
}
async function doSubmit() {
  if (current.value.mode === 'questions' && answeredCount.value < questionTotal.value) {
    return ElMessage.warning(`还有 ${questionTotal.value - answeredCount.value} 道题未作答`)
  }
  if (current.value.mode !== 'questions' && !submitForm.content.trim() && !submitFiles.value.length) {
    return ElMessage.warning('请输入作业内容或上传附件')
  }
  // 附件为选择即暂存上传：提交前不能有上传中/失败的任务，避免漏交或静默丢弃
  if (submitFiles.value.some((f) => f.status === 'uploading')) {
    return ElMessage.warning('附件正在上传中，请稍候再提交')
  }
  if (submitFiles.value.some((f) => f.status === 'error')) {
    return ElMessage.warning('有附件上传失败，请重试或移除后再提交')
  }
  submitting.value = true
  try {
    let payload
    if (current.value.mode === 'questions') {
      payload = { homework: current.value.id, answers: submitForm.answers }
    } else {
      payload = new FormData()
      payload.append('homework', current.value.id)
      payload.append('content', submitForm.content)
      // 附件已在选择时暂存上传，提交仅传引用（uploaded 为 JSON 字符串）
      const uploaded = submitFiles.value
        .filter((f) => f.status === 'success' && f.staged)
        .map((f) => f.staged)
      if (uploaded.length) payload.append('uploaded', JSON.stringify(uploaded))
    }
    const submission = await submitHomework(payload)
    ElMessage.success('提交成功')
    // 提交后直接进入该作业的结果展示页（即时看成绩/逐题判定），不再返回列表
    if (submission && submission.id) {
      subMap.value = { ...subMap.value, [current.value.id]: submission }
      openView(current.value)
      load().catch(() => {}) // 后台静默刷新列表状态，不阻塞结果页
    } else {
      closeWorkspace()
      await load()
    }
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
  releaseSubmitPreviews()
}

// 已提交附件（兼容旧的单附件字段 attachment）
const submittedAttachments = computed(() => {
  const list = []
  if (viewData.value?.attachment) {
    list.push({ name: fileNameFromUrl(viewData.value.attachment), url: viewData.value.attachment, size: 0 })
  }
  ;(viewData.value?.attachments || []).forEach((f) => list.push(f))
  return list
})
const submittedImageUrls = computed(() => submittedAttachments.value.filter((f) => isImageFile(f.name)).map((f) => f.url))

function formatAnswer(answer, snapshot) {
  if (!answer) return ''
  const options = snapshot?.options || []
  // 选择题：选项字母附带选项内容，避免只显示 A/B/C/D 造成困惑（与正确答案展示一致）
  const label = (key) => {
    const opt = options.find((o) => o.key === key)
    return opt ? `${key}. ${opt.text}` : String(key)
  }
  if (answer.key != null && String(answer.key) !== '') return label(answer.key)
  if (Array.isArray(answer.keys)) return answer.keys.length ? answer.keys.map(label).join('、') : ''
  if (Array.isArray(answer.blanks)) {
    const filled = answer.blanks.map((b) => String(b ?? '').trim()).filter((b) => b !== '')
    return filled.length ? filled.join('；') : ''
  }
  if (answer.text != null && String(answer.text).trim() !== '') return String(answer.text)
  return ''
}
// 简答题无唯一标准答案：展示为「参考答案」（取自题目自身的 answer 字段，教师在题目编辑中维护）
function answerLabel(item) {
  return item?.snapshot?.qtype === 'short' ? '参考答案' : '正确答案'
}

watch(fixedCourseId, () => {
  closeWorkspace()
  load()
})

onMounted(load)
onBeforeUnmount(() => {
  releaseSubmitPreviews()
})
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
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
}
.student-status.muted {
  color: #64748b;
  background: #f1f5f9;
  box-shadow: inset 0 0 0 1px #e2e8f0;
}
.student-status.warn {
  color: #d97706;
  background: #fff7ed;
  box-shadow: inset 0 0 0 1px #fde68a;
}
.student-status.success {
  color: #16a34a;
  background: #f0fdf4;
  box-shadow: inset 0 0 0 1px #bbf7d0;
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px 20px;
  flex-wrap: wrap;
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
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid rgba(219, 229, 242, 0.9);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.85);
  color: #475569;
  font-size: 12.5px;
  font-weight: 600;
}

.meta-chip .el-icon {
  color: var(--primary-600);
  font-size: 14px;
}

.meta-chip-label {
  color: #94a3b8;
  font-weight: 600;
}

.meta-chip.score {
  border-color: rgba(96, 165, 250, 0.3);
  background: var(--primary-50);
  color: var(--primary-600);
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

/* PDF 滚动预览（无工具栏，师生端同一组件）挂载点 */
.resource-preview {
  margin-top: 14px;
}

.resource-file-list {
  margin-top: 14px;
  display: grid;
  gap: 10px;
}

.resource-file-list .resource-file {
  margin-top: 0;
}

.resource-file-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: auto;
}

/* 附件 PDF 作业：左资料右作答分栏 */
.submit-cols {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, 1fr);
  gap: 4px 20px;
  align-items: stretch;
}

.submit-cols .assignment-resource {
  display: flex;
  flex-direction: column;
}

.submit-cols .resource-preview {
  flex: 1;
}

.submit-cols .attachment-answer {
  display: flex;
  flex-direction: column;
  margin-top: 20px;
}

.submit-cols .workspace-footer {
  grid-column: 1 / -1;
}

@media (max-width: 1100px) {
  .submit-cols {
    grid-template-columns: minmax(0, 1fr);
  }
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

/* 题型徽章：与序号/分值同一视觉体系，按题型着色 */
.question-type-tag {
  height: 22px;
  margin-top: 3px;
  padding: 0 8px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  font-size: 11.5px;
  font-weight: 800;
  white-space: nowrap;
}
.question-type-tag.qt-single { color: #2563eb; background: #eff6ff; }
.question-type-tag.qt-multi { color: #7c3aed; background: #f5f3ff; }
.question-type-tag.qt-judge { color: #059669; background: #ecfdf5; }
.question-type-tag.qt-blank { color: #d97706; background: #fffbeb; }
.question-type-tag.qt-short { color: #475569; background: #f1f5f9; }

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
}

/* 作答输入卡：文本域 + 底部附件工具行合并为一张卡 */
.answer-dock {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 12px 14px 10px;
  border: 1px solid #dbe5f2;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.07);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.answer-dock:focus-within {
  border-color: var(--primary-500);
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.1), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.answer-dock-textarea {
  flex: 1;
  display: flex;
}

.answer-dock-textarea :deep(.el-textarea__inner) {
  flex: 1;
  height: 100%;
  min-height: 240px;
  padding: 4px 6px;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  font-size: 14px;
  line-height: 1.75;
}

.answer-dock-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--gray-200);
}

.upload-info {
  min-width: 0;
}

.upload-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.upload-btn {
  border-radius: 10px;
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

/* ---- 学生提交：多附件（图片预览 + 大小统计） ---- */
.submit-file-list {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}
.submit-file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}
.submit-file-thumb {
  flex: none;
  width: 52px;
  height: 52px;
  border-radius: 8px;
  background: #e2e8f0;
  cursor: zoom-in;
}
.submit-file-icon {
  flex: none;
  width: 52px;
  height: 52px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #64748b;
  background: #eef2f7;
  font-size: 22px;
}
.submit-file-info { flex: 1; min-width: 0; }
.submit-file-name {
  color: #1e293b;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.submit-file-meta { margin-top: 2px; color: #94a3b8; font-size: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.submit-file-status.is-uploading { color: #2563eb; font-weight: 700; }
.submit-file-status.is-success { color: #16a34a; font-weight: 700; }
.submit-file-status.is-error { color: #dc2626; font-weight: 700; }
.submit-file-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.submit-progress-track {
  height: 6px;
  margin-top: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.submit-progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  transition: width 0.2s ease;
}
.submit-file-error { margin-top: 4px; color: #dc2626; font-size: 12px; }
.submit-file-summary {
  padding: 2px 4px;
  color: #94a3b8;
  font-size: 12px;
}

/* ---- 查看结果：正确答案/解析/对错 ---- */
.correct-answer { color: #059669; font-weight: 700; }
.answer-analysis { color: #64748b; font-size: 13px; line-height: 1.6; }
.result-score-row { display: flex; gap: 8px; }
/* 逐题老师评语（成绩发布后随答案一并放行） */
.answer-comment {
  margin-top: 2px;
  padding: 6px 10px;
  border-left: 3px solid #93c5fd;
  border-radius: 6px;
  background: #f0f7ff;
  color: #1e40af;
  font-size: 13px;
  line-height: 1.6;
}

/* ---- 查看结果：已提交附件预览 ---- */
.submitted-attachments { margin-top: 14px; }
.submitted-attachment-list {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.submitted-attachment-thumb {
  width: 112px;
  height: 84px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f1f5f9;
  cursor: zoom-in;
}
.submitted-attachment-file {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 260px;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  color: #334155;
  background: #f8fafc;
  font-size: 13px;
  text-decoration: none;
}
.submitted-attachment-file:hover { border-color: #93c5fd; background: #eff6ff; }
.submitted-attachment-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.submitted-attachment-file small { color: #94a3b8; }
</style>
