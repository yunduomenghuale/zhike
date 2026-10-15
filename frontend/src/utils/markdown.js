import MarkdownIt from 'markdown-it'

// AI 生成内容的统一渲染入口。
// - linkify: false——避免 java.io / java.lang 这类名词被自动链化成链接，
//   点击后跳到浏览器搜索页（学生端 AI 助教实测问题）；
// - link_open/link_close 置空——模型主动输出的 markdown 链接也降级为纯文本，
//   课程问答为封闭域场景，外部链接均不可信、不需要。
const md = new MarkdownIt({ html: false, linkify: false, breaks: true })
md.renderer.rules.link_open = () => ''
md.renderer.rules.link_close = () => ''

export function renderAiMarkdown(text) {
  return md.render(text || '')
}
