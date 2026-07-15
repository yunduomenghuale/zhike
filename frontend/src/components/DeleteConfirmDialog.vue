<template>
  <el-dialog
    :model-value="modelValue"
    width="460px"
    align-center
    :show-close="false"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    class="platform-delete-dialog"
    @update:model-value="updateVisible"
  >
    <template #header>
      <div class="delete-confirm-header">
        <span class="delete-confirm-icon">
          <el-icon><Delete /></el-icon>
        </span>
        <div class="delete-confirm-heading">
          <div class="delete-confirm-title">{{ title }}</div>
          <div class="delete-confirm-subtitle">请确认本次危险操作</div>
        </div>
        <el-button
          text
          circle
          class="delete-confirm-close"
          :disabled="loading"
          aria-label="关闭"
          @click="updateVisible(false)"
        >
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </template>

    <div class="delete-confirm-body">
      <div class="delete-confirm-question">
        确定{{ actionText }} <strong>“{{ itemName || '当前内容' }}”</strong> 吗？
      </div>
      <div class="delete-confirm-warning">
        <el-icon><WarningFilled /></el-icon>
        <span>{{ description }}</span>
      </div>
    </div>

    <template #footer>
      <div class="delete-confirm-footer">
        <el-button :disabled="loading" @click="updateVisible(false)">取消</el-button>
        <el-button type="danger" :loading="loading" @click="$emit('confirm')">{{ confirmText }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { Close, Delete, WarningFilled } from '@element-plus/icons-vue'

defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '确认删除' },
  itemName: { type: String, default: '' },
  description: { type: String, default: '删除后无法恢复，请谨慎操作。' },
  actionText: { type: String, default: '删除' },
  confirmText: { type: String, default: '确认删除' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'confirm'])

function updateVisible(value) {
  emit('update:modelValue', value)
}
</script>

<style scoped>
:global(.platform-delete-dialog) {
  overflow: hidden;
  max-width: calc(100vw - 32px);
  border: 1px solid rgba(59, 130, 246, 0.14);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 28px 72px rgba(45, 78, 132, 0.2);
}

:global(.platform-delete-dialog .el-dialog__header) {
  padding: 0;
  margin: 0;
}

:global(.platform-delete-dialog .el-dialog__body) {
  padding: 0 28px 24px;
}

:global(.platform-delete-dialog .el-dialog__footer) {
  padding: 0 28px 24px;
}

.delete-confirm-header {
  display: flex;
  align-items: center;
  min-height: 88px;
  padding: 20px 28px;
  background: linear-gradient(180deg, #f6f9ff 0%, #fff 100%);
  border-bottom: 1px solid #edf2fa;
}

.delete-confirm-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 48px;
  width: 48px;
  height: 48px;
  margin-right: 14px;
  border-radius: 12px;
  color: #ef5350;
  font-size: 23px;
  background: #fff1f1;
  box-shadow: inset 0 0 0 1px rgba(239, 83, 80, 0.08);
}

.delete-confirm-heading {
  min-width: 0;
  flex: 1;
}

.delete-confirm-title {
  color: #17233d;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.4;
}

.delete-confirm-subtitle {
  margin-top: 3px;
  color: #8a96aa;
  font-size: 13px;
}

.delete-confirm-close {
  flex: 0 0 auto;
  margin-left: 16px;
  color: #9aa5b5;
  font-size: 18px;
}

.delete-confirm-body {
  padding-top: 24px;
}

.delete-confirm-question {
  color: #34415a;
  font-size: 16px;
  line-height: 1.7;
}

.delete-confirm-question strong {
  color: #17233d;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.delete-confirm-warning {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 18px;
  padding: 13px 15px;
  border: 1px solid #ffe1e1;
  border-radius: 8px;
  color: #b84a4a;
  font-size: 13px;
  line-height: 1.6;
  background: #fff7f7;
}

.delete-confirm-warning .el-icon {
  flex: 0 0 auto;
  margin-top: 3px;
  color: #ef5350;
}

.delete-confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 20px;
  border-top: 1px solid #edf2fa;
}

.delete-confirm-footer .el-button {
  min-width: 92px;
}

@media (max-width: 560px) {
  .delete-confirm-header {
    padding: 18px 20px;
  }

  :global(.platform-delete-dialog .el-dialog__body) {
    padding: 0 20px 20px;
  }

  :global(.platform-delete-dialog .el-dialog__footer) {
    padding: 0 20px 20px;
  }
}
</style>
