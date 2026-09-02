<template>
  <section class="login-page">
    <div class="login-page__background" aria-hidden="true">
      <LoginBackground />
    </div>

    <div class="login-card">
      <div class="login-card__brand">
        <img src="/smart-course-logo.svg" alt="" aria-hidden="true" />
        <span>智课平台</span>
      </div>
      <h1>欢迎登录</h1>
      <p class="login-card__description">智能课程教学平台，登录后继续教学与学习。</p>

      <el-form :model="form" @submit.prevent="submit">
        <el-form-item class="auth-input">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            placeholder="请输入用户名"
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
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" class="auth-submit" :loading="loading" @click="submit">
            立即登录
          </el-button>
        </el-form-item>
      </el-form>

      <p class="login-card__tip">账号由管理员统一开通，如需账号或忘记密码请联系管理员。</p>
    </div>
  </section>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'
import LoginBackground from '@/components/LoginBackground.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }

  loading.value = true
  try {
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
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #fff;
  padding: 20px;
}

.login-page__background {
  position: absolute;
  inset: 0;
}

.login-card {
  position: relative;
  z-index: 1;
  width: min(100%, 460px);
  padding: 56px 54px 44px;
  border-radius: 32px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 24px 80px rgba(37, 99, 235, 0.18);
  backdrop-filter: blur(18px) saturate(1.1);
  text-align: center;
}

.login-card__brand {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 30px;
  color: #0f172a;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.5px;
}

.login-card__brand img {
  width: 46px;
  height: 46px;
  display: block;
}

.login-card h1 {
  margin: 0 0 10px;
  color: #1e293b;
  font-size: 34px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.6px;
}

.login-card__description {
  margin: 0 0 36px;
  color: #64748b;
  font-size: 15px;
}

.login-card__tip {
  margin: 22px 0 0;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.7;
}

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
  margin-top: 8px;
  border-radius: 12px;
  font-size: 17px;
  font-weight: 600;
}

@media screen and (max-width: 520px) {
  .login-card {
    padding: 40px 28px 32px;
    border-radius: 24px;
  }

  .login-card h1 {
    font-size: 28px;
  }
}
</style>
