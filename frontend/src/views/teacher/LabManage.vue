<template>
  <LabLibrary :fixed-course-id="fixedCourseId" />
</template>

<script setup>
// Stage 6 教师反馈第 1 条：课程内的「虚拟实验」与顶级「实验管理」合并为同一页面。
// 课程工作台内嵌 LabLibrary，实验固定归属当前课程，创建 / 排课 / 发布全在此完成。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import LabLibrary from './LabLibrary.vue'

const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
</script>
