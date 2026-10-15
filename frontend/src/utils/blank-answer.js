/**
 * 填空题答案工具：兼容旧版纯字符串数组与新版按空赋分对象数组。
 *
 * 数据结构（2026-10 起）：
 *   新版：answer.blanks = [{ text: '答案', score: 2 }, ...]（每空单独赋分，判分按空累计）
 *   旧版：answer.blanks = ['答案', ...]（整题赋分，判分全对满分/否则 0 分）
 * 学生答案恒为 { blanks: ['作答', ...] }（字符串数组），与版本无关。
 */

/** 标准答案的空列表 → [{ text, score }]，score 为 null 表示旧版无按空分值 */
export function blankItems(answer) {
  const blanks = answer && Array.isArray(answer.blanks) ? answer.blanks : []
  return blanks.map((b) => (
    b && typeof b === 'object'
      ? { text: String(b.text ?? ''), score: b.score == null ? null : Number(b.score) }
      : { text: String(b ?? ''), score: null }
  ))
}

/** 标准答案文本（「正确答案」展示用）：封装；继承；多态 */
export function blankAnswerText(answer, sep = '；') {
  return blankItems(answer)
    .map((it) => it.text.trim())
    .filter((t) => t !== '')
    .join(sep)
}

/** 空数量（学生端按此渲染输入框个数，至少 1） */
export function blankCount(answer) {
  return Math.max(1, blankItems(answer).length)
}
