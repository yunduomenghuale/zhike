<template>
  <!--
    文档导入弹窗：上传题目文档 → 后端规则解析 → 建草稿批次。
    导入成功后由父层打开 QuestionDraftPreview 预览编辑入库。
  -->
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => emit('update:visible', v)"
    width="560px"
    align-center
    class="import-dialog"
    :show-close="false"
    :close-on-click-modal="false"
  >
    <template #header>
      <div class="creation-dialog-header">
        <span class="creation-dialog-icon import-create-icon"><el-icon><UploadFilled /></el-icon></span>
        <div class="creation-dialog-heading">
          <div class="creation-dialog-title">导入题目文档</div>
          <div class="creation-dialog-subtitle">上传文档，系统解析为可编辑的题目草稿</div>
        </div>
        <el-button text circle class="creation-dialog-close" :icon="Close" @click="emit('update:visible', false)" />
      </div>
    </template>

    <div class="import-body">
      <!-- 课程上下文：导入操作已在某课程下，自动关联无需选择（原「目标课程」字段已移除） -->
      <div class="import-course-hint">
        <el-icon><School /></el-icon>
        <span>导入到课程：<b>{{ courseName || '当前课程' }}</b>（自动关联当前课程）</span>
      </div>
      <el-form label-position="top" class="import-form">
        <el-form-item label="目标章节（可选）">
          <el-select v-model="catalog" class="module-select" popper-class="module-select-popper" placeholder="可稍后在预览中设置，不影响解析" style="width: 100%" clearable>
            <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="题目文件">
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            :on-exceed="onExceed"
            accept=".pdf,.doc,.docx,.txt,.md"
            class="import-uploader"
          >
            <el-icon class="import-uploader-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
            <template #tip>
              <div class="import-uploader-tip">
                支持 pdf / doc / docx / txt / md，单个文件不超过 10MB。<br />
                建议文档包含题号、选项、答案等结构（如「1. 题干 / A. 选项 / 答案：A」）。
              </div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <div class="import-hint">
        <el-icon class="import-hint-icon"><InfoFilled /></el-icon>
        <span>解析为<b>草稿</b>后可在预览中逐题编辑、核对告警，确认后再批量入库；上传文件在题目入库后自动删除。</span>
      </div>
    </div>

    <template #footer>
      <div class="creation-dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button class="q-btn-primary" type="primary" :icon="UploadFilled" :loading="parsing" :disabled="!file" @click="doImport">
          解析并预览
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, InfoFilled, School, UploadFilled } from '@element-plus/icons-vue'
import { importQuestions } from '@/api/question'

const SUPPORTED_EXT = ['.pdf', '.doc', '.docx', '.txt', '.md']
const MAX_SIZE = 10 * 1024 * 1024

const props = defineProps({
  visible: { type: Boolean, default: false },
  courseId: { type: [Number, String], default: null },
  courseName: { type: String, default: '' },
  catalogs: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'imported'])

const uploadRef = ref(null)
const file = ref(null)
const catalog = ref(null)
const parsing = ref(false)

watch(() => props.visible, (v) => {
  if (v) {
    file.value = null
    catalog.value = null
    uploadRef.value?.clearFiles()
  }
})

function onFileChange(uploadFile) {
  const raw = uploadFile.raw
  if (!raw) return
  const ext = '.' + (raw.name.split('.').pop() || '').toLowerCase()
  if (!SUPPORTED_EXT.includes(ext)) {
    ElMessage.warning(`暂不支持该文件格式，支持：${SUPPORTED_EXT.join(' / ')}`)
    uploadRef.value?.clearFiles()
    file.value = null
    return
  }
  if (raw.size > MAX_SIZE) {
    ElMessage.warning('文件超过 10MB 上限，请压缩或拆分后重试')
    uploadRef.value?.clearFiles()
    file.value = null
    return
  }
  file.value = raw
}
function onFileRemove() {
  file.value = null
}
function onExceed() {
  ElMessage.warning('一次只能导入一个文件，请先移除已选文件')
  uploadRef.value?.clearFiles()
  file.value = null
}

async function doImport() {
  if (!file.value) return ElMessage.warning('请先选择题目文件')
  if (!props.courseId) return ElMessage.warning('请先选择课程')
  const form = new FormData()
  form.append('file', file.value)
  form.append('course', props.courseId)
  if (catalog.value) form.append('catalog', catalog.value)
  parsing.value = true
  try {
    const batch = await importQuestions(form)
    ElMessage.success(`已识别 ${batch.drafts?.length || 0} 道题目，请预览编辑后入库`)
    emit('imported', batch)
    emit('update:visible', false)
  } catch {
    // 错误消息由 request 拦截器统一提示
  } finally {
    parsing.value = false
  }
}
</script>

<style scoped>
.import-dialog :deep(.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.import-dialog :deep(.el-dialog__header) {
  margin: 0;
  padding: 0;
}
.import-dialog :deep(.el-dialog__body) {
  padding: 0;
}
.import-dialog :deep(.el-dialog__footer) {
  padding: 0;
}

.import-body {
  padding: 16px 22px 18px;
}
.import-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.import-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

/* 课程提示行（导入到课程，自动关联） */
.import-course-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
  padding: 9px 13px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #475569;
  font-size: 13px;
}
.import-course-hint b {
  color: #0f172a;
  font-weight: 700;
}
.import-course-hint .el-icon {
  flex: 0 0 auto;
  font-size: 15px;
  color: var(--primary-600);
}

.import-uploader {
  width: 100%;
}
.import-uploader :deep(.el-upload-dragger) {
  width: 100%;
  padding: 22px 16px;
  border: 1.5px dashed #c7d7ee;
  border-radius: 14px;
  background: #f8fbff;
}
.import-uploader-icon {
  font-size: 30px;
  color: var(--primary-500);
}
.import-uploader-tip {
  margin-top: 6px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.6;
}

.import-hint {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 14px;
  padding: 11px 14px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.9), rgba(219, 234, 254, 0.5));
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.6;
}
.import-hint b { color: var(--primary-700); font-weight: 700; }
.import-hint-icon { flex: 0 0 auto; font-size: 17px; color: var(--primary-600); margin-top: 2px; }

.import-create-icon {
  color: #fff;
  background: linear-gradient(140deg, #34d399, #059669);
  box-shadow: 0 10px 20px rgba(5, 150, 105, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 66px;
  padding: 15px 22px 13px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}
.creation-dialog-icon {
  width: 38px;
  height: 38px;
  display: grid;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  font-size: 18px;
}
.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}
.creation-dialog-title {
  color: #0f172a;
  font-size: 18px;
  font-weight: 760;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12.5px;
  line-height: 1.3;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 22px 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}
.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}
.q-btn-primary {
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 12px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}
</style>
