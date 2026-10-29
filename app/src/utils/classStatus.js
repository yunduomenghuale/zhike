/**
 * 班级状态枚举（与 frontend/src/utils/classStatus.js 保持一致）。
 *
 * 后端 ClassRoom.Status 为 preparing/active/graduated/archived，
 * 页面不要硬编码 'open'/'closed'，否则新增状态时会各处漏改。
 */
export const CLASS_STATUS_META = {
  preparing: { label: '筹备中', type: 'info' },
  active: { label: '在读', type: 'success' },
  graduated: { label: '已毕业', type: 'warning' },
  archived: { label: '已归档', type: 'info' },
}

export function classStatusMeta(status) {
  return CLASS_STATUS_META[status] || { label: status || '未知', type: 'info' }
}

export function classStatusLabel(status) {
  return classStatusMeta(status).label
}
