<template>
  <span class="stat-delta" :class="tone">
    <el-icon v-if="delta > 0"><Top /></el-icon>
    <el-icon v-else-if="delta < 0"><Bottom /></el-icon>
    <el-icon v-else><Minus /></el-icon>
    {{ text }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { Bottom, Minus, Top } from '@element-plus/icons-vue'

const props = defineProps({
  delta: { type: Number, default: 0 },
  deltaPct: { type: Number, default: null }, // 后端已算好的比例（0.1234），null 时只展示绝对差
  suffix: { type: String, default: '较上周' },
})

const tone = computed(() => (props.delta > 0 ? 'up' : props.delta < 0 ? 'down' : 'flat'))
const text = computed(() => {
  const pct = props.deltaPct === null || props.deltaPct === undefined
    ? ''
    : ` ${props.delta > 0 ? '+' : ''}${(props.deltaPct * 100).toFixed(0)}%`
  return `${props.delta > 0 ? '+' : ''}${props.delta}${pct} ${props.suffix}`
})
</script>

<style scoped>
.stat-delta { display: inline-flex; align-items: center; gap: 2px; font-size: 12px; font-weight: 700; }
.stat-delta .el-icon { font-size: 12px; }
/* 教学平台不用涨红跌绿，增长=主色、下降=灰、持平=浅灰 */
.stat-delta.up { color: #2563eb; }
.stat-delta.down { color: #94a3b8; }
.stat-delta.flat { color: #cbd5e1; }
</style>
