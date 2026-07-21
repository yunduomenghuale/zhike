<template>
  <CourseWorkspaceShell
    :course-name="course?.name"
    :course-sub="course?.term || '未设置学期'"
    :tabs="tabs"
    back-to="/teacher/courses"
    back-text="返回个人空间"
    home-tab="course-chapters"
  />
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  Document,
  EditPen,
  Notebook,
  Reading,
  TrendCharts,
} from '@element-plus/icons-vue'
import CourseWorkspaceShell from '@/components/CourseWorkspaceShell.vue'
import { listCourses } from '@/api/course'

const route = useRoute()
const course = ref(null)

const tabs = [
  { name: 'course-chapters', label: '章节与课件', icon: Reading },
  { name: 'course-knowledge', label: '知识库', icon: Collection },
  { name: 'course-qa', label: 'AI 问答', icon: ChatDotRound },
  { name: 'course-questions', label: '题库', icon: EditPen },
  { name: 'course-homework', label: '作业', icon: Notebook },
  { name: 'course-exams', label: '考试', icon: Document },
  { name: 'course-analytics', label: '学习统计', icon: TrendCharts },
]

const courseId = computed(() => Number(route.params.id) || null)

async function loadCourse() {
  if (!courseId.value) return
  const data = await listCourses()
  const list = data.results ?? data
  course.value = list.find((item) => Number(item.id) === courseId.value) || null
}

onMounted(loadCourse)
watch(courseId, loadCourse)
</script>
