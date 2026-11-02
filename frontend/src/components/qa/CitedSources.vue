<template>
  <div class="cited-sources">
    <div class="cited-head">
      <div class="cited-title">
        <el-icon :size="12"><Collection /></el-icon> 参考来源
      </div>
      <button v-if="collapsible" type="button" class="cite-toggle" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开全部' }}
        <el-icon :size="11"><component :is="expanded ? ArrowUp : ArrowDown" /></el-icon>
      </button>
    </div>
    <div ref="tagsRef" class="cited-tags" :class="{ folded: !expanded }">
      <button
        v-for="(g, gi) in groups"
        :key="gi"
        class="cite-tag"
        :class="{ active: open === gi, highlighted: highlightNums.size && g.nums.some((n) => highlightNums.has(n)) }"
        :title="citedSourceFullLabel(g)"
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
          <span v-if="badge(it.kind)" class="cite-item-kind">{{ badge(it.kind) }}</span>
          <span v-if="it.page" class="cite-item-page">P{{ it.page }}</span>
        </div>
        <div class="cite-item-snippet">{{ it.snippet }}…</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Collection } from '@element-plus/icons-vue'
import { groupCitedSources, citedSourceLabel, citedSourceFullLabel, sourceBadge } from '@/utils/cited-sources'
import { renumberCitations } from '@/utils/markdown'

// 问答参考来源：分组 tag（编号徽章+类型徽章+名称页码）+ 点击展开片段摘录。
// 与回答中的 [N] 引用上标对应：编号徽章即展示序号（已按正文首次出现顺序重排为 1..M）。
// 默认只占一行，超出的来源折叠，点「展开全部」查看（避免命中资料多时刷屏）。
const props = defineProps({
  cited: { type: Array, default: () => [] },
  // 需要高亮的资料编号（点击回答中的 [N] 上标时传入），Set/数组均可
  highlight: { type: [Set, Array], default: () => new Set() },
  // 回答正文：用于重编号 + 剔除未被引用的条目（与正文渲染共用同一套映射）
  answer: { type: String, default: '' },
})

// 与父组件 renderQaAnswer(text, cited) 内的重编号完全同构：同样的入参必得同样的序号
const prepared = computed(() => renumberCitations(props.answer, props.cited))
const groups = computed(() => groupCitedSources(prepared.value.cited))
const highlightNums = computed(() => (props.highlight instanceof Set ? props.highlight : new Set(props.highlight)))
const badge = sourceBadge

const open = ref(null)
function toggle(gi) {
  open.value = open.value === gi ? null : gi
}

// ---- 单行折叠：内容超过一行才出现展开入口 ----
const expanded = ref(false)
const overflowing = ref(false)
const collapsible = computed(() => overflowing.value || expanded.value)
const tagsRef = ref(null)
let ro = null
let rafId = 0
let lastWidth = -1

function measure() {
  const el = tagsRef.value
  if (!el) return
  // 用首个 tag 的实测高度作为「一行」高度，避免不同字体下裁剪出半行
  const first = el.firstElementChild
  if (first) el.style.setProperty('--cite-row-h', `${first.offsetHeight}px`)
  // 展开态 clientHeight 已被内容撑开，测不出溢出，沿用折叠时的判断结果
  if (!expanded.value) overflowing.value = el.scrollHeight > el.clientHeight + 1
}

function scheduleMeasure() {
  cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(measure)
}

onMounted(() => {
  nextTick(measure)
  // 字体加载完成后再校一次行高
  document.fonts?.ready?.then(() => scheduleMeasure()).catch(() => {})
  if (typeof ResizeObserver !== 'undefined' && tagsRef.value) {
    lastWidth = tagsRef.value.clientWidth
    ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width ?? 0
      // 只在宽度变化（换行情况变了）时重测，避免高度变化引发回调死循环
      if (Math.abs(w - lastWidth) < 1) return
      lastWidth = w
      scheduleMeasure()
    })
    ro.observe(tagsRef.value)
  }
})

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
  cancelAnimationFrame(rafId)
})

// 点了回答里的 [N] 上标：把被折叠的来源展开，保证高亮项可见
watch(highlightNums, (set) => {
  if (set.size && !expanded.value) expanded.value = true
})
</script>

<style scoped>
.cited-sources {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--gray-200, #e2e8f0);
}

.cited-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.cited-title {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-500, #64748b);
  font-size: 12px;
}

.cite-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: var(--primary-600, #2563eb);
  font-size: 12px;
  cursor: pointer;
}
.cite-toggle:hover {
  color: var(--primary-700, #1d4ed8);
  text-decoration: underline;
}

.cited-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  /* 上下留 2px 给高亮描边，避免折叠裁剪时被切掉 */
  padding: 2px 0;
}

/* 折叠：只留实测的一行高度（首帧用 24px 兜底），其余裁掉 */
.cited-tags.folded {
  max-height: calc(var(--cite-row-h, 24px) + 4px);
  overflow: hidden;
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
  line-height: 16px;
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

/* 片段来源类型（章节合并后同一条目里可能混着课件/讲稿片段） */
.cite-item-kind {
  padding: 0 5px;
  border-radius: 4px;
  background: rgba(100, 116, 139, 0.12);
  color: var(--gray-500, #64748b);
  font-size: 10.5px;
  line-height: 15px;
}

.cite-item-snippet {
  color: var(--gray-600, #475569);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
