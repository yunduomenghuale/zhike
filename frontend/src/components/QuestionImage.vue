<template>
  <!-- 题目配图（题干一张图）：所有题干渲染处共用，点击放大预览 -->
  <img
    v-if="src"
    class="question-image"
    :src="src"
    alt="题图"
    @click="previewVisible = true"
  />
  <el-dialog
    v-model="previewVisible"
    append-to-body
    :show-close="true"
    class="question-image-preview-dialog"
    width="auto"
  >
    <img v-if="src" :src="src" alt="题图（放大预览）" style="max-width: 90vw; max-height: 82vh; display: block" />
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'

// 兼容两种数据形态：序列器输出的 image_url（/media/...）与草稿态的 image（相对路径）
const props = defineProps({
  question: { type: Object, default: () => ({}) },
})

const previewVisible = ref(false)
const src = computed(() => {
  const q = props.question || {}
  if (q.image_url) return q.image_url
  if (q.image) return `/media/${q.image}`
  return ''
})
</script>

<style scoped>
.question-image {
  display: block;
  max-width: 320px;
  max-height: 200px;
  margin: 6px 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  object-fit: contain;
  cursor: zoom-in;
}
</style>
