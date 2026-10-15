<template>
  <!-- 注意：课程空间内「切换课程」下拉已按需求暂时隐藏。
       恢复方式：把下方 :courses="courseOptions" 加回 Shell，并在 script 中恢复 courseOptions 的构建 -->
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
  VideoPlay,
  Pointer,
} from '@element-plus/icons-vue'
import CourseWorkspaceShell from '@/components/CourseWorkspaceShell.vue'
import { listClasses } from '@/api/classroom'

const route = useRoute()
const course = ref(null)

const tabs = [
  { name: 'student-course-learning', label: '章节目录', icon: Reading },
  { name: 'student-course-qa', label: 'AI 助教', icon: ChatDotRound },
  { name: 'student-course-materials', label: '课程资料', icon: Files },
  { name: 'student-course-resources', label: '课程资源', icon: VideoPlay },
  { name: 'student-course-labs', label: '虚拟实验', icon: Pointer },
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
      const cid = Number(id)
      if (!map.has(cid)) {
        map.set(cid, {
          id: cid,
          name: row.course_names?.[index] || row.course_name || `课程 ${cid}`,
          className: row.name,
        })
      }
    })
  })
  course.value = map.get(courseId.value) || null
}

onMounted(loadCourse)
watch(courseId, loadCourse)
</script>
