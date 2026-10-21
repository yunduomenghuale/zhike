<template>
  <span class="qa-feedback">
    <button
      class="fb-btn"
      :class="{ active: modelValue === 1 }"
      :disabled="!recordId || sending"
      title="回答有用"
      @click.stop="send(1)"
    >有用</button>
    <button
      class="fb-btn"
      :class="{ active: modelValue === -1 }"
      :disabled="!recordId || sending"
      title="回答无用"
      @click.stop="send(-1)"
    >无用</button>
  </span>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { submitQaFeedback } from '@/api/knowledge'

// 问答反馈（有用/无用）：recordId 为空（记录未落库）时禁用；
// 再次点击已选项 = 取消反馈（value 0）
const props = defineProps({
  recordId: { type: [Number, String], default: null },
  modelValue: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue'])

const sending = ref(false)
async function send(v) {
  if (!props.recordId || sending.value) return
  const next = props.modelValue === v ? 0 : v
  sending.value = true
  try {
    await submitQaFeedback(props.recordId, next)
    emit('update:modelValue', next)
  } catch {
    ElMessage.error('反馈提交失败')
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.qa-feedback {
  display: inline-flex;
  gap: 4px;
}

.fb-btn {
  padding: 2px 10px;
  border: 1px solid var(--gray-200, #e2e8f0);
  border-radius: 999px;
  background: transparent;
  color: var(--gray-400, #94a3b8);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.fb-btn:hover:not(:disabled) {
  border-color: var(--primary-400, #60a5fa);
  color: var(--primary-600, #2563eb);
}

.fb-btn.active {
  border-color: var(--primary-500, #3b82f6);
  background: var(--primary-50, #eff6ff);
  color: var(--primary-600, #2563eb);
}

.fb-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
