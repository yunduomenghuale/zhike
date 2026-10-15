// 题型/难度简写映射（题目选择器左右结构下收窄列宽共用）
// 优先按原始值映射；快照等仅有展示文本的数据回退按文本处理
const QTYPE_ABBR = { single: '单选', multi: '多选', judge: '判断', blank: '填空', short: '简答' }
const DIFFICULTY_ABBR = { easy: '易', medium: '中', hard: '难' }
const DIFFICULTY_DISPLAY_ABBR = { 简单: '易', 中等: '中', 困难: '难' }

export function abbrQtype(row) {
  if (row?.qtype && QTYPE_ABBR[row.qtype]) return QTYPE_ABBR[row.qtype]
  return String(row?.qtype_display || '').replace(/题$/, '') || '—'
}

export function abbrDifficulty(row) {
  if (row?.difficulty && DIFFICULTY_ABBR[row.difficulty]) return DIFFICULTY_ABBR[row.difficulty]
  const display = String(row?.difficulty_display || '')
  return DIFFICULTY_DISPLAY_ABBR[display] || display || '—'
}
