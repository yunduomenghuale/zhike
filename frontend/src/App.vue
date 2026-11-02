<template>
  <el-config-provider :locale="zhCn">
    <router-view />
    <AiTaskCenter />
  </el-config-provider>
</template>

<script setup>
import { onMounted } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import AiTaskCenter from '@/components/AiTaskCenter.vue'
import { useGenerationStore } from '@/store/generation'

onMounted(() => {
  // 队列化恢复：清旧前端续跑记录 + 从服务端 /ai-tasks/active/ 取回进行中任务。
  // 放在根组件：教师课程空间等独立布局不经过 MainLayout，只有根组件覆盖所有已登录页面。
  useGenerationStore().restoreTasks()
})
</script>
