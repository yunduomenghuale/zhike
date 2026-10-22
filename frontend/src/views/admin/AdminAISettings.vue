<template>
  <div class="page-container ai-settings" v-loading="loading">
    <header class="page-head">
      <div><div class="eyebrow">MODEL OPERATIONS</div><h1>大模型配置</h1><p>按能力配置平台 AI 使用的服务商、模型和访问凭证，四项能力可混搭不同服务商；调用统计与配置变更记录便于运维追溯。</p></div>
      <div class="runtime-badge" :class="overallTone"><span></span><div><strong>{{ overallTitle }}</strong><small>{{ overallSubtitle }}</small></div></div>
    </header>

    <el-tabs v-model="activeTab" class="ai-tabs" @tab-change="onTabChange">
      <!-- ================= Tab 1：能力配置 ================= -->
      <el-tab-pane label="能力配置" name="config">
        <section class="effective-card">
          <div class="section-head"><div><h2>当前生效配置</h2></div><el-button :icon="Refresh" @click="load">刷新</el-button></div>
          <el-table :data="effective" class="effective-table" scrollbar-always-on>
            <el-table-column label="能力" width="120">
              <template #default="{ row }"><strong>{{ row.capability_display }}</strong><small class="block">{{ capabilityDesc(row.capability) }}</small></template>
            </el-table-column>
            <el-table-column label="服务商 / 模型" min-width="230">
              <template #default="{ row }"><span class="provider-name">{{ row.provider_display }}</span><small class="block">{{ row.model_name || '未设置模型' }}<template v-if="row.timeout || row.voice">（{{ [row.timeout ? '超时 ' + row.timeout + 's' : '', row.voice].filter(Boolean).join(' · ') }}）</template></small><el-tag v-if="row.supports_vision" size="small" type="success" effect="plain" class="vision-tag" title="问答已开启图片上传入口">图片</el-tag></template>
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
              <template v-if="cap.showVision">
                <el-form-item label="支持图片（多模态）">
                  <el-switch v-model="forms[cap.value].supports_vision" :disabled="isMock(cap.value)" active-text="显示图片上传入口" inactive-text="隐藏" />
                  <div class="field-note"><el-icon><InfoFilled /></el-icon><span>开启后学生/教师端问答显示图片上传入口，图片随问题一起发给对话模型；所用模型无视觉能力时请关闭，否则发送图片会被接口拒绝。</span></div>
                  <div v-if="visionMismatch" class="field-note warn-note"><el-icon><WarningFilled /></el-icon><span>{{ visionMismatch }}</span></div>
                </el-form-item>
              </template>
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
      </el-tab-pane>

      <!-- ================= Tab 2：调用统计 ================= -->
      <el-tab-pane label="调用统计" name="stats">
        <section class="stats-panel" v-loading="statsLoading">
          <div class="stats-toolbar">
            <el-date-picker
              v-model="period.range"
              type="daterange"
              value-format="YYYY-MM-DD"
              unlink-panels
              range-separator="~"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :shortcuts="rangeShortcuts"
              clearable
              style="width:270px"
              @change="onRangeChange"
            />
            <span class="days-input">
              <span class="days-label">近</span>
              <el-input-number v-model="period.days" :min="1" :max="365" :step="1" controls-position="right" style="width:108px" @change="onDaysChange" />
              <span class="days-label">天</span>
            </span>
            <el-button :icon="Refresh" @click="refreshStatsAndLogs">刷新</el-button>
            <el-button :icon="Download" :loading="exporting" @click="exportCsv">导出 CSV</el-button>
            <span class="toolbar-note">统计范围为平台全部 AI 调用（含 Mock 回退）；本地内置模型按条数计量，无 token。</span>
          </div>
          <p v-if="windowText" class="window-note">当前窗口 {{ windowText }}</p>

          <div v-if="stats?.alerts?.length" class="alerts">
            <div v-for="(alert, i) in stats.alerts" :key="i" class="alert" :class="alert.level">
              <el-icon><WarningFilled v-if="alert.level === 'warning'" /><InfoFilled v-else /></el-icon>
              <span>{{ alert.message }}</span>
            </div>
          </div>

          <div class="stat-cards">
            <div class="stat-card">
              <small>总调用</small>
              <strong>{{ fmtNum(stats?.totals?.calls) }}</strong>
              <span class="delta" :class="totalsDelta.calls.tone" :title="`上周期 ${fmtNum(stats?.totals_previous?.calls)} 次`">{{ totalsDelta.calls.text }}</span>
            </div>
            <div class="stat-card">
              <small>成功率</small>
              <strong :class="successTone">{{ fmtPct(stats?.totals?.success_rate) }}</strong>
              <span class="sub">成功 {{ stats?.totals?.success ?? 0 }} · 失败 {{ stats?.totals?.failed ?? 0 }}</span>
              <span class="delta" :class="totalsDelta.success_rate.tone" :title="`上周期 ${fmtPct(stats?.totals_previous?.success_rate)}`">{{ totalsDelta.success_rate.text }}</span>
            </div>
            <div class="stat-card">
              <small>Mock 回退</small>
              <strong :class="{ warn: stats?.totals?.mock_calls }">{{ fmtNum(stats?.totals?.mock_calls) }}</strong>
              <span class="sub">结果可能是占位内容</span>
              <span class="delta" :class="totalsDelta.mock_calls.tone" :title="`上周期 ${fmtNum(stats?.totals_previous?.mock_calls)} 次`">{{ totalsDelta.mock_calls.text }}</span>
            </div>
            <div class="stat-card">
              <small>Token 合计</small>
              <strong>{{ fmtNum(stats?.totals?.total_tokens) }}</strong>
              <span class="sub">入 {{ fmtNum(stats?.totals?.prompt_tokens) }} · 出 {{ fmtNum(stats?.totals?.completion_tokens) }}</span>
              <span class="delta" :class="totalsDelta.total_tokens.tone" :title="`上周期 ${fmtNum(stats?.totals_previous?.total_tokens)}`">{{ totalsDelta.total_tokens.text }}</span>
            </div>
            <div class="stat-card">
              <small>平均耗时</small>
              <strong>{{ avgLatencyText }}</strong>
              <span class="sub">P95 {{ p95Text }}</span>
              <span class="delta" :class="totalsDelta.avg_latency_ms.tone" :title="`上周期 ${fmtMs(stats?.totals_previous?.avg_latency_ms)}`">{{ totalsDelta.avg_latency_ms.text }}</span>
            </div>
          </div>

          <div class="chart-card">
            <div class="chart-head">
              <h3>调用趋势<small v-if="trendPoints.length">（{{ trendPoints.length }} {{ trendWeekly ? '周' : '天' }} · 柱为当前周期，虚线为上周期）</small></h3>
              <el-radio-group v-model="chartMetric" size="small">
                <el-radio-button value="calls">调用次数</el-radio-button>
                <el-radio-button value="total_tokens">Token</el-radio-button>
                <el-radio-button value="avg_latency_ms">平均耗时</el-radio-button>
              </el-radio-group>
            </div>
            <svg v-if="trendPoints.length" viewBox="0 0 680 220" class="trend-chart" preserveAspectRatio="xMidYMid meet">
              <line v-for="g in gridValues" :key="'grid' + g" :x1="36" :x2="670" :y1="yOf(g)" :y2="yOf(g)" stroke="#e8eef7" stroke-width="1" />
              <text :x="30" :y="yOf(axisMax) + 4" text-anchor="end" class="axis-label">{{ fmtMetric(axisMax) }}</text>
              <text :x="30" :y="yOf(0) + 4" text-anchor="end" class="axis-label">0</text>
              <polyline v-if="hasPrevSeries" :points="prevPoints" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5 4" stroke-linecap="round" />
              <g v-for="(row, i) in trendPoints" :key="row.day">
                <rect :x="barX(i)" :y="yOf(row.value)" :width="barWidth" :height="barH(row.value)" rx="2" fill="#2563eb">
                  <title>{{ row.label }} · {{ metricLabel }} {{ fmtMetric(row.value) }} · 上周期 {{ fmtMetric(row.prev) }}</title>
                </rect>
                <rect v-if="chartMetric === 'calls' && row.failed" :x="barX(i)" :y="yOf(row.value)" :width="barWidth" :height="barH(row.failed)" rx="2" fill="#dc2626" />
                <text v-if="i % labelEvery === 0" :x="barX(i) + barWidth / 2" :y="212" text-anchor="middle" class="axis-label">{{ row.label }}</text>
              </g>
            </svg>
            <el-empty v-else description="该时间范围内暂无调用记录" :image-size="60" />
            <p v-if="trendSparseHint" class="chart-hint"><el-icon><InfoFilled /></el-icon>{{ trendSparseHint }}</p>
          </div>

          <div class="dist-card" :class="'dim-' + distDim">
            <div class="dist-head">
              <h3>调用分布</h3>
              <el-radio-group v-model="distDim" size="small">
                <el-radio-button value="capability">按能力</el-radio-button>
                <el-radio-button value="scene">按场景</el-radio-button>
                <el-radio-button value="user">按触发人</el-radio-button>
              </el-radio-group>
            </div>
            <el-empty v-if="!distRows.length" description="该时间范围内暂无调用记录" :image-size="60" />
            <template v-else>
              <div v-for="grp in distGroups" :key="grp.group" class="dist-group">
                <div v-if="grp.group" class="dist-group-title">{{ grp.group }}<small>共 {{ fmtNum(grp.calls) }} 次</small></div>
                <button v-for="row in grp.rows" :key="row.key" type="button" class="dist-row" @click="filterByDistRow(row)">
                  <span class="dist-name" :title="row.label">{{ row.label }}</span>
                  <span class="dist-bar"><i :style="{ width: distBarWidth(row) + '%' }"></i></span>
                  <span class="dist-calls">{{ fmtNum(row.calls) }}</span>
                  <span class="dist-pct">{{ distPct(row) }}</span>
                  <span class="dist-latency" :title="row.calls < 3 ? '样本不足 3 次，不展示耗时' : `平均耗时 ${fmtMs(row.avg_latency)}`">{{ row.calls < 3 ? '—' : fmtMs(row.avg_latency) }}</span>
                  <span class="dist-badges">
                    <em v-if="row.failed" class="badge fail" :title="`失败 ${row.failed} 次`">失败 {{ row.failed }}</em>
                    <em v-if="row.mock_calls" class="badge mock" :title="`Mock 回退 ${row.mock_calls} 次`">Mock {{ row.mock_calls }}</em>
                  </span>
                </button>
              </div>
              <p class="dist-hint">点击任意一行，可按该维度联动筛选下方调用流水</p>
            </template>
          </div>

          <div class="logs-card">
            <div class="logs-head">
              <h3>调用流水</h3>
              <div class="logs-filters">
                <el-select v-model="logFilters.capability" placeholder="能力" clearable style="width:120px">
                  <el-option v-for="item in capabilityOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-select v-model="logFilters.scene" placeholder="场景" clearable style="width:150px">
                  <el-option v-for="item in sceneOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-select v-model="logFilters.provider" placeholder="服务商" clearable style="width:140px">
                  <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-select v-model="logFilters.triggered_by" placeholder="触发人" clearable style="width:130px">
                  <el-option v-for="item in triggeredByOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-select v-model="logFilters.success" placeholder="结果" clearable style="width:100px">
                  <el-option label="成功" value="true" />
                  <el-option label="失败" value="false" />
                </el-select>
                <el-input v-model.trim="logFilters.keyword" placeholder="追溯ID / 输入摘要" clearable style="width:190px" @keyup.enter="applyLogFilters" />
                <el-button :icon="Search" @click="applyLogFilters">查询</el-button>
              </div>
            </div>
            <el-table :data="logs" size="small" v-loading="logsLoading" scrollbar-always-on>
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="能力" width="90">
                <template #default="{ row }">{{ row.capability_display }}</template>
              </el-table-column>
              <el-table-column label="场景" width="110">
                <template #default="{ row }">{{ row.scene_display }}</template>
              </el-table-column>
              <el-table-column label="服务商 / 模型" min-width="180">
                <template #default="{ row }"><span>{{ row.provider_display }}</span><small class="block">{{ row.model_name || '—' }}</small></template>
              </el-table-column>
              <el-table-column label="结果" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.success ? 'success' : 'danger'" size="small" effect="light">{{ row.success ? '成功' : '失败' }}</el-tag>
                  <el-tag v-if="row.is_mock" type="info" size="small" effect="plain" class="mock-tag">Mock</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="80">
                <template #default="{ row }">{{ fmtMs(row.latency_ms) }}</template>
              </el-table-column>
              <el-table-column label="Token / 条数" width="110">
                <template #default="{ row }">
                  <span v-if="row.total_tokens != null">{{ fmtNum(row.total_tokens) }}</span>
                  <span v-else-if="row.item_count != null">{{ fmtNum(row.item_count) }} 条</span>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="触发人" width="100">
                <template #default="{ row }">{{ row.triggered_by_name || '—' }}</template>
              </el-table-column>
              <el-table-column label="课程" min-width="120">
                <template #default="{ row }"><span :title="row.course_name || ''">{{ row.course_name || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="追溯ID" width="150">
                <template #default="{ row }"><code :title="row.trace_id">{{ row.trace_id || '—' }}</code></template>
              </el-table-column>
              <el-table-column label="输入摘要" min-width="140">
                <template #default="{ row }"><span class="ellipsis" :title="row.input_preview || ''">{{ row.input_preview || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="错误" min-width="140">
                <template #default="{ row }"><span v-if="row.error" class="error-text ellipsis" :title="row.error">{{ row.error }}</span><span v-else class="muted">—</span></template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-if="logsTotal > logsPageSize"
              background
              class="pager"
              layout="sizes, prev, pager, next, total"
              :total="logsTotal"
              :page-size="logsPageSize"
              :current-page="logsPage"
              :page-sizes="[10, 20, 50, 100]"
              @current-change="(page) => { logsPage = page; loadLogs() }"
              @size-change="(size) => { logsPageSize = size; logsPage = 1; loadLogs() }"
            />
          </div>
        </section>
      </el-tab-pane>

      <!-- ================= Tab 3：变更记录 ================= -->
      <el-tab-pane label="变更记录" name="changes">
        <section class="changes-panel" v-loading="changesLoading">
          <div class="stats-toolbar">
            <el-select v-model="changeCapability" placeholder="能力" clearable style="width:140px" @change="reloadChanges">
              <el-option v-for="item in capabilityOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-button :icon="Refresh" @click="reloadChanges">刷新</el-button>
            <span class="toolbar-note">每次管理端保存配置都会记录字段级旧值→新值（审计单轨，与「操作审计」页同源）；API Key 只记录「已配置 / 未配置」，不落密钥内容。</span>
          </div>
          <div class="changes-card">
            <el-table :data="changes" size="small" scrollbar-always-on>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="能力" width="110">
                <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.target_label || '—' }}</el-tag></template>
              </el-table-column>
              <el-table-column label="操作人" width="140">
                <template #default="{ row }">{{ row.actor_name || '系统' }}</template>
              </el-table-column>
              <el-table-column label="变更明细" min-width="360">
                <template #default="{ row }">
                  <div class="change-list">
                    <template v-for="(group, gi) in changeGroups(row)" :key="gi">
                      <span v-for="c in group.changes" :key="c.field" class="change-item">
                        <em>{{ group.capability_display || group.capability }} · {{ c.label }}</em>
                        <span class="old">{{ c.old || '（空）' }}</span>
                        <el-icon><Right /></el-icon>
                        <span class="new">{{ c.new || '（空）' }}</span>
                      </span>
                    </template>
                    <span v-if="!changeGroups(row).length" class="muted">—</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-if="changesTotal > changesPageSize"
              background
              class="pager"
              layout="prev, pager, next, total"
              :total="changesTotal"
              :page-size="changesPageSize"
              :current-page="changesPage"
              @current-change="(page) => { changesPage = page; loadChanges() }"
            />
          </div>
        </section>
      </el-tab-pane>

      <!-- ================= Tab 4：问答质量 ================= -->
      <el-tab-pane label="问答质量" name="quality">
        <section class="stats-panel" v-loading="qaLoading">
          <div class="stats-toolbar">
            <el-date-picker
              v-model="period.range"
              type="daterange"
              value-format="YYYY-MM-DD"
              unlink-panels
              range-separator="~"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :shortcuts="rangeShortcuts"
              clearable
              style="width:270px"
              @change="onRangeChange"
            />
            <span class="days-input">
              <span class="days-label">近</span>
              <el-input-number v-model="period.days" :min="1" :max="365" :step="1" controls-position="right" style="width:108px" @change="onDaysChange" />
              <span class="days-label">天</span>
            </span>
            <el-button :icon="Refresh" @click="reloadQA">刷新</el-button>
            <span class="toolbar-note">统计范围为平台全部知识库问答（含章节内提问与课程问答页提问）；纯图片提问跳过检索、不计入为空率分母。</span>
          </div>
          <p v-if="qaWindowText" class="window-note">当前窗口 {{ qaWindowText }}</p>

          <div v-if="qa?.alerts?.length" class="alerts">
            <div v-for="(alert, i) in qa.alerts" :key="i" class="alert" :class="alert.level">
              <el-icon><WarningFilled v-if="alert.level !== 'info'" /><InfoFilled v-else /></el-icon>
              <span>{{ alert.title }}：{{ alert.detail }}</span>
            </div>
          </div>

          <div class="stat-cards qa-cards">
            <div class="stat-card">
              <small>提问总量<QaHelp text="窗口内学生向 AI 助手提出的问题总数（含章节内提问与课程问答页提问）。" /></small>
              <strong>{{ fmtNum(qa?.totals?.questions) }}</strong>
              <span class="sub">跳过检索 {{ fmtNum(qa?.totals?.skip_retrieval) }} · 收到评价 {{ fmtNum(qa?.totals?.feedback?.rated) }}</span>
            </div>
            <div class="stat-card">
              <small>检索为空率<QaHelp text="检索未命中任何课程片段的提问占比。分母已排除纯图片提问（跳过检索、直接走视觉理解）。偏高说明课程资料对问题的覆盖不足。" /></small>
              <strong :class="qaRateTone(qa?.totals?.empty_retrieval?.rate, { badAbove: 0.3, warnAbove: 0.2 })">{{ fmtPct(qa?.totals?.empty_retrieval?.rate) }}</strong>
              <span class="sub">空检索 {{ fmtNum(qa?.totals?.empty_retrieval?.count) }} 条</span>
              <span class="delta" :class="qaDelta(qa?.totals?.empty_retrieval?.rate, qa?.totals?.empty_retrieval?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.empty_retrieval?.rate_previous)}`">{{ qaDelta(qa?.totals?.empty_retrieval?.rate, qa?.totals?.empty_retrieval?.rate_previous).text }}</span>
            </div>
            <div class="stat-card">
              <small>改写触发率<QaHelp text="多轮追问时，系统把口语化问题改写成可独立检索的问题的占比（仅用于检索，学生看到的仍是原问题）。首轮提问天然不触发改写。" /></small>
              <strong>{{ fmtPct(qa?.totals?.rewrite?.rate) }}</strong>
              <span class="sub">触发改写 {{ fmtNum(qa?.totals?.rewrite?.count) }} 条</span>
              <span class="delta" :class="qaDelta(qa?.totals?.rewrite?.rate, qa?.totals?.rewrite?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.rewrite?.rate_previous)}`">{{ qaDelta(qa?.totals?.rewrite?.rate, qa?.totals?.rewrite?.rate_previous).text }}</span>
            </div>
            <div class="stat-card">
              <small>学生好评率<QaHelp text="学生点「有用」的占比，分母为点过评价的提问（有用 ÷（有用+无用））。请配合「评价覆盖率」一起看，避免小样本误导。" /></small>
              <strong :class="qaRateTone(qa?.totals?.feedback?.rate, { badBelow: 0.6, warnBelow: 0.8 })">{{ fmtPct(qa?.totals?.feedback?.rate) }}</strong>
              <span class="sub">有用 {{ fmtNum(qa?.totals?.feedback?.positive) }} / {{ fmtNum(qa?.totals?.feedback?.rated) }}</span>
              <span class="delta" :class="qaDelta(qa?.totals?.feedback?.rate, qa?.totals?.feedback?.rate_previous, { goodWhenUp: true }).tone" :title="`上周期 ${fmtPct(qa?.totals?.feedback?.rate_previous)}`">{{ qaDelta(qa?.totals?.feedback?.rate, qa?.totals?.feedback?.rate_previous, { goodWhenUp: true }).text }}</span>
            </div>
            <div class="stat-card">
              <small>评价覆盖率<QaHelp text="收到学生评价的提问占比（分母为全部提问）。覆盖率低时，好评率的参考意义有限。" /></small>
              <strong>{{ fmtPct(qa?.totals?.feedback?.coverage) }}</strong>
              <span class="sub">评价 {{ fmtNum(qa?.totals?.feedback?.rated) }} / {{ fmtNum(qa?.totals?.questions) }} 条</span>
              <span class="delta" :class="qaDelta(qa?.totals?.feedback?.coverage, qa?.totals?.feedback?.coverage_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.feedback?.coverage_previous)}`">{{ qaDelta(qa?.totals?.feedback?.coverage, qa?.totals?.feedback?.coverage_previous).text }}</span>
            </div>
            <div class="stat-card">
              <small>兜底触发率<QaHelp text="当前轮检索为空时，用上一轮检索到的片段继续作答的提问占比。偏高说明追问场景下检索连续落空。" /></small>
              <strong :class="qaRateTone(qa?.totals?.fallback?.rate, { badAbove: 0.2, warnAbove: 0.1 })">{{ fmtPct(qa?.totals?.fallback?.rate) }}</strong>
              <span class="sub">触发兜底 {{ fmtNum(qa?.totals?.fallback?.count) }} 条</span>
              <span class="delta" :class="qaDelta(qa?.totals?.fallback?.rate, qa?.totals?.fallback?.rate_previous).tone" :title="`上周期 ${fmtPct(qa?.totals?.fallback?.rate_previous)}`">{{ qaDelta(qa?.totals?.fallback?.rate, qa?.totals?.fallback?.rate_previous).text }}</span>
            </div>
          </div>

          <div class="chart-card">
            <div class="chart-head">
              <h3>日趋势<QaHelp text="按天聚合的检索为空率与学生好评率（分母口径同指标卡）；当天无提问时折线断开。滑动圆点可查看当日数值。" /></h3>
            </div>
            <svg v-if="qaPointCount" viewBox="0 0 680 220" class="trend-chart" preserveAspectRatio="xMidYMid meet">
              <line v-for="g in qaGridValues" :key="'grid' + g" :x1="44" :x2="664" :y1="qaY(g)" :y2="qaY(g)" stroke="#e8eef7" stroke-width="1" />
              <text :x="38" :y="qaY(qaAxisMax) + 4" text-anchor="end" class="axis-label">{{ fmtPct(qaAxisMax) }}</text>
              <text :x="38" :y="qaY(qaAxisMax / 2) + 4" text-anchor="end" class="axis-label">{{ fmtPct(qaAxisMax / 2) }}</text>
              <text :x="38" :y="qaY(0) + 4" text-anchor="end" class="axis-label">0%</text>
              <polyline v-for="(seg, i) in qaFeedbackSegments" :key="'f' + i" :points="seg" fill="none" stroke="#16a34a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              <polyline v-for="(seg, i) in qaEmptySegments" :key="'e' + i" :points="seg" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              <g v-for="(row, i) in qaTrendDays" :key="row.date">
                <circle v-if="row.feedback_rate != null" :cx="qaX(i, qaPointCount)" :cy="qaY(row.feedback_rate)" r="2.5" fill="#16a34a">
                  <title>{{ row.date }} · 学生好评率 {{ fmtPct(row.feedback_rate) }}</title>
                </circle>
                <circle v-if="row.empty_rate != null" :cx="qaX(i, qaPointCount)" :cy="qaY(row.empty_rate)" r="2.5" fill="#dc2626">
                  <title>{{ row.date }} · 检索为空率 {{ fmtPct(row.empty_rate) }}</title>
                </circle>
                <text v-if="i % qaLabelEvery === 0" :x="qaX(i, qaPointCount)" :y="212" text-anchor="middle" class="axis-label">{{ row.date.slice(5) }}</text>
              </g>
            </svg>
            <el-empty v-else description="该时间范围内暂无问答记录" :image-size="60" />
            <p class="chart-legend">
              <span><i class="dot dot-red"></i>检索为空率</span>
              <span><i class="dot dot-green"></i>学生好评率</span>
            </p>
          </div>

          <div class="dist-card">
            <div class="dist-head">
              <h3>上下文降级分布<QaHelp text="上下文超限时的分级重试：L1 丢一半旧历史、L2 仅保留最近两轮、L4 丢弃全部历史。L4 占比突增通常意味着长会话频繁触发超限。" /></h3>
              <span v-if="qa?.degraded" class="toolbar-note">降级率 {{ fmtPct(qa.degraded.degraded_rate) }} · 环比上周期 {{ fmtPct(qa.degraded.degraded_rate_previous) }}</span>
            </div>
            <el-empty v-if="!qa?.totals?.questions" description="该时间范围内暂无问答记录" :image-size="60" />
            <template v-else>
              <div v-for="row in qaDegradedRows" :key="row.key" class="dist-row dist-static">
                <span class="dist-name" :title="row.label">{{ row.label }}</span>
                <span class="dist-bar"><i :style="{ width: row.width + '%', background: row.color }"></i></span>
                <span class="dist-calls">{{ fmtNum(row.count) }}</span>
                <span class="dist-pct">{{ row.pct }}</span>
              </div>
            </template>
          </div>

          <div class="dist-card">
            <div class="dist-head">
              <h3>引用来源分布<QaHelp text="回答引用的片段来源（知识库资料 / 讲解稿 / 课件 PPT / 两者组合）；一条回答引用多个片段时各计一次；早期无来源标记的历史记录计入「其他」。" /></h3>
            </div>
            <el-empty v-if="!qaSourceRows.length" description="该时间范围内暂无问答记录" :image-size="60" />
            <template v-else>
              <div v-for="row in qaSourceRows" :key="row.key" class="dist-row dist-static">
                <span class="dist-name" :title="row.label">{{ row.label }}</span>
                <span class="dist-bar"><i :style="{ width: row.width + '%', background: row.color }"></i></span>
                <span class="dist-calls">{{ fmtNum(row.count) }}</span>
                <span class="dist-pct">{{ row.pct }}</span>
              </div>
            </template>
          </div>

          <div class="logs-card">
            <div class="logs-head">
              <h3>课程质量排行<QaHelp text="按课程聚合的提问量、检索为空率、学生好评率与降级率。红色为超阈值（为空率>30%、降级率>20%），黄色为关注区间（为空率 20~30%、降级率 10~20%）；好评率评价数不足 5 条时不参与着色。" /></h3>
              <span class="toolbar-note">默认按检索为空率从高到低（最需关注的课程在前），点击表头可改排序</span>
            </div>
            <el-table :data="qa?.by_course || []" size="small" class="qa-quality-table" scrollbar-always-on :default-sort="{ prop: 'empty_rate', order: 'descending' }">
              <el-table-column label="课程" min-width="180">
                <template #default="{ row }"><strong>{{ row.course_name }}</strong><small class="block">{{ row.teacher || '—' }}</small></template>
              </el-table-column>
              <el-table-column label="提问量" width="90" sortable :sort-method="(a, b) => a.questions - b.questions">
                <template #default="{ row }">{{ fmtNum(row.questions) }}</template>
              </el-table-column>
              <el-table-column label="为空率" width="100" sortable :sort-by="(row) => row.empty_rate == null ? -1 : row.empty_rate">
                <template #default="{ row }"><span :class="qaRateTone(row.empty_rate, { badAbove: 0.3, warnAbove: 0.2 })">{{ fmtPct(row.empty_rate) }}</span></template>
              </el-table-column>
              <el-table-column label="好评率" width="100" sortable :sort-by="(row) => row.feedback_rate == null ? -1 : row.feedback_rate">
                <template #default="{ row }">
                  <span v-if="row.rated < 5" class="muted">样本少</span>
                  <span v-else :class="qaRateTone(row.feedback_rate, { badBelow: 0.6, warnBelow: 0.8 })">{{ fmtPct(row.feedback_rate) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="评价数" width="90" sortable :sort-method="(a, b) => a.rated - b.rated">
                <template #default="{ row }">{{ fmtNum(row.rated) }}</template>
              </el-table-column>
              <el-table-column label="降级率" width="100" sortable :sort-by="(row) => row.degraded_rate == null ? -1 : row.degraded_rate">
                <template #default="{ row }"><span :class="qaRateTone(row.degraded_rate, { badAbove: 0.2, warnAbove: 0.1 })">{{ fmtPct(row.degraded_rate) }}</span></template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <!-- 保存栏必须放在 el-tabs 之外：el-tabs__content 自带 overflow:hidden，
         栏的负底边距(-36px,用于伸进页面底边距)会被它裁掉底部（保存按钮被切），
         且 sticky 会以 el-tabs__content 为吸附容器、永远吸不到面板底部 -->
    <footer v-if="activeTab === 'config'" class="action-bar">
      <div><span v-if="dirty">配置有未保存修改</span><span v-else>所有修改已保存</span></div>
      <el-button type="primary" :icon="Check" :loading="saving" :disabled="!dirty || saving" @click="save">保存并应用</el-button>
    </footer>

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
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTooltip } from 'element-plus'
import { ChatDotRound, Check, CircleCheck, CircleClose, Connection, Download, Files, InfoFilled, Lock, Microphone, Refresh, Right, Search, Sort, Timer, WarningFilled } from '@element-plus/icons-vue'
import {
  getAdminAIConfiguration, saveAdminAIConfiguration, testAdminAIConnection,
  getAdminAICallStats, listAdminAICallLogs, exportAdminAICallLogs, listAdminActionLogs,
  getAdminQAQualityStats,
} from '@/api/admin'

// 指标说明气泡：统计字样右上角的小问号，悬停显示口径解释（问答质量看板）
const QaHelp = defineComponent({
  name: 'QaHelp',
  props: { text: { type: String, required: true } },
  setup(props) {
    return () => h(ElTooltip, { content: props.text, placement: 'top', 'show-after': 150 }, {
      default: () => h('span', { class: 'qa-help' }, '?'),
    })
  },
})

// 全量服务商（供生效表格/弹窗按值查标签）；卡片下拉按能力收窄：
// DeepSeek 无 embedding/TTS 接口；模拟模式不产生真实向量/音频（64 维假向量
// 还会污染真实向量空间），向量化与语音合成仅保留通义千问 + 本地模型服务；
// 重排序开放通义千问（DashScope 原生 rerank 端点）与系统内置模型；
// 系统内置模型（local）：向量化内置 BGE-M3、重排序内置 Qwen3-Reranker-0.6B，
// 权重部署时自动下载、本机 CPU 推理，无需 Key/接口地址（对话/语音暂无内置实现）；
// 对话卡过滤掉 local（保留 mock 供无 Key 演示）、语音卡同样不含 local——
// 与后端 CAPABILITY_PROVIDERS 白名单一致，选了也保存不了（序列化层拒收）
// 对话生成保留模拟模式，便于无 Key 环境演示流程
const providers = [
  { value:'deepseek', label:'DeepSeek' },
  { value:'tongyi', label:'通义千问' },
  { value:'openai', label:'本地模型服务' },
  { value:'local', label:'系统内置模型' },
  { value:'mock', label:'模拟模式' },
]
const realProviders = providers.filter(i=>i.value!=='mock')
const providerOptions = providers
// 预设按能力区分：选服务商时各卡填各自能力的默认模型（TTS 卡不会再被填成聊天模型）
const presets = {
  deepseek:{ base_url:'https://api.deepseek.com/v1', chat:'deepseek-chat', embed:'', rerank:'', tts:'' },
  tongyi:{ base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1', chat:'qwen-plus', embed:'text-embedding-v3', rerank:'gte-rerank-v2', tts:'qwen3-tts-flash' },
  openai:{ base_url:'', chat:'', embed:'', rerank:'', tts:'' },
  local:{ base_url:'', chat:'', embed:'BAAI/bge-m3', rerank:'Qwen/Qwen3-Reranker-0.6B', tts:'' },
  mock:{ base_url:'', chat:'', embed:'', rerank:'', tts:'' },
}
const capabilityList = [
  { value:'chat', label:'对话生成', desc:'目录识别、逐页讲稿、智能出题、知识问答、学情分析', icon:ChatDotRound, color:'#2563eb', bg:'#eff6ff', modelLabel:'对话模型', modelPlaceholder:'例如 qwen-plus / deepseek-chat', showTimeout:true, timeoutDefault:45, showVision:true, providers: providers.filter(i=>i.value!=='local') },
  { value:'embed', label:'向量化', desc:'知识库资料入库与检索', icon:Files, color:'#7c3aed', bg:'#f5f3ff', modelLabel:'向量模型', modelPlaceholder:'例如 text-embedding-v3', showTimeout:true, timeoutDefault:60, providers: realProviders.filter(i=>i.value!=='deepseek') },
  { value:'rerank', label:'重排序', desc:'知识库检索结果按问题语义精排，过滤关键词命中的噪声片段', icon:Sort, color:'#0ea5e9', bg:'#f0f9ff', modelLabel:'重排序模型', modelPlaceholder:'例如 gte-rerank-v2', showTimeout:true, timeoutDefault:60, providers: [{ value:'tongyi', label:'通义千问' }, { value:'local', label:'系统内置模型' }] },
  { value:'tts', label:'语音合成', desc:'PPT 逐页 AI 配音', icon:Microphone, color:'#f59e0b', bg:'#fffbeb', modelLabel:'语音模型', modelPlaceholder:'例如 qwen3-tts-flash', showTimeout:true, showVoice:true, timeoutDefault:120, providers: realProviders.filter(i=>i.value!=='deepseek' && i.value!=='local') },
]
// 统计/流水页的筛选项（与后端 Scene / Provider 枚举一致）
const capabilityOptions = capabilityList.map(i=>({ value:i.value, label:i.label }))
const sceneOptions = [
  { value:'catalog_gen', label:'目录识别' },
  { value:'script_gen', label:'讲解稿生成' },
  { value:'tts', label:'语音合成' },
  { value:'material_embed', label:'教辅资料向量化' },
  { value:'ppt_embed', label:'课件向量化' },
  { value:'qa', label:'知识库问答' },
  { value:'question_gen', label:'题目生成' },
  { value:'grading', label:'作业批改' },
  { value:'analytics', label:'学情分析' },
  { value:'tts_preview', label:'配音试听' },
  { value:'connection_test', label:'连接测试' },
  { value:'vector_rebuild', label:'向量重建' },
  { value:'rag_eval', label:'检索评测' },
  { value:'other', label:'其他' },
]

const loading=ref(false), saving=ref(false), testing=ref(''), dirty=ref(false), hydrating=ref(false)
const effective=ref([])
const testDialog=reactive({
  visible:false, title:'', status:'untested', headline:'', message:'',
  capabilityLabel:'', providerModel:'', baseUrl:'', sourceLabel:'',
  request:'', response:'', elapsed:'', testedAt:'', fromForm:false,
})
const forms=reactive({
  chat:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', supports_vision:false, api_key:'' },
  embed:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', supports_vision:false, api_key:'' },
  rerank:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', supports_vision:false, api_key:'' },
  tts:{ provider:'mock', enabled:false, base_url:'', model_name:'', timeout:null, voice:'', supports_vision:false, api_key:'' },
})

// ---------------- Tab 切换 ----------------
const activeTab=ref('config')
const statsLoaded=ref(false), changesLoaded=ref(false), qaLoaded=ref(false)
function onTabChange(name){
  if(name==='stats' && !statsLoaded.value){ reloadStats(); loadLogs() }
  if(name==='changes' && !changesLoaded.value){ reloadChanges() }
  if(name==='quality' && !qaLoaded.value){ loadQA() }
}

// ---------------- 调用统计 ----------------
// 周期三方式并存（后使用者生效）：预设快捷与自定义起止日期走日历窗（start/end），
// 近 N 天走滚动窗（days）；mode 决定发给后端的参数形态
const period = reactive({ mode: 'days', days: 7, range: [] })
const rangeShortcuts = [
  { text: '今天', value: () => { const t = new Date(); return [t, t] } },
  { text: '近 7 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 6); return [s, t] } },
  { text: '近 30 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 29); return [s, t] } },
  { text: '近 90 天', value: () => { const t = new Date(); const s = new Date(t); s.setDate(s.getDate() - 89); return [s, t] } },
]
function periodParams() {
  if (period.mode === 'range' && period.range?.length === 2) {
    return { start: period.range[0], end: period.range[1] }
  }
  return { days: period.days }
}
const statsLoading = ref(false)
const stats = ref(null)
const exporting = ref(false)

const windowText = computed(() => {
  const w = stats.value?.window
  if (!w) return ''
  const s = w.start.slice(0, 10), e = w.end.slice(0, 10)
  const ps = w.previous_start.slice(0, 10), pe = w.previous_end.slice(0, 10)
  return `${s} ~ ${e}（${w.days} 天）· 对比上周期 ${ps} ~ ${pe}`
})

// 环比：涨红跌绿（中文语境）；success_rate 反向（越高越好）；上周期无数据时给「新增」
function deltaInfo(cur, prev, { goodWhenUp = false } = {}) {
  if (cur == null || prev == null) return { text: '—', tone: 'none' }
  if (prev === 0) {
    if (cur === 0) return { text: '持平', tone: 'flat' }
    return { text: '新增', tone: goodWhenUp ? 'good' : 'up' }
  }
  const ratio = (cur - prev) / prev
  if (Math.abs(ratio) < 0.001) return { text: '持平', tone: 'flat' }
  const text = `${ratio > 0 ? '↑' : '↓'} ${(Math.abs(ratio) * 100).toFixed(0)}%`
  if (goodWhenUp) return { text, tone: ratio > 0 ? 'good' : 'bad' }
  return { text, tone: ratio > 0 ? 'up' : 'down' }
}
const totalsDelta = computed(() => ({
  calls: deltaInfo(stats.value?.totals?.calls, stats.value?.totals_previous?.calls),
  success_rate: deltaInfo(stats.value?.totals?.success_rate, stats.value?.totals_previous?.success_rate, { goodWhenUp: true }),
  mock_calls: deltaInfo(stats.value?.totals?.mock_calls, stats.value?.totals_previous?.mock_calls),
  total_tokens: deltaInfo(stats.value?.totals?.total_tokens, stats.value?.totals_previous?.total_tokens),
  avg_latency_ms: deltaInfo(stats.value?.totals?.avg_latency_ms, stats.value?.totals_previous?.avg_latency_ms),
}))
// 小样本保护：调用 <3 次平均耗时不可信；<10 次 P95 样本不足
const totalCalls = computed(() => stats.value?.totals?.calls ?? 0)
const avgLatencyText = computed(() => (totalCalls.value < 3 ? '—' : fmtMs(stats.value?.totals?.avg_latency_ms)))
const p95Text = computed(() => (totalCalls.value < 10 ? '样本不足' : fmtMs(stats.value?.totals?.p95_latency_ms)))

// ---------------- 趋势图（当前周期柱 + 上周期虚线，按窗口内偏移对齐） ----------------
const chartMetric = ref('calls')  // calls | total_tokens | avg_latency_ms
const metricLabel = computed(() => ({ calls: '调用', total_tokens: 'Token', avg_latency_ms: '平均耗时' })[chartMetric.value])

function isoDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function eachDayInclusive(startDay, endDay) {
  const days = []
  const end = new Date(endDay + 'T00:00:00')
  for (let d = new Date(startDay + 'T00:00:00'); d <= end; d.setDate(d.getDate() + 1)) {
    days.push(isoDay(d))
    if (days.length > 400) break  // 防御：后端已限制 366 天
  }
  return days
}
const trendSeries = computed(() => {
  const w = stats.value?.window
  if (!w) return []
  const curMap = Object.fromEntries((stats.value.daily || []).map(r => [r.day, r]))
  const prevMap = Object.fromEntries((stats.value.daily_previous || []).map(r => [r.day, r]))
  const curDays = eachDayInclusive(w.start.slice(0, 10), w.end.slice(0, 10))
  const prevDays = eachDayInclusive(w.previous_start.slice(0, 10), w.previous_end.slice(0, 10))
  const rows = []
  for (let i = 0; i < Math.max(curDays.length, prevDays.length); i++) {
    const cur = i < curDays.length ? curMap[curDays[i]] : null
    const prev = i < prevDays.length ? prevMap[prevDays[i]] : null
    rows.push({
      day: (i < curDays.length ? curDays[i] : prevDays[i]),
      calls: cur?.calls || 0,
      failed: cur?.failed || 0,
      total_tokens: cur?.total_tokens || 0,
      avg_latency_ms: cur?.avg_latency_ms || 0,
      prev_calls: prev?.calls || 0,
      prev_total_tokens: prev?.total_tokens || 0,
      prev_avg_latency_ms: prev?.avg_latency_ms || 0,
    })
  }
  // 跨度超过 31 天按周聚合（前端分桶，7 天一组从窗口首日起算）
  if (rows.length > 31) {
    const buckets = []
    for (let i = 0; i < rows.length; i += 7) {
      const chunk = rows.slice(i, i + 7)
      const sum = k => chunk.reduce((a, r) => a + (r[k] || 0), 0)
      // 平均耗时按调用次数加权，避免无调用天数稀释
      const wavg = (vk, ck) => (sum(ck) ? Math.round(chunk.reduce((a, r) => a + (r[vk] || 0) * (r[ck] || 0), 0) / sum(ck)) : 0)
      buckets.push({
        day: chunk[0].day,
        calls: sum('calls'), failed: sum('failed'), total_tokens: sum('total_tokens'),
        avg_latency_ms: wavg('avg_latency_ms', 'calls'),
        prev_calls: sum('prev_calls'), prev_total_tokens: sum('prev_total_tokens'),
        prev_avg_latency_ms: wavg('prev_avg_latency_ms', 'prev_calls'),
        weekly: true,
      })
    }
    return buckets
  }
  return rows
})
const trendPoints = computed(() => trendSeries.value.map(r => ({
  day: r.day,
  label: r.day.slice(5),
  calls: r.calls,
  failed: r.failed,
  value: chartMetric.value === 'total_tokens' ? r.total_tokens : chartMetric.value === 'avg_latency_ms' ? r.avg_latency_ms : r.calls,
  prev: chartMetric.value === 'total_tokens' ? r.prev_total_tokens : chartMetric.value === 'avg_latency_ms' ? r.prev_avg_latency_ms : r.prev_calls,
})))
const trendWeekly = computed(() => trendSeries.value.some(r => r.weekly))
const hasPrevSeries = computed(() => trendPoints.value.some(p => p.prev > 0))
const prevPoints = computed(() => trendPoints.value.map((p, i) => `${barX(i) + barWidth.value / 2},${yOf(p.prev)}`).join(' '))
const trendMax = computed(() => Math.max(1, ...trendPoints.value.flatMap(p => [p.value, p.prev])))
const axisMax = computed(() => {
  const m = trendMax.value
  if (m <= 5) return 5
  if (m <= 10) return 10
  const pow = Math.pow(10, Math.floor(Math.log10(m)))
  return Math.ceil(m / pow) * pow
})
const gridValues = computed(() => [axisMax.value, axisMax.value / 2, 0])
const barSlot = computed(() => 634 / Math.max(1, trendPoints.value.length))
const barWidth = computed(() => Math.max(4, Math.min(28, barSlot.value - 4)))
const labelEvery = computed(() => Math.max(1, Math.ceil(trendPoints.value.length / 10)))
const PLOT_TOP = 10, PLOT_HEIGHT = 186
function barX(i) { return 36 + i * barSlot.value + (barSlot.value - barWidth.value) / 2 }
function barH(v) { return Math.round((v / axisMax.value) * PLOT_HEIGHT) }
function yOf(v) { return PLOT_TOP + PLOT_HEIGHT - barH(v) }
function fmtMetric(v) { return chartMetric.value === 'avg_latency_ms' ? fmtMs(v) : fmtNum(v) }
const trendSparseHint = computed(() => {
  if (!totalCalls.value) return ''
  const effective = trendSeries.value.filter(r => r.calls > 0).length
  return effective < 3 ? `仅 ${effective} 天有调用记录，趋势形态暂不稳定，仅供参考` : ''
})

// ---------------- 调用分布（能力/场景/触发人三表合一，点击联动流水） ----------------
const distDim = ref('capability')  // capability | scene | user
const distRows = computed(() => {
  const s = stats.value
  if (!s) return []
  if (distDim.value === 'scene') {
    return (s.by_scene || []).map(r => ({ key: r.scene, label: sceneLabel(r.scene), group: r.group || '其他', ...r }))
  }
  if (distDim.value === 'user') {
    return (s.top_triggered_by || []).map(r => ({
      key: r.triggered_by, label: r.triggered_by__username || '—', group: '',
      calls: r.calls, failed: r.failed, mock_calls: 0,
      avg_latency: null, total_tokens: null, item_count: null,
    }))
  }
  return (s.by_capability || []).map(r => ({ key: r.capability, label: capabilityLabel(r.capability), group: '', ...r }))
})
const distMax = computed(() => Math.max(1, ...distRows.value.map(r => r.calls || 0)))
const distTotal = computed(() => stats.value?.totals?.calls || 0)
function distBarWidth(row) { return Math.max(2, ((row.calls || 0) / distMax.value) * 100) }
function distPct(row) { return distTotal.value ? ((row.calls / distTotal.value) * 100).toFixed(1) + '%' : '—' }
const distGroups = computed(() => {
  const rows = distRows.value
  if (distDim.value !== 'scene') return rows.length ? [{ group: '', calls: distTotal.value, rows }] : []
  const map = new Map()
  for (const r of rows) {
    if (!map.has(r.group)) map.set(r.group, [])
    map.get(r.group).push(r)
  }
  return [...map.entries()]
    .map(([group, list]) => ({ group, calls: list.reduce((a, r) => a + (r.calls || 0), 0), rows: list }))
    .sort((a, b) => b.calls - a.calls)
})
function filterByDistRow(row) {
  if (distDim.value === 'capability') logFilters.capability = row.key
  else if (distDim.value === 'scene') logFilters.scene = row.key
  else logFilters.triggered_by = String(row.key)
  applyLogFilters()
  document.querySelector('.logs-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const successTone = computed(() => {
  const rate = stats.value?.totals?.success_rate
  if (rate == null) return ''
  return rate >= 0.95 ? 'good' : (rate >= 0.8 ? '' : 'bad')
})

function fmtNum(v) {
  if (v == null) return '0'
  if (v >= 10000) return (v / 10000).toFixed(1).replace(/\.0$/, '') + ' 万'
  return String(v)
}
function fmtMs(v) {
  if (!v) return '0ms'
  return v >= 1000 ? (v / 1000).toFixed(1) + 's' : v + 'ms'
}
function fmtPct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%' }
function capabilityLabel(value) { return capabilityOptions.find(i => i.value === value)?.label || value }
function sceneLabel(value) { return sceneOptions.find(i => i.value === value)?.label || value }

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await getAdminAICallStats(periodParams())
    statsLoaded.value = true
  } finally { statsLoading.value = false }
}
function reloadStats() { loadStats() }
// 周期/筛选变化：汇总与流水共用同一窗口，一并刷新
function refreshStatsAndLogs() { reloadStats(); logsPage.value = 1; loadLogs() }
function onRangeChange(value) {
  if (!value) { period.range = []; return }  // 清空不改变当前生效窗口
  period.mode = 'range'
  refreshStatsAndLogs()
  if (qaLoaded.value) reloadQA()
}
function onDaysChange() {
  period.mode = 'days'
  refreshStatsAndLogs()
  if (qaLoaded.value) reloadQA()
}

// ---------------- 问答质量（看板） ----------------
// 与调用统计共用 period 窗口（近 N 天滚动窗 / 日历窗），首次进入 tab 时懒加载
const qaLoading = ref(false)
const qa = ref(null)

async function loadQA() {
  qaLoading.value = true
  try {
    qa.value = await getAdminQAQualityStats(periodParams())
    qaLoaded.value = true
  } finally { qaLoading.value = false }
}
function reloadQA() { loadQA() }

const qaWindowText = computed(() => {
  const w = qa.value?.window
  if (!w) return ''
  const s = w.start.slice(0, 10), e = w.end.slice(0, 10)
  const ps = w.previous_start.slice(0, 10), pe = w.previous_end.slice(0, 10)
  return `${s} ~ ${e}（${w.days} 天）· 对比上周期 ${ps} ~ ${pe}`
})

// 指标卡着色：badAbove/warnAbove 越高越坏（为空率/兜底率/降级率）；
// badBelow/warnBelow 越低越坏（好评率）
function qaRateTone(value, { badAbove, warnAbove, badBelow, warnBelow } = {}) {
  if (value == null) return ''
  if (badAbove != null) return value > badAbove ? 'bad' : (warnAbove != null && value > warnAbove ? 'warn' : '')
  if (badBelow != null) return value < badBelow ? 'bad' : (warnBelow != null && value < warnBelow ? 'warn' : '')
  return ''
}
// 比率环比：复用 deltaInfo（涨红跌绿；好评率传 goodWhenUp 反向）
function qaDelta(cur, prev, options = {}) {
  return deltaInfo(cur, prev, options)
}

// 日趋势：为空率（红）/ 好评率（绿）双折线；null（当天无提问）断开
const qaTrendDays = computed(() => qa.value?.daily || [])
const qaPointCount = computed(() => qaTrendDays.value.length)
const qaTrendMax = computed(() => Math.max(
  0,
  ...qaTrendDays.value.flatMap(r => [r.empty_rate || 0, r.feedback_rate || 0]),
))
const qaAxisMax = computed(() => {
  const m = qaTrendMax.value
  if (m <= 0.1) return 0.2
  if (m <= 0.25) return 0.5
  if (m <= 0.5) return 0.75
  return 1
})
const qaGridValues = computed(() => [qaAxisMax.value, qaAxisMax.value / 2, 0])
const QA_PLOT = { top: 12, height: 178, left: 44, right: 16 }
function qaX(i, n) {
  if (n <= 1) return (680 - QA_PLOT.left - QA_PLOT.right) / 2 + QA_PLOT.left
  return QA_PLOT.left + (i * (680 - QA_PLOT.left - QA_PLOT.right)) / (n - 1)
}
function qaY(v) { return QA_PLOT.top + QA_PLOT.height - (v / qaAxisMax.value) * QA_PLOT.height }
// 按指标生成折线段数组（null 处断开成多段）
function qaSeries(key) {
  const rows = qaTrendDays.value
  const segments = []
  let cur = []
  rows.forEach((r, i) => {
    if (r[key] == null) {
      if (cur.length) { segments.push(cur.join(' ')); cur = [] }
      return
    }
    cur.push(`${qaX(i, rows.length)},${qaY(r[key])}`)
  })
  if (cur.length) segments.push(cur.join(' '))
  return segments
}
const qaEmptySegments = computed(() => qaSeries('empty_rate'))
const qaFeedbackSegments = computed(() => qaSeries('feedback_rate'))
const qaLabelEvery = computed(() => Math.max(1, Math.ceil(qaPointCount.value / 10)))

// 降级分布（L0 未降级 / L1 丢一半 / L2 近两轮 / L4 全丢）
const qaDegradedLabels = { L0: 'L0 未降级', L1: 'L1 丢一半', L2: 'L2 近两轮', L4: 'L4 全丢' }
const qaDegradedColors = {
  L0: 'linear-gradient(90deg,#93c5fd,#2563eb)',
  L1: 'linear-gradient(90deg,#c4b5fd,#7c3aed)',
  L2: 'linear-gradient(90deg,#7dd3fc,#0284c7)',
  L4: 'linear-gradient(90deg,#fca5a5,#dc2626)',
}
const qaDegradedRows = computed(() => {
  const d = qa.value?.degraded
  if (!d) return []
  const total = qa.value?.totals?.questions || 0
  const max = Math.max(1, ...['L0', 'L1', 'L2', 'L4'].map(k => d[k] || 0))
  return ['L0', 'L1', 'L2', 'L4'].map(k => ({
    key: k,
    label: qaDegradedLabels[k],
    count: d[k] || 0,
    width: Math.max(2, ((d[k] || 0) / max) * 100),
    pct: total ? (((d[k] || 0) / total) * 100).toFixed(1) + '%' : '—',
    color: qaDegradedColors[k],
  }))
})

// 引用来源分布（material 资料 / script 讲解稿 / ppt 课件 / script+ppt 组合 / unknown 历史记录无来源键）
const qaSourceLabels = { material: '知识库资料', script: '讲解稿', ppt: '课件 PPT', 'script+ppt': '讲解稿+课件', unknown: '其他' }
const qaSourceColors = { material: 'linear-gradient(90deg,#93c5fd,#2563eb)', script: 'linear-gradient(90deg,#c4b5fd,#7c3aed)', ppt: 'linear-gradient(90deg,#7dd3fc,#0284c7)', 'script+ppt': 'linear-gradient(90deg,#5eead4,#0d9488)', unknown: 'linear-gradient(90deg,#cbd5e1,#94a3b8)' }
const qaSourceRows = computed(() => {
  const src = qa.value?.by_source || {}
  const entries = Object.entries(src)
  if (!entries.length) return []
  const total = entries.reduce((a, [, c]) => a + c, 0)
  const max = Math.max(...entries.map(([, c]) => c))
  return entries
    .map(([key, count]) => ({
      key,
      label: qaSourceLabels[key] || key,
      count,
      width: Math.max(2, (count / max) * 100),
      pct: total ? ((count / total) * 100).toFixed(1) + '%' : '—',
      color: qaSourceColors[key] || qaSourceColors.unknown,
    }))
    .sort((a, b) => b.count - a.count)
})

// ---------------- 调用流水 ----------------
const logFilters = reactive({ capability: '', scene: '', provider: '', triggered_by: '', success: '', keyword: '' })
const logs = ref([]), logsTotal = ref(0), logsPage = ref(1), logsPageSize = ref(20), logsLoading = ref(false)
const triggeredByOptions = computed(() => (stats.value?.top_triggered_by || []).map(r => ({
  value: String(r.triggered_by), label: r.triggered_by__username || `用户 ${r.triggered_by}`,
})))

async function loadLogs() {
  logsLoading.value = true
  try {
    const params = { ...periodParams(), page: logsPage.value, page_size: logsPageSize.value }
    for (const [key, value] of Object.entries(logFilters)) {
      if (value !== '' && value != null) params[key] = value
    }
    const result = await listAdminAICallLogs(params)
    logs.value = result?.items || []
    logsTotal.value = result?.total || 0
  } finally { logsLoading.value = false }
}
function applyLogFilters() { logsPage.value = 1; loadLogs() }

async function exportCsv() {
  exporting.value = true
  try {
    const blob = await exportAdminAICallLogs(periodParams())
    // 后端错误也可能以 blob（JSON）返回，先识别再落盘，避免下载到错误文件
    if (blob?.type && blob.type.includes('application/json')) {
      const text = await blob.text()
      let message = '导出失败'
      try { message = JSON.parse(text).message || message } catch { /* 保留默认文案 */ }
      ElMessage.error(message)
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ai_call_logs_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载（单次上限 5 万条）')
  } catch {
    ElMessage.error('导出失败，请稍后重试')
  } finally { exporting.value = false }
}

// ---------------- 配置变更记录 ----------------
// 审计双轨已合并：变更记录读管理端操作审计单轨（action=ai_config_save，
// 字段级 diff 按能力分组存 new_value.changes）；AICapabilityChangeLog 端点仅存历史。
const changeCapability=ref('')
const changes=ref([]), changesTotal=ref(0), changesPage=ref(1), changesPageSize=ref(20), changesLoading=ref(false)

function changeGroups(row){
  return (row.new_value && row.new_value.changes) || []
}

async function loadChanges(){
  changesLoading.value=true
  try{
    const params={ action:'ai_config_save', page: changesPage.value, page_size: changesPageSize.value }
    // 能力筛选走审计 keyword（匹配对象名称=能力显示名，与后端 target_label 一致）
    if(changeCapability.value) params.keyword=capabilityLabel(changeCapability.value)
    const result=await listAdminActionLogs(params)
    changes.value=result?.items||[]
    changesTotal.value=result?.total||0
    changesLoaded.value=true
  }finally{ changesLoading.value=false }
}
function reloadChanges(){ changesPage.value=1; loadChanges() }

const realCount=computed(()=>effective.value.filter(i=>!i.runtime_is_mock).length)
const overallTone=computed(()=>realCount.value===0?'muted':'active')
const overallTitle=computed(()=>realCount.value===0?'当前为模拟模式':(realCount.value===4?'真实模型已启用':'部分能力为真实模型'))
const overallSubtitle=computed(()=>realCount.value===0?'不会调用外部模型服务':`${realCount.value}/4 项能力已对接真实模型`)
function providerLabel(value){ return providers.find(i=>i.value===value)?.label || value }
function capabilityDesc(value){ return capabilityList.find(i=>i.value===value)?.desc || '' }
function effectiveItem(value){ return effective.value.find(i=>i.capability===value) || {} }
function isMock(value){ return forms[value].provider==='mock' }
function isLocal(value){ return forms[value].provider==='local' }
// 模型名视觉特征（与后端 model_name_suggests_vision 同规则）：仅用于配置页提示
const VISION_MODEL_HINTS = ['vl', 'vision', '4v', 'gpt-4o', 'gpt-4.1', 'gemini', 'claude-3', 'pixtral', 'llava', '多模态']
function looksLikeVisionModel(name){
  const n = String(name || '').toLowerCase()
  return VISION_MODEL_HINTS.some(h => n.includes(h))
}
// 图片开关与模型能力的错配提示（两个方向都提示：qwen3.7-plus 这类实测支持
// 视觉但名称不带 vl/vision 的模型，关闭时不该误报，只做确认提醒）
const visionMismatch = computed(() => {
  if (isMock('chat')) return ''
  const looks = looksLikeVisionModel(forms.chat.model_name)
  if (looks && !forms.chat.supports_vision) {
    return '当前模型名疑似多模态（视觉）模型，但图片上传入口为隐藏；如确认支持图片请开启开关。'
  }
  if (!looks && forms.chat.supports_vision) {
    return '模型名未体现视觉能力（如 qwen3.7-plus 实测支持图片但名称不带 vl/vision）；请确认所用模型确实支持图片输入，否则用户发送图片会被接口拒绝。'
  }
  return ''
})
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
    form.supports_vision=Boolean(item.supports_vision)
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
  // 「支持图片」开关防护：生效值为开启而表单要关闭时二次确认——
  // 防止误触开关或旧标签页（保存前打开、表单还是旧状态）静默覆盖关闭，
  // 导致学生端图片上传入口无故消失（曾实际发生：开启 1 分钟后被覆盖为关闭）
  if(effectiveItem('chat').supports_vision && !forms.chat.supports_vision){
    try{
      await ElMessageBox.confirm(
        '「支持图片」开关当前为开启状态，本次保存将关闭它，学生端的图片上传入口会立即隐藏。确定关闭吗？',
        '关闭图片上传入口',
        { type:'warning', confirmButtonText:'确定关闭', cancelButtonText:'取消' }
      )
    }catch{ return } // 用户取消：不保存
  }
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
.ai-settings{color:#0f172a}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-bottom:22px}.eyebrow{margin-bottom:6px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.16em}h1,h2,h3,p{margin:0}h1{font-size:30px}.page-head p{margin-top:7px;color:#8190a8}.runtime-badge{min-width:230px;padding:12px 15px;border:1px solid #e2e8f0;border-radius:16px;display:flex;align-items:center;gap:11px;background:#fff}.runtime-badge>span{width:10px;height:10px;border-radius:50%;background:#94a3b8;box-shadow:0 0 0 5px #f1f5f9}.runtime-badge>div{display:grid;gap:2px}.runtime-badge small{color:#94a3b8}.runtime-badge.active>span{background:#22c55e;box-shadow:0 0 0 5px #dcfce7}
.ai-tabs{--el-tabs-header-height:44px}.ai-tabs :deep(.el-tabs__header){margin-bottom:18px}.ai-tabs :deep(.el-tabs__item){font-size:15px;font-weight:700}.ai-tabs :deep(.el-tabs__nav-wrap::after){background:#e8eef7}
.effective-card,.config-card,.stats-toolbar,.chart-card,.dist-card,.logs-card,.changes-card{border:1px solid #e5edf8;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.effective-card{padding:20px;margin-bottom:16px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.section-head h2{font-size:18px}.effective-table{width:100%;font-size:14px}.effective-table :deep(.el-table__cell){padding:8px 0;font-size:14px}.effective-table :deep(.el-table__cell .cell){padding:0 10px}.effective-table code{background:#f1f5f9;border-radius:5px;padding:2px 7px;font-size:13px;color:#334155}.provider-name{font-weight:600;color:#0f172a}.muted{color:#64748b;font-size:14px}.warn{color:#d97706;font-size:12px}.block{display:block;margin-top:3px;color:#64748b;font-size:12px}.test-cell{display:flex;align-items:flex-start;gap:7px;color:#334155}.test-cell span{font-size:13px;font-weight:500;word-break:break-all}.test-cell small{display:block;margin-top:2px;color:#64748b;font-size:12px}.test-cell.success{color:#16a34a}.test-cell.failed{color:#dc2626}
.capability-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.config-card{padding:22px}.card-head{display:flex;align-items:center;gap:12px;padding-bottom:17px;border-bottom:1px solid #edf2f7}.card-title{min-width:0;flex:1}.card-head h2{font-size:17px}.card-head p{margin-top:3px;color:#94a3b8;font-size:12px}.head-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;flex:0 0 auto;font-size:19px}.config-form{margin-top:16px}.secret-note{margin-top:7px;color:#94a3b8;font-size:12px;display:flex;align-items:flex-start;gap:5px;line-height:1.5}.field-note{margin-top:7px;color:#94a3b8;font-size:12px;display:flex;align-items:flex-start;gap:5px;line-height:1.5}.card-foot{margin-top:14px;padding-top:13px;border-top:1px solid #edf2f7;display:flex;align-items:center;justify-content:space-between;gap:10px}.source-tag{color:#94a3b8;font-size:12px}.vision-tag{margin-top:5px}.warn-note{color:#b45309}.warn-note .el-icon{color:#d97706}
/* 吸底保存栏：bottom:0 贴滚动视口(.main)底边；负底边距 -36px 伸进页面底边距，
   滚到底时栏底与面板底边齐平（配合布局默认的 36px 页面底边距）。
   勿改回负 bottom——那会让栏底掉到视口外被面板 overflow:hidden 裁掉 */
.action-bar{position:sticky;bottom:0;z-index:5;margin:18px -36px -36px;padding:15px 36px;border-top:1px solid #e5edf8;background:rgba(255,255,255,.92);backdrop-filter:blur(16px);display:flex;justify-content:flex-end;align-items:center;gap:10px}.action-bar>div{margin-right:auto;color:#94a3b8;font-size:12px}
.test-banner{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;border:1px solid;border-radius:12px;margin-bottom:14px}.test-banner.success{border-color:#bbf7d0;background:#f0fdf4;color:#15803d}.test-banner.failed{border-color:#fecaca;background:#fef2f2;color:#b91c1c}.test-banner.untested{border-color:#e2e8f0;background:#f8fafc;color:#475569}.banner-icon{font-size:22px;margin-top:1px}.banner-text strong{display:block;margin-bottom:4px;font-size:15px}.banner-text p{margin:0;font-size:13px;line-height:1.6;word-break:break-all}.form-note{margin-bottom:12px;padding:8px 12px;border-radius:8px;background:#eff6ff;color:#1d4ed8;font-size:12px;line-height:1.6}.test-dialog :deep(.el-descriptions__content){word-break:break-all;line-height:1.6}
/* ---- 调用统计 ---- */
.stats-panel{display:grid;gap:16px}.stats-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 18px}.toolbar-note{color:#94a3b8;font-size:12px;line-height:1.5}.window-note{padding:0 4px;color:#64748b;font-size:12px}.days-input{display:inline-flex;align-items:center;gap:6px}.days-label{color:#64748b;font-size:13px}
.alerts{display:grid;gap:8px}.alert{display:flex;align-items:flex-start;gap:8px;padding:11px 15px;border-radius:14px;font-size:13px;line-height:1.6}.alert.warning{background:#fffbeb;border:1px solid #fde68a;color:#b45309}.alert.info{background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8}.alert .el-icon{margin-top:2px;flex:0 0 auto}
.stat-cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.stat-card{padding:15px 17px;display:grid;gap:3px;border:1px solid #e5edf8;border-radius:18px;background:rgba(255,255,255,.94);box-shadow:0 16px 40px rgba(37,99,235,.07)}.stat-card small{color:#94a3b8;font-size:12px}.stat-card strong{font-size:24px;color:#0f172a}.stat-card strong.good{color:#16a34a}.stat-card strong.bad{color:#dc2626}.stat-card strong.warn{color:#d97706}.stat-card .sub{color:#94a3b8;font-size:12px}
/* 环比：涨红跌绿（成功率反向：good/bad） */
.delta{font-size:12px;font-weight:700}.delta.up,.delta.bad{color:#dc2626}.delta.down,.delta.good{color:#16a34a}.delta.flat,.delta.none{color:#94a3b8;font-weight:400}
.chart-card{padding:18px}.chart-card h3,.dist-card h3,.logs-card h3{font-size:16px;margin-bottom:12px}.chart-card h3 small,.logs-head h3 small{margin-left:8px;color:#94a3b8;font-size:12px;font-weight:400}.chart-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}.chart-head h3{margin-bottom:0}.trend-chart{width:100%;height:220px;display:block}.axis-label{font-size:10px;fill:#94a3b8}.chart-hint{display:flex;align-items:center;gap:6px;margin:10px 0 0;color:#b45309;font-size:12px}
.dist-card{padding:18px}.dist-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:6px}.dist-head h3{margin-bottom:0}
.dist-group-title{display:flex;align-items:center;gap:8px;margin:12px 0 4px;font-size:13px;font-weight:700;color:#334155}.dist-group-title small{color:#94a3b8;font-weight:400}.dist-group:first-child .dist-group-title{margin-top:4px}
.dist-row{display:grid;grid-template-columns:minmax(88px,150px) 1fr 58px 52px 62px auto;align-items:center;gap:10px;width:100%;padding:7px 10px;border:0;border-radius:10px;background:transparent;cursor:pointer;text-align:left;font:inherit;color:#0f172a}.dist-row:hover{background:#f1f7ff}.dist-row:active{background:#e8f1ff}
.dist-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
.dist-bar{height:8px;border-radius:5px;background:#eef3fa;overflow:hidden}.dist-bar i{display:block;height:100%;border-radius:5px;transition:width .3s}
.dist-card.dim-capability .dist-bar i{background:linear-gradient(90deg,#93c5fd,#2563eb)}.dist-card.dim-scene .dist-bar i{background:linear-gradient(90deg,#c4b5fd,#7c3aed)}.dist-card.dim-user .dist-bar i{background:linear-gradient(90deg,#7dd3fc,#0284c7)}
.dist-calls{font-size:13px;font-weight:700;text-align:right}.dist-pct{font-size:12px;color:#64748b;text-align:right}.dist-latency{font-size:12px;color:#94a3b8;text-align:right}
.dist-badges{display:inline-flex;gap:5px}.badge{font-style:normal;font-size:11px;padding:1px 7px;border-radius:6px;white-space:nowrap}.badge.fail{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}.badge.mock{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}
.dist-hint{margin:12px 0 0;color:#94a3b8;font-size:12px}
.logs-card{padding:18px}.logs-head{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:12px}.logs-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.mock-tag{margin-left:5px}.ellipsis{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}.error-text{color:#dc2626}.pager{margin-top:14px;justify-content:flex-end}
.change-list{display:flex;flex-wrap:wrap;gap:6px 14px}.change-item{display:inline-flex;align-items:center;gap:5px;max-width:100%;font-size:12px;color:#334155;background:#f8fafc;border:1px solid #e8eef7;border-radius:8px;padding:3px 9px}.change-item em{font-style:normal;color:#64748b}.change-item .old{color:#dc2626;text-decoration:line-through}.change-item .new{color:#16a34a;font-weight:600}.change-item .el-icon{font-size:11px;color:#94a3b8}.change-item .old,.change-item .new{overflow-wrap:anywhere}
.changes-card{padding:18px}.changes-card :deep(.el-table){font-size:13px}
/* ---- 问答质量看板 ---- */
.qa-help{display:inline-grid;place-items:center;width:15px;height:15px;margin-left:5px;border-radius:50%;border:1px solid #cbd5e1;color:#64748b;font-size:10px;font-weight:700;line-height:1;cursor:help;vertical-align:1px;flex:0 0 auto}.qa-help:hover{border-color:#2563eb;color:#2563eb}
.qa-cards{grid-template-columns:repeat(3,minmax(0,1fr))}
.chart-legend{display:flex;align-items:center;gap:18px;margin:10px 0 0;color:#64748b;font-size:12px}.chart-legend .dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px;vertical-align:-1px}.chart-legend .dot-red{background:#dc2626}.chart-legend .dot-green{background:#16a34a}
.dist-static{border:0;background:transparent;cursor:default;text-align:left;font:inherit;color:inherit}.dist-static:hover{background:transparent}
.alert.error{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c}
.qa-quality-table{width:100%;font-size:13px}.qa-quality-table :deep(.el-table .cell){white-space:nowrap}
/* 全局隐藏 EP 滚动条会让表格列总宽超容器时看不到横滚条（假截断）：本表需要时显式放行 */
.qa-quality-table :deep(.el-table .el-scrollbar__bar.is-horizontal){display:block!important}
@media(max-width:1200px){.capability-grid{grid-template-columns:1fr}.page-head{align-items:flex-start;flex-direction:column}.stat-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.qa-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){.action-bar{margin-left:-16px;margin-right:-16px;padding-left:16px;padding-right:16px}.action-bar>div{display:none}.stat-cards{grid-template-columns:1fr}.qa-cards{grid-template-columns:1fr}.dist-row{grid-template-columns:minmax(72px,1fr) 1fr 52px auto}.dist-latency{display:none}}
</style>
