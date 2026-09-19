<template>
  <web-view v-if="url" :src="url" />
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

const url = ref('')

onLoad((q) => {
  if (q.url) url.value = decodeURIComponent(q.url)
  if (q.title) uni.setNavigationBarTitle({ title: decodeURIComponent(q.title) })
})
</script>
