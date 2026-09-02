<template>
  <div class="page-container admin-users">
    <header class="page-head">
      <div><div class="eyebrow">IDENTITY & ACCESS</div><h1>用户管理</h1><p>统一维护管理员、教师和学生账号。</p></div>
      <div class="head-actions">
        <el-button :icon="Upload" @click="openImport">批量导入学生</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建账号</el-button>
      </div>
    </header>

    <section class="toolbar">
      <el-input v-model="filters.search" class="search" clearable :prefix-icon="Search" placeholder="搜索用户名、姓名或手机号" @keyup.enter="applyFilters" @clear="applyFilters" />
      <el-select v-model="filters.role" clearable placeholder="全部角色" @change="applyFilters">
        <el-option label="管理员" value="admin" /><el-option label="教师" value="teacher" /><el-option label="学生" value="student" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="applyFilters">
        <el-option label="正常" value="active" /><el-option label="已停用" value="disabled" />
      </el-select>
      <el-button :icon="Search" @click="applyFilters">查询</el-button>
      <span class="result-count">共 {{ total }} 个账号</span>
    </section>

    <section class="table-card">
      <el-table v-loading="loading" :data="rows" row-key="id" class="user-table">
        <el-table-column label="用户" min-width="230">
          <template #default="{ row }">
            <div class="identity"><el-avatar :size="40" :src="row.avatar || ''" :icon="UserFilled" /><div><strong>{{ row.real_name || '未填写姓名' }}</strong><span>@{{ row.username }}</span></div></div>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" min-width="145"><template #default="{ row }">{{ row.phone || '—' }}</template></el-table-column>
        <el-table-column label="角色" width="110"><template #default="{ row }"><el-tag effect="light" :type="roleType(row.role)">{{ row.role_display }}</el-tag></template></el-table-column>
        <el-table-column label="创建时间" min-width="150"><template #default="{ row }">{{ formatDate(row.date_joined) }}</template></el-table-column>
        <el-table-column label="账号状态" width="125">
          <template #default="{ row }"><el-switch :model-value="row.is_active" :disabled="row.id === profile?.id" inline-prompt active-text="正常" inactive-text="停用" @change="(value) => changeActive(row, value)" /></template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link @click="openReset(row)">重置密码</el-button></template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" class="pager" background layout="prev, pager, next, total" :total="total" :page-size="pageSize" :current-page="page" @current-change="changePage" />
    </section>

    <el-dialog v-model="editorVisible" width="580px" align-center :title="editingId ? '编辑账号' : '新建账号'" @closed="editorRef?.clearValidate()">
      <el-form ref="editorRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <el-form-item label="用户名" prop="username"><el-input v-model.trim="form.username" placeholder="用于登录，不能与其他账号重复" /></el-form-item>
          <el-form-item label="手机号" prop="phone"><el-input v-model.trim="form.phone" placeholder="也可用于登录" maxlength="20" /></el-form-item>
          <el-form-item label="姓名" prop="real_name"><el-input v-model.trim="form.real_name" placeholder="请输入真实姓名" /></el-form-item>
          <el-form-item label="角色" prop="role"><el-select v-model="form.role" style="width:100%"><el-option label="学生" value="student" /><el-option label="教师" value="teacher" /><el-option label="管理员" value="admin" /></el-select></el-form-item>
          <el-form-item v-if="!editingId" label="初始密码" prop="password" class="full"><el-input v-model="form.password" type="password" show-password placeholder="8～12 位字符" maxlength="12" /></el-form-item>
          <el-form-item label="账号状态" class="full"><el-switch v-model="form.is_active" active-text="正常使用" inactive-text="停用账号" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="editorVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveUser">保存账号</el-button></template>
    </el-dialog>

    <el-dialog v-model="resetVisible" width="460px" align-center title="重置密码">
      <p class="dialog-tip">为 <b>{{ resetTarget?.real_name || resetTarget?.username }}</b> 设置新密码，保存后原密码立即失效，该用户下次登录会被提示修改密码。</p>
      <el-form label-position="top"><el-form-item label="新密码"><el-input v-model="resetPassword" type="password" show-password placeholder="8～12 位字符" maxlength="12" @keyup.enter="submitReset" /></el-form-item></el-form>
      <template #footer><el-button @click="resetVisible=false">取消</el-button><el-button type="primary" :loading="resetting" @click="submitReset">确认重置</el-button></template>
    </el-dialog>

    <el-dialog v-model="importVisible" width="900px" align-center title="批量导入学生" :close-on-click-modal="false">
      <div v-if="!importRows.length" class="import-upload">
        <div class="import-steps">
          <div class="import-step">
            <span class="step-no">1</span>
            <div>
              <strong>下载模板</strong>
              <p>按模板填写用户名与姓名，初始密码自动生成为「Lylg + 用户名后 6 位」，如用户名 2024012345 的初始密码为 Lylg012345。</p>
              <el-button size="small" :icon="Download" :loading="templateDownloading" @click="downloadTemplate">下载导入模板</el-button>
            </div>
          </div>
          <div class="import-step">
            <span class="step-no">2</span>
            <div>
              <strong>上传解析</strong>
              <p>上传填写好的 .xlsx 文件，系统会逐行解析并校验，确认无误后再正式导入，学生首次登录会被提示修改密码。</p>
            </div>
          </div>
        </div>
        <el-upload drag :show-file-list="false" accept=".xlsx" :http-request="handlePreview" class="import-drop">
          <el-icon class="upload-icon"><UploadFilled /></el-icon>
          <div class="el-upload__text">将文件拖到此处，或 <em>点击上传</em></div>
          <template #tip><div class="el-upload__tip">仅支持 .xlsx 文件，不超过 5MB，单次最多 500 行</div></template>
        </el-upload>
        <div v-if="parsing" class="import-parsing"><el-icon class="is-loading"><Loading /></el-icon> 正在解析文件…</div>
      </div>

      <template v-else>
        <div class="import-summary">
          <span>共解析 <b>{{ importRows.length }}</b> 行</span>
          <span class="ok">可导入 <b>{{ importValidCount }}</b> 行</span>
          <span v-if="importErrorCount" class="err">待修正 <b>{{ importErrorCount }}</b> 行</span>
          <el-button class="reupload" link type="primary" :icon="RefreshLeft" @click="resetImport">重新上传</el-button>
        </div>
        <el-table :data="importRows" max-height="420" class="import-table">
          <el-table-column type="index" label="#" width="52" />
          <el-table-column label="用户名" min-width="170">
            <template #default="{ row }"><el-input v-model.trim="row.username" size="small" @input="markEdited(row)" /></template>
          </el-table-column>
          <el-table-column label="姓名" min-width="130">
            <template #default="{ row }"><el-input v-model.trim="row.real_name" size="small" @input="markEdited(row)" /></template>
          </el-table-column>
          <el-table-column label="初始密码" width="130">
            <template #default="{ row }"><code class="pwd">{{ previewPassword(row.username) }}</code></template>
          </el-table-column>
          <el-table-column label="校验结果" min-width="180">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'ok'" type="success" effect="light">可导入</el-tag>
              <el-tooltip v-else-if="row.status === 'error'" :content="row.message" placement="top"><el-tag type="danger" effect="light">{{ row.message }}</el-tag></el-tooltip>
              <el-tag v-else type="warning" effect="light">已修改，待确认时重新校验</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" fixed="right">
            <template #default="{ $index }"><el-button link type="danger" @click="importRows.splice($index, 1)">删除</el-button></template>
          </el-table-column>
        </el-table>
        <p class="import-note">提示：确认导入时服务端会按最终内容重新校验，存在无效或冲突行将整批拒绝，不会产生一半成功一半失败的情况。</p>
      </template>

      <template #footer>
        <el-button @click="importVisible=false">取消</el-button>
        <el-button v-if="importRows.length" type="primary" :loading="importing" :disabled="!importRows.length" @click="submitImport">
          确认导入 {{ importRows.length }} 个学生
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { Plus, Search, UserFilled, Upload, UploadFilled, Download, Loading, RefreshLeft } from '@element-plus/icons-vue'
import {
  confirmAdminUserImport,
  createAdminUser,
  downloadAdminUserImportTemplate,
  listAdminUsers,
  previewAdminUserImport,
  resetAdminUserPassword,
  updateAdminUser,
} from '@/api/admin'
import { useUserStore } from '@/store/user'

const { profile } = storeToRefs(useUserStore())
const loading = ref(false), saving = ref(false), resetting = ref(false)
const rows = ref([]), total = ref(0), page = ref(1), pageSize = 10
const filters = reactive({ search: '', role: '', status: '' })
const editorVisible = ref(false), editorRef = ref(), editingId = ref(null)
const resetVisible = ref(false), resetTarget = ref(null), resetPassword = ref('')
const blankForm = () => ({ username: '', phone: '', real_name: '', role: 'student', is_active: true, password: '' })
const form = reactive(blankForm())
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  phone: [{ required: true, message: '请输入手机号', trigger: 'blur' }, { pattern: /^\+?\d{6,20}$/, message: '请输入正确的手机号', trigger: 'blur' }],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: [{ required: true, message: '请输入初始密码', trigger: 'blur' }, { min: 8, max: 12, message: '密码长度应为 8～12 位', trigger: 'blur' }],
}

function roleType(role) { return role === 'admin' ? 'danger' : role === 'teacher' ? 'warning' : 'primary' }
function formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-') : '—' }
function applyFilters() { page.value = 1; load() }
function changePage(value) { page.value = value; load() }
async function load() {
  loading.value = true
  try { const res = await listAdminUsers({ ...filters, page: page.value, page_size: pageSize }); rows.value = res.items; total.value = res.total } finally { loading.value = false }
}
function openCreate() { editingId.value = null; Object.assign(form, blankForm()); editorVisible.value = true }
function openEdit(row) { editingId.value = row.id; Object.assign(form, { username: row.username, phone: row.phone || '', real_name: row.real_name || '', role: row.role, is_active: row.is_active, password: '' }); editorVisible.value = true }
async function saveUser() {
  if (!(await editorRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const payload = { username: form.username, phone: form.phone, real_name: form.real_name, role: form.role, is_active: form.is_active }
    if (editingId.value) await updateAdminUser(editingId.value, payload)
    else await createAdminUser({ ...payload, password: form.password })
    ElMessage.success(editingId.value ? '账号已更新' : '账号已创建'); editorVisible.value = false; load()
  } finally { saving.value = false }
}
async function changeActive(row, value) {
  try { await updateAdminUser(row.id, { is_active: value }); row.is_active = value; ElMessage.success(value ? '账号已启用' : '账号已停用') } catch { row.is_active = !value }
}
function openReset(row) { resetTarget.value = row; resetPassword.value = ''; resetVisible.value = true }
async function submitReset() {
  if (resetPassword.value.length < 8 || resetPassword.value.length > 12) return ElMessage.warning('密码长度应为 8～12 位')
  resetting.value = true
  try { await resetAdminUserPassword(resetTarget.value.id, { password: resetPassword.value }); ElMessage.success('密码已重置'); resetVisible.value = false } finally { resetting.value = false }
}

// ---- 学生批量导入 ----
const importVisible = ref(false), parsing = ref(false), importing = ref(false), templateDownloading = ref(false)
const importRows = ref([])
const importValidCount = computed(() => importRows.value.filter((r) => r.status === 'ok').length)
const importErrorCount = computed(() => importRows.value.filter((r) => r.status === 'error').length)

function openImport() { resetImport(); importVisible.value = true }
function resetImport() { importRows.value = []; parsing.value = false; importing.value = false }

// 与后端 user_import.initial_password_for 同规则，仅用于预览展示
function previewPassword(username) {
  const name = String(username || '').trim()
  return name ? `Lylg${name.slice(-6)}` : '—'
}

async function downloadTemplate() {
  templateDownloading.value = true
  try {
    const blob = await downloadAdminUserImportTemplate()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '学生导入模板.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } finally { templateDownloading.value = false }
}

async function handlePreview({ file }) {
  parsing.value = true
  try {
    const res = await previewAdminUserImport(file)
    importRows.value = res.rows
    if (res.valid === res.total) ElMessage.success(`解析完成，${res.total} 行全部可导入`)
    else ElMessage.warning(`解析完成：${res.valid}/${res.total} 行可导入，请修正或删除问题行`)
  } catch { /* 文件级错误由拦截器统一提示 */ } finally { parsing.value = false }
}

// 预览中编辑过的行标记为“待确认”，最终校验以确认接口的服务端结果为准
function markEdited(row) { row.status = 'edited'; row.message = '' }

async function submitImport() {
  importing.value = true
  try {
    const payload = importRows.value.map((r) => ({ username: r.username, real_name: r.real_name }))
    const res = await confirmAdminUserImport(payload)
    ElMessage.success(`成功导入 ${res.created} 个学生账号`)
    importVisible.value = false
    resetImport()
    load()
  } catch (err) {
    // 服务端重验失败：把最新校验结果回填到表格中供继续修正
    const annotated = err?.data?.rows
    if (Array.isArray(annotated)) importRows.value = annotated
  } finally { importing.value = false }
}
onMounted(load)
</script>

<style scoped>
.admin-users{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}.head-actions{display:flex;gap:10px;flex-shrink:0}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}
.toolbar{min-height:70px;padding:13px 16px;border:1px solid #e5edf8;border-radius:18px 18px 0 0;background:rgba(255,255,255,.92);display:flex;align-items:center;gap:10px}.toolbar .search{width:min(380px,35vw)}.toolbar :deep(.el-select){width:130px}.result-count{margin-left:auto;color:#94a3b8;font-size:13px}
.table-card{overflow:hidden;border:1px solid #e5edf8;border-top:0;border-radius:0 0 20px 20px;background:#fff;box-shadow:0 18px 42px rgba(37,99,235,.07)}.user-table{min-height:480px}.identity{display:flex;align-items:center;gap:12px}.identity>div{min-width:0;display:grid;gap:3px}.identity strong,.identity span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.identity span{color:#94a3b8;font-size:12px}.pager{justify-content:flex-end;padding:16px 18px;border-top:1px solid #eef2f7}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.form-grid .full{grid-column:1/-1}.dialog-tip{margin-bottom:18px;color:#64748b;line-height:1.7}
.import-steps{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}.import-step{display:flex;gap:12px;padding:14px 16px;border:1px solid #e5edf8;border-radius:14px;background:#f8fafc}.import-step strong{display:block;margin-bottom:4px;color:#1e293b}.import-step p{margin:0 0 10px;color:#8190a8;font-size:12.5px;line-height:1.7}.step-no{flex-shrink:0;width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:#2563eb;color:#fff;font-size:13px;font-weight:700}
.import-drop :deep(.el-upload-dragger){padding:28px 12px}.upload-icon{font-size:40px;color:#2563eb;margin-bottom:6px}.import-parsing{display:flex;align-items:center;gap:8px;margin-top:10px;color:#2563eb;font-size:13px}
.import-summary{display:flex;align-items:center;gap:18px;margin-bottom:12px;padding:10px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5edf8;color:#475569;font-size:13.5px}.import-summary .ok b{color:#16a34a}.import-summary .err b{color:#dc2626}.import-summary .reupload{margin-left:auto}
.import-table .pwd{padding:2px 8px;border-radius:6px;background:#f1f5f9;color:#0f172a;font-size:12.5px}
.import-note{margin:12px 0 0;color:#94a3b8;font-size:12.5px;line-height:1.7}
@media(max-width:820px){.toolbar{align-items:stretch;flex-wrap:wrap}.toolbar .search{width:100%}.result-count{width:100%;margin-left:0}.page-head{align-items:flex-start}.head-actions{flex-wrap:wrap}.form-grid{grid-template-columns:1fr}.form-grid .full{grid-column:auto}.import-steps{grid-template-columns:1fr}}
</style>
