<template>
  <el-dialog
    :model-value="modelValue"
    title="新建实验"
    width="640px"
    top="6vh"
    append-to-body
    @update:model-value="(v) => emit('update:modelValue', v)"
    @closed="resetForm"
  >
    <el-tabs v-model="tab" class="create-tabs">
      <el-tab-pane label="自定义上传" name="custom">
        <div class="tab-tip">
          推荐方式：先创建实验拿到接入说明，再上传单个 HTML 实验页面（步骤与判分规则都写在页面里，平台只接收总分）。
        </div>
      </el-tab-pane>
      <el-tab-pane label="平台预置（计算机网络实验）" name="preset">
        <div class="tab-tip">
          平台内置的计算机网络课程虚拟仿真实验（交换机 / 路由 / 协议分析等 7 个），步骤与判分由平台预置页面提供，无需任何配置。
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
          <el-option v-for="c in courseList" :key="c.id" :value="c.id" :label="c.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="所属章节">
        <el-select v-model="form.catalog" placeholder="可选，不绑章节也能进班级学情" clearable style="width: 100%">
          <el-option v-for="c in catalogOptions" :key="c.id" :value="c.id" :label="c.title" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="tab === 'preset'" label="实验模板" required>
        <el-select v-model="form.template" placeholder="选择平台预置实验" style="width: 100%">
          <el-option v-for="t in templates" :key="t.id" :value="t.id" :label="t.title" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="tab === 'preset'" label="实验说明">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选，留空使用模板说明" />
      </el-form-item>
      <el-form-item v-if="tab === 'custom'" label="实验名称" required>
        <el-input v-model="form.title" placeholder="必填，例如：VLAN 与 Trunk 配置" />
      </el-form-item>

      <el-alert type="info" :closable="false" class="rule-alert">
        <template #title>
          满分固定 100 分、及格 60 分，无需配置；同一学生多次提交只记录<strong>最高分</strong>。
        </template>
      </el-alert>

      <template v-if="tab === 'custom'">
        <el-form-item label="实验页面">
          <LabPageUploader v-model="pickedFile" :lab-id="null" />
          <div class="upload-optional-tip">
            可现在上传，也可以创建后到详情的「实验页面」页上传或替换（发布前必须已上传）。
          </div>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <div v-if="phase" class="phase-tip">
        <el-icon class="is-loading"><Loading /></el-icon>
        {{ phase }}
        <el-progress
          v-if="uploadPercent > 0"
          :percentage="uploadPercent"
          :stroke-width="8"
          style="margin-top: 6px"
        />
      </div>
      <div class="footer-btns">
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">创建实验</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import request from '@/api/request'
import { listCatalogs } from '@/api/course'
import { createLab, listLabTemplates, uploadLabPage } from '@/api/labs'
import LabPageUploader from './LabPageUploader.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courses: { type: Array, default: () => [] },
  fixedCourseId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'created'])

// Stage 6：抽屉打开时自拉课程列表，不依赖父组件的加载时序
// （父页 load() 会并发拉大量统计请求，课程下拉可能晚于抽屉打开就绪）。
const courseList = ref([])
async function loadCourseList() {
  if (props.fixedCourseId) {
    const fixed = props.courses.find((c) => String(c.id) === String(props.fixedCourseId))
    if (fixed) {
      courseList.value = [fixed]
      return
    }
    // 课程工作台内嵌时父组件不拉课程列表（courses 为空），下拉没有匹配选项
    // 会直接显示裸 id（如「5」）——按 id 回查课程详情兜底。
    try {
      const res = await request.get(`/courses/${props.fixedCourseId}/`)
      courseList.value = res && res.id ? [res] : []
    } catch {
      courseList.value = []
    }
    return
  }
  try {
    const res = await request.get('/courses/', { params: { page_size: 100 } })
    courseList.value = res.results ?? res ?? []
  } catch {
    courseList.value = []
  }
}

// Stage 6 教师反馈：自定义上传是主路径，排在第一且默认选中
const tab = ref('custom')
const templates = ref([])
const catalogOptions = ref([])
const pickedFile = ref(null)
const creating = ref(false)
// 阶段反馈：创建 → 上传（含进度百分比），让整个流程可见（教师反馈第 7 条）
const phase = ref('')
const uploadPercent = ref(0)
const blankForm = () => ({
  course: props.fixedCourseId || null,
  catalog: null,
  template: null,
  title: '',
  description: '',
})
const form = ref(blankForm())

function resetForm() {
  form.value = blankForm()
  pickedFile.value = null
  tab.value = 'custom'
  phase.value = ''
  uploadPercent.value = 0
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
async function uploadAfterCreate(labId, fileName) {
  if (tab.value !== 'custom' || !pickedFile.value) return
  let force = false
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await uploadLabPage(labId, pickedFile.value, force, (e) => {
        if (e.total) uploadPercent.value = Math.round((e.loaded / e.total) * 100)
      })
      return
    } catch (e) {
      // 400 响应体是 { code, message, data: { require_confirm, hits, ... } }——确认数据在 data 里
      const respBody = e?.response?.data || e || {}
      const payload = respBody?.data || respBody || {}
      if (payload?.require_confirm && !force) {
        const ok = await ElMessageBox.confirm(
          `页面源码命中安全扫描规则：${(payload.hits || []).join('、')}。确认源码无误并继续上传？`,
          '安全扫描提示',
          { type: 'warning' },
        ).then(() => true).catch(() => false)
        if (!ok) {
          ElMessage.warning('实验已创建，请稍后在「实验页面」页补传页面')
          return
        }
        force = true
        continue
      }
      ElMessage.warning(`实验已创建，但页面「${fileName}」上传失败：${payload?.message || respBody?.message || e?.message || '未知错误'}`)
      return
    }
  }
}

async function create() {
  if (!form.value.course) return ElMessage.warning('请选择所属课程')
  if (tab.value === 'preset' && !form.value.template) return ElMessage.warning('请选择实验模板')
  if (tab.value === 'custom' && !form.value.title.trim()) return ElMessage.warning('自定义实验请填写实验名称')

  creating.value = true
  try {
    // Stage 6/7：满分/及格/时长/重做不再收集（后端默认 100/60，多次提交保留最高分）；
    // 实验页面不作为创建必填——引导「先创建 → 看成绩接口说明 → 再上传页面（发布前必须已上传）」
    const payload = {
      course: form.value.course,
      catalog: form.value.catalog || undefined,
      title: form.value.title.trim() || undefined,
      description: form.value.description || undefined,
      page_source: tab.value === 'custom' ? 'custom' : 'template',
      template: tab.value === 'preset' ? form.value.template : undefined,
    }
    phase.value = '正在创建实验…'
    const lab = await createLab(payload)
    let uploadedNow = false
    if (tab.value === 'custom' && pickedFile.value) {
      phase.value = `正在上传页面 ${pickedFile.value.name}…`
      uploadPercent.value = 1
      await uploadAfterCreate(lab.id, pickedFile.value.name)
      uploadedNow = true
    }
    phase.value = ''
    uploadPercent.value = 0
    if (tab.value === 'custom') {
      ElMessage.success(uploadedNow
        ? '实验与页面已就绪。接入说明见「成绩接口」页，可复制给 AI。'
        : '实验已创建（草稿）。请先看「成绩接口」说明，再到「实验页面」上传 HTML 后发布。')
    } else {
      ElMessage.success('实验已创建')
    }
    emit('created', { ...lab, page_source: payload.page_source })
    emit('update:modelValue', false)
  } catch (e) {
    ElMessage.error(e?.message || '创建实验失败')
  } finally {
    creating.value = false
    phase.value = ''
    uploadPercent.value = 0
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
    loadCourseList()
    loadTemplates()
    loadCatalogs(form.value.course)
  }
})
onMounted(loadTemplates)
</script>

<style scoped>
.create-tabs { margin-bottom: 6px; }
.upload-optional-tip { margin-top: 8px; font-size: 12px; color: #94a3b8; line-height: 1.7; }
.tab-tip { font-size: 12.5px; color: #64748b; line-height: 1.7; padding: 2px 2px 8px; }
.create-form { padding-right: 8px; }
.unit { margin-left: 10px; font-size: 12px; color: #94a3b8; }
.rule-alert { margin: 4px 0 10px; }
.phase-tip {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #2563eb; padding: 4px 2px 10px;
  flex: 1;
}
.footer-btns { display: flex; gap: 10px; justify-content: flex-end; }
</style>
