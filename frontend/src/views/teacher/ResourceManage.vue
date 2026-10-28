<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">教学资源</div>
        <div class="page-subtitle">思维导图/交互演示为平台预置页，文档支持上传 pdf / doc / docx（≤100MB），发布后学生课程内可见</div>
      </div>
    </div>

    <!-- 思维导图 / 交互演示（平台预置页引用） -->
    <el-card shadow="never" class="mb12 res-panel">
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
          <el-button
            v-if="resForm.path"
            link
            type="primary"
            :loading="presetPreviewing"
            @click="previewPreset"
          >
            <el-icon class="path-icon"><Link /></el-icon>
            预览该页面
          </el-button>
          <span v-if="resForm.path" class="form-tip">预置页：{{ resForm.path }}</span>
          <span v-else class="form-tip">页面为平台预置，选择后可先预览再添加</span>
        </el-form-item>
        <el-form-item label="资源标题">
          <el-input v-model="resForm.title" placeholder="留空默认取页面文件名" style="max-width: 420px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creating" @click="createResource">添加资源</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="presetResources" v-loading="loadingRes" size="small" class="compact-table">
        <el-table-column prop="title" label="标题" min-width="170" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'mindmap' ? 'primary' : 'success'" size="small">{{ row.kind_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="页面地址" width="150">
          <template #default="{ row }">
            <!-- 每条资源的访问链接唯一（按令牌）；点击经签名后新窗口打开 -->
            <el-link
              type="primary"
              :underline="false"
              :href="row.url"
              target="_blank"
              class="path-link res-url-link"
              :title="row.url"
              @click.prevent="openSignedPage(row)"
            >
              <el-icon class="path-icon"><Link /></el-icon>
              {{ shortToken(row.url) }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_published ? 'success' : 'info'" size="small">{{ row.is_published ? '已发布' : '未发布' }}</el-tag>
          </template>
        </el-table-column>
        <!-- 操作列：4 个按钮全部平铺（预览/发布/复制链接/删除），不再收进 ⋯ 下拉；列头居中 -->
        <el-table-column label="操作" width="330" fixed="right" header-align="center">
          <template #default="{ row }">
            <div class="op-cell">
              <el-button @click="previewResource(row)">预览</el-button>
              <el-button v-if="!row.is_published" type="success" @click="publishRes(row)">发布</el-button>
              <el-button v-else type="warning" @click="unpublishRes(row)">下架</el-button>
              <el-button @click="copyResourceLink(row)">复制链接</el-button>
              <el-button @click="removeRes(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loadingRes && !presetResources.length" class="table-empty">暂无预置资源，添加后显示在这里</div>
    </el-card>

    <!-- 文档资源（教师上传 pdf/doc/docx） -->
    <el-card shadow="never" class="res-panel">
      <template #header><span>文档资源</span></template>
      <el-form label-width="90px" style="max-width: 720px" class="mb12">
        <el-form-item label="文档文件" required>
          <input ref="docFileEl" type="file" accept=".pdf,.doc,.docx" @change="onDocPicked" />
          <span class="form-tip">支持 PDF / DOC / DOCX，单个不超过 100MB；PDF 学生端可直接预览，DOC/DOCX 下载查看</span>
        </el-form-item>
        <el-form-item label="资源标题" required>
          <el-input v-model="docForm.title" placeholder="例如：计算机网络复习大纲" style="max-width: 420px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="uploading" :disabled="!docForm.file" @click="uploadDocument">
            {{ uploading ? `上传中 ${uploadPercent}%` : '上传文档' }}
          </el-button>
        </el-form-item>
      </el-form>

      <el-table v-if="documentResources.length" :data="documentResources" v-loading="loadingRes" size="small" class="compact-table">
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="文件名" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.file_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="大小" width="96">
          <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_published ? 'success' : 'info'" size="small">{{ row.is_published ? '已发布' : '未发布' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right" header-align="center">
          <template #default="{ row }">
            <div class="op-cell">
              <el-button @click="previewResource(row)">{{ isPdf(row) ? '预览' : '下载' }}</el-button>
              <el-button v-if="!row.is_published" type="success" @click="publishRes(row)">发布</el-button>
              <el-button v-else type="warning" @click="unpublishRes(row)">下架</el-button>
              <el-button @click="copyResourceLink(row)">复制链接</el-button>
              <el-button @click="removeRes(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div v-else-if="!loadingRes" class="table-empty">暂无文档，上传后显示在这里</div>
    </el-card>
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
  signCourseResource, signPresetPage, uploadCourseDocument,
} from '@/api/course'
import { openTabDeferred } from '@/utils/open-tab'

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

const resForm = ref({ kind: 'mindmap', path: '', title: '' })
const availablePaths = computed(() => PRESET_PAGES.filter((p) => p.kind === resForm.value.kind))

const resources = ref([])
const loadingRes = ref(false)
const creating = ref(false)
const presetPreviewing = ref(false)

const docForm = ref({ file: null, title: '' })
const docFileEl = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)

const presetResources = computed(() => resources.value.filter((r) => r.kind !== 'document'))
const documentResources = computed(() => resources.value.filter((r) => r.kind === 'document'))

function presetTitle(path) {
  return PRESET_PAGES.find((p) => p.value === path)?.label || path
}

function isPdf(row) {
  return (row.file_name || '').toLowerCase().endsWith('.pdf')
}

// 页面地址列展示短令牌（完整 URL 在 title 提示与复制链接里）
function shortToken(url) {
  const token = (url || '').replace('/api/course-resources/page/', '').replace('/', '')
  return token.length > 8 ? `page/${token.slice(0, 8)}…` : `page/${token}`
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

async function createResource() {
  if (!resForm.value.path) {
    ElMessage.warning('请选择平台页面')
    return
  }
  creating.value = true
  try {
    await createCourseResource({
      course: courseId.value,
      kind: resForm.value.kind,
      title: resForm.value.title || presetTitle(resForm.value.path),
      path: resForm.value.path,
    })
    ElMessage.success('资源已添加')
    resForm.value.path = ''
    resForm.value.title = ''
    await loadResources()
  } catch { /* 响应拦截器已提示具体错误（如重复添加） */ }
  finally {
    creating.value = false
  }
}

async function previewResource(row) {
  // 先签发唯一签名 URL 再打开；文档类签发 file 地址（PDF 新窗口内联预览，doc/docx 触发下载）
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
    tab.open(signed.url)
    return
  }
  const hash = row.kind === 'mindmap' ? '#chapters-hidden' : ''
  router.push({
    name: 'course-resource-viewer',
    params: { id: courseId.value },
    query: {
      src: `${signed.url}${hash}`,
      title: row.title,
      kind: row.kind,
      back: 'course-resources',
    },
  })
}

// 页面地址列：签发后新窗口打开（每条资源链接唯一，未发布仅教师本人可签）
async function openSignedPage(row) {
  const tab = openTabDeferred()
  let signed
  try {
    signed = await signCourseResource(row.id)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '资源打开失败，请稍后重试')
    return
  }
  tab.open(signed.url)
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

// 添加资源前预览平台预置页（教师签发，无需资源行）
async function previewPreset() {
  if (!resForm.value.path) return
  presetPreviewing.value = true
  const tab = openTabDeferred()
  try {
    const signed = await signPresetPage(resForm.value.path)
    tab.open(signed.url)
  } catch (e) {
    tab.close()
    ElMessage.error(e?.message || '预览失败，请稍后重试')
  } finally {
    presetPreviewing.value = false
  }
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
  await ElMessageBox.confirm(
    `确认删除资源「${row.title}」？${row.kind === 'document' ? '上传的文件将一并删除，' : ''}不可恢复。`,
    '提示', { type: 'warning' },
  )
  await deleteCourseResource(row.id)
  await loadResources()
}

// ---- 文档上传 ----
const DOC_EXTS = ['.pdf', '.doc', '.docx']
const DOC_MAX_SIZE = 100 * 1024 * 1024

function onDocPicked(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!DOC_EXTS.includes(ext)) {
    ElMessage.error('仅支持 pdf / doc / docx 格式')
    docFileEl.value.value = ''
    return
  }
  if (file.size > DOC_MAX_SIZE) {
    ElMessage.error('文档不能超过 100MB')
    docFileEl.value.value = ''
    return
  }
  if (file.size === 0) {
    ElMessage.error('文档文件为空')
    docFileEl.value.value = ''
    return
  }
  docForm.value.file = file
  if (!docForm.value.title) docForm.value.title = file.name.replace(/\.[^.]+$/, '')
}

async function uploadDocument() {
  if (!docForm.value.file || !docForm.value.title.trim()) {
    ElMessage.warning('请选择文件并填写标题')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    await uploadCourseDocument({
      course: courseId.value,
      title: docForm.value.title.trim(),
      file: docForm.value.file,
      onProgress: (e) => {
        if (e.total) uploadPercent.value = Math.round((e.loaded / e.total) * 100)
      },
    })
    ElMessage.success('文档已上传')
    docForm.value = { file: null, title: '' }
    docFileEl.value.value = ''
    await loadResources()
  } catch { /* 响应拦截器已提示具体错误 */ }
  finally {
    uploading.value = false
  }
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
.mb12 { margin-bottom: 12px; }
.form-tip { color: #94a3b8; font-size: 12px; margin-left: 10px; }
.path-link { font-size: 12px; }
.path-icon { margin-right: 4px; vertical-align: -2px; }
.res-url-link { max-width: 100%; }
.res-url-link :deep(.el-link__inner) {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

/* 表格紧凑化：小尺寸 + 收紧单元格内边距，消除行内无效空白 */
.compact-table :deep(.el-table__cell) { padding: 7px 0; }
.compact-table :deep(.el-table__cell .cell) { line-height: 22px; }
/* 操作列单行：按钮间距收紧 + 不换行（按钮保持默认尺寸，不做二次收缩）
   注意：EP 主题有 .el-button + .el-button { margin-left: 12px }，会和 gap 叠加把按钮挤出列宽
   （删除按钮曾被裁掉 36px）——这里清零，间距只由 gap 控制 */
.op-cell { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.op-cell :deep(.el-button) { margin-left: 0; }
/* 空表紧凑占位（替代整张空表格，省掉表头+空块约 100px 空白） */
.table-empty {
  border: 1px dashed #dbe4f0;
  border-radius: 10px;
  padding: 14px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}
/* 表单留白收紧 */
.res-panel :deep(.el-form-item) { margin-bottom: 12px; }
.res-panel :deep(.el-form-item:last-child) { margin-bottom: 0; }
.res-panel :deep(.el-form) { margin-bottom: 10px; }
/* 卡片留白收紧 */
.res-panel :deep(.el-card__header) { padding: 10px 16px; }
.res-panel :deep(.el-card__body) { padding: 12px 16px 12px; }
</style>
