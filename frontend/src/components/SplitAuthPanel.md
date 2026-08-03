# 双幕认证组件（SplitAuthPanel）

`SplitAuthPanel.vue` 是一个与接口、路由和 UI 组件库无关的 Vue 3 登录/注册展示组件。它负责品牌信息、双面滑动切换、响应式布局和主题色，实际表单通过插槽传入。

## 基本使用

```vue
<template>
  <SplitAuthPanel
    v-model="registering"
    logo-src="/logo.svg"
    brand-name="我的产品"
    login-description="欢迎回来"
    register-description="创建你的账号"
    primary-color="#2563eb"
    secondary-color="#4f46e5"
    @change="handleModeChange"
  >
    <template #background>
      <MyBackground />
    </template>

    <template #login>
      <form @submit.prevent="login">登录表单</form>
    </template>

    <template #register>
      <form @submit.prevent="register">注册表单</form>
    </template>
  </SplitAuthPanel>
</template>

<script setup>
import { ref } from 'vue'
import SplitAuthPanel from './SplitAuthPanel.vue'

const registering = ref(false)

function handleModeChange(mode) {
  console.log(mode) // "login" 或 "register"
}
</script>
```

## 主要属性

| 属性 | 说明 | 默认值 |
| --- | --- | --- |
| `v-model` | `true` 显示注册，`false` 显示登录 | `false` |
| `logo-src` / `brand-name` | 品牌图标与名称 | 空 |
| `login-title` / `register-title` | 两侧表单标题 | 登录账号 / 注册账号 |
| `login-description` / `register-description` | 两侧表单说明 | 内置文案 |
| `register-prompt` / `login-prompt` | 彩色切换面板文案对象 | 内置文案 |
| `primary-color` / `secondary-color` | 渐变主题色 | 蓝色 / 靛色 |
| `panel-width` / `panel-height` | 面板尺寸（CSS 长度） | 1000px / 700px |

## 插槽与事件

- `login`：登录表单。
- `register`：注册表单。
- `background`：背景动画或静态装饰。
- `brand`：完全替换默认品牌区域；该插槽会分别渲染在两个表单上。
- `change`：切换时返回 `login` 或 `register`。

组件还通过模板引用暴露了 `showLogin()` 和 `showRegister()` 方法，并自动适配窄屏与“减少动态效果”系统设置。
