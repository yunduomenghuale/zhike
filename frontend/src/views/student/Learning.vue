<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">课程学习</div>
        <div class="page-subtitle">按章节学习课件与讲解，并完成章节练习</div>
      </div>
      <el-select v-model="courseId" placeholder="选择课程" style="width: 240px" @change="loadTree">
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <el-empty v-if="!courseId" description="请先选择课程（需先加入班级）" />

    <el-row v-else :gutter="20">
      <!-- 章节目录 -->
      <el-col :xs="24" :lg="6">
        <el-card shadow="never" class="catalog-card">
          <template #header><div class="card-h"><el-icon><Files /></el-icon> 章节目录</div></template>
          <el-tree
            :data="tree"
            node-key="id"
            default-expand-all
            :expand-on-click-node="false"
            highlight-current
            @node-click="onSelect"
          >
            <template #default="{ data }">
              <span :class="{ 'is-section': data.parent }">{{ data.title }}</span>
            </template>
          </el-tree>
          <el-empty v-if="!tree.length" description="暂无已发布章节" :image-size="60" />
        </el-card>
      </el-col>

      <!-- 学习内容 -->
      <el-col :xs="24" :lg="18">
        <el-empty v-if="!current" description="请选择左侧章节开始学习" />
        <el-card v-else shadow="never">
          <template #header>
            <div class="content-head">
              <span class="chapter-name">{{ current.title }}</span>
              <el-radio-group v-model="tab" size="small">
                <el-radio-button value="learn">课件学习</el-radio-button>
                <el-radio-button value="practice">章节练习</el-radio-button>
              </el-radio-group>
            </div>
          </template>

          <!-- 课件学习 -->
          <div v-show="tab === 'learn'" v-loading="learnLoading">
            <template v-if="pages.length">
              <div class="slide">
                <img
                  v-if="pages[pageIdx].image || pages[pageIdx].image_url"
                  class="slide-image"
                  :src="pages[pageIdx].image || pages[pageIdx].image_url"
                  :alt="pages[pageIdx].title || `第 ${pageIdx + 1} 页`"
                />
                <template v-else>
                  <div class="slide-title">{{ pages[pageIdx].title || `第 ${pageIdx + 1} 页` }}</div>
                  <div class="slide-body">{{ pages[pageIdx].body || '（本页无文本内容）' }}</div>
                </template>
              </div>
              <div class="full-lecture">
                <div class="full-lecture-head">
                  <div>
                    <div class="full-lecture-title">完整讲解</div>
                    <div class="full-lecture-subtitle">
                      {{ hasAudio ? `已配音 ${audioPageCount}/${pages.length} 页，可连续播放` : '老师还没有生成配音' }}
                    </div>
                  </div>
                  <el-button
                    v-if="hasAudio"
                    type="primary"
                    :icon="VideoPlay"
                    @click="toggleContinuous"
                  >
                    {{ continuousPlay ? '停止播放' : '开始播放' }}
                  </el-button>
                </div>
                <audio
                  v-if="audioOf(pages[pageIdx])"
                  ref="audioRef"
                  :key="pageIdx"
                  :src="audioOf(pages[pageIdx])"
                  controls
                  :autoplay="continuousPlay"
                  class="script-audio"
                  @ended="onAudioEnded"
                />
                <div v-else class="full-lecture-missing">当前页没有配音，连续播放时会自动跳到下一页有配音的页面。</div>
              </div>
              <div v-if="scriptOf(pages[pageIdx])" class="script">
                <div class="script-label">
                  <span><el-icon><Microphone /></el-icon> 当前页讲解稿</span>
                </div>
                <div class="script-text">{{ scriptOf(pages[pageIdx]) }}</div>
              </div>
              <div class="slide-bar">
                <el-button :icon="ArrowLeft" :disabled="pageIdx === 0" @click="pageIdx--">上一页</el-button>
                <span class="page-ind">{{ pageIdx + 1 }} / {{ pages.length }}</span>
                <el-button :disabled="pageIdx === pages.length - 1" @click="pageIdx++">
                  下一页<el-icon class="el-icon--right"><ArrowRight /></el-icon>
                </el-button>
              </div>
            </template>
            <el-empty v-else description="该章节暂无课件（老师尚未上传 PPT）" />
          </div>

          <!-- 章节练习 -->
          <div v-show="tab === 'practice'" v-loading="practiceLoading">
            <template v-if="questions.length">
              <el-card v-for="(q, i) in questions" :key="q.id" class="q-card" shadow="never">
                <div class="q-stem">
                  <span class="q-idx">{{ i + 1 }}.</span>
                  <el-tag size="small" effect="light">{{ q.qtype_display }}</el-tag>
                  <span>{{ q.stem }}</span>
                </div>
                <el-radio-group v-if="q.qtype === 'single' || q.qtype === 'judge'" v-model="answers[q.id]" :disabled="submitted">
                  <el-radio v-for="o in q.options" :key="o.key" :value="o.key" class="opt">{{ o.key }}. {{ o.text }}</el-radio>
                </el-radio-group>
                <el-checkbox-group v-else-if="q.qtype === 'multi'" v-model="answers[q.id]" :disabled="submitted">
                  <el-checkbox v-for="o in q.options" :key="o.key" :value="o.key" class="opt">{{ o.key }}. {{ o.text }}</el-checkbox>
                </el-checkbox-group>
                <el-input v-else-if="q.qtype === 'blank'" v-model="answers[q.id][0]" :disabled="submitted" style="max-width: 320px" placeholder="填写答案" />
                <el-input v-else v-model="answers[q.id]" type="textarea" :rows="3" :disabled="submitted" placeholder="作答（主观题不自动评分）" />

                <!-- 提交后反馈 -->
                <div v-if="feedback[q.id]" class="fb" :class="feedback[q.id].is_correct ? 'ok' : 'no'">
                  <el-icon><CircleCheck v-if="feedback[q.id].is_correct" /><CircleClose v-else /></el-icon>
                  {{ feedback[q.id].is_correct ? '回答正确' : '回答错误' }} · 正确答案：{{ fmt(feedback[q.id].correct_answer) }}
                  <div v-if="feedback[q.id].analysis" class="fb-ana">解析：{{ feedback[q.id].analysis }}</div>
                </div>
              </el-card>

              <div class="practice-bar">
                <el-button v-if="!submitted" type="primary" :loading="submitting" @click="submitPractice">提交练习</el-button>
                <template v-else>
                  <el-tag type="success" size="large">得分 {{ result.correct }} / {{ result.total }}</el-tag>
                  <el-button @click="resetPractice">重做</el-button>
                </template>
              </div>
            </template>
            <el-empty v-else description="该章节暂无练习题" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Files, Microphone, ArrowLeft, ArrowRight, CircleCheck, CircleClose, VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listClasses } from '@/api/classroom'
import { listCatalogs, listPpts, listVideos } from '@/api/course'
import { listQuestions, practiceSubmit } from '@/api/question'

const courses = ref([])
const courseId = ref(null)
const tree = ref([])
const current = ref(null)
const tab = ref('learn')

async function loadCourses() {
  const data = await listClasses()
  const rows = data.results ?? data
  const map = new Map()
  rows.forEach((row) => {
    const ids = row.courses?.length ? row.courses : [row.course]
    ids.filter(Boolean).forEach((id, index) => {
      map.set(id, { id, name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
    })
  })
  courses.value = [...map.values()]
  if (courses.value.length) {
    courseId.value = courses.value[0].id
    loadTree()
  }
}

async function loadTree() {
  current.value = null
  const data = await listCatalogs({ course: courseId.value, tree: 1 })
  tree.value = data.results ?? data
}

function onSelect(node) {
  current.value = node
  tab.value = 'learn'
  loadLearn()
  loadPractice()
}

// ---- 课件学习 ----
const learnLoading = ref(false)
const pages = ref([])
const scripts = ref([])
const pageIdx = ref(0)
const continuousPlay = ref(false)
const audioRef = ref(null)
const hasAudio = computed(() => scripts.value.some((s) => s.audio_url))
const audioPageCount = computed(() => scripts.value.filter((s) => s.audio_url).length)
function scriptOf(page) {
  return scripts.value.find((s) => s.page === page.page)?.script || ''
}
function audioOf(page) {
  return scripts.value.find((s) => s.page === page.page)?.audio_url || ''
}
async function loadLearn() {
  learnLoading.value = true
  pages.value = []
  scripts.value = []
  pageIdx.value = 0
  try {
    const ppt = await listPpts({ catalog: current.value.id })
    const pptList = ppt.results ?? ppt
    const active = pptList.find((p) => p.is_active) || pptList[0]
    pages.value = active?.parsed_pages || []
    const vid = await listVideos({ catalog: current.value.id })
    const vids = vid.results ?? vid
    scripts.value = vids[0]?.scripts || []
  } finally {
    learnLoading.value = false
  }
}

function toggleContinuous() {
  continuousPlay.value = !continuousPlay.value
  if (!continuousPlay.value) {
    audioRef.value?.pause?.()
    return
  }
  if (!audioOf(pages.value[pageIdx.value])) {
    const next = findNextAudioPage(pageIdx.value - 1)
    if (next >= 0) pageIdx.value = next
  }
  setTimeout(() => audioRef.value?.play?.(), 0)
}

function onAudioEnded() {
  if (!continuousPlay.value) return
  const next = findNextAudioPage(pageIdx.value)
  if (next >= 0) {
    pageIdx.value = next
  } else {
    continuousPlay.value = false
  }
}

function findNextAudioPage(startIndex) {
  for (let i = startIndex + 1; i < pages.value.length; i += 1) {
    if (audioOf(pages.value[i])) return i
  }
  return -1
}

// ---- 章节练习 ----
const practiceLoading = ref(false)
const questions = ref([])
const answers = reactive({})
const feedback = reactive({})
const submitted = ref(false)
const submitting = ref(false)
const result = reactive({ total: 0, correct: 0 })

async function loadPractice() {
  practiceLoading.value = true
  resetState()
  try {
    const data = await listQuestions({ course: courseId.value, catalog: current.value.id, status: 'published' })
    questions.value = data.results ?? data
    questions.value.forEach((q) => {
      answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? [''] : ''
    })
  } finally {
    practiceLoading.value = false
  }
}
function resetState() {
  Object.keys(answers).forEach((k) => delete answers[k])
  Object.keys(feedback).forEach((k) => delete feedback[k])
  submitted.value = false
}
function resetPractice() {
  questions.value.forEach((q) => {
    answers[q.id] = q.qtype === 'multi' ? [] : q.qtype === 'blank' ? [''] : ''
  })
  Object.keys(feedback).forEach((k) => delete feedback[k])
  submitted.value = false
}
function buildAns(q) {
  const v = answers[q.id]
  if (q.qtype === 'multi') return { keys: v }
  if (q.qtype === 'blank') return { blanks: v }
  if (q.qtype === 'short') return { text: v }
  return { key: v }
}
function fmt(a) {
  if (!a) return '-'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  return '-'
}
async function submitPractice() {
  const payload = {}
  questions.value.forEach((q) => { payload[q.id] = buildAns(q) })
  submitting.value = true
  try {
    const res = await practiceSubmit({ answers: payload })
    res.results.forEach((r) => { feedback[r.question_id] = r })
    result.total = res.total
    result.correct = res.correct
    submitted.value = true
    ElMessage.success(`提交完成，答对 ${res.correct}/${res.total}`)
  } finally {
    submitting.value = false
  }
}

onMounted(loadCourses)
</script>

<style scoped>
.card-h {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.catalog-card :deep(.is-section) {
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.chapter-name {
  font-weight: 600;
  font-size: 15px;
}
.slide {
  background: linear-gradient(135deg, #f8fafc, #eef2ff);
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  padding: 32px;
  min-height: 260px;
}
.slide-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
  text-align: center;
}
.slide-body {
  white-space: pre-wrap;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.slide-image {
  display: block;
  width: 100%;
  max-height: 640px;
  object-fit: contain;
  border-radius: 8px;
  background: #fff;
}
.full-lecture {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: #fff;
}
.full-lecture-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.full-lecture-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.full-lecture-subtitle,
.full-lecture-missing {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.script {
  margin-top: 14px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
  padding: 14px 16px;
}
.script-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 13px;
  color: var(--el-color-primary);
  margin-bottom: 6px;
}

.script-label span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.script-audio {
  width: 100%;
  height: 38px;
  margin-bottom: 10px;
}
.script-text {
  line-height: 1.8;
  color: var(--el-text-color-regular);
}
.slide-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  margin-top: 18px;
}
.page-ind {
  color: var(--el-text-color-secondary);
}
.q-card {
  margin-bottom: 14px;
}
.q-stem {
  margin-bottom: 12px;
}
.q-idx {
  font-weight: 700;
  margin-right: 6px;
}
.opt {
  display: block;
  margin: 6px 0;
}
.fb {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
}
.fb.ok {
  background: #f0f9eb;
  color: #67c23a;
}
.fb.no {
  background: #fef0f0;
  color: #f56c6c;
}
.fb-ana {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.practice-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
}
</style>
