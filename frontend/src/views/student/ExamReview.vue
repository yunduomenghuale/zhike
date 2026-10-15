<template>
  <div class="page-container exam-review-page">
    <!-- 常驻返回栏：课程空间内 page-header 被 CourseWorkspaceShell 隐藏、全局入口滚动后头部也会移出视口，
         故返回入口独立常驻（sticky），不依赖 page-header -->
    <div class="page-back-bar">
      <el-button :icon="ArrowLeft" @click="goBack">返回考试列表</el-button>
      <span class="page-back-title">答题情况<template v-if="examName"> · {{ examName }}</template></span>
    </div>

    <div class="page-header">
      <div>
        <div class="page-title">答题情况</div>
        <div class="page-subtitle">{{ examName }}</div>
      </div>
    </div>

    <div v-loading="loading">
      <el-empty v-if="!loading && !review" :description="emptyText">
        <template #description>
          <div class="empty-text">{{ emptyText }}</div>
          <div class="empty-tip">完成考试并交卷后，可在此查看答案、解析与得分</div>
        </template>
      </el-empty>

      <template v-else-if="review">
        <!-- 成绩摘要 -->
        <el-card class="score-card" shadow="never">
          <div class="score-main">
            <div class="score-block">
              <div class="score-value primary">{{ review.submission?.objective_score ?? '-' }}</div>
              <div class="score-label">客观题得分</div>
            </div>
            <div class="score-block">
              <div class="score-value" :class="{ pending: review.submission?.total_score == null }">
                {{ review.submission?.total_score ?? '待批阅' }}
              </div>
              <div class="score-label">总分</div>
            </div>
            <div class="score-block">
              <div class="score-value small">
                {{ subjectiveProgress }}
              </div>
              <div class="score-label">主观题批阅</div>
            </div>
          </div>
          <div class="score-tips">
            <span>交卷时间：{{ fmtTime(review.submission?.submitted_at) }}</span>
            <span v-if="review.submission?.abnormal" class="abnormal">本场考试存在异常行为记录</span>
            <span v-if="review.options_shuffled" class="shuffle-tip">
              本场考试开启了选项乱序，回看按原题顺序展示，与考试时所见顺序可能不同
            </span>
            <span v-if="review.submission?.total_score == null && hasSubjective" class="pending-text">
              主观题待教师批阅后出分
            </span>
            <span v-else-if="review.score_released" class="released-text">成绩已发布</span>
          </div>
        </el-card>

        <!-- 逐题回看 -->
        <el-card
          v-for="(q, i) in review.questions"
          :key="q.question_id"
          class="q-card"
          shadow="never"
        >
          <div class="q-stem">
            <span class="q-index">{{ i + 1 }}.</span>
            <el-tag size="small" effect="light" class="q-type">{{ q.qtype_display }}</el-tag>
            <span>{{ q.stem }}</span>
            <span class="q-score">（{{ q.score }} 分）</span>
          </div>

          <div v-if="q.options?.length" class="q-options">
            <div
              v-for="opt in q.options"
              :key="opt.key"
              class="q-opt"
              :class="optClass(q, opt.key)"
            >
              <span class="opt-key">{{ opt.key }}.</span>
              <span>{{ opt.text }}</span>
              <el-tag v-if="isCorrectOption(q, opt.key)" type="success" size="small" effect="plain" round>正确答案</el-tag>
              <el-tag v-else-if="isMyOption(q, opt.key)" type="danger" size="small" effect="plain" round>你的选择</el-tag>
            </div>
          </div>

          <div class="review-line">
            你的答案：<span class="answer">{{ fmtAnswer(q.student_answer, q.blank_count) }}</span>
          </div>
          <div class="review-line correct">
            正确答案：<span>{{ fmtAnswer(q.correct_answer, q.blank_count) }}</span>
          </div>
          <div class="review-line">
            本题得分：
            <span v-if="q.pending" class="pending">待教师批阅</span>
            <span v-else class="answer">{{ q.my_score ?? '-' }} / {{ q.score }} 分</span>
          </div>
          <div v-if="q.analysis" class="review-line analysis">解析：{{ q.analysis }}</div>
        </el-card>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { listExamSubmissions, reviewExam } from '@/api/exam'
import { blankItems } from '@/utils/blank-answer'

const route = useRoute()
const router = useRouter()
// 两种入口共用本页：课程空间内嵌路由 /student/courses/:id/exams/:examId/review
// 与全局路由 /student/exams/:id/review
const examId = Number(route.params.examId || route.params.id)
// 课程空间入口时保留课程 id，供返回按钮回到课程内考试列表
const courseId = computed(() => {
  const m = route.path.match(/^\/student\/courses\/(\d+)\/exams\//)
  return m ? Number(m[1]) : null
})

function goBack() {
  if (courseId.value) {
    router.push(`/student/courses/${courseId.value}/exams`)
  } else {
    router.push('/student/exams')
  }
}

const loading = ref(true)
const review = ref(null)
const examName = ref('在线考试')
const emptyText = ref('暂无答卷记录')

const hasSubjective = computed(() =>
  (review.value?.questions || []).some((q) => !q.is_objective),
)

const subjectiveProgress = computed(() => {
  const list = (review.value?.questions || []).filter((q) => !q.is_objective)
  if (!list.length) return '无主观题'
  const graded = list.filter((q) => !q.pending).length
  return `${graded} / ${list.length} 题`
})

async function init() {
  loading.value = true
  try {
    const data = await listExamSubmissions({ exam: examId })
    const list = data.results ?? data
    const sub = (list || []).find((s) => String(s.exam) === String(examId)) || list?.[0]
    if (!sub) {
      emptyText.value = '你还没有参加这场考试'
      return
    }
    if (!['submitted', 'timeout'].includes(sub.status)) {
      emptyText.value = '考试尚未交卷，交卷后可查看答题情况'
      return
    }
    review.value = await reviewExam(sub.id)
    examName.value = review.value?.submission?.exam_name || '在线考试'
  } catch {
    review.value = null
    emptyText.value = '答卷加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function fmtTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtAnswer(a, blankCount) {
  if (!a) return '（未作答）'
  if (a.blanks) {
    // 学生答案为字符串数组、正确答案可能为按空赋分对象数组，统一走 blankItems 取文本
    const filled = blankItems(a).map((it) => it.text.trim()).filter((b) => b !== '')
    if (!filled.length) return '（未作答）'
    return filled.map((b, i) => `第 ${i + 1} 空：${b}`).join('；')
  }
  if (a.key != null && String(a.key) !== '') return String(a.key)
  if (a.keys?.length) return a.keys.join('、')
  if (a.text != null && String(a.text).trim() !== '') return String(a.text)
  return '（未作答）'
}

function isCorrectOption(q, key) {
  const c = q.correct_answer || {}
  return String(c.key ?? '') === String(key) || (c.keys || []).map(String).includes(String(key))
}

function isMyOption(q, key) {
  const m = q.student_answer || {}
  return String(m.key ?? '') === String(key) || (m.keys || []).map(String).includes(String(key))
}

function optClass(q, key) {
  if (isCorrectOption(q, key)) return 'opt-right'
  if (isMyOption(q, key)) return 'opt-wrong'
  return ''
}

onMounted(init)
</script>

<style scoped>
.exam-review-page {
  padding-bottom: 40px;
}
/* 常驻返回栏（sticky：课程空间头部被隐藏/全局滚动后仍可返回） */
.page-back-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.08);
}
.page-back-title {
  font-size: 14px;
  font-weight: 700;
  color: #334155;
}
.score-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.score-main {
  display: flex;
  gap: 48px;
  flex-wrap: wrap;
}
.score-block {
  text-align: center;
}
.score-value {
  font-size: 30px;
  font-weight: 800;
  color: #059669;
}
.score-value.primary {
  color: #2563eb;
}
.score-value.pending {
  font-size: 22px;
  color: #d97706;
}
.score-value.small {
  font-size: 22px;
  color: #475569;
}
.score-label {
  margin-top: 4px;
  font-size: 12.5px;
  color: #64748b;
}
.score-tips {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
  font-size: 12.5px;
  color: #64748b;
}
.score-tips .abnormal {
  color: #dc2626;
  font-weight: 600;
}
.score-tips .pending-text {
  color: #d97706;
  font-weight: 600;
}
.score-tips .released-text {
  color: #059669;
  font-weight: 600;
}
.score-tips .shuffle-tip {
  color: #64748b;
  font-style: italic;
}
.q-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.q-stem {
  margin-bottom: 14px;
  line-height: 1.7;
  font-size: 15px;
  color: #1e293b;
}
.q-index {
  font-weight: 700;
  margin-right: 6px;
}
.q-type {
  margin-right: 8px;
  font-weight: 500;
}
.q-score {
  color: #64748b;
  font-size: 13px;
  margin-left: 6px;
}
.q-options {
  margin-bottom: 6px;
}
.q-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 14px;
  color: #334155;
}
.q-opt.opt-right {
  background: #ecfdf5;
  color: #047857;
}
.q-opt.opt-wrong {
  background: #fef2f2;
  color: #b91c1c;
}
.opt-key {
  font-weight: 700;
}
.review-line {
  margin-top: 8px;
  font-size: 14px;
  color: #475569;
}
.review-line .answer {
  font-weight: 600;
  color: #1e293b;
}
.review-line.correct {
  color: #059669;
  font-weight: 500;
}
.review-line .pending {
  color: #d97706;
  font-weight: 600;
}
.review-line.analysis {
  color: #64748b;
  background: #f8fafc;
  padding: 10px 12px;
  border-radius: 8px;
  margin-top: 10px;
}
.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}
.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}
</style>
