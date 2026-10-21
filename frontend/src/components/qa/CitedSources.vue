<template>
  <div class="cited-sources">
    <div class="cited-title">
      <el-icon :size="12"><Collection /></el-icon> 参考来源
    </div>
    <div class="cited-tags">
      <button
        v-for="(g, gi) in groups"
        :key="gi"
        class="cite-tag"
        :class="{ active: open === gi, highlighted: highlightNums.size && g.nums.some((n) => highlightNums.has(n)) }"
        @click="toggle(gi)"
      >
        <span v-if="g.nums.length" class="cite-nums">{{ g.nums.join(' ') }}</span>
        <span v-if="badge(g.source)" class="cite-kind">{{ badge(g.source) }}</span>
        <span class="cite-name">{{ citedSourceLabel(g) }}</span>
      </button>
    </div>
    <div v-if="open !== null && groups[open]?.items.length" class="cite-detail">
      <div v-for="(it, ii) in groups[open].items" :key="ii" class="cite-item">
        <div class="cite-item-head">
          <span v-if="it.n" class="cite-item-n">资料{{ it.n }}</span>
          <span v-if="it.page" class="cite-item-page">P{{ it.page }}</span>
        </div>
        <div class="cite-item-snippet">{{ it.snippet }}…</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Collection } from '@element-plus/icons-vue'
import { groupCitedSources, citedSourceLabel, sourceBadge } from '@/utils/cited-sources'

// 问答参考来源：分组 tag（编号徽章+类型徽章+名称页码）+ 点击展开片段摘录。
// 与回答中的 [N] 引用上标对应：编号徽章即注入时的资料编号。
const props = defineProps({
  cited: { type: Array, default: () => [] },
  // 需要高亮的资料编号（点击回答中的 [N] 上标时传入），Set/数组均可
  highlight: { type: [Set, Array], default: () => new Set() },
})

const groups = computed(() => groupCitedSources(props.cited))
const highlightNums = computed(() => (props.highlight instanceof Set ? props.highlight : new Set(props.highlight)))
const badge = sourceBadge

const open = ref(null)
function toggle(gi) {
  open.value = open.value === gi ? null : gi
}
</script>

<style scoped>
.cited-sources {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--gray-200, #e2e8f0);
}

.cited-title {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
  color: var(--gray-500, #64748b);
  font-size: 12px;
}

.cited-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.cite-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 3px 10px;
  border: 1px solid var(--gray-200, #e2e8f0);
  border-radius: 999px;
  background: var(--gray-50, #f8fafc);
  color: var(--gray-600, #475569);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cite-tag:hover {
  border-color: var(--primary-400, #60a5fa);
  color: var(--primary-600, #2563eb);
  background: var(--primary-50, #eff6ff);
}

.cite-tag.active {
  border-color: var(--primary-500, #3b82f6);
  color: var(--primary-600, #2563eb);
  background: var(--primary-50, #eff6ff);
}

.cite-tag.highlighted {
  border-color: var(--primary-500, #3b82f6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.18);
}

.cite-nums {
  display: inline-flex;
  gap: 2px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--primary-600, #2563eb);
  color: #fff;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 16px;
}

.cite-kind {
  padding: 0 6px;
  border-radius: 4px;
  background: rgba(100, 116, 139, 0.12);
  color: var(--gray-500, #64748b);
  font-size: 10.5px;
  line-height: 16px;
  white-space: nowrap;
}

.cite-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cite-detail {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--gray-200, #e2e8f0);
  border-radius: 10px;
  background: var(--gray-50, #f8fafc);
}

.cite-item + .cite-item {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--gray-200, #e2e8f0);
}

.cite-item-head {
  display: flex;
  gap: 6px;
  margin-bottom: 3px;
}

.cite-item-n {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--primary-600, #2563eb);
  color: #fff;
  font-size: 10.5px;
  line-height: 16px;
}

.cite-item-page {
  color: var(--gray-500, #64748b);
  font-size: 11px;
}

.cite-item-snippet {
  color: var(--gray-600, #475569);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
