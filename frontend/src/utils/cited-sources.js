/**
 * 问答「参考来源」汇总工具。
 *
 * 背景：同一章课件的多个页面被检索命中时，cited 里每条带一个页码，
 * 早期逐条渲染成「第4章 网络层课件 P1」「第4章 网络层课件 P2」… 一排重复 pill。
 * 这里按来源名归组、页码去重升序合并，渲染为一条「第4章 网络层课件 P1 / P2 / P17」。
 *
 * 入参 cited: [{ n, chunk_id, source, material_name, page, snippet }]
 * （n/source 为 2026-10-21 结构化注入新增的字段；旧数据无此字段时
 * nums 为空、source 徽章不显示，向后兼容）
 * 返回 groups: [{ name, pages, nums, source, items: [{n, page, snippet}] }]
 */

export function groupCitedSources(cited) {
  const groups = []
  const byName = new Map()
  for (const c of cited || []) {
    if (!c) continue
    const name = c.material_name || '课程资料'
    let g = byName.get(name)
    if (!g) {
      g = { name, pages: [], nums: [], source: c.source || '', items: [] }
      byName.set(name, g)
      groups.push(g)
    }
    const p = Number(c.page)
    if (Number.isFinite(p) && p > 0) g.pages.push(p)
    const n = Number(c.n)
    if (Number.isFinite(n) && n > 0) g.nums.push(n)
    if (c.snippet) {
      g.items.push({
        n: Number.isFinite(n) && n > 0 ? n : null,
        page: Number.isFinite(p) && p > 0 ? p : null,
        snippet: c.snippet,
      })
    }
  }
  for (const g of groups) {
    g.pages = [...new Set(g.pages)].sort((a, b) => a - b)
    g.nums = [...new Set(g.nums)].sort((a, b) => a - b)
  }
  return groups
}

/** 单条来源的展示文本：名称 + 汇总页码（无页码则仅名称，如原文拼接兜底条目） */
export function citedSourceLabel(g) {
  if (!g.pages.length) return g.name
  return `${g.name} ${g.pages.map((p) => `P${p}`).join(' / ')}`
}

// 来源类型徽章（与后端 _SOURCE_LABELS 同口径；旧数据无 source 时不显示徽章）
const SOURCE_BADGES = {
  material: '资料',
  ppt: '课件',
  script: '讲稿',
  'ppt+script': '课件+讲稿',
  'script+ppt': '讲稿+课件',
  prev: '上轮参考',
}

export function sourceBadge(source) {
  return SOURCE_BADGES[source] || ''
}
