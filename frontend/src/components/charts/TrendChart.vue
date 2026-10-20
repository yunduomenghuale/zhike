<template>
  <div class="trend-chart" v-loading="loading">
    <div v-if="series.length && points" class="chart-wrap">
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        preserveAspectRatio="none"
        class="chart-svg"
        @mousemove="onMove"
        @mouseleave="hoverIndex = -1"
      >
        <!-- 网格与 y 轴刻度（4 等分） -->
        <g>
          <line
            v-for="i in 4" :key="'g' + i"
            :x1="PAD.l" :x2="W - PAD.r" :y1="yOf(i / 4)" :y2="yOf(i / 4)"
            class="grid-line"
          />
          <text
            v-for="i in 4" :key="'t' + i"
            :x="PAD.l - 8" :y="yOf(i / 4) + 4" class="axis-text" text-anchor="end"
          >{{ fmtShort(maxVal * i / 4) }}</text>
        </g>
        <!-- 各序列折线 -->
        <polyline
          v-for="s in series" :key="s.name"
          :points="s.points" fill="none" :stroke="s.color" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"
        />
        <!-- hover 竖线与圆点 -->
        <line
          v-if="hoverIndex >= 0"
          :x1="xOf(hoverIndex)" :x2="xOf(hoverIndex)" :y1="PAD.t" :y2="H - PAD.b"
          class="hover-line"
        />
        <circle
          v-for="s in series" :key="'c' + s.name"
          v-show="hoverIndex >= 0"
          :cx="xOf(hoverIndex)" :cy="s.ys[hoverIndex]" r="3.5"
          :fill="s.color" stroke="#fff" stroke-width="1.5"
        />
      </svg>
      <!-- x 轴日期（首/中/末） -->
      <div class="x-axis">
        <span>{{ labels[0] }}</span>
        <span v-if="labels.length > 2">{{ labels[Math.floor(labels.length / 2)] }}</span>
        <span>{{ labels[labels.length - 1] }}</span>
      </div>
      <!-- 图例 -->
      <div class="legend">
        <span v-for="s in series" :key="'l' + s.name">
          <i :style="{ background: s.color }" />{{ s.name }}
        </span>
      </div>
      <!-- hover 详情 -->
      <div v-if="hoverIndex >= 0" class="hover-card" :style="{ left: hoverLeft }">
        <strong>{{ labels[hoverIndex] }}</strong>
        <span v-for="s in series" :key="'h' + s.name">
          <i :style="{ background: s.color }" />{{ s.name }}：{{ s.values[hoverIndex] }}
        </span>
      </div>
    </div>
    <div v-else class="chart-empty">暂无趋势数据</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  // labels: ['2026-10-13', ...]；series: [{ name, color, values: [1,2,...] }]
  labels: { type: Array, default: () => [] },
  series: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const W = 680, H = 220, PAD = { l: 44, r: 12, t: 12, b: 12 }
const hoverIndex = ref(-1)
const hoverLeft = ref('0px')

const maxVal = computed(() => {
  const all = props.series.flatMap((s) => s.values)
  const max = all.length ? Math.max(...all) : 0
  return max <= 4 ? Math.max(max, 4) : max * 1.15
})

const points = computed(() => props.labels.length > 1)

const xOf = (i) => {
  const n = props.labels.length
  return PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r)
}
const yOf = (ratio) => H - PAD.b - ratio * (H - PAD.t - PAD.b)

const series = computed(() => props.series.map((s) => ({
  ...s,
  ys: s.values.map((v) => yOf(maxVal.value ? v / maxVal.value : 0)),
  points: s.values.map((v, i) => `${xOf(i)},${yOf(maxVal.value ? v / maxVal.value : 0)}`).join(' '),
})))

function fmtShort(n) {
  n = Math.round(n)
  return n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n)
}

function onMove(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const ratio = (event.clientX - rect.left) / rect.width
  const i = Math.round(ratio * (props.labels.length - 1))
  hoverIndex.value = Math.min(props.labels.length - 1, Math.max(0, i))
  hoverLeft.value = `${Math.min(Math.max(ratio * 100, 8), 78)}%`
}
</script>

<style scoped>
.trend-chart { position: relative; min-height: 220px; }
.chart-wrap { position: relative; }
.chart-svg { width: 100%; height: 220px; display: block; }
.grid-line { stroke: #eef2f7; stroke-width: 1; }
.axis-text { fill: #94a3b8; font-size: 11px; }
.hover-line { stroke: #94a3b8; stroke-dasharray: 3 3; }
.x-axis { display: flex; justify-content: space-between; padding: 6px 4px 0 44px; color: #94a3b8; font-size: 11px; }
.legend { display: flex; gap: 16px; padding: 8px 4px 0; color: #64748b; font-size: 12px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.hover-card {
  position: absolute; top: 0; transform: translateX(-50%);
  display: grid; gap: 3px; padding: 8px 12px; border-radius: 10px;
  background: rgba(15, 23, 42, .92); color: #e2e8f0; font-size: 12px;
  pointer-events: none; white-space: nowrap; z-index: 2;
}
.hover-card strong { font-size: 12px; }
.hover-card i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 6px; }
.chart-empty { height: 220px; display: grid; place-items: center; color: #94a3b8; font-size: 13px; }
</style>
