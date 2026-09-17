<template>
  <section class="split-auth" :style="themeStyle">
    <div class="split-auth__background" aria-hidden="true">
      <slot name="background" />
    </div>

    <div class="split-auth__container" :class="{ 'is-registering': modelValue }">
      <div class="split-auth__form-box split-auth__form-box--login">
        <div class="split-auth__form-content">
          <slot name="brand">
            <div
              v-if="showFormBrand && (logoSrc || brandName)"
              class="split-auth__brand"
              :class="{ 'is-heading': !loginTitle && !loginDescription }"
            >
              <img v-if="logoSrc" :src="logoSrc" alt="" aria-hidden="true" />
              <span>{{ brandName }}</span>
            </div>
          </slot>
          <h1 v-if="loginTitle">{{ loginTitle }}</h1>
          <p v-if="loginDescription" class="split-auth__description">{{ loginDescription }}</p>
          <slot name="login" :switch-mode="showRegister" />
        </div>
      </div>

      <div class="split-auth__form-box split-auth__form-box--register">
        <div class="split-auth__form-content">
          <slot name="brand">
            <div
              v-if="showFormBrand && (logoSrc || brandName)"
              class="split-auth__brand"
              :class="{ 'is-heading': !registerTitle && !registerDescription }"
            >
              <img v-if="logoSrc" :src="logoSrc" alt="" aria-hidden="true" />
              <span>{{ brandName }}</span>
            </div>
          </slot>
          <h1 v-if="registerTitle">{{ registerTitle }}</h1>
          <p v-if="registerDescription" class="split-auth__description">{{ registerDescription }}</p>
          <slot name="register" :switch-mode="showLogin" />
        </div>
      </div>

      <div class="split-auth__toggle-box">
        <div class="split-auth__toggle-panel split-auth__toggle-panel--left">
          <div class="split-auth__toggle-content">
            <template v-if="showToggleBrand">
              <div v-if="logoSrc || brandName" class="split-auth__toggle-brand">
                <img v-if="logoSrc" :src="logoSrc" alt="" aria-hidden="true" />
                <span>{{ brandName }}</span>
              </div>
              <span v-else class="split-auth__tag">{{ registerPrompt.tag }}</span>
            </template>
            <h2>{{ registerPrompt.title }}</h2>
            <p>{{ registerPrompt.description }}</p>
            <button type="button" class="split-auth__toggle-button" @click="showRegister">
              {{ registerPrompt.action }}
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4L10.59 5.41L16.17 11H4V13H16.17L10.59 18.59L12 20L20 12L12 4Z" fill="currentColor" />
              </svg>
            </button>
          </div>
        </div>

        <div class="split-auth__toggle-panel split-auth__toggle-panel--right">
          <div class="split-auth__toggle-content">
            <template v-if="showToggleBrand">
              <div v-if="logoSrc || brandName" class="split-auth__toggle-brand">
                <img v-if="logoSrc" :src="logoSrc" alt="" aria-hidden="true" />
                <span>{{ brandName }}</span>
              </div>
              <span v-else class="split-auth__tag">{{ loginPrompt.tag }}</span>
            </template>
            <h2>{{ loginPrompt.title }}</h2>
            <p>{{ loginPrompt.description }}</p>
            <button type="button" class="split-auth__toggle-button" @click="showLogin">
              {{ loginPrompt.action }}
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 4L10.59 5.41L16.17 11H4V13H16.17L10.59 18.59L12 20L20 12L12 4Z" fill="currentColor" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  logoSrc: { type: String, default: '' },
  brandName: { type: String, default: '' },
  showFormBrand: { type: Boolean, default: true },
  showToggleBrand: { type: Boolean, default: true },
  loginTitle: { type: String, default: '登录账号' },
  loginDescription: { type: String, default: '欢迎回来' },
  registerTitle: { type: String, default: '注册账号' },
  registerDescription: { type: String, default: '创建一个新账号' },
  registerPrompt: {
    type: Object,
    default: () => ({
      tag: '新用户',
      title: '加入我们',
      description: '创建一个账号，开启新的旅程。',
      action: '立即注册',
    }),
  },
  loginPrompt: {
    type: Object,
    default: () => ({
      tag: '老用户',
      title: '欢迎回来',
      description: '已有账号？登录后继续使用。',
      action: '立即登录',
    }),
  },
  primaryColor: { type: String, default: '#2563eb' },
  secondaryColor: { type: String, default: '#4f46e5' },
  panelWidth: { type: String, default: '1000px' },
  panelHeight: { type: String, default: '700px' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const themeStyle = computed(() => ({
  '--split-auth-primary': props.primaryColor,
  '--split-auth-secondary': props.secondaryColor,
  '--split-auth-width': props.panelWidth,
  '--split-auth-height': props.panelHeight,
}))

function setMode(isRegistering) {
  if (props.modelValue === isRegistering) return
  emit('update:modelValue', isRegistering)
  emit('change', isRegistering ? 'register' : 'login')
}

function showRegister() {
  setMode(true)
}

function showLogin() {
  setMode(false)
}

defineExpose({ showLogin, showRegister })
</script>

<style scoped>
@font-face {
  font-family: 'MiSans Auth';
  src: url('/fonts/MiSans-Auth.woff2') format('woff2');
  font-style: normal;
  font-weight: 400;
  font-display: swap;
}

.split-auth {
  position: relative;
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #fff;
  padding: 20px;
}

.split-auth__background {
  position: absolute;
  inset: 0;
}

.split-auth__container {
  position: relative;
  z-index: 1;
  width: min(100%, var(--split-auth-width));
  min-height: var(--split-auth-height);
  overflow: hidden;
  border-radius: 36px;
  background: #fff;
  box-shadow: 0 24px 80px color-mix(in srgb, var(--split-auth-primary) 18%, transparent);
}

.split-auth__form-box {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 1;
  width: 50%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px;
  text-align: center;
  background: #fff;
  transition: all 0.6s ease-in-out;
}

.split-auth__form-box--register {
  z-index: 0;
  padding-top: 42px;
  padding-bottom: 42px;
  opacity: 0;
  visibility: hidden;
}

.split-auth__form-box--register .split-auth__brand.is-heading {
  margin-bottom: 24px;
}

.split-auth__container.is-registering .split-auth__form-box--login {
  opacity: 0;
  visibility: hidden;
  transform: translateX(-100%);
}

.split-auth__container.is-registering .split-auth__form-box--register {
  z-index: 1;
  opacity: 1;
  visibility: visible;
  transform: translateX(-100%);
}

.split-auth__form-content {
  width: 100%;
  max-width: 380px;
}

.split-auth__brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.split-auth__brand img {
  width: 34px;
  height: 34px;
  display: block;
}

.split-auth__brand.is-heading {
  gap: 14px;
  margin-bottom: 38px;
  font-size: 28px;
  font-weight: 750;
  letter-spacing: -0.6px;
}

.split-auth__brand.is-heading img {
  width: 48px;
  height: 48px;
}

.split-auth__form-content > h1 {
  margin: 0 0 10px;
  color: #1e293b;
  font-family: 'MiSans Auth', 'MiSans', 'Noto Sans SC', sans-serif;
  font-size: 40px;
  font-weight: 400;
  line-height: 1.2;
  letter-spacing: -0.8px;
  text-rendering: geometricprecision;
}

.split-auth__description {
  margin: 0 0 40px;
  color: #64748b;
  font-size: 16px;
}

.split-auth__toggle-box {
  position: absolute;
  inset: 0;
}

.split-auth__toggle-box::before {
  content: '';
  position: absolute;
  left: 0;
  z-index: 2;
  width: 50%;
  height: 100%;
  border-radius: 0 100px 100px 0;
  background: linear-gradient(135deg, var(--split-auth-primary), var(--split-auth-secondary));
  transition: all 0.6s ease-in-out;
}

.split-auth__container.is-registering .split-auth__toggle-box::before {
  left: 50%;
  border-radius: 100px 0 0 100px;
}

.split-auth__toggle-panel {
  position: absolute;
  top: 0;
  z-index: 3;
  width: 50%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  text-align: center;
  transition: all 0.6s ease-in-out;
}

.split-auth__toggle-content {
  max-width: 380px;
  padding: 50px;
}

.split-auth__tag {
  display: inline-block;
  margin-bottom: 18px;
  padding: 6px 16px;
  border-radius: 20px;
  background: rgb(255 255 255 / 15%);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  backdrop-filter: blur(4px);
}

.split-auth__toggle-brand {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 22px;
  padding: 9px 16px;
  border: 1px solid rgb(255 255 255 / 70%);
  border-radius: 14px;
  background: rgb(255 255 255 / 94%);
  box-shadow: 0 10px 30px rgb(15 23 42 / 12%);
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
  backdrop-filter: blur(8px);
}

.split-auth__toggle-brand img {
  width: 30px;
  height: 30px;
  display: block;
}

.split-auth__toggle-panel h2 {
  margin: 0 0 16px;
  color: #fff;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: 1px;
  text-shadow: 0 4px 20px rgb(0 0 0 / 15%);
}

.split-auth__toggle-panel p {
  margin: 0 0 38px;
  color: rgb(255 255 255 / 95%);
  font-size: 17px;
  line-height: 1.8;
}

.split-auth__toggle-button {
  width: 190px;
  height: 54px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 2px solid rgb(255 255 255 / 90%);
  border-radius: 14px;
  background: transparent;
  color: #fff;
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s ease;
}

.split-auth__toggle-button:hover,
.split-auth__toggle-button:focus-visible {
  border-color: #fff;
  outline: none;
  background: #fff;
  color: var(--split-auth-primary);
  box-shadow: 0 8px 24px rgb(0 0 0 / 15%);
}

.split-auth__toggle-button svg {
  width: 18px;
  height: 18px;
  transition: transform 0.25s ease;
}

.split-auth__toggle-button:hover svg {
  transform: translateX(3px);
}

.split-auth__toggle-panel--left {
  left: 0;
}

.split-auth__toggle-panel--right {
  right: 0;
}

.split-auth__container:not(.is-registering) .split-auth__toggle-panel--right,
.split-auth__container.is-registering .split-auth__toggle-panel--left {
  opacity: 0;
  visibility: hidden;
}

.split-auth__container:not(.is-registering) .split-auth__toggle-panel--left,
.split-auth__container.is-registering .split-auth__toggle-panel--right {
  opacity: 1;
  visibility: visible;
}

@media (prefers-reduced-motion: reduce) {
  .split-auth__form-box,
  .split-auth__toggle-box::before,
  .split-auth__toggle-panel {
    transition-duration: 0.01ms;
  }
}

@media screen and (max-width: 768px) {
  .split-auth__container {
    max-width: 420px;
    min-height: max(720px, var(--split-auth-height));
  }

  .split-auth__form-box {
    left: 0;
    width: 100%;
    padding: 32px;
  }

  .split-auth__form-box--register {
    transform: translateY(100%);
  }

  .split-auth__container.is-registering .split-auth__form-box--login {
    transform: translateY(-100%);
  }

  .split-auth__container.is-registering .split-auth__form-box--register {
    transform: translateY(0);
  }

  .split-auth__toggle-box::before {
    top: 0;
    left: 0;
    width: 100%;
    height: 40%;
    border-radius: 0 0 50px 50px;
  }

  .split-auth__container.is-registering .split-auth__toggle-box::before {
    top: 60%;
    left: 0;
    border-radius: 50px 50px 0 0;
  }

  .split-auth__toggle-panel {
    width: 100%;
  }

  .split-auth__toggle-panel--left {
    top: 0;
  }

  .split-auth__toggle-panel--right {
    top: 60%;
  }

  .split-auth__form-content > h1 {
    font-size: 32px;
  }
}
</style>
