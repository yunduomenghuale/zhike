<template>
  <div class="pdf-scroll-preview">
    <div v-if="loading" class="pdf-preview-state">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在加载预览…</span>
    </div>
    <div v-else-if="errorMessage" class="pdf-preview-state is-error">
      <span>{{ errorMessage }}</span>
    </div>
    <div v-else class="pdf-preview-scroll" :style="{ maxHeight }">
      <div v-for="(page, index) in pages" :key="page" class="pdf-page">
        <img :src="page" loading="lazy" class="pdf-page-img" :alt="`第 ${index + 1} 页`" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { previewHomeworkAttachment } from '@/api/homework'

const props = defineProps({
  // 作业 ID（教师端编辑用作业 id；学生端用当前作业 id）
  homeworkId: { type: [Number, String], required: true },
  // PDF 附件的 media URL
  url: { type: String, required: true },
  // 预览区最大高度（超出上下滚动）
  maxHeight: { type: String, default: '560px' },
})

const pages = ref([])
const loading = ref(false)
const errorMessage = ref('')

async function load() {
  if (!props.url) return
  loading.value = true
  errorMessage.value = ''
  pages.value = []
  try {
    const data = await previewHomeworkAttachment(props.homeworkId, props.url)
    const list = data?.pages || []
    if (!list.length) {
      errorMessage.value = '预览失败，请下载后查看'
      return
    }
    pages.value = list
  } catch (error) {
    errorMessage.value = error?.message || '在线预览加载失败，请下载后查看'
  } finally {
    loading.value = false
  }
}

watch(() => [props.homeworkId, props.url], load, { immediate: true })
</script>

<style scoped>
.pdf-scroll-preview {
  width: 100%;
}

.pdf-preview-scroll {
  overflow-y: auto;
  overflow-x: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f1f5f9;
  scrollbar-width: thin;
}

.pdf-page {
  display: flex;
  justify-content: center;
  padding: 10px 0;
  background: #f1f5f9;
}

.pdf-page + .pdf-page {
  border-top: 1px solid #e2e8f0;
}

.pdf-page-img {
  display: block;
  width: 100%;
  max-width: 720px;
  height: auto;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08);
}

.pdf-preview-state {
  min-height: 180px;
  border: 1px dashed #bfdbfe;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #64748b;
  background: #f8fbff;
  font-size: 13px;
}

.pdf-preview-state .el-icon {
  color: #2563eb;
  font-size: 20px;
}

.pdf-preview-state.is-error {
  border-color: #fed7aa;
  color: #9a3412;
  background: #fff7ed;
}
</style>
