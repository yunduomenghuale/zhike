<template>
  <div class="page-container ai-settings" v-loading="loading">
    <header class="page-head">
      <div><div class="eyebrow">MODEL OPERATIONS</div><h1>大模型配置</h1><p>配置平台 AI 能力使用的服务商、模型和访问凭证。</p></div>
      <div class="runtime-badge" :class="statusTone"><span></span><div><strong>{{ runtimeTitle }}</strong><small>{{ runtimeSubtitle }}</small></div></div>
    </header>

    <section class="provider-section">
      <div class="section-head"><div><h2>选择模型服务</h2><p>保存后将应用到知识问答、智能出题、课件讲稿和学情分析。</p></div><el-switch v-model="form.enabled" :disabled="form.provider === 'mock'" active-text="启用真实模型" inactive-text="停用" /></div>
      <div class="provider-grid">
        <button v-for="item in providers" :key="item.value" type="button" class="provider-card" :class="{ active: form.provider === item.value }" @click="selectProvider(item.value)">
          <span class="provider-mark" :style="{ color:item.color, background:item.bg }">{{ item.mark }}</span>
          <span class="provider-copy"><strong>{{ item.label }}</strong><small>{{ item.desc }}</small></span>
          <span class="provider-check"><el-icon><Check /></el-icon></span>
        </button>
      </div>
    </section>

    <section class="config-layout">
      <article class="config-card">
        <div class="card-head"><span class="head-icon blue"><el-icon><SetUp /></el-icon></span><div><h2>接口与模型</h2><p>模型名称需与服务商控制台保持一致。</p></div></div>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="config-form">
          <el-form-item label="接口地址" prop="base_url" class="full">
            <el-input v-model.trim="form.base_url" :disabled="form.provider === 'mock'" placeholder="https://example.com/v1" />
          </el-form-item>
          <el-form-item label="对话模型" prop="chat_model"><el-input v-model.trim="form.chat_model" :disabled="form.provider === 'mock'" placeholder="例如 deepseek-chat" /></el-form-item>
          <el-form-item label="向量模型（可选）"><el-input v-model.trim="form.embed_model" :disabled="form.provider === 'mock'" placeholder="未配置时使用本地兜底向量" /></el-form-item>
          <el-form-item label="语音模型（可选）" class="full"><el-input v-model.trim="form.tts_model" :disabled="form.provider === 'mock'" placeholder="仅需要 AI 配音时填写" /></el-form-item>
          <el-form-item label="API Key" prop="api_key" class="full">
            <el-input v-model="form.api_key" :disabled="form.provider === 'mock'" type="password" show-password autocomplete="new-password" :placeholder="keyPlaceholder">
              <template #prefix><el-icon><Key /></el-icon></template>
            </el-input>
            <div class="secret-note"><el-icon><Lock /></el-icon><span>密钥会加密保存，页面和接口均不会回显明文。</span></div>
          </el-form-item>
        </el-form>
      </article>

      <aside class="side-stack">
        <article class="config-card status-card">
          <div class="card-head"><span class="head-icon green"><el-icon><Connection /></el-icon></span><div><h2>连接状态</h2><p>测试会向当前模型发送一条最小请求。</p></div></div>
          <div class="status-content">
            <div class="status-line"><span>当前服务</span><strong>{{ currentProviderLabel }}</strong></div>
            <div class="status-line"><span>配置来源</span><strong>{{ config.source === 'database' ? '管理端配置' : '环境变量' }}</strong></div>
            <div class="status-line"><span>API Key</span><strong>{{ config.api_key_configured ? '已配置' : '未配置' }}</strong></div>
            <div class="test-result" :class="config.last_test_status || 'untested'">
              <el-icon><CircleCheck v-if="config.last_test_status === 'success'" /><CircleClose v-else-if="config.last_test_status === 'failed'" /><InfoFilled v-else /></el-icon>
              <div><strong>{{ testTitle }}</strong><span>{{ config.last_test_message || '保存配置后可执行连接测试' }}</span><small v-if="config.last_tested_at">{{ formatTime(config.last_tested_at) }}</small></div>
            </div>
          </div>
        </article>
        <article class="security-card"><el-icon><Warning /></el-icon><div><strong>安全提示</strong><p>API Key 属于敏感凭证，请使用服务商提供的最小权限密钥，并定期轮换。</p></div></article>
      </aside>
    </section>

    <footer class="action-bar">
      <div><span v-if="dirty">配置有未保存修改</span><span v-else>所有修改已保存</span></div>
      <el-button :icon="Connection" :disabled="dirty || config.source !== 'database'" :loading="testing" @click="testConnection">测试连接</el-button>
      <el-button type="primary" :icon="Check" :loading="saving" @click="save">保存并应用</el-button>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, CircleCheck, CircleClose, Connection, InfoFilled, Key, Lock, SetUp, Warning } from '@element-plus/icons-vue'
import { getAdminAIConfiguration, saveAdminAIConfiguration, testAdminAIConnection } from '@/api/admin'

const providers = [
  { value:'deepseek', label:'DeepSeek', mark:'DS', desc:'推理与通用对话', color:'#2563eb', bg:'#eff6ff' },
  { value:'tongyi', label:'通义千问', mark:'QW', desc:'对话、向量与语音', color:'#7c3aed', bg:'#f5f3ff' },
  { value:'zhipu', label:'智谱 GLM', mark:'GL', desc:'国产通用大模型', color:'#0f9f6e', bg:'#ecfdf5' },
  { value:'openai', label:'兼容接口', mark:'API', desc:'OpenAI 协议或本地模型', color:'#ea580c', bg:'#fff7ed' },
  { value:'mock', label:'模拟模式', mark:'MO', desc:'不产生外部模型费用', color:'#64748b', bg:'#f1f5f9' },
]
const presets = {
  deepseek:{ base_url:'https://api.deepseek.com/v1', chat_model:'deepseek-chat', embed_model:'', tts_model:'' },
  tongyi:{ base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1', chat_model:'qwen-plus', embed_model:'text-embedding-v3', tts_model:'' },
  zhipu:{ base_url:'https://open.bigmodel.cn/api/paas/v4', chat_model:'glm-4-flash', embed_model:'embedding-3', tts_model:'' },
  openai:{ base_url:'', chat_model:'', embed_model:'', tts_model:'' },
  mock:{ base_url:'', chat_model:'', embed_model:'', tts_model:'' },
}
const loading=ref(false), saving=ref(false), testing=ref(false), dirty=ref(false), hydrating=ref(false), formRef=ref()
const config=reactive({ source:'environment', api_key_configured:false, last_test_status:'untested', last_test_message:'', last_tested_at:null })
const form=reactive({ provider:'mock', enabled:false, base_url:'', chat_model:'', embed_model:'', tts_model:'', api_key:'' })
const rules={
  base_url:[{ validator:(_,v,cb)=> form.enabled && form.provider!=='mock' && !v ? cb(new Error('请输入接口地址')) : cb(), trigger:'blur' }],
  chat_model:[{ validator:(_,v,cb)=> form.enabled && form.provider!=='mock' && !v ? cb(new Error('请输入对话模型')) : cb(), trigger:'blur' }],
  api_key:[{ validator:(_,v,cb)=> form.enabled && form.provider!=='mock' && !v && !config.api_key_configured ? cb(new Error('请输入 API Key')) : cb(), trigger:'blur' }],
}
const currentProviderLabel=computed(()=>providers.find(i=>i.value===form.provider)?.label || form.provider)
const keyPlaceholder=computed(()=>config.api_key_configured ? '已安全保存，留空表示不修改' : '请输入服务商 API Key')
const testTitle=computed(()=>config.last_test_status==='success'?'连接成功':config.last_test_status==='failed'?'连接失败':'尚未测试')
const statusTone=computed(()=>config.last_test_status==='failed'?'danger':form.enabled&&form.provider!=='mock'?'active':'muted')
const runtimeTitle=computed(()=>form.enabled&&form.provider!=='mock'?'真实模型已启用':'当前为模拟模式')
const runtimeSubtitle=computed(()=>form.enabled&&form.provider!=='mock'?`${currentProviderLabel.value} · ${form.chat_model||'未设置模型'}`:'不会调用外部模型服务')

watch(form,()=>{ if(!hydrating.value) dirty.value=true },{deep:true})
function formatTime(value){return new Date(value).toLocaleString('zh-CN',{hour12:false})}
function hydrate(data){ hydrating.value=true; Object.assign(config,data); Object.assign(form,{provider:data.provider||'mock',enabled:Boolean(data.enabled),base_url:data.base_url||'',chat_model:data.chat_model||'',embed_model:data.embed_model||'',tts_model:data.tts_model||'',api_key:''}); nextTick(()=>{dirty.value=false;hydrating.value=false}) }
async function load(){loading.value=true;try{hydrate(await getAdminAIConfiguration())}finally{loading.value=false}}
function selectProvider(value){if(form.provider===value)return;form.provider=value;Object.assign(form,presets[value]);form.enabled=value!=='mock';form.api_key='';config.api_key_configured=false;formRef.value?.clearValidate()}
async function save(){if(!(await formRef.value?.validate().catch(()=>false)))return;saving.value=true;try{const payload={...form};if(!payload.api_key)delete payload.api_key;const result=await saveAdminAIConfiguration(payload);hydrate(result);ElMessage.success('大模型配置已保存并生效')}finally{saving.value=false}}
async function testConnection(){testing.value=true;try{const result=await testAdminAIConnection();Object.assign(config,result);ElMessage.success(result.last_test_message||'连接成功')}catch{await load()}finally{testing.value=false}}
onMounted(load)
</script>

<style scoped>
.ai-settings{color:#0f172a;padding-bottom:110px!important}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,h2,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}.runtime-badge{min-width:230px;padding:12px 15px;border:1px solid #e2e8f0;border-radius:16px;display:flex;align-items:center;gap:11px;background:#fff}.runtime-badge>span{width:10px;height:10px;border-radius:50%;background:#94a3b8;box-shadow:0 0 0 5px #f1f5f9}.runtime-badge>div{display:grid;gap:2px}.runtime-badge small{color:#94a3b8}.runtime-badge.active>span{background:#22c55e;box-shadow:0 0 0 5px #dcfce7}.runtime-badge.danger>span{background:#ef4444;box-shadow:0 0 0 5px #fee2e2}
.provider-section,.config-card{border:1px solid #e5edf8;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.provider-section{padding:20px;margin-bottom:16px}.section-head,.card-head{display:flex;align-items:center;justify-content:space-between;gap:16px}.section-head h2,.card-head h2{font-size:18px}.section-head p,.card-head p{margin-top:4px;color:#94a3b8;font-size:12px}.provider-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-top:18px}.provider-card{min-width:0;padding:14px;border:1px solid #e8eef6;border-radius:16px;background:#fbfdff;display:flex;align-items:center;gap:10px;text-align:left;cursor:pointer;transition:.18s}.provider-card:hover{border-color:#bfdbfe;transform:translateY(-1px)}.provider-card.active{border-color:#60a5fa;background:#eff6ff;box-shadow:0 0 0 2px rgba(59,130,246,.08)}.provider-mark{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;flex:0 0 auto;font-size:12px;font-weight:850}.provider-copy{min-width:0;display:grid;gap:3px}.provider-copy small{color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.provider-check{margin-left:auto;width:19px;height:19px;border:1px solid #cbd5e1;border-radius:50%;display:grid;place-items:center;color:transparent}.provider-card.active .provider-check{border-color:#3b82f6;background:#3b82f6;color:#fff}
.config-layout{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(310px,.7fr);gap:16px}.config-card{padding:22px}.card-head{justify-content:flex-start;padding-bottom:17px;border-bottom:1px solid #edf2f7}.head-icon{width:44px;height:44px;border-radius:13px;display:grid;place-items:center;font-size:20px}.head-icon.blue{color:#2563eb;background:#eff6ff}.head-icon.green{color:#16a34a;background:#ecfdf5}.config-form{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;margin-top:18px}.config-form .full{grid-column:1/-1}.secret-note{margin-top:7px;color:#94a3b8;font-size:12px;display:flex;align-items:center;gap:5px}.side-stack{display:grid;align-content:start;gap:16px}.status-content{display:grid;gap:13px;margin-top:18px}.status-line{display:flex;align-items:center;justify-content:space-between;color:#64748b;font-size:13px}.status-line strong{color:#334155}.test-result{padding:14px;border-radius:15px;background:#f8fafc;color:#64748b;display:flex;gap:10px}.test-result.success{background:#f0fdf4;color:#16a34a}.test-result.failed{background:#fef2f2;color:#dc2626}.test-result>div{min-width:0;display:grid;gap:3px}.test-result span{color:#64748b;font-size:12px;word-break:break-word}.test-result small{color:#94a3b8}.security-card{padding:17px;border:1px solid #fde7bd;border-radius:18px;background:#fffbeb;color:#d97706;display:flex;gap:11px}.security-card p{margin-top:4px;color:#92723b;font-size:12px;line-height:1.6}
.action-bar{position:sticky;bottom:-36px;z-index:5;margin:18px -36px -36px;padding:15px 36px;border-top:1px solid #e5edf8;background:rgba(255,255,255,.92);backdrop-filter:blur(16px);display:flex;justify-content:flex-end;align-items:center;gap:10px}.action-bar>div{margin-right:auto;color:#94a3b8;font-size:12px}
@media(max-width:1200px){.provider-grid{grid-template-columns:repeat(3,1fr)}.config-layout{grid-template-columns:1fr}}@media(max-width:720px){.page-head,.section-head{align-items:flex-start;flex-direction:column}.provider-grid{grid-template-columns:1fr}.config-form{grid-template-columns:1fr}.config-form .full{grid-column:auto}.action-bar{margin-left:-16px;margin-right:-16px;padding-left:16px;padding-right:16px}.action-bar>div{display:none}}
</style>
