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

/* 经认证接口拉取文件并以 blob 方式打开/下载。
 * 背景：media 直链（/media/...）在零信任网关/公网 nginx 不转发该路径时 404，
 * 且 <a> 跳转无法携带 JWT，故改走带 Authorization 的 /api/ 接口取回 blob。
 * - inline=true（PDF/文本等可内嵌渲染类型）：复用用户手势占位新标签页，
 *   取回后写入 blob URL 内嵌预览（需后端接口支持 ?inline=1 返回 inline disposition）；
 * - 否则（word/ppt 等浏览器无法内嵌展示的类型）：关闭占位页，触发下载，
 *   文件名用原始文件名（blob URL 无 Content-Disposition，必须显式 a.download）。
 * fetchBlob: 返回 Blob 的异步函数（如 downloadMaterial(id, { inline })）；
 * fallbackName: 下载时展示的文件名；失败时关闭占位页并向上抛错由调用方提示。
 */
export async function openFetchedFile(fetchBlob, fallbackName = 'download', { inline = false } = {}) {
  const tab = openTabDeferred()
  let url = ''
  try {
    const blob = await fetchBlob()
    if (!(blob instanceof Blob)) throw new Error('unexpected-response')
    url = URL.createObjectURL(blob)
    if (inline) {
      tab.open(url)
      // blob URL 交给浏览器后即可延后释放；延迟留足 PDF viewer 加载时间
      setTimeout(() => URL.revokeObjectURL(url), 120000)
    } else {
      tab.close()
      const a = document.createElement('a')
      a.href = url
      a.download = fallbackName || 'download'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 120000)
    }
  } catch (err) {
    tab.close()
    if (url) URL.revokeObjectURL(url)
    throw err
  }
}
