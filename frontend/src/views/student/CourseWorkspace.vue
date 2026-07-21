<template>
  <CourseWorkspaceShell
    :course-name="course?.name"
    :course-sub="course?.className || '已加入课程'"
    :tabs="tabs"
    back-to="/student/my-classes"
    back-text="返回我的课程"
    home-tab="student-course-learning"
  />
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  Document,
  Files,
  Notebook,
  Reading,
} from '@element-plus/icons-vue'
import CourseWorkspaceShell from '@/components/CourseWorkspaceShell.vue'
import { listClasses } from '@/api/classroom'

const route = useRoute()
const course = ref(null)

const tabs = [
  { name: 'student-course-learning', label: '章节目录', icon: Reading },
  { name: 'student-course-qa', label: 'AI 助教', icon: ChatDotRound },
  { name: 'student-course-materials', label: '课程资料', icon: Files },
  { name: 'student-course-homework', label: '我的作业', icon: Notebook },
  { name: 'student-course-exams', label: '我的考试', icon: Document },
  { name: 'student-course-wrong', label: '错题本', icon: Collection },
]

const courseId = computed(() => Number(route.params.id) || null)

async function loadCourse() {
  if (!courseId.value) return
  const data = await listClasses()
  const rows = data.results ?? data
  const map = new Map()
  rows.forEach((row) => {
    const ids = row.courses?.length ? row.courses : [row.course]
    ids.filter(Boolean).forEach((id, index) => {
      map.set(Number(id), {
        id: Number(id),
        name: row.course_names?.[index] || row.course_name || `课程 ${id}`,
        className: row.name,
      })
    })
  })
  course.value = map.get(courseId.value) || null
}

onMounted(loadCourse)
watch(courseId, loadCourse)
</script>
