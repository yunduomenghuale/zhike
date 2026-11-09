<template>
  <div class="lab-page-uploader">
    <!-- 当前生效页面（教师反馈：预览的是当前生效页面，信息卡置顶） -->
    <div v-if="page" class="page-active-card">
      <el-icon class="page-active-icon"><Document /></el-icon>
      <span class="page-active-name" :title="page.name">{{ page.name || '当前实验页面' }}</span>
      <el-button size="small" text type="primary" :disabled="uploading" @click="preview">预览当前生效页面</el-button>
    </div>

    <el-upload
      drag
      :show-file-list="false"
      :before-upload="onHtmlPicked"
      :accept="'.html,.htm'"
      :disabled="disabled || uploading"
      class="lab-html-upload"
    >
      <div class="upload-inner">
        <div class="upload-mark">
          <el-icon><UploadFilled /></el-icon>
        </div>
        <div class="upload-main">
          {{ page ? '拖入或选择 HTML 文件，将覆盖当前页面' : '拖入或选择 HTML 文件' }}
        </div>
        <div class="upload-sub">
          单个 .html 文件，不超过 50MB；JS / CSS / 图片须全部内联
          <template v-if="page">；选择后<b>立即上传并覆盖</b></template>
        </div>
      </div>
    </el-upload>

    <!-- 已选择待上传文件（新建弹窗场景暂存；已有实验则选择后立即自动上传） -->
    <div v-if="modelValue && !uploading" class="file-status">
      <el-icon><Document /></el-icon>
      <span class="file-name" :title="modelValue.name">{{ modelValue.name }}</span>
      <span class="file-size">{{ fmtSize(modelValue.size) }}</span>
      <el-tag v-if="page" size="small" type="warning" effect="plain" class="overwrite-tag">将覆盖当前生效页面</el-tag>
    </div>

    <!-- S8 静态扫描命中：展示命中项，由教师显式二次确认后才落库 -->
    <el-alert
      v-if="needConfirm"
      type="warning"
      :closable="false"
      show-icon
      title="页面源码命中安全扫描规则"
      class="scan-alert"
    >
      <template #default>
        <div class="scan-hits">{{ hits.join('、') }}</div>
        <div class="scan-tip">确认源码无误后点「确认继续上传」；上传后会通知平台管理员复核。</div>
      </template>
    </el-alert>

    <!-- 上传进度（教师反馈第 7 条：中间过程可见） -->
    <div v-if="uploading" class="progress-row">
      <el-progress :percentage="percent" :stroke-width="10" />
      <div class="progress-tip">正在上传并覆盖{{ page ? '当前页面' : '' }} {{ modelValue?.name || '' }}…</div>
    </div>

    <div v-if="needConfirm" class="uploader-actions">
      <el-button type="warning" size="small" :loading="uploading" @click="submit(true)">确认继续上传</el-button>
    </div>
    <span v-if="!labId && modelValue" class="picked-tip">已选择，创建实验时将一并上传</span>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Document } from '@element-plus/icons-vue'
import { uploadLabPage, previewLabPage } from '@/api/labs'

const props = defineProps({
  // 已有实验：选择文件后立即上传/覆盖；为空表示新建弹窗内暂存文件，由父组件创建后再传
  labId: { type: [Number, String], default: null },
  modelValue: { type: Object, default: null },
  page: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'uploaded', 'changed'])

const uploading = ref(false)
const needConfirm = ref(false)
const hits = ref([])
const percent = ref(0)

function fmtSize(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function onHtmlPicked(file) {
  const ext = String(file.name || '').toLowerCase().split('.').pop()
  if (ext !== 'html' && ext !== 'htm') {
    ElMessage.warning('仅支持单个 .html 文件')
    return false
  }
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.warning('页面文件不能超过 50MB')
    return false
  }
  if (!file.size) {
    ElMessage.warning('文件为空')
    return false
  }
  emit('update:modelValue', file)
  needConfirm.value = false
  hits.value = []
  // 教师反馈：已有实验时选择文件后直接上传，不再需要点「上传并覆盖页面」按钮
  if (props.labId) submit(false)
  return false // 阻止 el-upload 自动上传，统一由 submit() 显式提交
}

async function submit(force) {
  if (!props.modelValue || !props.labId) return
  uploading.value = true
  percent.value = 0
  try {
    const res = await uploadLabPage(props.labId, props.modelValue, Boolean(force || needConfirm.value), (e) => {
      if (e.total) percent.value = Math.round((e.loaded / e.total) * 100)
    })
    needConfirm.value = false
    hits.value = []
    emit('update:modelValue', null)
    emit('uploaded', res)
    ElMessage.success(page?.name ? '新页面已上传并覆盖当前页面' : '实验页面已保存')
  } catch (e) {
    const body = e?.response?.data
    if (body?.require_confirm) {
      needConfirm.value = true
      hits.value = body.hits || []
      ElMessage.warning(body.message || '页面源码命中安全扫描规则，请确认后重试')
    } else {
      ElMessage.error(body?.message || e?.message || '页面上传失败')
    }
  } finally {
    uploading.value = false
  }
}

async function preview() {
  try {
    const data = await previewLabPage(props.labId)
    const url = data?.url
    if (!url) return ElMessage.warning('预览链接生成失败')
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch (e) {
    ElMessage.error(e?.message || '预览失败')
  }
}
</script>

<style scoped>
.page-active-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  margin-bottom: 10px;
  font-size: 13px;
  color: #334155;
}
.page-active-icon { color: #10b981; font-size: 16px; }
.page-active-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.upload-inner { padding: 14px 8px; text-align: center; }
.upload-mark { font-size: 30px; color: #409eff; line-height: 1.2; }
.upload-main { margin-top: 6px; font-size: 14px; color: #334155; font-weight: 600; }
.upload-sub { margin-top: 4px; font-size: 12px; color: #94a3b8; }
.upload-sub b { color: #d97706; }
.file-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13px;
  color: #475569;
}
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { color: #94a3b8; font-size: 12px; }
.overwrite-tag { margin-left: 8px; flex-shrink: 0; }
.scan-alert { margin-top: 10px; }
.progress-row { margin-top: 10px; }
.progress-tip { margin-top: 4px; font-size: 12px; color: #64748b; }
.scan-hits { font-weight: 600; line-height: 1.7; }
.scan-tip { margin-top: 4px; font-size: 12px; }
.uploader-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.uploader-actions :deep(.el-button + .el-button) { margin-left: 0; }
.picked-tip { font-size: 12px; color: #94a3b8; }
</style>
