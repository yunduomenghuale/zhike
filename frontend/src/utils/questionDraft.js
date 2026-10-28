// 题目表单态 ↔ 草稿态纯函数（QuestionFormFields 与 QuestionDraftPreview 共用）。
// 表单态：前端编辑用（选项/答案拆成 answerKey/answerKeys/blanks/answerText）。
// 草稿态：与后端 import_parser / question_gen_ai 输出、入库管道入参同构：
//   {qtype, stem, options:[{key,text}], answer, analysis, score, difficulty}
// 答案契约：单选 {key} / 多选 {keys} / 判断 {key:A|B} / 填空 {blanks:[{text,score}]} / 简答 {text}

export const DEFAULT_QTYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multi', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
]

// 题目用途分类（与后端 SceneTag.code 对齐）：新建默认 练习+作业（考试显式勾选防泄题）
export const SCENE_OPTIONS = [
  { code: 'practice', label: '章节练习' },
  { code: 'homework', label: '作业' },
  { code: 'exam', label: '考试' },
]
export const DEFAULT_SCENES = ['practice', 'homework']
export const sceneLabel = (code) => SCENE_OPTIONS.find((s) => s.code === code)?.label || code

function defaultOptions() {
  return [
    { key: 'A', text: '' }, { key: 'B', text: '' },
    { key: 'C', text: '' }, { key: 'D', text: '' },
  ]
}

/** 载入既有填空题答案：旧版字符串按题库总分均分预填（与后端 _split_score 同口径：余数补给前几个空） */
export function distributeScore(blanks, totalScore) {
  const list = Array.isArray(blanks) && blanks.length ? blanks : ['']
  const n = list.length
  const tenths = Math.round(Number(totalScore || 0) * 10)
  const base = Math.floor(tenths / n)
  const rem = tenths % n
  return list.map((b, i) => {
    if (typeof b === 'string') return { text: b, score: (base + (i < rem ? 1 : 0)) / 10 || 1 }
    return { text: b?.text || '', score: Number(b?.score) || 1 }
  })
}

/** 草稿态 → 表单态（预览/编辑入口） */
export function draftToForm(d = {}) {
  return {
    qtype: d.qtype || 'single',
    stem: d.stem || '',
    image: d.image || '', // 题图：媒体库相对路径（question_images/ 前缀），展示用 /media/ 拼 URL
    options: Array.isArray(d.options) && d.options.length
      ? d.options.map((o) => ({ key: o.key, text: o.text ?? '' }))
      : defaultOptions(),
    answerKey: d.answer?.key || '',
    answerKeys: Array.isArray(d.answer?.keys) ? [...d.answer.keys] : [],
    blanks: Array.isArray(d.answer?.blanks) && d.answer.blanks.length
      ? d.answer.blanks.map((b) => ({ text: b?.text ?? '', score: Number(b?.score) || 1 }))
      : distributeScore(null, d.score),
    answerText: d.answer?.text || '',
    analysis: d.analysis || '',
    score: Number(d.score) || 2,
    difficulty: d.difficulty || 'medium',
    scenes: Array.isArray(d.scenes) && d.scenes.length ? [...d.scenes] : [...DEFAULT_SCENES],
  }
}

export function blankScoreTotal(form) {
  return (form.blanks || []).reduce((sum, b) => sum + (Number(b?.score) || 0), 0)
}

export function buildAnswer(form) {
  if (form.qtype === 'single' || form.qtype === 'judge') return { key: form.answerKey }
  if (form.qtype === 'multi') return { keys: form.answerKeys }
  // 填空题：按空赋分，总分由后端按 Σ空分重算
  if (form.qtype === 'blank') {
    return {
      blanks: form.blanks
        .filter((b) => b.text && b.text.trim())
        .map((b) => ({ text: b.text.trim(), score: Number(b.score) || 0 })),
    }
  }
  // 简答题：参考答案（answer.text），学生端/教师端批改页以「参考答案」展示
  if (form.qtype === 'short') return form.answerText.trim() ? { text: form.answerText.trim() } : {}
  return {}
}

export function buildOptions(form) {
  if (form.qtype === 'single' || form.qtype === 'multi') return form.options.filter((o) => o.text !== '')
  if (form.qtype === 'judge') return [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }]
  return []
}

/** 表单态 → 草稿态（规范化字段，供 save / 预览防抖回传合并进 drafts） */
export function formToDraft(form) {
  return {
    qtype: form.qtype,
    stem: (form.stem || '').trim(),
    image: (form.image || '').trim(),
    options: buildOptions(form),
    answer: buildAnswer(form),
    analysis: (form.analysis || '').trim(),
    // 填空题总分 = Σ空分（后端入库管道按此均分校验）
    score: form.qtype === 'blank' ? blankScoreTotal(form) : (Number(form.score) || 0),
    difficulty: form.difficulty || 'medium',
    scenes: Array.isArray(form.scenes) && form.scenes.length ? [...form.scenes] : [...DEFAULT_SCENES],
  }
}
