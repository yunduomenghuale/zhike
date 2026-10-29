/**
 * 班级状态枚举的唯一前端来源。
 *
 * 后端 ClassRoom.Status 已从 open/closed 改为 preparing/active/graduated/archived
 * （见 docs/组织体系重构与智课复用-方案设计.md §4.1），页面不要再硬编码状态文案，
 * 否则新增状态时会各处漏改。
 */
export const CLASS_STATUS_META = {
  preparing: { label: '筹备中', type: 'info' },
  active: { label: '在读', type: 'success' },
  graduated: { label: '已毕业', type: 'warning' },
  archived: { label: '已归档', type: 'info' },
}

export const CLASS_STATUS_OPTIONS = Object.entries(CLASS_STATUS_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

export function classStatusMeta(status) {
  return CLASS_STATUS_META[status] || { label: status || '未知', type: 'info' }
}
