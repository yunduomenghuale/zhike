<template>
  <div class="page-container materials-page">
    <div v-loading="loading" class="materials-list course-standard-list">
      <article v-for="item in materials" :key="item.id" class="material-row course-standard-row">
        <div class="material-left">
          <div class="file-badge">
            <el-icon><Document /></el-icon>
          </div>
          <div class="material-main">
            <div class="material-title">{{ item.file_name }}</div>
            <div class="material-meta">
              <span>{{ (item.file_type || '文件').toUpperCase() }}</span>
              <span :class="['qa-pill', item.qa_open ? 'open' : 'closed']">
                {{ item.qa_open ? '已接入 AI 助教' : '未开放问答' }}
              </span>
            </div>
          </div>
        </div>
        <div v-if="item.file" class="material-actions course-standard-actions">
          <button
            v-if="canPreview(item)"
            type="button"
            class="open-btn course-standard-action-btn"
            @click="openPreview(item)"
          >
            在线查看
          </button>
          <button
            type="button"
            class="open-btn course-standard-action-btn"
            :disabled="downloadingId === item.id"
            @click="download(item)"
          >
            {{ downloadingId === item.id ? '下载中…' : '下载' }}
          </button>
        </div>
      </article>

      <el-empty v-if="!loading && !materials.length" description="暂无课程资料">
        <template #description>
          <div class="empty-title">暂无课程资料</div>
          <div class="empty-tip">老师上传并解析资料后，会显示在这里。</div>
        </template>
      </el-empty>
    </div>

    <el-dialog
      v-model="previewVisible"
      :title="previewName"
      width="860px"
      top="4vh"
      destroy-on-close
      class="material-preview-dialog"
    >
      <div v-if="previewLoading" class="preview-state">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在加载预览…（Word/PPT 首次转换约需几十秒）</span>
      </div>
      <div v-else-if="previewError" class="preview-state is-error">
        <span>{{ previewError }}</span>
      </div>
      <div v-else-if="previewText !== null" class="preview-text-wrap">
        <pre class="preview-text">{{ previewText }}</pre>
      </div>
      <div v-else class="preview-scroll">
        <div v-for="(page, index) in previewPages" :key="page" class="preview-page">
          <img :src="page" loading="lazy" class="preview-page-img" :alt="`第 ${index + 1} 页`" />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Document, Loading } from '@element-plus/icons-vue'
import { downloadMaterial, listMaterials, previewMaterial } from '@/api/knowledge'

const route = useRoute()
const courseId = computed(() => Number(route.params.id) || null)
const loading = ref(false)
const materials = ref([])

// 支持在线预览的类型（与后端 PREVIEWABLE_EXTENSIONS + txt 一致）
const PREVIEWABLE_EXTENSIONS = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.txt']

function canPreview(item) {
  const name = (item.file_name || '').toLowerCase()
  return PREVIEWABLE_EXTENSIONS.some((ext) => name.endsWith(ext))
}

// ---- 在线查看（弹窗滚动预览）----
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewPages = ref([])
const previewText = ref(null)
const previewName = ref('')

async function openPreview(item) {
  previewVisible.value = true
  previewLoading.value = true
  previewError.value = ''
  previewPages.value = []
  previewText.value = null
  previewName.value = item.file_name || '资料预览'
  try {
    const data = await previewMaterial(item.id)
    if (data?.kind === 'text') {
      previewText.value = data.text || '（空文件）'
    } else if (data?.pages?.length) {
      previewPages.value = data.pages
    } else {
      previewError.value = '预览失败，请下载后查看'
    }
  } catch (error) {
    previewError.value = (await extractErrorMessage(error)) || '在线预览加载失败，请下载后查看'
  } finally {
    previewLoading.value = false
  }
}

// ---- 下载（blob 保存，还原原始文件名）----
const downloadingId = ref(null)

async function download(item) {
  if (downloadingId.value) return
  downloadingId.value = item.id
  try {
    const blob = await downloadMaterial(item.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = item.file_name || '课程资料'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch {
    // 拦截器已统一提示错误
  } finally {
    downloadingId.value = null
  }
}

// blob 错误响应里取出后端 message（预览接口的 ValidationError 提示更有用）
async function extractErrorMessage(error) {
  const data = error?.response?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text())
      if (parsed?.message) return parsed.message
    } catch {
      /* 忽略解析失败 */
    }
  }
  return error?.message || ''
}

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const data = await listMaterials({ course: courseId.value })
    materials.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

watch(courseId, load)
onMounted(load)
</script>

<style scoped>
.materials-list {
  display: grid;
}

.material-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.material-left {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-badge {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: #2563eb;
  background: #eff6ff;
  font-size: 17px;
}

.material-main {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 12px;
}

.material-title {
  max-width: 420px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.material-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #64748b;
  font-size: 12.5px;
}

.qa-pill {
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-weight: 700;
}

.qa-pill.open {
  color: #2563eb;
  background: #eff6ff;
}

.qa-pill.closed {
  color: #64748b;
  background: #f1f5f9;
}

.open-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.open-btn:hover {
  background: #fff;
  box-shadow: var(--shadow-xs);
}

.open-btn:disabled {
  color: #94a3b8;
  cursor: not-allowed;
  box-shadow: none;
}

.material-actions {
  display: flex;
  align-items: center;
}

/* 两个按钮分开：全局 .course-standard-actions 是共享灰底的连体容器，容易看成一个按钮 */
.material-actions.course-standard-actions {
  gap: 10px;
  padding: 0;
  background: transparent;
}

.material-actions .open-btn {
  height: 30px;
  padding: 0 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.material-actions .open-btn:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
  box-shadow: none;
}

/* ---- 在线预览弹窗（与作业附件 PdfScrollPreview 同款滚动图览） ---- */
.preview-scroll {
  max-height: 72vh;
  overflow-y: auto;
  overflow-x: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f1f5f9;
  scrollbar-width: thin;
}

.preview-page {
  display: flex;
  justify-content: center;
  padding: 10px 0;
  background: #f1f5f9;
}

.preview-page + .preview-page {
  border-top: 1px solid #e2e8f0;
}

.preview-page-img {
  display: block;
  width: 100%;
  max-width: 760px;
  height: auto;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08);
}

.preview-text-wrap {
  max-height: 72vh;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  padding: 18px 20px;
  scrollbar-width: thin;
}

.preview-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #0f172a;
  font-size: 14px;
  line-height: 1.8;
}

.preview-state {
  min-height: 180px;
  border: 1px dashed #bfdbfe;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #64748b;
  background: #f8fbff;
  font-size: 13px;
}

.preview-state .el-icon {
  color: #2563eb;
  font-size: 20px;
}

.preview-state.is-error {
  border-color: #fed7aa;
  color: #9a3412;
  background: #fff7ed;
}

.empty-title {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 4px;
}

.empty-tip {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 720px) {
  .material-row {
    align-items: stretch;
    flex-direction: column;
  }

  .material-left {
    align-items: flex-start;
  }

  .material-main {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
