<template>
  <section class="page-container profile-page">
    <header class="profile-heading">
      <div>
        <span class="eyebrow">ACCOUNT SETTINGS</span>
        <h1>个人中心</h1>
        <p>管理你的头像、账号资料与登录密码。</p>
      </div>
      <div class="security-chip">
        <el-icon><Lock /></el-icon>
        <span>账号安全保护中</span>
      </div>
    </header>

    <div class="profile-layout">
      <aside class="identity-card">
        <div class="avatar-area">
          <button
            type="button"
            class="avatar-button"
            :disabled="avatarLoading"
            aria-label="更换头像"
            @click="openAvatarPicker"
          >
            <el-avatar
              :size="96"
              :src="profile?.avatar || ''"
              :icon="UserFilled"
              class="profile-avatar"
            />
            <span class="avatar-edit">
              <el-icon v-if="!avatarLoading"><Camera /></el-icon>
              <span v-else class="loading-dot"></span>
            </span>
          </button>
          <input
            ref="avatarInput"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            @change="handleAvatarChange"
          />
        </div>

        <h2>{{ displayName }}</h2>
        <p class="account-name">姓名 · {{ profile?.real_name || '未填写' }}</p>
        <span class="role-pill">{{ profile?.role_display || '平台用户' }}</span>

        <button type="button" class="upload-button" :disabled="avatarLoading" @click="openAvatarPicker">
          <el-icon><Upload /></el-icon>
          {{ avatarLoading ? '正在上传...' : '更换头像' }}
        </button>
        <p class="upload-tip">支持 JPG、PNG、WEBP，大小不超过 3MB</p>

        <div class="identity-meta">
          <div>
            <span>账号类型</span>
            <strong>{{ profile?.role_display || '-' }}</strong>
          </div>
          <div>
            <span>加入时间</span>
            <strong>{{ joinedDate }}</strong>
          </div>
        </div>
      </aside>

      <div class="settings-column">
        <article class="settings-card">
          <div class="card-heading">
            <span class="card-icon profile-icon"><EditPen /></span>
            <div>
              <h2>账号资料</h2>
              <p>用户名和手机号均可用于登录，且都不能与其他账号重复。</p>
            </div>
          </div>

          <el-form
            ref="profileFormRef"
            :model="profileForm"
            :rules="profileRules"
            label-position="top"
            class="settings-form"
          >
            <div class="form-grid">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="profileForm.username" maxlength="150" placeholder="请输入唯一用户名">
                  <template #prefix><el-icon><User /></el-icon></template>
                </el-input>
              </el-form-item>
              <el-form-item label="手机号" prop="phone">
                <el-input v-model="profileForm.phone" maxlength="20" placeholder="请输入手机号" />
              </el-form-item>
              <el-form-item label="姓名" prop="real_name">
                <el-input v-model="profileForm.real_name" maxlength="64" placeholder="请输入姓名" />
              </el-form-item>
            </div>
            <div class="form-actions">
              <el-button type="primary" :loading="profileLoading" @click="saveProfile">
                保存资料
              </el-button>
            </div>
          </el-form>
        </article>

        <article class="settings-card password-card">
          <div class="card-heading">
            <span class="card-icon password-icon"><Key /></span>
            <div>
              <h2>修改密码</h2>
              <p>定期更新密码可以提升账号安全性。</p>
            </div>
          </div>

          <el-form
            ref="passwordFormRef"
            :model="passwordForm"
            :rules="passwordRules"
            label-position="top"
            class="settings-form"
          >
            <div class="form-grid password-grid">
              <el-form-item label="当前密码" prop="current_password">
                <el-input
                  v-model="passwordForm.current_password"
                  type="password"
                  show-password
                  autocomplete="current-password"
                  placeholder="请输入当前密码"
                />
              </el-form-item>
              <el-form-item label="新密码" prop="new_password">
                <el-input
                  v-model="passwordForm.new_password"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  placeholder="至少 6 位字符"
                />
              </el-form-item>
              <el-form-item label="确认新密码" prop="confirm_password">
                <el-input
                  v-model="passwordForm.confirm_password"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  placeholder="请再次输入新密码"
                />
              </el-form-item>
            </div>
            <div class="form-actions password-actions">
              <span><el-icon><CircleCheck /></el-icon> 修改后当前登录状态保持不变</span>
              <el-button type="primary" :loading="passwordLoading" @click="savePassword">
                更新密码
              </el-button>
            </div>
          </el-form>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import {
  Camera,
  CircleCheck,
  EditPen,
  Key,
  Lock,
  Upload,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { changePassword } from '@/api/auth'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const { profile } = storeToRefs(userStore)
const profileFormRef = ref()
const passwordFormRef = ref()
const avatarInput = ref()
const profileLoading = ref(false)
const passwordLoading = ref(false)
const avatarLoading = ref(false)

const profileForm = reactive({
  username: '',
  real_name: '',
  phone: '',
})

const passwordForm = reactive({
  current_password: '',
  new_password: '',
  confirm_password: '',
})

const validateConfirmPassword = (_rule, value, callback) => {
  if (!value) callback(new Error('请再次输入新密码'))
  else if (value !== passwordForm.new_password) callback(new Error('两次输入的新密码不一致'))
  else callback()
}

const profileRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 150, message: '用户名长度为 2–150 个字符', trigger: 'blur' },
    { pattern: /^[\p{L}\p{N}_@.+-]+$/u, message: '仅支持文字、字母、数字及 @ . + - _', trigger: 'blur' },
  ],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^[+\d][\d -]{5,19}$/, message: '请输入正确的手机号', trigger: 'blur' },
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

const passwordRules = {
  current_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码至少需要 6 位字符', trigger: 'blur' },
  ],
  confirm_password: [{ validator: validateConfirmPassword, trigger: ['blur', 'change'] }],
}

watch(
  profile,
  (value) => {
    if (!value) return
    profileForm.username = value.username || ''
    profileForm.real_name = value.real_name || ''
    profileForm.phone = value.phone || ''
  },
  { immediate: true },
)

const displayName = computed(() => profile.value?.username || '智课用户')
const joinedDate = computed(() => {
  if (!profile.value?.date_joined) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(profile.value.date_joined))
})

function openAvatarPicker() {
  if (!avatarLoading.value) avatarInput.value?.click()
}

async function handleAvatarChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    ElMessage.warning('请选择 JPG、PNG 或 WEBP 图片')
    return
  }
  if (file.size > 3 * 1024 * 1024) {
    ElMessage.warning('头像大小不能超过 3MB')
    return
  }

  avatarLoading.value = true
  try {
    await userStore.updateAvatar(file)
    ElMessage.success('头像已更新')
  } finally {
    avatarLoading.value = false
  }
}

async function saveProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return
  profileLoading.value = true
  try {
    await userStore.updateProfile({ ...profileForm })
    ElMessage.success('个人资料已保存')
  } finally {
    profileLoading.value = false
  }
}

async function savePassword() {
  const valid = await passwordFormRef.value?.validate().catch(() => false)
  if (!valid) return
  passwordLoading.value = true
  try {
    await changePassword({ ...passwordForm })
    Object.assign(passwordForm, {
      current_password: '',
      new_password: '',
      confirm_password: '',
    })
    passwordFormRef.value?.clearValidate()
    ElMessage.success('密码修改成功')
  } finally {
    passwordLoading.value = false
  }
}
</script>

<style scoped>
.profile-page {
  color: #0f172a;
}

.profile-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
}

.eyebrow {
  display: block;
  margin-bottom: 5px;
  color: #2563eb;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.profile-heading h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.profile-heading p {
  margin: 5px 0 0;
  color: #64748b;
  font-size: 14px;
}

.security-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  background: rgba(239, 246, 255, 0.86);
  color: #2563eb;
  font-size: 13px;
  font-weight: 650;
}

.profile-layout {
  display: grid;
  grid-template-columns: 258px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.identity-card,
.settings-card {
  border: 1px solid rgba(219, 229, 242, 0.94);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 16px 42px rgba(37, 99, 235, 0.08);
}

.identity-card {
  position: sticky;
  top: 0;
  overflow: hidden;
  padding: 26px 22px 22px;
  border-radius: 22px;
  text-align: center;
}

.identity-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 96px;
  background:
    radial-gradient(circle at 24% 20%, rgba(255, 255, 255, 0.64), transparent 28%),
    linear-gradient(135deg, #dbeafe, #eff6ff 58%, #eef2ff);
}

.avatar-area {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: center;
  margin-bottom: 13px;
}

.avatar-button {
  position: relative;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
}

.avatar-button:disabled {
  cursor: wait;
}

.profile-avatar {
  border: 4px solid #fff;
  background: linear-gradient(135deg, #2563eb, #60a5fa);
  color: #fff;
  font-size: 38px;
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.22);
}

.avatar-edit {
  position: absolute;
  right: 1px;
  bottom: 4px;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 3px solid #fff;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.28);
}

.loading-dot {
  width: 13px;
  height: 13px;
  border: 2px solid rgba(255, 255, 255, 0.45);
  border-top-color: #fff;
  border-radius: 50%;
  animation: avatar-spin 0.8s linear infinite;
}

@keyframes avatar-spin {
  to { transform: rotate(360deg); }
}

.identity-card h2 {
  margin: 0;
  font-size: 19px;
}

.account-name {
  margin: 5px 0 10px;
  color: #94a3b8;
  font-size: 13px;
}

.role-pill {
  display: inline-flex;
  padding: 5px 12px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.upload-button {
  width: 100%;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 18px;
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  background: #f8fbff;
  color: #2563eb;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
}

.upload-button:hover:not(:disabled) {
  border-color: #60a5fa;
  background: #eff6ff;
  transform: translateY(-1px);
}

.upload-button:disabled {
  opacity: 0.65;
  cursor: wait;
}

.upload-tip {
  margin: 8px 0 18px;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.5;
}

.identity-meta {
  padding-top: 16px;
  border-top: 1px solid #eef2f7;
  text-align: left;
}

.identity-meta div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.identity-meta div + div {
  margin-top: 10px;
}

.identity-meta span {
  color: #94a3b8;
  font-size: 12px;
}

.identity-meta strong {
  color: #475569;
  font-size: 12px;
  font-weight: 650;
}

.settings-column {
  display: grid;
  gap: 16px;
}

.settings-card {
  padding: 22px 24px 23px;
  border-radius: 22px;
}

.card-heading {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 15px;
  border-bottom: 1px solid #eef2f7;
}

.card-heading h2 {
  margin: 0;
  font-size: 18px;
}

.card-heading p {
  margin: 5px 0 0;
  color: #94a3b8;
  font-size: 12px;
}

.card-icon {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 13px;
}

.card-icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.profile-icon {
  background: #eff6ff;
  color: #2563eb;
}

.password-icon {
  background: #f0fdf4;
  color: #16a34a;
}

.settings-form {
  padding-top: 17px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  column-gap: 18px;
}

.settings-form :deep(.el-form-item) {
  margin-bottom: 15px;
}

.settings-form :deep(.el-form-item__label) {
  padding-bottom: 8px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
}

.settings-form :deep(.el-input__wrapper) {
  min-height: 41px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px #e8edf4;
  transition: all 0.18s ease;
}

.settings-form :deep(.el-input__wrapper.is-focus) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
}

.form-actions :deep(.el-button) {
  min-width: 112px;
  height: 40px;
  border-radius: 11px;
  font-weight: 700;
}

.password-actions {
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.password-actions > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #94a3b8;
  font-size: 12px;
}

.password-actions > span .el-icon {
  color: #22c55e;
}

@media (max-width: 1380px) {
  .profile-layout {
    grid-template-columns: 238px minmax(0, 1fr);
  }

  .form-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-grid > :last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 1080px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }

  .identity-card {
    position: static;
  }
}

@media (max-width: 720px) {
  .profile-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .form-grid > :last-child {
    grid-column: auto;
  }

  .settings-card {
    padding: 22px 18px;
  }

  .password-actions {
    align-items: stretch;
    flex-direction: column;
  }
}

:global(html.dark) .profile-page {
  color: #f8fafc;
}

:global(html.dark) .identity-card,
:global(html.dark) .settings-card {
  border-color: rgba(71, 85, 105, 0.74);
  background: rgba(15, 23, 42, 0.92);
}

:global(html.dark) .identity-card::before {
  background: linear-gradient(135deg, rgba(30, 64, 175, 0.52), rgba(30, 41, 59, 0.64));
}

:global(html.dark) .profile-heading p,
:global(html.dark) .card-heading p,
:global(html.dark) .account-name {
  color: #94a3b8;
}

:global(html.dark) .card-heading,
:global(html.dark) .identity-meta {
  border-color: #334155;
}

:global(html.dark) .settings-form :deep(.el-input__wrapper) {
  background: #111c2f;
  box-shadow: inset 0 0 0 1px #334155;
}
</style>
