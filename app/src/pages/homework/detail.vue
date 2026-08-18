<template>
  <view class="page">
    <view v-if="loading" class="tip">加载中…</view>
    <template v-else-if="hw">
      <!-- 作业信息 -->
      <view class="card">
        <view class="title">{{ hw.title }}</view>
        <view class="meta">
          <text class="chip">{{ hw.mode === 'questions' ? '题库作业' : '附件/文本' }}</text>
          <text class="chip">总分 {{ hw.total_score }} 分</text>
          <text v-if="isLate" class="chip late">已逾期</text>
        </view>
        <view v-if="hw.description" class="desc">{{ hw.description }}</view>
        <view class="time-row">开始：{{ formatTime(hw.start_time) }}</view>
        <view class="time-row">截止：{{ formatTime(hw.deadline) }}</view>
        <view v-if="hw.attachment" class="attach" @click="openAttachment(hw.attachment)">
          📎 {{ attachmentName(hw.attachment) }}（点击复制链接）
        </view>
      </view>

      <!-- 已提交：查看我的提交 -->
      <template v-if="submission">
        <view class="card">
          <view class="section-label">我的提交</view>
          <view class="time-row">提交时间：{{ formatTime(submission.submitted_at) }}</view>

          <!-- 成绩区（发布后可见） -->
          <view v-if="submission.correct_status === 'returned'" class="score-box">
            <view class="score-num">{{ submission.score ?? '-' }} 分</view>
            <view v-if="submission.objective_score != null" class="score-sub">
              客观题得分 {{ submission.objective_score }} 分
            </view>
            <view v-if="submission.comment" class="comment">老师评语：{{ submission.comment }}</view>
          </view>
          <view v-else class="score-pending">
            {{ submission.correct_status === 'graded' ? '老师已批改完成，成绩发布后可见得分与评语' : '已提交，等待老师批改' }}
          </view>

          <view v-if="submission.content" class="desc">{{ submission.content }}</view>
          <view v-if="submission.attachment" class="attach" @click="openAttachment(submission.attachment)">
            📎 我的附件：{{ attachmentName(submission.attachment) }}
          </view>
        </view>

        <!-- 题库作业：逐题作答与批改结果 -->
        <view v-for="(item, i) in submission.answer_items || []" :key="item.id" class="card q-card">
          <view class="q-stem">
            <text class="q-idx">{{ i + 1 }}.</text>
            <text class="chip">{{ item.snapshot?.qtype_display }}</text>
            <text>{{ item.snapshot?.stem }}</text>
          </view>
          <view class="q-answer">我的答案：{{ fmtAnswer(item.student_answer) }}</view>
          <template v-if="submission.correct_status === 'returned'">
            <view class="fb" :class="item.is_correct === null ? '' : item.is_correct ? 'ok' : 'no'">
              <template v-if="item.is_correct === null">主观题，得分：{{ item.score ?? '待批' }} 分</template>
              <template v-else>{{ item.is_correct ? '回答正确' : '回答错误' }}，得分：{{ item.score ?? 0 }} 分</template>
              <view v-if="item.comment" class="fb-ana">评语：{{ item.comment }}</view>
            </view>
          </template>
        </view>
      </template>

      <!-- 未提交：作答区 -->
      <template v-else>
        <view v-if="!isStudent" class="tip">当前账号仅供预览，学生账号可提交作业</view>
        <view v-else-if="!started" class="tip">作业尚未开始</view>
        <template v-else>
          <!-- 题库模式 -->
          <template v-if="hw.mode === 'questions'">
            <view v-for="(item, i) in hw.questions || []" :key="item.id" class="card q-card">
              <view class="q-stem">
                <text class="q-idx">{{ i + 1 }}.</text>
                <text class="chip">{{ item.snapshot?.qtype_display }}</text>
                <text>{{ item.snapshot?.stem }}</text>
                <text class="q-score">（{{ item.score }} 分）</text>
              </view>

              <!-- 单选 / 判断 -->
              <view v-if="['single', 'judge'].includes(item.snapshot?.qtype)" class="opts">
                <view
                  v-for="opt in item.snapshot?.options || []"
                  :key="opt.key"
                  class="opt"
                  :class="{ active: answers[item.id]?.key === opt.key }"
                  @click="answers[item.id] = { key: opt.key }"
                >
                  <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
                </view>
              </view>

              <!-- 多选 -->
              <view v-else-if="item.snapshot?.qtype === 'multi'" class="opts">
                <view
                  v-for="opt in item.snapshot?.options || []"
                  :key="opt.key"
                  class="opt"
                  :class="{ active: answers[item.id]?.keys?.includes(opt.key) }"
                  @click="toggleMulti(item.id, opt.key)"
                >
                  <text class="opt-key">{{ opt.key }}.</text> {{ opt.text }}
                </view>
              </view>

              <!-- 填空 -->
              <view v-else-if="item.snapshot?.qtype === 'blank'" class="blanks">
                <input
                  v-for="(_, bi) in answers[item.id]?.blanks || []"
                  :key="bi"
                  v-model="answers[item.id].blanks[bi]"
                  class="blank-input"
                  :placeholder="`第 ${bi + 1} 空`"
                  placeholder-class="ph"
                />
              </view>

              <!-- 简答 -->
              <textarea
                v-else
                v-model="answers[item.id].text"
                class="textarea"
                placeholder="请作答"
                placeholder-class="ph"
              />
            </view>
          </template>

          <!-- 附件/文本模式 -->
          <view v-else class="card">
            <view class="section-label">作答内容</view>
            <textarea
              v-model="content"
              class="textarea"
              placeholder="请输入作业内容（或上传附件图片）"
              placeholder-class="ph"
            />
            <view class="upload-row">
              <button class="upload-btn" @click="pickImage">📷 添加附件图片</button>
              <view v-if="filePath" class="file-name">
                {{ fileName }}
                <text class="file-del" @click="filePath = ''">✕</text>
              </view>
            </view>
          </view>

          <button class="submit-btn" :disabled="submitting" :loading="submitting" @click="doSubmit">
            提交作业{{ hw.mode === 'questions' ? `（${answeredCount}/${questionTotal}）` : '' }}
          </button>
        </template>
      </template>
    </template>
    <view v-else class="tip">作业不存在或已删除</view>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get } from '@/utils/request.js'
import { listSubmissions, submitHomework, submitHomeworkWithFile } from '@/api/homework.js'
import { mediaURL } from '@/config.js'

const hwId = ref(null)
const hw = ref(null)
const submission = ref(null)
const loading = ref(false)
const submitting = ref(false)
const content = ref('')
const answers = ref({})
const filePath = ref('')
const fileName = ref('')

// 提交接口仅学生可用（IsStudent）；教师角色不加载提交记录
// （教师视角的 submissions 是全班学生的，直接取 [0] 会串数据）
const isStudent = uni.getStorageSync('user')?.role === 'student'

onLoad((q) => {
  hwId.value = Number(q.id) || null
  load()
})

async function load() {
  if (!hwId.value) return
  loading.value = true
  try {
    const [detail, subs] = await Promise.all([
      get(`/homeworks/${hwId.value}/`),
      isStudent ? listSubmissions({ homework: hwId.value }) : Promise.resolve([]),
    ])
    hw.value = detail
    submission.value = isStudent ? (subs.results ?? subs)[0] || null : null
    if (!submission.value && detail.mode === 'questions') {
      const init = {}
      ;(detail.questions || []).forEach((item) => { init[item.id] = initialAnswer(item) })
      answers.value = init
    }
  } catch {
    hw.value = null
  } finally {
    loading.value = false
  }
}

const started = computed(() =>
  !hw.value?.start_time || new Date(hw.value.start_time).getTime() <= Date.now(),
)
const isLate = computed(() =>
  hw.value?.deadline && new Date(hw.value.deadline).getTime() < Date.now(),
)

const questionTotal = computed(() => hw.value?.questions?.length || 0)
const answeredCount = computed(() => (hw.value?.questions || []).filter((item) => {
  const a = answers.value[item.id] || {}
  const qtype = item.snapshot?.qtype
  if (qtype === 'multi') return Boolean(a.keys?.length)
  if (qtype === 'blank') return Boolean(a.blanks?.length) && a.blanks.every((v) => String(v || '').trim())
  if (qtype === 'short') return Boolean(String(a.text || '').trim())
  return Boolean(String(a.key || '').trim())
}).length)

function initialAnswer(item) {
  const snap = item.snapshot || {}
  if (snap.qtype === 'multi') return { keys: [] }
  if (snap.qtype === 'blank') {
    const count = Math.max(
      1,
      snap.answer_blank_count || (snap.stem?.match(/_{2,}|（\s*）|\(\s*\)/g) || []).length,
    )
    return { blanks: Array.from({ length: count }, () => '') }
  }
  if (snap.qtype === 'short') return { text: '' }
  return { key: '' }
}

function toggleMulti(id, key) {
  const a = answers.value[id] || { keys: [] }
  const keys = a.keys.includes(key)
    ? a.keys.filter((k) => k !== key)
    : [...a.keys, key]
  answers.value = { ...answers.value, [id]: { keys } }
}

function fmtAnswer(answer) {
  if (!answer) return '（未作答）'
  if (answer.key != null) return String(answer.key)
  if (answer.keys) return answer.keys.join('、')
  if (answer.blanks) return answer.blanks.join(' / ')
  if (answer.text != null) return String(answer.text)
  return JSON.stringify(answer)
}

function formatTime(value) {
  if (!value) return '不限'
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function attachmentName(url) {
  const raw = String(url).split('/').pop()?.split('?')[0] || '附件'
  try { return decodeURIComponent(raw) } catch { return raw }
}

function openAttachment(url) {
  uni.setClipboardData({
    data: mediaURL(url),
    success: () => uni.showToast({ title: '链接已复制，请在浏览器打开', icon: 'none' }),
  })
}

function pickImage() {
  uni.chooseImage({
    count: 1,
    success: (res) => {
      filePath.value = res.tempFilePaths[0]
      fileName.value = res.tempFiles?.[0]?.name || '图片附件'
    },
  })
}

async function doSubmit() {
  if (!hw.value) return
  if (hw.value.mode === 'questions' && answeredCount.value < questionTotal.value) {
    uni.showToast({ title: `还有 ${questionTotal.value - answeredCount.value} 道题未作答`, icon: 'none' })
    return
  }
  if (hw.value.mode !== 'questions' && !content.value.trim() && !filePath.value) {
    uni.showToast({ title: '请输入作业内容或上传附件', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    if (hw.value.mode === 'questions') {
      await submitHomework({ homework: hw.value.id, answers: answers.value })
    } else if (filePath.value) {
      await submitHomeworkWithFile({
        homework: hw.value.id,
        content: content.value,
        filePath: filePath.value,
      })
    } else {
      await submitHomework({ homework: hw.value.id, content: content.value })
    }
    uni.showToast({ title: '提交成功', icon: 'success' })
    await load()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.page {
  padding: 28rpx;
}

.tip {
  padding: 100rpx 0;
  text-align: center;
  font-size: 26rpx;
  color: #94a3b8;
}

.card {
  margin-bottom: 20rpx;
  padding: 28rpx;
  border-radius: 20rpx;
  background: #ffffff;
  border: 1rpx solid #f1f5f9;
  box-shadow: 0 2rpx 6rpx rgba(15, 23, 42, 0.04);
}

.title {
  font-size: 32rpx;
  font-weight: 800;
  color: #0f172a;
}

.meta {
  display: flex;
  gap: 12rpx;
  margin-top: 14rpx;
}

.chip {
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  font-size: 22rpx;
}

.chip.late {
  background: #fef2f2;
  color: #ef4444;
}

.desc {
  margin-top: 18rpx;
  font-size: 26rpx;
  line-height: 1.8;
  color: #475569;
  white-space: pre-wrap;
}

.time-row {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: #94a3b8;
}

.attach {
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #2563eb;
}

.section-label {
  margin-bottom: 16rpx;
  font-size: 26rpx;
  font-weight: 700;
  color: #0f172a;
}

.score-box {
  margin-top: 18rpx;
  padding: 24rpx;
  border-radius: 18rpx;
  background: #ecfdf5;
}

.score-num {
  font-size: 40rpx;
  font-weight: 800;
  color: #10b981;
}

.score-sub {
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #10b981;
}

.comment {
  margin-top: 12rpx;
  font-size: 25rpx;
  line-height: 1.7;
  color: #334155;
}

.score-pending {
  margin-top: 18rpx;
  padding: 24rpx;
  border-radius: 18rpx;
  background: #fff7ed;
  font-size: 25rpx;
  color: #d97706;
}

.q-card {
  padding-bottom: 24rpx;
}

.q-stem {
  font-size: 27rpx;
  line-height: 1.8;
  color: #0f172a;
}

.q-idx {
  margin-right: 8rpx;
  font-weight: 700;
}

.q-score {
  font-size: 22rpx;
  color: #94a3b8;
}

.opts {
  margin-top: 18rpx;
}

.opt {
  margin-bottom: 14rpx;
  padding: 18rpx 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  color: #334155;
}

.opt.active {
  background: #eff6ff;
  border-color: #2563eb;
  color: #2563eb;
}

.opt-key {
  font-weight: 700;
}

.blanks {
  margin-top: 18rpx;
}

.blank-input {
  height: 76rpx;
  margin-bottom: 14rpx;
  padding: 0 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.textarea {
  width: 100%;
  min-height: 160rpx;
  margin-top: 14rpx;
  padding: 20rpx 24rpx;
  border-radius: 20rpx;
  background: #f1f5f9;
  border: 1rpx solid transparent;
  font-size: 26rpx;
  box-sizing: border-box;
}

.ph {
  color: #94a3b8;
}

.q-answer {
  margin-top: 16rpx;
  font-size: 25rpx;
  color: #475569;
}

.fb {
  margin-top: 14rpx;
  padding: 18rpx 22rpx;
  border-radius: 14rpx;
  background: #f8fafc;
  font-size: 24rpx;
  color: #475569;
}

.fb.ok {
  background: #ecfdf5;
  color: #10b981;
}

.fb.no {
  background: #fef2f2;
  color: #ef4444;
}

.fb-ana {
  margin-top: 8rpx;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 16rpx;
}

.upload-btn {
  height: 64rpx;
  line-height: 64rpx;
  padding: 0 28rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-size: 24rpx;
}

.upload-btn::after {
  border: none;
}

.file-name {
  flex: 1;
  overflow: hidden;
  font-size: 23rpx;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-del {
  margin-left: 10rpx;
  color: #ef4444;
}

.submit-btn {
  margin-top: 12rpx;
  height: 92rpx;
  line-height: 92rpx;
  border-radius: 24rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
}

.submit-btn::after {
  border: none;
}
</style>
