<template>
  <div class="page-container exam-page" :class="{ 'is-editing': editVisible }">
    <template v-if="!editVisible">
    <div class="page-header">
      <div>
        <div class="page-title">考试管理</div>
        <div class="page-subtitle">创建考试、随机组卷、发布考试并实时监控学生答题情况</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <div class="toolbar module-toolbar">
        <div class="toolbar-left">
          <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="loadExams">
            <el-option v-for="c in classes" :key="c.id" :label="`${c.name} / ${classCourseNames(c)}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openCreate">新建考试</el-button>
        </div>
      </div>

      <div class="exam-list-shell">
        <el-empty v-if="!classId" description="请先选择班级">
          <template #description>
            <div class="empty-text">请先选择班级</div>
            <div class="empty-tip">选择班级后即可查看与管理该班级的考试</div>
          </template>
        </el-empty>

        <TableSkeleton v-else-if="loading" :cols="6" />
        <div v-else class="exam-card-list animate-list">
          <el-empty v-if="!exams.length" description="暂无考试" :image-size="96" />
          <template v-else>
            <article v-for="row in exams" :key="row.id" class="exam-list-card" :class="{ 'is-published': row.status === 'published' }">
              <div class="exam-card-main">
                <span class="exam-kind-badge">考试</span>
                <div class="exam-card-content">
                  <div class="exam-card-title">{{ row.name }}</div>
                  <div class="exam-card-meta">
                    <span v-if="formatExamWindow(row)" class="exam-meta-pill slate">{{ formatExamWindow(row) }}</span>
                    <span class="exam-meta-pill duration">{{ row.duration }} 分钟</span>
                    <span class="exam-score">{{ row.total_score || 0 }} 分</span>
                    <span class="exam-status-pill" :class="row.status">{{ row.status_display }}</span>
                    <span v-if="!row.has_paper" class="exam-meta-pill orange">未组卷</span>
                    <span v-else class="exam-meta-pill slate">共 {{ row.question_count }} 题</span>
                    <span v-if="row.shuffle_questions" class="exam-meta-pill blue">题目乱序</span>
                    <span v-if="row.shuffle_options" class="exam-meta-pill blue">选项乱序</span>
                    <span v-if="row.per_student_paper" class="exam-meta-pill slate">一人一卷</span>
                  </div>
                </div>
              </div>
              <div class="exam-card-actions">
                <!-- 草稿：编辑（基础信息与组卷已合并为同一整页）→ 必须组卷后才能发布 -->
                <template v-if="row.status === 'draft'">
                  <el-tooltip content="编辑基础信息并组卷" placement="top">
                    <el-button link type="primary" :icon="EditPen" @click="openEdit(row)">编辑</el-button>
                  </el-tooltip>
                  <el-tooltip :disabled="row.has_paper" content="请先完成组卷才能发布" placement="top">
                    <span class="action-wrap">
                      <el-button link type="success" :icon="VideoPlay" :disabled="!row.has_paper" @click="setStatus(row, 'published')">发布</el-button>
                    </span>
                  </el-tooltip>
                </template>
                <!-- 发布后：只能查看试卷，不能组卷/编辑 -->
                <template v-else>
                  <el-button link type="primary" :icon="View" @click="openPaper(row)">查看试卷</el-button>
                  <el-button v-if="row.status === 'published'" link type="info" :icon="CircleClose" @click="setStatus(row, 'finished')">结束</el-button>
                </template>
                <el-button link type="primary" :icon="Monitor" @click="openMonitor(row)">监控 / 批改</el-button>
                <el-tooltip :disabled="row.has_paper" content="组卷后即可查看答题统计" placement="top">
                  <span class="action-wrap">
                    <el-button link type="warning" :icon="TrendCharts" :disabled="!row.has_paper" @click="openStats(row)">考试统计</el-button>
                  </span>
                </el-tooltip>
                <el-button link type="danger" :icon="Delete" @click="openDelete(row)">删除</el-button>
              </div>
            </article>
          </template>
        </div>
      </div>
    </el-card>

    </template>

    <!-- 新建/编辑考试：整页工作台（版式对齐发布作业：左基础信息 + 右组卷选题与试卷预览） -->
    <Teleport to="body">
      <div v-if="editVisible" class="exam-editor">
        <div class="exam-editor-topbar">
          <div class="exam-editor-title-wrap">
            <span class="exam-editor-icon"><el-icon><Document /></el-icon></span>
            <div class="exam-editor-heading">
              <div class="exam-editor-title-line">
                <span class="exam-editor-title">{{ editingExam ? '编辑考试' : '新建考试' }}</span>
                <span class="exam-editor-kicker">{{ editorContext }}</span>
              </div>
              <div class="exam-editor-subtitle">设置考试信息并完成组卷，发布后学生方可参加</div>
            </div>
          </div>
          <div class="exam-editor-stats">
            <span><strong>{{ manualSelected.length }}</strong> 道题目</span>
            <span class="exam-stats-split" />
            <span><strong>{{ manualTotal }}</strong> 总分</span>
            <el-tag :type="form.status === 'published' ? 'success' : 'warning'" effect="light" round>
              {{ form.status === 'published' ? '已发布' : '草稿' }}
            </el-tag>
          </div>
          <div class="exam-editor-actions">
            <el-button @click="editVisible = false">退出编辑</el-button>
            <el-button type="primary" :loading="saving" @click="saveBasic(false)">{{ editingExam ? '保存修改' : '创建考试' }}</el-button>
            <el-button :loading="composing" :disabled="composeConfirming" @click="doCompose">生成试卷</el-button>
            <el-tooltip popper-class="exam-editor-tooltip" :disabled="paperReady" content="请先完成组卷才能发布" placement="top">
              <span class="action-wrap">
                <el-button type="success" plain :loading="publishing" :disabled="!paperReady" @click="publishExam">发布考试</el-button>
              </span>
            </el-tooltip>
          </div>
        </div>

        <div class="exam-editor-body">
          <el-form :model="form" label-position="top" class="exam-creation-form">
            <div class="creation-form-grid">
              <!-- 左列：基础信息 -->
              <div class="form-col form-col-left">
                <div class="exam-card exam-info-card">
                  <div class="exam-card-head"><el-icon><Tickets /></el-icon>基础信息</div>
                  <el-form-item label="考试名称"><el-input v-model="form.name" placeholder="请输入考试名称" /></el-form-item>
                  <el-form-item label="考试时长（分钟）"><el-input-number v-model="form.duration" :min="1" /></el-form-item>
                  <el-form-item label="满分"><el-input-number v-model="form.total_score" :min="0" :precision="1" /></el-form-item>
                  <el-form-item label="开始时间">
                    <el-date-picker
                      v-model="form.start_at"
                      type="datetime"
                      value-format="YYYY-MM-DDTHH:mm:ss"
                      format="YYYY年MM月DD日 HH:mm"
                      placeholder="选择开始时间"
                      popper-class="exam-datetime-popper"
                      style="width: 100%"
                    />
                  </el-form-item>
                  <el-form-item label="结束时间">
                    <el-date-picker
                      v-model="form.end_at"
                      type="datetime"
                      value-format="YYYY-MM-DDTHH:mm:ss"
                      format="YYYY年MM月DD日 HH:mm"
                      placeholder="选择结束时间"
                      popper-class="exam-datetime-popper"
                      style="width: 100%"
                    />
                  </el-form-item>
                  <el-form-item label="考试模式" class="setting-item">
                    <div class="checkbox-group">
                      <el-checkbox v-model="form.shuffle_questions">题目乱序</el-checkbox>
                      <el-checkbox v-model="form.shuffle_options">选项乱序</el-checkbox>
                      <el-checkbox v-model="form.per_student_paper">每人不同卷</el-checkbox>
                      <el-checkbox v-model="form.show_analysis_after">考后看解析</el-checkbox>
                      <el-checkbox v-model="form.allow_resubmit">允许重交</el-checkbox>
                    </div>
                    <div class="mode-tip">题目乱序在单选/多选/判断/填空/简答五类内部打乱（类间顺序不变）；选项乱序将打乱选择题选项内容（ABCD 标签位置不变，正确答案跟随内容），开始考试后顺序固定不再改变。</div>
                  </el-form-item>
                  <el-form-item label="防作弊" class="setting-item">
                    <div class="checkbox-group">
                      <el-checkbox v-model="form.anti.detect_blur">记录切屏</el-checkbox>
                      <el-checkbox v-model="form.anti.forbid_copy">禁止复制</el-checkbox>
                      <el-checkbox v-model="form.anti.forbid_paste">禁止粘贴</el-checkbox>
                      <el-checkbox v-model="form.anti.forbid_contextmenu">禁止右键</el-checkbox>
                    </div>
                  </el-form-item>
                </div>
              </div>

              <!-- 右列：组卷（页签比作业多：随机抽题 / 题库选题 / 自写题目） -->
              <div class="form-col form-col-right">
                <div class="exam-card exam-compose-card">
                  <div class="exam-card-head">
                    <el-icon><EditPen /></el-icon>组卷
                    <span class="compose-head-hint">左侧组卷选题，右侧实时预览试卷</span>
                  </div>
                  <el-alert
                    v-if="composedPaper"
                    class="compose-paper-alert"
                    type="info"
                    :closable="false"
                    show-icon
                    :title="`当前试卷已生成：共 ${composedPaper.count} 题，总分 ${composedPaper.total} 分。调整后再次点击「生成试卷」将覆盖原试卷。`"
                  />
                  <div class="compose-layout">
                    <el-tabs v-model="composeMode" class="compose-tabs">
                      <el-tab-pane label="随机抽题" name="random">
                        <div class="compose-pane">
                          <div class="compose-pane-tip">按题型/难度从课程题库随机抽题；请确保题库中已有【已发布】状态的题目。</div>
                          <el-table :data="rules" class="compose-rule-table" size="small">
                            <el-table-column label="题型" width="150">
                              <template #default="{ row }">
                                <el-select v-model="row.qtype" size="small" popper-class="exam-compose-popper">
                                  <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
                                </el-select>
                              </template>
                            </el-table-column>
                            <el-table-column label="难度" width="140">
                              <template #default="{ row }">
                                <el-select v-model="row.difficulty" size="small" clearable placeholder="不限" popper-class="exam-compose-popper">
                                  <el-option label="简单" value="easy" />
                                  <el-option label="中等" value="medium" />
                                  <el-option label="困难" value="hard" />
                                </el-select>
                              </template>
                            </el-table-column>
                            <el-table-column label="数量" width="130">
                              <template #default="{ row }"><el-input-number v-model="row.count" :min="1" size="small" /></template>
                            </el-table-column>
                            <el-table-column label="每题分" width="130">
                              <template #default="{ row }"><el-input-number v-model="row.score" :min="1" size="small" /></template>
                            </el-table-column>
                            <el-table-column width="80" align="center">
                              <template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="rules.splice($index, 1)"></el-button></template>
                            </el-table-column>
                          </el-table>
                          <el-button link type="primary" :icon="Plus" class="compose-add-rule" @click="addRule">添加规则</el-button>
                        </div>
                      </el-tab-pane>

                      <el-tab-pane label="题库选题" name="manual">
                        <div class="compose-pane compose-pane-manual">
                          <div class="question-filters">
                            <el-select v-model="poolFilters.catalog" clearable placeholder="章节" popper-class="exam-filter-popper" @change="loadPoolQuestions">
                              <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                            </el-select>
                            <el-select v-model="poolFilters.qtype" clearable placeholder="题型" popper-class="exam-filter-popper" @change="loadPoolQuestions">
                              <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
                            </el-select>
                            <el-select v-model="poolFilters.difficulty" clearable placeholder="难度" popper-class="exam-filter-popper" @change="loadPoolQuestions">
                              <el-option label="简单" value="easy" />
                              <el-option label="中等" value="medium" />
                              <el-option label="困难" value="hard" />
                            </el-select>
                            <button
                              class="pool-select-all"
                              :class="{ active: allFilteredSelected }"
                              type="button"
                              :disabled="!poolQuestions.length"
                              @click="toggleSelectAllFiltered"
                            >
                              {{ allFilteredSelected ? '取消全选' : `全选 ${poolQuestions.length} 题` }}
                            </button>
                          </div>
                          <el-table
                            :data="poolQuestions"
                            height="100%"
                            v-loading="poolLoading"
                            class="question-pool-table"
                            :row-class-name="poolRowClass"
                          >
                            <el-table-column prop="stem" label="题干" min-width="150">
                              <template #default="{ row }">
                                <QuestionDetailPopover v-bind="questionDetailOf(row)">
                                  <span class="pool-stem">{{ row.stem }}</span>
                                </QuestionDetailPopover>
                              </template>
                            </el-table-column>
                            <el-table-column label="题型" width="64" align="center">
                              <template #default="{ row }">
                                <span class="pool-tag type">{{ abbrQtype(row) }}</span>
                              </template>
                            </el-table-column>
                            <el-table-column label="难度" width="56" align="center">
                              <template #default="{ row }">
                                <span class="pool-tag difficulty" :class="`difficulty-${row.difficulty}`">{{ abbrDifficulty(row) }}</span>
                              </template>
                            </el-table-column>
                            <el-table-column label="操作" width="72" align="center">
                              <template #default="{ row }">
                                <button class="pool-action" :class="{ selected: isPoolSelected(row.id) }" type="button" @click="togglePoolQuestion(row)">
                                  {{ isPoolSelected(row.id) ? '移除' : '添加' }}
                                </button>
                              </template>
                            </el-table-column>
                          </el-table>
                        </div>
                      </el-tab-pane>

                      <el-tab-pane label="自写题目" name="custom">
                        <div class="compose-pane">
                          <el-form :model="draftQuestion" label-position="top" class="compose-custom-form">
                            <div class="custom-question-grid">
                              <el-form-item label="章节">
                                <el-select v-model="draftQuestion.catalog" placeholder="选择章节" popper-class="exam-compose-popper">
                                  <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                                </el-select>
                              </el-form-item>
                              <el-form-item label="题型">
                                <el-select v-model="draftQuestion.qtype" popper-class="exam-compose-popper" @change="resetDraftAnswer">
                                  <el-option v-for="t in qtypes" :key="t.value" :label="t.label" :value="t.value" />
                                </el-select>
                              </el-form-item>
                              <el-form-item label="难度">
                                <el-select v-model="draftQuestion.difficulty" popper-class="exam-compose-popper">
                                  <el-option label="简单" value="easy" />
                                  <el-option label="中等" value="medium" />
                                  <el-option label="困难" value="hard" />
                                </el-select>
                              </el-form-item>
                              <el-form-item label="分值">
                                <el-input-number v-model="draftQuestion.score" :min="1" />
                              </el-form-item>
                              <el-form-item label="题干" class="custom-span-full">
                                <el-input v-model="draftQuestion.stem" type="textarea" :rows="3" resize="none" placeholder="请输入题干" />
                              </el-form-item>
                              <template v-if="['single', 'multi'].includes(draftQuestion.qtype)">
                                <el-form-item v-for="option in draftQuestion.options" :key="option.key" :label="`选项 ${option.key}`">
                                  <el-input v-model="option.text" />
                                </el-form-item>
                              </template>
                              <el-form-item label="答案" class="custom-span-full">
                                <el-select v-if="draftQuestion.qtype === 'single'" v-model="draftQuestion.answerKey" placeholder="选择正确答案" popper-class="exam-compose-popper">
                                  <el-option v-for="option in draftQuestion.options" :key="option.key" :label="option.key" :value="option.key" />
                                </el-select>
                                <el-select v-else-if="draftQuestion.qtype === 'multi'" v-model="draftQuestion.answerKeys" multiple placeholder="选择正确答案" popper-class="exam-compose-popper">
                                  <el-option v-for="option in draftQuestion.options" :key="option.key" :label="option.key" :value="option.key" />
                                </el-select>
                                <el-select v-else-if="draftQuestion.qtype === 'judge'" v-model="draftQuestion.answerKey" placeholder="选择正确答案" popper-class="exam-compose-popper">
                                  <el-option label="正确" value="true" />
                                  <el-option label="错误" value="false" />
                                </el-select>
                                <el-input v-else v-model="draftQuestion.answerText" placeholder="填空题可用 / 分隔多个答案，简答题填写参考答案" />
                              </el-form-item>
                              <el-form-item label="解析" class="custom-span-full">
                                <el-input v-model="draftQuestion.analysis" type="textarea" :rows="2" resize="none" placeholder="可选" />
                              </el-form-item>
                            </div>
                            <div class="custom-compose-actions">
                              <el-button type="primary" :loading="creatingQuestion" @click="saveDraftQuestion">保存到题库并加入试卷</el-button>
                            </div>
                          </el-form>
                        </div>
                      </el-tab-pane>
                    </el-tabs>

                    <!-- 右列：试卷预览（结构对齐作业已选题目，hover 看题目详情） -->
                    <div class="selected-panel">
                      <div class="selected-header">
                        <strong>试卷预览 · {{ manualSelected.length }} 题</strong>
                        <span>总分 {{ manualTotal }} 分</span>
                      </div>
                      <div v-if="!manualSelected.length" class="selected-empty">
                        <el-icon><Plus /></el-icon>
                        <span>{{ composeMode === 'random' ? '设置抽题规则后点击「生成试卷」，抽出的题目会显示在这里' : '从左侧题库「添加」题目，或切换到「自写题目」页签' }}</span>
                      </div>
                      <el-scrollbar v-else class="selected-list-scroll">
                        <div class="selected-list">
                          <div v-for="(item, index) in manualSelected" :key="item.question_id" class="selected-item">
                            <div class="selected-item-main">
                              <span class="question-order">{{ index + 1 }}</span>
                              <QuestionDetailPopover v-bind="questionDetailOf(item)">
                                <span class="selected-stem">{{ item.stem }}</span>
                              </QuestionDetailPopover>
                            </div>
                            <div class="selected-item-sub">
                              <span class="pool-tag type selected-qtype">{{ abbrQtype(item) }}</span>
                              <el-input
                                v-model.number="item.score"
                                class="score-input"
                                type="number"
                                min="0.5"
                                max="100"
                                step="0.5"
                              />
                              <span class="score-unit">分</span>
                              <div class="selected-actions">
                                <el-button link circle :icon="ArrowUp" :disabled="index === 0" title="上移" @click="moveSelected(index, -1)" />
                                <el-button link circle :icon="ArrowDown" :disabled="index === manualSelected.length - 1" title="下移" @click="moveSelected(index, 1)" />
                                <el-button link type="danger" @click="manualSelected.splice(index, 1)">删除</el-button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </el-scrollbar>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </el-form>
        </div>
      </div>
    </Teleport>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除考试"
      :item-name="deleteTarget?.name"
      description="删除后将无法继续组卷、发布或查看该考试，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 监控与成绩批改 -->
    <el-drawer v-model="monitorVisible" title="考试监控与成绩批改" size="64%" class="monitor-drawer">
      <div class="monitor-toolbar">
        <div class="monitor-toolbar-left">
          <el-button type="primary" :loading="releasing" @click="doReleaseAll">统一出分（发布全部成绩）</el-button>
          <el-button :icon="TrendCharts" @click="openStats(monitorExamRow)">考试统计</el-button>
        </div>
        <div class="monitor-toolbar-right">
          <span class="monitor-auto-tip">
            每 5 秒自动刷新<span v-if="monitorLastAt"> · 更新于 {{ monitorLastAt }}</span>
          </span>
          <el-button :icon="Refresh" :loading="monitorRefreshing" @click="refreshMonitor">刷新</el-button>
        </div>
      </div>
      <div class="monitor-summary">
        <span class="summary-stat">已交卷 <strong>{{ submittedCount }}</strong> 份</span>
        <span class="summary-split" />
        <span class="summary-stat">待批改 <strong :class="{ warn: pendingCount > 0 }">{{ pendingCount }}</strong> 份</span>
      </div>
      <el-table :data="monitorRows" v-loading="monitorLoading" stripe>
        <el-table-column prop="student_name" label="学生" width="110" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }"><el-tag effect="light" round>{{ row.status_display }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="objective_score" label="客观题分" width="90" align="center" />
        <el-table-column prop="total_score" label="总分" width="80" align="center" />
        <el-table-column label="异常次数" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.abnormal_count" type="danger" size="small" effect="light" round>{{ row.abnormal_count }} 次</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="成绩" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.score_released" type="success" size="small" effect="light" round>已发布</el-tag>
            <span v-else class="text-muted">未发布</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'submitted' || row.status === 'timeout'"
              link type="primary" @click="openGrading(row)"
            >批改{{ row.subjective_count ? ` ${row.graded_subjective_count}/${row.subjective_count}` : '' }}</el-button>
            <el-button
              v-if="(row.status === 'submitted' || row.status === 'timeout') && !row.score_released"
              link type="success" @click="doReleaseOne(row)"
            >发布</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" min-width="150">
          <template #default="{ row }">{{ row.submitted_at ? new Date(row.submitted_at).toLocaleString() : '-' }}</template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <!-- 批改答卷：全卷回看 + 主观题评分（与作业批改一致） -->
    <el-dialog v-model="gradingVisible" title="批改答卷" width="720px" align-center :close-on-click-modal="false" class="exam-grade-dialog">
      <div v-loading="gradingLoading">
        <div v-if="gradingSub" class="grade-mode-brief">
          <span>学生：<strong>{{ gradingSub.student_name }}</strong></span>
          <span class="grade-brief-split" />
          <span>客观题得分 <strong>{{ gradingSub.objective_score ?? 0 }}</strong></span>
          <span class="grade-brief-split" />
          <span>共 {{ gradingReview.length }} 题</span>
          <template v-if="gradingPendingCount > 0">
            <span class="grade-brief-split" />
            <span class="grade-brief-pending">{{ gradingPendingCount }} 道主观题待评分</span>
          </template>
          <span v-else-if="gradingSubjectiveCount" class="grade-brief-done">主观题已全部评分</span>
        </div>
        <el-empty v-if="!gradingReview.length" description="暂无答卷内容" :image-size="80" />
        <div
          v-for="(q, i) in gradingReview"
          :key="q.question_id"
          class="answer-review-item"
          :class="{ 'is-pending': !q.is_objective && q.pending }"
        >
          <div class="answer-review-head">
            <strong>{{ i + 1 }}. {{ q.stem }}</strong>
            <span>{{ q.pending ? '待批' : (q.my_score ?? '-') }} / {{ q.score }} 分</span>
          </div>
          <QuestionImage :question="q" />
          <div v-if="q.options?.length" class="q-options">
            <div v-for="opt in q.options" :key="String(opt.key)" class="q-opt" :class="optClass(q, opt.key)">
              <span class="opt-key">{{ opt.key }}.</span>
              <span>{{ opt.text }}</span>
            </div>
          </div>
          <div class="student-answer">学生答案：{{ fmtGradingAnswer(q.student_answer) }}</div>
          <div class="correct-answer">正确答案：{{ fmtGradingAnswer(q.correct_answer) }}</div>
          <div v-if="q.analysis" class="answer-analysis">解析：{{ q.analysis }}</div>
          <div v-if="!q.is_objective" class="manual-grade-row">
            <span class="manual-grade-label">评分</span>
            <el-input-number v-model="gradingScores[q.question_id]" :min="0" :max="Number(q.score)" :step="0.5" controls-position="right" />
            <span class="text-muted">/ {{ q.score }} 分</span>
          </div>
          <el-tag v-else :type="q.is_correct ? 'success' : 'danger'" size="small">
            {{ q.is_correct ? '自动判定正确' : '自动判定错误' }}
          </el-tag>
        </div>
        <el-empty v-if="gradingReview.length && !gradingSubjectiveCount" description="该试卷没有主观题，客观题已自动评分" :image-size="80" />
      </div>
      <template #footer>
        <el-button @click="gradingVisible = false">取消</el-button>
        <el-button v-if="gradingSubjectiveCount" type="primary" :loading="gradingSaving" @click="doGrade">保存批改</el-button>
      </template>
    </el-dialog>

    <!-- 查看试卷（只读）：题干 hover 显示题目详情，与查看作业一致 -->
    <el-dialog v-model="paperVisible" title="查看试卷" width="720px" align-center class="exam-paper-dialog">
      <div v-loading="paperLoading">
        <template v-if="paperDetail">
          <div class="paper-brief">
            <span>{{ paperDetail.mode_display }}</span>
            <span class="paper-brief-split" />
            <span>共 <strong>{{ paperDetail.questions.length }}</strong> 题</span>
            <span class="paper-brief-split" />
            <span>总分 <strong>{{ paperDetail.total_score }}</strong> 分</span>
            <template v-if="paperDetail.per_student">
              <span class="paper-brief-split" />
              <span>展示为首位学生的个人试卷</span>
            </template>
          </div>
          <div v-for="(q, i) in paperDetail.questions" :key="q.question_id" class="paper-q-item">
            <span class="paper-q-order">{{ i + 1 }}</span>
            <QuestionDetailPopover v-bind="questionDetailOf(q)">
              <span class="paper-q-stem">{{ q.stem }}</span>
            </QuestionDetailPopover>
            <QuestionImage :question="q" />
            <el-tag size="small" effect="plain" round class="paper-q-type">{{ q.qtype_display }}</el-tag>
            <span class="paper-q-score">{{ q.score }} 分</span>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="paperVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus, EditPen, VideoPlay, CircleClose, View, Delete, Document, Close, Monitor,
  ArrowUp, ArrowDown, Tickets, Refresh, TrendCharts,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import QuestionImage from '@/components/QuestionImage.vue'
import { listClasses } from '@/api/classroom'
import { listExams, createExam, updateExam, deleteExam, composePaper, getExamPaper, monitorExam, releaseExamScores, examGradingDetail, gradeExamSubmission, releaseExamScore } from '@/api/exam'
import { listCatalogs } from '@/api/course'
import { listQuestions, createQuestion } from '@/api/question'
import { blankItems } from '@/utils/blank-answer'
import { abbrQtype, abbrDifficulty } from '@/utils/question-abbr'
import { sortedCourseNames } from '@/utils/course-sort'

const qtypes = [
  { value: 'single', label: '单选题' },
  { value: 'multi', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
]

const classes = ref([])
const classId = ref(null)
const exams = ref([])
const loading = ref(false)
const route = useRoute()
const router = useRouter()
const fixedCourseId = computed(() => Number(route.params.id) || null)

// 打开考试统计页（课程空间内走课程内嵌路由，保留课程导航）
function openStats(row) {
  const base = fixedCourseId.value
    ? `/teacher/courses/${fixedCourseId.value}/exams/${row.id}/stats`
    : `/teacher/exams/${row.id}/stats`
  router.push(base)
}

function classCourseNames(item) {
  // 多课程名按首字母排序（英文/数字在前、中文按拼音），与班级卡片口径一致
  return sortedCourseNames(item).join('、') || '未关联课程'
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    loadExams()
  } else {
    classId.value = null
    exams.value = []
  }
}
async function loadExams() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await listExams({ classroom: classId.value })
    exams.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatExamWindow(row) {
  const start = formatDateTime(row.start_at)
  const end = formatDateTime(row.end_at)
  if (start && end) return `${start} - ${end}`
  return start || end
}

// ---- 新建 / 编辑（整页工作台：基础信息 + 组卷）----
const editVisible = ref(false)
const saving = ref(false)
const publishing = ref(false)
const editingExam = ref(null)
const form = reactive({})
// 组卷状态：composeMode 与三个页签对应；rules 随机抽题规则；manualSelected 既是题库选题数据也是试卷预览
const composeMode = ref('random')
const rules = ref([])
const manualSelected = ref([])
// 已生成试卷摘要（打开已组卷考试时回填 / 组卷成功后更新），控制发布按钮可用与覆盖提示
const composedPaper = ref(null)
const composing = ref(false)
// 覆盖确认框打开中：禁用按钮并忽略连点，防止堆叠多个确认框（编辑器关闭后集中爆发）
const composeConfirming = ref(false)
const catalogOptions = ref([])
const poolQuestions = ref([])
const poolLoading = ref(false)
const creatingQuestion = ref(false)
const poolFilters = reactive({ catalog: null, qtype: '', difficulty: '' })
const draftQuestion = reactive({})
const manualTotal = computed(() => manualSelected.value.reduce((sum, item) => sum + Number(item.score || 0), 0))
const paperReady = computed(() => Boolean(composedPaper.value?.count))

const editorContext = computed(() => {
  const cls = classes.value.find((item) => item.id === (form.classroom || classId.value))
  if (!cls) return fixedCourseId.value ? '当前课程' : '请选择班级'
  return `${classCourseNames(cls)} · ${cls.name}`
})

function flattenCatalogs(items, depth = 0) {
  return (items || []).flatMap((item) => [
    { id: item.id, label: `${'　'.repeat(depth)}${item.title}` },
    ...flattenCatalogs(item.children, depth + 1),
  ])
}

function activeExamCourseId() {
  const cls = classes.value.find((c) => c.id === (form.classroom || classId.value))
  return form.course || fixedCourseId.value || cls?.course
}

async function loadCatalogOptions() {
  const course = activeExamCourseId()
  if (!course) return
  const data = await listCatalogs({ course, tree: 1, page_size: 100 })
  catalogOptions.value = flattenCatalogs(data.results ?? data)
  if (!draftQuestion.catalog && catalogOptions.value.length) {
    draftQuestion.catalog = catalogOptions.value[0].id
  }
}

async function loadPoolQuestions() {
  const course = activeExamCourseId()
  if (!course) return
  poolLoading.value = true
  try {
    const params = { course, status: 'published', page_size: 1000 }
    if (poolFilters.catalog) params.catalog = poolFilters.catalog
    if (poolFilters.qtype) params.qtype = poolFilters.qtype
    if (poolFilters.difficulty) params.difficulty = poolFilters.difficulty
    const data = await listQuestions(params)
    poolQuestions.value = data.results ?? data
  } finally {
    poolLoading.value = false
  }
}

function resetDraftAnswer() {
  Object.assign(draftQuestion, {
    options: [
      { key: 'A', text: '' },
      { key: 'B', text: '' },
      { key: 'C', text: '' },
      { key: 'D', text: '' },
    ],
    answerKey: '',
    answerKeys: [],
    answerText: '',
  })
}

function resetDraftQuestion() {
  Object.assign(draftQuestion, {
    catalog: catalogOptions.value[0]?.id || null,
    qtype: 'single',
    difficulty: 'medium',
    score: 5,
    stem: '',
    analysis: '',
  })
  resetDraftAnswer()
}

function resetComposeState() {
  composeMode.value = 'random'
  rules.value = [{ qtype: 'single', difficulty: '', count: 5, score: 2 }]
  manualSelected.value = []
  composedPaper.value = null
  poolFilters.catalog = null
  poolFilters.qtype = ''
  poolFilters.difficulty = ''
  resetDraftQuestion()
}

function openCreate() {
  editingExam.value = null
  Object.assign(form, {
    id: null, course: null, classroom: classId.value,
    name: '', start_at: '', end_at: '', duration: 60, total_score: 100, status: 'draft',
    shuffle_questions: true,
    // 选项乱序默认开启（ABCD 标签位置不变，正确答案跟随内容）
    shuffle_options: true,
    per_student_paper: false, show_analysis_after: true, allow_resubmit: false,
    anti: { detect_blur: true, forbid_copy: true, forbid_paste: true, forbid_contextmenu: true },
  })
  resetComposeState()
  editVisible.value = true
  loadCatalogOptions()
  loadPoolQuestions()
}

async function openEdit(row) {
  editingExam.value = row
  Object.assign(form, {
    id: row.id,
    course: row.course,
    classroom: row.classroom,
    name: row.name,
    start_at: row.start_at || '',
    end_at: row.end_at || '',
    duration: row.duration,
    total_score: row.total_score,
    status: row.status,
    shuffle_questions: row.shuffle_questions,
    shuffle_options: row.shuffle_options ?? true,
    per_student_paper: row.per_student_paper,
    show_analysis_after: row.show_analysis_after,
    allow_resubmit: row.allow_resubmit,
    anti: {
      detect_blur: true,
      forbid_copy: true,
      forbid_paste: true,
      forbid_contextmenu: true,
      ...(row.anti_cheat || {}),
    },
  })
  resetComposeState()
  editVisible.value = true
  loadCatalogOptions()
  loadPoolQuestions()
  // 已组卷：回填试卷信息（题目/分值/模式），再次进入组卷界面不再空白
  if (row.has_paper) {
    try {
      applyPaperToEditor(await getExamPaper(row.id))
    } catch {
      // 错误信息由拦截器提示；回填失败时组卷区为空，教师可重新组卷
    }
  }
}

function buildPayload() {
  const cls = classes.value.find((c) => c.id === (form.classroom || classId.value))
  const courseId = form.course || fixedCourseId.value || cls?.course
  return {
    course: courseId,
    classroom: form.classroom || classId.value,
    name: form.name?.trim() || '',
    start_at: form.start_at || null,
    end_at: form.end_at || null,
    duration: form.duration,
    total_score: form.total_score || 0,
    shuffle_questions: form.shuffle_questions,
    shuffle_options: form.shuffle_options,
    per_student_paper: form.per_student_paper,
    show_analysis_after: form.show_analysis_after,
    allow_resubmit: form.allow_resubmit,
    anti_cheat: form.anti,
    status: form.status || 'draft',
  }
}

// 保存基础信息（组卷/发布前会自动调用）；silent 用于内部流程（不弹成功提示）
async function saveBasic(silent = false) {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写考试名称')
    return null
  }
  const payload = buildPayload()
  if (!payload.course) {
    ElMessage.warning('该班级尚未关联课程')
    return null
  }
  if (form.start_at && form.end_at && new Date(form.end_at) <= new Date(form.start_at)) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return null
  }
  saving.value = true
  try {
    const isNew = !form.id
    const saved = isNew ? await createExam(payload) : await updateExam(form.id, payload)
    if (saved?.id) {
      form.id = saved.id
      form.status = saved.status || form.status
      if (isNew) editingExam.value = { id: saved.id }
    }
    if (!silent) ElMessage.success(isNew ? '已创建草稿，可继续组卷' : '已保存修改')
    loadExams()
    return form.id
  } catch {
    return null
  } finally {
    saving.value = false
  }
}

// 试卷详情 → 预览数据（题库选题数据与试卷预览共用）
function paperQuestionsToSelected(questions) {
  return (questions || []).map((q) => ({
    question_id: q.question_id,
    stem: q.stem,
    score: Number(q.score) || 5,
    qtype: q.qtype || '',
    difficulty: q.difficulty || '',
    qtype_display: q.qtype_display || '',
    difficulty_display: q.difficulty_display || '',
    options: Array.isArray(q.options) ? q.options : [],
    answer: q.answer ?? '',
    analysis: q.analysis || '',
  }))
}

function refreshPreviewFromPaper(detail) {
  manualSelected.value = paperQuestionsToSelected(detail?.questions)
  composedPaper.value = {
    count: detail?.questions?.length || 0,
    total: detail?.total_score ?? 0,
  }
}

// 打开已组卷考试：按试卷内容反推组卷信息（手动卷→已选题目；随机卷→按题型/难度聚合规则）
function applyPaperToEditor(detail) {
  refreshPreviewFromPaper(detail)
  if (detail?.mode === 'random') {
    composeMode.value = 'random'
    rules.value = rebuildRulesFromPaper(detail.questions || [])
  } else {
    composeMode.value = 'manual'
  }
}

function rebuildRulesFromPaper(questions) {
  const groups = new Map()
  ;(questions || []).forEach((q) => {
    const key = `${q.qtype || ''}|${q.difficulty || ''}`
    if (!groups.has(key)) {
      groups.set(key, {
        qtype: q.qtype || 'single',
        difficulty: q.difficulty || '',
        count: 0,
        score: Number(q.score) || 2,
      })
    }
    groups.get(key).count += 1
  })
  return [...groups.values()]
}

function addRule() {
  rules.value.push({ qtype: 'single', difficulty: '', count: 1, score: 2 })
}

async function doCompose() {
  // 组卷进行中/覆盖确认框打开中：忽略连点（确认框期间按钮同时置禁用）
  if (composing.value || composeConfirming.value) return
  if (composeMode.value === 'random') {
    if (!rules.value.some((r) => Number(r.count) > 0)) {
      return ElMessage.warning('请至少添加一条有效的抽题规则')
    }
  } else if (!manualSelected.value.length) {
    return ElMessage.warning('请先选择或新建题目')
  }
  if (composedPaper.value) {
    composeConfirming.value = true
    try {
      await ElMessageBox.confirm('重新生成试卷将覆盖当前试卷，确定继续吗？', '覆盖试卷', {
        type: 'warning',
        confirmButtonText: '重新生成',
        cancelButtonText: '取消',
      })
    } catch {
      return // 用户取消
    } finally {
      composeConfirming.value = false
    }
  }
  composing.value = true
  try {
    // 考试必须先落库才能组卷：新建态先自动创建草稿
    const examId = await saveBasic(true)
    if (!examId) return
    const payload = composeMode.value === 'random'
      ? { mode: 'random', rules: rules.value }
      : { mode: 'manual', questions: manualSelected.value.map((item) => ({ question_id: item.question_id, score: item.score })) }
    const res = await composePaper(examId, payload)
    const count = res.question_items?.length || 0
    composedPaper.value = { count, total: res.total_score }
    form.total_score = Number(res.total_score) || form.total_score
    ElMessage.success(`组卷完成，共 ${count} 题，总分 ${res.total_score}`)
    // 用试卷详情刷新预览，保证与后端真实试卷一致（随机抽题后也能回看题目）
    try {
      refreshPreviewFromPaper(await getExamPaper(examId))
    } catch {
      // 预览刷新失败不影响组卷结果
    }
    loadExams()
  } catch {
    // 错误信息由拦截器提示
  } finally {
    composing.value = false
  }
}

async function publishExam() {
  if (!paperReady.value) return ElMessage.warning('请先完成组卷再发布')
  // 组卷必须落在已保存的考试上，此时 form.id 必然存在
  if (!form.id) return ElMessage.warning('请先保存考试信息')
  publishing.value = true
  try {
    await updateExam(form.id, { ...buildPayload(), status: 'published' })
    form.status = 'published'
    ElMessage.success('已发布，学生端考试入口已可见')
    editVisible.value = false
    loadExams()
  } catch {
    // 错误信息由拦截器提示（如组卷被清空导致发布失败）
  } finally {
    publishing.value = false
  }
}

async function setStatus(row, status) {
  try {
    await updateExam(row.id, { ...row, status })
    ElMessage.success(status === 'published' ? '已发布' : '已结束')
    loadExams()
  } catch {
    // 错误信息由拦截器提示（如未组卷不能发布）
  }
}
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteExam(deleteTarget.value.id)
    ElMessage.success('考试已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    loadExams()
  } finally {
    deleting.value = false
  }
}

// ---- 题库选题 ----
function poolRowClass({ row }) {
  return isPoolSelected(row.id) ? 'is-added' : ''
}
function isPoolSelected(id) {
  return manualSelected.value.some((item) => Number(item.question_id) === Number(id))
}
function addPoolQuestion(question) {
  if (isPoolSelected(question.id)) return
  manualSelected.value.push({
    question_id: question.id,
    stem: question.stem,
    score: Number(question.score) || 5,
    qtype: question.qtype,
    difficulty: question.difficulty,
    qtype_display: question.qtype_display,
    difficulty_display: question.difficulty_display,
    options: Array.isArray(question.options) ? question.options : [],
    answer: question.answer ?? '',
    analysis: question.analysis || '',
  })
}
function togglePoolQuestion(question) {
  const index = manualSelected.value.findIndex((item) => Number(item.question_id) === Number(question.id))
  if (index >= 0) manualSelected.value.splice(index, 1)
  else addPoolQuestion(question)
}
const allFilteredSelected = computed(() =>
  poolQuestions.value.length > 0 && poolQuestions.value.every((q) => isPoolSelected(q.id)),
)
function toggleSelectAllFiltered() {
  if (allFilteredSelected.value) {
    // 取消全选只移除当前筛选范围内的题目，其他批次已选题目保留
    const ids = new Set(poolQuestions.value.map((q) => Number(q.id)))
    manualSelected.value = manualSelected.value.filter((item) => !ids.has(Number(item.question_id)))
  } else {
    poolQuestions.value.forEach((q) => addPoolQuestion(q))
  }
}
function moveSelected(index, offset) {
  const target = index + offset
  if (target < 0 || target >= manualSelected.value.length) return
  const [item] = manualSelected.value.splice(index, 1)
  manualSelected.value.splice(target, 0, item)
}

// 题干详情浮层入参（题库行 / 试卷预览 / 查看试卷通用）
function questionDetailOf(q) {
  return {
    stem: q?.stem || '',
    qtype: q?.qtype || '',
    difficulty: q?.difficulty || '',
    qtypeDisplay: q?.qtype_display || '',
    difficultyDisplay: q?.difficulty_display || '',
    score: q?.score ?? '',
    options: Array.isArray(q?.options) ? q.options : [],
    answer: q?.answer ?? '',
    analysis: q?.analysis || '',
  }
}

function buildDraftAnswer() {
  if (draftQuestion.qtype === 'single') return { key: draftQuestion.answerKey }
  if (draftQuestion.qtype === 'multi') return { keys: draftQuestion.answerKeys }
  if (draftQuestion.qtype === 'judge') return { key: draftQuestion.answerKey === 'true' }
  if (draftQuestion.qtype === 'blank') {
    return { blanks: String(draftQuestion.answerText || '').split('/').map((item) => item.trim()).filter(Boolean) }
  }
  return { text: draftQuestion.answerText || '' }
}

function buildDraftOptions() {
  if (draftQuestion.qtype === 'judge') {
    return [{ key: true, text: '正确' }, { key: false, text: '错误' }]
  }
  if (['single', 'multi'].includes(draftQuestion.qtype)) {
    return draftQuestion.options.filter((item) => item.text.trim())
  }
  return []
}

async function saveDraftQuestion() {
  const course = activeExamCourseId()
  if (!course) return ElMessage.warning('该班级尚未关联课程')
  if (!draftQuestion.catalog) return ElMessage.warning('请选择章节')
  if (!draftQuestion.stem?.trim()) return ElMessage.warning('请填写题干')
  const options = buildDraftOptions()
  if (['single', 'multi'].includes(draftQuestion.qtype) && options.length < 2) {
    return ElMessage.warning('选择题至少填写两个选项')
  }
  const answer = buildDraftAnswer()
  if (draftQuestion.qtype === 'single' && !answer.key) return ElMessage.warning('请选择正确答案')
  if (draftQuestion.qtype === 'multi' && !answer.keys.length) return ElMessage.warning('请选择正确答案')
  if (draftQuestion.qtype === 'judge' && answer.key === '') return ElMessage.warning('请选择正确答案')
  creatingQuestion.value = true
  try {
    const question = await createQuestion({
      course,
      catalog: draftQuestion.catalog,
      qtype: draftQuestion.qtype,
      stem: draftQuestion.stem,
      options,
      answer,
      analysis: draftQuestion.analysis,
      score: draftQuestion.score,
      difficulty: draftQuestion.difficulty,
      source: 'manual',
      status: 'published',
    })
    addPoolQuestion(question)
    // 自写题目加入的是「已选试卷」，切到题库选题页签以便继续调整后统一生成试卷
    composeMode.value = 'manual'
    await loadPoolQuestions()
    resetDraftQuestion()
    ElMessage.success('题目已加入试卷预览，点击「生成试卷」后生效')
  } finally {
    creatingQuestion.value = false
  }
}

// ---- 监控 ----
const monitorVisible = ref(false)
const monitorLoading = ref(false)
const monitorRefreshing = ref(false)
const monitorRows = ref([])
const monitorExamRow = ref(null)
const monitorLastAt = ref('')
const releasing = ref(false)
let monitorTimer = null

// 拉取监控数据（静默刷新不显示整表 loading，避免闪烁）
async function loadMonitor(showSpinner = true) {
  if (!monitorExamRow.value) return
  if (showSpinner) monitorLoading.value = true
  try {
    monitorRows.value = await monitorExam(monitorExamRow.value.id)
    monitorLastAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } finally {
    if (showSpinner) monitorLoading.value = false
  }
}

function stopMonitorPolling() {
  if (monitorTimer) {
    clearInterval(monitorTimer)
    monitorTimer = null
  }
}

// 抽屉打开期间每 5 秒静默轮询；关闭/卸载即停
function startMonitorPolling() {
  stopMonitorPolling()
  monitorTimer = setInterval(() => {
    if (monitorVisible.value && !monitorLoading.value && !monitorRefreshing.value) {
      loadMonitor(false)
    }
  }, 5000)
}

// 已交卷份数 / 待批改份数（含主观题且未批完的答卷）
const submittedCount = computed(() =>
  monitorRows.value.filter((r) => ['submitted', 'timeout'].includes(r.status)).length,
)
const pendingCount = computed(() =>
  monitorRows.value.filter(
    (r) =>
      ['submitted', 'timeout'].includes(r.status) &&
      r.has_subjective &&
      (r.graded_subjective_count ?? 0) < (r.subjective_count ?? 0),
  ).length,
)

async function openMonitor(row) {
  monitorExamRow.value = row
  monitorVisible.value = true
  await loadMonitor(true)
  startMonitorPolling()
}

// 手动刷新（保留loading态，按钮转圈）
async function refreshMonitor() {
  monitorRefreshing.value = true
  try {
    await loadMonitor(false)
  } finally {
    monitorRefreshing.value = false
  }
}

watch(monitorVisible, (v) => {
  if (!v) stopMonitorPolling()
})
onBeforeUnmount(stopMonitorPolling)

// ---- 查看试卷（只读）----
const paperVisible = ref(false)
const paperLoading = ref(false)
const paperDetail = ref(null)

async function openPaper(row) {
  paperVisible.value = true
  paperLoading.value = true
  paperDetail.value = null
  try {
    paperDetail.value = await getExamPaper(row.id)
  } catch {
    // 错误信息（如尚未组卷）由拦截器提示
  } finally {
    paperLoading.value = false
  }
}

// 统一出分：发布本场考试全部已批改答卷
async function doReleaseAll() {
  if (!monitorExamRow.value) return
  releasing.value = true
  try {
    const res = await releaseExamScores(monitorExamRow.value.id)
    if (res.skipped?.length) {
      ElMessage.warning(`已发布 ${res.released} 份成绩，以下学生因主观题未批改被跳过：${res.skipped.join('、')}`)
    } else {
      ElMessage.success(`已发布 ${res.released} 份成绩`)
    }
    await loadMonitor(false)
  } finally {
    releasing.value = false
  }
}

// 发布单个学生成绩
async function doReleaseOne(row) {
  try {
    await releaseExamScore(row.id)
    ElMessage.success('成绩已发布')
    await loadMonitor(false)
  } catch {
    // 错误信息由拦截器提示
  }
}

// ---- 主观题批改 ----
const gradingVisible = ref(false)
const gradingLoading = ref(false)
const gradingSaving = ref(false)
const gradingSub = ref(null)
const gradingReview = ref([])
const gradingScores = reactive({})

// 主观题数量 / 待评分数量（批改弹窗摘要用）
const gradingSubjectiveCount = computed(() =>
  gradingReview.value.filter((q) => !q.is_objective).length,
)
const gradingPendingCount = computed(() =>
  gradingReview.value.filter((q) => !q.is_objective && q.pending).length,
)

function fmtGradingAnswer(a) {
  if (!a) return '（未作答）'
  if (a.blanks) {
    // 学生答案为字符串数组、正确答案可能为按空赋分对象数组，统一走 blankItems 取文本
    const filled = blankItems(a).map((it) => it.text.trim()).filter((b) => b !== '')
    if (!filled.length) return '（未作答）'
    return filled.map((b, i) => `第 ${i + 1} 空：${b}`).join('；')
  }
  if (a.key != null && String(a.key) !== '') return String(a.key)
  if (a.keys?.length) return a.keys.join('、')
  if (a.text != null && String(a.text).trim() !== '') return String(a.text)
  return '（未作答）'
}

function optClass(q, key) {
  const c = q.correct_answer || {}
  if (String(c.key ?? '') === String(key) || (c.keys || []).map(String).includes(String(key))) return 'opt-right'
  const m = q.student_answer || {}
  if (String(m.key ?? '') === String(key) || (m.keys || []).map(String).includes(String(key))) return 'opt-wrong'
  return ''
}

async function openGrading(row) {
  gradingVisible.value = true
  gradingLoading.value = true
  gradingSub.value = null
  gradingReview.value = []
  try {
    const data = await examGradingDetail(row.id)
    gradingSub.value = data.submission
    gradingReview.value = data.answer_review || []
    Object.keys(gradingScores).forEach((k) => delete gradingScores[k])
    gradingReview.value.forEach((q) => {
      if (q.is_objective) return
      const saved = data.subjective_scores?.[String(q.question_id)]
      // 未评分默认预设 0 分（不与空值混淆，教师直接改分即可）
      gradingScores[q.question_id] = saved != null ? Number(saved) : 0
    })
    // 与作业批改一致：打开后自动定位到第一道待评分主观题，
    // 避免评分行藏在折叠线下方被漏看
    nextTick(() => {
      setTimeout(() => {
        const first = document.querySelector(
          '.exam-grade-dialog .answer-review-item.is-pending .manual-grade-row',
        )
        if (first) first.scrollIntoView({ block: 'center' })
      }, 60)
    })
  } finally {
    gradingLoading.value = false
  }
}

async function doGrade() {
  if (!gradingSub.value) return
  gradingSaving.value = true
  try {
    // 未填写的题目不上报（默认 0 分会正常提交），后端支持分批批改
    const scores = {}
    Object.entries(gradingScores).forEach(([qid, v]) => {
      if (v !== null && v !== undefined && v !== '') scores[qid] = v
    })
    await gradeExamSubmission(gradingSub.value.id, { scores })
    ElMessage.success('批改已保存')
    gradingVisible.value = false
    await loadMonitor(false)
  } catch {
    // 错误信息由拦截器提示
  } finally {
    gradingSaving.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.monitor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.monitor-toolbar-left,
.monitor-toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.monitor-toolbar-right {
  flex-wrap: wrap;
  justify-content: flex-end;
}
.monitor-auto-tip {
  font-size: 12.5px;
  color: #64748b;
  white-space: nowrap;
}

.monitor-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 13px;
  color: #475569;
}
.monitor-summary strong {
  color: #0f172a;
  font-weight: 700;
}
.monitor-summary strong.warn {
  color: #d97706;
}
/* 统计项单行显示，不随抽屉宽度换行 */
.monitor-summary .summary-stat {
  white-space: nowrap;
  flex-shrink: 0;
}
.monitor-summary .summary-split {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
  flex-shrink: 0;
}

/* 监控抽屉宽屏封顶，与作业批改抽屉一致 */
.monitor-drawer :deep(.el-drawer) {
  max-width: 820px;
}

/* 发布按钮禁用态外层包裹，保证 tooltip 可触发 */
.action-wrap {
  display: inline-flex;
  vertical-align: middle;
}

/* 查看试卷（只读） */
.paper-brief {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 13px;
  color: #475569;
}
.paper-brief strong {
  color: #0f172a;
}
.paper-brief-split {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
}
.paper-q-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #e5eaf3;
  border-radius: 10px;
  background: #fff;
}
.paper-q-order {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 13px;
  font-weight: 700;
}
.paper-q-stem {
  flex: 1;
  min-width: 0;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.6;
  cursor: help;
}
.paper-q-type {
  flex-shrink: 0;
}
.paper-q-score {
  flex-shrink: 0;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
}

/* 批改答卷弹窗（版式对齐作业批改） */
.grade-mode-brief {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 13px;
  color: #475569;
}
.grade-mode-brief strong {
  color: #0f172a;
}
.grade-brief-split {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
}
.grade-brief-pending {
  color: #d97706;
  font-weight: 600;
}
.grade-brief-done {
  color: #059669;
  font-weight: 600;
}
.answer-review-item {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid #e5eaf3;
  border-radius: 12px;
}
.answer-review-item.is-pending {
  border-color: #fde68a;
  background: #fffbeb;
}
.answer-review-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.6;
}
.answer-review-head span {
  flex-shrink: 0;
  color: #64748b;
  font-size: 13px;
}
.student-answer,
.correct-answer,
.answer-analysis {
  margin-top: 6px;
  font-size: 13.5px;
  line-height: 1.7;
  color: #334155;
}
.correct-answer {
  color: #047857;
}
.answer-analysis {
  color: #64748b;
}
.manual-grade-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}
.manual-grade-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}
.q-options {
  margin-bottom: 6px;
}
.q-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
  padding: 6px 12px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13.5px;
  color: #334155;
}
.q-opt.opt-right {
  background: #ecfdf5;
  color: #047857;
}
.q-opt.opt-wrong {
  background: #fef2f2;
  color: #b91c1c;
}
.opt-key {
  font-weight: 700;
}

.exam-page :deep(.data-card) {
  padding: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.exam-page :deep(.data-card > .el-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0;
}
.module-toolbar {
  margin: 0 0 16px;
  padding: 0;
  border-bottom: 0;
}
.module-primary-button {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  font-weight: 800;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  box-shadow: 0 11px 22px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.exam-list-shell {
  flex: 1;
  overflow: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.exam-card-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0 0 8px;
}
.exam-list-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100, #e5e9f0);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.exam-list-card:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.exam-card-main {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
  min-width: 0;
}
.exam-kind-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 32px;
  padding: 0 12px;
  border-radius: 9px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
}
.exam-card-content {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}
.exam-card-title {
  overflow: hidden;
  color: #0f172a;
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exam-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  color: #64748b;
  font-size: 12.5px;
  font-weight: 600;
}
.exam-meta-pill,
.exam-status-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}
.exam-meta-pill.duration {
  color: #475569;
  background: #f1f5f9;
}
.exam-score {
  color: #64748b;
  font-weight: 700;
}
.exam-status-pill.draft {
  color: #d97706;
  border: 1px solid #fed7aa;
  background: #fff7ed;
}
.exam-status-pill.published {
  color: #16a34a;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
}
.exam-status-pill.finished {
  color: #64748b;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
}
.exam-meta-pill.blue {
  color: #2563eb;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}
.exam-meta-pill.orange {
  color: #d97706;
  border: 1px solid #fed7aa;
  background: #fff7ed;
}
.exam-meta-pill.slate {
  color: #475569;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
}
.exam-card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.exam-card-actions :deep(.el-button.is-link) {
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}
.exam-card-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.exam-card-actions :deep(.el-button.is-link:hover) {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.exam-card-actions :deep(.el-button--success.is-link:hover) {
  background: #ecfdf5;
}
.exam-card-actions :deep(.el-button--danger.is-link:hover) {
  background: #fff1f2;
}
.exam-card-list :deep(.el-empty) {
  min-height: 430px;
}
.module-table {
  --el-table-border-color: #edf2f8;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: #fff;
  --el-table-row-hover-bg-color: #f8fbff;
  overflow: hidden;
  background: #fff;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  height: 58px;
  padding: 0 24px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 13px;
  font-weight: 850;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.module-table :deep(td.el-table__cell) {
  height: 76px;
  padding: 14px 24px;
  border-bottom: 1px solid #edf2f8;
  color: #334155;
  font-weight: 700;
  background: #fff;
}
.module-table :deep(.el-table__body tr:nth-child(even) > td.el-table__cell) {
  background: #fbfdff;
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: #f8fbff;
}
.module-table :deep(.el-tag) {
  height: 26px;
  padding: 0 10px;
  border-radius: 9px;
  font-weight: 760;
}
.module-table :deep(.el-button.is-link) {
  height: 30px;
  padding: 0 8px;
  border-radius: 9px;
  font-weight: 780;
  text-decoration: none;
}
.module-table :deep(.el-button.is-link:hover) {
  background: #eff6ff;
}
.module-table :deep(.el-button--success.is-link:hover) {
  background: #ecfdf5;
}
.module-table :deep(.el-button--danger.is-link:hover) {
  background: #fff1f2;
}
.exam-list-shell :deep(.el-empty) {
  min-height: 420px;
}

/* ============ 整页编辑器（版式对齐发布作业）============ */
/* EP 弹层（消息/确认框/下拉/日期/题干浮层）均内联 z-index（2000 起步），
   会被 z-index 3000 的全屏编辑器盖住，必须显式抬高。
   注意 EP 2.14.2 的 MessageBox 根节点是 el-overlay（类名 el-overlay is-message-box，
   z-index 内联在根节点上），旧版类名 el-message-box__wrapper 已不存在，勿写错选择器。 */
:global(.el-message) {
  z-index: 5200 !important;
}
:global(.el-overlay.is-message-box) {
  z-index: 5400 !important;
}
:global(.exam-editor-tooltip.el-popper) {
  z-index: 5400 !important;
}
:global(.exam-filter-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid #bfdbfe !important;
  border-radius: 16px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 18px 38px rgba(37, 99, 235, 0.14), 0 0 0 5px rgba(219, 234, 254, 0.24) !important;
}
:global(.exam-filter-popper .el-popper__arrow) {
  display: none;
}
:global(.exam-filter-popper .el-select-dropdown) {
  border: 0;
  border-radius: 16px;
  background: transparent;
  box-shadow: none;
}
:global(.exam-filter-popper .el-select-dropdown__list) {
  padding: 8px 0;
}
:global(.exam-filter-popper .el-select-dropdown__item) {
  height: 40px;
  padding: 0 16px;
  color: #475569;
  font-size: 14px;
  font-weight: 700;
  line-height: 40px;
}
:global(.exam-filter-popper .el-select-dropdown__item.is-selected) {
  color: #2563eb;
  background: #eff6ff;
}
.exam-editor {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  color: #0f172a;
}
.exam-editor,
.exam-editor * {
  scrollbar-width: none;
}
.exam-editor::-webkit-scrollbar,
.exam-editor *::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}
.exam-editor-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.08);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.06);
  backdrop-filter: blur(18px) saturate(1.08);
}
.exam-editor-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.exam-editor-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  border-radius: 14px;
  color: #2563eb;
  background: #eaf2ff;
  font-size: 20px;
}
.exam-editor-heading { min-width: 0; }
.exam-editor-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.exam-editor-title {
  color: #14213d;
  font-size: 18px;
  font-weight: 850;
  line-height: 1.25;
  white-space: nowrap;
}
.exam-editor-kicker {
  overflow: hidden;
  max-width: 260px;
  padding: 2px 10px;
  border-radius: 999px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exam-editor-subtitle {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12.5px;
}
.exam-editor-stats {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-left: auto;
  padding: 7px 12px;
  border: 1px solid rgba(191, 219, 254, 0.7);
  border-radius: 999px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
  font-size: 12px;
  white-space: nowrap;
}
.exam-editor-stats strong {
  color: #2563eb;
  font-size: 16px;
}
.exam-stats-split {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
}
.exam-editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.exam-editor-actions :deep(.el-button) {
  height: 38px;
  border-radius: 11px;
  font-weight: 700;
}
.exam-editor-actions :deep(.el-button--primary) {
  border-color: #3b82f6;
  background: #3b82f6;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.2);
}
.exam-editor-body {
  min-width: 0;
  min-height: 0;
  padding: 12px 14px 14px;
  overflow: hidden;
}
.exam-editor .exam-creation-form {
  height: 100%;
  min-height: 0;
  padding: 0;
}
.creation-form-grid {
  display: grid;
  grid-template-columns: clamp(340px, 25vw, 430px) minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  height: 100%;
  min-height: 0;
}
.form-col { min-width: 0; min-height: 0; display: flex; }

/* 分组卡片（左右等高） */
.exam-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 14px 14px 16px;
  border: 1px solid rgba(191, 219, 254, 0.58);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow:
    0 24px 64px rgba(37, 99, 235, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  overflow: hidden;
  backdrop-filter: blur(18px) saturate(1.08);
}
.exam-info-card {
  overflow: auto;
}
/* 左卡（基础信息）表单项间距收紧 */
.exam-info-card :deep(.el-form-item) {
  margin-bottom: 12px;
}
.exam-compose-card {
  overflow: hidden;
}
.exam-card :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.exam-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.9);
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}
.exam-card-head :deep(.el-icon) {
  color: #2563eb;
  font-size: 15px;
}
.compose-head-hint {
  margin-left: auto;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
}
.exam-creation-form :deep(.el-form-item) { margin-bottom: 18px; }
.exam-creation-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 8px;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
}
.exam-creation-form :deep(.el-input__wrapper),
.exam-creation-form :deep(.el-date-editor.el-input),
.exam-creation-form :deep(.el-input-number) {
  min-height: 44px;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: none;
}
.exam-creation-form :deep(.el-input__wrapper:focus-within),
.exam-creation-form :deep(.el-date-editor.el-input:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.exam-creation-form :deep(.el-input-number) { width: 100%; }
.setting-item {
  padding: 13px 14px 7px;
  border: 1px solid #e4edf7;
  border-radius: 12px;
  background: #f8fbff;
}
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  padding-top: 2px;
}
.checkbox-group :deep(.el-checkbox) { margin-right: 0; color: #475569; font-weight: 600; }
.mode-tip { margin-top: 8px; color: #94a3b8; font-size: 12px; line-height: 1.6; }

/* 组卷卡：左页签（组卷方式）+ 右试卷预览 */
.compose-paper-alert {
  flex: none;
  margin-bottom: 10px;
}
.compose-layout {
  flex: 1;
  display: flex;
  gap: 10px;
  min-height: 0;
  min-width: 0;
}
.compose-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.compose-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}
.compose-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.compose-tabs :deep(.el-tab-pane) {
  height: 100%;
}
.compose-pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}
/* 题库选题：筛选行（auto）+ 题库表格（剩余高度） */
.compose-pane-manual {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}
.compose-pane-tip {
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.6;
}
.compose-add-rule {
  align-self: flex-start;
}

/* 组卷页签（随机/题库/自写） */
.compose-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.compose-tabs :deep(.el-tabs__nav) {
  gap: 8px;
}
.compose-tabs :deep(.el-tabs__active-bar) {
  display: none;
}
.compose-tabs :deep(.el-tabs__item) {
  height: 38px;
  padding: 0 18px !important;
  border: 1px solid #dbeafe;
  border-radius: 11px;
  color: #64748b;
  background: #f8fbff;
  font-weight: 780;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.compose-tabs :deep(.el-tabs__item:hover) {
  border-color: #bfdbfe;
  color: #2563eb;
  background: #eff6ff;
}
.compose-tabs :deep(.el-tabs__item.is-active) {
  border-color: transparent;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}

/* 抽题规则表 */
.compose-rule-table {
  overflow: hidden;
  border: 1px solid #e5edf7;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.045);
}
.compose-rule-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.compose-rule-table :deep(th.el-table__cell) {
  height: 44px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 13px;
  font-weight: 820;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.compose-rule-table :deep(td.el-table__cell) {
  height: 54px;
  border-bottom-color: #edf2f8;
  color: #334155;
}
.compose-rule-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: #f8fbff;
}
.compose-rule-table :deep(.el-select__wrapper),
.compose-rule-table :deep(.el-input-number) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: none;
}
.compose-rule-table :deep(.el-input-number),
.compose-rule-table :deep(.el-input-number .el-input__wrapper) {
  width: 96px;
}

/* 题库筛选行 */
.question-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}
.question-filters :deep(.el-select) {
  flex: 1 1 128px;
  min-width: 0;
}
.question-filters :deep(.el-select__wrapper) {
  min-height: 34px;
  padding: 0 10px;
  border-radius: 11px;
  background: rgba(248, 251, 255, 0.94);
  box-shadow: inset 0 0 0 1px #dbe5ef, 0 4px 12px rgba(37, 99, 235, 0.035);
  transition: background-color 0.18s ease, box-shadow 0.18s ease;
}
.question-filters :deep(.el-select__wrapper:hover),
.question-filters :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe, 0 0 0 3px rgba(59, 130, 246, 0.09);
}
/* 全选当前筛选范围（范围已全选时变为「取消全选」） */
.pool-select-all {
  flex: 0 0 auto;
  height: 34px;
  padding: 0 14px;
  border: 1px solid #bfdbfe;
  border-radius: 11px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.78);
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}
.pool-select-all:hover:not(:disabled) {
  border-color: #60a5fa;
  color: #fff;
  background: #3b82f6;
}
.pool-select-all:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pool-select-all.active {
  border-color: #fecaca;
  color: #ef4444;
  background: #fef2f2;
}
.pool-select-all.active:hover:not(:disabled) {
  border-color: #ef4444;
  color: #fff;
  background: #ef4444;
}

/* 题库表格 */
.question-pool-table {
  overflow: hidden;
  border: 1px solid #e5edf7;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.045);
}
.question-pool-table :deep(.el-table__inner-wrapper::before) { display: none; }
.question-pool-table :deep(.el-table__body tr) {
  transition: background-color 0.18s ease;
}
.question-pool-table :deep(th.el-table__cell) {
  height: 36px;
  border-bottom: 1px solid #e2ebf7;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  background: linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
}
.question-pool-table :deep(td.el-table__cell) {
  height: 44px;
  padding: 0 6px;
  border-bottom-color: #edf2f8;
  color: #334155;
}
/* 题库列表列宽很紧，必须把 .cell 内边距清零，空间全部留给标签与按钮 */
.question-pool-table :deep(.el-table__cell .cell) {
  padding: 0;
}
.question-pool-table :deep(.el-table__row:hover > td.el-table__cell) {
  background: #f8fbff;
}
/* 已添加题目：整行浅蓝高亮 + 首列左侧蓝色竖条 + 题干加粗变色 */
.question-pool-table :deep(.el-table__row.is-added > td.el-table__cell) {
  background: #e8f1fe;
}
.question-pool-table :deep(.el-table__row.is-added:hover > td.el-table__cell) {
  background: #d9e8fd;
}
.question-pool-table :deep(.el-table__row.is-added > td.el-table__cell:first-child) {
  box-shadow: inset 3px 0 0 #3b82f6;
}
.question-pool-table :deep(.el-table__row.is-added .pool-stem) {
  color: #1d4ed8;
  font-weight: 700;
}
.pool-stem {
  display: block;
  overflow: hidden;
  color: #334155;
  font-size: 13px;
  font-weight: 560;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: help;
}
.pool-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 20px;
  padding: 0 4px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 750;
  white-space: nowrap;
}
.pool-tag.type {
  border: 1px solid #bfdbfe;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.72);
}
.pool-tag.difficulty {
  border: 1px solid #dbeafe;
  color: #64748b;
  background: #f8fbff;
}
.pool-tag.difficulty-easy {
  border-color: #bbf7d0;
  color: #16a34a;
  background: rgba(240, 253, 244, 0.72);
}
.pool-tag.difficulty-medium {
  border-color: #fed7aa;
  color: #d97706;
  background: rgba(255, 247, 237, 0.78);
}
.pool-tag.difficulty-hard {
  border-color: #fecaca;
  color: #ef4444;
  background: rgba(254, 242, 242, 0.78);
}
.pool-action {
  height: 24px;
  min-width: 44px;
  padding: 0 6px;
  border: 1px solid #bfdbfe;
  border-radius: 7px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.78);
  font-size: 11.5px;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}
.pool-action:hover {
  border-color: #60a5fa;
  color: #fff;
  background: #3b82f6;
}
.pool-action.selected {
  border-color: #fecaca;
  color: #ef4444;
  background: #fef2f2;
}
.pool-action.selected:hover {
  border-color: #ef4444;
  color: #fff;
  background: #ef4444;
}
.question-pool-table :deep(.el-scrollbar__bar),
.selected-list-scroll :deep(.el-scrollbar__bar) {
  display: none !important;
}

/* 试卷预览（右列，结构对齐作业已选题目） */
.selected-panel {
  flex: 0 0 384px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  padding: 12px 12px 10px;
  border: 1px solid #e5edf7;
  border-radius: 18px;
  background: rgba(248, 251, 255, 0.68);
}
.selected-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 2px 10px;
  border-bottom: 1px solid #e8eef7;
  color: #334155;
  font-size: 14px;
}
.selected-header strong {
  font-weight: 800;
  white-space: nowrap;
}
.selected-header span { color: #2563eb; font-weight: 700; white-space: nowrap; }
.selected-empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 140px;
  margin-top: 10px;
  padding: 15px 14px;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  color: #94a3b8;
  font-size: 13px;
  text-align: center;
  background: rgba(255, 255, 255, 0.5);
}
.selected-empty :deep(.el-icon) { font-size: 22px; }
.selected-list-scroll {
  flex: 1;
  min-height: 0;
  margin-top: 10px;
}
.selected-list-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden;
}
.selected-list-scroll :deep(.el-scrollbar__view) {
  min-height: 100%;
}
.selected-list {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 0;
  padding: 0 2px 2px 0;
}
/* 紧凑双行卡片：上行序号+题干（两行截断），下行简写题型+分值+操作 */
.selected-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid #e8eef7;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 5px 14px rgba(37, 99, 235, 0.035);
}
.selected-item-main {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}
.selected-item-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-left: 34px;
}
.selected-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
}
.question-order {
  display: grid;
  width: 26px;
  height: 26px;
  flex: none;
  place-items: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 13px;
  font-weight: 800;
  box-shadow: inset 0 0 0 1px rgba(191, 219, 254, 0.72);
}
.selected-stem {
  display: -webkit-box;
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
  cursor: help;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.selected-qtype { min-width: 36px; height: 22px; padding: 0 6px; font-size: 12px; }
.score-input {
  width: 64px;
  flex: none;
}
.score-input :deep(.el-input__wrapper) {
  min-height: 30px;
  border-radius: 9px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbeafe;
}
.score-input :deep(.el-input__inner) {
  text-align: center;
  font-weight: 700;
}
.score-input :deep(input::-webkit-outer-spin-button),
.score-input :deep(input::-webkit-inner-spin-button) {
  margin: 0;
  appearance: none;
}
.score-input :deep(input[type='number']) {
  appearance: textfield;
}
.score-unit {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

/* 自写题目表单 */
.compose-custom-form {
  padding: 4px 2px 0;
}
.custom-question-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 14px;
}
.custom-span-full {
  grid-column: 1 / -1;
}
.compose-custom-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
.compose-custom-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 780;
  line-height: 1.35;
}
.compose-custom-form :deep(.el-select__wrapper),
.compose-custom-form :deep(.el-input__wrapper),
.compose-custom-form :deep(.el-textarea__inner),
.compose-custom-form :deep(.el-input-number) {
  min-height: 42px;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  background: #f8fbff;
  box-shadow: none;
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.compose-custom-form :deep(.el-select__wrapper:hover),
.compose-custom-form :deep(.el-select__wrapper.is-focused),
.compose-custom-form :deep(.el-input__wrapper:hover),
.compose-custom-form :deep(.el-input__wrapper.is-focus),
.compose-custom-form :deep(.el-textarea__inner:focus) {
  border-color: #bfdbfe;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.09);
}
.custom-compose-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
.custom-compose-actions :deep(.el-button) {
  height: 38px;
  border-radius: 11px;
  font-weight: 780;
}

/* 弹层（日期选择 / 下拉）样式：编辑器 z-index 3000，弹层需更高 */
:global(.exam-datetime-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.48) !important;
  border-radius: 18px !important;
  background: #fff !important;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.18), 0 0 0 6px rgba(219, 234, 254, 0.16) !important;
}
:global(.exam-datetime-popper .el-popper__arrow) {
  display: none;
}
:global(.exam-datetime-popper .el-picker-panel) {
  border: 0;
  border-radius: 18px;
  color: #334155;
  background: #fff;
  box-shadow: none;
}
:global(.exam-datetime-popper .el-date-picker) {
  width: 560px;
}
:global(.exam-datetime-popper .el-date-picker__time-header) {
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input:first-child) {
  width: 214px;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input:last-child) {
  width: 150px;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input__wrapper) {
  min-height: 36px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
:global(.exam-datetime-popper .el-date-picker__time-header .el-input__wrapper:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
:global(.exam-datetime-popper .el-date-picker__header) {
  width: 320px;
  margin: 14px 18px 8px;
}
:global(.exam-datetime-popper .el-date-picker__header-label) {
  color: #334155;
  font-size: 15px;
  font-weight: 750;
}
:global(.exam-datetime-popper .el-picker-panel__icon-btn) {
  width: 28px;
  height: 28px;
  margin: 0 1px;
  border-radius: 8px;
  color: #64748b;
}
:global(.exam-datetime-popper .el-picker-panel__icon-btn:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-date-table th) {
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-picker-panel__content) {
  width: 320px;
  margin: 12px 218px 12px 18px;
}
:global(.exam-datetime-popper .el-date-table td .el-date-table-cell) {
  width: 34px;
  height: 34px;
  margin: 1px auto;
  border-radius: 10px;
}
:global(.exam-datetime-popper .el-date-table td.available:hover .el-date-table-cell) {
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-date-table td.available:hover span),
:global(.exam-datetime-popper .el-date-table td.today span) {
  color: #2563eb;
  font-weight: 750;
}
:global(.exam-datetime-popper .el-date-table td.current:not(.disabled) .el-date-table-cell) {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.24);
}
:global(.exam-datetime-popper .el-date-table td.current:not(.disabled) span) {
  color: #fff;
}
:global(.exam-datetime-popper .el-picker-panel__footer) {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px 12px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-picker-panel__footer .el-button) {
  min-width: 64px;
  height: 34px;
  border-radius: 9px;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-picker-panel__footer .el-button--primary) {
  border-color: #3b82f6;
  color: #fff;
  background: #3b82f6;
}
:global(.exam-datetime-popper .el-time-panel) {
  top: 74px !important;
  right: 16px !important;
  left: auto !important;
  width: 178px !important;
  overflow: hidden;
  border: 1px solid #dbe5f2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12);
}
:global(.exam-datetime-popper .el-time-panel::before) {
  content: "选择时间";
  display: block;
  height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid #edf2f8;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 38px;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-time-panel__content) {
  height: 194px;
}
:global(.exam-datetime-popper .el-time-panel__content::before),
:global(.exam-datetime-popper .el-time-panel__content::after) {
  border-color: #e5edf7;
}
:global(.exam-datetime-popper .el-time-spinner__item) {
  color: #64748b;
}
:global(.exam-datetime-popper .el-time-spinner__item:hover:not(.is-disabled):not(.is-active)) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.exam-datetime-popper .el-time-spinner__item.is-active:not(.is-disabled)) {
  color: #2563eb;
  font-weight: 800;
}
:global(.exam-datetime-popper .el-time-panel__footer) {
  height: auto;
  padding: 9px 10px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.exam-datetime-popper .el-time-panel__btn) {
  min-width: 58px;
  height: 32px;
  margin: 0 2px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 700;
}
:global(.exam-datetime-popper .el-time-panel__btn.confirm) {
  color: #fff;
  background: #3b82f6;
}

/* 组卷相关下拉（规则表 / 自写题目） */
:global(.exam-compose-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid #bfdbfe !important;
  border-radius: 16px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 18px 38px rgba(37, 99, 235, 0.14), 0 0 0 5px rgba(219, 234, 254, 0.24) !important;
}
:global(.exam-compose-popper .el-popper__arrow) {
  display: none;
}
:global(.exam-compose-popper .el-select-dropdown) {
  border: 0;
  border-radius: 16px;
  background: transparent;
  box-shadow: none;
}
:global(.exam-compose-popper .el-select-dropdown__list) {
  padding: 8px 0;
}
:global(.exam-compose-popper .el-select-dropdown__item) {
  height: 42px;
  padding: 0 18px;
  color: #475569;
  font-size: 14px;
  font-weight: 760;
  line-height: 42px;
}
:global(.exam-compose-popper .el-select-dropdown__item.is-hovering),
:global(.exam-compose-popper .el-select-dropdown__item:hover),
:global(.exam-compose-popper .el-select-dropdown__item.is-selected) {
  color: #2563eb;
  background: #eff6ff;
}

.empty-text {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 4px;
}

.empty-tip {
  font-size: 12px;
  color: #94a3b8;
}

.text-muted {
  color: #94a3b8;
}

@media (max-width: 1120px) {
  .exam-list-card {
    grid-template-columns: 1fr;
  }

  .exam-card-actions {
    justify-content: flex-start;
    width: 100%;
    min-width: 0;
  }
}

@media (max-width: 920px) {
  .creation-form-grid {
    grid-template-columns: 1fr;
  }
  .compose-layout {
    flex-direction: column;
  }
  .selected-panel {
    flex: 0 0 auto;
    max-height: 40%;
  }
  .custom-question-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .exam-page :deep(.data-card > .el-card__body) {
    padding: 20px 18px 24px;
  }

  .exam-card-main {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .exam-list-card {
    padding: 18px;
  }

  .exam-card-actions {
    flex-wrap: wrap;
    min-height: auto;
    padding: 10px;
  }
}
</style>
