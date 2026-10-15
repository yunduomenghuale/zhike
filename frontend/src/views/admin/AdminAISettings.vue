<template>
  <div class="page-container ai-settings" v-loading="loading">
    <header class="page-head">
      <div><div class="eyebrow">MODEL OPERATIONS</div><h1>大模型配置</h1><p>按能力配置平台 AI 使用的服务商、模型和访问凭证，四项能力可混搭不同服务商。</p></div>
      <div class="runtime-badge" :class="overallTone"><span></span><div><strong>{{ overallTitle }}</strong><small>{{ overallSubtitle }}</small></div></div>
    </header>

    <section class="effective-card">
      <div class="section-head"><div><h2>当前生效配置</h2></div><el-button :icon="Refresh" @click="load">刷新</el-button></div>
      <el-table :data="effective" class="effective-table">
        <el-table-column label="能力" width="120">
          <template #default="{ row }"><strong>{{ row.capability_display }}</strong><small class="block">{{ capabilityDesc(row.capability) }}</small></template>
        </el-table-column>
        <el-table-column label="服务商 / 模型" min-width="230">
          <template #default="{ row }"><span class="provider-name">{{ row.provider_display }}</span><small class="block">{{ row.model_name || '未设置模型' }}<template v-if="row.timeout || row.voice">（{{ [row.timeout ? '超时 ' + row.timeout + 's' : '', row.voice].filter(Boolean).join(' · ') }}）</template></small></template>
        </el-table-column>
        <el-table-column label="API Key" min-width="170">
          <template #default="{ row }"><code v-if="row.api_key_masked">{{ row.api_key_masked }}</code><span v-else class="muted">未配置</span></template>
        </el-table-column>
        <el-table-column label="实际运行时" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.runtime_is_mock" type="info" effect="light">模拟模式</el-tag>
            <el-tag v-else type="success" effect="light">{{ providerLabel(row.runtime_provider) }}</el-tag>
            <small v-if="row.runtime_is_mock && row.provider !== 'mock'" class="block warn">已配置但回退 Mock</small>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }"><el-tag :type="row.source === 'database' ? 'primary' : 'warning'" effect="plain">{{ row.source === 'database' ? '管理端配置' : '环境变量' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="最近测试" min-width="230">
          <template #default="{ row }">
            <div class="test-cell" :class="row.last_test_status">
              <el-icon><CircleCheck v-if="row.last_test_status === 'success'" /><CircleClose v-else-if="row.last_test_status === 'failed'" /><InfoFilled v-else /></el-icon>
              <div><span>{{ row.last_test_message || '尚未测试' }}</span><small v-if="row.last_tested_at">{{ formatTime(row.last_tested_at) }}</small></div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="testDialog.visible" :title="testDialog.title" width="520px" append-to-body class="test-dialog">
      <div class="test-banner" :class="testDialog.status">
        <el-icon class="banner-icon">
          <CircleCheck v-if="testDialog.status === 'success'" />
          <CircleClose v-else-if="testDialog.status === 'failed'" />
          <InfoFilled v-else />
        </el-icon>
        <div class="banner-text">
          <strong>{{ testDialog.headline }}</strong>
          <p>{{ testDialog.message }}</p>
        </div>
      </div>
      <div v-if="testDialog.fromForm" class="form-note">本次测试使用当前表单填写的参数（未保存）；API Key 留空时沿用已生效配置的 Key。</div>
      <el-descriptions :column="1" size="small" border>
        <el-descriptions-item label="能力">{{ testDialog.capabilityLabel }}</el-descriptions-item>
        <el-descriptions-item label="服务商 / 模型">{{ testDialog.providerModel }}</el-descriptions-item>
        <el-descriptions-item label="接口地址">{{ testDialog.baseUrl || '—' }}</el-descriptions-item>
        <el-descriptions-item label="配置来源">{{ testDialog.sourceLabel }}</el-descriptions-item>
        <el-descriptions-item label="测试请求">{{ testDialog.request || '—' }}</el-descriptions-item>
        <el-descriptions-item label="测试响应">{{ testDialog.response || '—' }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ testDialog.elapsed || '—' }}</el-descriptions-item>
        <el-descriptions-item label="测试时间">{{ testDialog.testedAt || '—' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer><el-button type="primary" @click="testDialog.visible = false">知道了</el-button></template>
    </el-dialog>

    <section class="capability-grid">
      <article v-for="cap in capabilityList" :key="cap.value" class="config-card">
        <div class="card-head">
          <span class="head-icon" :style="{ color: cap.color, background: cap.bg }"><el-icon><component :is="cap.icon" /></el-icon></span>
          <div class="card-title"><h2>{{ cap.label }}</h2><p>{{ cap.desc }}</p></div>
          <el-switch v-model="forms[cap.value].enabled" :disabled="forms[cap.value].provider === 'mock'" active-text="启用" inactive-text="停用" />
        </div>
        <el-form label-position="top" class="config-form">
          <el-form-item label="服务商">
            <el-select v-model="forms[cap.value].provider" @change="(value) => selectProvider(cap.value, value)">
              <el-option v-for="item in cap.providers" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="接口地址">
            <el-input v-model.trim="forms[cap.value].base_url" :disabled="isMock(cap.value) || isLocal(cap.value)" placeholder="https://example.com/v1" />
            <div v-if="isLocal(cap.value)" class="field-note"><el-icon><InfoFilled /></el-icon><span>系统内置模型在本机推理，权重部署时已自动下载，无需接口地址与 Key。</span></div>
          </el-form-item>
          <el-form-item :label="cap.modelLabel">
            <el-input v-model.trim="forms[cap.value].model_name" :disabled="isMock(cap.value)" :placeholder="cap.modelPlaceholder" />
          </el-form-item>
          <template v-if="cap.showTimeout">
            <el-form-item label="超时(秒)">
              <el-input-number v-model="forms[cap.value].timeout" :min="1" :max="3600" :step="30" controls-position="right" :disabled="isMock(cap.value)" style="width:100%" />
              <div class="field-note"><el-icon><Timer /></el-icon><span>单次请求超时；留空默认 {{ cap.timeoutDefault }} 秒。本地模型推理慢建议调大。</span></div>
            </el-form-item>
          </template>
          <template v-if="cap.showVoice">
            <el-form-item label="发音人">
              <el-input v-model.trim="forms[cap.value].voice" :disabled="isMock(cap.value)" placeholder="默认 Cherry；本地 TTS 填服务端说话人 ID" />
            </el-form-item>
          </template>
          <el-form-item label="API Key">
            <el-input v-model="forms[cap.value].api_key" type="password" show-password autocomplete="new-password" :disabled="isMock(cap.value) || isLocal(cap.value)" :placeholder="keyPlaceholder(cap.value)" />
            <div class="secret-note"><el-icon><Lock /></el-icon><span>{{ isLocal(cap.value) ? '系统内置模型无需 Key。' : `加密保存；当前 ${effectiveItem(cap.value).api_key_masked || '未配置'}，留空表示不修改。` }}</span></div>
          </el-form-item>
        </el-form>
        <div class="card-foot">
          <span class="source-tag">来源：{{ effectiveItem(cap.value).source === 'database' ? '管理端配置' : '环境变量' }}</span>
          <el-button :icon="Connection" size="small" :loading="testing === cap.value" @click="testConnection(cap.value)">测试连接</el-button>
        </div>
      </article>
    </section>

    <footer class="action-bar">
      <div><span v-if="dirty">配置有未保存修改</span><span v-else>所有修改已保存</span></div>
      <el-button type="primary" :icon="Check" :loading="saving" :disabled="!dirty || saving" @click="save">保存并应用</el-button>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Check, CircleCheck, CircleClose, Connection, Files, InfoFilled, Lock, Microphone, Refresh, Sort, Timer } from '@element-plus/icons-vue'
import { getAdminAIConfiguration, saveAdminAIConfiguration, testAdminAIConnection } from '@/api/admin'

// 全量服务商（供生效表格/弹窗按值查标签）；卡片下拉按能力收窄：
// DeepSeek 无 embedding/TTS 接口；模拟模式不产生真实向量/音频（64 维假向量
// 还会污染真实向量空间），向量化与语音合成仅保留通义千问 + 本地模型服务；
// 重排序开放通义千问（DashScope 原生 rerank 端点）与系统内置模型；
// 系统内置模型（local）：向量化内置 BGE-M3、重排序内置 Qwen3-Reranker-0.6B，
// 权重部署时自动下载、本机 CPU 推理，无需 Key/接口地址（对话/语音暂无内置实现）；
// 对话生成保留模拟模式，便于无 Key 环境演示流程
const providers = [
  { value:'deepseek', label:'DeepSeek' },
  { value:'tongyi', label:'通义千问' },
  { value:'openai', label:'本地模型服务' },
  { value:'local', label:'系统内置模型' },
  { value:'mock', label:'模拟模式' },
]
const realProviders = providers.filter(i=>i.value!=='mock')
// 预设按能力区分：选服务商时各卡填各自能力的默认模型（TTS 卡不会再被填成聊天模型）
const presets = {
  deepseek:{ base_url:'https://api.deepseek.com/v1', chat:'deepseek-chat', embed:'', rerank:'', tts:'' },
  tongyi:{ base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1', chat:'qwen-plus', embed:'text-embedding-v3', rerank:'gte-rerank-v2', tts:'qwen3-tts-flash' },
  openai:{ base_url:'', chat:'', embed:'', rerank:'', tts:'' },
  local:{ base_url:'', chat:'', embed:'BAAI/bge-m3', rerank:'Qwen/Qwen3-Reranker-0.6B', tts:'' },
  mock:{ base_url:'', chat:'', embed:'', rerank:'', tts:'' },
}
const capabilityList = [
  { value:'chat', label:'对话生成', desc:'目录识别、逐页讲稿、智能出题、知识问答、学情分析', icon:ChatDotRound, color:'#2563eb', bg:'#eff6ff', modelLabel:'对话模型', modelPlaceholder:'例如 qwen-plus / deepseek-chat', showTimeout:true, timeoutDefault:45, providers },
  { value:'embed', label:'向量化', desc:'知识库资料入库与检索', icon:Files, color:'#7c3aed', bg:'#f5f3ff', modelLabel:'向量模型', modelPlaceholder:'例如 text-embedding-v3', showTimeout:true, timeoutDefault:60, providers: realProviders.filter(i=>i.value!=='deepseek') },
  { value:'rerank', label:'重排序', desc:'知识库检索结果按问题语义精排，过滤关键词命中的噪声片段', icon:Sort, color:'#0ea5e9', bg:'#f0f9ff', modelLabel:'重排序模型', modelPlaceholder:'例如 gte-rerank-v2', showTimeout:true, timeoutDefault:60, providers: [{ value:'tongyi', label:'通义千问' }, { value:'local', label:'系统内置模型' }] },
  { value:'tts', label:'语音合成', desc:'PPT 逐页 AI 配音', icon:Microphone, color:'#f59e0b', bg:'#fffbeb', modelLabel:'语音模型', modelPlaceholder:'例如 qwen3-tts-flash', showTimeout:true, showVoice:true, timeoutDefault:120, providers: realProviders.filter(i=>i.value!=='deepseek') },
]

const loading=ref(false), saving=ref(false), testing=ref(''), dirty=ref(false), hydrating=ref(false)
const effective=ref([])
const testDialog=reactive({
  visible:false, title:'', status:'untested', headline:'', message:'',
  capabilityLabel:'', providerModel:'', baseUrl:'', sourceLabel:'',
  request:'', response:'', elapsed:'', testedAt:'', fromForm:false,
})
const forms=reactive({
  chat:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', api_key:'' },
  embed:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', api_key:'' },
  rerank:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', api_key:'' },
  tts:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', api_key:'' },
})

const realCount=computed(()=>effective.value.filter(i=>!i.runtime_is_mock).length)
const overallTone=computed(()=>realCount.value===0?'muted':'active')
const overallTitle=computed(()=>realCount.value===0?'当前为模拟模式':(realCount.value===4?'真实模型已启用':'部分能力为真实模型'))
const overallSubtitle=computed(()=>realCount.value===0?'不会调用外部模型服务':`${realCount.value}/4 项能力已对接真实模型`)
function providerLabel(value){ return providers.find(i=>i.value===value)?.label || value }
function capabilityDesc(value){ return capabilityList.find(i=>i.value===value)?.desc || '' }
function effectiveItem(value){ return effective.value.find(i=>i.capability===value) || {} }
function isMock(value){ return forms[value].provider==='mock' }
function isLocal(value){ return forms[value].provider==='local' }
function keyPlaceholder(value){ if(isLocal(value)) return '系统内置模型无需 API Key'; return effectiveItem(value).api_key_configured ? '已安全保存，留空表示不修改' : '请输入服务商 API Key' }
function formatTime(value){ return value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '' }

watch(forms,()=>{ if(!hydrating.value) dirty.value=true },{deep:true})
function hydrate(items){
  hydrating.value=true
  effective.value=items||[]
  for(const item of items||[]){
    const form=forms[item.capability]
    if(!form) continue
    // 历史/运行时可能给出当前能力已不合法的服务商（如向量化/语音合成曾配过模拟模式，
    // 或未配置时运行时回落 mock）：回退到该卡下拉首项（通义千问），避免展示非法值
    const allowed=(capabilityList.find(c=>c.value===item.capability)||{}).providers||providers
    form.provider=allowed.some(i=>i.value===item.provider) ? item.provider : (allowed[0]?.value||'tongyi')
    form.enabled=Boolean(item.enabled)
    form.base_url=item.base_url||''
    form.model_name=item.model_name||''
    form.timeout=item.timeout==null?null:Number(item.timeout)
    form.voice=item.voice||''
    form.api_key=''
  }
  nextTick(()=>{ dirty.value=false; hydrating.value=false })
}
async function load(){ loading.value=true; try{ hydrate((await getAdminAIConfiguration()).items) } finally{ loading.value=false } }
async function refreshEffective(){ try{ effective.value=(await getAdminAIConfiguration()).items||[] }catch{ /* 保留原状 */ } }
function selectProvider(value, provider){
  const preset=presets[provider]||presets.openai
  forms[value].base_url=preset.base_url
  forms[value].model_name=preset[value]||''
  forms[value].enabled=provider!=='mock'
  forms[value].api_key=''
  // 发音人是服务端相关体系：切服务商时重置（千问 TTS 预设 Cherry，本地服务留空）
  if(value==='tts'){ forms[value].voice = provider==='tongyi' ? 'Cherry' : '' }
}
function openTestDialog(value, result={}){
  const cap=capabilityList.find(c=>c.value===value)
  const item=effectiveItem(value)
  const detail=result.detail||{}
  const status=result.last_test_status||'untested'
  const failedRequest=Boolean(result._failedRequest)
  testDialog.title=`${cap?.label||value} · 连接测试`
  testDialog.status=status
  testDialog.headline=failedRequest?'测试未完成':(status==='success'?'连接成功':status==='failed'?'连接失败':'尚未测试')
  testDialog.message=result.last_test_message||'暂无测试结果'
  // 有 detail 时展示「实际被测的参数与内容」，否则回退生效配置信息
  const providerDisplay=detail.provider_display||item.provider_display||'—'
  const modelName=detail.model||item.model_name||'未设置模型'
  testDialog.capabilityLabel=item.capability_display||cap?.label||value
  testDialog.providerModel=[providerDisplay, modelName].filter(Boolean).join(' · ')
  testDialog.baseUrl=detail.base_url||item.base_url||''
  const src=detail.source||item.source
  testDialog.sourceLabel=src==='database'?'管理端配置':src==='form'?'当前表单（未保存）':'环境变量'
  testDialog.request=detail.request||''
  testDialog.response=detail.response||''
  testDialog.elapsed=detail.elapsed_ms?`${(detail.elapsed_ms/1000).toFixed(1)} 秒`:''
  testDialog.testedAt=formatTime(result.last_tested_at)
  testDialog.fromForm=Boolean(detail.from_form)
  testDialog.visible=true
}
async function testConnection(value){
  testing.value=value
  const form=forms[value]
  try{
    // 测试当前表单填写的值（刚改的模型/接口不必先保存即可测）；Key 留空由后端沿用已生效配置
    const result=await testAdminAIConnection(value, {
      provider:form.provider,
      base_url:form.base_url,
      model_name:form.model_name,
      timeout:form.timeout,
      voice:form.voice,
      api_key:form.api_key,
    })
    await refreshEffective()
    openTestDialog(value, result)
  }catch(error){
    // 请求本身失败（网络异常 / 服务端 500 等）时也用弹窗呈现，便于定位
    await refreshEffective()
    openTestDialog(value, { last_test_status:'failed', last_test_message:error?.message||'请求失败，请稍后重试', last_tested_at:new Date().toISOString(), _failedRequest:true })
  }finally{ testing.value='' }
}
async function save(){
  for(const cap of capabilityList){
    const form=forms[cap.value]
    if(form.enabled && form.provider!=='mock'){
      if(!form.base_url){ ElMessage.warning(`${cap.label}：请填写接口地址`); return }
      if(!form.model_name){ ElMessage.warning(`${cap.label}：请填写模型名称`); return }
      if(!form.api_key && !effectiveItem(cap.value).api_key_configured){ ElMessage.warning(`${cap.label}：请填写 API Key`); return }
    }
    if(form.timeout!=null && (form.timeout<1 || form.timeout>3600)){ ElMessage.warning(`${cap.label}：超时需在 1~3600 秒之间`); return }
  }
  saving.value=true
  try{
    const capabilities=capabilityList.map(cap=>{
      const form={ ...forms[cap.value] }
      if(!form.api_key) delete form.api_key
      return { capability:cap.value, ...form }
    })
    await saveAdminAIConfiguration(capabilities)
    await load()
    ElMessage.success('大模型配置已保存并生效')
  }finally{ saving.value=false }
}
onMounted(load)
</script>

<style scoped>
.ai-settings{color:#0f172a;padding-bottom:110px!important}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,h2,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}.runtime-badge{min-width:230px;padding:12px 15px;border:1px solid #e2e8f0;border-radius:16px;display:flex;align-items:center;gap:11px;background:#fff}.runtime-badge>span{width:10px;height:10px;border-radius:50%;background:#94a3b8;box-shadow:0 0 0 5px #f1f5f9}.runtime-badge>div{display:grid;gap:2px}.runtime-badge small{color:#94a3b8}.runtime-badge.active>span{background:#22c55e;box-shadow:0 0 0 5px #dcfce7}
.effective-card,.config-card{border:1px solid #e5edf8;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.effective-card{padding:20px;margin-bottom:16px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.section-head h2{font-size:18px}.effective-table{width:100%;font-size:14px}.effective-table :deep(.el-table__cell){padding:8px 0;font-size:14px}.effective-table :deep(.el-table__cell .cell){padding:0 10px}.effective-table code{background:#f1f5f9;border-radius:5px;padding:2px 7px;font-size:13px;color:#334155}.provider-name{font-weight:600;color:#0f172a}.muted{color:#64748b;font-size:14px}.warn{color:#d97706;font-size:12px}.block{display:block;margin-top:3px;color:#64748b;font-size:12px}.test-cell{display:flex;align-items:flex-start;gap:7px;color:#334155}.test-cell span{font-size:13px;font-weight:500;word-break:break-all}.test-cell small{display:block;margin-top:2px;color:#64748b;font-size:12px}.test-cell.success{color:#16a34a}.test-cell.failed{color:#dc2626}
.capability-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.config-card{padding:22px}.card-head{display:flex;align-items:center;gap:12px;padding-bottom:17px;border-bottom:1px solid #edf2f7}.card-title{min-width:0;flex:1}.card-head h2{font-size:17px}.card-head p{margin-top:3px;color:#94a3b8;font-size:12px}.head-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;flex:0 0 auto;font-size:19px}.config-form{margin-top:16px}.secret-note{margin-top:7px;color:#94a3b8;font-size:12px;display:flex;align-items:flex-start;gap:5px;line-height:1.5}.field-note{margin-top:7px;color:#94a3b8;font-size:12px;display:flex;align-items:flex-start;gap:5px;line-height:1.5}.card-foot{margin-top:14px;padding-top:13px;border-top:1px solid #edf2f7;display:flex;align-items:center;justify-content:space-between;gap:10px}.source-tag{color:#94a3b8;font-size:12px}
.action-bar{position:sticky;bottom:-36px;z-index:5;margin:18px -36px -36px;padding:15px 36px;border-top:1px solid #e5edf8;background:rgba(255,255,255,.92);backdrop-filter:blur(16px);display:flex;justify-content:flex-end;align-items:center;gap:10px}.action-bar>div{margin-right:auto;color:#94a3b8;font-size:12px}
.test-banner{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;border:1px solid;border-radius:12px;margin-bottom:14px}.test-banner.success{border-color:#bbf7d0;background:#f0fdf4;color:#15803d}.test-banner.failed{border-color:#fecaca;background:#fef2f2;color:#b91c1c}.test-banner.untested{border-color:#e2e8f0;background:#f8fafc;color:#475569}.banner-icon{font-size:22px;margin-top:1px}.banner-text strong{display:block;margin-bottom:4px;font-size:15px}.banner-text p{margin:0;font-size:13px;line-height:1.6;word-break:break-all}.form-note{margin-bottom:12px;padding:8px 12px;border-radius:8px;background:#eff6ff;color:#1d4ed8;font-size:12px;line-height:1.6}.test-dialog :deep(.el-descriptions__content){word-break:break-all;line-height:1.6}
@media(max-width:1200px){.capability-grid{grid-template-columns:1fr}.page-head{align-items:flex-start;flex-direction:column}}@media(max-width:720px){.action-bar{margin-left:-16px;margin-right:-16px;padding-left:16px;padding-right:16px}.action-bar>div{display:none}}
</style>
