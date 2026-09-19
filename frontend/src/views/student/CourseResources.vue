<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">课程资源</div>
        <div class="page-subtitle">思维导图、交互演示与数字人视频，点击卡片全屏查看</div>
      </div>
    </div>

    <el-card shadow="never" class="mb12">
      <template #header><span>思维导图 / 交互演示</span></template>
      <el-empty v-if="!resources.length" description="教师暂未发布资源" :image-size="80" />
      <template v-else>
        <div v-for="group in groupedResources" :key="group.catalog" class="chapter-group">
          <div class="group-title">
            <el-icon><Collection /></el-icon>
            <span>{{ group.title }}</span>
            <span class="group-count">{{ group.items.length }} 个</span>
          </div>
          <div class="res-grid">
            <div
              v-for="r in group.items"
              :key="r.id"
              class="res-card"
              @click="openResource(r)"
            >
              <div class="res-icon">{{ r.kind === 'mindmap' ? '🗺️' : '🎬' }}</div>
              <div class="res-info">
                <div class="res-title">{{ r.title }}</div>
                <div class="res-meta">{{ r.kind_display }}</div>
              </div>
              <el-icon class="res-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    <el-card shadow="never">
      <template #header><span>数字人视频</span></template>
      <el-empty v-if="!videos.length" description="教师暂未发布视频" :image-size="80" />
      <template v-else>
        <div v-for="group in groupedVideos" :key="group.catalog" class="chapter-group">
          <div class="group-title">
            <el-icon><Collection /></el-icon>
            <span>{{ group.title }}</span>
            <span class="group-count">{{ group.items.length }} 个</span>
          </div>
          <div class="res-grid">
            <div v-for="v in group.items" :key="v.id" class="res-card" @click="openVideo(v)">
              <div class="res-icon">📹</div>
              <div class="res-info">
                <div class="res-title">{{ v.title }}</div>
                <div class="res-meta">视频 · {{ fmtSize(v.file_size) }}</div>
              </div>
              <el-icon class="res-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    <!-- 视频预览弹窗（保持原有查看方式） -->
    <el-dialog v-model="videoVisible" :title="videoTitle" width="920" destroy-on-close>
      <video
        v-if="videoUrl"
        :src="videoUrl"
        controls
        autoplay
        style="width: 100%; max-height: 62vh"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Collection } from '@element-plus/icons-vue'
import { listCourseResources, listCourseVideos } from '@/api/course'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.id) || null)

const resources = ref([])
const videos = ref([])

// 视频弹窗播放状态
const videoVisible = ref(false)
const videoUrl = ref('')
const videoTitle = ref('')

function pick(list) {
  if (Array.isArray(list)) return list
  return list?.results ?? []
}

async function load() {
  const params = courseId.value ? { course: courseId.value } : undefined
  const [r, v] = await Promise.all([listCourseResources(params), listCourseVideos(params)])
  resources.value = pick(r)
  videos.value = pick(v)
}

// 按挂载章节分组：有章节的排前面按章节聚合，未挂章节的归入「通用资源」
function groupByCatalog(list) {
  const chapters = new Map()
  const general = []
  for (const item of list) {
    if (item.catalog && item.catalog_title) {
      if (!chapters.has(item.catalog)) chapters.set(item.catalog, [])
      chapters.get(item.catalog).push(item)
    } else {
      general.push(item)
    }
  }
  const groups = [...chapters.entries()].map(([catalog, items]) => ({
    catalog,
    title: items[0].catalog_title,
    items,
  }))
  if (general.length) groups.push({ catalog: 0, title: '通用资源', items: general })
  return groups
}

const groupedResources = computed(() => groupByCatalog(resources.value))
const groupedVideos = computed(() => groupByCatalog(videos.value))

// 进入近全屏查看器；思维导图带 #chapters-hidden 隐藏站内章节导航（只看挂载的这一章）
function viewerQuery(extra) {
  return {
    src: extra.src,
    title: extra.title,
    type: extra.type || 'html',
    kind: extra.kind || '',
    back: 'student-course-resources',
    t: Date.now(),
  }
}

function openResource(r) {
  const hash = r.kind === 'mindmap' ? '#chapters-hidden' : ''
  routeToViewer({
    name: 'student-course-resource-viewer',
    params: { id: courseId.value },
    query: viewerQuery({ src: `${r.url}${hash}`, title: r.title, kind: r.kind }),
  })
}

function openVideo(v) {
  // 视频保持弹窗播放（原有方式），仅思维导图/演示用全屏查看器
  videoTitle.value = v.title
  videoUrl.value = v.file_url
  videoVisible.value = true
}

function routeToViewer(loc) {
  const { href } = router.resolve(loc)
  // 查看器占满整个浏览器窗口（新标签页），体验接近独立播放页
  window.open(href, '_blank')
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

onMounted(load)
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.chapter-group { margin-bottom: 18px; }
.chapter-group:last-child { margin-bottom: 0; }
.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 10px;
}
.group-count {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
}
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
.res-meta { color: #94a3b8; font-size: 12px; }
.res-arrow { color: #cbd5e1; }
.res-card:hover .res-arrow { color: #4a90e2; }
</style>
