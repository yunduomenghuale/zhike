<template>
  <div class="page-container">
    <el-card shadow="never" class="data-card kb-card">
      <div class="kb-toolbar">
        <div class="kb-toolbar-left">
          <el-select
            v-if="!inCourseWorkspace"
            v-model="courseId"
            size="large"
            placeholder="请选择课程"
            style="width: 240px"
            @change="onCourseChange"
          >
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
        <div class="kb-toolbar-actions">
          <el-select
            v-if="courseId"
            v-model="uploadCatalogId"
            class="kb-catalog-filter"
            clearable
            placeholder="归属章节（可选）"
          >
            <el-option v-for="c in catalogs" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
          <el-button v-if="courseId" :icon="Brush" @click="openRebuild">重建向量</el-button>
          <el-upload
            v-if="courseId"
            :show-file-list="false"
            :before-upload="handleUpload"
            accept=".pdf,.doc,.docx,.ppt,.pptx,.txt,.md"
          >
            <el-button class="kb-upload-btn" type="primary" :icon="UploadFilled" :loading="uploading">
              上传教辅资料
            </el-button>
          </el-upload>
        </div>
      </div>

      <el-empty v-if="!courseId" :image-size="110">
        <template #description>
          <div class="empty-text">请先选择课程</div>
          <div class="empty-tip">选择课程后即可上传资料并管理知识库</div>
        </template>
      </el-empty>

      <template v-else>
        <TableSkeleton v-if="loadingMaterials" :cols="6" />
        <el-empty v-else-if="!materials.length" :image-size="110">
          <template #description>
            <div class="empty-text">还没有教辅资料</div>
            <div class="empty-tip">点击右上角「上传教辅资料」开始构建知识库</div>
          </template>
        </el-empty>
        <div v-else class="kb-list animate-list">
          <div v-for="m in materials" :key="m.id" class="kb-row">
            <div class="kb-row-left">
              <span class="kb-file-icon" :class="'ext-' + (m.file_type || 'file')">
                <el-icon><Document /></el-icon>
              </span>
              <div class="kb-row-copy">
                <div class="kb-row-title-line">
                  <span class="kb-row-title">{{ m.file_name }}</span>
                  <el-tag size="small" effect="plain" round>{{ (m.file_type || '文件').toUpperCase() }}</el-tag>
                  <el-tag :type="statusType(m.parse_status)" size="small" effect="light" round>
                    {{ m.parse_status_display }}
                  </el-tag>
                  <el-tag size="small" type="info" effect="plain" round>{{ m.chunk_count || 0 }} 片段</el-tag>
                </div>
                <div class="kb-row-sub">
                  <span class="kb-sub-label">归属章节</span>
                  <el-select
                    :model-value="m.catalog || null"
                    size="small"
                    clearable
                    placeholder="未关联章节"
                    class="kb-catalog-select"
                    @change="(val) => changeCatalog(m, val)"
                  >
                    <el-option v-for="c in catalogs" :key="c.id" :label="c.title" :value="c.id" />
                  </el-select>
                </div>
              </div>
            </div>
            <div class="kb-row-actions">
              <div class="kb-action-group">
                <a
                  v-if="m.file"
                  class="kb-action-btn"
                  :href="m.file"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <el-icon><View /></el-icon> 查看资料
                </a>
                <button class="kb-action-btn" @click="reparse(m)">
                  <el-icon><Refresh /></el-icon> 重新解析
                </button>
                <button class="kb-action-btn danger" @click="openDelete(m)">
                  <el-icon><Delete /></el-icon> 删除
                </button>
              </div>
              <div class="kb-manage-group">
                <span class="kb-switch-label">学生提问</span>
                <el-switch :model-value="m.qa_open" @change="() => toggle(m)" />
              </div>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除资料"
      :item-name="deleteTarget?.file_name || deleteTarget?.title || deleteTarget?.name"
      description="删除后，该资料及其解析内容将无法继续访问，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <el-dialog v-model="rebuildDialog.visible" title="重建知识库向量" width="600px" append-to-body>
      <div v-if="rebuildDialog.loading" class="rebuild-running">
        <el-icon class="is-loading"><Loading /></el-icon>
        <div>
          <p class="rebuild-running-title">正在重建向量…</p>
          <p class="rebuild-running-tip">用当前向量模型重新计算资料与课件的全部向量片段，内容多时需要几分钟，请勿关闭页面。</p>
        </div>
      </div>
      <template v-else-if="rebuildDialog.report">
        <el-result
          :icon="rebuildDialog.report.failed.length ? 'warning' : 'success'"
          :title="rebuildDialog.report.failed.length ? '部分内容重建失败' : '重建完成'"
        >
          <template #sub-title>
            资料 {{ rebuildDialog.report.materials.success }}/{{ rebuildDialog.report.materials.total }} 份，
            课件 {{ rebuildDialog.report.ppts.success }}/{{ rebuildDialog.report.ppts.total }} 部，
            共 {{ rebuildDialog.report.chunks }} 个片段；向量模型
            {{ rebuildDialog.report.model || rebuildDialog.report.provider }}（{{ rebuildDialog.report.dimension }} 维）
          </template>
        </el-result>
        <div v-if="rebuildDialog.report.failed.length" class="rebuild-failed">
          <p class="rebuild-failed-title">失败清单（旧向量已保留，修复后可逐项重试）：</p>
          <div
            v-for="item in rebuildDialog.report.failed"
            :key="item.kind + (item.material_id || item.ppt_id)"
            class="rebuild-failed-row"
          >
            <el-tag size="small" :type="item.kind === 'ppt' ? 'warning' : 'info'" disable-transitions>
              {{ item.kind === 'ppt' ? '课件' : '资料' }}
            </el-tag>
            <span class="rebuild-failed-name" :title="item.file_name">{{ item.file_name }}</span>
            <span class="rebuild-failed-reason">{{ item.reason }}</span>
            <el-button size="small" :loading="item.retrying" @click="retryMaterial(item)">重试</el-button>
          </div>
        </div>
      </template>
      <div v-else-if="rebuildDialog.error" class="rebuild-error">
        <el-result icon="error" title="重建未执行" :sub-title="rebuildDialog.error" />
        <p class="rebuild-error-tip">如为向量模型问题，请让平台管理员在「大模型配置 · 向量化」中检查模型与连接。</p>
      </div>
      <template #footer><el-button @click="rebuildDialog.visible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  UploadFilled, Refresh, Delete, Document, View, Brush, Loading,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listCourses, listCatalogs } from '@/api/course'
import {
  listMaterials, uploadMaterial, updateMaterial, reparseMaterial, toggleQa, deleteMaterial, rebuildVectors,
} from '@/api/knowledge'

const courses = ref([])
const courseId = ref(null)
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const inCourseWorkspace = computed(() => Boolean(fixedCourseId.value))

const materials = ref([])
const catalogs = ref([])
const uploadCatalogId = ref(null)
const loadingMaterials = ref(false)
const uploading = ref(false)
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)
// 重建向量对话框：loading=重建中；report=结果报告；error=事前校验失败（未执行）
const rebuildDialog = reactive({ visible: false, loading: false, report: null, error: '' })

function statusType(s) {
  return { done: 'success', failed: 'danger', parsing: 'warning', pending: 'info' }[s] || 'info'
}

async function loadCourses() {
  if (fixedCourseId.value) {
    courseId.value = fixedCourseId.value
    onCourseChange()
    return
  }
  const data = await listCourses()
  courses.value = data.results ?? data
  if (courses.value.length && !courseId.value) {
    courseId.value = courses.value[0].id
    onCourseChange()
  }
}

async function loadMaterials() {
  if (!courseId.value) return
  loadingMaterials.value = true
  try {
    const data = await listMaterials({ course: courseId.value })
    materials.value = data.results ?? data
  } finally {
    loadingMaterials.value = false
  }
}

async function loadCatalogs() {
  if (!courseId.value) {
    catalogs.value = []
    return
  }
  const data = await listCatalogs({ course: courseId.value })
  catalogs.value = data.results ?? data
}

function onCourseChange() {
  uploadCatalogId.value = null
  loadMaterials()
  loadCatalogs()
}

async function handleUpload(file) {
  uploading.value = true
  try {
    await uploadMaterial({ course: courseId.value, catalog: uploadCatalogId.value, file })
    ElMessage.success('上传并入库成功')
    loadMaterials()
  } finally {
    uploading.value = false
  }
  return false
}

async function changeCatalog(row, catalogId) {
  await updateMaterial(row.id, { catalog: catalogId || null })
  row.catalog = catalogId || null
  const cat = catalogs.value.find((c) => c.id === catalogId)
  row.catalog_title = cat?.title || ''
  ElMessage.success(catalogId ? `已关联到「${cat?.title}」` : '已取消章节关联')
}

async function reparse(row) {
  const res = await reparseMaterial(row.id)
  ElMessage.success(`已重新入库，共 ${res.chunk_count} 个片段`)
  loadMaterials()
}

async function toggle(row) {
  await toggleQa(row.id)
  ElMessage.success('已更新开放状态')
  loadMaterials()
}

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteMaterial(deleteTarget.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    await loadMaterials()
  } finally {
    deleting.value = false
  }
}

// ===== 重建向量（换向量模型后必须执行，否则旧向量与新模型不兼容、检索静默失效）=====
async function openRebuild() {
  try {
    await ElMessageBox.confirm(
      '将用当前生效的向量模型重新计算本课程全部资料的向量，旧向量会被覆盖。' +
      '耗时取决于资料量与模型速度（本地模型可能较久），期间请勿关闭页面。确定继续？',
      '重建知识库向量',
      { type: 'warning', confirmButtonText: '开始重建', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  rebuildDialog.visible = true
  rebuildDialog.loading = true
  rebuildDialog.report = null
  rebuildDialog.error = ''
  try {
    rebuildDialog.report = await rebuildVectors({ course: courseId.value })
    loadMaterials()
  } catch (err) {
    // 拦截器已将 {code,message} 转为 Error(message)：400 的 message 即事前校验失败原因
    rebuildDialog.error = err?.message || '重建失败，请稍后重试'
  } finally {
    rebuildDialog.loading = false
  }
}

async function retryMaterial(item) {
  item.retrying = true
  const isPpt = item.kind === 'ppt'
  try {
    const res = await rebuildVectors(isPpt ? { ppt: item.ppt_id } : { material: item.material_id })
    if (res.failed && res.failed.length) {
      item.reason = res.failed[0].reason
      ElMessage.error(`仍然失败：${res.failed[0].reason}`)
    } else {
      rebuildDialog.report.failed = rebuildDialog.report.failed.filter(
        (f) => isPpt ? f.ppt_id !== item.ppt_id : f.material_id !== item.material_id,
      )
      const group = isPpt ? rebuildDialog.report.ppts : rebuildDialog.report.materials
      group.success += 1
      rebuildDialog.report.success += 1
      rebuildDialog.report.chunks += res.chunks || 0
      ElMessage.success(isPpt ? '该课件重建成功' : '该资料重建成功')
      loadMaterials()
    }
  } catch (err) {
    ElMessage.error(err?.message || '重试失败')
  } finally {
    item.retrying = false
  }
}

onMounted(loadCourses)
</script>

<style scoped>
/* 透明容器（与目录页一致：无边框/无阴影/无内边距） */
.kb-card {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.kb-card:hover {
  box-shadow: none;
}
.kb-card :deep(.el-card__body) {
  padding: 0;
}

/* 工具栏：右对齐 + 下划分隔线（与目录页 catalog-toolbar 一致） */
.kb-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 0 0 12px;
  margin-bottom: 12px;
}
.kb-toolbar-left,
.kb-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.kb-upload-btn {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.kb-upload-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.2);
}

/* 上传区章节选择 + 行内章节设置 */
.kb-catalog-filter {
  width: 200px;
}

.kb-row-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.kb-sub-label {
  color: var(--gray-400, #94a3b8);
  font-size: 12px;
  flex-shrink: 0;
}

.kb-catalog-select {
  width: 180px;
}

/* 资料行卡片列表 */
.kb-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.kb-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.kb-row:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.kb-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.kb-file-icon {
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  font-size: 20px;
  color: var(--primary-600);
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: transform 0.18s ease;
}
.kb-row:hover .kb-file-icon {
  transform: scale(1.05);
}
.kb-file-icon.ext-pdf { color: #ef4444; background: linear-gradient(145deg, #fef2f2, #fff); }
.kb-file-icon.ext-ppt { color: #ea580c; background: linear-gradient(145deg, #fff7ed, #fff); }
.kb-file-icon.ext-word { color: #2563eb; background: linear-gradient(145deg, #eff6ff, #fff); }
.kb-file-icon.ext-txt,
.kb-file-icon.ext-md { color: #0891b2; background: linear-gradient(145deg, #ecfeff, #fff); }
.kb-row-copy {
  min-width: 0;
}
.kb-row-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.kb-row-title {
  max-width: 380px;
  font-size: 15px;
  font-weight: 650;
  color: var(--gray-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-row-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}
.kb-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.kb-action-btn {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-600);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
}
.kb-action-btn:hover {
  background: #fff;
  box-shadow: var(--shadow-xs);
}
.kb-action-btn.danger {
  color: var(--danger);
}
.kb-manage-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 14px;
  border-left: 1px solid var(--gray-200);
}
.kb-switch-label {
  font-size: 13px;
  color: var(--gray-500);
}

/* 重建向量对话框 */
.rebuild-running {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 18px 4px 8px;
}
.rebuild-running .el-icon {
  font-size: 26px;
  color: var(--primary-600);
  margin-top: 2px;
}
.rebuild-running-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 650;
  color: var(--gray-900);
}
.rebuild-running-tip {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--gray-500);
}
.rebuild-failed {
  margin-top: 4px;
  border: 1px solid #fde68a;
  border-radius: 12px;
  background: #fffbeb;
  padding: 12px 14px;
}
.rebuild-failed-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 650;
  color: #b45309;
}
.rebuild-failed-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px dashed #fde68a;
  font-size: 13px;
}
.rebuild-failed-row:first-of-type {
  border-top: 0;
}
.rebuild-failed-name {
  flex: 0 0 200px;
  font-weight: 600;
  color: var(--gray-800);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rebuild-failed-reason {
  flex: 1;
  min-width: 0;
  color: var(--gray-500);
  word-break: break-all;
}
.rebuild-error-tip {
  margin: 0;
  text-align: center;
  font-size: 13px;
  color: var(--gray-500);
}

@media (max-width: 768px) {
  .kb-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .kb-row-actions {
    justify-content: space-between;
  }
}
</style>
