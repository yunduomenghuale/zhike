<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">课程资源</div>
        <div class="page-subtitle">思维导图、交互演示与文档资料，点击卡片查看</div>
      </div>
    </div>

    <!-- 类型筛选 + 搜索（前端即时过滤） -->
    <div class="res-toolbar">
      <div class="kind-tabs">
        <button
          v-for="t in kindTabs"
          :key="t.value"
          type="button"
          class="kind-tab"
          :class="{ active: kindFilter === t.value }"
          @click="kindFilter = t.value"
        >
          {{ t.label }}<span class="tab-count">{{ t.count }}</span>
        </button>
      </div>
      <span class="toolbar-spacer" />
      <el-input
        v-model.trim="keyword"
        placeholder="搜索资源"
        clearable
        class="toolbar-search"
        :prefix-icon="Search"
      />
    </div>

    <el-empty
      v-if="!filteredResources.length"
      :description="resources.length ? '没有匹配当前筛选的资源' : '教师暂未发布资源'"
      :image-size="90"
    />
    <div v-else class="res-grid">
      <div
        v-for="r in filteredResources"
        :key="r.id"
        class="res-card"
        @click="openResource(r)"
      >
        <div class="res-cover" :class="'cover-' + r.kind">
          <span class="cover-badge">
            <el-icon :size="18"><component :is="kindIcon(r.kind)" /></el-icon>
          </span>
        </div>
        <div class="res-body">
          <div class="res-title" :title="r.title">{{ r.title }}</div>
          <div class="res-meta">
            {{ r.kind_display }}
            <template v-if="r.kind === 'document'">
              <template v-if="r.file_size"> · {{ fmtSize(r.file_size) }}</template>
              <template v-if="isPdf(r)"> · 可在线预览</template>
            </template>
          </div>
        </div>
        <el-icon class="res-arrow"><ArrowRight /></el-icon>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, Connection, Document, MagicStick, Search } from '@element-plus/icons-vue'
import { listCourseResources, signCourseResource } from '@/api/course'
import { openTabDeferred } from '@/utils/open-tab'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.id) || null)

const resources = ref([])
const kindFilter = ref('')
const keyword = ref('')

function pick(list) {
  if (Array.isArray(list)) return list
  return list?.results ?? []
}

async function load() {
  const params = courseId.value ? { course: courseId.value } : undefined
  const r = await listCourseResources(params)
  resources.value = pick(r)
}

const kindTabs = computed(() => [
  { value: '', label: '全部', count: resources.value.length },
  { value: 'mindmap', label: '思维导图', count: resources.value.filter((r) => r.kind === 'mindmap').length },
  { value: 'demo', label: '交互演示', count: resources.value.filter((r) => r.kind === 'demo').length },
  { value: 'document', label: '文档', count: resources.value.filter((r) => r.kind === 'document').length },
])

const filteredResources = computed(() => {
  const kw = keyword.value.toLowerCase()
  return resources.value.filter((r) => {
    if (kindFilter.value && r.kind !== kindFilter.value) return false
    if (kw) {
      const hay = `${r.title} ${r.kind === 'document' ? r.file_name || '' : ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

function kindIcon(kind) {
  return kind === 'mindmap' ? Connection : kind === 'demo' ? MagicStick : Document
}

function isPdf(row) {
  return (row.file_name || '').toLowerCase().endsWith('.pdf')
}

function viewerQuery(extra) {
  return {
    src: extra.src,
    title: extra.title,
    type: extra.type || 'html',
    kind: extra.kind || '',
    back: 'student-course-resources',
  }
}

async function openResource(r) {
  // 先签发唯一签名 URL（未发布/非在读课程后端拒签）再打开；
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
  if (r.kind === 'document' && isPdf(r)) {
    // PDF 进查看器内联预览
    const { href } = router.resolve({
      name: 'student-course-resource-viewer',
      params: { id: courseId.value },
      query: viewerQuery({ src: signed.url, title: r.title, type: 'pdf', kind: 'document' }),
    })
    tab.open(href)
    return
  }
  if (r.kind === 'document') {
    // doc/docx 直接下载
    tab.open(signed.url)
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
/* ---- 工具栏 ---- */
.res-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.kind-tabs {
  display: flex;
  gap: 4px;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 3px;
}
.kind-tab {
  border: 0;
  background: transparent;
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.kind-tab:hover { color: #0f172a; }
.kind-tab.active {
  background: #fff;
  color: #0f172a;
  font-weight: 500;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: #94a3b8;
}
.kind-tab.active .tab-count { color: #2563eb; }
.toolbar-spacer { flex: 1; }
.toolbar-search { width: 200px; }

/* ---- 封面式卡片 ---- */
.res-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}
.res-card {
  background: #fff;
  border: 0.5px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.res-card:hover {
  border-color: #4a90e2;
  box-shadow: 0 2px 10px rgba(74, 144, 226, 0.15);
}
.res-cover {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.res-cover.cover-mindmap { background: #e6f1fb; }
.res-cover.cover-demo { background: #e1f5ee; }
.res-cover.cover-document { background: #faeeda; }
.cover-badge {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-mindmap .cover-badge { color: #185fa5; }
.cover-demo .cover-badge { color: #0f6e56; }
.cover-document .cover-badge { color: #854f0b; }
.res-body {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
}
.res-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.res-meta {
  flex: 0 0 auto;
  max-width: 46%;
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.res-arrow {
  flex: 0 0 auto;
  color: #cbd5e1;
  font-size: 14px;
  margin-right: 4px;
}
.res-card:hover .res-arrow { color: #4a90e2; }
</style>
