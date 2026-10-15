<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { onMounted } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useGenerationStore } from '@/store/generation'

onMounted(() => {
  // 恢复刷新/关闭页面前未完成的生成任务（讲稿/配音断点续跑，按钮进度即时占位）。
  // 放在根组件：教师课程空间等独立布局不经过 MainLayout，只有根组件覆盖所有已登录页面。
  useGenerationStore().restoreTasks()
})
</script>
