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
