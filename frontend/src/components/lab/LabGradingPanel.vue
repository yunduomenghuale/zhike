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
        告知 AI 三件事：上报地址、报文格式（只收 <code>total_score</code>，1 位小数，0 ~ 满分）、运行环境（沙箱内通过 <code>LabBridge</code> 桥接）。点击问号看使用示例。
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
    <el-dialog v-model="helpVisible" title="如何使用接入说明" width="720px" append-to-body>
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
        <h4>发给 AI 的提示词示例（整段复制即可用）</h4>
        <pre class="help-code">帮我开发一个校园网故障排查实验页面，要求如下：

1. 交付物：单个 HTML 文件（所有 JS / CSS 内联，不引用任何外部资源）。
2. 实验内容：给出一个拓扑图（可用 SVG 绘制），包含 3 个待排查任务：
   任务一（40 分）找出 VLAN 划分错误；任务二（40 分）修复网关配置；
   任务三（20 分）验证全网连通。每个任务提供交互式判断（选择 / 输入命令）。
3. 界面：显示实验标题、满分（运行时从 LabBridge 读取，不要写死）、
   任务列表与完成状态、作答计时。
4. 提交：学生点「提交成绩」时，按完成情况计算总分（不超过满分），
   调用 LabBridge.reportGrade({ total_score: 总分, elapsed_seconds: 用时秒 }) 上报，
   并把返回结果展示给学生；重复点击要有防抖处理。
5. 运行环境：页面将嵌入平台沙箱 iframe，通过 window.LabBridge 与平台通信：
   - const ctx = await LabBridge.validate()  // 返回 { labId, submissionId, totalScore, gradeEndpoint }
   - await LabBridge.reportGrade(payload)     // 返回平台响应 { code, message, ... }
   - LabBridge.preview === true 表示教师预览模式，此时不要提交。
6. 禁止：访问 localStorage / cookie、请求外部网址、使用 eval。

请直接输出完整 HTML 文件内容。</pre>
      </div>
      <template #footer>
        <el-button type="primary" @click="copyText(helpPromptText, '提示词示例')">复制提示词示例</el-button>
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
const helpPromptText =
  '帮我开发一个校园网故障排查实验页面，要求如下：\n\n' +
  '1. 交付物：单个 HTML 文件（所有 JS / CSS 内联，不引用任何外部资源）。\n' +
  '2. 实验内容：给出一个拓扑图（可用 SVG 绘制），包含 3 个待排查任务：\n' +
  '   任务一（40 分）找出 VLAN 划分错误；任务二（40 分）修复网关配置；\n' +
  '   任务三（20 分）验证全网连通。每个任务提供交互式判断（选择 / 输入命令）。\n' +
  '3. 界面：显示实验标题、满分（运行时从 LabBridge 读取，不要写死）、\n' +
  '   任务列表与完成状态、作答计时。\n' +
  '4. 提交：学生点「提交成绩」时，按完成情况计算总分（不超过满分），\n' +
  '   调用 LabBridge.reportGrade({ total_score: 总分, elapsed_seconds: 用时秒 }) 上报，\n' +
  '   并把返回结果展示给学生；重复点击要有防抖处理。\n' +
  '5. 运行环境：页面将嵌入平台沙箱 iframe，通过 window.LabBridge 与平台通信：\n' +
  '   - const ctx = await LabBridge.validate()  // 返回 { labId, submissionId, totalScore, gradeEndpoint }\n' +
  '   - await LabBridge.reportGrade(payload)     // 返回平台响应 { code, message, ... }\n' +
  '   - LabBridge.preview === true 表示教师预览模式，此时不要提交。\n' +
  '6. 禁止：访问 localStorage / cookie、请求外部网址、使用 eval。\n\n' +
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
.help-doc ol, .help-doc ul { margin: 0 0 10px 22px; line-height: 1.9; color: #475569; font-size: 13px; }
.help-doc code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.help-code {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
</style>
