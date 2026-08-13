<template>
  <div class="page-container wrong-page">
    <!-- 工具栏 -->
    <div class="wrong-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-title">错题本</span>
        <span v-if="!loading" class="wrong-count">{{ mergedRows.length }} 道</span>
        <el-select
          v-if="!fixedCourseId"
          v-model="courseId"
          class="module-select"
          popper-class="module-select-popper"
          placeholder="全部课程"
          clearable
          style="width: 220px"
          @change="load"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </div>
      <el-button class="add-btn" type="primary" :icon="Plus" @click="openAdd">添加错题</el-button>
    </div>

    <div v-loading="loading" class="wrong-list animate-list">
      <div v-for="(q, i) in mergedRows" :key="q.key" class="wrong-card" :class="{ expanded: expandedKeys.has(q.key) }">
        <!-- 折叠头 -->
        <button type="button" class="q-head" @click="toggle(q.key)">
          <span class="q-idx">{{ String(i + 1).padStart(2, '0') }}</span>
          <span class="q-type">{{ q.typeLabel }}</span>
          <span class="q-scene">{{ q.sceneLabel }}</span>
          <span class="q-stem-preview">{{ q.stem }}</span>
          <span class="review-label" :class="{ mastered: masteredSet.has(q.key) }">
            {{ masteredSet.has(q.key) ? '已巩固' : '待巩固' }}
          </span>
          <el-icon class="q-caret"><ArrowDown v-if="expandedKeys.has(q.key)" /><ArrowRight v-else /></el-icon>
        </button>

        <!-- 展开内容 -->
        <div v-if="expandedKeys.has(q.key)" class="q-body">
          <div class="q-stem">{{ q.stem }}</div>

          <template v-if="q.source === 'auto'">
            <div v-if="q.options?.length" class="q-options">
              <div v-for="o in q.options" :key="o.key" class="opt" :class="optClass(q, o.key)">
                <span class="opt-key">{{ o.key }}</span>
                <span class="opt-text">{{ o.text }}</span>
                <span v-if="isCorrectOption(q, o.key)" class="opt-state right">
                  <el-icon><CircleCheckFilled /></el-icon>正确答案
                </span>
                <span v-else-if="isMyOption(q, o.key)" class="opt-state wrong">
                  <el-icon><CircleCloseFilled /></el-icon>你的选择
                </span>
              </div>
            </div>
            <div v-else class="answer-grid">
              <div class="answer-box wrong">
                <div class="answer-label"><el-icon><CircleCloseFilled /></el-icon>你的答案</div>
                <strong>{{ fmt(q.my_answer) }}</strong>
              </div>
              <div class="answer-box right">
                <div class="answer-label"><el-icon><CircleCheckFilled /></el-icon>正确答案</div>
                <strong>{{ fmt(q.correct_answer) }}</strong>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="answer-grid">
              <div class="answer-box wrong">
                <div class="answer-label"><el-icon><CircleCloseFilled /></el-icon>我的答案</div>
                <strong>{{ q.my_answer || '—' }}</strong>
              </div>
              <div class="answer-box right">
                <div class="answer-label"><el-icon><CircleCheckFilled /></el-icon>正确答案</div>
                <strong>{{ q.correct_answer || '—' }}</strong>
              </div>
            </div>
          </template>

          <div v-if="q.analysis" class="analysis">
            <div class="analysis-title">
              <el-icon><Reading /></el-icon>{{ q.source === 'auto' ? '答案解析' : '解析 / 笔记' }}
            </div>
            <div class="analysis-copy">{{ q.analysis }}</div>
          </div>

          <div class="q-foot">
            <span class="q-time">{{ fmtTime(q.time) }}</span>
            <div class="q-foot-actions">
              <el-button
                v-if="q.source === 'manual'"
                link
                type="danger"
                :icon="Delete"
                @click.stop="askDelete(q)"
              >删除</el-button>
              <el-button
                v-else
                link
                type="info"
                :icon="Remove"
                @click.stop="askRemove(q)"
              >移除</el-button>
              <el-button
                size="small"
                round
                :type="masteredSet.has(q.key) ? 'success' : 'primary'"
                :plain="!masteredSet.has(q.key)"
                :icon="CircleCheckFilled"
                :loading="masteringKeys.has(q.key)"
                :disabled="masteringKeys.has(q.key)"
                @click.stop="toggleMastery(q)"
              >
                {{ masteredSet.has(q.key) ? '已巩固' : '标记为已巩固' }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!loading && !mergedRows.length" class="empty-panel">
        <el-empty :description="rows.length || notes.length ? '没有匹配的错题' : '太棒了，暂无错题！也可以点右上角手动添加'" />
      </div>
    </div>

    <!-- 手动添加错题 -->
    <el-dialog v-model="addVisible" width="560px" align-center :show-close="false" class="note-dialog">
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon note-dialog-icon">
            <el-icon><EditPen /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">添加错题</div>
            <div class="creation-dialog-subtitle">手动整理一道易错题，加入错题本随时复习</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="addVisible = false" />
        </div>
      </template>

      <el-form label-position="top" class="note-form">
        <el-form-item label="题干">
          <el-input v-model="noteForm.stem" type="textarea" :rows="3" resize="none" placeholder="题目内容" />
        </el-form-item>
        <div class="note-form-grid">
          <el-form-item label="我的答案">
            <el-input v-model="noteForm.my_answer" placeholder="如 A / 填空内容" />
          </el-form-item>
          <el-form-item label="正确答案">
            <el-input v-model="noteForm.correct_answer" placeholder="如 C / 参考答案" />
          </el-form-item>
        </div>
        <el-form-item label="解析 / 笔记">
          <el-input v-model="noteForm.analysis" type="textarea" :rows="3" resize="none" placeholder="错因分析、知识点笔记（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="addVisible = false">取消</el-button>
          <el-button type="primary" :loading="adding" @click="saveNote">保存</el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      :title="deleteTarget?.kind === 'remove' ? '移除错题' : '删除错题'"
      :item-name="deleteTarget?.stem"
      :description="deleteTarget?.kind === 'remove'
        ? '移除后本题不再出现在错题本中，答题记录不受影响。'
        : '删除后这条手动错题将无法恢复，此操作无法撤销。'"
      :action-text="deleteTarget?.kind === 'remove' ? '移除' : '删除'"
      :confirm-text="deleteTarget?.kind === 'remove' ? '确认移除' : '确认删除'"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowDown, ArrowRight, CircleCheckFilled, CircleCloseFilled, Close, Delete, EditPen, Plus, Reading, Remove,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listClasses } from '@/api/classroom'
import { getMyWrongQuestions } from '@/api/analytics'
import { createWrongNote, deleteWrongNote, listWrongMastery, listWrongNotes, toggleWrongMastery } from '@/api/question'

const route = useRoute()
const courses = ref([])
const courseId = ref(null)
const rows = ref([])
const notes = ref([])
const masteredSet = ref(new Set())
const masteringKeys = ref(new Set())
const removedSet = ref(new Set())
const loading = ref(false)
const expandedKeys = ref(new Set())
const fixedCourseId = computed(() => Number(route.params.id) || null)

const keyword = computed(() => String(route.query.search || '').trim().toLowerCase())

// 自动收录 + 手动添加，统一成同一种展示结构
const mergedRows = computed(() => {
  const auto = rows.value.map((q) => ({
    key: `auto-${q.question_id}`,
    source: 'auto',
    stem: q.stem,
    typeLabel: q.qtype_display,
    sceneLabel: q.scene,
    time: q.submitted_at,
    options: q.options,
    my_answer: q.my_answer,
    correct_answer: q.correct_answer,
    analysis: q.analysis,
  }))
  const manual = notes.value.map((n) => ({
    key: `manual-${n.id}`,
    source: 'manual',
    noteId: n.id,
    stem: n.stem,
    typeLabel: '手动添加',
    sceneLabel: n.course_name || '错题本',
    time: n.created_at,
    options: null,
    my_answer: n.my_answer,
    correct_answer: n.correct_answer,
    analysis: n.analysis,
  }))
  let list = [...manual, ...auto].filter((q) => !removedSet.value.has(q.key))
  if (keyword.value) {
    list = list.filter((q) => [q.stem, q.analysis, q.sceneLabel, q.typeLabel]
      .some((text) => String(text || '').toLowerCase().includes(keyword.value)))
  }
  return list
})

function toggle(key) {
  const next = new Set(expandedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedKeys.value = next
}

function fmt(a) {
  if (!a) return '（未作答）'
  if (a.key) return a.key
  if (a.keys) return a.keys.join(', ')
  if (a.blanks) return a.blanks.join(' / ')
  if (a.text) return a.text
  return '—'
}
function fmtTime(t) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}
function isCorrectOption(q, key) {
  return q.correct_answer?.key === key || (q.correct_answer?.keys || []).includes(key)
}
function isMyOption(q, key) {
  return q.my_answer?.key === key || (q.my_answer?.keys || []).includes(key)
}
function optClass(q, key) {
  if (isCorrectOption(q, key)) return 'opt-right'
  if (isMyOption(q, key)) return 'opt-wrong'
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
    const activeCourseId = fixedCourseId.value || courseId.value
    const params = activeCourseId ? { course: activeCourseId } : {}
    const [wrong, manual, mastery] = await Promise.all([
      getMyWrongQuestions(params),
      listWrongNotes(params),
      listWrongMastery(params),
    ])
    rows.value = wrong.results ?? []
    notes.value = manual.results ?? manual ?? []
    const set = new Set()
    ;(mastery?.questions || []).forEach((id) => set.add(`auto-${id}`))
    ;(mastery?.notes || []).forEach((id) => set.add(`manual-${id}`))
    masteredSet.value = set
    const removed = new Set()
    ;(mastery?.removed_questions || []).forEach((id) => removed.add(`auto-${id}`))
    ;(mastery?.removed_notes || []).forEach((id) => removed.add(`manual-${id}`))
    removedSet.value = removed
  } finally {
    loading.value = false
  }
}

// ---- 巩固标记 ----
async function toggleMastery(q) {
  if (masteringKeys.value.has(q.key)) return
  masteringKeys.value = new Set([...masteringKeys.value, q.key])
  const payload = q.source === 'auto'
    ? { question: Number(q.key.replace('auto-', '')) }
    : { note: q.noteId }
  try {
    const res = await toggleWrongMastery(payload)
    const next = new Set(masteredSet.value)
    if (res?.mastered) next.add(q.key)
    else next.delete(q.key)
    masteredSet.value = next
    ElMessage.success(res?.mastered ? '已标记为已巩固' : '已取消巩固标记')
  } finally {
    const pending = new Set(masteringKeys.value)
    pending.delete(q.key)
    masteringKeys.value = pending
  }
}

// ---- 手动添加 ----
const addVisible = ref(false)
const adding = ref(false)
const noteForm = reactive({ stem: '', my_answer: '', correct_answer: '', analysis: '' })

function openAdd() {
  Object.assign(noteForm, { stem: '', my_answer: '', correct_answer: '', analysis: '' })
  addVisible.value = true
}

async function saveNote() {
  if (!noteForm.stem.trim()) return ElMessage.warning('请填写题干')
  const targetCourse = fixedCourseId.value || courseId.value || courses.value[0]?.id
  if (!targetCourse) return ElMessage.warning('请先加入课程')
  adding.value = true
  try {
    await createWrongNote({
      course: targetCourse,
      stem: noteForm.stem.trim(),
      my_answer: noteForm.my_answer.trim(),
      correct_answer: noteForm.correct_answer.trim(),
      analysis: noteForm.analysis.trim(),
    })
    ElMessage.success('已加入错题本')
    addVisible.value = false
    load()
  } finally {
    adding.value = false
  }
}

// ---- 删除手动错题 / 移除自动错题 ----
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

function askDelete(q) {
  deleteTarget.value = { ...q, kind: 'delete' }
  deleteVisible.value = true
}

function askRemove(q) {
  deleteTarget.value = { ...q, kind: 'remove' }
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    if (deleteTarget.value.kind === 'remove') {
      await toggleWrongMastery({
        question: Number(deleteTarget.value.key.replace('auto-', '')),
        action: 'remove',
      })
      removedSet.value = new Set([...removedSet.value, deleteTarget.value.key])
      ElMessage.success('已从错题本移除')
    } else {
      await deleteWrongNote(deleteTarget.value.noteId)
      ElMessage.success('已删除')
    }
    deleteVisible.value = false
    deleteTarget.value = null
    load()
  } finally {
    deleting.value = false
  }
}

watch(fixedCourseId, (id) => {
  courseId.value = id || null
  load()
})

onMounted(() => {
  if (fixedCourseId.value) courseId.value = fixedCourseId.value
  loadCourses()
  load()
})
</script>

<style scoped>
.wrong-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-title {
  color: var(--gray-900);
  font-size: 17px;
  font-weight: 800;
}
.wrong-count {
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 700;
}
.add-btn {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.add-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.2);
}

/* 错题卡片（默认折叠，点击展开） */
.wrong-list {
  display: grid;
  gap: 12px;
}
.wrong-card {
  border: 1px solid var(--gray-100);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.wrong-card:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.4);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.09);
}
.wrong-card.expanded {
  border-color: rgba(96, 165, 250, 0.5);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}

.q-head {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 14px 16px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.q-idx {
  min-width: 34px;
  height: 26px;
  padding: 0 8px;
  border-radius: 8px;
  background: #eaf2ff;
  color: #2563eb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}
.q-type,
.q-scene {
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 650;
  flex-shrink: 0;
}
.q-type {
  color: #2563eb;
  background: #eff6ff;
}
.q-scene {
  color: #64748b;
  background: #f3f6fa;
}
.q-stem-preview {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--gray-700);
  font-size: 13.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-label {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  color: #b45309;
  background: #fff7ed;
  font-size: 12px;
  font-weight: 650;
}
.review-label.mastered {
  color: #16a34a;
  background: #f0fdf4;
}
.q-foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.q-caret {
  flex-shrink: 0;
  color: var(--gray-400);
  font-size: 14px;
  transition: transform 0.18s ease;
}

.q-body {
  padding: 0 18px 16px;
  border-top: 1px dashed var(--gray-200);
  animation: row-enter 0.3s ease both;
}
.q-stem {
  margin: 14px 0 16px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.65;
}

.q-options {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}
.opt {
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid #e9eef5;
  border-radius: 12px;
  background: #f8fafc;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
  line-height: 1.5;
}
.opt-key {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #64748b;
  background: #fff;
  box-shadow: inset 0 0 0 1px #e2e8f0;
  font-size: 12px;
  font-weight: 750;
}
.opt-text {
  min-width: 0;
  flex: 1;
}
.opt-right {
  border-color: #bbf7d0;
  background: #f2fcf5;
  color: #166534;
}
.opt-right .opt-key {
  color: #15803d;
  background: #dcfce7;
  box-shadow: none;
}
.opt-wrong {
  border-color: #fecaca;
  background: #fff6f6;
  color: #991b1b;
}
.opt-wrong .opt-key {
  color: #dc2626;
  background: #fee2e2;
  box-shadow: none;
}
.opt-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 700;
}
.opt-state.right {
  color: #16a34a;
}
.opt-state.wrong {
  color: #dc2626;
}

.answer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.answer-box {
  min-width: 0;
  min-height: 66px;
  padding: 12px 14px;
  border: 1px solid;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
}
.answer-box.wrong {
  border-color: #fee2e2;
  background: #fff8f8;
}
.answer-box.right {
  border-color: #dcfce7;
  background: #f7fdf8;
}
.answer-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
}
.answer-box.wrong .answer-label .el-icon {
  color: #ef4444;
}
.answer-box.right .answer-label .el-icon {
  color: #16a34a;
}
.answer-box strong {
  overflow-wrap: anywhere;
  color: #0f172a;
  font-size: 14px;
  line-height: 1.5;
}

.analysis {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid #e6edf8;
  border-radius: 14px;
  background: #f8fbff;
}
.analysis-title {
  margin-bottom: 7px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: #2563eb;
  font-size: 12.5px;
  font-weight: 750;
}
.analysis-copy {
  color: #526076;
  font-size: 13.5px;
  line-height: 1.75;
}

.q-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
}
.q-time {
  color: var(--gray-400);
  font-size: 12px;
}

.empty-panel {
  min-height: 300px;
  border: 1px solid #e8edf5;
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}

/* 添加错题弹窗 */
.note-dialog :deep(.el-dialog),
:global(.note-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.note-dialog :deep(.el-dialog__header),
:global(.note-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}
.note-dialog :deep(.el-dialog__body),
:global(.note-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}
.note-dialog :deep(.el-dialog__footer),
:global(.note-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 86px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.creation-dialog-icon {
  width: 44px;
  height: 44px;
  display: grid;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  font-size: 21px;
}
.note-dialog-icon {
  background: #e8f4ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}
.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}
.creation-dialog-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}
.note-form {
  padding: 20px 24px 8px;
}
.note-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}
.note-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
}
.note-form :deep(.el-input__wrapper),
.note-form :deep(.el-textarea__inner) {
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
  transition: box-shadow 0.2s ease, background-color 0.2s ease;
}
.note-form :deep(.el-input__wrapper.is-focus),
.note-form :deep(.el-textarea__inner:focus) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 20px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}
.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}
.creation-dialog-footer :deep(.el-button--primary) {
  box-shadow: 0 9px 18px rgba(37, 99, 235, 0.22);
}

@media (max-width: 768px) {
  .q-stem-preview {
    font-size: 12.5px;
  }
  .q-scene {
    display: none;
  }
  .answer-grid {
    grid-template-columns: 1fr;
  }
  .note-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
