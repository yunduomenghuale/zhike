// 课程名「首字母」排序工具：班级选择器标签、班级卡片课程列表等展示场景共用。
//
// 规则（通讯录式，符合国内习惯）：
// 1. 英文/数字开头的课名按字母序在前，中文开头的按拼音序在后
//    （如 Java程序设计 排在 真实测试课程 前，即 J < Z 的首字母预期）；
// 2. 组内用 localeCompare 指定 zh 语域走 ICU 拼音拼序（编译原理 < 操作系统 < 数据结构）。
//
// 坑：不能直接用 localeCompare(b, 'zh-Hans-CN') 一把梭——zh 拼序把中文整体排在
// 英文前（实测「真实…」会排在「Java…」前），违背首字母预期，必须先分组。

/**
 * 两个课程名的比较函数（可直接传给 Array.prototype.sort）。
 * @param {string} a
 * @param {string} b
 * @returns {number}
 */
export function compareCourseName(a, b) {
  const sa = String(a ?? '')
  const sb = String(b ?? '')
  const latinA = /^[\x00-\x7F]/.test(sa)
  const latinB = /^[\x00-\x7F]/.test(sb)
  if (latinA !== latinB) return latinA ? -1 : 1
  return sa.localeCompare(sb, 'zh-Hans-CN')
}

/**
 * 取班级/课程对象的课程名列表，按首字母排序后返回（不修改入参）。
 * 无 course_names 时回退单课程 course_name；都没有则返回空数组。
 * @param {{ course_names?: string[], course_name?: string } | null | undefined} item
 * @returns {string[]}
 */
export function sortedCourseNames(item) {
  const names = item?.course_names
  if (Array.isArray(names) && names.length) {
    return [...names].sort(compareCourseName)
  }
  return item?.course_name ? [item.course_name] : []
}
