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
// - 仅匹配独立出现的 [N]（前非单词字符、后非 (，避免误伤 [1](url) 等形态）；
// - 跳过代码段（与加粗兜底同一 CODE_SEGMENT 切分策略）。
export function linkCitations(html) {
  return String(html || '')
    .split(CODE_SEGMENT)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part.replace(
            /(?<![\w\]/])\[(\d{1,2})\](?!\()/g,
            '<sup class="cite-sup" data-cite="$1">[$1]</sup>'
          )
    )
    .join('')
}

// 问答回答的统一渲染：markdown + 引用上标
export function renderQaAnswer(text) {
  return linkCitations(renderAiMarkdown(text))
}
