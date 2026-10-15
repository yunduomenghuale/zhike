// 原生 XHR 上传：附件即传需要展示真实上传进度（axios 实例不直接暴露 upload.onprogress）
export function uploadWithProgress(method, url, body, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, url)
    const token = localStorage.getItem('access_token')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => {
      let payload = {}
      try {
        payload = JSON.parse(xhr.responseText || '{}')
      } catch {
        payload = {}
      }
      if (xhr.status >= 200 && xhr.status < 300 && (!('code' in payload) || payload.code === 0)) {
        resolve(payload)
      } else {
        reject(new Error(payload?.message || `上传失败（HTTP ${xhr.status}）`))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误，上传失败'))
    xhr.send(body)
  })
}

export function formatFileSize(bytes) {
  const size = Number(bytes || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

export function fileExtOf(name) {
  const parts = String(name || '').split('.')
  return parts.length > 1 ? String(parts.pop()).toUpperCase() : 'FILE'
}

export function isImageFile(name) {
  return /\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(String(name || ''))
}

export function fileNameFromUrl(url) {
  const raw = String(url || '').split('/').pop()?.split('?')[0] || '附件'
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}
