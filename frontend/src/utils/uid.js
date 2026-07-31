// 生成唯一 ID。crypto.randomUUID 仅在安全上下文（HTTPS 或 localhost）可用，
// HTTP 部署（如 http://IP:端口 访问）下需回退，否则抛 TypeError 中断业务流程
export function genUid() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}
