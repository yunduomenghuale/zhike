<template>
  <el-drawer
    :model-value="modelValue" size="min(780px, 94vw)" :show-close="false"
    class="teacher-drawer" @close="$emit('update:modelValue', false)"
  >
    <template #header>
      <div class="drawer-head">
        <div class="drawer-title">
          <el-avatar :size="42" :icon="UserFilled" class="teacher-avatar" />
          <div>
            <strong>{{ detail?.real_name || detail?.username || '教师详情' }}</strong>
            <small v-if="detail">@{{ detail.username }}</small>
          </div>
        </div>
        <div class="drawer-head-actions">
          <el-tag v-if="detail" size="small" effect="light" :type="detail.is_active ? 'success' : 'danger'">{{ detail.is_active ? '账号正常' : '已停用' }}</el-tag>
          <button class="drawer-close" type="button" title="关闭" @click="$emit('update:modelValue', false)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <el-alert v-if="loadError" type="error" show-icon :closable="false" :title="loadError" />

      <template v-if="detail">
        <section class="stat-grid">
          <div class="stat-card"><span>注册时间</span><strong class="text">{{ formatDate(detail.date_joined) }}</strong></div>
          <div class="stat-card"><span>最近登录</span><strong class="text">{{ formatDate(detail.last_login) }}</strong></div>
          <div class="stat-card"><span>负责课程</span><strong>{{ detail.courses?.length ?? 0 }}</strong></div>
          <div class="stat-card"><span>负责班级</span><strong>{{ detail.classes?.length ?? 0 }}</strong></div>
        </section>

        <section class="block">
          <h3>AI 调用分布</h3>
          <div v-if="!detail.ai_by_capability?.length" class="empty">暂无 AI 调用记录</div>
          <template v-else>
            <el-table :data="detail.ai_by_capability" size="small">
              <el-table-column label="能力" min-width="130">
                <template #default="{ row }">{{ row.capability_display }}</template>
              </el-table-column>
              <el-table-column label="调用次数" width="110" align="center">
                <template #default="{ row }"><b class="number">{{ row.calls }}</b></template>
              </el-table-column>
              <el-table-column label="用量" width="130" align="center">
                <template #default="{ row }">
                  <b class="number" :title="usageTitle(row)">{{ usageText(row) }}</b>
                </template>
              </el-table-column>
              <el-table-column label="占比" min-width="150">
                <template #default="{ row }">
                  <el-progress :percentage="usagePercent(row)" :stroke-width="8" :show-text="false" color="#2563eb" />
                </template>
              </el-table-column>
            </el-table>
            <p class="meter-note">计量口径：对话生成 / 向量化 / 重排序按 Token，语音合成按合成字符数，本地内置模型按条数；占比为混合口径的相对值，仅供参考。</p>
          </template>
        </section>

        <section class="block">
          <h3>负责课程</h3>
          <div v-if="!detail.courses?.length" class="empty">暂无课程</div>
          <el-table v-else :data="detail.courses" size="small" max-height="240">
            <el-table-column label="课程" min-width="180" class-name="name-cell">
              <template #default="{ row }">
                <el-link type="primary" :underline="false" @click="$emit('open-course', row.id)">{{ row.name }}</el-link>
                <small class="block">{{ row.term || '未设置学期' }}</small>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" effect="light" :type="statusType(row.status)">{{ row.status_display }}</el-tag></template>
            </el-table-column>
            <el-table-column label="班级" width="90" align="center">
              <template #default="{ row }">{{ row.class_count }}</template>
            </el-table-column>
            <el-table-column label="覆盖学生" width="100" align="center">
              <template #default="{ row }">{{ row.student_count }}</template>
            </el-table-column>
          </el-table>
        </section>

        <section class="block">
          <h3>负责班级</h3>
          <div v-if="!detail.classes?.length" class="empty">暂无班级</div>
          <el-table v-else :data="detail.classes" size="small" max-height="240">
            <el-table-column label="班级" min-width="180" class-name="name-cell">
              <template #default="{ row }">
                <el-link type="primary" :underline="false" @click="$emit('open-class', row.id)">{{ row.name }}</el-link>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" effect="light" :type="row.status === 'open' ? 'success' : 'info'">{{ row.status === 'open' ? '开课中' : '已结课' }}</el-tag></template>
            </el-table-column>
            <el-table-column label="关联课程" width="100" align="center">
              <template #default="{ row }">{{ row.course_count }}</template>
            </el-table-column>
            <el-table-column label="学生" width="90" align="center">
              <template #default="{ row }">{{ row.student_count }}</template>
            </el-table-column>
          </el-table>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Close, UserFilled } from '@element-plus/icons-vue'
import { getAdminTeacherDetail } from '@/api/admin'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  teacherId: { type: [Number, String], default: null },
})
defineEmits(['update:modelValue', 'open-course', 'open-class'])

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)

function formatDate(value) { return value ? new Date(value).toLocaleDateString('zh-CN') : '—' }
function formatNum(n) {
  if (!n) return '0'
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n)
}
// formatNum 对万级数值自带空格（"3.8 万"），拼接单位时按需省略连接空格，避免 DOM 文本出现双空格
function withUnit(num, unit) { return num.includes(' ') ? `${num}${unit}` : `${num} ${unit}` }
function statusType(status) { return status === 'active' ? 'success' : status === 'archived' ? 'info' : 'warning' }

// ---- AI 用量：token 口径优先，无 token 的能力（语音合成）按字符，本地模型按条数 ----
function usageOf(row) {
  if (row.tokens) return { value: row.tokens, unit: '', raw: withUnit(formatNum(row.tokens), 'Token') }
  if (row.chars) return { value: row.chars, unit: '字符', raw: withUnit(formatNum(row.chars), '字符') }
  if (row.items) return { value: row.items, unit: '条', raw: withUnit(formatNum(row.items), '条') }
  return null
}
function usageText(row) {
  const u = usageOf(row)
  if (!u) return '—'
  const num = formatNum(u.value)
  return u.unit ? withUnit(num, u.unit) : num
}
function usageTitle(row) {
  const u = usageOf(row)
  return u ? u.raw : ''
}

// 混合口径的相对占比（各能力取自身主计量指标）
const usageTotal = computed(() => (
  detail.value?.ai_by_capability?.reduce((sum, r) => sum + (usageOf(r)?.value || 0), 0) || 0
))
function usagePercent(row) {
  if (!usageTotal.value) return 0
  return Math.round(((usageOf(row)?.value || 0) / usageTotal.value) * 100)
}

watch(
  () => [props.modelValue, props.teacherId],
  async ([visible]) => {
    if (!visible || !props.teacherId) return
    loading.value = true
    loadError.value = ''
    detail.value = null
    try {
      detail.value = await getAdminTeacherDetail(props.teacherId)
    } catch {
      loadError.value = '教师详情加载失败，请稍后重试。'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.drawer-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; }
.drawer-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.drawer-title > div { display: grid; gap: 4px; min-width: 0; }
.drawer-title strong { color: #0f172a; font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.drawer-title small { color: #94a3b8; font-size: 12px; }
.drawer-head-actions { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.teacher-avatar { background: linear-gradient(135deg, #2563eb, #4f46e5); color: #fff; flex: 0 0 auto; }
.drawer-close {
  width: 34px; height: 34px; border: 1px solid #e5edf8; border-radius: 10px;
  background: #fff; color: #64748b; cursor: pointer; display: grid; place-items: center; font-size: 16px;
}
.drawer-close:hover { color: #2563eb; border-color: #bfdbfe; background: #f8fbff; }
.drawer-body { color: #0f172a; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 22px; }
.stat-card { padding: 14px 16px; border: 1px solid #e5edf8; border-radius: 14px; background: #fff; display: grid; gap: 6px; }
.stat-card span { color: #718096; font-size: 12px; font-weight: 700; }
.stat-card strong { font-size: 20px; line-height: 1.1; }
.stat-card strong.text { font-size: 14px; }
.block { margin-bottom: 26px; }
.block h3 { margin: 0 0 12px; font-size: 15px; display: flex; align-items: baseline; gap: 8px; }
.empty { padding: 26px 0; text-align: center; color: #94a3b8; font-size: 13px; border: 1px dashed #e2e8f0; border-radius: 14px; }
.number { color: #2563eb; font-size: 15px; }
.meter-note { margin: 8px 2px 0; color: #94a3b8; font-size: 12px; line-height: 1.6; }
.block :deep(.el-table__cell) { padding: 7px 0; }
</style>

<style>
.teacher-drawer.el-drawer { border-radius: 22px 0 0 22px; overflow: hidden; }
.teacher-drawer .el-drawer__header { margin: 0; padding: 18px 22px; border-bottom: 1px solid #edf2f7; color: #0f172a; }
.teacher-drawer .el-drawer__body { padding: 20px 22px 28px; }
/* name-cell 双行内容（链接+次级行）的行高修复：
   ① flex 列布局消除模板空白文本节点生成的匿名行盒；
   ② 次级行的 class="block" 与 scoped 段落容器 .block{margin-bottom:26px} 撞名，
      margin 被继承进单元格把行高撑到 90px——必须显式 margin 复位覆盖 */
.teacher-drawer .name-cell .cell { white-space: normal; word-break: break-all; display: flex; flex-direction: column; align-items: flex-start; }
.teacher-drawer .name-cell .block { display: block; margin: 3px 0 0; color: #94a3b8; font-size: 12px; font-weight: 400; }
</style>
