<template>
  <SplitAuthPanel
    v-model="isRegister"
    logo-src="/smart-course-logo.svg"
    brand-name="智课平台"
    login-description="欢迎回到智能课程教学平台"
    register-description="创建账号开始使用平台"
    :register-prompt="registerPrompt"
    :login-prompt="loginPrompt"
    @change="resetForm"
  >
    <template #background>
      <LoginBackground />
    </template>

    <template #login>
      <el-form :model="form" @submit.prevent="submit">
        <el-form-item class="auth-input">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            placeholder="请输入用户名或手机号"
            size="large"
          />
        </el-form-item>

        <el-form-item class="auth-input">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            show-password
            placeholder="请输入密码"
            size="large"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" class="auth-submit" :loading="loading" @click="submit">
            立即登录
          </el-button>
        </el-form-item>
      </el-form>
    </template>

    <template #register>
      <el-form :model="form" @submit.prevent="submit">
        <el-form-item class="auth-input">
          <el-input v-model="form.username" placeholder="请输入用户名" size="large" />
        </el-form-item>

        <el-form-item class="auth-input">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" size="large" />
        </el-form-item>

        <el-form-item class="auth-input">
          <el-input v-model="form.real_name" placeholder="请输入姓名" size="large" />
        </el-form-item>

        <el-form-item class="auth-input">
          <el-input v-model="form.phone" placeholder="请输入手机号" maxlength="20" size="large" />
        </el-form-item>

        <el-form-item class="role-box">
          <div class="role-options">
            <button
              type="button"
              class="role-card"
              :class="{ active: form.role === 'teacher' }"
              :aria-pressed="form.role === 'teacher'"
              @click="form.role = 'teacher'"
            >
              <span class="role-icon teacher-icon">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 3L1 9L5 11.18V17.18L12 21L19 17.18V11.18L21 10.09V17H23V9L12 3ZM17.82 9L12 12L6.18 9L12 6L17.82 9ZM17 15.99L12 18.72L7 15.99V12.27L12 15L17 12.27V15.99Z" fill="currentColor" />
                </svg>
              </span>
              <span class="role-label">教师</span>
            </button>

            <button
              type="button"
              class="role-card"
              :class="{ active: form.role === 'student' }"
              :aria-pressed="form.role === 'student'"
              @click="form.role = 'student'"
            >
              <span class="role-icon student-icon">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 3L1 9L12 15L21 10.09V17H23V9L12 3ZM5 13.18V17.18L12 21L19 17.18V13.18L12 17L5 13.18Z" fill="currentColor" />
                  <path d="M12 3L1 9L12 15L23 9L12 3Z" fill="currentColor" opacity="0.3" />
                </svg>
              </span>
              <span class="role-label">学生</span>
            </button>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" class="auth-submit" :loading="loading" @click="submit">
            注册并登录
          </el-button>
        </el-form-item>
      </el-form>
    </template>
  </SplitAuthPanel>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import { register } from '@/api/auth'
import LoginBackground from '@/components/LoginBackground.vue'
import SplitAuthPanel from '@/components/SplitAuthPanel.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const registerPrompt = {
  tag: '新用户',
  title: '加入我们',
  description: '创建一个账号，开启属于你的智能教学与学习旅程。',
  action: '立即注册',
}

const loginPrompt = {
  tag: '老用户',
  title: '欢迎回来',
  description: '已有账号？登录后继续管理课程或投入学习。',
  action: '立即登录',
}

const isRegister = ref(false)
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
  real_name: '',
  phone: '',
  role: 'teacher',
})

function resetForm() {
  Object.assign(form, {
    username: '',
    password: '',
    real_name: '',
    phone: '',
    role: 'teacher',
  })
}

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写用户名或手机号和密码')
    return
  }
  if (isRegister.value && !form.real_name) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (isRegister.value && !/^\+?\d{6,20}$/.test(form.phone.replace(/[ -]/g, ''))) {
    ElMessage.warning('请填写正确的手机号')
    return
  }
  if (isRegister.value && form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }

  loading.value = true
  try {
    if (isRegister.value) await register(form)
    await userStore.login({ username: form.username, password: form.password })
    ElMessage.success('欢迎回来')
    router.push(route.query.redirect || '/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
:deep(.auth-input) {
  margin-bottom: 24px;
}

:deep(.auth-input .el-input__inner) {
  height: 50px;
  font-size: 16px;
}

:deep(.auth-input .el-input__wrapper) {
  border: 1px solid transparent;
  border-radius: 12px;
  background: #f1f5f9;
  box-shadow: none;
  transition: all 0.2s ease;
}

:deep(.auth-input .el-input__wrapper.is-focus) {
  border-color: #2563eb;
  background: #fff;
  box-shadow: 0 0 0 3px rgb(37 99 235 / 10%);
}

:deep(.auth-submit) {
  width: 100%;
  height: 52px;
  margin-top: 14px;
  border-radius: 12px;
  font-size: 17px;
  font-weight: 600;
}

:deep(.role-box .el-form-item__content) {
  line-height: 1;
}

.role-options {
  width: 100%;
  display: flex;
  gap: 16px;
}

.role-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px 12px;
  border: 2px solid #e2e8f0;
  border-radius: 16px;
  background: #f8fafc;
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition: all 0.25s ease;
}

.role-card:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
  transform: translateY(-2px);
}

.role-card:focus-visible {
  outline: 3px solid rgb(37 99 235 / 20%);
  outline-offset: 2px;
}

.role-card.active {
  border-color: #2563eb;
  background: #fff;
  box-shadow: 0 8px 24px rgb(37 99 235 / 15%);
}

.role-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
  border-radius: 12px;
  color: #64748b;
  transition: all 0.25s ease;
}

.role-icon svg {
  width: 28px;
  height: 28px;
}

.role-card.active .role-icon {
  color: #2563eb;
}

.teacher-icon {
  background: rgb(37 99 235 / 8%);
}

.student-icon {
  background: rgb(14 165 233 / 8%);
}

.role-card.active .teacher-icon {
  background: rgb(37 99 235 / 14%);
}

.role-card.active .student-icon {
  background: rgb(14 165 233 / 14%);
}

.role-label {
  margin-bottom: 4px;
  color: #475569;
  font-size: 16px;
  font-weight: 600;
}

.role-card.active .role-label {
  color: #1e293b;
}
</style>
