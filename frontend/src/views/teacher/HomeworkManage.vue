<template>
  <div class="page-container homework-page" :class="{ 'is-editing': editVisible }">
    <template v-if="!editVisible">
    <div class="page-header">
      <div>
        <div class="page-title">作业管理</div>
        <div class="page-subtitle">发布作业、查看提交情况并批改评分</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <div class="toolbar module-toolbar">
        <div class="toolbar-left">
          <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="load">
            <el-option v-for="c in classes" :key="c.id" :label="`${classCourseNames(c)} / ${c.name}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openEdit()">发布作业</el-button>
        </div>
      </div>

      <el-empty v-if="!classId" description="请先选择班级" />
      <template v-else>
        <TableSkeleton v-if="loading" :cols="5" />
        <el-empty v-else-if="!rows.length" :image-size="110">
          <template #description>
            <div class="hw-empty-text">还没有作业</div>
            <div class="hw-empty-tip">点击右上角「发布作业」开始布置</div>
          </template>
        </el-empty>
        <div v-else class="hw-list animate-list">
          <div v-for="row in rows" :key="row.id" class="hw-row">
            <div class="hw-row-left">
              <div class="hw-copy">
                <div class="hw-title">{{ row.title }}</div>
                <div class="hw-meta">
                  <span class="hw-meta-item">
                    <el-icon><Clock /></el-icon>{{ row.start_time ? new Date(row.start_time).toLocaleString() : '立即开始' }}
                  </span>
                  <span class="hw-meta-item">
                    截止 {{ row.deadline ? new Date(row.deadline).toLocaleString() : '不限' }}
                  </span>
                  <span class="hw-score">{{ row.total_score }} 分</span>
                  <span class="hw-meta-item">已交 {{ row.submission_count }}</span>
                  <el-tag size="small" :type="{ published: 'success', draft: 'warning', closed: 'info' }[row.status]" effect="light" round>
                    {{ row.status_display }}
                  </el-tag>
                </div>
              </div>
            </div>
            <div class="hw-action-group">
              <button class="hw-action-btn" @click="openSubmissions(row)"><el-icon><View /></el-icon> 批改</button>
              <button v-if="row.status === 'draft'" class="hw-action-btn success" @click="setStatus(row, 'published')">
                <el-icon><Promotion /></el-icon> 发布
              </button>
              <button v-if="row.status === 'published'" class="hw-action-btn warn" @click="setStatus(row, 'draft')">
                <el-icon><RefreshLeft /></el-icon> 撤回
              </button>
              <button class="hw-action-btn" @click="openEdit(row)"><el-icon><EditPen /></el-icon> 编辑</button>
              <button class="hw-action-btn danger" @click="openDelete(row)"><el-icon><Delete /></el-icon> 删除</button>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    </template>

    <!-- 发布/编辑作业：复用完整讲解的全屏工作台结构 -->
    <Teleport to="body">
    <div v-if="editVisible" class="homework-editor">
      <div class="hw-editor-topbar">
        <div class="hw-editor-title-wrap">
          <span class="hw-editor-icon"><el-icon><Document /></el-icon></span>
          <div class="hw-editor-heading">
            <div class="hw-editor-title-line">
              <div class="hw-editor-title">{{ form.id ? '编辑作业' : '发布作业' }}</div>
              <span class="hw-editor-kicker">{{ editorContext }}</span>
            </div>
            <div class="hw-editor-subtitle">从题库选题，或使用文本 / 附件作业</div>
          </div>
        </div>
        <div class="hw-editor-stats">
          <template v-if="form.mode === 'questions'">
            <span><strong>{{ selectedQuestions.length }}</strong> 道题目</span>
            <span><strong>{{ selectedTotal }}</strong> 总分</span>
          </template>
          <template v-else>
            <span><strong>{{ form.total_score || 0 }}</strong> 总分</span>
            <span>附件型作业</span>
          </template>
          <el-tag :type="form.status === 'published' ? 'success' : 'warning'" effect="light" round>
            {{ form.status === 'published' ? '已发布' : '草稿' }}
          </el-tag>
        </div>
        <div class="hw-editor-actions">
          <el-button v-if="isFrozen" type="warning" plain :loading="saving" @click="withdrawCurrent">撤回修改</el-button>
          <el-button type="primary" :loading="saving" @click="save">{{ form.id ? '保存修改' : '保存作业' }}</el-button>
          <el-button @click="editVisible = false">退出编辑</el-button>
        </div>
      </div>

      <div class="homework-editor-body">
      <el-form :model="form" label-position="top" class="homework-creation-form">
        <div class="creation-form-grid">
          <!-- 左列：基础信息 -->
          <div class="form-col form-col-left">
            <div class="hw-card hw-info-card">
              <div class="hw-card-head"><el-icon><Tickets /></el-icon>基础信息</div>
            <el-form-item label="作业模式">
              <el-radio-group v-model="form.mode" class="homework-mode-switch" :disabled="isFrozen" @change="onModeChange">
                <el-radio-button value="questions">题库选题</el-radio-button>
                <el-radio-button value="attachment">文本 / 附件</el-radio-button>
              </el-radio-group>
              <span v-if="isFrozen" class="freeze-tip">已发布，题目快照已冻结</span>
            </el-form-item>
            <el-form-item label="作业标题"><el-input v-model="form.title" placeholder="请输入作业标题" /></el-form-item>
            <el-form-item label="作业说明" class="hw-desc-item"><el-input v-model="form.description" type="textarea" :rows="5" resize="none" placeholder="请输入作业要求说明" /></el-form-item>
            <el-form-item label="开始时间">
              <el-date-picker
                v-model="form.start_time"
                type="datetime"
                placeholder="选择开始时间"
                format="YYYY年MM月DD日 HH:mm"
                value-format="YYYY-MM-DDTHH:mm:ss"
                popper-class="platform-datetime-popper"
                :disabled-date="disabledStartDate"
                :disabled-hours="disabledStartHours"
                :disabled-minutes="disabledStartMinutes"
                :disabled-seconds="disabledStartSeconds"
                @change="validateTimeRange"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="截止时间">
              <el-date-picker
                v-model="form.deadline"
                type="datetime"
                placeholder="选择截止时间"
                format="YYYY年MM月DD日 HH:mm"
                value-format="YYYY-MM-DDTHH:mm:ss"
                popper-class="platform-datetime-popper"
                :disabled-date="disabledDeadlineDate"
                :disabled-hours="disabledDeadlineHours"
                :disabled-minutes="disabledDeadlineMinutes"
                :disabled-seconds="disabledDeadlineSeconds"
                @change="validateTimeRange"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item v-if="form.mode === 'attachment'" label="满分"><el-input-number v-model="form.total_score" :min="1" :max="200" /></el-form-item>
            </div>
          </div>

          <!-- 右列：题库选题 / 附件 -->
          <div class="form-col form-col-right">
            <div class="hw-card hw-content-card">
              <div class="hw-card-head"><el-icon><EditPen /></el-icon>{{ form.mode === 'attachment' ? '作业附件' : '题目选择' }}</div>
              <div v-if="form.mode === 'attachment'" class="attachment-panel">
                <el-upload
                  ref="homeworkUploadRef"
                  class="attachment-uploader"
                  drag
                  :auto-upload="false"
                  :limit="1"
                  accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip,.rar"
                  :on-change="onHomeworkFile"
                  :on-remove="() => { homeworkFile = null }"
                >
                  <el-icon class="attachment-upload-icon"><Document /></el-icon>
                  <div class="attachment-upload-title">拖拽文件到此处，或点击选择</div>
                  <div class="attachment-upload-tip">支持 PDF、Word、PPT、Excel、TXT 与压缩包，最大 20MB</div>
                </el-upload>
                <a
                  v-if="currentAttachment && !homeworkFile"
                  class="existing-attachment"
                  :href="currentAttachment"
                  target="_blank"
                  rel="noopener"
                >
                  <el-icon><Document /></el-icon>
                  <span>查看已上传附件</span>
                </a>
              </div>
              <div v-else class="question-builder">
                <el-alert
                  v-if="isFrozen"
                  type="success"
                  :closable="false"
                  show-icon
                  title="该作业已经发布，以下题目与答案均使用已冻结快照。"
                />
                <div v-if="!isFrozen" class="question-pool-panel">
                  <div class="question-filters">
                    <el-select v-model="questionFilters.catalog" clearable placeholder="章节" popper-class="homework-filter-popper">
                      <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                    </el-select>
                    <el-select v-model="questionFilters.qtype" clearable placeholder="题型" popper-class="homework-filter-popper">
                      <el-option label="单选题" value="single" /><el-option label="多选题" value="multi" />
                      <el-option label="判断题" value="judge" /><el-option label="填空题" value="blank" />
                      <el-option label="简答题" value="short" />
                    </el-select>
                    <el-select v-model="questionFilters.difficulty" clearable placeholder="难度" popper-class="homework-filter-popper">
                      <el-option label="简单" value="easy" /><el-option label="中等" value="medium" /><el-option label="困难" value="hard" />
                    </el-select>
                  </div>
                  <el-table :data="filteredQuestionOptions" height="300" v-loading="questionLoading" class="question-pool-table">
                    <el-table-column prop="stem" label="题干" min-width="240">
                      <template #default="{ row }">
                        <span class="pool-stem">{{ row.stem }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="题型" width="94">
                      <template #default="{ row }">
                        <span class="pool-tag type">{{ row.qtype_display }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="难度" width="82">
                      <template #default="{ row }">
                        <span class="pool-tag difficulty" :class="`difficulty-${row.difficulty}`">{{ row.difficulty_display }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="操作" width="82" align="center">
                      <template #default="{ row }">
                        <button class="pool-action" :class="{ selected: isSelected(row.id) }" type="button" @click="toggleQuestion(row)">
                          {{ isSelected(row.id) ? '移除' : '添加' }}
                        </button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>

                <div class="selected-panel">
                  <div class="selected-header">
                    <strong>已选 {{ selectedQuestions.length }} 题</strong>
                    <span>总分 {{ selectedTotal }} 分（自动计算）</span>
                  </div>
                  <div v-if="!selectedQuestions.length" class="selected-empty">
                    <el-icon><Plus /></el-icon>
                    <span>点击上方题目的「添加」，已选题目会显示在这里</span>
                  </div>
                  <el-scrollbar v-else class="selected-list-scroll">
                    <div class="selected-list">
                      <div v-for="(item, index) in selectedQuestions" :key="item.question" class="selected-item">
                        <span class="question-order">{{ index + 1 }}</span>
                        <span class="selected-stem">{{ item.stem }}</span>
                        <el-tag size="small" effect="plain">{{ item.qtype_display }}</el-tag>
                        <el-input
                          v-model.number="item.score"
                          class="score-input"
                          type="number"
                          min="0.5"
                          max="100"
                          step="0.5"
                        />
                        <span class="score-unit">分</span>
                        <div v-if="!isFrozen" class="selected-actions">
                          <el-button link circle :icon="ArrowUp" :disabled="index === 0" title="上移" @click="moveQuestion(index, -1)" />
                          <el-button link circle :icon="ArrowDown" :disabled="index === selectedQuestions.length - 1" title="下移" @click="moveQuestion(index, 1)" />
                          <el-button link type="danger" @click="selectedQuestions.splice(index, 1)">删除</el-button>
                        </div>
                      </div>
                    </div>
                  </el-scrollbar>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-form>
      </div>
    </div>
    </Teleport>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除作业"
      :item-name="deleteTarget?.title"
      description="删除后将无法从当前课程工作区继续访问，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 提交与批改 -->
    <el-drawer v-model="subVisible" class="grading-drawer" modal-class="grading-drawer-mask" size="48%" :with-header="false">
      <div class="grading-panel">
        <div class="grading-panel-head">
          <div class="grading-heading">
            <div class="grading-kicker">提交批改</div>
            <div class="grading-title">{{ currentHw?.title || '作业批改' }}</div>
            <div class="grading-meta">
              <span>{{ currentHw?.deadline ? new Date(currentHw.deadline).toLocaleString() : '不限截止' }}</span>
              <span>{{ currentHw?.total_score || 0 }} 分</span>
            </div>
          </div>
          <button class="grading-close" type="button" @click="subVisible = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>

        <div class="grading-summary">
          <div class="grading-stat">
            <span>已提交</span>
            <strong>{{ submissions.length }}</strong>
          </div>
          <div class="grading-stat">
            <span>待批改</span>
            <strong>{{ pendingSubmissionCount }}</strong>
          </div>
          <div class="grading-stat">
            <span>平均分</span>
            <strong>{{ averageSubmissionScore }}</strong>
          </div>
        </div>

        <div class="grading-table-card">
          <el-table :data="submissions" v-loading="subLoading" class="grading-table" height="100%">
            <el-table-column prop="student_name" label="学生" width="116" />
            <el-table-column label="提交内容" min-width="210" show-overflow-tooltip>
              <template #default="{ row }">
                {{ currentHw?.mode === 'questions' ? `客观题 ${row.objective_score ?? 0} 分` : (row.content || '附件提交') }}
              </template>
            </el-table-column>
            <el-table-column label="逾期" width="78" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.is_late" type="danger" size="small" effect="light" round>逾期</el-tag>
                <span v-else class="grading-muted">正常</span>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="得分" width="86" align="center">
              <template #default="{ row }">
                <span :class="row.score == null ? 'grading-muted' : 'grading-score'">{{ row.score ?? '未批' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="92" align="center">
              <template #default="{ row }">
                <button class="grading-action" type="button" @click="openGrade(row)">
                  {{ row.score == null ? '批改' : '查看' }}
                </button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="grading-empty">
                <el-empty :image-size="120" description="还没有学生提交" />
              </div>
            </template>
          </el-table>
        </div>
      </div>
    </el-drawer>

    <!-- 批改弹窗 -->
    <el-dialog v-model="gradeVisible" class="grade-dialog" title="批改作业" width="720px" align-center>
      <div v-if="currentHw?.mode === 'questions'" class="answer-review-list">
        <div v-for="(item, index) in gradeForm.answerItems" :key="item.id" class="answer-review-item">
          <div class="answer-review-head">
            <strong>{{ index + 1 }}. {{ item.snapshot.stem }}</strong>
            <span>{{ item.score ?? '待批' }} / {{ item.fullScore }} 分</span>
          </div>
          <div class="student-answer">学生答案：{{ formatAnswer(item.student_answer) || '未作答' }}</div>
          <div v-if="item.needs_manual_grading" class="manual-grade-row">
            <el-input-number v-model="item.manualScore" :min="0" :max="item.fullScore" :step="0.5" />
            <el-input v-model="item.comment" placeholder="本题评语（选填）" />
          </div>
          <el-tag v-else :type="item.is_correct ? 'success' : 'danger'" size="small">
            {{ item.is_correct ? '自动判定正确' : '自动判定错误' }}
          </el-tag>
        </div>
      </div>
      <div v-else class="grade-content">
        <div class="grade-label">学生提交</div>
        <div class="grade-text">{{ gradeForm.content || '（无文本内容）' }}</div>
      </div>
      <el-form :model="gradeForm" label-width="70px">
        <el-form-item v-if="currentHw?.mode !== 'questions'" label="得分">
          <el-input-number v-model="gradeForm.score" :min="0" :max="Number(currentHw?.total_score) || 100" />
          <span class="total-hint">/ {{ currentHw?.total_score }} 分</span>
        </el-form-item>
        <el-form-item label="评语"><el-input v-model="gradeForm.comment" type="textarea" :rows="3" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="gradeVisible = false">取消</el-button>
          <el-button type="primary" :loading="grading" @click="doGrade">提交批改</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Delete, EditPen, View, Document, Close, Promotion, Clock, ArrowUp, ArrowDown, Tickets, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listClasses } from '@/api/classroom'
import { listCatalogs } from '@/api/course'
import { listQuestions } from '@/api/question'
import {
  listHomeworks, createHomework, updateHomework, deleteHomework,
  listSubmissions, gradeSubmission,
} from '@/api/homework'

const classes = ref([])
const classId = ref(null)
const rows = ref([])
const loading = ref(false)
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const activeClassroom = computed(() => classes.value.find((item) => item.id === classId.value))
const editorContext = computed(() => {
  const classroom = activeClassroom.value
  if (!classroom) return '课程作业'
  return `${classCourseNames(classroom)} · ${classroom.name}`
})

function classCourseNames(item) {
  return item.course_names?.join('、') || item.course_name || '未关联课程'
}

function activeCourseId() {
  const classroom = activeClassroom.value
  return fixedCourseId.value || classroom?.course || null
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    load()
  } else {
    classId.value = null
    rows.value = []
  }
}
async function load() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await listHomeworks({ classroom: classId.value, course: activeCourseId() })
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

// ---- 发布/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})
const originalSchedule = reactive({ start_time: '', deadline: '' })
const isFrozen = computed(() => Boolean(form.id) && form.status !== 'draft')
const selectedQuestions = ref([])
const selectedTotal = computed(() => selectedQuestions.value.reduce((sum, item) => sum + Number(item.score || 0), 0))
const homeworkFile = ref(null)
const homeworkUploadRef = ref(null)
const currentAttachment = ref('')
const catalogOptions = ref([])
const questionOptions = ref([])
const questionLoading = ref(false)
const questionFilters = reactive({ catalog: null, qtype: '', difficulty: '' })
const filteredQuestionOptions = computed(() => questionOptions.value.filter((item) => {
  if (questionFilters.catalog && Number(item.catalog) !== Number(questionFilters.catalog)) return false
  if (questionFilters.qtype && item.qtype !== questionFilters.qtype) return false
  if (questionFilters.difficulty && item.difficulty !== questionFilters.difficulty) return false
  return true
}))

function flattenCatalogs(items, depth = 0) {
  return (items || []).flatMap((item) => [
    { id: item.id, label: `${'　'.repeat(depth)}${item.title}` },
    ...flattenCatalogs(item.children, depth + 1),
  ])
}

async function loadCatalogOptions() {
  const course = activeCourseId()
  if (!course) return
  const data = await listCatalogs({ course, tree: 1, page_size: 100 })
  catalogOptions.value = flattenCatalogs(data.results ?? data)
}

async function loadQuestionOptions() {
  if (form.mode !== 'questions' || isFrozen.value) return
  questionLoading.value = true
  try {
    const params = { course: activeCourseId(), status: 'published', page_size: 1000 }
    const data = await listQuestions(params)
    questionOptions.value = data.results ?? data
  } finally {
    questionLoading.value = false
  }
}

function parseDateTime(value) {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

function startOfDay(value) {
  const date = new Date(value)
  date.setHours(0, 0, 0, 0)
  return date
}

function range(count) {
  return Array.from({ length: Math.max(0, count) }, (_, index) => index)
}

function minDeadlineDate() {
  return parseDateTime(form.start_time) || new Date()
}

function disabledBeforeDate(date, minDate) {
  const min = startOfDay(minDate)
  const current = new Date(date)
  current.setHours(0, 0, 0, 0)
  return current.getTime() < min.getTime()
}

function selectedMatchesMinDate(value, minDate) {
  const selected = parseDateTime(value)
  return !selected || isSameDay(selected, minDate)
}

function disabledHoursFor(value, minDate) {
  if (!selectedMatchesMinDate(value, minDate)) return []
  return range(minDate.getMinutes() >= 59 ? minDate.getHours() + 1 : minDate.getHours())
}

function disabledMinutesFor(value, minDate, hour) {
  if (!selectedMatchesMinDate(value, minDate) || hour !== minDate.getHours()) return []
  return range(minDate.getMinutes() + 1)
}

function disabledSecondsFor(value, minDate, hour, minute) {
  if (!selectedMatchesMinDate(value, minDate) || hour !== minDate.getHours() || minute !== minDate.getMinutes()) return []
  return range(minDate.getSeconds() + 1)
}

function disabledStartDate(date) {
  return disabledBeforeDate(date, new Date())
}

function disabledStartHours() {
  return disabledHoursFor(form.start_time, new Date())
}

function disabledStartMinutes(hour) {
  return disabledMinutesFor(form.start_time, new Date(), hour)
}

function disabledStartSeconds(hour, minute) {
  return disabledSecondsFor(form.start_time, new Date(), hour, minute)
}

function disabledDeadlineDate(date) {
  return disabledBeforeDate(date, minDeadlineDate())
}

function disabledDeadlineHours() {
  return disabledHoursFor(form.deadline, minDeadlineDate())
}

function disabledDeadlineMinutes(hour) {
  return disabledMinutesFor(form.deadline, minDeadlineDate(), hour)
}

function disabledDeadlineSeconds(hour, minute) {
  return disabledSecondsFor(form.deadline, minDeadlineDate(), hour, minute)
}

function validateTimeRange() {
  const start = parseDateTime(form.start_time)
  const deadline = parseDateTime(form.deadline)
  const now = Date.now()
  const startChanged = form.start_time !== originalSchedule.start_time
  const deadlineChanged = form.deadline !== originalSchedule.deadline
  if (start && start.getTime() < now && startChanged) {
    form.start_time = ''
    ElMessage.warning('开始时间不能早于当前时间')
    return false
  }
  if (deadline && deadline.getTime() < now && deadlineChanged) {
    form.deadline = ''
    ElMessage.warning('截止时间不能早于当前时间')
    return false
  }
  if (start && deadline && deadline.getTime() <= start.getTime()) {
    form.deadline = ''
    ElMessage.warning('截止时间必须晚于开始时间')
    return false
  }
  return true
}

function onModeChange(mode) {
  if (mode === 'questions') {
    loadCatalogOptions()
    loadQuestionOptions()
  }
}

function isSelected(id) {
  return selectedQuestions.value.some((item) => Number(item.question) === Number(id))
}

function toggleQuestion(question) {
  const index = selectedQuestions.value.findIndex((item) => Number(item.question) === Number(question.id))
  if (index >= 0) selectedQuestions.value.splice(index, 1)
  else selectedQuestions.value.push({
    question: question.id,
    stem: question.stem,
    qtype_display: question.qtype_display,
    difficulty_display: question.difficulty_display,
    score: Number(question.score) || 5,
  })
}

function moveQuestion(index, offset) {
  const target = index + offset
  if (target < 0 || target >= selectedQuestions.value.length) return
  const [item] = selectedQuestions.value.splice(index, 1)
  selectedQuestions.value.splice(target, 0, item)
}

function onHomeworkFile(file) {
  const name = String(file.name || '').toLowerCase()
  const allowed = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.zip', '.rar']
  if (!allowed.some((ext) => name.endsWith(ext))) {
    homeworkFile.value = null
    homeworkUploadRef.value?.clearFiles()
    ElMessage.warning('不支持该文件格式，请上传 PDF、Office 文档、TXT 或压缩包')
    return
  }
  if (Number(file.size || 0) > 20 * 1024 * 1024) {
    homeworkFile.value = null
    homeworkUploadRef.value?.clearFiles()
    ElMessage.warning('附件大小不能超过 20MB')
    return
  }
  homeworkFile.value = file.raw
  currentAttachment.value = ''
}

function openEdit(row) {
  originalSchedule.start_time = row?.start_time || ''
  originalSchedule.deadline = row?.deadline || ''
  Object.assign(form, {
    id: row?.id || null,
    title: row?.title || '',
    description: row?.description || '',
    start_time: row?.start_time || '',
    deadline: row?.deadline || '',
    total_score: Number(row?.total_score) || 100,
    mode: row?.mode || 'questions',
    status: row?.status || 'draft',
  })
  homeworkFile.value = null
  currentAttachment.value = row?.attachment || ''
  selectedQuestions.value = (row?.questions || []).map((item) => ({
    question: item.question,
    stem: item.snapshot?.stem || '题目快照',
    qtype_display: item.snapshot?.qtype_display || item.snapshot?.qtype || '',
    difficulty_display: item.snapshot?.difficulty_display || '',
    score: Number(item.score),
  }))
  questionFilters.catalog = null
  questionFilters.qtype = ''
  questionFilters.difficulty = ''
  editVisible.value = true
  if ((row?.mode || 'questions') === 'questions') {
    loadCatalogOptions()
    loadQuestionOptions()
  }
}
async function save() {
  if (!form.title?.trim()) return ElMessage.warning('请填写标题')
  const courseId = activeCourseId()
  if (!courseId) return ElMessage.warning('该班级尚未关联课程')
  if (!validateTimeRange()) return
  if (form.mode === 'questions' && form.status === 'published' && !selectedQuestions.value.length) {
    return ElMessage.warning('发布题库作业前请至少选择一道题')
  }
  let payload = {
    title: form.title.trim(), description: form.description, start_time: form.start_time || null, deadline: form.deadline || null, status: form.status,
  }
  if (!isFrozen.value) {
    payload = { ...payload, course: courseId, classroom: classId.value, mode: form.mode }
    if (form.mode === 'questions') {
      payload.question_items = selectedQuestions.value.map((item) => ({ question: item.question, score: item.score }))
    } else {
      payload.total_score = form.total_score
    }
  }
  if (form.mode === 'attachment' && homeworkFile.value) {
    const body = new FormData()
    Object.entries(payload).forEach(([key, value]) => {
      if (value !== null && value !== undefined) body.append(key, value)
    })
    body.append('attachment', homeworkFile.value)
    payload = body
  }
  saving.value = true
  try {
    if (form.id) { await updateHomework(form.id, payload); ElMessage.success('已更新') }
    else { await createHomework(payload); ElMessage.success('已保存') }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}
async function setStatus(row, status) {
  await updateHomework(row.id, { status })
  ElMessage.success(status === 'published' ? '已发布' : '已撤回，可继续修改')
  load()
}

async function withdrawCurrent() {
  if (!form.id) return
  saving.value = true
  try {
    await updateHomework(form.id, { status: 'draft' })
    form.status = 'draft'
    ElMessage.success('已撤回，可继续修改')
    if (form.mode === 'questions') {
      await loadCatalogOptions()
      await loadQuestionOptions()
    }
    load()
  } finally {
    saving.value = false
  }
}
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteHomework(deleteTarget.value.id)
    ElMessage.success('作业已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    load()
  } finally {
    deleting.value = false
  }
}

// ---- 提交与批改 ----
const subVisible = ref(false)
const subLoading = ref(false)
const submissions = ref([])
const currentHw = ref(null)
const gradedSubmissions = computed(() => submissions.value.filter((row) => row.score !== null && row.score !== undefined && row.score !== ''))
const pendingSubmissionCount = computed(() => Math.max(submissions.value.length - gradedSubmissions.value.length, 0))
const averageSubmissionScore = computed(() => {
  if (!gradedSubmissions.value.length) return '--'
  const total = gradedSubmissions.value.reduce((sum, row) => sum + Number(row.score || 0), 0)
  return (total / gradedSubmissions.value.length).toFixed(1)
})
async function openSubmissions(row) {
  currentHw.value = row
  subVisible.value = true
  subLoading.value = true
  try {
    const data = await listSubmissions({ homework: row.id })
    submissions.value = data.results ?? data
  } finally {
    subLoading.value = false
  }
}

const gradeVisible = ref(false)
const grading = ref(false)
const gradeForm = reactive({ id: null, content: '', score: 0, comment: '' })
function openGrade(row) {
  Object.assign(gradeForm, {
    id: row.id,
    content: row.content,
    score: Number(row.score) || 0,
    comment: row.comment || '',
    answerItems: (row.answer_items || []).map((item) => ({
      ...item,
      fullScore: Number(currentHw.value?.questions?.find((q) => q.id === item.homework_question)?.score || 0),
      manualScore: item.score == null ? 0 : Number(item.score),
      comment: item.comment || '',
    })),
  })
  gradeVisible.value = true
}
function formatAnswer(answer) {
  if (!answer) return ''
  if (answer.key != null) return String(answer.key)
  if (answer.keys) return answer.keys.join('、')
  if (answer.blanks) return answer.blanks.join(' / ')
  if (answer.text != null) return String(answer.text)
  return JSON.stringify(answer)
}
async function doGrade() {
  grading.value = true
  try {
    const payload = { score: gradeForm.score, comment: gradeForm.comment }
    if (currentHw.value?.mode === 'questions') {
      payload.answer_scores = Object.fromEntries(
        gradeForm.answerItems
          .filter((item) => item.needs_manual_grading)
          .map((item) => [item.id, { score: item.manualScore, comment: item.comment }]),
      )
    }
    await gradeSubmission(gradeForm.id, payload)
    ElMessage.success('批改完成')
    gradeVisible.value = false
    openSubmissions(currentHw.value)
  } finally {
    grading.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.homework-page :deep(.data-card) { padding: 0; }
.homework-page :deep(.data-card > .el-card__body) { padding: 0; }
.module-toolbar {
  margin: 0 0 12px;
  padding: 0 0 12px;
  border-bottom: 0;
}
.module-primary-button {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  box-shadow: 0 11px 22px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.module-table {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: transparent;
  background: transparent;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  padding: 0 14px 10px;
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  background: transparent;
}
.module-table :deep(td.el-table__cell) {
  padding: 17px 14px;
  border-bottom: 10px solid transparent;
  color: #334155;
  background: rgba(255, 255, 255, 0.8);
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #fff; }
.module-table :deep(.el-table__body tr > td.el-table__cell:first-child) { border-top-left-radius: 15px; border-bottom-left-radius: 15px; }
.module-table :deep(.el-table__body tr > td.el-table__cell:last-child) { border-top-right-radius: 15px; border-bottom-right-radius: 15px; }

/* 作业卡片行（与题库列表一致） */
.hw-empty-text { color: var(--gray-700, #334155); font-size: 15px; font-weight: 700; }
.hw-empty-tip { margin-top: 4px; color: var(--gray-400, #94a3b8); font-size: 13px; }
.hw-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hw-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100, #e5e9f0);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.hw-row:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.hw-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.hw-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.hw-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gray-900, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.hw-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hw-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
}
.hw-score {
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
  font-weight: 700;
}
.hw-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.hw-action-btn {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-600, #2563eb);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.hw-action-btn:hover {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.hw-action-btn.success { color: var(--success, #16a34a); }
.hw-action-btn.warn { color: #d97706; }
.hw-action-btn.danger { color: var(--danger, #dc2626); }

@media (max-width: 768px) {
  .hw-row { flex-direction: column; align-items: stretch; gap: 12px; }
  .hw-action-group { justify-content: space-between; }
}

/* 深色模式 */
html.dark .hw-row { background: #1e293b; border-color: #334155; }
html.dark .hw-title { color: #f1f5f9; }
html.dark .hw-action-group { background: #0f172a; }
html.dark .hw-action-btn:hover { background: #334155; }
.homework-form-dialog :deep(.el-dialog),
:global(.homework-form-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.homework-form-dialog :deep(.el-dialog__header),
:global(.homework-form-dialog.el-dialog .el-dialog__header),
.homework-form-dialog :deep(.el-dialog__footer),
:global(.homework-form-dialog.el-dialog .el-dialog__footer) {
  margin: 0;
  padding: 0;
}
.homework-form-dialog :deep(.el-dialog__body),
:global(.homework-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 82px;
  padding: 18px 22px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
.creation-dialog-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 15px;
  font-size: 21px;
}
.homework-create-icon {
  color: #2563eb;
  background: #eaf2ff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.creation-dialog-heading { min-width: 0; }
.creation-dialog-title {
  color: #14213d;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  margin-left: auto;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #2563eb;
  background: #eff6ff;
}
.homework-creation-form { padding: 20px 24px 22px; }
.creation-form-grid {
  display: grid;
  grid-template-columns: clamp(340px, 25vw, 430px) minmax(0, 1fr);
  gap: 24px;
  align-items: stretch;
  height: 100%;
  min-height: 0;
}
.form-col { min-width: 0; min-height: 0; display: flex; }

/* 分组卡片（左右等高） */
.hw-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 26px 28px 28px;
  border: 1px solid rgba(191, 219, 254, 0.58);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow:
    0 24px 64px rgba(37, 99, 235, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  overflow: hidden;
  backdrop-filter: blur(18px) saturate(1.08);
}
.hw-info-card {
  overflow: auto;
}
.hw-content-card {
  overflow: hidden;
}
.hw-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.9);
  color: #0f172a;
  font-size: 17px;
  font-weight: 800;
}
.hw-card-head :deep(.el-icon) {
  color: #2563eb;
  font-size: 17px;
}
.hw-card :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

/* 发布作业：占满内容区的编辑视图 */
.homework-editor {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  color: #0f172a;
}
.homework-editor,
.homework-editor * {
  scrollbar-width: none;
}
.homework-editor::-webkit-scrollbar,
.homework-editor *::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}
.hw-editor-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  padding: 14px 30px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.08);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  backdrop-filter: blur(18px) saturate(1.08);
}
.hw-editor-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.hw-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px 0 12px;
  border: 1px solid rgba(37, 99, 235, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  color: #2563eb;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}
.hw-back-btn:hover {
  background: #eff6ff;
  border-color: rgba(37, 99, 235, 0.4);
}
.hw-editor-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.9);
  font-size: 16px;
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.18),
    0 4px 10px rgba(37, 99, 235, 0.06);
}
.hw-editor-heading { min-width: 0; }
.hw-editor-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.hw-editor-kicker {
  max-width: 34vw;
  overflow: hidden;
  padding: 3px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #64748b;
  background: rgba(248, 251, 255, 0.9);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hw-editor-title {
  color: #0f172a;
  font-size: 21px;
  font-weight: 800;
  line-height: 1.2;
  white-space: nowrap;
}
.hw-editor-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 12px;
}
.hw-editor-actions {
  display: flex;
  gap: 8px;
}
.hw-editor-actions :deep(.el-button) {
  min-width: 96px;
  height: 38px;
  padding: 0 18px;
  border-radius: 11px;
  font-weight: 700;
}
.hw-editor-actions :deep(.el-button--primary) {
  border-color: #3b82f6;
  background: #3b82f6;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.2);
}
.homework-editor .homework-creation-form {
  height: 100%;
  min-height: 0;
  padding: 0;
}
.homework-editor-body {
  min-width: 0;
  min-height: 0;
  padding: 24px 34px 30px;
  overflow: hidden;
}
.hw-editor-stats {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-left: auto;
  padding: 7px 12px;
  border: 1px solid rgba(191, 219, 254, 0.7);
  border-radius: 999px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
  font-size: 12px;
  white-space: nowrap;
}
.hw-editor-stats strong {
  color: #2563eb;
  font-size: 16px;
}

html.dark .hw-editor-title { color: #f1f5f9; }
html.dark .hw-editor-topbar { border-bottom-color: #1e293b; }
html.dark .hw-editor-icon {
  background: rgba(37, 99, 235, 0.18);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.2);
}
html.dark .hw-back-btn {
  background: rgba(30, 41, 59, 0.6);
  border-color: #334155;
  color: #93c5fd;
}
html.dark .hw-card {
  background: rgba(30, 41, 59, 0.55);
  border-color: #334155;
}
html.dark .hw-card-head {
  color: #f1f5f9;
  border-bottom-color: #334155;
}
.homework-creation-form :deep(.el-form-item) { margin-bottom: 18px; }
.homework-creation-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 8px;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
}
.homework-mode-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  width: 100%;
  max-width: 248px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.homework-mode-switch :deep(.el-radio-button) {
  min-width: 0;
  --el-radio-button-checked-bg-color: transparent;
  --el-radio-button-checked-border-color: transparent;
  --el-radio-button-checked-text-color: inherit;
}
.homework-mode-switch :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid #dbe5f2 !important;
  border-left: 0 !important;
  border-radius: 10px !important;
  background: #f8fbff !important;
  box-shadow: none !important;
  color: #64748b;
  font-size: 13px;
  font-weight: 750;
  line-height: 1;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}
.homework-mode-switch :deep(.el-radio-button__inner:hover) {
  border-color: #bfdbfe !important;
  background: #eff6ff !important;
  color: var(--el-color-primary);
}
.homework-mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: transparent !important;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
  color: #fff;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.22) !important;
}
.homework-mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner:hover) {
  color: #fff;
}
.homework-mode-switch :deep(.el-radio-button__original-radio:disabled + .el-radio-button__inner) {
  cursor: not-allowed;
  opacity: 0.58;
}
.homework-creation-form :deep(.el-input__wrapper),
.homework-creation-form :deep(.el-date-editor.el-input),
.homework-creation-form :deep(.el-input-number) {
  min-height: 48px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: none;
}
.homework-creation-form :deep(.el-input__wrapper:focus-within),
.homework-creation-form :deep(.el-date-editor.el-input:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.homework-creation-form :deep(.el-input-number) { width: 100%; }
.homework-creation-form :deep(.el-textarea__inner) {
  min-height: 150px !important;
  padding: 12px 14px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: none;
  line-height: 1.65;
}
.homework-creation-form :deep(.el-textarea__inner:focus) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: rgba(248, 250, 252, 0.82);
}
.creation-dialog-footer :deep(.el-button) {
  min-width: 88px;
  height: 38px;
  border-radius: 10px;
  font-weight: 700;
}
:global(.platform-datetime-popper.el-popper) {
  z-index: 3200 !important;
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.48) !important;
  border-radius: 18px !important;
  background: #fff !important;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.18), 0 0 0 6px rgba(219, 234, 254, 0.16) !important;
}
:global(.el-message) {
  z-index: 5200 !important;
}
:global(.homework-filter-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid #bfdbfe !important;
  border-radius: 18px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 20px 44px rgba(37, 99, 235, 0.16), 0 0 0 5px rgba(219, 234, 254, 0.28) !important;
}
:global(.homework-filter-popper .el-popper__arrow) {
  display: none;
}
:global(.homework-filter-popper .el-select-dropdown) {
  border: 0;
  border-radius: 18px;
  background: transparent;
  box-shadow: none;
}
:global(.homework-filter-popper .el-select-dropdown__wrap) {
  max-height: 360px;
}
:global(.homework-filter-popper .el-select-dropdown__list) {
  padding: 14px 0;
}
:global(.homework-filter-popper .el-select-dropdown__item) {
  height: 52px;
  padding: 0 28px;
  color: #334155;
  font-size: 16px;
  font-weight: 800;
  line-height: 52px;
}
:global(.homework-filter-popper .el-select-dropdown__item.is-hovering),
:global(.homework-filter-popper .el-select-dropdown__item:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.homework-filter-popper .el-select-dropdown__item.is-selected) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-picker-panel) {
  border: 0;
  border-radius: 18px;
  color: #334155;
  background: #fff;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker) {
  width: 560px;
}
:global(.platform-datetime-popper .el-date-picker__time-header) {
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input:first-child) {
  width: 214px;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input:last-child) {
  width: 150px;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper) {
  min-height: 36px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
:global(.platform-datetime-popper .el-date-picker__header) {
  width: 320px;
  margin: 14px 18px 8px;
}
:global(.platform-datetime-popper .el-date-picker__header-label) {
  color: #334155;
  font-size: 15px;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn) {
  width: 28px;
  height: 28px;
  margin: 0 1px;
  border-radius: 8px;
  color: #64748b;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table th) {
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-picker-panel__content) {
  width: 320px;
  margin: 12px 218px 12px 18px;
}
:global(.platform-datetime-popper .el-date-table td .el-date-table-cell) {
  width: 34px;
  height: 34px;
  margin: 1px auto;
  border-radius: 10px;
}
:global(.platform-datetime-popper .el-date-table td.available:hover .el-date-table-cell) {
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table td.available:hover span),
:global(.platform-datetime-popper .el-date-table td.today span) {
  color: #2563eb;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) .el-date-table-cell) {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.24);
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) span) {
  color: #fff;
}
:global(.platform-datetime-popper .el-picker-panel__footer) {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px 12px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button) {
  min-width: 64px;
  height: 34px;
  border-radius: 9px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button:first-child),
:global(.platform-datetime-popper .el-picker-panel__footer .el-picker-panel__link-btn:first-child) {
  display: none !important;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button--primary) {
  border-color: #3b82f6;
  color: #fff;
  background: #3b82f6;
}
:global(.platform-datetime-popper .el-time-panel) {
  top: 74px !important;
  right: 16px !important;
  left: auto !important;
  width: 178px !important;
  overflow: hidden;
  border: 1px solid #dbe5f2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12);
}
:global(.platform-datetime-popper .el-time-panel::before) {
  content: "选择时间";
  display: block;
  height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid #edf2f8;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 38px;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-time-panel__content) {
  height: 194px;
}
:global(.platform-datetime-popper .el-time-panel__content::before),
:global(.platform-datetime-popper .el-time-panel__content::after) {
  border-color: #e5edf7;
}
:global(.platform-datetime-popper .el-time-spinner__item) {
  color: #64748b;
}
:global(.platform-datetime-popper .el-time-spinner__item:hover:not(.is-disabled):not(.is-active)) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-time-spinner__item.is-active:not(.is-disabled)) {
  color: #2563eb;
  font-weight: 800;
}
:global(.platform-datetime-popper .el-time-panel__footer) {
  height: auto;
  padding: 9px 10px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-time-panel__btn) {
  min-width: 58px;
  height: 32px;
  margin: 0 2px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-time-panel__btn.confirm) {
  color: #fff;
  background: #3b82f6;
}
@media (max-width: 720px) {
  .homework-form-dialog :deep(.el-dialog),
  :global(.homework-form-dialog.el-dialog) { width: calc(100% - 28px) !important; }
  .creation-form-grid { grid-template-columns: 1fr; }
  .form-span-full { grid-column: auto; }
  .creation-dialog-header { padding: 16px 18px; }
  .homework-creation-form { padding: 18px; }
  .creation-dialog-footer { padding: 14px 18px 16px; }
}
.grade-content {
  border: 1px solid #e2ebf7;
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 16px;
  background: #f8fbff;
}
.grade-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 800;
  margin-bottom: 6px;
}
.grade-text {
  color: #334155;
  white-space: pre-wrap;
  line-height: 1.6;
}
.total-hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}
:global(.grade-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(191, 219, 254, 0.72);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18);
}
:global(.grade-dialog .el-dialog__header) {
  padding: 20px 22px 14px;
  border-bottom: 1px solid #edf2f8;
}
:global(.grade-dialog .el-dialog__title) {
  color: #0f172a;
  font-size: 18px;
  font-weight: 850;
}
:global(.grade-dialog .el-dialog__body) {
  padding: 18px 22px;
}
:global(.grade-dialog .el-dialog__footer) {
  padding: 14px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
.freeze-tip { margin-left: 12px; color: #16a34a; font-size: 13px; }
.question-builder {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
}
.question-pool-panel {
  flex: 0 0 auto;
  display: grid;
  gap: 12px;
  min-width: 0;
}
.question-filters {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.question-filters :deep(.el-select__wrapper) {
  min-height: 44px;
  padding: 0 12px;
  border-radius: 13px;
  background: rgba(248, 251, 255, 0.94);
  box-shadow: inset 0 0 0 1px #dbe5ef, 0 4px 12px rgba(37, 99, 235, 0.035);
  transition: background-color 0.18s ease, box-shadow 0.18s ease;
}
.question-filters :deep(.el-select__wrapper:hover),
.question-filters :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe, 0 0 0 3px rgba(59, 130, 246, 0.09);
}
.question-pool-table {
  overflow: hidden;
  border: 1px solid #e5edf7;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.045);
}
.question-pool-table :deep(.el-table__inner-wrapper::before) { display: none; }
.question-pool-table :deep(.el-table__body tr) {
  transition: background-color 0.18s ease;
}
.question-pool-table :deep(th.el-table__cell) {
  height: 44px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 13px;
  font-weight: 800;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.question-pool-table :deep(td.el-table__cell) {
  height: 52px;
  border-bottom-color: #edf2f8;
  color: #334155;
}
.question-pool-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: #f8fbff;
}
.pool-stem {
  display: block;
  overflow: hidden;
  color: #334155;
  font-size: 14px;
  font-weight: 560;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pool-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  height: 24px;
  padding: 0 8px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 750;
  white-space: nowrap;
}
.pool-tag.type {
  border: 1px solid #bfdbfe;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.72);
}
.pool-tag.difficulty {
  border: 1px solid #dbeafe;
  color: #64748b;
  background: #f8fbff;
}
.pool-tag.difficulty-easy {
  border-color: #bbf7d0;
  color: #16a34a;
  background: rgba(240, 253, 244, 0.72);
}
.pool-tag.difficulty-medium {
  border-color: #fed7aa;
  color: #d97706;
  background: rgba(255, 247, 237, 0.78);
}
.pool-tag.difficulty-hard {
  border-color: #fecaca;
  color: #ef4444;
  background: rgba(254, 242, 242, 0.78);
}
.pool-action {
  height: 28px;
  min-width: 50px;
  padding: 0 10px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.78);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}
.pool-action:hover {
  border-color: #60a5fa;
  color: #fff;
  background: #3b82f6;
}
.pool-action.selected {
  border-color: #fecaca;
  color: #ef4444;
  background: #fef2f2;
}
.pool-action.selected:hover {
  border-color: #ef4444;
  color: #fff;
  background: #ef4444;
}
.question-pool-table :deep(.el-scrollbar__bar),
.selected-list-scroll :deep(.el-scrollbar__bar) {
  display: none !important;
}
.selected-panel {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  margin-top: 2px;
  padding: 14px;
  border: 1px solid #e5edf7;
  border-radius: 18px;
  background: rgba(248, 251, 255, 0.68);
}
.selected-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  color: #334155;
  font-size: 15px;
}
.selected-header strong {
  font-weight: 800;
}
.selected-header span { color: #2563eb; font-weight: 700; }
.selected-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 1;
  min-height: 120px;
  margin-top: 12px;
  padding: 15px 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  color: #94a3b8;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.5);
}
.selected-list-scroll {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
}
.selected-list-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden;
}
.selected-list-scroll :deep(.el-scrollbar__view) {
  min-height: 100%;
}
.selected-list {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 0;
  padding: 0 2px 2px 0;
}
.selected-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto 72px 18px minmax(128px, auto);
  align-items: center;
  gap: 10px;
  min-height: 48px;
  min-width: 0;
  padding: 9px 12px;
  border: 1px solid #e8eef7;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 5px 14px rgba(37, 99, 235, 0.035);
}
.question-order {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
  font-weight: 800;
  box-shadow: inset 0 0 0 1px rgba(191, 219, 254, 0.72);
}
.selected-stem { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.score-input {
  width: 72px;
  flex: none;
}
.score-input :deep(.el-input__wrapper) {
  min-height: 34px;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbeafe;
}
.score-input :deep(.el-input__inner) {
  text-align: center;
  font-weight: 700;
}
.score-input :deep(input::-webkit-outer-spin-button),
.score-input :deep(input::-webkit-inner-spin-button) {
  margin: 0;
  appearance: none;
}
.score-input :deep(input[type='number']) {
  appearance: textfield;
}
.score-unit {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}
.selected-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  min-width: 128px;
  white-space: nowrap;
}
:global(.grading-drawer-mask) {
  background: rgba(15, 23, 42, 0.38) !important;
  backdrop-filter: blur(2px);
}
:global(.grading-drawer.el-drawer) {
  margin: 18px 22px 18px 0;
  height: calc(100% - 36px) !important;
  border: 1px solid rgba(191, 219, 254, 0.72);
  border-radius: 22px;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  box-shadow: 0 28px 70px rgba(15, 23, 42, 0.22), 0 0 0 8px rgba(219, 234, 254, 0.24);
}
:global(.grading-drawer .el-drawer__body) {
  height: 100%;
  padding: 0;
}
.grading-panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
  height: 100%;
  padding: 24px 26px 26px;
  color: #0f172a;
}
.grading-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.grading-heading {
  min-width: 0;
}
.grading-kicker {
  color: #2563eb;
  font-size: 13px;
  font-weight: 800;
}
.grading-title {
  margin-top: 6px;
  overflow: hidden;
  color: #0f172a;
  font-size: 22px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.grading-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.grading-meta span {
  padding: 5px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-weight: 700;
}
.grading-close {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background-color 0.18s ease;
}
.grading-close:hover {
  border-color: #bfdbfe;
  color: #2563eb;
  background: #eff6ff;
}
.grading-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.grading-stat {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid #e2ebf7;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.055);
}
.grading-stat span {
  display: block;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 750;
}
.grading-stat strong {
  display: block;
  margin-top: 6px;
  color: #2563eb;
  font-size: 24px;
  font-weight: 850;
  line-height: 1;
}
.grading-table-card {
  min-height: 0;
  overflow: hidden;
  border: 1px solid #e2ebf7;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
}
.grading-table {
  height: 100%;
  --el-table-border-color: #edf2f8;
  --el-table-header-bg-color: #f8fbff;
  --el-table-row-hover-bg-color: #eff6ff;
}
.grading-table :deep(.el-table__inner-wrapper) {
  height: 100%;
}
.grading-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.grading-table :deep(th.el-table__cell) {
  height: 52px;
  color: #64748b;
  font-weight: 800;
  background: #f8fbff;
}
.grading-table :deep(td.el-table__cell) {
  height: 58px;
  color: #334155;
}
.grading-score {
  color: #2563eb;
  font-weight: 850;
}
.grading-muted {
  color: #94a3b8;
  font-weight: 700;
}
.grading-action {
  height: 30px;
  padding: 0 12px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.grading-action:hover {
  border-color: #60a5fa;
  color: #fff;
  background: #3b82f6;
}
.grading-empty {
  display: grid;
  min-height: 360px;
  place-items: center;
}
.grading-empty :deep(.el-empty__description) {
  color: #94a3b8;
  font-size: 14px;
}
.answer-review-list { display: grid; gap: 12px; max-height: 55vh; overflow: auto; margin-bottom: 18px; }
.answer-review-item {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
.answer-review-head { display: flex; justify-content: space-between; gap: 16px; line-height: 1.55; }
.answer-review-head span { flex: none; color: #2563eb; }
.student-answer { color: #475569; white-space: pre-wrap; }
.manual-grade-row { display: grid; grid-template-columns: 140px 1fr; gap: 10px; }
.attachment-panel {
  display: grid;
  flex: 1;
  place-items: center;
  min-height: 520px;
}
.attachment-uploader { width: min(520px, 86%); }
.attachment-uploader :deep(.el-upload),
.attachment-uploader :deep(.el-upload-dragger) { width: 100%; }
.attachment-uploader :deep(.el-upload-dragger) {
  padding: 64px 24px;
  border: 1px dashed #bfdbfe;
  border-radius: 18px;
  background: linear-gradient(145deg, #f8fbff, #f1f7ff);
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}
.attachment-uploader :deep(.el-upload-dragger:hover) {
  transform: translateY(-2px);
  border-color: #60a5fa;
  background: #eff6ff;
}
.attachment-upload-icon { color: #3b82f6; font-size: 42px; }
.attachment-upload-title { margin-top: 15px; color: #334155; font-size: 15px; font-weight: 750; }
.attachment-upload-tip { margin-top: 7px; color: #94a3b8; font-size: 13px; }
.existing-attachment {
  width: min(520px, 86%);
  margin-top: 12px;
  padding: 12px 16px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: #2563eb;
  background: #f8fbff;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}
.existing-attachment:hover { border-color: #93c5fd; background: #eff6ff; }
@media (max-width: 1180px) {
  .creation-form-grid { grid-template-columns: 320px minmax(0, 1fr); gap: 16px; }
  .hw-card { padding: 20px; }
  .selected-item {
    grid-template-columns: 28px minmax(0, 1fr) auto 72px 18px;
  }
  .selected-actions {
    grid-column: 2 / -1;
    justify-content: flex-start;
  }
}
@media (max-width: 920px) {
  .creation-form-grid { grid-template-columns: 1fr; }
  .hw-card { min-height: auto; }
  .hw-editor-topbar { flex-wrap: wrap; }
  .hw-editor-actions { width: 100%; justify-content: flex-end; }
  .homework-editor-body { overflow: auto; }
  .creation-form-grid { height: auto; }
  .form-col { min-height: auto; }
  .hw-content-card { min-height: 720px; }
}
@media (max-width: 720px) {
  .question-filters { grid-template-columns: 1fr; }
  .selected-header { align-items: flex-start; flex-direction: column; gap: 5px; }
  .selected-item {
    grid-template-columns: 28px minmax(0, 1fr) auto;
  }
  .score-input {
    grid-column: 2;
    width: 90px;
  }
  .score-unit {
    grid-column: 3;
  }
  .selected-actions {
    grid-column: 2 / -1;
  }
}
</style>
