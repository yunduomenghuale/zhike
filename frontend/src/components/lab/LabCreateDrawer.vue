<template>
  <el-drawer
    :model-value="modelValue"
    title="新建实验"
    size="580px"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @closed="resetForm"
  >
    <el-tabs v-model="tab" class="create-tabs">
      <el-tab-pane label="平台预置" name="preset">
        <div class="tab-tip">选择平台已有的实验模板，步骤与判分由平台预置页面提供。</div>
      </el-tab-pane>
      <el-tab-pane label="自定义上传" name="custom">
        <div class="tab-tip">
          上传单个 HTML：步骤与判分规则都写在页面里，平台只接收总分与用时；创建后可在「成绩接口」Tab 一键复制接入说明给 AI。
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-form :model="form" label-width="100px" class="create-form">
      <el-form-item label="所属课程" required>
        <el-select
          v-model="form.course"
          placeholder="选择课程"
          style="width: 100%"
          :disabled="Boolean(fixedCourseId)"
        >
          <el-option v-for="c in courses" :key="c.id" :value="c.id" :label="c.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="所属章节">
        <el-select v-model="form.catalog" placeholder="可选，不绑章节也能进班级学情" clearable style="width: 100%">
          <el-option v-for="c in catalogOptions" :key="c.id" :value="c.id" :label="c.title" />
        </el-select>
      </el-form-item>
      <el-form-item label="实验模板" required>
        <el-select v-model="form.template" placeholder="选择平台预置实验" style="width: 100%">
          <el-option v-for="t in templates" :key="t.id" :value="t.id" :label="t.title" />
        </el-select>
      </el-form-item>
      <el-form-item label="实验名称" :required="tab === 'custom'">
        <el-input v-model="form.title" :placeholder="tab === 'custom' ? '必填，例如：VLAN 与 Trunk 配置' : '留空默认使用模板名称'" />
      </el-form-item>
      <el-form-item label="实验说明">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
      </el-form-item>
      <el-form-item label="实验满分">
        <el-input-number v-model="form.total_score" :min="1" :max="1000" :step="10" />
      </el-form-item>
      <el-form-item label="及格分">
        <el-input-number v-model="form.pass_score" :min="0" :max="1000" :step="5" />
      </el-form-item>
      <el-form-item label="标准时长">
        <el-input-number v-model="form.standard_minutes" :min="5" :max="180" :step="5" />
        <span class="unit">分钟</span>
      </el-form-item>
      <el-form-item label="允许重做">
        <el-switch v-model="form.allow_resubmit" />
        <span class="unit">自定义实验默认关闭（重做会保留上轮成绩，易造成误读）</span>
      </el-form-item>

      <template v-if="tab === 'custom'">
        <el-form-item label="实验页面" required>
          <LabPageUploader v-model="pickedFile" :lab-id="null" />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input
            v-model="form.report_note"
            type="textarea"
            :rows="2"
            placeholder="可选：写给 AI 的额外要求，会追加在接入说明末尾"
          />
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="creating" @click="create">创建实验</el-button>
    </template>
  </el-drawer>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCatalogs } from '@/api/course'
import { createLab, listLabTemplates, uploadLabPage } from '@/api/labs'
import LabPageUploader from './LabPageUploader.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courses: { type: Array, default: () => [] },
  fixedCourseId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'created'])

const tab = ref('preset')
const templates = ref([])
const catalogOptions = ref([])
const pickedFile = ref(null)
const creating = ref(false)
const blankForm = () => ({
  course: props.fixedCourseId || null,
  catalog: null,
  template: null,
  title: '',
  description: '',
  total_score: 100,
  pass_score: 60,
  standard_minutes: 30,
  // C12：自定义实验默认不允许重做（_reset_fields 刻意保留上轮成绩）
  allow_resubmit: false,
  report_note: '',
})
const form = ref(blankForm())

function resetForm() {
  form.value = blankForm()
  pickedFile.value = null
  tab.value = 'preset'
}

function flattenCatalogs(nodes) {
  const out = []
  const walk = (list, depth) => {
    ;(list || []).forEach((n) => {
      if (!n || !n.id) return
      out.push({ id: n.id, title: `${'　'.repeat(depth)}${n.title || ''}` })
      if (Array.isArray(n.children) && n.children.length) walk(n.children, depth + 1)
    })
  }
  walk(nodes, 0)
  return out
}

async function loadTemplates() {
  const res = await listLabTemplates()
  templates.value = res.results ?? res ?? []
}

async function loadCatalogs(courseId) {
  if (!courseId) {
    catalogOptions.value = []
    return
  }
  try {
    const res = await listCatalogs({ course: courseId, tree: 1, page_size: 100 })
    catalogOptions.value = flattenCatalogs(res.results ?? res)
  } catch {
    catalogOptions.value = []
  }
}

/** 创建后再上传：先有 lab.id 才能走 /page/ 端点；命中 S8 扫描时二次确认重传。 */
async function uploadAfterCreate(labId) {
  if (tab.value !== 'custom' || !pickedFile.value) return
  let force = false
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await uploadLabPage(labId, pickedFile.value, force)
      return
    } catch (e) {
      const body = e?.response?.data
      if (body?.require_confirm && !force) {
        const ok = await ElMessageBox.confirm(
          `页面源码命中安全扫描规则：${(body.hits || []).join('、')}。确认源码无误并继续上传？`,
          '安全扫描提示',
          { type: 'warning' },
        ).then(() => true).catch(() => false)
        if (!ok) {
          ElMessage.warning('实验已创建，请稍后在「实验页面」Tab 补传页面')
          return
        }
        force = true
        continue
      }
      ElMessage.warning(`实验已创建，但页面上传失败：${body?.message || e?.message || '未知错误'}`)
      return
    }
  }
}

async function create() {
  if (!form.value.course) return ElMessage.warning('请选择所属课程')
  if (tab.value === 'preset' && !form.value.template) return ElMessage.warning('请选择实验模板')
  if (tab.value === 'custom' && !form.value.title.trim()) return ElMessage.warning('自定义实验请填写实验名称')
  if (tab.value === 'custom' && !pickedFile.value) return ElMessage.warning('请上传实验 HTML 页面')

  creating.value = true
  try {
    const payload = {
      course: form.value.course,
      catalog: form.value.catalog || undefined,
      title: form.value.title.trim() || undefined,
      description: form.value.description || undefined,
      total_score: form.value.total_score,
      pass_score: form.value.pass_score,
      standard_minutes: form.value.standard_minutes,
      allow_resubmit: form.value.allow_resubmit,
      page_source: tab.value === 'custom' ? 'custom' : 'template',
      template: tab.value === 'preset' ? form.value.template : undefined,
      report_note: tab.value === 'custom' ? form.value.report_note : '',
    }
    const lab = await createLab(payload)
    await uploadAfterCreate(lab.id)
    ElMessage.success('实验已创建')
    emit('created', { ...lab, page_source: payload.page_source })
    emit('update:modelValue', false)
  } catch (e) {
    ElMessage.error(e?.message || '创建实验失败')
  } finally {
    creating.value = false
  }
}

watch(() => props.fixedCourseId, (id) => {
  form.value.course = id || form.value.course
  loadCatalogs(id)
})
watch(() => form.value.course, (id) => loadCatalogs(id))
watch(() => props.modelValue, (open) => {
  if (open) {
    form.value.course = props.fixedCourseId || form.value.course
    loadTemplates()
    loadCatalogs(form.value.course)
  }
})
onMounted(loadTemplates)
</script>

<style scoped>
.create-tabs { margin-bottom: 6px; }
.tab-tip { font-size: 12.5px; color: #64748b; line-height: 1.7; padding: 2px 2px 8px; }
.create-form { padding-right: 8px; }
.unit { margin-left: 10px; font-size: 12px; color: #94a3b8; }
</style>
