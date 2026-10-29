<template>
  <el-dialog
    :model-value="modelValue"
    width="640px"
    align-center
    :show-close="false"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    class="class-graduate-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @closed="preview = null"
  >
    <template #header>
      <div class="grad-head">
        <span class="grad-icon">
          <el-icon><School /></el-icon>
        </span>
        <div class="grad-heading">
          <div class="grad-title">整班毕业</div>
          <div class="grad-subtitle">{{ classroom?.name || '' }} · 名单预览不写库，确认后才执行</div>
        </div>
        <el-button text circle class="grad-close" :disabled="loading" aria-label="关闭" @click="close">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </template>

    <div v-loading="loadingPreview" class="grad-body">
      <div v-if="loadError" class="grad-empty">{{ loadError }}</div>
      <div v-else-if="preview && !preview.student_count" class="grad-empty">
        该班没有可毕业的学生（需要存在班级占用关系且在读的学生）
      </div>
      <template v-else-if="preview">
        <div class="grad-class-meta">
          <span>{{ preview.classroom.enrollment_year }} 级 · {{ preview.classroom.duration_years }} 年制</span>
          <span v-if="preview.classroom.graduate_year">预计 {{ preview.classroom.graduate_year }} 年毕业</span>
          <el-tag v-if="!preview.classroom.year_reached" type="warning" size="small" effect="light" round>未到毕业年份</el-tag>
        </div>

        <div class="grad-section">
          <div class="grad-section-title">将毕业 {{ preview.student_count }} 人</div>
          <div class="grad-stu-list">
            <div v-for="s in preview.students" :key="s.id" class="grad-stu-row">
              <span class="grad-stu-no">{{ s.username }}</span>
              <span class="grad-stu-name">{{ s.name }}</span>
              <el-tag size="small" type="info" effect="plain" round>在读</el-tag>
            </div>
          </div>
        </div>

        <div v-if="preview.transferred.length" class="grad-note warn">
          <el-icon><WarningFilled /></el-icon>
          <span>
            已转走/移出 {{ preview.transferred.length }} 人，不在本次毕业范围：
            {{ preview.transferred.map((t) => t.name).join('、') }}
          </span>
        </div>

        <template v-if="blockerCount">
          <div class="grad-note danger">
            <el-icon><WarningFilled /></el-icon>
            <span>有 {{ blockerCount }} 项在途内容，毕业后学生将无法继续提交：</span>
          </div>
          <div class="grad-blockers">
            <div v-for="(b, i) in preview.blockers.in_progress_exams" :key="`e${i}`" class="grad-blocker-row">
              <span class="grad-blocker-tag exam">考试中</span>
              <span class="grad-blocker-text">《{{ b.exam }}》 · {{ b.student }}</span>
            </div>
            <div v-for="(h, i) in preview.blockers.open_homeworks" :key="`h${i}`" class="grad-blocker-row">
              <span class="grad-blocker-tag hw">未截止</span>
              <span class="grad-blocker-text">《{{ h.title }}》{{ h.deadline ? ` · 截止 ${fmtDeadline(h.deadline)}` : '' }}</span>
            </div>
          </div>
          <el-checkbox v-model="force" class="grad-force">我已了解，仍要强制毕业</el-checkbox>
        </template>
        <el-checkbox v-else-if="!preview.classroom.year_reached" v-model="force" class="grad-force">
          未到预计毕业年份，确认强制提前毕业
        </el-checkbox>
      </template>
    </div>

    <template #footer>
      <div class="grad-footer">
        <el-button :disabled="loading" @click="close">取消</el-button>
        <el-button type="primary" :loading="loading" :disabled="!canConfirm" @click="confirmGraduate">
          确认毕业
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Close, School, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { graduatePreview, graduateClass } from '@/api/classroom'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  classroom: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'done'])

const preview = ref(null)
const loadingPreview = ref(false)
const loading = ref(false)
const force = ref(false)
const loadError = ref('')

const blockerCount = computed(() => {
  const b = preview.value?.blockers
  return b ? (b.in_progress_exams?.length || 0) + (b.open_homeworks?.length || 0) : 0
})
// 有在途内容或未到毕业年份时，必须显式勾选强制才能确认（与后端 409 分级一致）
const needsForce = computed(() => blockerCount.value > 0 || preview.value?.classroom?.year_reached === false)
const canConfirm = computed(() =>
  Boolean(preview.value?.student_count) && (!needsForce.value || force.value))

watch(() => props.modelValue, (open) => {
  if (open) loadPreview()
})

async function loadPreview() {
  if (!props.classroom?.id) return
  loadingPreview.value = true
  loadError.value = ''
  force.value = false
  try {
    preview.value = await graduatePreview(props.classroom.id)
  } catch (err) {
    loadError.value = err?.message || '预览加载失败，请重试'
  } finally {
    loadingPreview.value = false
  }
}

async function confirmGraduate() {
  loading.value = true
  try {
    const result = await graduateClass(props.classroom.id, { force: force.value, note: '' })
    ElMessage.success(`已毕业 ${result.graduated_count} 名学生`)
    emit('done', result)
    close()
  } catch (err) {
    // 预览之后被别人推进出新的在途内容（409 带清单）：刷新预览，让管理员重新过目
    if (err?.data?.blockers || err?.data?.expected_graduate_year) {
      await loadPreview()
    }
  } finally {
    loading.value = false
  }
}

function fmtDeadline(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function close() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
:global(.class-graduate-dialog) {
  overflow: hidden;
  max-width: calc(100vw - 32px);
  border: 1px solid rgba(59, 130, 246, 0.14);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 28px 72px rgba(45, 78, 132, 0.2);
}
:global(.class-graduate-dialog .el-dialog__header) {
  padding: 0;
  margin: 0;
}
:global(.class-graduate-dialog .el-dialog__body) {
  padding: 0 28px 24px;
}
:global(.class-graduate-dialog .el-dialog__footer) {
  padding: 0 28px 24px;
}

.grad-head {
  display: flex;
  align-items: center;
  min-height: 88px;
  padding: 20px 28px;
  background: linear-gradient(180deg, #f6f9ff 0%, #fff 100%);
  border-bottom: 1px solid #edf2fa;
}
.grad-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 48px;
  width: 48px;
  height: 48px;
  margin-right: 14px;
  border-radius: 12px;
  color: #2563eb;
  font-size: 23px;
  background: #eff6ff;
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
}
.grad-heading {
  min-width: 0;
  flex: 1;
}
.grad-title {
  color: #17233d;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.4;
}
.grad-subtitle {
  margin-top: 3px;
  color: #8a96aa;
  font-size: 13px;
}
.grad-close {
  flex: 0 0 auto;
  margin-left: 16px;
  color: #9aa5b5;
  font-size: 18px;
}

.grad-body {
  padding-top: 20px;
  min-height: 120px;
}
.grad-empty {
  padding: 28px 12px;
  color: #8a96aa;
  font-size: 13.5px;
  text-align: center;
}

.grad-class-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  color: #475569;
  font-size: 13px;
}

.grad-section {
  margin-top: 16px;
}
.grad-section-title {
  margin-bottom: 8px;
  color: #17233d;
  font-size: 14px;
  font-weight: 700;
}
.grad-stu-list {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  background: #f8fafc;
}
.grad-stu-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-bottom: 1px solid #eef2f7;
}
.grad-stu-row:last-child {
  border-bottom: none;
}
.grad-stu-no {
  min-width: 96px;
  color: #475569;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
}
.grad-stu-name {
  flex: 1;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
}

.grad-note {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 14px;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.6;
}
.grad-note .el-icon {
  flex: 0 0 auto;
  margin-top: 3px;
}
.grad-note.warn {
  border: 1px solid #fde8c8;
  color: #a16207;
  background: #fffbeb;
}
.grad-note.warn .el-icon {
  color: #f59e0b;
}
.grad-note.danger {
  border: 1px solid #ffdcdc;
  color: #b84a4a;
  background: #fff5f5;
}
.grad-note.danger .el-icon {
  color: #ef5350;
}

.grad-blockers {
  margin-top: 8px;
  border: 1px solid #f3e2e2;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.grad-blocker-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid #f7efef;
}
.grad-blocker-row:last-child {
  border-bottom: none;
}
.grad-blocker-tag {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 700;
}
.grad-blocker-tag.exam {
  color: #b84a4a;
  background: #fdeeee;
}
.grad-blocker-tag.hw {
  color: #a16207;
  background: #fdf3e0;
}
.grad-blocker-text {
  color: #475569;
  font-size: 12.5px;
}

.grad-force {
  margin-top: 12px;
}

.grad-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 20px;
  border-top: 1px solid #edf2fa;
}
.grad-footer .el-button {
  min-width: 92px;
}

@media (max-width: 560px) {
  :global(.class-graduate-dialog .el-dialog__body),
  :global(.class-graduate-dialog .el-dialog__footer) {
    padding: 0 20px 20px;
  }
  .grad-head {
    padding: 18px 20px;
  }
}
</style>
