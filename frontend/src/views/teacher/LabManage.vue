<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">虚拟实验</div>
        <div class="page-subtitle">引用平台实验模板创建实验，排课后学生按窗口进入</div>
      </div>
      <el-button type="warning" plain size="small" @click="guideDialog.open()">实验必读</el-button>
    </div>

    <!-- 新建实验：选模板 → 绑课程 → 覆盖配置 -->
    <el-card shadow="never" class="mb12">
      <template #header><span>新建实验</span></template>
      <el-form :model="form" label-width="100px" style="max-width: 720px">
        <el-form-item label="实验模板" required>
          <el-select v-model="form.template" placeholder="选择平台预置实验" style="width: 100%">
            <el-option v-for="t in templates" :key="t.id" :value="t.id" :label="t.title" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属课程">
          <el-input :model-value="currentCourseName" disabled>
            <template #append>当前课程</template>
          </el-input>
        </el-form-item>
        <el-form-item label="实验名称">
          <el-input v-model="form.title" placeholder="留空默认使用模板名称" />
        </el-form-item>
        <el-form-item label="标准时长">
          <el-input-number v-model="form.standard_minutes" :min="5" :max="180" placeholder="分钟" />
        </el-form-item>
        <el-form-item label="题目权重">
          <el-input-number v-model="form.question_weight" :min="0" :max="1" :step="0.1" />
          <span class="form-tip">0 = 纯实验步骤评分；0.3 = 实验分×0.7 + 附题分×0.3</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creating" @click="create">创建实验</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 已建实验列表：附题/排课/发布/成绩/复核/重置 -->
    <el-card shadow="never">
      <template #header><span>我的实验</span></template>
      <el-table :data="labs" v-loading="loading">
        <el-table-column prop="title" label="实验" min-width="200" />
        <el-table-column prop="course_name" label="课程" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="standard_minutes_display" label="标准时长(分)" width="100" />
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openSchedule(row)">排课</el-button>
            <el-button v-if="row.status === 'draft'" size="small" type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" size="small" type="warning" @click="close(row)">下线</el-button>
            <el-button size="small" @click="openSubmissions(row)">成绩</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 排课弹窗 -->
    <el-dialog v-model="scheduleVisible" title="排课（班级开放窗口）" width="560">
      <el-form :model="scheduleForm" label-width="90px">
        <el-form-item label="班级" required>
          <el-select v-model="scheduleForm.classroom" style="width: 100%">
            <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="c.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="开放时间" required>
          <el-date-picker v-model="scheduleForm.open_at" type="datetime" style="width: 100%" />
        </el-form-item>
        <el-form-item label="截止时间" required>
          <el-date-picker v-model="scheduleForm.close_at" type="datetime" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scheduleVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSchedule">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成绩弹窗 -->
    <el-dialog v-model="scoreVisible" :title="`实验成绩 - ${currentLab?.title || ''}`" width="860">
      <el-table :data="submissions" v-loading="scoreLoading">
        <el-table-column prop="student_name" label="学生" width="110" />
        <el-table-column prop="student_username" label="学号" width="110" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ row.status === 'submitted' ? '已提交' : '进行中' }}</template>
        </el-table-column>
        <el-table-column prop="passed_steps" label="步骤" width="80">
          <template #default="{ row }">{{ row.passed_steps }}/{{ row.total_steps }}</template>
        </el-table-column>
        <el-table-column prop="error_count" label="错误" width="70" />
        <el-table-column label="用时" width="90">
          <template #default="{ row }">{{ Math.round(row.elapsed_seconds / 60) }} 分</template>
        </el-table-column>
        <el-table-column prop="total_score" label="总分" width="80" />
        <el-table-column label="复核" width="70">
          <template #default="{ row }"><el-tag v-if="row.reviewed" size="small">已复核</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'submitted'" size="small" @click="openReview(row)">改分</el-button>
            <el-button size="small" type="warning" plain @click="reset(row)">重置</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 复核改分弹窗 -->
    <el-dialog v-model="reviewVisible" title="复核改分" width="420">
      <el-form label-width="90px">
        <el-form-item label="新总分">
          <el-input-number v-model="reviewForm.total_score" :min="0" :max="Number(currentSub?.lab_total_score || 100)" />
        </el-form-item>
        <el-form-item label="评语">
          <el-input v-model="reviewForm.comment" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button type="primary" @click="saveReview">提交（将通知学生）</el-button>
      </template>
    </el-dialog>

    <!-- 实验必读管理弹窗（教师：可编辑/恢复预设） -->
    <LabGuideDialog ref="guideDialog" is-teacher-view />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/api/request'
import LabGuideDialog from '@/components/LabGuideDialog.vue'
import {
  listLabs, createLab, updateLab, deleteLab, publishLab, closeLab,
  listLabTemplates, listLabSchedules, createLabSchedule,
  listLabSubmissions, reviewLabSubmission, resetLabSubmission,
} from '@/api/labs'

const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
// 课程空间内新建实验：课程固定为当前路由课程，无需选择
const currentCourseName = computed(
  () => courses.value.find((c) => c.id === fixedCourseId.value)?.name || `课程 #${fixedCourseId.value}`,
)

const templates = ref([])
const courses = ref([])
const classes = ref([])
const labs = ref([])
const loading = ref(false)
const creating = ref(false)

const form = ref({ template: null, title: '', standard_minutes: 30, question_weight: 0 })

const scheduleVisible = ref(false)
const scheduleForm = ref({ lab: null, classroom: null, open_at: '', close_at: '' })
const currentLab = ref(null)

const scoreVisible = ref(false)
const scoreLoading = ref(false)
const submissions = ref([])

const reviewVisible = ref(false)
const reviewForm = ref({ total_score: 0, comment: '' })
const currentSub = ref(null)
const guideDialog = ref(null)

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已下线' }[s] || s)
const statusType = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')

async function load() {
  loading.value = true
  try {
    const params = fixedCourseId.value ? { course: fixedCourseId.value } : undefined
    // 课程固定为当前课程：只需拉模板、实验列表、课程名（用于只读展示）
    const [t, l, c] = await Promise.all([listLabTemplates(), listLabs(params), request.get('/courses/', { params })])
    templates.value = t.results ?? t
    labs.value = (l.results ?? l)
    courses.value = (c.results ?? c)
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.value.template) {
    ElMessage.warning('请选择实验模板')
    return
  }
  creating.value = true
  try {
    // course 由路由注入：本页面仅存在于课程空间内
    await createLab({ ...form.value, course: fixedCourseId.value, title: form.value.title || undefined })
    ElMessage.success('实验已创建，排课并发布后学生可见')
    form.value = { template: null, title: '', standard_minutes: 30, question_weight: 0 }
    await load()
  } finally {
    creating.value = false
  }
}

async function openSchedule(row) {
  currentLab.value = row
  const res = await request.get('/classes/')
  classes.value = (res.results ?? res).filter(
    (c) => !c.courses || c.courses.some?.((cid) => cid === row.course) || true,
  )
  scheduleForm.value = { lab: row.id, classroom: null, open_at: '', close_at: '' }
  scheduleVisible.value = true
}

async function saveSchedule() {
  try {
    await createLabSchedule(scheduleForm.value)
    ElMessage.success('排课已保存')
    scheduleVisible.value = false
  } catch (e) {
    ElMessage.error(e?.message || '排课失败')
  }
}

async function publish(row) {
  await publishLab(row.id)
  ElMessage.success('已发布并通知班级学生')
  await load()
}

async function close(row) {
  await closeLab(row.id)
  ElMessage.success('已下线')
  await load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除实验「${row.title}」？`, '提示', { type: 'warning' })
  await deleteLab(row.id)
  await load()
}

async function openSubmissions(row) {
  currentLab.value = row
  scoreVisible.value = true
  scoreLoading.value = true
  try {
    const res = await listLabSubmissions({ lab: row.id })
    submissions.value = res.results ?? res
  } finally {
    scoreLoading.value = false
  }
}

function openReview(row) {
  currentSub.value = { ...row, lab_total_score: currentLab.value?.total_score }
  reviewForm.value = { total_score: Number(row.total_score || 0), comment: '' }
  reviewVisible.value = true
}

async function saveReview() {
  await reviewLabSubmission(currentSub.value.id, reviewForm.value)
  ElMessage.success('复核完成，已通知学生')
  reviewVisible.value = false
  await openSubmissions(currentLab.value)
}

async function reset(row) {
  await ElMessageBox.confirm('重置后该学生可重新做实验（旧成绩清空），确认？', '提示', { type: 'warning' })
  await resetLabSubmission(row.id)
  ElMessage.success('已重置')
  await openSubmissions(currentLab.value)
}

onMounted(load)
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.form-tip { color: #94a3b8; font-size: 12px; margin-left: 10px; }
</style>
