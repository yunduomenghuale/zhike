<template>
  <div v-loading="loading" class="lab-grading-panel">
    <!-- 1. 接口地址 -->
    <div class="gp-section">
      <div class="gp-title">成绩上报地址</div>
      <div class="endpoint-row">
        <code class="endpoint">POST {{ endpoint }}</code>
        <el-button size="small" @click="copyText(endpoint, '接口地址')">复制</el-button>
      </div>
      <div class="gp-hint">
        同源路径，由<strong>平台父页面</strong> <code>lab-bridge-parent.js</code> 代发上报请求。
        一次性票据只在该父页面的闭包里自动附带，教师 HTML 拿不到票据、无需配置，<strong>没有固定密钥</strong>。
      </div>
    </div>

    <!-- 2. 动态接入说明 -->
    <div class="gp-section">
      <div class="gp-title">
        动态接入说明
        <el-icon class="help-icon" @click="helpVisible = true"><QuestionFilled /></el-icon>
        <el-button size="small" type="primary" :disabled="!specMarkdown" @click="copyText(specMarkdown, '接入说明')">
          复制给 AI
        </el-button>
        <span class="gp-meta">按「{{ specTitle || '本实验' }}」与满分 {{ specScore || '—' }} 生成</span>
      </div>
      <div class="gp-hint">
        已按本实验预填名称与满分：<b>点「复制给 AI」把整段说明发给任意 AI 编程工具</b>，
        它会产出可直接上传的单文件 HTML。点击问号查看使用步骤与提示词模板。
      </div>
      <pre class="spec-markdown" ref="specBox">{{ specMarkdown }}</pre>
    </div>

    <!-- 3. 在线调试（dry-run，不入库） -->
    <div class="gp-section">
      <div class="gp-title">
        在线调试
        <el-tag size="small" type="info" effect="plain">dry-run · 不入库</el-tag>
      </div>
      <div class="debug-form">
        <span class="debug-label">总分</span>
        <el-input-number v-model="debugForm.total_score" :min="0" :max="Number(specScore) || 100" :step="0.5" :precision="1" size="small" />
        <span class="debug-label">用时（秒）</span>
        <el-input-number v-model="debugForm.elapsed_seconds" :min="0" :step="10" size="small" />
        <el-button size="small" @click="fillExample('full')">满分示例</el-button>
        <el-button size="small" @click="fillExample('zero')">零分示例</el-button>
        <el-button size="small" @click="fillExample('part')">部分分示例</el-button>
        <el-button size="small" type="primary" :loading="debugging" @click="runDebug">发送调试请求</el-button>
      </div>

      <template v-if="debugResult">
        <div class="debug-verdict" :class="debugResult.passed ? 'pass' : 'fail'">
          {{ debugResult.passed ? '调试通过' : '调试未通过' }}
          <span>（模拟报文，未产生真实提交）</span>
        </div>
        <div class="check-list">
          <div v-for="(c, i) in debugResult.checks" :key="i" class="check-item" :class="checkClass(c)">
            <span class="check-flag">{{ checkFlag(c) }}</span>
            <span class="check-name">{{ c.name }}</span>
            <span class="check-detail">{{ c.detail }}</span>
          </div>
        </div>
        <div v-if="debugResult.preview" class="debug-preview">
          <div class="gp-subtitle">若正式提交会写入</div>
          <pre>{{ JSON.stringify(debugResult.preview, null, 2) }}</pre>
        </div>
      </template>
    </div>

    <!-- 使用示例弹窗（教师反馈第 5 条） -->
    <el-dialog v-model="helpVisible" title="如何使用接入说明" width="720px" top="6vh" append-to-body class="help-dialog">
      <div class="help-doc">
        <h4>三步接入</h4>
        <ol>
          <li><b>复制接入说明</b>：点上方「复制给 AI」，把整段说明发给任意 AI 编程工具（豆包 / Kimi / Copilot 等）。</li>
          <li><b>让 AI 生成页面</b>：AI 会按说明产出<b>单文件 HTML</b> 实验页（界面、交互、判分都在页面里）。</li>
          <li><b>上传并调试</b>：在「实验页面」上传该 HTML，用下方「在线调试」模拟提交，通过后发布实验。</li>
        </ol>
        <h4>使用规则（务必让 AI 遵守）</h4>
        <ul>
          <li>页面只上报一个总分（<code>total_score</code>，最多 1 位小数，0 ~ 满分）；用时仅留痕，正式用时由平台计算。</li>
          <li>页面运行在平台沙箱 iframe 内：读不到票据和平台数据，须通过 <code>LabBridge.validate()</code> 取满分、<code>LabBridge.reportGrade()</code> 上报。</li>
          <li>单文件：JS / CSS / 图片全部内联；不得访问浏览器存储、外链资源或平台接口（静态扫描会拦截）。</li>
          <li>同一学生多次提交只记录<b>最高分</b>，可放心让学生重试。</li>
        </ul>
        <h4>发给 AI 的提示词模板（填一行主题即可用）</h4>
        <pre class="help-code">{{ helpPromptText }}</pre>
        <h4>实测范例：主题描述的推荐写法（已验证有效）</h4>
        <div class="help-tip-line">
          「复制给 AI」说明已替你预填实验名与满分；AI 只差一段<b>具体的主题描述</b>。
          下面是按此写法实测的范例——把「实验主题与判分需求」的占位符替换成这样的描述（场景化操作 + 明确计分），
          AI 就会产出带 SVG 场景与动画的交互实验（本范例由 AI 按此描述生成并通过全部健康检查）：
        </div>
        <pre class="help-code">十进制与二进制转换练习实验。满分 100 分，判分基于学生在场景中的操作结果：
学生通过拨动「二进制位开关」构造出一个指定的二进制数（教师面板给出目标十进制值），
共 5 关，每关目标值不同（难度递增），构造正确并点击「确认本关」得 20 分；
全部达成得满分。</pre>
      </div>
      <template #footer>
        <el-button type="primary" @click="copyText(helpPromptText, '提示词模板')">复制提示词模板</el-button>
        <el-button type="success" plain @click="copyText(helpExampleText, '实测范例主题描述')">复制范例主题描述</el-button>
        <el-button @click="helpVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <div v-if="copied" class="copy-toast">{{ copied }}已复制到剪贴板</div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import { getIntegrationSpec, gradeDebug } from '@/api/labs'

const props = defineProps({
  labId: { type: [Number, String], required: true },
  lab: { type: Object, default: null },
})
const emit = defineEmits(['updated'])

const endpoint = '/api/lab-gate/grade/'
const loading = ref(false)
const debugging = ref(false)
const specMarkdown = ref('')
const specTitle = ref('')
const specScore = ref('')
const copied = ref('')
const specBox = ref(null)
const debugForm = ref({ total_score: 100, elapsed_seconds: 60 })
const debugResult = ref(null)
const helpVisible = ref(false)
const helpExampleText =
  '十进制与二进制转换练习实验。满分 100 分，判分基于学生在场景中的操作结果：\n' +
  '学生通过拨动「二进制位开关」构造出一个指定的二进制数（教师面板给出目标十进制值），\n' +
  '共 5 关，每关目标值不同（难度递增），构造正确并点击「确认本关」得 20 分；\n' +
  '全部达成得满分。'

const helpPromptText =
  '请为我开发一个智课平台的自定义实验页面，交付物是单个 HTML 文件\n' +
  '（所有 CSS/JS/图片内联，不引用外部资源、不使用 eval）。\n\n' +
  '实验主题与判分需求：\n' +
  '[在这里描述你的实验：学生要做什么、分几步、每步怎样算对、总分怎么算]\n\n' +
  '实验呈现要求（重要——这是虚拟实验，不是答题问卷）：\n' +
  '1. 页面必须有一个「实验场景区」：用 SVG 或 Canvas 绘制与主题相关的可视化场景\n' +
  '   （如网络拓扑图、实验装置、流程示意），标注设备/元件名称与当前状态。\n' +
  '2. 学生的每一步操作都要与场景联动：点击设备/元件进行配置或操作，场景状态实时变化，\n' +
  '   关键过程用动画呈现（用 CSS/SVG 动画实现）。\n' +
  '3. 判分基于学生在场景中的操作结果；可以辅以少量输入题，但纯选择/填空题不应超过总分的一半。\n\n' +
  '硬性要求：\n' +
  '1. 平台会在沙箱 iframe 内注入 window.LabBridge。页面启动后先 await LabBridge.validate()\n' +
  '   读取满分（ctx.totalScore，不要写死）；若 LabBridge.preview === true 表示教师预览，只展示不提交。\n' +
  '2. 学生完成操作后，页面自行判分并只调用一次：\n' +
  '   await LabBridge.reportGrade({ total_score: <总分>, elapsed_seconds: <用时秒> })\n' +
  '   total_score 在 0 ~ 满分之间、最多 1 位小数；平台只接收这两个字段；\n' +
  '   失败时把返回的 message 展示给学生并允许重试；同一学生多次提交平台只保留最高分。\n' +
  '   上报成功后：停止计时、锁定所有作答交互，页面只展示最终结果与成绩。\n' +
  '   响应契约：{ code, message }。必须检查 code === 0 才显示「成绩已提交」；\n' +
  '   code 非 0 时必须原样展示 message 并允许重试——绝不能把失败当作成功。\n' +
  '3. 禁止访问 localStorage/sessionStorage/cookie、fetch 平台 /api、触碰 window.parent/opener；\n' +
  '   票据由平台父页面自动附带，页面不要读取 location.search 或拼接任何 token。\n\n' +
  '请直接输出完整 HTML 文件内容。'
async function loadSpec() {
  if (!props.labId) return
  loading.value = true
  try {
    const data = await getIntegrationSpec(props.labId)
    specMarkdown.value = data.markdown || ''
    specTitle.value = data.lab_title || ''
    specScore.value = data.total_score || ''
    debugForm.value.total_score = Number(data.total_score) || 100
  } finally {
    loading.value = false
  }
}

async function copyText(text, label) {
  // clipboard API 在非安全上下文 / 无权限时会抛错，降级到 execCommand，
  // 保证「复制给 AI」在本地 http、真实浏览器上都可用。
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* 忽略：正文仍在下方 pre 中可手动全选 */ }
    document.body.removeChild(ta)
  }
  copied.value = label
  ElMessage.success(`${label}已复制`)
}

function fillExample(kind) {
  const max = Number(specScore.value) || 100
  debugForm.value.total_score = kind === 'full' ? max : kind === 'zero' ? 0 : Math.round(max * 0.6 * 10) / 10
  debugForm.value.elapsed_seconds = kind === 'zero' ? 0 : 120
}

async function runDebug() {
  debugging.value = true
  try {
    debugResult.value = await gradeDebug(props.labId, { ...debugForm.value })
    emit('updated') // 后端把摘要回写 last_debug，列表徽标需要刷新
    ElMessage.success(debugResult.value.passed ? '调试通过（未入库）' : '调试未通过（未入库）')
  } finally {
    debugging.value = false
  }
}

// Stage 3 交接：checks 每项带 blocking；环境提示项（发布状态 / 页面文件等）
// 草稿态为 false 属正常，必须渲染成灰色提示而不是红色失败。
function checkClass(c) {
  if (!c.blocking) return 'info'
  return c.ok ? 'ok' : 'bad'
}
function checkFlag(c) {
  if (!c.blocking) return '提示'
  return c.ok ? 'PASS' : 'FAIL'
}

watch(() => props.labId, () => { debugResult.value = null; loadSpec() })
onMounted(loadSpec)
</script>

<style scoped>
.lab-grading-panel { padding: 0 2px 8px; }
.gp-section { margin-bottom: 22px; }
.gp-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}
.gp-title :deep(.el-button) { margin-left: 0; }
.help-icon { color: #94a3b8; cursor: pointer; font-size: 16px; }
.help-icon:hover { color: #409eff; }
.gp-meta { margin-left: auto; font-size: 12px; font-weight: 400; color: #94a3b8; }
.gp-subtitle { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 6px; }
.gp-hint { font-size: 12.5px; color: #64748b; line-height: 1.8; margin-bottom: 8px; }
.gp-hint code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }
.endpoint-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.endpoint {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #2563eb;
  font-size: 13px;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.spec-markdown,
.debug-preview pre {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.debug-form { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.debug-form :deep(.el-button + .el-button) { margin-left: 0; }
.debug-label { font-size: 12.5px; color: #64748b; }
.debug-verdict { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.debug-verdict.pass { color: #059669; }
.debug-verdict.fail { color: #dc2626; }
.debug-verdict span { font-size: 12px; font-weight: 400; color: #94a3b8; }
.check-list { display: grid; gap: 6px; }
.check-item {
  display: grid;
  grid-template-columns: 52px 120px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12.5px;
  background: #f8fafc;
}
.check-item.ok { background: #ecfdf5; }
.check-item.bad { background: #fef2f2; }
.check-item.info { background: #f8fafc; color: #94a3b8; }
.check-flag { font-weight: 700; font-family: 'JetBrains Mono', Consolas, monospace; }
.check-item.ok .check-flag { color: #059669; }
.check-item.bad .check-flag { color: #dc2626; }
.check-name { font-weight: 600; color: #334155; }
.check-item.info .check-name { color: #94a3b8; font-weight: 500; }
.check-detail { color: #64748b; word-break: break-word; }
.check-item.info .check-detail { color: #94a3b8; }
.debug-preview { margin-top: 12px; }
.copy-toast { font-size: 12px; color: #059669; }
.help-doc h4 { margin: 14px 0 8px; color: #1e293b; }
.help-tip-line { font-size: 12.5px; color: #64748b; line-height: 1.8; margin-bottom: 8px; }
.help-doc ol, .help-doc ul { margin: 0 0 10px 22px; line-height: 1.9; color: #475569; font-size: 13px; }
.help-doc code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.help-code {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
</style>
