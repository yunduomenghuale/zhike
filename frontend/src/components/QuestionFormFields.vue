<template>
  <!--
    单题编辑表单字段：新建/编辑题目弹窗与草稿批次预览行内共用。
    model 为受控对象引用（父层直接持有，字段变更即时可见）；
    normalize() 输出规范化草稿字段（qtype/stem/options/answer/analysis/score/difficulty），
    答案结构与后端 grading/入库管道契约一致：
    单选 {key} / 多选 {keys} / 判断 {key:A|B} / 填空 {blanks:[{text,score}]} / 简答 {text}。

    布局：内置 el-form 容器，不依赖调用处是否有 el-form（曾因预览态裸用 el-form-item
    导致 label/控件布局退化）——
    labelPosition=right（默认）：72px 固定标签列，所有行控件起点对齐（草稿预览紧凑态）；
    labelPosition=top：标签在上、控件全宽（手动新建/编辑弹窗态）。
  -->
  <el-form
    class="qff"
    :class="{ 'qff-compact': compact, 'qff-label-top': labelPosition === 'top' }"
    :model="model"
    :label-position="labelPosition"
    :label-width="labelPosition === 'top' ? undefined : 72"
  >
    <el-form-item v-if="showCatalog" label="所属章节" class="qff-catalog-field">
      <el-select v-model="model.catalog" class="module-select" popper-class="module-select-popper" placeholder="请选择题目所属章节" style="width: 100%">
        <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
      </el-select>
    </el-form-item>

    <el-form-item label="题型" class="qff-type-field">
      <el-select v-model="model.qtype" class="module-select" popper-class="module-select-popper" style="width: 100%; max-width: 240px" @change="onTypeChange">
        <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
    </el-form-item>

    <el-form-item label="题干" class="qff-multiline">
      <el-input v-model="model.stem" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" placeholder="请输入题干" />
    </el-form-item>

    <!-- 题图（题干配图，一张）：选择即上传，path 随表单回传 -->
    <el-form-item label="题图" class="qff-multiline">
      <div class="qimg-editor">
        <div v-if="model.image" class="qimg-preview">
          <img :src="imageUrl" alt="题图" />
          <div class="qimg-bar">
            <el-button size="small" text type="primary" :loading="uploading" @click="pickFile">更换</el-button>
            <el-button size="small" text type="danger" @click="model.image = ''">移除</el-button>
          </div>
        </div>
        <el-button v-else class="qimg-upload" :loading="uploading" @click="pickFile">
          <el-icon><Plus /></el-icon> 上传题图
        </el-button>
        <span class="qimg-tip">选填 · PNG/JPG/GIF/WebP/BMP ≤5MB</span>
        <input
          ref="fileInput"
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
          style="display: none"
          @change="onFilePicked"
        />
      </div>
    </el-form-item>

    <!-- 选项（单选/多选） -->
    <el-form-item v-if="model.qtype === 'single' || model.qtype === 'multi'" label="选项" class="qff-multiline">
      <div class="opt-editor">
        <div v-for="(opt, i) in model.options" :key="opt.key" class="opt-row">
          <el-tag class="opt-key" size="small">{{ opt.key }}</el-tag>
          <el-input v-model="opt.text" placeholder="选项内容" />
          <el-button
            class="opt-correct-btn"
            size="small"
            :type="isCorrect(opt.key) ? 'success' : ''"
            :plain="!isCorrect(opt.key)"
            @click="toggleCorrect(opt.key)"
          >{{ isCorrect(opt.key) ? '✓ 正确答案' : '设为答案' }}</el-button>
          <el-button link type="danger" :icon="Delete" class="opt-remove" @click="model.options.splice(i, 1)" />
        </div>
        <el-button link type="primary" :icon="Plus" @click="addOption">添加选项</el-button>
      </div>
    </el-form-item>

    <!-- 判断题答案 -->
    <el-form-item v-else-if="model.qtype === 'judge'" label="答案">
      <el-radio-group v-model="model.answerKey">
        <el-radio value="A">正确</el-radio>
        <el-radio value="B">错误</el-radio>
      </el-radio-group>
    </el-form-item>

    <!-- 填空答案（按空单独赋分） -->
    <el-form-item v-else-if="model.qtype === 'blank'" label="答案" class="qff-multiline">
      <div class="opt-editor">
        <div v-for="(b, i) in model.blanks" :key="i" class="opt-row blank-row">
          <span class="blank-idx">第{{ i + 1 }}空</span>
          <el-input v-model="b.text" placeholder="正确答案" />
          <el-input-number v-model="b.score" class="blank-score-input" :min="1" :max="100" :controls="false" placeholder="分值" />
          <span class="blank-score-unit">分</span>
          <el-button link type="danger" :icon="Delete" class="opt-remove" @click="model.blanks.splice(i, 1)" />
        </div>
        <el-button link type="primary" :icon="Plus" @click="addBlank">添加空</el-button>
      </div>
    </el-form-item>

    <!-- 简答题参考答案（主观题无唯一标准答案，供学生作答与教师批改参考） -->
    <el-form-item v-else-if="model.qtype === 'short'" label="参考答案" class="qff-multiline">
      <el-input v-model="model.answerText" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }" placeholder="选填：本题的参考要点，学生端以「参考答案」展示" />
    </el-form-item>

    <el-form-item label="解析" class="qff-multiline">
      <el-input v-model="model.analysis" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }" placeholder="选填" />
    </el-form-item>

    <el-form-item label="分值/难度">
      <div class="score-diff-row">
        <span v-if="model.qtype === 'blank'" class="blank-total-score">
          合计 <b>{{ blankTotal }}</b> 分<em>（按空自动累计）</em>
        </span>
        <el-input-number v-else v-model="model.score" class="score-num" :min="1" :max="100" />
        <el-select v-model="model.difficulty" class="module-select" popper-class="module-select-popper" style="width: 120px">
          <el-option label="简单" value="easy" />
          <el-option label="中等" value="medium" />
          <el-option label="困难" value="hard" />
        </el-select>
      </div>
    </el-form-item>
  </el-form>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { DEFAULT_QTYPES, blankScoreTotal, buildAnswer, buildOptions, formToDraft } from '@/utils/questionDraft'
import { uploadQuestionImage } from '@/api/question'

const props = defineProps({
  // 受控表单对象（父层持有引用，字段直接变更；改题型时由本组件重置答案字段）
  model: { type: Object, required: true },
  qtypes: { type: Array, default: () => DEFAULT_QTYPES },
  // 扁平化章节：[{id, label}]（showCatalog 时可用）
  catalogs: { type: Array, default: () => [] },
  // 是否展示章节选择（新建/编辑题目显示；草稿预览行内不显示，章节在批次级设置）
  showCatalog: { type: Boolean, default: false },
  // 紧凑模式：草稿预览行内嵌使用（压缩纵向占位）
  compact: { type: Boolean, default: false },
  // 标签布局：right=标签列在左（72px 固定对齐，默认）/ top=标签在上（手动弹窗态）
  labelPosition: { type: String, default: 'right' },
})

function onTypeChange() {
  props.model.answerKey = ''
  props.model.answerKeys = []
  props.model.answerText = ''
}

function isCorrect(key) {
  return props.model.qtype === 'single' ? props.model.answerKey === key : props.model.answerKeys.includes(key)
}
function toggleCorrect(key) {
  if (props.model.qtype === 'single') {
    props.model.answerKey = key
  } else {
    const idx = props.model.answerKeys.indexOf(key)
    if (idx >= 0) props.model.answerKeys.splice(idx, 1)
    else props.model.answerKeys.push(key)
  }
}
function addOption() {
  const key = String.fromCharCode(65 + props.model.options.length)
  props.model.options.push({ key, text: '' })
}
function addBlank() {
  props.model.blanks.push({ text: '', score: 1 })
}

const blankTotal = computed(() => blankScoreTotal(props.model))

// ---- 题图上传（选择即传，回传 path；展示走 /media/ 静态服务）----
const fileInput = ref(null)
const uploading = ref(false)
const imageUrl = computed(() => (props.model.image ? `/media/${props.model.image}` : ''))
function pickFile() {
  fileInput.value?.click()
}
async function onFilePicked(event) {
  const file = event.target.files?.[0]
  event.target.value = '' // 允许再次选择同一文件
  if (!file) return
  uploading.value = true
  try {
    const data = await uploadQuestionImage(file)
    props.model.image = data.path
  } catch {
    // 失败消息由 request 拦截器统一提示
  } finally {
    uploading.value = false
  }
}

/** 表单态 → 规范化草稿字段（供 save/预览回传合并进 drafts） */
function normalize() {
  return formToDraft(props.model)
}

defineExpose({ normalize })
</script>

<style scoped>
/* ---- 行距 ---- */
.qff :deep(.el-form-item) { margin-bottom: 16px; }
.qff-compact :deep(.el-form-item) { margin-bottom: 10px; }
.qff-label-top :deep(.el-form-item) { margin-bottom: 12px; }

/* ---- 标签 ---- */
.qff :deep(.el-form-item__label) {
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 38px; /* 与控件等高：单行控件标签垂直居中 */
  padding: 0 12px 0 0;
}
.qff-compact :deep(.el-form-item__label) {
  font-size: 12.5px;
  line-height: 34px;
}
/* 多行控件（题干/解析/选项/答案）：标签顶部对齐，不落垂直中部 */
.qff :deep(.qff-multiline .el-form-item__label) {
  line-height: 1.5;
  padding-top: 9px;
}
.qff-compact :deep(.qff-multiline .el-form-item__label) {
  padding-top: 8px;
}
/* top 模式：标签独占一行 */
.qff-label-top :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 7px;
  line-height: 1.2;
}

/* ---- 控件皮肤（手动弹窗与草稿预览统一） ---- */
.qff :deep(.el-input__wrapper),
.qff :deep(.el-select__wrapper),
.qff :deep(.el-input-number) {
  min-height: 38px;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
}
.qff-compact :deep(.el-input__wrapper),
.qff-compact :deep(.el-select__wrapper),
.qff-compact :deep(.el-input-number) {
  min-height: 34px;
  border-radius: 9px;
}
.qff :deep(.el-textarea__inner) {
  padding: 11px 13px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
  font-size: 13.5px;
  line-height: 1.6;
}
.qff :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.qff-compact :deep(.el-textarea__inner) {
  padding: 8px 11px;
  font-size: 13px;
}

/* ---- 题图上传 ---- */
.qimg-editor {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  width: 100%;
}
.qimg-preview {
  display: flex;
  align-items: center;
  gap: 10px;
}
.qimg-preview img {
  max-width: 200px;
  max-height: 120px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #fff;
  object-fit: contain;
}
.qimg-bar {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.qimg-upload {
  border: 1px dashed #c3d4ea;
  border-radius: 10px;
  background: #f8fbff;
  color: #2563eb;
}
.qimg-tip {
  color: #94a3b8;
  font-size: 12px;
}

/* ---- 选项行：key 定宽 + input 占满 + 答案按钮等宽（两态文案不抖动） ---- */
.opt-editor {
  width: 100%;
}
.opt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.opt-row .el-input {
  flex: 1;
  min-width: 0;
}
.opt-key {
  flex: none;
  width: 28px;
  justify-content: center;
  font-weight: 700;
}
.opt-correct-btn {
  flex: none;
  min-width: 92px;
}
.opt-remove {
  flex: none;
}

/* ---- 填空行 ---- */
.blank-idx {
  flex: none;
  width: 48px;
  color: #64748b;
  font-size: 13px;
  white-space: nowrap;
}
.blank-row .el-input {
  flex: 1;
  min-width: 0;
}
.blank-score-input {
  width: 72px;
  flex: none;
}
.blank-score-input :deep(.el-input__wrapper) {
  padding: 0 8px;
}
.blank-score-unit {
  flex: none;
  color: #64748b;
  font-size: 13px;
}

/* ---- 分值/难度 ---- */
.score-diff-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  width: 100%;
}
.score-num {
  width: 130px;
}
.blank-total-score {
  color: #1e293b;
  font-size: 14px;
}
.blank-total-score b {
  color: #2563eb;
  font-size: 16px;
  margin: 0 2px;
}
.blank-total-score em {
  color: #94a3b8;
  font-size: 12px;
  font-style: normal;
  margin-left: 6px;
}
</style>
