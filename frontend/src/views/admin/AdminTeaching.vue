<template>
  <div class="page-container admin-teaching">
    <header class="page-head">
      <div>
        <div class="eyebrow">TEACHING GOVERNANCE</div>
        <h1>教学监管</h1>
        <p>跨教师查看课程、班级、教师三个维度的运行情况，点击行查看详情。</p>
      </div>
    </header>

    <section class="teaching-card">
      <el-tabs v-model="activeTab" class="admin-tabs" @tab-change="switchTab">
        <el-tab-pane name="courses"><template #label><span class="tab-label"><el-icon><Reading /></el-icon>课程监管</span></template></el-tab-pane>
        <el-tab-pane name="classes"><template #label><span class="tab-label"><el-icon><School /></el-icon>班级监管</span></template></el-tab-pane>
        <el-tab-pane name="teachers"><template #label><span class="tab-label"><el-icon><UserFilled /></el-icon>教师监管</span></template></el-tab-pane>
      </el-tabs>

      <div class="toolbar">
        <el-input v-model="search" clearable :prefix-icon="Search" :placeholder="searchPlaceholder" @keyup.enter="applyFilters" @clear="applyFilters" />
        <el-select v-if="activeTab !== 'teachers'" v-model="statusFilter" clearable placeholder="全部状态" @change="applyFilters">
          <template v-if="activeTab === 'courses'">
            <el-option label="启用" value="active" /><el-option label="停用" value="inactive" /><el-option label="归档" value="archived" />
          </template>
          <template v-else>
            <el-option v-for="opt in CLASS_STATUS_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
          </template>
        </el-select>
        <el-button :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Download" :loading="exporting" @click="exportCsv">导出 CSV</el-button>
        <span>共 {{ total }} 条</span>
      </div>

      <!-- 课程监管（scrollbar-always-on：列总宽超容器时让横向滚动条常显，EP 默认仅 mousemove 才显示） -->
      <el-table v-if="activeTab === 'courses'" v-loading="loading" :data="rows" row-key="id" scrollbar-always-on @row-click="openCourseDetail">
        <el-table-column label="课程" min-width="150">
          <template #default="{ row }"><div class="entity"><span class="entity-icon course"><el-icon><Reading /></el-icon></span><div><strong :title="row.name">{{ row.name }}</strong><small :title="row.term || '未设置学期'">{{ row.term || '未设置学期' }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="授课教师" min-width="96"><template #default="{ row }"><strong :title="row.teacher_name || '未填写姓名'">{{ row.teacher_name || '未填写姓名' }}</strong><small class="block" :title="'@' + row.teacher_username">@{{ row.teacher_username }}</small></template></el-table-column>
        <el-table-column label="内容资产" min-width="166">
          <template #default="{ row }">
            <div class="asset-chips">
              <span class="asset-chip"><b>{{ row.catalog_count }}</b> 章节</span>
              <span class="asset-chip"><b>{{ row.ppt_count }}</b> 课件</span>
              <span class="asset-chip"><b>{{ row.video_count }}</b> 视频</span>
              <span class="asset-chip"><b>{{ row.question_count }}</b> 题目</span>
              <span class="asset-chip"><b>{{ row.homework_count }}</b> 作业</span>
              <span class="asset-chip"><b>{{ row.exam_count }}</b> 考试</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="关联班级" width="82" align="center"><template #default="{ row }"><b class="number">{{ row.class_count }}</b> 个</template></el-table-column>
        <el-table-column label="覆盖学生" width="82" align="center"><template #default="{ row }"><b class="number">{{ row.student_count }}</b> 人</template></el-table-column>
        <el-table-column label="课程状态" width="100">
          <template #default="{ row }">
            <el-select :model-value="row.status" size="small" @change="(value) => changeCourseStatus(row, value)" @click.stop>
              <el-option label="启用" value="active" /><el-option label="停用" value="inactive" /><el-option label="归档" value="archived" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="最近更新" width="108" show-overflow-tooltip><template #default="{ row }">{{ formatDate(row.last_content_update) }}</template></el-table-column>
        <el-table-column label="创建时间" width="108" show-overflow-tooltip><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      </el-table>

      <!-- 班级监管 -->
      <el-table v-else-if="activeTab === 'classes'" v-loading="loading" :data="rows" row-key="id" scrollbar-always-on @row-click="openClassDetail">
        <el-table-column label="班级" min-width="172">
          <template #default="{ row }"><div class="entity"><span class="entity-icon class"><el-icon><School /></el-icon></span><div><strong :title="row.name">{{ row.name }}</strong><small :title="dateRange(row)">{{ dateRange(row) }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="负责人" min-width="112"><template #default="{ row }"><strong :title="row.teacher_name || '未填写姓名'">{{ row.teacher_name || '未填写姓名' }}</strong><small class="block" :title="'@' + row.teacher_username">@{{ row.teacher_username }}</small></template></el-table-column>
        <el-table-column label="关联课程" width="82" align="center"><template #default="{ row }"><b class="number">{{ row.course_count }}</b> 门</template></el-table-column>
        <el-table-column label="班级学生" width="82" align="center"><template #default="{ row }"><b class="number">{{ row.student_count }}</b> 人</template></el-table-column>
        <el-table-column label="作业提交率" width="92" align="center">
          <template #default="{ row }"><span class="rate" :class="rateClass(row.homework_rate)">{{ row.homework_rate === null ? '—' : row.homework_rate + '%' }}</span></template>
        </el-table-column>
        <el-table-column label="考试完成率" width="92" align="center">
          <template #default="{ row }"><span class="rate" :class="rateClass(row.exam_rate)">{{ row.exam_rate === null ? '—' : row.exam_rate + '%' }}</span></template>
        </el-table-column>
        <el-table-column label="预警人数" width="78" align="center">
          <template #default="{ row }"><span v-if="row.warning_count" class="warn-count">{{ row.warning_count }}</span><span v-else class="rate ok">0</span></template>
        </el-table-column>
        <el-table-column label="状态" width="116">
          <template #default="{ row }">
            <el-select :model-value="row.status" size="small" @change="(value) => changeClassStatus(row, value)" @click.stop>
              <el-option v-for="opt in CLASS_STATUS_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </template>
        </el-table-column>
      </el-table>

      <!-- 教师监管：全列 min-width 弹性分配——若只留一个 flex 列，余量会被它独占（教师列曾因此占半屏） -->
      <el-table v-else v-loading="loading" :data="rows" row-key="id" scrollbar-always-on @row-click="openTeacherDetail">
        <el-table-column label="教师" min-width="130">
          <template #default="{ row }"><div class="entity"><span class="entity-icon teacher"><el-icon><UserFilled /></el-icon></span><div><strong :title="row.real_name || '未填写姓名'">{{ row.real_name || '未填写姓名' }}</strong><small :title="'@' + row.username">@{{ row.username }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="课程" min-width="76" align="center"><template #default="{ row }"><b class="number">{{ row.course_count }}</b> 门</template></el-table-column>
        <el-table-column label="班级" min-width="76" align="center"><template #default="{ row }"><b class="number">{{ row.class_count }}</b> 个</template></el-table-column>
        <el-table-column label="覆盖学生" min-width="82" align="center"><template #default="{ row }"><b class="number">{{ row.student_count }}</b> 人</template></el-table-column>
        <el-table-column label="AI 调用" min-width="78" align="center">
          <template #default="{ row }"><b class="number">{{ row.ai_calls || 0 }}</b> 次</template>
        </el-table-column>
        <el-table-column label="用量" min-width="86" align="center">
          <template #default="{ row }"><b class="number" :title="usageTitle(row)">{{ usageText(row) }}</b></template>
        </el-table-column>
        <el-table-column label="账号状态" min-width="80">
          <template #default="{ row }"><el-tag size="small" effect="light" :type="row.is_active ? 'success' : 'danger'">{{ row.is_active ? '正常' : '已停用' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最近活跃" min-width="108" show-overflow-tooltip><template #default="{ row }">{{ formatDate(row.last_active) }}</template></el-table-column>
        <el-table-column label="注册时间" min-width="108" show-overflow-tooltip><template #default="{ row }">{{ formatDate(row.date_joined) }}</template></el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" class="pager" background layout="prev, pager, next, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="changePage" />
    </section>

    <!-- 详情抽屉 -->
    <CourseDetailDrawer v-model="courseDrawer" :course-id="activeId" @open-class="openClassFromCourse" />
    <ClassDetailDrawer v-model="classDrawer" :class-id="activeId" />
    <TeacherDetailDrawer v-model="teacherDrawer" :teacher-id="activeId" @open-course="openCourseFromTeacher" @open-class="openClassFromTeacher" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Reading, School, Search, UserFilled } from '@element-plus/icons-vue'
import {
  exportAdminClasses, exportAdminCourses, exportAdminTeachers,
  listAdminClasses, listAdminCourses, listAdminTeachers,
  updateAdminClassStatus, updateAdminCourseStatus,
} from '@/api/admin'
import CourseDetailDrawer from '@/components/admin/drawers/CourseDetailDrawer.vue'
import ClassDetailDrawer from '@/components/admin/drawers/ClassDetailDrawer.vue'
import { CLASS_STATUS_OPTIONS } from '@/utils/classStatus'
import TeacherDetailDrawer from '@/components/admin/drawers/TeacherDetailDrawer.vue'

const activeTab = ref('courses'), search = ref(''), statusFilter = ref('')
const loading = ref(false), exporting = ref(false), rows = ref([]), total = ref(0), page = ref(1), pageSize = 10

// 抽屉状态（三种详情共用 activeId，按维度互斥打开）
const courseDrawer = ref(false), classDrawer = ref(false), teacherDrawer = ref(false)
const activeId = ref(null)

const searchPlaceholder = computed(() => (
  { courses: '搜索课程或教师', classes: '搜索班级或教师', teachers: '搜索教师姓名或用户名' }[activeTab.value]
))

function formatDate(value) { return value ? new Date(value).toLocaleDateString('zh-CN') : '—' }
function dateRange(row) { return `${row.start_at || '未设置'} 至 ${row.end_at || '未设置'}` }
function formatTokens(n) {
  if (!n) return '0'
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n)
}
// formatTokens 对万级数值自带空格（"3.8 万"），拼接单位时按需省略连接空格，避免 DOM 文本出现双空格
function withUnit(num, unit) { return num.includes(' ') ? `${num}${unit}` : `${num} ${unit}` }
// AI 用量：token 口径优先，无 token 的能力（语音合成）按字符，本地模型按条数（与教师详情抽屉口径一致）
function usageText(row) {
  if (row.ai_tokens) return formatTokens(row.ai_tokens)
  if (row.ai_chars) return withUnit(formatTokens(row.ai_chars), '字符')
  if (row.ai_items) return withUnit(formatTokens(row.ai_items), '条')
  return '0'
}
function usageTitle(row) {
  if (row.ai_tokens) return `${row.ai_tokens} Token`
  if (row.ai_chars) return `${row.ai_chars} 字符`
  if (row.ai_items) return `${row.ai_items} 条`
  return ''
}
function rateClass(rate) {
  if (rate === null || rate === undefined) return ''
  if (rate >= 80) return 'rate ok'
  if (rate >= 50) return 'rate mid'
  return 'rate low'
}
function applyFilters() { page.value = 1; load() }
function switchTab() { search.value = ''; statusFilter.value = ''; page.value = 1; load() }
function changePage(value) { page.value = value; load() }

async function load() {
  loading.value = true
  try {
    const params = { search: search.value, status: statusFilter.value, page: page.value, page_size: pageSize }
    if (activeTab.value === 'courses') {
      const res = await listAdminCourses(params)
      rows.value = res.items; total.value = res.total
    } else if (activeTab.value === 'classes') {
      const res = await listAdminClasses(params)
      rows.value = res.items; total.value = res.total
    } else {
      const res = await listAdminTeachers(params)
      rows.value = res.items; total.value = res.total
    }
  } finally { loading.value = false }
}

// ---- 详情抽屉 ----
function openCourseDetail(row) { activeId.value = row.id; courseDrawer.value = true }
function openClassDetail(row) { activeId.value = row.id; classDrawer.value = true }
function openTeacherDetail(row) { activeId.value = row.id; teacherDrawer.value = true }
function openClassFromCourse(classId) { courseDrawer.value = false; activeId.value = classId; classDrawer.value = true }
function openCourseFromTeacher(courseId) { teacherDrawer.value = false; activeId.value = courseId; courseDrawer.value = true }
function openClassFromTeacher(classId) { teacherDrawer.value = false; activeId.value = classId; classDrawer.value = true }

// ---- 干预：课程状态（服务端审计，前端直接切换）----
async function changeCourseStatus(row, value) {
  const previous = row.status
  row.status = value
  try {
    const updated = await updateAdminCourseStatus(row.id, value)
    Object.assign(row, updated)
    ElMessage.success('课程状态已更新')
  } catch {
    row.status = previous
  }
}

// ---- 干预：班级开课/结课（影响预览 + 二次确认 + 执行后回显）----
async function changeClassStatus(row, value) {
  const closing = value === 'closed'
  const action = closing ? '结课' : '重新开课'
  try {
    await ElMessageBox.confirm(
      `确定将班级「${row.name}」${action}吗？\n`
      + `影响范围：${row.student_count} 名在读学生、${row.course_count} 门关联课程。\n`
      + (closing ? '结课后进行中的作业与考试将随班级状态一并冻结，学生端不再展示新任务。' : '重新开课后该班级恢复可访问状态。'),
      `${action}影响确认`,
      { type: 'warning', confirmButtonText: `确认${action}`, cancelButtonText: '取消', customClass: 'admin-confirm-dialog' },
    )
  } catch {
    return // 用户取消
  }
  try {
    const updated = await updateAdminClassStatus(row.id, value)
    Object.assign(row, updated)
    ElMessage.success(
      `班级已${action}：影响 ${updated.affected?.students ?? 0} 名学生、`
      + `${updated.affected?.courses ?? 0} 门课程、${updated.affected?.active_homeworks ?? 0} 份进行中作业、`
      + `${updated.affected?.active_exams ?? 0} 场已发布考试（已记录审计）`,
    )
  } catch {
    // 失败保持原状，错误提示由请求层统一处理
  }
}

// ---- 导出 CSV（与筛选条件一致；上限 5000 行）----
async function exportCsv() {
  exporting.value = true
  try {
    const params = { search: search.value, status: statusFilter.value }
    const request = { courses: exportAdminCourses, classes: exportAdminClasses, teachers: exportAdminTeachers }[activeTab.value]
    const blob = await request(params)
    // 后端错误也可能以 blob（JSON）返回，先识别再落盘，避免下载到错误文件
    if (blob?.type && blob.type.includes('application/json')) {
      const text = await blob.text()
      let message = '导出失败'
      try { message = JSON.parse(text).message || message } catch { /* 保留默认文案 */ }
      ElMessage.error(message)
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `admin_${activeTab.value}_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载（单次上限 5000 行）')
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.admin-teaching{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}
.teaching-card{overflow:hidden;border:1px solid #e5edf8;border-radius:22px;background:#fff;box-shadow:0 18px 42px rgba(37,99,235,.07)}.admin-tabs{padding:0 20px}.admin-tabs :deep(.el-tabs__header){margin:0}.admin-tabs :deep(.el-tabs__content){display:none}.tab-label{height:58px;display:flex;align-items:center;gap:7px;font-weight:750}
.toolbar{min-height:66px;margin:0 -20px;padding:12px 20px;border-bottom:1px solid #edf2f7;background:#fbfdff;display:flex;align-items:center;gap:10px}.toolbar :deep(.el-input){width:min(380px,38vw)}.toolbar :deep(.el-select){width:140px}.toolbar>span{margin-left:auto;color:#94a3b8;font-size:13px}
.entity{display:flex;align-items:center;gap:12px}.entity>div{min-width:0;display:grid;gap:4px}.entity strong,.entity small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.entity small,.block{color:#94a3b8;font-size:12px}.block{display:block;margin-top:4px}.entity-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;flex:0 0 auto;font-size:19px}.entity-icon.course{color:#2563eb;background:#eff6ff}.entity-icon.class{color:#10b981;background:#ecfdf5}.entity-icon.teacher{color:#8b5cf6;background:#f5f3ff}.number{color:#2563eb;font-size:18px}.pager{justify-content:flex-end;padding:16px 18px;border-top:1px solid #eef2f7}
.asset-chips{display:flex;flex-wrap:wrap;gap:6px}.asset-chip{padding:2px 9px;border-radius:999px;background:#f1f5f9;color:#64748b;font-size:12px}.asset-chip b{color:#0f172a;font-weight:750}
.rate{font-weight:700}.rate.ok{color:#059669}.rate.mid{color:#d97706}.rate.low{color:#dc2626}.warn-count{color:#dc2626;font-weight:800}
.admin-teaching :deep(.el-table__row){cursor:pointer}
/* 单元格不换行：EP .cell 默认 white-space:normal，窄列下日期会被从 "/" 处折断（"2026/10/1\n6"）、
   四字表头也会被挤成两行；数值/日期列内容本就短，nowrap 保持单行。
   文本列（课程/教师/班级）内部的 .entity strong/small 自带 ellipsis，不受此影响 */
.teaching-card :deep(.el-table .cell){white-space:nowrap}
@media(max-width:720px){.page-head{align-items:flex-start;flex-direction:column}.toolbar{align-items:stretch;flex-wrap:wrap}.toolbar :deep(.el-input){width:100%}.toolbar>span{width:100%;margin-left:0}}
</style>
