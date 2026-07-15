<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">我的错题本</div>
        <div class="page-subtitle">自动收录练习与考试中的错题，随时复习巩固</div>
      </div>
      <el-select v-model="courseId" placeholder="全部课程" clearable style="width: 240px" @change="load">
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <div v-loading="loading">
      <el-card v-for="(q, i) in rows" :key="q.question_id" shadow="never" class="wrong-card">
        <div class="q-head">
          <span class="q-idx">{{ i + 1 }}</span>
          <el-tag size="small" effect="light">{{ q.qtype_display }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ q.scene }}</el-tag>
          <span class="q-stem">{{ q.stem }}</span>
        </div>
        <div v-if="q.options?.length" class="q-options">
          <div v-for="o in q.options" :key="o.key" class="opt" :class="optClass(q, o.key)">
            {{ o.key }}. {{ o.text }}
          </div>
        </div>
        <div class="ans-line wrong">你的答案：{{ fmt(q.my_answer) }}</div>
        <div class="ans-line right">正确答案：{{ fmt(q.correct_answer) }}</div>
        <div v-if="q.analysis" class="analysis">解析：{{ q.analysis }}</div>
      </el-card>
      <el-empty v-if="!loading && !rows.length" description="太棒了，暂无错题！" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { listClasses } from '@/api/classroom'
import { getMyWrongQuestions } from '@/api/analytics'

const courses = ref([])
const courseId = ref(null)
const rows = ref([])
const loading = ref(false)

function fmt(a) {
  if (!a) return '（未作答）'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '—'
}
function optClass(q, key) {
  const correct = q.correct_answer?.key === key || (q.correct_answer?.keys || []).includes(key)
  const mine = q.my_answer?.key === key || (q.my_answer?.keys || []).includes(key)
  if (correct) return 'opt-right'
  if (mine) return 'opt-wrong'
  return ''
}

async function loadCourses() {
  const data = await listClasses()
  const map = new Map()
  ;(data.results ?? data).forEach((row) => {
    const ids = row.courses?.length ? row.courses : [row.course]
    ids.filter(Boolean).forEach((id, index) => {
      map.set(id, { id, name: row.course_names?.[index] || row.course_name || `课程 ${id}` })
    })
  })
  courses.value = [...map.values()]
}
async function load() {
  loading.value = true
  try {
    const data = await getMyWrongQuestions(courseId.value ? { course: courseId.value } : {})
    rows.value = data.results
  } finally {
    loading.value = false
  }
}

onMounted(() => { loadCourses(); load() })
</script>

<style scoped>
.wrong-card {
  margin-bottom: 16px;
}
.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.q-idx {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  flex-shrink: 0;
}
.q-stem {
  font-weight: 500;
}
.q-options {
  margin: 8px 0;
}
.opt {
  padding: 6px 12px;
  border-radius: 6px;
  margin: 4px 0;
}
.opt-right {
  background: #f0f9eb;
  color: #67c23a;
  font-weight: 600;
}
.opt-wrong {
  background: #fef0f0;
  color: #f56c6c;
}
.ans-line {
  font-size: 14px;
  margin-top: 6px;
}
.ans-line.wrong {
  color: #f56c6c;
}
.ans-line.right {
  color: #67c23a;
}
.analysis {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}
</style>
