<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">教学资源</div>
        <div class="page-subtitle">思维导图、交互演示与文档直接归属课程，发布后学生课程内可见</div>
      </div>
    </div>

    <!-- 工具栏：类型分段（带计数）+ 搜索 + 状态筛选 + 添加资源 -->
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
        placeholder="搜索资源标题 / 文件名"
        clearable
        class="toolbar-search"
        :prefix-icon="Search"
      />
      <el-select v-model="statusFilter" class="toolbar-status" placeholder="状态：全部">
        <el-option label="状态：全部" value="" />
        <el-option label="已发布" value="published" />
        <el-option label="未发布" value="unpublished" />
      </el-select>
      <el-button type="primary" :icon="Plus" @click="openAddDialog">添加资源</el-button>
    </div>

    <!-- 统一资源表格（三种类型同表，前端即时过滤） -->
    <el-card shadow="never" class="res-panel">
      <el-table :data="filteredResources" v-loading="loadingRes" size="small" class="compact-table">
        <el-table-column label="资源" min-width="220">
          <template #default="{ row }">
            <div class="res-cell">
              <span class="res-badge" :class="'kind-' + row.kind">
                <el-icon :size="15"><component :is="kindIcon(row.kind)" /></el-icon>
              </span>
              <span class="res-text">
                <span class="res-title" :title="row.title">{{ row.title }}</span>
                <span class="res-sub" :title="row.kind === 'document' || !row.path ? row.file_name : row.path">
                  {{ row.kind === 'document' || !row.path ? (row.file_name || '—') : row.path }}
                </span>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="92">
          <template #default="{ row }">
            <el-tag :type="kindTagType(row.kind)" size="small" effect="light">{{ row.kind_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">
            <span v-if="row.kind === 'document'">{{ fmtSize(row.file_size) }}</span>
            <span v-else class="muted-cell">—</span>
          </template>
        </el-table-column>
        <el-table-column label="发布" width="72" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_published"
              :loading="row._toggling"
              inline-prompt
              active-text="已发"
              inactive-text="未发"
              @change="togglePublish(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="228" fixed="right" header-align="center">
          <template #default="{ row }">
            <div class="op-cell">
              <el-button size="small" @click="previewResource(row)">
                {{ row.kind === 'document' && !isPdf(row) ? '下载' : '预览' }}
              </el-button>
              <el-button size="small" @click="copyResourceLink(row)">复制链接</el-button>
              <el-button size="small" type="danger" plain @click="removeRes(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="resources.length ? '没有匹配当前筛选的资源' : '暂无资源，点击右上角「添加资源」开始'" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 添加资源弹窗：第一步选类型，动态出表单 -->
    <el-dialog
      v-model="addVisible"
      width="560px"
      align-center
      :show-close="false"
      class="add-res-dialog"
      :close-on-click-modal="false"
    >
      <template #header>
        <div class="dialog-head">
          <span class="dialog-title">添加资源</span>
          <el-button text circle :icon="Close" @click="addVisible = false" />
        </div>
      </template>

      <el-form label-position="top">
        <el-form-item label="资源类型" required>
          <el-radio-group v-model="addForm.kind">
            <el-radio-button value="document">文档</el-radio-button>
            <el-radio-button value="mindmap">思维导图</el-radio-button>
            <el-radio-button value="demo">交互演示</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="addForm.kind !== 'document'">
          <el-form-item label="资源来源" required>
            <el-radio-group v-model="addForm.source">
              <el-radio-button value="upload">上传文件</el-radio-button>
              <el-radio-button value="preset">平台预置</el-radio-button>
            </el-radio-group>
            <div class="form-extra">
              <span class="form-tip">预置为平台自带静态页；上传支持自定义单文件 HTML（由 markmap 等工具导出，≤100MB）</span>
            </div>
          </el-form-item>

          <template v-if="addForm.source === 'preset'">
            <el-form-item label="平台页面" required>
              <el-select v-model="addForm.path" filterable placeholder="选择预置静态页" style="width: 100%">
                <el-option v-for="p in availablePaths" :key="p.value" :value="p.value" :label="p.label" />
              </el-select>
              <div class="form-extra">
                <el-button
                  v-if="addForm.path"
                  link
                  type="primary"
                  :loading="presetPreviewing"
                  @click="previewPreset"
                >
                  <el-icon class="path-icon"><Link /></el-icon>
                  预览该页面
                </el-button>
                <span v-if="addForm.path" class="form-tip">预置页：{{ addForm.path }}</span>
                <span v-else class="form-tip">页面为平台预置，选择后可先预览再添加</span>
              </div>
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="HTML 文件" required>
              <el-upload
                drag
                :show-file-list="false"
                :before-upload="onHtmlPicked"
                :accept="'.html'"
                class="course-upload"
              >
                <div class="upload-inner">
                  <div class="upload-mark">
                    <el-icon><UploadFilled /></el-icon>
                  </div>
                  <div class="upload-main">{{ addForm.file ? '重新选择文件' : '拖入或选择 HTML 文件' }}</div>
                  <div class="upload-sub">单个 .html 文件，不超过 100MB；多文件（含图片/JS 目录）的演示请先内联为单文件</div>
                </div>
              </el-upload>
              <div v-if="addForm.file" class="file-status">
                <div class="file-icon">
                  <el-icon><Document /></el-icon>
                </div>
                <div class="file-meta">
                  <div class="file-name" :title="addForm.file.name">{{ addForm.file.name }}</div>
                  <div class="file-note">{{ fmtSize(addForm.file.size) }} · 点击上方区域可重新选择</div>
                </div>
              </div>
              <el-progress v-if="uploading" :percentage="uploadPercent" :stroke-width="8" class="upload-progress" />
            </el-form-item>
          </template>

          <el-form-item label="资源标题">
            <el-input v-model="addForm.title" :placeholder="addForm.source === 'preset' ? '留空默认取页面名称' : '例如：第5章 传输层思维导图'" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="文档文件" required>
            <!-- 与章节课件上传同构（CourseCatalog .course-upload）：拖入或点击选择，选择即校验 -->
            <el-upload
              drag
              :show-file-list="false"
              :before-upload="onDocPicked"
              :accept="'.pdf,.doc,.docx'"
              class="course-upload"
            >
              <div class="upload-inner">
                <div class="upload-mark">
                  <el-icon><UploadFilled /></el-icon>
                </div>
                <div class="upload-main">{{ addForm.file ? '重新选择文档' : '拖入或选择文档' }}</div>
                <div class="upload-sub">支持 PDF / DOC / DOCX，单个不超过 100MB；PDF 学生端可在线预览，DOC/DOCX 下载查看</div>
              </div>
            </el-upload>
            <div v-if="addForm.file" class="file-status">
              <div class="file-icon">
                <el-icon><Document /></el-icon>
              </div>
              <div class="file-meta">
                <div class="file-name" :title="addForm.file.name">{{ addForm.file.name }}</div>
                <div class="file-note">{{ fmtSize(addForm.file.size) }} · 点击上方区域可重新选择</div>
              </div>
            </div>
            <el-progress v-if="uploading" :percentage="uploadPercent" :stroke-width="8" class="upload-progress" />
          </el-form-item>
          <el-form-item label="资源标题" required>
            <el-input v-model="addForm.title" placeholder="例如：计算机网络复习大纲" />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating || uploading"
          :disabled="confirmDisabled"
          @click="confirmAdd"
        >
          {{ addForm.kind === 'document' || addForm.source === 'upload' ? '上传并添加' : '添加资源' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Close, Connection, Document, Link, MagicStick, Plus, Search, UploadFilled,
} from '@element-plus/icons-vue'
import {
  listCourseResources, createCourseResource, deleteCourseResource,
  publishCourseResource, unpublishCourseResource,
  signCourseResource, signPresetPage, uploadCourseDocument, uploadCourseResourceFile,
} from '@/api/course'
import { openTabDeferred, downloadUrl } from '@/utils/open-tab'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.id) || null)

// 平台预置静态页清单（deploy/resources 只读资产，经签名门控由 Django 读出；新增页面时同步此表）
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

const KIND_LABELS = { mindmap: '思维导图', demo: '交互演示', document: '文档' }

// ---- 列表数据与过滤 ----
const resources = ref([])
const loadingRes = ref(false)
const kindFilter = ref('')
const keyword = ref('')
const statusFilter = ref('')

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
    if (statusFilter.value === 'published' && !r.is_published) return false
    if (statusFilter.value === 'unpublished' && r.is_published) return false
    if (kw) {
      const hay = `${r.title} ${r.kind === 'document' ? r.file_name || '' : r.path}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

function kindIcon(kind) {
  return kind === 'mindmap' ? Connection : kind === 'demo' ? MagicStick : Document
}

function kindTagType(kind) {
  return kind === 'mindmap' ? 'primary' : kind === 'demo' ? 'success' : 'warning'
}

function isPdf(row) {
  return (row.file_name || '').toLowerCase().endsWith('.pdf')
}

async function loadResources() {
  loadingRes.value = true
  try {
    const res = await listCourseResources(courseId.value ? { course: courseId.value } : undefined)
    const data = res.results ?? res
    resources.value = (Array.isArray(data) ? data : data?.results ?? []).map((r) => ({ ...r, _toggling: false }))
  } finally {
    loadingRes.value = false
  }
}

// ---- 添加资源弹窗 ----
const addVisible = ref(false)
const creating = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const presetPreviewing = ref(false)
const addForm = reactive({ kind: 'document', source: 'upload', path: '', title: '', file: null })

const availablePaths = computed(() => PRESET_PAGES.filter((p) => p.kind === addForm.kind))

// 确认按钮禁用态：文档/上传来源必须有文件，预置来源必须选页面
const confirmDisabled = computed(() => {
  if (addForm.kind === 'document') return !addForm.file
  if (addForm.source === 'upload') return !addForm.file
  return !addForm.path
})

function openAddDialog() {
  // 文档/上传文件为高频路径，排首位且默认选中
  addForm.kind = 'document'
  addForm.source = 'upload'
  addForm.path = ''
  addForm.title = ''
  addForm.file = null
  uploadPercent.value = 0
  addVisible.value = true
}

function presetTitle(path) {
  return PRESET_PAGES.find((p) => p.value === path)?.label || path
}

const DOC_EXTS = ['.pdf', '.doc', '.docx']
const HTML_EXTS = ['.html']
const DOC_MAX_SIZE = 100 * 1024 * 1024

function onDocPicked(file) {
  // el-upload before-upload：返回 false 阻断自动上传，仅做校验与暂存（对齐课件/题库导入模式）
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!DOC_EXTS.includes(ext)) {
    ElMessage.error('仅支持 pdf / doc / docx 格式')
    return false
  }
  if (file.size > DOC_MAX_SIZE) {
    ElMessage.error('文档不能超过 100MB')
    return false
  }
  if (file.size === 0) {
    ElMessage.error('文档文件为空')
    return false
  }
  addForm.file = file
  if (!addForm.title) addForm.title = file.name.replace(/\.[^.]+$/, '')
  return false
}

function onHtmlPicked(file) {
  // 自定义导图/演示：仅单文件 .html（el-upload before-upload 阻断自动上传）
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!HTML_EXTS.includes(ext)) {
    ElMessage.error('仅支持 .html 单文件')
    return false
  }
  if (file.size > DOC_MAX_SIZE) {
    ElMessage.error('文件不能超过 100MB')
    return false
  }
  if (file.size === 0) {
    ElMessage.error('文件为空')
    return false
  }
  addForm.file = file
  if (!addForm.title) addForm.title = file.name.replace(/\.[^.]+$/, '')
  return false
}

async function confirmAdd() {
  if (addForm.kind === 'document') {
    await uploadDocument()
    return
  }
  if (addForm.source === 'upload') {
    await uploadCustomHtml()
    return
  }
  creating.value = true
  try {
    await createCourseResource({
      course: courseId.value,
      kind: addForm.kind,
      title: addForm.title.trim() || presetTitle(addForm.path),
      path: addForm.path,
    })
    ElMessage.success('资源已添加')
    addVisible.value = false
    await loadResources()
  } catch { /* 响应拦截器已提示具体错误（如重复添加） */ }
  finally {
    creating.value = false
  }
}

// 自定义导图/演示：单文件 HTML 上传（multipart，path 留空由后端判定为自定义）
async function uploadCustomHtml() {
  if (!addForm.title.trim()) {
    ElMessage.warning('请填写资源标题')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await uploadCourseResourceFile({
      course: courseId.value,
      kind: addForm.kind,
      title: addForm.title.trim(),
      file: addForm.file,
      onProgress: (e) => {
        if (e.total) uploadPercent.value = Math.round((e.loaded / e.total) * 100)
      },
    })
    ElMessage.success('自定义资源已上传')
    addVisible.value = false
    await loadResources()
  } catch { /* 响应拦截器已提示具体错误 */ }
  finally {
    uploading.value = false
  }
}

async function uploadDocument() {
  if (!addForm.title.trim()) {
    ElMessage.warning('请填写资源标题')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await uploadCourseDocument({
      course: courseId.value,
      title: addForm.title.trim(),
      file: addForm.file,
      onProgress: (e) => {
        if (e.total) uploadPercent.value = Math.round((e.loaded / e.total) * 100)
      },
    })
    ElMessage.success('文档已上传')
    addVisible.value = false
    await loadResources()
  } catch { /* 响应拦截器已提示具体错误 */ }
  finally {
    uploading.value = false
  }
}

// 添加资源前预览平台预置页（教师签发，无需资源行）
async function previewPreset() {
  if (!addForm.path) return
  presetPreviewing.value = true
  const tab = openTabDeferred()
  try {
    const signed = await signPresetPage(addForm.path)
    tab.open(signed.url)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '预览失败，请稍后重试')
  } finally {
    presetPreviewing.value = false
  }
}

// ---- 行操作 ----
async function togglePublish(row) {
  row._toggling = true
  try {
    if (row.is_published) {
      await unpublishCourseResource(row.id)
      row.is_published = false
      ElMessage.success('已下架，学生端立即不可见')
    } else {
      await publishCourseResource(row.id)
      row.is_published = true
      ElMessage.success('已发布')
    }
  } catch { /* 拦截器已提示 */ }
  finally {
    row._toggling = false
  }
}

async function previewResource(row) {
  // 文档类非 PDF（doc/docx）：签发后直接触发下载，不开新标签页（避免 about:blank 残留）
  if (row.kind === 'document' && !isPdf(row)) {
    try {
      const signed = await signCourseResource(row.id)
      downloadUrl(signed.url)
    } catch { /* 拦截器已提示 */ }
    return
  }
  // HTML 类（预置/自定义导图演示）：在延迟标签页中打开查看器，避免签名异步等待被弹窗拦截
  const tab = openTabDeferred()
  let signed
  try {
    signed = await signCourseResource(row.id)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '资源打开失败，请稍后重试')
    return
  }
  if (row.kind === 'document') {
    // PDF 文档：file 地址进查看器内联预览（iframe）
    const { href } = router.resolve({
      name: 'course-resource-viewer',
      params: { id: courseId.value },
      query: { src: signed.url, title: row.title, type: 'pdf', kind: 'document', back: 'course-resources' },
    })
    tab.open(href)
    return
  }
  const hash = row.kind === 'mindmap' ? '#chapters-hidden' : ''
  const { href } = router.resolve({
    name: 'course-resource-viewer',
    params: { id: courseId.value },
    query: {
      src: `${signed.url}${hash}`,
      title: row.title,
      kind: row.kind,
      back: 'course-resources',
    },
  })
  tab.open(href)
}

// 复制 2 小时内有效的访问链接（便于临时分享）
async function copyResourceLink(row) {
  let signed
  try {
    signed = await signCourseResource(row.id)
  } catch (e) {
    ElMessage.error(e?.message || '链接生成失败，请稍后重试')
    return
  }
  const ok = await copyText(`${location.origin}${signed.url}`)
  if (ok) ElMessage.success('链接已复制（2 小时内有效）')
  else ElMessage.warning('复制失败，请手动复制页面地址')
}

// 剪贴板：安全上下文用 async API，http 环境回退 execCommand
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 回退 */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.cssText = 'position:fixed;opacity:0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

async function removeRes(row) {
  await ElMessageBox.confirm(
    `确认删除资源「${row.title}」？${row.kind === 'document' ? '上传的文件将一并删除，' : ''}不可恢复。`,
    '提示', { type: 'warning' },
  )
  await deleteCourseResource(row.id)
  ElMessage.success('已删除')
  await loadResources()
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

onMounted(loadResources)
</script>

<style scoped>
/* ---- 工具栏 ---- */
.res-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
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
.toolbar-search { width: 220px; }
.toolbar-status { width: 116px; }

/* ---- 资源列（图标章 + 标题/副行） ---- */
.res-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.res-badge {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}
.res-badge.kind-mindmap { background: #e6f1fb; color: #185fa5; }
.res-badge.kind-demo { background: #e1f5ee; color: #0f6e56; }
.res-badge.kind-document { background: #faeeda; color: #854f0b; }
.res-text { min-width: 0; display: flex; flex-direction: column; }
.res-title {
  font-size: 13px;
  font-weight: 500;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.res-sub {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.muted-cell { color: #cbd5e1; font-size: 12px; }

/* 操作列：按钮平铺（EP 主题 .el-button+.el-button margin 与 flex gap 叠加，须 :deep 归零） */
.op-cell { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.op-cell :deep(.el-button) { margin-left: 0; }

/* 表格紧凑化 */
.compact-table :deep(.el-table__cell) { padding: 8px 0; }
.compact-table :deep(.el-table__cell .cell) { line-height: 22px; }
.res-panel :deep(.el-card__body) { padding: 8px 12px; }

/* ---- 添加弹窗 ---- */
.add-res-dialog :deep(.el-dialog) { border-radius: 16px; }
.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 4px;
}
.dialog-title { font-size: 16px; font-weight: 600; color: #0f172a; }
.form-extra { margin-top: 6px; display: flex; align-items: center; gap: 8px; }
.form-tip { color: #94a3b8; font-size: 12px; }
.path-icon { margin-right: 2px; vertical-align: -2px; }
.upload-progress { margin-top: 8px; }

/* ---- 文档上传区：与章节课件上传同构（CourseCatalog .course-upload 同款样式） ---- */
.course-upload :deep(.el-upload) { width: 100%; }
.course-upload :deep(.el-upload-dragger) {
  width: 100%;
  min-height: 150px;
  padding: 24px 16px;
  border: 1px dashed #bfdbfe;
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}
.course-upload :deep(.el-upload-dragger .el-upload__text) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
}
.course-upload :deep(.el-upload-dragger:hover) {
  border-color: #3b82f6;
  background: #fff;
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.1);
}
.upload-inner { display: grid; justify-items: center; align-content: center; gap: 10px; padding: 0 8px; }
.upload-mark {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #60a5fa 0%, #2563eb 100%);
  color: #fff;
  font-size: 22px;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.2);
}
.upload-main { font-size: 15px; font-weight: 700; color: #0f172a; }
.upload-sub { font-size: 12px; color: #94a3b8; text-align: center; }
.file-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid #e2ebf7;
  border-radius: 14px;
  background: #f8fbff;
}
.file-icon {
  width: 34px;
  height: 34px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: #fff;
  color: #2563eb;
  flex-shrink: 0;
}
.file-meta { min-width: 0; flex: 1; }
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #0f172a;
  font-weight: 600;
  font-size: 13px;
}
.file-note { margin-top: 2px; font-size: 12px; color: #94a3b8; }
</style>
