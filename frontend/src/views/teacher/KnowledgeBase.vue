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
        <div v-else class="kb-list">
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
              </div>
            </div>
            <div class="kb-row-actions">
              <div class="kb-action-group">
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  UploadFilled, Refresh, Delete, Document,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import { listCourses } from '@/api/course'
import {
  listMaterials, uploadMaterial, reparseMaterial, toggleQa, deleteMaterial,
} from '@/api/knowledge'

const courses = ref([])
const courseId = ref(null)
const route = useRoute()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const inCourseWorkspace = computed(() => Boolean(fixedCourseId.value))

const materials = ref([])
const loadingMaterials = ref(false)
const uploading = ref(false)
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

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

function onCourseChange() {
  loadMaterials()
}

async function handleUpload(file) {
  uploading.value = true
  try {
    await uploadMaterial({ course: courseId.value, file })
    ElMessage.success('上传并入库成功')
    loadMaterials()
  } finally {
    uploading.value = false
  }
  return false
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

/* 深色模式 */
html.dark .kb-title-text { color: #f1f5f9; }
html.dark .kb-row {
  background: #1e293b;
  border-color: #334155;
}
html.dark .kb-row-title { color: #f1f5f9; }
html.dark .kb-action-group { background: #0f172a; }
html.dark .kb-action-btn:hover { background: #334155; }
html.dark .kb-manage-group { border-left-color: #334155; }
html.dark .kb-file-icon {
  background: #0f172a;
}
</style>
