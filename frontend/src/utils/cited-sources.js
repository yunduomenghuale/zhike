/**
 * 问答「参考来源」汇总工具。
 *
 * 两层归并：
 * 1) 按来源名归组：同一章课件的多个页面被检索命中时，cited 里每条带一个页码，
 *    早期逐条渲染成「第4章 网络层课件 P1」「第4章 网络层课件 P2」… 一排重复 pill。
 *    这里按 material_name 归组、页码去重升序合并。
 * 2) 按章节归并：同一章的课件与讲稿是两个不同的 material_name
 *    （「第三章数据链路层课件」/「第三章数据链路层讲解稿」），第 1 层归组后仍是两条，
 *    用户看到的是「同一章出现两次」。第 2 层剥掉类型后缀按章节名合并，
 *    渲染为一条「第三章数据链路层 P1 / P35 / P47」，徽章变「课件+讲稿」。
 *    引用编号（回答里的 [N]）不受影响：合并后 nums 保留全部编号，
 *    点标签展开的详情里每段仍各自标明编号与页，回链照常。
 *
 * 入参 cited: [{ n, chunk_id, source, material_name, page, snippet }]
 * （n/source 为 2026-10-21 结构化注入新增的字段；旧数据无此字段时
 * nums 为空、source 徽章不显示，向后兼容）
 * 返回 groups: [{ name, pages, nums, source, items: [{n, page, snippet, kind}] }]
 */

// 章节来源的类型后缀（与后端 _chunk_display_name 同口径）：
//   课件 → 「{章节}课件」、讲稿 → 「{章节}讲解稿」、资料 → 「{章节} · 资料」
const CHAPTER_SUFFIX_RE = /(课件|讲解稿| ?· ?资料)$/

/** 章节归并键：能识别出章节后缀才返回章节名，否则返回空串（不参与归并） */
function chapterBaseOf(name) {
  const text = String(name || '')
  const m = CHAPTER_SUFFIX_RE.exec(text)
  if (!m) return ''
  return text.slice(0, m.index).trim()
}

// 来源类型的固定展示顺序：合并后按此顺序拼 source（material+ppt+script）
const SOURCE_ORDER = ['material', 'ppt', 'script', 'prev']

function normalizeSource(sources) {
  const kinds = new Set()
  for (const s of sources) {
    String(s || '')
      .split('+')
      .forEach((k) => {
        if (k) kinds.add(k)
      })
  }
  const ordered = SOURCE_ORDER.filter((k) => kinds.has(k))
  const extra = [...kinds].filter((k) => !SOURCE_ORDER.includes(k))
  return [...ordered, ...extra].join('+')
}

export function groupCitedSources(cited) {
  const groups = []
  const byName = new Map()
  for (const c of cited || []) {
    if (!c) continue
    const name = c.material_name || '课程资料'
    let g = byName.get(name)
    if (!g) {
      g = { name, pages: [], nums: [], sources: new Set(), items: [] }
      byName.set(name, g)
      groups.push(g)
    }
    if (c.source) g.sources.add(c.source)
    const p = Number(c.page)
    if (Number.isFinite(p) && p > 0) g.pages.push(p)
    const n = Number(c.n)
    if (Number.isFinite(n) && n > 0) g.nums.push(n)
    if (c.snippet) {
      g.items.push({
        n: Number.isFinite(n) && n > 0 ? n : null,
        page: Number.isFinite(p) && p > 0 ? p : null,
        snippet: c.snippet,
        kind: c.source || '',
      })
    }
  }

  // 第 2 层：同一章节的课件/讲稿/资料合并为一条（章节名做展示名）
  const byChapter = new Map()
  const merged = []
  for (const g of groups) {
    const base = chapterBaseOf(g.name)
    if (!base) {
      merged.push(g)
      continue
    }
    const exist = byChapter.get(base)
    if (!exist) {
      const ng = {
        name: base,
        pages: [...g.pages],
        nums: [...g.nums],
        sources: new Set(g.sources),
        items: [...g.items],
      }
      byChapter.set(base, ng)
      merged.push(ng)
      continue
    }
    exist.pages.push(...g.pages)
    exist.nums.push(...g.nums)
    g.sources.forEach((s) => exist.sources.add(s))
    exist.items.push(...g.items)
  }

  for (const g of merged) {
    g.pages = [...new Set(g.pages)].sort((a, b) => a - b)
    g.nums = [...new Set(g.nums)].sort((a, b) => a - b)
    g.source = normalizeSource(g.sources || [])
    delete g.sources
    // 详情里按编号升序，便于对照回答中的 [N]
    g.items.sort((a, b) => (a.n || 0) - (b.n || 0))
  }
  return merged
}

// 单条标签最多展示几个页码，超出用省略号（完整清单放在 title 与展开详情里）
const PAGES_INLINE_MAX = 4

function pageText(pages, limit) {
  const shown = limit && pages.length > limit ? pages.slice(0, limit) : pages
  const text = shown.map((p) => `P${p}`).join(' / ')
  return limit && pages.length > limit ? `${text} …` : text
}

/** 单条来源的展示文本：名称 + 汇总页码（无页码则仅名称，如原文拼接兜底条目） */
export function citedSourceLabel(g) {
  if (!g.pages.length) return g.name
  return `${g.name} ${pageText(g.pages, PAGES_INLINE_MAX)}`
}

/** 完整展示文本（hover 提示用，页码不省略） */
export function citedSourceFullLabel(g) {
  const base = g.pages.length ? `${g.name} ${pageText(g.pages)}` : g.name
  return g.nums?.length ? `${base}（引用 ${g.nums.join(' ')}）` : base
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
  if (!source) return ''
  if (SOURCE_BADGES[source]) return SOURCE_BADGES[source]
  // 章节合并后的多来源（如 material+ppt+script）：按顺序拼中文，查不到整串时逐项拆
  const parts = String(source)
    .split('+')
    .map((k) => SOURCE_BADGES[k])
    .filter(Boolean)
  return [...new Set(parts)].join('+')
}
