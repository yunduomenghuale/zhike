<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">课程资源</div>
        <div class="page-subtitle">思维导图、交互演示与文档资料，点击卡片查看</div>
      </div>
    </div>

    <el-card shadow="never" class="mb12">
      <template #header><span>思维导图 / 交互演示</span></template>
      <el-empty v-if="!presetResources.length" description="教师暂未发布资源" :image-size="80" />
      <div v-else class="res-grid">
        <div
          v-for="r in presetResources"
          :key="r.id"
          class="res-card"
          @click="openPreset(r)"
        >
          <div class="res-icon">{{ r.kind === 'mindmap' ? '🗺️' : '🎬' }}</div>
          <div class="res-info">
            <div class="res-title">{{ r.title }}</div>
            <div class="res-meta">{{ r.kind_display }}</div>
          </div>
          <el-icon class="res-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header><span>文档资料</span></template>
      <el-empty v-if="!documentResources.length" description="教师暂未发布文档" :image-size="80" />
      <div v-else class="res-grid">
        <div
          v-for="r in documentResources"
          :key="r.id"
          class="res-card"
          @click="openDocument(r)"
        >
          <div class="res-icon">📄</div>
          <div class="res-info">
            <div class="res-title">{{ r.title }}</div>
            <div class="res-meta">
              文档 · {{ r.file_name || '—' }}
              <template v-if="r.file_size"> · {{ fmtSize(r.file_size) }}</template>
              <template v-if="isPdf(r)"> · 可在线预览</template>
            </div>
          </div>
          <el-icon class="res-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { listCourseResources, signCourseResource } from '@/api/course'
import { openTabDeferred } from '@/utils/open-tab'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.id) || null)

const resources = ref([])

function pick(list) {
  if (Array.isArray(list)) return list
  return list?.results ?? []
}

async function load() {
  const params = courseId.value ? { course: courseId.value } : undefined
  const r = await listCourseResources(params)
  resources.value = pick(r)
}

const presetResources = computed(() => resources.value.filter((r) => r.kind !== 'document'))
const documentResources = computed(() => resources.value.filter((r) => r.kind === 'document'))

function isPdf(row) {
  return (row.file_name || '').toLowerCase().endsWith('.pdf')
}

// 进入近全屏查看器；思维导图带 #chapters-hidden 隐藏站内章节导航
function viewerQuery(extra) {
  return {
    src: extra.src,
    title: extra.title,
    type: extra.type || 'html',
    kind: extra.kind || '',
    back: 'student-course-resources',
  }
}

async function openPreset(r) {
  // 先签发唯一签名 URL（未发布/非在读课程后端拒签），再进查看器；
  // 标签页在点击时同步开出，避免异步后的 window.open 被弹窗拦截
  const tab = openTabDeferred()
  let signed
  try {
    signed = await signCourseResource(r.id)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '资源打开失败，请稍后重试')
    return
  }
  const hash = r.kind === 'mindmap' ? '#chapters-hidden' : ''
  const { href } = router.resolve({
    name: 'student-course-resource-viewer',
    params: { id: courseId.value },
    query: viewerQuery({ src: `${signed.url}${hash}`, title: r.title, kind: r.kind }),
  })
  tab.open(href)
}

async function openDocument(r) {
  // 文档：签发 file 地址；PDF 进查看器内联预览，doc/docx 新窗口触发下载
  const tab = openTabDeferred()
  let signed
  try {
    signed = await signCourseResource(r.id)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '文档打开失败，请稍后重试')
    return
  }
  if (isPdf(r)) {
    const { href } = router.resolve({
      name: 'student-course-resource-viewer',
      params: { id: courseId.value },
      query: viewerQuery({ src: signed.url, title: r.title, type: 'pdf', kind: 'document' }),
    })
    tab.open(href)
    return
  }
  tab.open(signed.url)
}

function fmtSize(bytes) {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = Number(bytes)
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i += 1
  }
  return `${n.toFixed(1)} ${units[i]}`
}

// 课程空间内切换课程时重新加载
watch(courseId, () => load())

onMounted(load)
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.res-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.res-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.res-card:hover {
  border-color: #4a90e2;
  box-shadow: 0 2px 8px rgba(74, 144, 226, 0.15);
}
.res-icon { font-size: 28px; }
.res-info { flex: 1; min-width: 0; }
.res-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.res-meta { color: #94a3b8; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.res-arrow { color: #cbd5e1; }
.res-card:hover .res-arrow { color: #4a90e2; }
</style>
