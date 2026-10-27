<template>
  <!--
    题目配图（题干一张图）：所有题干渲染处共用。
    用 EP 自带预览器：图片在遮罩层居中，工具栏支持放大/缩小/旋转/复位；
    teleport 到 body，z-index 提到 3000 保证盖在抽屉/弹层之上。
  -->
  <el-image
    v-if="src"
    class="question-image"
    :src="src"
    :preview-src-list="[src]"
    :preview-teleported="true"
    :z-index="3000"
    fit="contain"
    alt="题图"
  />
</template>

<script setup>
import { computed } from 'vue'

// 兼容两种数据形态：序列器输出的 image_url（/media/...）与草稿态的 image（相对路径）
const props = defineProps({
  question: { type: Object, default: () => ({}) },
})

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
  width: fit-content;
  max-width: 320px;
  margin: 6px 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
.question-image :deep(img) {
  display: block;
  max-width: 320px;
  max-height: 200px;
  cursor: zoom-in;
}
</style>
