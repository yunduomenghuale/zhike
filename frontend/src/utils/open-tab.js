/* 提前同步弹出新标签页（保留用户手势，避免异步请求后的 window.open 被弹窗拦截），
 * 异步完成后再把真实地址写入该标签。被拦截时回退为普通 window.open。
 */
export function openTabDeferred() {
  const tab = typeof window !== 'undefined' ? window.open('', '_blank') : null
  return {
    open(url) {
      if (tab && !tab.closed) tab.location.href = url
      else window.open(url, '_blank')
    },
    close() {
      try {
        if (tab && !tab.closed) tab.close()
      } catch {
        /* 忽略 */
      }
    },
  }
}

/* 触发浏览器下载而不新开标签页：隐藏 <a download> 点击。
 * 适用于后端返回 Content-Disposition: attachment 的签名地址
 * （doc/docx 等资源）——openTabDeferred 开 about:blank 再跳转会残留空标签页。
 */
export function downloadUrl(url) {
  const a = document.createElement('a')
  a.href = url
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
