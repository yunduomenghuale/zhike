<template>
  <div class="page-container admin-users">
    <header class="page-head">
      <div><div class="eyebrow">IDENTITY & ACCESS</div><h1>用户管理</h1><p>统一维护管理员、教师和学生账号。</p></div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建账号</el-button>
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
          <el-form-item v-if="!editingId" label="初始密码" prop="password" class="full"><el-input v-model="form.password" type="password" show-password placeholder="至少 6 位字符" /></el-form-item>
          <el-form-item label="账号状态" class="full"><el-switch v-model="form.is_active" active-text="正常使用" inactive-text="停用账号" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="editorVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveUser">保存账号</el-button></template>
    </el-dialog>

    <el-dialog v-model="resetVisible" width="460px" align-center title="重置密码">
      <p class="dialog-tip">为 <b>{{ resetTarget?.real_name || resetTarget?.username }}</b> 设置新密码，保存后原密码立即失效。</p>
      <el-form label-position="top"><el-form-item label="新密码"><el-input v-model="resetPassword" type="password" show-password placeholder="至少 6 位字符" @keyup.enter="submitReset" /></el-form-item></el-form>
      <template #footer><el-button @click="resetVisible=false">取消</el-button><el-button type="primary" :loading="resetting" @click="submitReset">确认重置</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { Plus, Search, UserFilled } from '@element-plus/icons-vue'
import { createAdminUser, listAdminUsers, resetAdminUserPassword, updateAdminUser } from '@/api/admin'
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
  password: [{ required: true, message: '请输入初始密码', trigger: 'blur' }, { min: 6, message: '密码至少 6 位', trigger: 'blur' }],
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
  if (resetPassword.value.length < 6) return ElMessage.warning('密码至少 6 位')
  resetting.value = true
  try { await resetAdminUserPassword(resetTarget.value.id, { password: resetPassword.value }); ElMessage.success('密码已重置'); resetVisible.value = false } finally { resetting.value = false }
}
onMounted(load)
</script>

<style scoped>
.admin-users{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}
.toolbar{min-height:70px;padding:13px 16px;border:1px solid #e5edf8;border-radius:18px 18px 0 0;background:rgba(255,255,255,.92);display:flex;align-items:center;gap:10px}.toolbar .search{width:min(380px,35vw)}.toolbar :deep(.el-select){width:130px}.result-count{margin-left:auto;color:#94a3b8;font-size:13px}
.table-card{overflow:hidden;border:1px solid #e5edf8;border-top:0;border-radius:0 0 20px 20px;background:#fff;box-shadow:0 18px 42px rgba(37,99,235,.07)}.user-table{min-height:480px}.identity{display:flex;align-items:center;gap:12px}.identity>div{min-width:0;display:grid;gap:3px}.identity strong,.identity span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.identity span{color:#94a3b8;font-size:12px}.pager{justify-content:flex-end;padding:16px 18px;border-top:1px solid #eef2f7}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.form-grid .full{grid-column:1/-1}.dialog-tip{margin-bottom:18px;color:#64748b;line-height:1.7}
@media(max-width:820px){.toolbar{align-items:stretch;flex-wrap:wrap}.toolbar .search{width:100%}.result-count{width:100%;margin-left:0}.page-head{align-items:flex-start}.form-grid{grid-template-columns:1fr}.form-grid .full{grid-column:auto}}
</style>
