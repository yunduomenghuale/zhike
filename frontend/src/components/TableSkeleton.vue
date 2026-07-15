<template>
  <div class="table-skeleton">
    <div class="sk-row sk-head">
      <div v-for="c in cols" :key="'h' + c" class="sk-cell">
        <el-skeleton-item variant="text" style="width: 55%" />
      </div>
    </div>
    <div v-for="r in rows" :key="r" class="sk-row" :style="{ animationDelay: r * 0.05 + 's' }">
      <div v-for="c in cols" :key="r + '-' + c" class="sk-cell">
        <el-skeleton-item variant="text" :style="{ width: c === 1 ? '70%' : '85%' }" />
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  rows: { type: Number, default: 6 },
  cols: { type: Number, default: 5 },
})
</script>

<style scoped>
.table-skeleton {
  padding: 2px 0;
}

.sk-row {
  display: flex;
  gap: 20px;
  padding: 15px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  animation: sk-fade-in 0.3s ease both;
}

.sk-head {
  background: var(--el-fill-color-light);
  border-radius: 8px 8px 0 0;
}

.sk-cell {
  flex: 1;
}

@keyframes sk-fade-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
