<template>
  <el-dialog
    v-model="visible"
    width="520px"
    align-center
    title="首次登录安全设置"
    :close-on-click-modal="false"
  >
    <p class="first-login-tip">
      你的账号由管理员开通，当前使用的是初始密码。建议立即修改密码并补充手机号，保障账号安全。
      也可以点击「以后再说」跳过，下次登录时会再次提示。
    </p>
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="当前密码（初始密码）" prop="current_password">
        <el-input v-model="form.current_password" type="password" show-password placeholder="请输入当前使用的密码" />
      </el-form-item>
      <div class="form-grid">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="form.new_password" type="password" show-password placeholder="8～12 位，不能全为数字" maxlength="12" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="form.confirm_password" type="password" show-password placeholder="请再次输入新密码" maxlength="12" />
        </el-form-item>
      </div>
      <el-form-item label="手机号（选填，用于完善资料）" prop="phone">
        <el-input v-model.trim="form.phone" placeholder="请输入手机号" maxlength="20" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">以后再说</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">完成设置</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/auth'
import { useUserStore } from '@/store/user'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])
const userStore = useUserStore()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const formRef = ref()
const submitting = ref(false)
const form = reactive({ current_password: '', new_password: '', confirm_password: '', phone: '' })

const rules = {
  current_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 12, message: '密码长度应为 8～12 位', trigger: 'blur' },
    { pattern: /^(?!\d+$).+$/, message: '密码不能全为数字', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_, value, callback) => {
        callback(value === form.new_password ? undefined : new Error('两次输入的新密码不一致'))
      },
      trigger: 'blur',
    },
  ],
  phone: [{ pattern: /^\+?\d{6,20}$/, message: '请输入正确的手机号', trigger: 'blur' }],
}

watch(visible, (value) => {
  if (value) {
    Object.assign(form, { current_password: '', new_password: '', confirm_password: '', phone: '' })
    formRef.value?.clearValidate()
  }
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  try {
    await changePassword({
      current_password: form.current_password,
      new_password: form.new_password,
      confirm_password: form.confirm_password,
    })
    if (form.phone) {
      await userStore.updateProfile({ phone: form.phone })
    }
    await userStore.fetchProfile() // 刷新 profile，清除 must_change_password 标志
    ElMessage.success('密码已更新，下次登录请使用新密码')
    visible.value = false
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.first-login-tip {
  margin: 0 0 18px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #eff6ff;
  border: 1px solid rgba(37, 99, 235, 0.16);
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}

@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
