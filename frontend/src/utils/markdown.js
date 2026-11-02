import MarkdownIt from 'markdown-it'

// AI 生成内容的统一渲染入口。
// - linkify: false——避免 java.io / java.lang 这类名词被自动链化成链接，
//   点击后跳到浏览器搜索页（学生端 AI 助教实测问题）；
// - link_open/link_close 置空——模型主动输出的 markdown 链接也降级为纯文本，
//   课程问答为封闭域场景，外部链接均不可信、不需要。
const md = new MarkdownIt({ html: false, linkify: false, breaks: true })
md.renderer.rules.link_open = () => ''
md.renderer.rules.link_close = () => ''

// markdown-it 的强调解析遵循 CommonMark flanking 规则，模型输出经常不满足而原样漏出星号：
//   1) 内侧带空格：** "是什么" **（** 后跟空白不能开启强调）；
//   2) 紧贴标点/汉字：侧重于**"x"**（** 前是汉字、后是引号，左右都不 flanking）。
// 渲染后兜底：把 HTML 里残留的 **...** 换成 <strong>。
// - 内容已由 markdown-it 转义（< > & 均为实体），不引入 XSS 面；
// - [^*<>] 限制不跨星号、不跨标签，天然只作用于单个文本节点；
// - 行内代码/代码块原样保留（`` `**x**` `` 里的星号是字面量，不能被加粗）。
const CODE_SEGMENT = /(<code>[\s\S]*?<\/code>|<pre>[\s\S]*?<\/pre>)/g

function boldFallback(segment) {
  return segment
    .replace(/\*\*\*([^*<>]+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([^*<>]+?)\*\*/g, (_match, inner) => `<strong>${inner.trim()}</strong>`)
}

export function renderAiMarkdown(text) {
  const html = md.render(text || '')
  // split 带捕获组时代码段会留在结果里（奇数下标），原样拼回、不做加粗替换
  return html
    .split(CODE_SEGMENT)
    .map((part, index) => (index % 2 === 1 ? part : boldFallback(part)))
    .join('')
}

// 引用标注 [N] → 可点上标（配合问答参考来源编号 n，见 CitedSources 组件）：
// - 上标点击后由消息容器委托处理（滚动到来源区并闪烁高亮）；
// - 仅匹配独立出现的 [N]（前非单词字符/非 [、后非 (，避免误伤 [1](url) 等形态）；
// - 允许相邻引用 [3][4]：后者前是 ] 也必须命中（旧 lookbehind 把相邻引用的第二个漏掉）；
// - 跳过代码段（与加粗兜底同一 CODE_SEGMENT 切分策略）。
const CITE_TOKEN_RE = /(?<![\w/\[])\[(\d{1,2})\](?!\()/g
// markdown 源码里的代码段（``` 块与 `行内`）：计算引用顺序与替换编号时都要跳过，
// 否则代码里的 [1]（数组下标之类）会被当成引用、扰乱重编号
const MD_CODE_SEGMENT = /(```[\s\S]*?```|`[^`\n]*`)/g

export function linkCitations(html) {
  return String(html || '')
    .split(CODE_SEGMENT)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part.replace(
            CITE_TOKEN_RE,
            '<sup class="cite-sup" data-cite="$1">[$1]</sup>'
          )
    )
    .join('')
}

/** 正文引用编号按首次出现顺序去重（跳过代码段、跳过 [N](url) 链接） */
function collectCiteOrder(text) {
  const order = []
  const seen = new Set()
  String(text || '')
    .split(MD_CODE_SEGMENT)
    .forEach((part, index) => {
      if (index % 2 === 1) return // 代码段原样，不当引用
      for (const m of part.matchAll(CITE_TOKEN_RE)) {
        const n = Number(m[1])
        if (n > 0 && !seen.has(n)) {
          seen.add(n)
          order.push(n)
        }
      }
    })
  return order
}

/**
 * 引用重编号：把「后端注入槽位号」换成「参考来源的展示序号」。
 *
 * 为什么要重编号：N 是资料在上下文里的槽位号（1..8），模型只标其中几个
 * （生产实测 35% 的注入资料从未被标注），直接按原编号展示就会出现
 * 「来源从 3 开始，1、2 不见踪影」。这里按正文首次出现顺序重排成 1..M，
 * 正文里的 [N] 同步改写，保证「正文标号 ↔ 来源序号」一一对应且连续。
 *
 * - 只保留被正文标注过的来源（幽灵条目一并丢弃）；
 * - 正文一个标注都没有（或 cited 为空）时原样返回，交给上层走回退逻辑，
 *   避免来源区整块消失；
 * - 代码段内的 [N] 不参与。
 */
export function renumberCitations(answer, cited) {
  const text = String(answer || '')
  const list = cited || []
  const order = collectCiteOrder(text)
  const byN = new Map()
  for (const c of list) {
    const n = Number(c.n)
    if (Number.isFinite(n) && n > 0 && !byN.has(n)) byN.set(n, c)
  }
  const mapping = new Map()
  const renumbered = []
  for (const oldN of order) {
    const src = byN.get(oldN)
    if (!src) continue // 模型标了不存在的编号：不进来源，也不改正文
    const newN = renumbered.length + 1
    mapping.set(oldN, newN)
    renumbered.push({ ...src, n: newN })
  }
  if (!mapping.size) return { answer: text, cited: list }
  const newAnswer = text
    .split(MD_CODE_SEGMENT)
    .map((part, index) => {
      if (index % 2 === 1) return part
      return part.replace(CITE_TOKEN_RE, (full, d) => {
        const nn = mapping.get(Number(d))
        return nn ? `[${nn}]` : full
      })
    })
    .join('')
  return { answer: newAnswer, cited: renumbered }
}

// 问答回答的统一渲染：markdown + 引用上标。
// 传入 cited 时先做引用重编号（展示序号连续 1..M），正文与来源区共用同一套映射。
export function renderQaAnswer(text, cited) {
  const source = cited && cited.length ? renumberCitations(text, cited).answer : text
  return linkCitations(renderAiMarkdown(source))
}
