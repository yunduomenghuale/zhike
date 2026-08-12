/**
 * 章节学习进度计算（学生端徽章 / 课程总进度共用）。
 *
 * 规则：每页只计 min(已看位置, 页时长)，未播放的页不计入分子；
 * 总时长 = 已发现页真实时长 + 未发现页按已发现页平均时长估算。
 */
export function chapterProgress(p) {
  if (!p) return { pct: null, label: '', type: 'info' }
  if (p.status === 'completed') return { pct: 100, label: '已完成', type: 'success' }
  const durations = p.page_durations || {}
  const durVals = Object.values(durations).map(Number).filter((x) => x > 0)
  if (!durVals.length) return { pct: null, label: '学习中', type: 'warning' }
  const watchedMap = p.page_watched || {}
  const watchedTotal = Object.entries(durations).reduce(
    (sum, [k, d]) => sum + Math.min(Number(watchedMap[k]) || 0, Number(d) || 0),
    0,
  )
  const avg = durVals.reduce((a, b) => a + b, 0) / durVals.length
  const pageCount = Number(p.page_count) || durVals.length
  const total = durVals.reduce((a, b) => a + b, 0) + Math.max(0, pageCount - durVals.length) * avg
  const pct = total > 0 ? Math.min(100, Math.round((watchedTotal / total) * 100)) : 0
  return { pct, label: `进度 ${pct}%`, type: 'warning' }
}
