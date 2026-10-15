<template>
  <!-- 题干详情浮层：悬停展示完整题干与题目详情，鼠标移走立即隐藏；默认插槽为触发元素（题干） -->
  <el-popover
    placement="right"
    trigger="hover"
    :width="400"
    :show-after="100"
    :hide-after="0"
    enterable
    popper-class="question-detail-popper"
  >
    <template #reference>
      <slot />
    </template>
    <div class="qdt">
      <div class="qdt-stem">{{ stem }}</div>
      <div class="qdt-meta">
        <span class="qdt-tag type">{{ typeAbbr }}</span>
        <span class="qdt-tag difficulty" :class="`difficulty-${difficulty}`">{{ difficultyAbbr }}</span>
        <span v-if="score !== '' && score !== null && score !== undefined" class="qdt-score">分值 {{ scoreText }}</span>
      </div>
      <div v-if="optionList.length" class="qdt-options">
        <div v-for="(opt, i) in optionList" :key="opt?.key ?? i" class="qdt-option">
          <span class="qdt-option-key">{{ opt?.key ?? '' }}</span>
          <span class="qdt-option-text">{{ opt?.text ?? '' }}</span>
        </div>
      </div>
      <div v-if="answerText" class="qdt-answer"><span class="qdt-label">参考答案</span>{{ answerText }}</div>
      <div v-if="analysis" class="qdt-analysis"><span class="qdt-label">解析</span>{{ analysis }}</div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed } from 'vue'
import { abbrQtype, abbrDifficulty } from '@/utils/question-abbr'
import { blankAnswerText } from '@/utils/blank-answer'

const props = defineProps({
  stem: { type: String, default: '' },
  qtype: { type: String, default: '' },
  difficulty: { type: String, default: '' },
  qtypeDisplay: { type: String, default: '' },
  difficultyDisplay: { type: String, default: '' },
  score: { type: [Number, String], default: '' },
  options: { type: Array, default: () => [] },
  answer: { type: [String, Number], default: '' },
  analysis: { type: String, default: '' },
})

const typeAbbr = computed(() => abbrQtype(props))
const difficultyAbbr = computed(() => abbrDifficulty(props))
const optionList = computed(() => (Array.isArray(props.options) ? props.options : []))
// 分值规范化："5.0" → "5"，"2.5" → "2.5"
const scoreText = computed(() => {
  const s = props.score
  if (s === '' || s === null || s === undefined) return ''
  const n = Number(s)
  if (Number.isFinite(n)) return String(Math.round(n * 100) / 100)
  return String(s)
})
// 参考答案按题型结构化展示，避免对象直接字符串化成 [object Object]
function formatAnswer(answer, options) {
  if (answer === null || answer === undefined || answer === '') return ''
  if (typeof answer === 'string') return answer.trim()
  if (typeof answer === 'number') return String(answer)
  if (Array.isArray(answer)) return answer.map((x) => String(x)).join('；')
  if (typeof answer !== 'object') return String(answer)
  const optText = (key) => {
    const opt = (options || []).find((o) => String(o?.key) === String(key))
    const text = opt && opt.text !== undefined && opt.text !== null && String(opt.text).trim() !== '' ? String(opt.text) : ''
    return text ? `${key}. ${text}` : String(key)
  }
  if (answer.key !== undefined && answer.key !== null && answer.key !== '') return optText(answer.key) // 单选/判断
  if (Array.isArray(answer.keys) && answer.keys.length) return answer.keys.map(optText).join('；') // 多选
  if (Array.isArray(answer.blanks) && answer.blanks.length) { // 填空（兼容按空赋分对象数组）
    return blankAnswerText(answer)
  }
  if (answer.text !== undefined && String(answer.text).trim() !== '') return String(answer.text) // 简答
  if (answer.value !== undefined && String(answer.value).trim() !== '') return String(answer.value)
  const leaves = [] // 兜底：拼接所有叶子值
  Object.values(answer).forEach((v) => {
    if (Array.isArray(v)) v.forEach((x) => { if (String(x).trim() !== '') leaves.push(String(x)) })
    else if (v !== null && v !== undefined && String(v).trim() !== '') leaves.push(String(v))
  })
  return leaves.join('；')
}
const answerText = computed(() => formatAnswer(props.answer, props.options))
</script>

<style scoped>
/* 题干完整展示 + 元信息（题型/难度/分值） */
.qdt {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 420px;
  overflow: auto;
}
.qdt-stem {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.qdt-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.qdt-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 21px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 750;
  white-space: nowrap;
}
.qdt-tag.type {
  border: 1px solid #bfdbfe;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.72);
}
.qdt-tag.difficulty {
  border: 1px solid #dbeafe;
  color: #64748b;
  background: #f8fbff;
}
.qdt-tag.difficulty-easy {
  border-color: #bbf7d0;
  color: #16a34a;
  background: rgba(240, 253, 244, 0.72);
}
.qdt-tag.difficulty-medium {
  border-color: #fed7aa;
  color: #d97706;
  background: rgba(255, 247, 237, 0.78);
}
.qdt-tag.difficulty-hard {
  border-color: #fecaca;
  color: #ef4444;
  background: rgba(254, 242, 242, 0.78);
}
.qdt-score { color: #2563eb; font-size: 12px; font-weight: 800; }
.qdt-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fbff;
}
.qdt-option {
  display: flex;
  gap: 8px;
  color: #334155;
  font-size: 13px;
  line-height: 1.55;
}
.qdt-option-key {
  display: grid;
  flex: none;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 6px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 800;
}
.qdt-option-text { min-width: 0; word-break: break-word; }
.qdt-answer { color: #16a34a; font-size: 13px; font-weight: 700; line-height: 1.6; }
.qdt-analysis { color: #334155; font-size: 13px; line-height: 1.6; }
.qdt-label {
  display: inline-block;
  margin-right: 8px;
  padding: 1px 8px;
  border-radius: 6px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 11px;
  font-weight: 800;
}
</style>

<style>
/* 浮层容器样式（popper 传送到 body，需全局样式） */
/* z-index 必须高于 .homework-editor 的 3000（全屏 fixed 覆盖层），否则浮层被压在编辑器下方不可见 */
/* EP 的 z-index 是内联 style 动态注入，必须 !important 才能覆盖 */
.question-detail-popper.el-popper {
  z-index: 5300 !important;
  padding: 14px 16px !important;
  border: 1px solid #dbe5ef;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 16px 40px rgba(37, 99, 235, 0.14);
}
.question-detail-popper .el-popper__arrow::before {
  border: 1px solid #dbe5ef;
  background: #fff;
}
</style>
