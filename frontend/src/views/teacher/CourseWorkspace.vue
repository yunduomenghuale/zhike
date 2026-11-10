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
  Pointer,
  Reading,
  TrendCharts,
  VideoCamera,
} from '@element-plus/icons-vue'
import CourseWorkspaceShell from '@/components/CourseWorkspaceShell.vue'
import { listCourses, visitCourse } from '@/api/course'

const route = useRoute()
const course = ref(null)

const tabs = [
  { name: 'course-chapters', label: '章节与课件', icon: Reading },
  { name: 'course-knowledge', label: '知识库', icon: Collection },
  { name: 'course-qa', label: 'AI 问答', icon: ChatDotRound },
  { name: 'course-questions', label: '题库', icon: EditPen },
  { name: 'course-homework', label: '作业', icon: Notebook },
  { name: 'course-exams', label: '考试', icon: Document },
  { name: 'course-resources', label: '教学资源', icon: VideoCamera },
  { name: 'course-labs', label: '实验管理', icon: Pointer },
  { name: 'course-analytics', label: '学习统计', icon: TrendCharts },
]

const courseId = computed(() => Number(route.params.id) || null)

async function loadCourse() {
  if (!courseId.value) return
  const data = await listCourses()
  const list = data.results ?? data
  course.value = list.find((item) => Number(item.id) === courseId.value) || null
}

onMounted(() => {
  loadCourse()
  // 访问埋点：进入课程空间 +1（课程列表「常用优先」排序依据），失败静默
  if (courseId.value) visitCourse(courseId.value).catch(() => {})
})
watch(courseId, loadCourse)
</script>
