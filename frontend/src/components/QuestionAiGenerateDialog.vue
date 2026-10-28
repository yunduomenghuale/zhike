<template>
  <!--
    AI 多类型生题弹窗：章节 + 多组「题型 × 数量 × 每题分值」配置。
    提交为异步任务（秒返 task_id），生成进度/结果由父层经 useAiTaskPolling
    轮询展示，完成后打开草稿批次预览（离开页面不丢失）。
  -->
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => emit('update:visible', v)"
    width="600px"
    align-center
    class="ai-gen-dialog"
    :show-close="false"
    :close-on-click-modal="false"
  >
    <template #header>
      <div class="creation-dialog-header">
        <span class="creation-dialog-icon ai-create-icon"><el-icon><MagicStick /></el-icon></span>
        <div class="creation-dialog-heading">
          <div class="creation-dialog-title">AI 自动生成题目</div>
          <div class="creation-dialog-subtitle">按章节资料一次生成多种题型</div>
        </div>
        <el-button text circle class="creation-dialog-close" :icon="Close" @click="emit('update:visible', false)" />
      </div>
    </template>

    <div class="aig-body">
      <div class="aig-hint">
        <el-icon class="aig-hint-icon"><InfoFilled /></el-icon>
        <span>基于章节 PPT 与知识库资料生成<b>草稿</b>题目，生成过程中可离开页面，完成后从「草稿批次」继续处理。未配置真实大模型时返回示例题。</span>
      </div>

      <el-form label-position="top" class="aig-form">
        <el-form-item label="所属章节（必选）">
          <el-select v-model="catalog" class="module-select" popper-class="module-select-popper" placeholder="选择章节（基于其 PPT 与资料出题）" style="width: 100%">
            <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="题型与数量">
          <div class="aig-groups">
            <div v-for="(g, i) in groups" :key="g.qtype" class="aig-group-row" :class="{ 'aig-group-off': !g.enabled }">
              <el-checkbox v-model="g.enabled" :label="g.label" />
              <template v-if="g.enabled">
                <el-input-number v-model="g.count" :min="1" :max="20" :controls="false" size="default" class="aig-num" />
                <span class="aig-unit">题</span>
                <span class="aig-sep">每题</span>
                <el-input-number v-model="g.score" :min="0.5" :max="100" :step="0.5" :precision="1" :controls="false" size="default" class="aig-num" />
                <span class="aig-unit">分</span>
              </template>
              <span v-else class="aig-off-text">不生成</span>
            </div>
          </div>
          <div class="aig-total" :class="{ 'aig-total-over': totalCount > 50 }">
            合计 <b>{{ totalCount }}</b> 题（一次最多 50 题，最多 5 种题型）
          </div>
        </el-form-item>

        <el-form-item label="用途分类">
          <el-select
            v-model="scenes"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="2"
            class="module-select"
            popper-class="module-select-popper"
            placeholder="生成的题目默认用于哪些场景"
            style="width: 100%"
          >
            <el-option v-for="s in SCENE_OPTIONS" :key="s.code" :label="s.label" :value="s.code" />
          </el-select>
          <div class="aig-scenes-tip">默认「章节练习+作业」；勾选「考试」的题目不会出现在学生练习中</div>
        </el-form-item>

        <el-form-item label="教学目标 / 出题要求（选填）">
          <el-input v-model="objective" type="textarea" :rows="2" placeholder="如：侧重概念辨析与实际应用，难度适中" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <div class="creation-dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button class="q-btn-primary" type="primary" :icon="MagicStick" :loading="submitting" @click="doSubmit">
          开始生成
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, InfoFilled, MagicStick } from '@element-plus/icons-vue'
import { generateQuestions } from '@/api/question'
import { DEFAULT_QTYPES, DEFAULT_SCENES, SCENE_OPTIONS } from '@/utils/questionDraft'

const props = defineProps({
  visible: { type: Boolean, default: false },
  courseId: { type: [Number, String], default: null },
  catalogs: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'submitted'])

const catalog = ref(null)
const objective = ref('')
const scenes = ref([...DEFAULT_SCENES])
const submitting = ref(false)

// 五种题型一行一组：勾选后配置数量与每题分值（与后端 groups 协议一致）
const groups = reactive(
  DEFAULT_QTYPES.map((t) => ({ qtype: t.value, label: t.label, enabled: false, count: 5, score: t.value === 'multi' ? 3 : t.value === 'blank' ? 4 : t.value === 'short' ? 10 : 2 })),
)

watch(() => props.visible, (v) => {
  if (v) {
    catalog.value = null
    objective.value = ''
    scenes.value = [...DEFAULT_SCENES]
    groups.forEach((g, i) => { g.enabled = i === 0; g.count = 5 })
  }
})

const enabledGroups = computed(() => groups.filter((g) => g.enabled))
const totalCount = computed(() => enabledGroups.value.reduce((sum, g) => sum + (Number(g.count) || 0), 0))

async function doSubmit() {
  if (!props.courseId) return ElMessage.warning('请先选择课程')
  if (!catalog.value) return ElMessage.warning('请选择题目所属章节')
  if (!enabledGroups.value.length) return ElMessage.warning('请至少勾选一种题型')
  if (!scenes.value.length) return ElMessage.warning('请至少选择一个用途分类')
  if (totalCount.value > 50) return ElMessage.warning('一次生成题目总数不可超过 50')
  const payloadGroups = enabledGroups.value.map((g) => ({
    qtype: g.qtype, count: Number(g.count) || 1, score: Number(g.score) || 1,
  }))
  submitting.value = true
  try {
    const res = await generateQuestions({
      course: props.courseId,
      catalog: catalog.value,
      objective: objective.value.trim(),
      scenes: [...scenes.value],
      groups: payloadGroups,
    })
    ElMessage.success('生题任务已提交，生成过程中离开页面也不会丢失')
    emit('submitted', { taskId: res.task_id })
    emit('update:visible', false)
  } catch {
    // 错误消息（含「已有进行中的生题任务」）由 request 拦截器统一提示
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.ai-gen-dialog :deep(.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.ai-gen-dialog :deep(.el-dialog__header) {
  margin: 0;
  padding: 0;
}
.ai-gen-dialog :deep(.el-dialog__body) {
  padding: 0;
}
.ai-gen-dialog :deep(.el-dialog__footer) {
  padding: 0;
}

.aig-body {
  padding: 16px 22px 18px;
}
.aig-hint {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 16px;
  padding: 11px 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.9), rgba(219, 234, 254, 0.5));
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
}
.aig-hint b { color: var(--primary-700); font-weight: 700; }
.aig-hint-icon { flex: 0 0 auto; font-size: 17px; color: var(--primary-600); margin-top: 2px; }

.aig-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.aig-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

.aig-groups {
  border: 1px solid var(--gray-100);
  border-radius: 12px;
  background: #f8fbff;
}
.aig-group-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.7);
}
.aig-group-row:last-child {
  border-bottom: 0;
}
.aig-group-off {
  opacity: 0.62;
}
.aig-group-row :deep(.el-checkbox) {
  flex: 0 0 76px;
}
.aig-num {
  width: 84px;
  flex: none;
}
.aig-unit {
  color: #64748b;
  font-size: 13px;
}
.aig-sep {
  margin-left: 10px;
  color: #64748b;
  font-size: 13px;
}
.aig-off-text {
  color: #94a3b8;
  font-size: 12.5px;
}
.aig-total {
  margin-top: 8px;
  color: var(--gray-600);
  font-size: 13px;
}
.aig-total b {
  color: #2563eb;
  font-size: 15px;
  margin: 0 2px;
}
.aig-total-over {
  color: var(--danger);
}
.aig-total-over b { color: var(--danger); }
.aig-scenes-tip {
  margin-top: 6px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 66px;
  padding: 15px 22px 13px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.creation-dialog-icon {
  width: 38px;
  height: 38px;
  display: grid;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  font-size: 18px;
}
.ai-create-icon {
  color: #fff;
  background: linear-gradient(140deg, #60a5fa, #2563eb);
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}
.creation-dialog-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 760;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12.5px;
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
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 22px 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}
.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}
.q-btn-primary {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}
</style>
