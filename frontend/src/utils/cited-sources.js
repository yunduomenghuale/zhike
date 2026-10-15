/**
 * 问答「参考来源」汇总工具。
 *
 * 背景：同一章课件的多个页面被检索命中时，cited 里每条带一个页码，
 * 早期逐条渲染成「第4章 网络层课件 P1」「第4章 网络层课件 P2」… 一排重复 pill。
 * 这里按来源名归组、页码去重升序合并，渲染为一条「第4章 网络层课件 P1 / P2 / P17」。
 *
 * 入参 cited: [{ material_name, page, ... }]（来自 _gather_course_context）
 * 返回 groups: [{ name, pages: number[] }]（保持原顺序，页码数字升序）
 */

export function groupCitedSources(cited) {
  const groups = []
  const byName = new Map()
  for (const c of cited || []) {
    if (!c) continue
    const name = c.material_name || '课程资料'
    let g = byName.get(name)
    if (!g) {
      g = { name, pages: [] }
      byName.set(name, g)
      groups.push(g)
    }
    const p = Number(c.page)
    if (Number.isFinite(p) && p > 0) g.pages.push(p)
  }
  for (const g of groups) {
    g.pages = [...new Set(g.pages)].sort((a, b) => a - b)
  }
  return groups
}

/** 单条来源的展示文本：名称 + 汇总页码（无页码则仅名称，如原文拼接兜底条目） */
export function citedSourceLabel(g) {
  if (!g.pages.length) return g.name
  return `${g.name} ${g.pages.map((p) => `P${p}`).join(' / ')}`
}
