<template>
  <!--
    草稿批次预览与入库（文档导入 / AI 生题共用）：
    逐题内嵌 QuestionFormFields 编辑（防抖回传 drafts），勾选/全部批量入库，
    入库即从批次移除（save 管道），全部处理完批次自动关闭。
    「离开页面不丢失」：编辑防抖落库 + 批次列表可随时回来继续。
  -->
  <el-drawer
    :model-value="visible"
    @update:model-value="(v) => emit('update:visible', v)"
    size="780px"
    :show-close="false"
    class="draft-preview-drawer"
    :close-on-click-modal="false"
  >
    <template #header>
      <div class="dp-header">
        <span class="dp-header-icon"><el-icon><Files /></el-icon></span>
        <div class="dp-header-heading">
          <div class="dp-header-title">
            题目预览与入库
            <el-tag size="small" :type="batch?.origin === 'ai_gen' ? 'primary' : 'info'" effect="light" round class="dp-origin-tag">
              {{ batch?.origin === 'ai_gen' ? 'AI 生成' : '文档导入' }}
            </el-tag>
          </div>
          <div class="dp-header-subtitle">
            {{ batch?.course_name }}<template v-if="batch?.file_name"> · {{ batch.file_name }}</template>
          </div>
        </div>
        <el-button text circle class="dp-close" :icon="Close" @click="emit('update:visible', false)" />
      </div>
    </template>

    <div v-if="loading" class="dp-body">
      <el-skeleton :rows="4" animated />
    </div>
    <div v-else-if="!batch" class="dp-body">
      <el-empty description="批次不存在或已被删除" :image-size="90" />
    </div>
    <template v-else>
      <!-- 批次摘要：章节 + 统计 -->
      <div class="dp-summary">
        <div class="dp-summary-row">
          <span class="dp-summary-label">入库章节</span>
          <el-select
            v-model="batch.catalog"
            class="module-select"
            popper-class="module-select-popper"
            placeholder="请选择题目入库章节（必选）"
            style="width: 260px"
            @change="onCatalogChange"
          >
            <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
          <span v-if="savingCatalog" class="dp-saving-hint">保存中…</span>
        </div>
        <div class="dp-summary-row dp-stats">
          <span>共 <b>{{ forms.length }}</b> 题待入库</span>
          <span v-if="batch.stats?.warned" class="dp-stat-warn">{{ batch.stats.warned }} 题带解析告警</span>
          <span v-if="batch.stats?.degraded" class="dp-stat-warn">
            部分题型生成失败：{{ failedGroupText }}
          </span>
        </div>
      </div>

      <!-- 工具栏：全选 / 已选 -->
      <div class="dp-toolbar">
        <el-checkbox :model-value="allChecked" :indeterminate="someChecked" @change="toggleAll">全选</el-checkbox>
        <span class="dp-checked-count">已选 {{ checkedCount }} / {{ forms.length }} 题</span>
      </div>

      <!-- 草稿列表 -->
      <div v-if="!forms.length" class="dp-body">
        <el-empty description="批次内已无待入库题目" :image-size="90" />
      </div>
      <div v-else class="dp-list">
        <div v-for="(f, i) in forms" :key="i" class="dp-card" :class="{ 'dp-card-unchecked': !f._checked }">
          <div class="dp-card-head">
            <el-checkbox v-model="f._checked" />
            <span class="q-type-badge" :class="'qt-' + f.qtype">{{ qtypeLabel(f.qtype) }}</span>
            <span class="dp-card-index">#{{ i + 1 }}</span>
            <span v-if="warningsOf(i).length" class="dp-card-warn" :title="warningsOf(i).join('；')">
              <el-icon><WarningFilled /></el-icon> {{ warningsOf(i).length }} 条告警
            </span>
            <el-button link type="danger" size="small" class="dp-card-remove" @click="removeDraft(i)">删除</el-button>
          </div>
          <QuestionFormFields :model="f" :compact="true" />
        </div>
      </div>
    </template>

    <template v-if="batch" #footer>
      <div class="dp-footer">
        <el-button text type="danger" :icon="Delete" @click="discardBatch">放弃批次</el-button>
        <div class="dp-footer-actions">
          <el-tooltip content="勾选后题目入库即为「已发布」，学生端章节练习立即可见（章节需已发布），省去逐题点发布" placement="top">
            <el-checkbox v-model="publishOnSave" class="dp-publish-check">入库后立即发布</el-checkbox>
          </el-tooltip>
          <el-button :disabled="!checkedCount || !batch.catalog" :loading="saving" @click="doSave(true)">
            入库勾选的 {{ checkedCount }} 题
          </el-button>
          <el-button type="primary" :disabled="!forms.length || !batch.catalog" :loading="saving" @click="doSave(false)">
            全部入库（{{ forms.length }}）
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Delete, Files, WarningFilled } from '@element-plus/icons-vue'
import QuestionFormFields from '@/components/QuestionFormFields.vue'
import {
  getDraftBatch, updateDraftBatch, deleteDraftBatch, saveDraftBatch,
} from '@/api/question'
import { DEFAULT_QTYPES, draftToForm, formToDraft } from '@/utils/questionDraft'

const props = defineProps({
  visible: { type: Boolean, default: false },
  batchId: { type: [Number, String], default: null },
  catalogs: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'saved'])

const batch = ref(null)
const forms = ref([]) // 与 batch.drafts 位置对齐的本地表单态（_checked 仅本地，不回传）
const loading = ref(false)
const saving = ref(false)
const savingCatalog = ref(false)
const publishOnSave = ref(false) // 入库后立即发布：入库题目直接置「已发布」
let persistTimer = null

watch(() => [props.visible, props.batchId], ([visible, id]) => {
  if (visible && id) loadBatch()
}, { immediate: false })

async function loadBatch() {
  loading.value = true
  try {
    const data = await getDraftBatch(props.batchId)
    batch.value = data
    forms.value = (data.drafts || []).map((d) => ({ ...draftToForm(d), _checked: true }))
  } catch {
    batch.value = null
    forms.value = []
  } finally {
    loading.value = false
  }
}

// ---- 编辑防抖回传（600ms）----
function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(persistDrafts, 600)
}
async function persistDrafts() {
  if (!batch.value) return
  const drafts = forms.value.map((f, i) => {
    const orig = batch.value.drafts?.[i] || {}
    const { _checked, ...rest } = f
    return { ...orig, ...formToDraft(rest) }
  })
  await updateDraftBatch(batch.value.id, { drafts })
}

// 表单任意字段变更 → 防抖回传（QuestionFormFields 直接 mutate form 对象）
watch(forms, schedulePersist, { deep: true })

async function onCatalogChange() {
  savingCatalog.value = true
  try {
    await updateDraftBatch(batch.value.id, { catalog: batch.value.catalog })
  } catch {
    // 失败保持原值，消息由 request 拦截器统一提示
  } finally {
    savingCatalog.value = false
  }
}

// ---- 勾选 ----
const checkedCount = computed(() => forms.value.filter((f) => f._checked).length)
const allChecked = computed(() => forms.value.length > 0 && checkedCount.value === forms.value.length)
const someChecked = computed(() => checkedCount.value > 0 && !allChecked.value)
function toggleAll(val) {
  forms.value.forEach((f) => { f._checked = val })
}

// ---- 告警（按位置对齐原草稿 _warnings）----
function warningsOf(i) {
  return batch.value?.drafts?.[i]?._warnings || []
}

// ---- 删除 ----
function removeDraft(i) {
  forms.value.splice(i, 1)
}

// ---- 入库 ----
async function doSave(onlyChecked) {
  if (!batch.value?.catalog) return ElMessage.warning('请先选择题目入库章节')
  const picked = onlyChecked ? forms.value.filter((f) => f._checked) : forms.value
  if (!picked.length) return ElMessage.warning('没有可入库的题目')
  saving.value = true
  try {
    await persistDrafts() // 先回传当前编辑，保证服务端 drafts 与前端一致
    const items = picked.map((f) => {
      const { _checked, ...rest } = f
      return formToDraft(rest)
    })
    const res = await saveDraftBatch(batch.value.id, items, publishOnSave.value)
    const parts = []
    if (res.saved?.length) parts.push(publishOnSave.value ? `已入库并发布 ${res.saved.length} 题` : `已入库 ${res.saved.length} 题`)
    if (res.skipped) parts.push(`跳过 ${res.skipped} 题（题库已存在相同题干）`)
    if (res.failed?.length) parts.push(`${res.failed.length} 题待修正`)
    if (parts.length) ElMessage.success(parts.join('，'))
    if (res.failed?.length) {
      // 失败明细（index 为本次提交 items 的下标）
      const detail = res.failed.slice(0, 5).map((f) => `第 ${f.index + 1} 题：${f.error}`).join('\n')
      ElMessageBox.alert(detail, `以下题目未能入库（${res.failed.length}）`, {
        type: 'warning', customClass: 'dp-fail-alert', confirmButtonText: '知道了',
      })
    }
    if (res.remaining === 0) {
      ElMessage.success('批次已全部入库')
      emit('saved')
      emit('update:visible', false)
      return
    }
    await loadBatch() // 服务端已移除成功项，重新加载不丢编辑（已先行回传）
  } finally {
    saving.value = false
  }
}

// ---- 放弃批次 ----
async function discardBatch() {
  try {
    await ElMessageBox.confirm(
      '放弃后批次内未入库的题目将一并删除，此操作无法撤销。',
      '放弃该草稿批次？',
      { type: 'warning', confirmButtonText: '放弃', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteDraftBatch(batch.value.id)
  ElMessage.success('已放弃该批次')
  emit('saved')
  emit('update:visible', false)
}

// ---- 展示 ----
const failedGroupText = computed(() => {
  const groups = batch.value?.stats?.failed_groups || []
  return groups.map((g) => `${qtypeLabel(g.qtype)}（${g.error}）`).join('；')
})
function qtypeLabel(v) {
  return DEFAULT_QTYPES.find((t) => t.value === v)?.label || v
}
</script>

<style scoped>
.draft-preview-drawer :deep(.el-drawer__header) {
  margin: 0;
  padding: 0;
}
.draft-preview-drawer :deep(.el-drawer__body) {
  padding: 0 20px 16px;
}

.dp-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 15px 22px 13px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.dp-header-icon {
  width: 38px;
  height: 38px;
  display: grid;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  font-size: 18px;
  color: var(--primary-600);
  background: #eaf2ff;
}
.dp-header-heading {
  min-width: 0;
  flex: 1;
}
.dp-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #0f172a;
  font-size: 17px;
  font-weight: 760;
  line-height: 1.25;
}
.dp-header-subtitle {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12.5px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dp-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
}
.dp-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}

.dp-summary {
  margin: 14px 0 10px;
  padding: 12px 14px;
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  background: #fff;
}
.dp-summary-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.dp-summary-label {
  color: #475569;
  font-size: 13px;
  font-weight: 650;
}
.dp-saving-hint {
  color: #94a3b8;
  font-size: 12.5px;
}
.dp-stats {
  margin-top: 8px;
  color: var(--gray-600);
  font-size: 13px;
}
.dp-stats b {
  color: #2563eb;
}
.dp-stat-warn {
  color: #d97706;
}

.dp-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 2px 10px;
}
.dp-checked-count {
  color: var(--gray-500);
  font-size: 12.5px;
}

.dp-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dp-card {
  padding: 12px 14px;
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}
.dp-card-unchecked {
  opacity: 0.62;
}
.dp-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.dp-card-index {
  color: #94a3b8;
  font-size: 12.5px;
  font-weight: 700;
}
.dp-card-warn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #d97706;
  font-size: 12.5px;
  cursor: help;
}
.dp-card-remove {
  margin-left: auto;
}

.dp-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 4px 4px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
}
.dp-footer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
/* 入库后立即发布：与按钮同行垂直居中（EP checkbox 默认高度与按钮不齐） */
.dp-publish-check {
  height: 32px;
  margin-right: 2px;
}
.dp-publish-check :deep(.el-checkbox__label) {
  font-size: 13px;
  color: #475569;
}
</style>
