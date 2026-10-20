<template>
  <div class="alert-banner">
    <div v-if="!items.length" class="alert-empty">暂无待办与异常，平台运行平稳</div>
    <button
      v-for="item in items" :key="item.key" type="button"
      class="alert-item" :class="item.level" @click="$emit('jump', item)"
    >
      <span class="alert-dot" />
      <div class="alert-main">
        <strong>{{ item.title }}</strong>
        <small>{{ item.hint }}</small>
      </div>
      <span class="alert-count">{{ item.count > 99 ? '99+' : item.count }}</span>
      <el-icon class="alert-arrow"><ArrowRight /></el-icon>
    </button>
  </div>
</template>

<script setup>
import { ArrowRight } from '@element-plus/icons-vue'

defineProps({ items: { type: Array, default: () => [] } })
defineEmits(['jump'])
</script>

<style scoped>
.alert-banner { display: grid; gap: 10px; }
.alert-empty { padding: 28px 0; text-align: center; color: #94a3b8; font-size: 13px; }
.alert-item {
  display: flex; align-items: center; gap: 12px; width: 100%;
  padding: 12px 14px; border: 1px solid #e5edf8; border-radius: 14px;
  background: #fff; cursor: pointer; text-align: left; transition: border-color .15s, box-shadow .15s;
}
.alert-item:hover { border-color: #bfdbfe; box-shadow: 0 8px 20px rgba(37, 99, 235, .08); }
.alert-dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
.alert-item.warning .alert-dot { background: #f59e0b; box-shadow: 0 0 0 5px #fef3c7; }
.alert-item.info .alert-dot { background: #2563eb; box-shadow: 0 0 0 5px #dbeafe; }
.alert-main { flex: 1; min-width: 0; display: grid; gap: 2px; }
.alert-main strong { color: #0f172a; font-size: 13.5px; }
.alert-main small { color: #94a3b8; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.alert-count { font-size: 20px; font-weight: 800; color: #0f172a; }
.alert-arrow { color: #cbd5e1; }
</style>
