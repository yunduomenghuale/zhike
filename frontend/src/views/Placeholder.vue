<template>
  <div class="page-container placeholder-page">
    <el-card shadow="never" class="placeholder-card">
      <el-empty :image-size="160">
        <template #image>
          <div class="placeholder-illustration">
            <el-icon :size="80" color="#cbd5e1"><Box /></el-icon>
          </div>
        </template>
        <template #description>
          <div class="placeholder-title">【{{ route.meta.title }}】模块正在建设中</div>
          <div class="placeholder-desc">后端接口已就绪，可在此页对接对应 API。</div>
        </template>
        <el-button type="primary" :icon="ArrowLeft" @click="$router.push('/dashboard')">
          返回工作台
        </el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { Box, ArrowLeft } from '@element-plus/icons-vue'

const route = useRoute()
</script>

<style scoped>
.placeholder-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 120px);
}

.placeholder-card {
  width: 100%;
  max-width: 560px;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  padding: 40px 20px;
}

.placeholder-illustration {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 20px;
}

.placeholder-title {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.placeholder-desc {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 24px;
}
</style>
