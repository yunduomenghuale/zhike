<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">教学资源</div>
        <div class="page-subtitle">挂载思维导图/交互演示与数字人视频，发布后学生课程内可见</div>
      </div>
    </div>

    <!-- 思维导图 / 交互演示 -->
    <el-card shadow="never" class="mb12">
      <template #header><span>思维导图 / 交互演示</span></template>
      <el-form :model="resForm" label-width="90px" style="max-width: 720px" class="mb12">
        <el-form-item label="资源类型" required>
          <el-radio-group v-model="resForm.kind">
            <el-radio-button value="mindmap">思维导图</el-radio-button>
            <el-radio-button value="demo">交互演示</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="平台页面" required>
          <el-select v-model="resForm.path" filterable placeholder="选择预置静态页" style="width: 100%">
            <el-option
              v-for="p in availablePaths"
              :key="p.value"
              :value="p.value"
              :label="p.label"
            />
          </el-select>
          <el-link
            v-if="resForm.path"
            type="primary"
            :underline="false"
            :href="`/resources/${resForm.path}`"
            target="_blank"
            class="form-tip path-link"
          >
            <el-icon class="path-icon"><Link /></el-icon>
            /resources/{{ resForm.path }}
          </el-link>
          <span v-else class="form-tip">页面为平台预置，选择后可点击地址预览</span>
        </el-form-item>
        <el-form-item label="资源标题">
          <el-input v-model="resForm.title" placeholder="留空默认取页面文件名" />
        </el-form-item>
        <el-form-item label="挂载章节">
          <el-select v-model="resForm.catalog" clearable placeholder="可选，便于学生按章节查找" style="width: 100%">
            <el-option v-for="c in catalogs" :key="c.id" :value="c.id" :label="c.title" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creating" @click="createResource">添加资源</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="resources" v-loading="loadingRes" size="default">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'mindmap' ? 'primary' : 'success'" size="small">{{ row.kind_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="catalog_title" label="章节" width="150" />
        <el-table-column label="页面地址" min-width="200">
          <template #default="{ row }">
            <el-link
              type="primary"
              :underline="false"
              :href="viewerHref(row)"
              target="_blank"
              class="path-link"
            >
              <el-icon class="path-icon"><Link /></el-icon>
              {{ row.url }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_published ? 'success' : 'info'" size="small">{{ row.is_published ? '已发布' : '未发布' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="previewResource(row)">预览</el-button>
            <el-button v-if="!row.is_published" size="small" type="success" @click="publishRes(row)">发布</el-button>
            <el-button v-else size="small" type="warning" @click="unpublishRes(row)">下架</el-button>
            <el-button size="small" type="danger" plain @click="removeRes(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 数字人视频 -->
    <el-card shadow="never">
      <template #header><span>数字人视频</span></template>
      <el-form label-width="90px" style="max-width: 720px" class="mb12">
        <el-form-item label="视频文件" required>
          <input ref="videoFileEl" type="file" accept="video/mp4,video/webm" @change="onVideoPicked" />
          <span class="form-tip">支持 MP4 / WebM，单个不超过 500MB</span>
        </el-form-item>
        <el-form-item label="视频标题" required>
          <el-input v-model="videoForm.title" placeholder="例如：第4章 IP地址数字人精讲" style="max-width: 360px" />
        </el-form-item>
        <el-form-item label="挂载章节">
          <el-select v-model="videoForm.catalog" clearable placeholder="可选" style="max-width: 360px">
            <el-option v-for="c in catalogs" :key="c.id" :value="c.id" :label="c.title" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="uploading" :disabled="!videoForm.file" @click="uploadVideo">
            {{ uploading ? `上传中 ${uploadPercent}%` : '上传视频' }}
          </el-button>
        </el-form-item>
      </el-form>

      <el-table :data="videos" v-loading="loadingVideo">
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="catalog_title" label="章节" width="150" />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_published ? 'success' : 'info'" size="small">{{ row.is_published ? '已发布' : '未发布' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="previewVideo(row)">播放</el-button>
            <el-button v-if="!row.is_published" size="small" type="success" @click="publishVideo(row)">发布</el-button>
            <el-button v-else size="small" type="warning" @click="unpublishVideo(row)">下架</el-button>
            <el-button size="small" type="danger" plain @click="removeVideo(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 视频预览弹窗（保持原有查看方式） -->
    <el-dialog v-model="videoVisible" :title="videoTitle" width="900" destroy-on-close>
      <video
        v-if="videoUrl"
        :src="videoUrl"
        controls
        style="width: 100%; max-height: 60vh"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Link } from '@element-plus/icons-vue'
import {
  listCourseResources, createCourseResource, deleteCourseResource,
  publishCourseResource, unpublishCourseResource,
  listCourseVideos, uploadCourseVideo, deleteCourseVideo,
  publishCourseVideo, unpublishCourseVideo,
} from '@/api/course'
import { listCatalogs } from '@/api/course'
import request from '@/api/request'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.id) || null)

// 平台预置静态页清单（nginx /resources/ 只读资产；新增页面时同步此表）
const PRESET_PAGES = [
  { value: 'mindmap/index.html', label: '思维导图：全课程总览', kind: 'mindmap' },
  { value: 'mindmap/chapter1.html', label: '思维导图：第1章 概述', kind: 'mindmap' },
  { value: 'mindmap/chapter2.html', label: '思维导图：第2章 物理层', kind: 'mindmap' },
  { value: 'mindmap/chapter3.html', label: '思维导图：第3章 链路层', kind: 'mindmap' },
  { value: 'mindmap/chapter4.html', label: '思维导图：第4章 网络层', kind: 'mindmap' },
  { value: 'mindmap/chapter5.html', label: '思维导图：第5章 传输层', kind: 'mindmap' },
  { value: 'mindmap/chapter6.html', label: '思维导图：第6章 应用层', kind: 'mindmap' },
  { value: 'mindmap/chapter7.html', label: '思维导图：第7章 网络安全', kind: 'mindmap' },
  { value: 'mindmap/chapter8.html', label: '思维导图：第8章', kind: 'mindmap' },
  { value: 'demos/Mind-Map.html', label: '演示：课程知识地图', kind: 'demo' },
  { value: 'demos/tcp-demo.html', label: '演示：TCP 协议详解', kind: 'demo' },
  { value: 'demos/sliding-window.html', label: '演示：滑动窗口', kind: 'demo' },
  { value: 'demos/csma-cd-protocol.html', label: '演示：CSMA/CD 协议', kind: 'demo' },
  { value: 'demos/channel-multiplexing.html', label: '演示：信道复用', kind: 'demo' },
  { value: 'demos/digital-signal-encoding.html', label: '演示：数字信号编码', kind: 'demo' },
  { value: 'demos/network-classification.html', label: '演示：网络分类', kind: 'demo' },
  { value: 'demos/network-data-animation.html', label: '演示：数据发送动画', kind: 'demo' },
  { value: 'demos/network-delay-demo.html', label: '演示：网络延迟', kind: 'demo' },
  { value: 'demos/network-device-comparison.html', label: '演示：网络设备对比', kind: 'demo' },
  { value: 'demos/network-switching-demo.html', label: '演示：交换技术', kind: 'demo' },
  { value: 'demos/transmission-media-comparison.html', label: '演示：传输介质对比', kind: 'demo' },
]

const resForm = ref({ kind: 'mindmap', path: '', title: '', catalog: null })
const availablePaths = computed(() => PRESET_PAGES.filter((p) => p.kind === resForm.value.kind))

const resources = ref([])
const videos = ref([])
const catalogs = ref([])
const loadingRes = ref(false)
const loadingVideo = ref(false)
const creating = ref(false)

const videoForm = ref({ file: null, title: '', catalog: null })
const videoFileEl = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)

// 视频弹窗播放状态
const videoVisible = ref(false)
const videoUrl = ref('')
const videoTitle = ref('')

function presetTitle(path) {
  return PRESET_PAGES.find((p) => p.value === path)?.label || path
}

async function loadCatalogs() {
  if (!courseId.value) return
  const res = await listCatalogs({ course: courseId.value, tree: '1' })
  catalogs.value = res.results ?? res
}

async function loadResources() {
  loadingRes.value = true
  try {
    const res = await listCourseResources(courseId.value ? { course: courseId.value } : undefined)
    const data = res.results ?? res
    resources.value = Array.isArray(data) ? data : data?.results ?? []
  } finally {
    loadingRes.value = false
  }
}

async function loadVideos() {
  loadingVideo.value = true
  try {
    const res = await listCourseVideos(courseId.value ? { course: courseId.value } : undefined)
    const data = res.results ?? res
    videos.value = Array.isArray(data) ? data : data?.results ?? []
  } finally {
    loadingVideo.value = false
  }
}

async function createResource() {
  if (!resForm.value.path) {
    ElMessage.warning('请选择平台页面')
    return
  }
  creating.value = true
  try {
    await createCourseResource({
      course: courseId.value,
      catalog: resForm.value.catalog || null,
      kind: resForm.value.kind,
      title: resForm.value.title || presetTitle(resForm.value.path),
      path: resForm.value.path,
    })
    ElMessage.success('资源已添加')
    resForm.value.path = ''
    resForm.value.title = ''
    await loadResources()
  } finally {
    creating.value = false
  }
}

function previewResource(row) {
  // 进入近全屏查看器（思维导图隐藏站内章节导航，只看挂载的这一章）
  const hash = row.kind === 'mindmap' ? '#chapters-hidden' : ''
  router.push({
    name: 'course-resource-viewer',
    params: { id: courseId.value },
    query: {
      src: `${row.url}${hash}`,
      title: row.title,
      kind: row.kind,
      back: 'course-resources',
      t: Date.now(),
    },
  })
}

// 教师直接打开原始静态页（带章节导航，便于备课翻看其他章节）
function viewerHref(row) {
  return row.url
}

async function publishRes(row) {
  await publishCourseResource(row.id)
  ElMessage.success('已发布')
  await loadResources()
}

async function unpublishRes(row) {
  await unpublishCourseResource(row.id)
  ElMessage.success('已下架')
  await loadResources()
}

async function removeRes(row) {
  await ElMessageBox.confirm(`确认删除资源「${row.title}」？`, '提示', { type: 'warning' })
  await deleteCourseResource(row.id)
  await loadResources()
}

function onVideoPicked(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (file.size > 500 * 1024 * 1024) {
    ElMessage.error('视频不能超过 500MB')
    videoFileEl.value.value = ''
    return
  }
  videoForm.value.file = file
  if (!videoForm.value.title) videoForm.value.title = file.name.replace(/\.[^.]+$/, '')
}

async function uploadVideo() {
  if (!videoForm.value.file || !videoForm.value.title) {
    ElMessage.warning('请选择文件并填写标题')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await uploadCourseVideo({
      course: courseId.value,
      catalog: videoForm.value.catalog || null,
      title: videoForm.value.title,
      file: videoForm.value.file,
      onProgress: (e) => {
        if (e.total) uploadPercent.value = Math.round((e.loaded / e.total) * 100)
      },
    })
    ElMessage.success('视频已上传')
    videoForm.value = { file: null, title: '', catalog: null }
    videoFileEl.value.value = ''
    await loadVideos()
  } finally {
    uploading.value = false
  }
}

function previewVideo(row) {
  videoTitle.value = row.title
  videoUrl.value = row.file_url
  videoVisible.value = true
}

async function publishVideo(row) {
  await publishCourseVideo(row.id)
  ElMessage.success('已发布')
  await loadVideos()
}

async function unpublishVideo(row) {
  await unpublishCourseVideo(row.id)
  ElMessage.success('已下架')
  await loadVideos()
}

async function removeVideo(row) {
  await ElMessageBox.confirm(`确认删除视频「${row.title}」？删除后不可恢复。`, '提示', { type: 'warning' })
  await deleteCourseVideo(row.id)
  await loadVideos()
}

function fmtSize(bytes) {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = Number(bytes)
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i += 1
  }
  return `${n.toFixed(1)} ${units[i]}`
}

onMounted(async () => {
  await loadCatalogs()
  await Promise.all([loadResources(), loadVideos()])
})
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.form-tip { color: #94a3b8; font-size: 12px; margin-left: 10px; }
.path-link { font-size: 12px; }
.path-icon { margin-right: 4px; vertical-align: -2px; }
</style>
