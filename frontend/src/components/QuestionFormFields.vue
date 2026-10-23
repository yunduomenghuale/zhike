<template>
  <!--
    单题编辑表单字段：新建/编辑题目弹窗与草稿批次预览行内共用。
    model 为受控对象引用（父层直接持有，字段变更即时可见）；
    normalize() 输出规范化草稿字段（qtype/stem/options/answer/analysis/score/difficulty），
    答案结构与后端 grading/入库管道契约一致：
    单选 {key} / 多选 {keys} / 判断 {key:A|B} / 填空 {blanks:[{text,score}]} / 简答 {text}。
  -->
  <div class="qff" :class="{ 'qff-compact': compact }">
    <el-form-item v-if="showCatalog" label="所属章节" class="qff-catalog-field">
      <el-select v-model="model.catalog" class="module-select" popper-class="module-select-popper" placeholder="请选择题目所属章节" style="width: 100%">
        <el-option v-for="c in catalogs" :key="c.id" :label="c.label" :value="c.id" />
      </el-select>
    </el-form-item>

    <el-form-item label="题型" class="qff-type-field">
      <el-select v-model="model.qtype" class="module-select" popper-class="module-select-popper" style="width: 160px" @change="onTypeChange">
        <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
    </el-form-item>

    <el-form-item label="题干">
      <el-input v-model="model.stem" type="textarea" :rows="compact ? 1 : 2" placeholder="请输入题干" />
    </el-form-item>

    <!-- 选项（单选/多选） -->
    <el-form-item v-if="model.qtype === 'single' || model.qtype === 'multi'" label="选项">
      <div class="opt-editor">
        <div v-for="(opt, i) in model.options" :key="opt.key" class="opt-row">
          <el-tag>{{ opt.key }}</el-tag>
          <el-input v-model="opt.text" placeholder="选项内容" />
          <el-button
            size="small"
            :type="isCorrect(opt.key) ? 'success' : ''"
            :plain="!isCorrect(opt.key)"
            @click="toggleCorrect(opt.key)"
          >{{ isCorrect(opt.key) ? '✓ 正确答案' : '设为答案' }}</el-button>
          <el-button link type="danger" :icon="Delete" @click="model.options.splice(i, 1)" />
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
    <el-form-item v-else-if="model.qtype === 'blank'" label="答案">
      <div class="opt-editor">
        <div v-for="(b, i) in model.blanks" :key="i" class="opt-row blank-row">
          <span class="blank-idx">第{{ i + 1 }}空</span>
          <el-input v-model="b.text" placeholder="正确答案" />
          <el-input-number v-model="b.score" class="blank-score-input" :min="1" :max="100" :controls="false" placeholder="分值" />
          <span class="blank-score-unit">分</span>
          <el-button link type="danger" :icon="Delete" @click="model.blanks.splice(i, 1)" />
        </div>
        <el-button link type="primary" :icon="Plus" @click="addBlank">添加空</el-button>
      </div>
    </el-form-item>

    <!-- 简答题参考答案（主观题无唯一标准答案，供学生作答与教师批改参考） -->
    <el-form-item v-else-if="model.qtype === 'short'" label="参考答案">
      <el-input v-model="model.answerText" type="textarea" :rows="compact ? 1 : 2" placeholder="选填：本题的参考要点，学生端以「参考答案」展示" />
    </el-form-item>

    <el-form-item label="解析">
      <el-input v-model="model.analysis" type="textarea" :rows="compact ? 1 : 2" placeholder="选填" />
    </el-form-item>

    <el-form-item label="分值/难度">
      <span v-if="model.qtype === 'blank'" class="blank-total-score">
        合计 <b>{{ blankTotal }}</b> 分<em>（按空自动累计）</em>
      </span>
      <el-input-number v-else v-model="model.score" :min="1" :max="100" />
      <el-select v-model="model.difficulty" class="module-select" popper-class="module-select-popper" style="width: 120px; margin-left: 12px">
        <el-option label="简单" value="easy" />
        <el-option label="中等" value="medium" />
        <el-option label="困难" value="hard" />
      </el-select>
    </el-form-item>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { DEFAULT_QTYPES, blankScoreTotal, buildAnswer, buildOptions, formToDraft } from '@/utils/questionDraft'

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

/** 表单态 → 规范化草稿字段（供 save/预览回传合并进 drafts） */
function normalize() {
  return formToDraft(props.model)
}

defineExpose({ normalize })
</script>

<style scoped>
.qff-compact :deep(.el-form-item) {
  margin-bottom: 10px;
}
.qff-compact :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 5px;
  font-size: 12.5px;
  line-height: 1.2;
}
.qff-compact :deep(.el-input__wrapper),
.qff-compact :deep(.el-select__wrapper),
.qff-compact :deep(.el-input-number) {
  min-height: 34px;
  border-radius: 9px;
}
.qff-compact :deep(.el-textarea__inner) {
  padding: 8px 11px;
  font-size: 13px;
}

.opt-editor {
  width: 100%;
}
.opt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.blank-idx {
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
  color: #64748b;
  font-size: 13px;
  flex: none;
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
