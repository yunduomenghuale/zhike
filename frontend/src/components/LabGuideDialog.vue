<template>
  <el-dialog
    v-model="visible"
    :title="isTeacherView ? '实验必读管理' : (guide.title || '实验必读')"
    width="860"
    top="4vh"
    destroy-on-close
    @closed="mode = 'view'"
  >
    <!-- 只读浏览（学生 / 教师浏览态） -->
    <div v-if="mode === 'view'" v-loading="loading" class="guide-view">
      <div class="guide-render" v-html="guide.content" />
    </div>

    <!-- 教师编辑态 -->
    <div v-else-if="mode === 'edit'" class="guide-edit">
      <el-form label-width="70px">
        <el-form-item label="标题">
          <el-input v-model="editForm.title" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="内容">
          <el-input
            v-model="editForm.content"
            type="textarea"
            :rows="18"
            placeholder="支持 HTML（含内联 style，样式在 .lab-guide-doc 作用域内生效）。留空保存 = 展示平台预设内容"
          />
        </el-form-item>
      </el-form>
      <div class="edit-tip">提示：内容留空保存即恢复展示平台预设；也可点"恢复预设"一键还原。</div>
    </div>

    <template #footer>
      <template v-if="!isTeacherView">
        <el-button @click="visible = false">关闭</el-button>
      </template>
      <template v-else>
        <template v-if="mode === 'view'">
          <el-button @click="visible = false">关闭</el-button>
          <el-button type="primary" plain @click="startEdit">编辑</el-button>
        </template>
        <template v-else>
          <el-button :loading="resetting" type="warning" plain @click="doReset">恢复预设</el-button>
          <el-button @click="cancelEdit">取消</el-button>
          <el-button :loading="saving" type="primary" @click="save">保存</el-button>
        </template>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getLabGuide, updateLabGuide, resetLabGuide } from '@/api/labGuide'

// 教师视图：可编辑/恢复预设；学生视图：仅浏览
defineProps({ isTeacherView: { type: Boolean, default: false } })

const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const resetting = ref(false)
const mode = ref('view') // view | edit
const guide = ref({ title: '', content: '', is_preset: true })
const editForm = reactive({ title: '', content: '' })

async function open() {
  visible.value = true
  loading.value = true
  mode.value = 'view'
  try {
    guide.value = await getLabGuide()
  } finally {
    loading.value = false
  }
}

function startEdit() {
  editForm.title = guide.value.title || ''
  // 预设态编辑框留空：后端约定 content 留空 = 展示预设
  editForm.content = guide.value.is_preset ? '' : (guide.value.content || '')
  mode.value = 'edit'
}

function cancelEdit() {
  mode.value = 'view'
}

async function save() {
  saving.value = true
  try {
    guide.value = await updateLabGuide({ title: editForm.title, content: editForm.content })
    mode.value = 'view'
    ElMessage.success('实验必读已保存')
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function doReset() {
  await ElMessageBox.confirm(
    '恢复后教师自定义内容将被清空，重新展示平台预设内容，确认？',
    '恢复平台预设',
    { type: 'warning' },
  )
  resetting.value = true
  try {
    guide.value = await resetLabGuide()
    mode.value = 'view'
    ElMessage.success('已恢复平台预设内容')
  } catch (e) {
    ElMessage.error(e?.message || '恢复失败')
  } finally {
    resetting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.guide-view {
  max-height: 72vh;
  overflow-y: auto;
  border-radius: 8px;
}
.guide-edit {
  max-height: 72vh;
  overflow-y: auto;
}
.edit-tip {
  color: #94a3b8;
  font-size: 12px;
  padding-left: 70px;
}
.guide-render :deep(h1),
.guide-render :deep(h2) { margin: 20px 0 10px; font-size: 20px; }
.guide-render :deep(h3) { margin: 14px 0 8px; font-size: 16px; }
.guide-render :deep(p) { line-height: 1.7; margin: 6px 0; }
.guide-render :deep(ul),
.guide-render :deep(ol) { padding-left: 22px; line-height: 1.9; }
</style>
