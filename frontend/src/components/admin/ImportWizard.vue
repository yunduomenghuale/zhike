<template>
  <el-dialog
    v-model="visible"
    :title="config.title"
    :width="step === 'preview' ? '960px' : '720px'"
    align-center
    :close-on-click-modal="false"
    class="import-wizard"
    @closed="reset"
  >
    <div class="wz-steps">
      <div v-for="(label, idx) in ['上传文件', '核对预览', '导入结果']" :key="label"
           class="wz-step" :class="stepClass(idx)">
        <span class="wz-dot">{{ idx + 1 }}</span>
        <span class="wz-label">{{ label }}</span>
        <i v-if="idx < 2" class="wz-line" />
      </div>
    </div>

    <!-- 1 上传 -->
    <div v-if="step === 'upload'" class="wz-upload">
      <div class="wz-card">
        <div class="wz-card-no">1</div>
        <div class="wz-card-body">
          <strong>先下载模板</strong>
          <p>{{ config.templateHint }}</p>
          <el-button size="small" :icon="Download" :loading="downloading" @click="downloadTemplate">
            下载{{ config.entity }}导入模板
          </el-button>
        </div>
      </div>
      <div class="wz-card">
        <div class="wz-card-no">2</div>
        <div class="wz-card-body">
          <strong>上传填好的表格</strong>
          <p>{{ config.uploadHint }}</p>
          <el-upload drag :show-file-list="false" accept=".xlsx" :http-request="handleUpload" class="wz-drop">
            <el-icon class="wz-drop-icon"><UploadFilled /></el-icon>
            <div class="wz-drop-text">把 .xlsx 拖到这里，或<em>点击选择文件</em></div>
            <div class="wz-drop-tip">仅支持 .xlsx，单次不超过 {{ config.maxRows }} 行 / 5MB</div>
          </el-upload>
          <div v-if="parsing" class="wz-parsing">
            <el-icon class="is-loading"><Loading /></el-icon> 正在解析并逐行校验…
          </div>
        </div>
      </div>
      <ul class="wz-tips">
        <li v-for="tip in config.tips" :key="tip">{{ tip }}</li>
      </ul>
    </div>

    <!-- 2 预览 -->
    <div v-else-if="step === 'preview'" class="wz-preview">
      <div class="wz-file">
        <el-icon><Document /></el-icon>
        <span class="wz-file-name">{{ fileName }}</span>
        <el-button link type="primary" :icon="RefreshLeft" @click="reset">重新上传</el-button>
      </div>

      <div class="wz-summary">
        <span>共 <b>{{ summary.total || 0 }}</b> 行</span>
        <span class="ok">可导入 <b>{{ summary.ok || 0 }}</b></span>
        <span v-if="summary.skipped" class="skip">跳过 <b>{{ summary.skipped }}</b></span>
        <span v-if="summary.error" class="err">待修正 <b>{{ summary.error }}</b></span>
        <span v-if="pendingList.length" class="pending">
          待建班级 <b>{{ pendingList.length }}</b> 个 / {{ summary.pending_student_count || 0 }} 人
        </span>
      </div>

      <!-- 学生导入：待建班级确认 -->
      <template v-if="kind === 'student' && pendingList.length">
        <div class="wz-section">
          <div class="wz-section-head">
            <strong>待新建的班级（{{ approved.length }}/{{ pendingList.length }} 已勾选）</strong>
            <span class="wz-hint">表格里的班级编码系统里还没有。勾选后才会建班并把学生放进去；不勾选则对应学生行不会导入。</span>
          </div>
          <el-table :data="pendingList" size="small" class="wz-table wz-pending-table" max-height="220">
            <el-table-column width="52" align="center">
              <template #header>
                <el-checkbox :model-value="allApproved" :indeterminate="someApproved && !allApproved"
                             @change="toggleAll" />
              </template>
              <template #default="{ row }">
                <el-checkbox :model-value="approved.includes(row.code)" @change="toggle(row.code)" />
              </template>
            </el-table-column>
            <el-table-column label="班级编码" prop="code" width="140" />
            <el-table-column label="班级名称（可改）" min-width="200">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" maxlength="200"
                          @input="syncName(row.code, row.name)" />
              </template>
            </el-table-column>
            <el-table-column label="届别" width="120">
              <template #default="{ row }">
                <el-input-number v-model="row.enrollment_year" :min="2000" :max="2100"
                                 :controls="false" size="small" class="wz-year"
                                 @change="syncYear(row.code, row.enrollment_year)" />
              </template>
            </el-table-column>
            <el-table-column label="将入班" width="90" align="right">
              <template #default="{ row }">{{ row.student_count }} 人</template>
            </el-table-column>
          </el-table>
        </div>
      </template>

      <!-- 选项 -->
      <div class="wz-section wz-options">
        <template v-if="kind === 'student'">
          <el-checkbox v-model="options.createMissing">
            编码不存在时允许自动建班（关闭后这些行会报错）
          </el-checkbox>
          <div class="wz-option-line">
            <span>新建班级默认学制</span>
            <el-select v-model="options.duration" size="small" style="width:96px">
              <el-option v-for="d in [2, 3, 4, 5]" :key="d" :label="`${d} 年`" :value="d" />
            </el-select>
            <span class="wz-hint">未填届别的班级按上方「届别」列，学制统一取此值</span>
          </div>
        </template>
        <el-checkbox v-if="summary.error" v-model="options.skipInvalid" class="wz-danger wz-skip-invalid">
          跳过待修正的 {{ summary.error }} 行，其余照常导入（不勾选则整批不导入）
        </el-checkbox>
      </div>

      <!-- 行明细 -->
      <div class="wz-section">
        <div class="wz-section-head">
          <strong>{{ showAll ? '全部行' : '需要处理的行' }}</strong>
          <el-button v-if="problemRows.length" link type="primary" @click="showAll = !showAll">
            {{ showAll ? '只看问题行' : `查看全部 ${rows.length} 行` }}
          </el-button>
          <span v-else class="wz-hint">全部行均可导入</span>
        </div>
        <el-table :data="visibleRows" size="small" max-height="260" class="wz-table wz-rows-table"
                  :row-class-name="rowClass">
          <el-table-column label="行号" prop="row_no" width="64" align="center" />
          <el-table-column v-for="col in config.columns" :key="col.key" :label="col.label"
                           :prop="col.key" :width="col.width" :min-width="col.minWidth">
            <template #default="{ row }">
              <span :title="String(row[col.key] ?? '')">{{ row[col.key] ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="88" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.row_status)" effect="light">
                {{ statusText(row.row_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="180">
            <template #default="{ row }">
              <span :class="row.row_status === 'error' ? 'wz-msg-err' : 'wz-msg'">{{ row.message || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 3 结果 -->
    <div v-else class="wz-result">
      <div class="wz-result-head">
        <el-icon class="wz-result-icon"><CircleCheckFilled /></el-icon>
        <div>
          <strong>导入完成</strong>
          <p>{{ resultText }}</p>
        </div>
      </div>
      <div class="wz-stats">
        <div class="wz-stat"><em>{{ result.created_users || 0 }}</em><span>新建账号</span></div>
        <div class="wz-stat"><em>{{ (result.created_classes || []).length }}</em><span>新建班级</span></div>
        <div class="wz-stat"><em>{{ result.created_members || 0 }}</em><span>入班人数</span></div>
        <div class="wz-stat"><em>{{ result.skipped || 0 }}</em><span>跳过行</span></div>
        <div class="wz-stat" :class="{ danger: result.failed }">
          <em>{{ result.failed || 0 }}</em><span>失败行</span>
        </div>
      </div>

      <div v-if="(result.created_classes || []).length" class="wz-section">
        <div class="wz-section-head"><strong>新建的班级</strong></div>
        <div class="wz-chips">
          <span v-for="item in result.created_classes" :key="item.id" class="wz-chip">
            {{ item.name }}<em>{{ item.code }}</em>
          </span>
        </div>
      </div>

      <div v-if="result.failures && result.failures.length" class="wz-section">
        <div class="wz-section-head"><strong>未导入的行</strong>
          <span class="wz-hint">下载失败行清单，改完后可直接再传一次</span>
        </div>
        <el-table :data="result.failures" size="small" max-height="200" class="wz-table">
          <el-table-column label="行号" prop="row_no" width="64" align="center" />
          <el-table-column label="账号/编码" width="180">
            <template #default="{ row }">{{ row.username || row.code || '—' }}</template>
          </el-table-column>
          <el-table-column label="原因" prop="message" min-width="240" />
        </el-table>
      </div>

      <div class="wz-downloads">
        <el-button v-if="result.failure_file" class="wz-dl-failure" :icon="Download" @click="saveFile(result.failure_file)">
          下载失败行（{{ result.failed }} 条）
        </el-button>
        <el-button v-if="result.password_file" class="wz-dl-password" type="primary" plain :icon="Key" @click="saveFile(result.password_file)">
          下载初始密码表
        </el-button>
        <span v-if="result.password_file" class="wz-hint">
          初始密码规则：Zk + 账号后 6 位；请通过安全渠道发给他本人
        </span>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">{{ step === 'result' ? '关闭' : '取消' }}</el-button>
      <el-button v-if="step === 'preview'" @click="reset">重新上传</el-button>
      <el-button v-if="step === 'preview'" class="wz-submit" type="primary" :loading="committing" @click="submit">
        确认导入
      </el-button>
      <el-button v-if="step === 'result'" type="primary" @click="visible = false">完成</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheckFilled, Document, Download, Key, Loading, RefreshLeft, UploadFilled,
} from '@element-plus/icons-vue'
import { commitImport, downloadImportTemplate, previewImport } from '@/api/admin'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // class / teacher / student
  kind: { type: String, default: 'student' },
})
const emit = defineEmits(['update:modelValue', 'done'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const kind = computed(() => (['class', 'teacher', 'student'].includes(props.kind) ? props.kind : 'student'))

const CONFIG = {
  class: {
    title: '批量导入班级',
    entity: '班级',
    maxRows: 200,
    templateHint: '模板含「班级编码 / 班级名称 / 入学年 / 学制 / 状态」五列，必填列标了 *。',
    uploadHint: '一行一个班级。编码已存在的行会标记为跳过，不会覆盖已有班级。',
    tips: [
      '班级编码是学生导入时的匹配键，3–32 位字母/数字/短横线，全平台唯一（不区分大小写）。',
      '入学年填 4 位年份，学制填 2/3/4/5；系统按「入学年 + 学制」推算预计毕业年份。',
      '状态留空按「在读」处理，可填「筹备中」用于提前建班。',
    ],
    columns: [
      { label: '班级编码', key: 'code', width: 130 },
      { label: '班级名称', key: 'name', minWidth: 160 },
      { label: '入学年', key: 'enrollment_year', width: 84 },
      { label: '学制', key: 'duration_years', width: 64 },
      { label: '状态', key: 'status_display', width: 84 },
    ],
    fields: ['row_no', 'code', 'name', 'enrollment_year', 'duration_years', 'status'],
  },
  teacher: {
    title: '批量导入教师',
    entity: '教师',
    maxRows: 500,
    templateHint: '模板只有「工号 / 姓名」两列，工号即登录账号。',
    uploadHint: '一行一位教师。工号已存在的行会标记为跳过，不会覆盖已有账号。',
    tips: [
      '工号 6~8 位且只能由字母和数字组成（初始密码取后 6 位），全平台唯一且不区分大小写。',
      '导入后账号状态为「首次登录需修改密码」。',
      '初始密码表在导入结果页下载，请通过安全渠道发给本人。',
    ],
    columns: [
      { label: '工号', key: 'username', width: 150 },
      { label: '姓名', key: 'real_name', minWidth: 140 },
    ],
    fields: ['row_no', 'username', 'real_name'],
  },
  student: {
    title: '批量导入学生',
    entity: '学生',
    maxRows: 500,
    templateHint: '模板含「学号 / 姓名 / 班级编码 / 班级名称 / 入学年」五列，只有学号与姓名必填。',
    uploadHint: '一行一名学生。班级编码留空则只建账号不入班；编码不存在时可确认自动建班。',
    tips: [
      '学号 6~8 位且只能由字母和数字组成（初始密码取后 6 位），全平台唯一且不区分大小写。',
      '一名学生只能在一个班；已在其他班的学生会标记为跳过，转班请先移除原班级关系。',
      '班级编码不存在时，预览页会列出待建班级，勾选确认后自动建班并放人。',
    ],
    columns: [
      { label: '学号', key: 'username', width: 130 },
      { label: '姓名', key: 'real_name', width: 110 },
      { label: '班级编码', key: 'class_code', width: 120 },
      { label: '班级名称', key: 'class_name', minWidth: 140 },
      { label: '入学年', key: 'enrollment_year', width: 84 },
    ],
    fields: ['row_no', 'username', 'real_name', 'class_code', 'class_name', 'enrollment_year'],
  },
}
const config = computed(() => CONFIG[kind.value])

const step = ref('upload')
const fileName = ref('')
const parsing = ref(false)
const committing = ref(false)
const downloading = ref(false)
const showAll = ref(false)
const data = ref({ rows: [], summary: {}, pending_classes: [] })
const result = ref({})
const approved = ref([])
const options = reactive({ skipInvalid: false, createMissing: true, duration: 4 })

const rows = computed(() => data.value.rows || [])
const summary = computed(() => data.value.summary || {})
const pendingList = computed(() => data.value.pending_classes || [])
const problemRows = computed(() => rows.value.filter((row) => row.row_status !== 'ok'))
const visibleRows = computed(() => {
  if (showAll.value || !problemRows.value.length) return rows.value
  return problemRows.value
})
const allApproved = computed(() => pendingList.value.length > 0 && approved.value.length === pendingList.value.length)
const someApproved = computed(() => approved.value.length > 0)

const resultText = computed(() => {
  const parts = []
  if (result.value.created_users) parts.push(`新建 ${result.value.created_users} 个账号`)
  if ((result.value.created_classes || []).length) parts.push(`新建 ${result.value.created_classes.length} 个班级`)
  if (result.value.created_members) parts.push(`${result.value.created_members} 人已入班`)
  if (result.value.skipped) parts.push(`跳过 ${result.value.skipped} 行`)
  if (result.value.failed) parts.push(`${result.value.failed} 行未能导入`)
  return parts.length ? parts.join('，') : '没有任何数据被写入'
})

function stepClass(idx) {
  const order = { upload: 0, preview: 1, result: 2 }
  const current = order[step.value] ?? 0
  if (idx < current) return 'done'
  if (idx === current) return 'active'
  return ''
}

function statusType(status) {
  return { ok: 'success', error: 'danger', skipped: 'info' }[status] || 'info'
}
function statusText(status) {
  return { ok: '可导入', error: '待修正', skipped: '跳过' }[status] || status
}
function rowClass({ row }) {
  return row.row_status === 'error' ? 'wz-row-err' : ''
}

function reset() {
  step.value = 'upload'
  fileName.value = ''
  parsing.value = false
  committing.value = false
  showAll.value = false
  data.value = { rows: [], summary: {}, pending_classes: [] }
  result.value = {}
  approved.value = []
  options.skipInvalid = false
  options.createMissing = true
  options.duration = 4
}

async function downloadTemplate() {
  downloading.value = true
  try {
    const blob = await downloadImportTemplate(kind.value)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${config.value.entity}导入模板.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  } catch { /* 拦截器已提示 */ } finally {
    downloading.value = false
  }
}

async function handleUpload({ file }) {
  if (!/\.xlsx$/i.test(file.name || '')) {
    ElMessage.warning('仅支持 .xlsx 文件，请使用系统模板')
    return
  }
  parsing.value = true
  try {
    const payload = await previewImport(kind.value, file, { create_missing_classes: options.createMissing })
    data.value = payload
    fileName.value = payload.file_name || file.name
    approved.value = []
    step.value = 'preview'
    const { summary: sum } = payload
    if (!sum.error && !sum.skipped) {
      ElMessage.success(`解析完成，${sum.total} 行全部可导入`)
    } else {
      ElMessage.warning(`解析完成：可导入 ${sum.ok}/${sum.total} 行${sum.error ? `，${sum.error} 行待修正` : ''}`)
    }
  } catch { /* 文件级错误由拦截器统一提示 */ } finally {
    parsing.value = false
  }
}

function toggle(code) {
  const index = approved.value.indexOf(code)
  if (index >= 0) approved.value.splice(index, 1)
  else approved.value.push(code)
}
function toggleAll(checked) {
  approved.value = checked ? pendingList.value.map((item) => item.code) : []
}

/** 在待建班级表里改名/改届别，回写到行数据——提交时服务端只会读 rows。 */
function syncName(code, name) {
  rows.value.forEach((row) => {
    if (row.class_code === code) row.class_name = name
  })
}
function syncYear(code, year) {
  rows.value.forEach((row) => {
    if (row.class_code === code) row.enrollment_year = year
  })
}

function payloadRows() {
  const fields = config.value.fields
  return rows.value.map((row) => {
    const item = {}
    fields.forEach((key) => { item[key] = row[key] ?? '' })
    return item
  })
}

async function submit() {
  if (!rows.value.length) return
  if (summary.value.error && !options.skipInvalid) {
    ElMessage.warning(`还有 ${summary.value.error} 行待修正：勾选「跳过待修正的行」或返回改表格`)
    return
  }
  const unchecked = pendingList.value.filter((item) => !approved.value.includes(item.code))
  if (kind.value === 'student' && unchecked.length) {
    try {
      await ElMessageBox.confirm(
        `有 ${unchecked.length} 个待建班级未勾选（${unchecked.map((i) => i.code).join('、')}），`
        + '这些编码下的学生不会导入。确定继续吗？',
        '还有未确认的班级', { type: 'warning', confirmButtonText: '继续导入' },
      )
    } catch { return }
  }

  committing.value = true
  try {
    const payload = await commitImport(kind.value, payloadRows(), {
      skip_invalid: options.skipInvalid,
      create_missing_classes: options.createMissing,
      default_duration_years: options.duration,
      approved_classes: approved.value,
    })
    result.value = payload
    step.value = 'result'
    emit('done', payload)
  } catch { /* 400 会带上逐行结果，但后端已在 message 里说清原因 */ } finally {
    committing.value = false
  }
}

function saveFile(file) {
  const binary = atob(file.content_base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.wz-steps{display:flex;align-items:center;gap:10px;margin:-6px 0 18px}
.wz-step{display:flex;align-items:center;gap:8px;color:#94a3b8;font-size:13px}
.wz-step.active{color:#2563eb;font-weight:600}
.wz-step.done{color:#16a34a}
.wz-dot{width:22px;height:22px;display:grid;place-items:center;border-radius:50%;background:#eef2f7;color:#64748b;font-size:12px;font-weight:700}
.wz-step.active .wz-dot{background:#2563eb;color:#fff}
.wz-step.done .wz-dot{background:#dcfce7;color:#16a34a}
.wz-line{flex:1;min-width:28px;height:1px;background:#e2e8f0;margin:0 4px}

.wz-upload{display:flex;flex-direction:column;gap:14px}
.wz-card{display:flex;gap:12px;padding:14px 16px;border:1px solid #e5edf8;border-radius:14px;background:#f8fafc}
.wz-card-no{flex-shrink:0;width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:#2563eb;color:#fff;font-size:13px;font-weight:700}
.wz-card-body{flex:1;min-width:0}
.wz-card-body strong{display:block;margin-bottom:4px;color:#1e293b}
.wz-card-body p{margin:0 0 10px;color:#8190a8;font-size:12.5px;line-height:1.7}
.wz-drop :deep(.el-upload-dragger){padding:22px 12px}
.wz-drop-icon{font-size:38px;color:#2563eb;margin-bottom:4px}
.wz-drop-text{color:#475569;font-size:13px}
.wz-drop-text em{color:#2563eb;font-style:normal;font-weight:600}
.wz-drop-tip{margin-top:4px;color:#94a3b8;font-size:12px}
.wz-parsing{display:flex;align-items:center;gap:8px;margin-top:10px;color:#2563eb;font-size:13px}
.wz-tips{margin:0;padding-left:18px;color:#94a3b8;font-size:12.5px;line-height:1.9}

.wz-preview{display:flex;flex-direction:column;gap:12px}
.wz-file{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;background:#f8fafc;border:1px solid #e5edf8;color:#475569;font-size:13px}
.wz-file-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wz-summary{display:flex;align-items:center;gap:18px;padding:10px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5edf8;color:#475569;font-size:13.5px}
.wz-summary .ok b{color:#16a34a}
.wz-summary .err b{color:#dc2626}
.wz-summary .skip b{color:#64748b}
.wz-summary .pending b{color:#2563eb}

.wz-section{display:flex;flex-direction:column;gap:8px}
.wz-section-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.wz-section-head strong{color:#1e293b;font-size:13.5px}
.wz-hint{color:#94a3b8;font-size:12.5px;line-height:1.6}
.wz-table{width:100%}
.wz-table :deep(.wz-row-err){background:#fef2f2}
.wz-year{width:100%}
.wz-options{gap:10px;padding:12px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5edf8}
.wz-option-line{display:flex;align-items:center;gap:10px;color:#475569;font-size:13px;flex-wrap:wrap}
.wz-danger :deep(.el-checkbox__label){color:#b45309}
.wz-msg{color:#64748b}
.wz-msg-err{color:#dc2626}

.wz-result{display:flex;flex-direction:column;gap:14px}
.wz-result-head{display:flex;align-items:flex-start;gap:12px}
.wz-result-icon{font-size:34px;color:#16a34a}
.wz-result-head strong{display:block;color:#1e293b;font-size:15px}
.wz-result-head p{margin:4px 0 0;color:#64748b;font-size:13px;line-height:1.6}
.wz-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
.wz-stat{padding:12px 10px;border-radius:12px;background:#f8fafc;border:1px solid #e5edf8;text-align:center}
.wz-stat em{display:block;font-style:normal;font-size:20px;font-weight:700;color:#1e293b}
.wz-stat span{color:#94a3b8;font-size:12.5px}
.wz-stat.danger em{color:#dc2626}
.wz-chips{display:flex;flex-wrap:wrap;gap:8px}
.wz-chip{padding:4px 10px;border-radius:8px;background:#eff6ff;color:#1d4ed8;font-size:12.5px}
.wz-chip em{margin-left:6px;font-style:normal;color:#93b4f6}
.wz-downloads{display:flex;align-items:center;gap:12px;flex-wrap:wrap}

@media(max-width:820px){
  .wz-stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  .wz-summary{flex-wrap:wrap;gap:10px}
}
</style>
