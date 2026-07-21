<template>
  <div class="login-page">
    <LoginBackground />
    <div class="login-container" :class="{ active: isRegister }">
      <!-- 左侧：登录表单 -->
      <div class="form-box login">
        <el-form :model="form" @submit.prevent>
          <div class="login-brand">
            <img src="/smart-course-logo.svg" alt="" aria-hidden="true" />
            <span>智课平台</span>
          </div>
          <h2>登录账号</h2>
          <p class="form-desc">欢迎回到智能课程教学平台</p>

          <el-form-item class="input-box">
            <el-input
              v-model="form.username"
              :prefix-icon="User"
              placeholder="请输入用户名或手机号"
              size="large"
            />
          </el-form-item>

          <el-form-item class="input-box">
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
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="loading"
              @click="submit"
            >
              立即登录
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 右侧：注册表单 -->
      <div class="form-box register">
        <el-form :model="form" @submit.prevent>
          <div class="login-brand">
            <img src="/smart-course-logo.svg" alt="" aria-hidden="true" />
            <span>智课平台</span>
          </div>
          <h2>注册账号</h2>
          <p class="form-desc">创建账号开始使用平台</p>

          <el-form-item class="input-box">
            <el-input v-model="form.username" placeholder="请输入用户名" size="large" />
          </el-form-item>

          <el-form-item class="input-box">
            <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" size="large" />
          </el-form-item>

          <el-form-item class="input-box">
            <el-input v-model="form.real_name" placeholder="请输入姓名" size="large" />
          </el-form-item>

          <el-form-item class="input-box">
            <el-input v-model="form.phone" placeholder="请输入手机号" maxlength="20" size="large" />
          </el-form-item>

          <el-form-item class="input-box role-box">
            <div class="role-options">
              <div
                class="role-card"
                :class="{ active: form.role === 'teacher' }"
                @click="form.role = 'teacher'"
              >
                <div class="role-icon teacher-icon">
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 3L1 9L5 11.18V17.18L12 21L19 17.18V11.18L21 10.09V17H23V9L12 3ZM17.82 9L12 12L6.18 9L12 6L17.82 9ZM17 15.99L12 18.72L7 15.99V12.27L12 15L17 12.27V15.99Z" fill="currentColor"/>
                  </svg>
                </div>
                <span class="role-label">教师</span>
              </div>
              <div
                class="role-card"
                :class="{ active: form.role === 'student' }"
                @click="form.role = 'student'"
              >
                <div class="role-icon student-icon">
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 3L1 9L12 15L21 10.09V17H23V9L12 3ZM5 13.18V17.18L12 21L19 17.18V13.18L12 17L5 13.18Z" fill="currentColor"/>
                    <path d="M12 3L1 9L12 15L23 9L12 3Z" fill="currentColor" opacity="0.3"/>
                  </svg>
                </div>
                <span class="role-label">学生</span>
              </div>
            </div>
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="loading"
              @click="submit"
            >
              注册并登录
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 切换面板 -->
      <div class="toggle-box">
        <div class="toggle-panel toggle-left">
          <div class="toggle-content">
            <span class="toggle-tag">新用户</span>
            <h2>加入我们</h2>
            <p>创建一个账号，开启属于你的智能教学与学习旅程。</p>
            <button class="toggle-btn" @click="toggleForm">
              立即注册
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 4L10.59 5.41L16.17 11H4V13H16.17L10.59 18.59L12 20L20 12L12 4Z" fill="currentColor"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="toggle-panel toggle-right">
          <div class="toggle-content">
            <span class="toggle-tag">老用户</span>
            <h2>欢迎回来</h2>
            <p>已有账号？登录后继续管理课程或投入学习。</p>
            <button class="toggle-btn" @click="toggleForm">
              立即登录
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 4L10.59 5.41L16.17 11H4V13H16.17L10.59 18.59L12 20L20 12L12 4Z" fill="currentColor"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import { register } from '@/api/auth'
import LoginBackground from '@/components/LoginBackground.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const isRegister = ref(false)
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
  real_name: '',
  phone: '',
  role: 'teacher',
})

function toggleForm() {
  isRegister.value = !isRegister.value
  form.username = ''
  form.password = ''
  form.real_name = ''
  form.phone = ''
  form.role = 'teacher'
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
    if (isRegister.value) {
      await register(form)
    }
    await userStore.login({ username: form.username, password: form.password })
    ElMessage.success('欢迎回来')
    router.push(route.query.redirect || '/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ffffff;
  padding: 20px;
}

.login-container {
  position: relative;
  z-index: 1;
  width: 1000px;
  min-height: 700px;
  background: #fff;
  border-radius: 36px;
  box-shadow: 0 24px 80px rgba(37, 99, 235, 0.18);
  overflow: hidden;
}

.form-box {
  position: absolute;
  top: 0;
  right: 0;
  width: 50%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px;
  text-align: center;
  background: #fff;
  z-index: 1;
  transition: all 0.6s ease-in-out;
}

.form-box.register {
  opacity: 0;
  visibility: hidden;
  z-index: 0;
}

.login-container.active .form-box.login {
  transform: translateX(-100%);
  opacity: 0;
  visibility: hidden;
}

.login-container.active .form-box.register {
  transform: translateX(-100%);
  opacity: 1;
  visibility: visible;
  z-index: 1;
}

form {
  width: 100%;
  max-width: 380px;
}

.login-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.login-brand img {
  width: 34px;
  height: 34px;
  display: block;
}

h2 {
  font-size: 38px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 10px;
}

.form-desc {
  font-size: 16px;
  color: #64748b;
  margin-bottom: 40px;
}

.input-box {
  margin-bottom: 24px;
}

.input-box :deep(.el-input__inner) {
  height: 50px;
  font-size: 16px;
}

.input-box :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: #f1f5f9;
  box-shadow: none;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.input-box :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.role-box :deep(.el-form-item__content) {
  line-height: 1;
}

.role-options {
  display: flex;
  gap: 16px;
  width: 100%;
}

.role-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px 12px;
  border-radius: 16px;
  border: 2px solid #e2e8f0;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.25s ease;
}

.role-card:hover {
  border-color: #93c5fd;
  background: #f0f9ff;
  transform: translateY(-2px);
}

.role-card.active {
  border-color: #2563eb;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.15);
}

.role-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  margin-bottom: 10px;
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
  background: rgba(37, 99, 235, 0.08);
}

.student-icon {
  background: rgba(14, 165, 233, 0.08);
}

.role-card.active .teacher-icon {
  background: rgba(37, 99, 235, 0.14);
}

.role-card.active .student-icon {
  background: rgba(14, 165, 233, 0.14);
}

.role-label {
  font-size: 16px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 4px;
}

.role-card.active .role-label {
  color: #1e293b;
}


.submit-btn {
  width: 100%;
  height: 52px;
  border-radius: 12px;
  font-size: 17px;
  font-weight: 600;
  margin-top: 14px;
}

/* 切换面板 */
.toggle-box {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.toggle-box::before {
  content: '';
  position: absolute;
  left: 0;
  width: 50%;
  height: 100%;
  background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
  border-radius: 0 100px 100px 0;
  z-index: 2;
  transition: all 0.6s ease-in-out;
}

.login-container.active .toggle-box::before {
  left: 50%;
  border-radius: 100px 0 0 100px;
}

.toggle-panel {
  position: absolute;
  top: 0;
  width: 50%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  text-align: center;
  z-index: 3;
  transition: all 0.6s ease-in-out;
}

.toggle-content {
  padding: 50px;
  max-width: 380px;
}

.toggle-tag {
  display: inline-block;
  padding: 6px 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 18px;
  backdrop-filter: blur(4px);
}

.toggle-panel h2 {
  color: #fff;
  font-size: 40px;
  font-weight: 700;
  margin-bottom: 16px;
  letter-spacing: 1px;
  text-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.toggle-panel p {
  font-size: 17px;
  line-height: 1.8;
  margin-bottom: 38px;
  opacity: 0.95;
  color: rgba(255, 255, 255, 0.95);
}

.toggle-btn {
  width: 190px;
  height: 54px;
  background: transparent;
  border: 2px solid rgba(255, 255, 255, 0.9);
  border-radius: 14px;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.toggle-btn:hover {
  background: #fff;
  color: #2563eb;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.btn-icon {
  width: 18px;
  height: 18px;
  transition: transform 0.25s ease;
}

.toggle-btn:hover .btn-icon {
  transform: translateX(3px);
}

.toggle-left {
  left: 0;
}

.toggle-right {
  right: 0;
}

.login-container:not(.active) .toggle-left {
  opacity: 1;
  visibility: visible;
}

.login-container:not(.active) .toggle-right {
  opacity: 0;
  visibility: hidden;
}

.login-container.active .toggle-left {
  opacity: 0;
  visibility: hidden;
}

.login-container.active .toggle-right {
  opacity: 1;
  visibility: visible;
}

/* 小屏适配 */
@media screen and (max-width: 768px) {
  .login-container {
    width: 100%;
    max-width: 420px;
    min-height: 720px;
  }

  .form-box {
    padding: 32px;
  }

  .form-box,
  .toggle-panel {
    width: 100%;
  }

  .form-box.login {
    top: 0;
    left: 0;
  }

  .form-box.register {
    top: 0;
    left: 0;
    transform: translateY(100%);
  }

  .login-container.active .form-box.login {
    transform: translateY(-100%);
  }

  .login-container.active .form-box.register {
    transform: translateY(0);
  }

  .toggle-box::before {
    top: 0;
    left: 0;
    width: 100%;
    height: 40%;
    border-radius: 0 0 50px 50px;
  }

  .login-container.active .toggle-box::before {
    top: 60%;
    left: 0;
    border-radius: 50px 50px 0 0;
  }

  .toggle-left {
    top: 0;
    left: 0;
  }

  .toggle-right {
    top: 60%;
    right: 0;
  }
}
</style>
