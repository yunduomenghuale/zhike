<template>
  <div class="page-container homework-page" :class="{ 'is-editing': editVisible }">
    <template v-if="!editVisible">
    <div class="page-header">
      <div>
        <div class="page-title">作业管理</div>
        <div class="page-subtitle">发布作业、查看提交情况并批改评分</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <div class="toolbar module-toolbar">
        <div class="toolbar-left">
          <el-select v-model="classId" class="module-select" placeholder="选择班级" popper-class="module-select-popper" style="width: 280px" @change="load">
            <el-option v-for="c in classes" :key="c.id" :label="`${c.name} / ${classCourseNames(c)}`" :value="c.id" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button v-if="classId" class="module-primary-button" type="primary" :icon="Plus" @click="openEdit()">发布作业</el-button>
        </div>
      </div>

      <el-empty v-if="!classId" description="请先选择班级" />
      <template v-else>
        <TableSkeleton v-if="loading" :cols="5" />
        <el-empty v-else-if="!rows.length" :image-size="110">
          <template #description>
            <div class="hw-empty-text">还没有作业</div>
            <div class="hw-empty-tip">点击右上角「发布作业」开始布置</div>
          </template>
        </el-empty>
        <div v-else class="hw-list animate-list">
          <div v-for="row in rows" :key="row.id" class="hw-row">
            <div class="hw-row-left">
              <div class="hw-copy">
                <div class="hw-title">{{ row.title }}</div>
                <div class="hw-meta">
                  <span class="hw-meta-item">
                    <el-icon><Clock /></el-icon>{{ row.start_time ? new Date(row.start_time).toLocaleString() : '立即开始' }}
                  </span>
                  <span class="hw-meta-item">
                    截止 {{ row.deadline ? new Date(row.deadline).toLocaleString() : '不限' }}
                  </span>
                  <span class="hw-score">{{ row.total_score }} 分</span>
                  <span class="hw-meta-item">已交 {{ row.submission_count }}</span>
                  <el-tag size="small" :type="{ published: 'success', draft: 'warning', closed: 'info' }[row.status]" effect="light" round>
                    {{ row.status_display }}
                  </el-tag>
                </div>
              </div>
            </div>
            <div class="hw-action-group">
              <button class="hw-action-btn" @click="openSubmissions(row)"><el-icon><View /></el-icon> 批改</button>
              <button v-if="row.status !== 'draft'" class="hw-action-btn" @click="openStats(row)"><el-icon><TrendCharts /></el-icon> 统计</button>
              <button v-if="row.status === 'draft'" class="hw-action-btn success" @click="setStatus(row, 'published')">
                <el-icon><Promotion /></el-icon> 发布
              </button>
              <button v-if="row.status === 'published'" class="hw-action-btn warn" @click="setStatus(row, 'draft')">
                <el-icon><RefreshLeft /></el-icon> 撤回
              </button>
              <button class="hw-action-btn" @click="openEdit(row)"><el-icon><EditPen /></el-icon> 编辑</button>
              <button class="hw-action-btn danger" @click="openDelete(row)"><el-icon><Delete /></el-icon> 删除</button>
            </div>
          </div>
        </div>
      </template>
    </el-card>

    </template>

    <!-- 发布/编辑作业：复用完整讲解的全屏工作台结构 -->
    <Teleport to="body">
    <div v-if="editVisible" class="homework-editor">
      <div class="hw-editor-topbar">
        <div class="hw-editor-title-wrap">
          <span class="hw-editor-icon"><el-icon><Document /></el-icon></span>
          <div class="hw-editor-heading">
            <div class="hw-editor-title-line">
              <div class="hw-editor-title">{{ form.id ? '编辑作业' : '发布作业' }}</div>
              <span class="hw-editor-kicker">{{ editorContext }}</span>
            </div>
            <div class="hw-editor-subtitle">从题库选题，或使用文本 / 附件作业</div>
          </div>
        </div>
        <div class="hw-editor-stats">
          <template v-if="form.mode === 'questions'">
            <span><strong>{{ selectedQuestions.length }}</strong> 道题目</span>
            <span><strong>{{ selectedTotal }}</strong> 总分</span>
          </template>
          <template v-else>
            <span><strong>{{ form.total_score || 0 }}</strong> 总分</span>
            <span>附件型作业</span>
          </template>
          <el-tag :type="form.status === 'published' ? 'success' : 'warning'" effect="light" round>
            {{ form.status === 'published' ? '已发布' : '草稿' }}
          </el-tag>
        </div>
        <div class="hw-editor-actions">
          <el-button v-if="isFrozen" type="warning" plain :loading="saving" @click="withdrawCurrent">撤回修改</el-button>
          <!-- 已发布作业也可保存：标题/说明/时间/附件均不在冻结集，保存按钮始终可用 -->
          <el-button type="primary" :loading="saving" :disabled="uploading" @click="save(false)">{{ form.id ? '保存修改' : '保存作业' }}</el-button>
          <el-button v-if="!isFrozen" class="hw-publish-btn" type="success" plain :loading="saving" :disabled="uploading" @click="save(true)">
            <el-icon><Promotion /></el-icon>{{ form.id ? '保存并发布' : '发布作业' }}
          </el-button>
          <el-button @click="editVisible = false">退出编辑</el-button>
        </div>
      </div>

      <div class="homework-editor-body">
      <el-form :model="form" label-position="top" class="homework-creation-form">
        <div class="creation-form-grid">
          <!-- 左列：基础信息 -->
          <div class="form-col form-col-left">
            <div class="hw-card hw-info-card">
              <div class="hw-card-head"><el-icon><Tickets /></el-icon>基础信息</div>
            <el-form-item label="作业模式">
              <el-radio-group v-model="form.mode" class="homework-mode-switch" :disabled="isFrozen" @change="onModeChange">
                <el-radio-button value="questions">题库选题</el-radio-button>
                <el-radio-button value="attachment">文本 / 附件</el-radio-button>
              </el-radio-group>
              <span v-if="isFrozen" class="freeze-tip">已发布，题目快照已冻结</span>
            </el-form-item>
            <el-form-item label="作业标题"><el-input v-model="form.title" placeholder="请输入作业标题" /></el-form-item>
            <el-form-item label="作业说明" class="hw-desc-item"><el-input v-model="form.description" type="textarea" :rows="5" resize="none" placeholder="请输入作业要求说明" /></el-form-item>
            <el-form-item label="开始时间">
              <el-date-picker
                v-model="form.start_time"
                type="datetime"
                placeholder="不选择则立即开始"
                format="YYYY年MM月DD日 HH:mm"
                value-format="YYYY-MM-DDTHH:mm:ss"
                popper-class="platform-datetime-popper"
                :disabled-date="disabledStartDate"
                :disabled-hours="disabledStartHours"
                :disabled-minutes="disabledStartMinutes"
                :disabled-seconds="disabledStartSeconds"
                @change="validateTimeRange"
                style="width: 100%"
              />
              <div class="time-field-tip">开始时间留空时，作业发布后学生可立即开始作答</div>
            </el-form-item>
            <el-form-item label="截止时间">
              <el-date-picker
                v-model="form.deadline"
                type="datetime"
                placeholder="不选择则截止不限"
                format="YYYY年MM月DD日 HH:mm"
                value-format="YYYY-MM-DDTHH:mm:ss"
                popper-class="platform-datetime-popper"
                :disabled-date="disabledDeadlineDate"
                :disabled-hours="disabledDeadlineHours"
                :disabled-minutes="disabledDeadlineMinutes"
                :disabled-seconds="disabledDeadlineSeconds"
                @change="validateTimeRange"
                style="width: 100%"
              />
              <div class="time-field-tip">截止时间留空时，作业长期开放，不限制提交时间</div>
            </el-form-item>
            <el-form-item v-if="form.mode === 'attachment'" label="满分"><el-input-number v-model="form.total_score" :min="1" :max="200" /></el-form-item>
            </div>
          </div>

          <!-- 右列：题库选题 / 附件 -->
          <div class="form-col form-col-right">
            <div class="hw-card hw-content-card">
              <div class="hw-card-head"><el-icon><EditPen /></el-icon>{{ form.mode === 'attachment' ? '作业附件' : '题目选择' }}</div>
              <div v-if="form.mode === 'attachment'" class="attachment-panel">
                <el-upload
                  ref="homeworkUploadRef"
                  class="attachment-uploader"
                  drag
                  :auto-upload="false"
                  accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip,.rar"
                  :on-change="onHomeworkFile"
                >
                  <el-icon class="attachment-upload-icon"><Document /></el-icon>
                  <div class="attachment-upload-title">拖拽文件到此处，或点击选择</div>
                  <div class="attachment-upload-tip">支持 PDF、Word、PPT、Excel、TXT 与压缩包，最大 20MB；可多选，追加不替换，最多 9 个</div>
                </el-upload>

                <!-- 上传中的任务：文件信息 + 上传进度 + 状态 + 失败重试（选择后立即上传） -->
                <div v-for="task in uploadTasks" :key="task.key" class="upload-file-card" :class="`is-${task.status}`">
                  <div class="upload-file-main">
                    <span class="upload-file-icon"><el-icon><Document /></el-icon></span>
                    <div class="upload-file-info">
                      <div class="upload-file-name" :title="task.name">{{ task.name }}</div>
                      <div class="upload-file-meta">
                        <span>{{ formatFileSize(task.size) }}</span>
                        <span class="upload-file-ext">{{ fileExtOf(task.name) }}</span>
                      </div>
                    </div>
                    <div class="upload-file-status">
                      <span v-if="task.status === 'uploading'" class="upload-status-text is-uploading">上传中 {{ task.progress }}%</span>
                      <template v-else-if="task.status === 'error'">
                        <el-button link type="primary" @click="retryTask(task)">重新上传</el-button>
                        <el-button link type="danger" @click="removeTask(task)">移除</el-button>
                      </template>
                      <el-button v-else link type="danger" @click="removeTask(task)">移除</el-button>
                    </div>
                  </div>
                  <div v-if="task.status === 'uploading'" class="upload-progress-track">
                    <div class="upload-progress-bar" :style="{ width: task.progress + '%' }"></div>
                  </div>
                  <div v-if="task.status === 'error'" class="upload-error-row">
                    <span class="upload-error-text">{{ task.error || '上传失败，请重试' }}</span>
                  </div>
                </div>

                <!-- 已上传附件列表：编辑页直接展示，支持预览 / 移除单个附件 -->
                <div v-if="attachmentList.length" class="uploaded-attachments">
                  <div class="uploaded-attachments-head">
                    <span class="uploaded-attachments-title">已上传附件（{{ attachmentList.length }}）</span>
                    <span class="uploaded-attachments-hint">再次上传为追加，不会替换已有附件</span>
                  </div>
                  <div v-for="(item, index) in attachmentList" :key="item.url" class="uploaded-attachment-item">
                    <span class="upload-file-icon"><el-icon><Document /></el-icon></span>
                    <div class="upload-file-info">
                      <div class="upload-file-name" :title="item.name">{{ item.name || '作业附件' }}</div>
                      <div class="upload-file-meta">
                        <span class="upload-file-ext">{{ fileExtOf(item.name) }}</span>
                        <span v-if="item.size">{{ formatFileSize(item.size) }}</span>
                      </div>
                    </div>
                    <div class="upload-file-status">
                      <el-button v-if="isPdfName(item.name)" link type="primary" @click="togglePreview(item)">
                        <el-icon><View /></el-icon>{{ previewTarget === item.url ? '收起预览' : '预览' }}
                      </el-button>
                      <a class="attachment-view-link" :href="item.url" target="_blank" rel="noopener noreferrer">
                        <el-icon><Download /></el-icon>下载
                      </a>
                      <el-button link type="danger" @click="removeAttachment(index)">移除</el-button>
                    </div>
                  </div>
                  <div class="upload-file-footer">
                    <span>共 {{ attachmentList.length }} 个附件，合计 {{ formatFileSize(attachmentTotalSize) }}（单个上限 20MB，最多 9 个）</span>
                  </div>
                  <!-- PDF 无工具栏连续滚动预览（师生端一致） -->
                  <div v-if="previewTarget" class="attachment-preview-box">
                    <PdfScrollPreview :homework-id="form.id" :url="previewTarget" max-height="480px" />
                  </div>
                </div>
                <el-empty v-if="!attachmentList.length && !uploadTasks.length" :image-size="64" description="尚未上传附件" />
              </div>
              <!-- 左右结构：左列题库筛选选题（已添加行高亮），右列已选题目独立全高列 -->
              <div v-else class="question-builder" :class="{ 'selected-only': isFrozen }">
                <el-alert
                  v-if="isFrozen"
                  type="success"
                  :closable="false"
                  show-icon
                  title="该作业已经发布，以下题目与答案均使用已冻结快照。"
                />
                <div class="question-builder-row">
                  <div v-if="!isFrozen" class="question-pool-panel">
                  <div class="question-filters">
                    <el-select v-model="questionFilters.catalog" clearable placeholder="章节" popper-class="homework-filter-popper">
                      <el-option v-for="item in catalogOptions" :key="item.id" :label="item.label" :value="item.id" />
                    </el-select>
                    <el-select v-model="questionFilters.qtype" clearable placeholder="题型" popper-class="homework-filter-popper">
                      <el-option label="单选题" value="single" /><el-option label="多选题" value="multi" />
                      <el-option label="判断题" value="judge" /><el-option label="填空题" value="blank" />
                      <el-option label="简答题" value="short" />
                    </el-select>
                    <el-select v-model="questionFilters.difficulty" clearable placeholder="难度" popper-class="homework-filter-popper">
                      <el-option label="简单" value="easy" /><el-option label="中等" value="medium" /><el-option label="困难" value="hard" />
                    </el-select>
                    <button
                      class="pool-select-all"
                      :class="{ active: allFilteredSelected }"
                      type="button"
                      :disabled="!filteredQuestionOptions.length"
                      @click="toggleSelectAllFiltered"
                    >
                      {{ allFilteredSelected ? '取消全选' : `全选 ${filteredQuestionOptions.length} 题` }}
                    </button>
                  </div>
                  <el-table
                    :data="filteredQuestionOptions"
                    height="100%"
                    v-loading="questionLoading"
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
                        <button class="pool-action" :class="{ selected: isSelected(row.id) }" type="button" @click="toggleQuestion(row)">
                          {{ isSelected(row.id) ? '移除' : '添加' }}
                        </button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>

                <div class="selected-panel">
                  <div class="selected-header">
                    <strong>已选 {{ selectedQuestions.length }} 题</strong>
                    <span>总分 {{ selectedTotal }} 分</span>
                  </div>
                  <div v-if="!selectedQuestions.length" class="selected-empty">
                    <el-icon><Plus /></el-icon>
                    <span>点击左侧题目的「添加」或「全选」，已选题目会显示在这里</span>
                  </div>
                  <el-scrollbar v-else class="selected-list-scroll">
                    <div class="selected-list">
                      <div v-for="(item, index) in selectedQuestions" :key="item.question" class="selected-item">
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
                          <div v-if="!isFrozen" class="selected-actions">
                            <el-button link circle :icon="ArrowUp" :disabled="index === 0" title="上移" @click="moveQuestion(index, -1)" />
                            <el-button link circle :icon="ArrowDown" :disabled="index === selectedQuestions.length - 1" title="下移" @click="moveQuestion(index, 1)" />
                            <el-button link type="danger" @click="selectedQuestions.splice(index, 1)">删除</el-button>
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
        </div>
      </el-form>
      </div>
    </div>
    </Teleport>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除作业"
      :item-name="deleteTarget?.title"
      description="删除后将无法从当前课程工作区继续访问，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <!-- 提交与批改 -->
    <el-drawer v-model="subVisible" class="grading-drawer" modal-class="grading-drawer-mask" size="64%" :with-header="false">
      <div class="grading-panel">
        <div class="grading-panel-head">
          <div class="grading-heading">
            <div class="grading-kicker">提交批改</div>
            <div class="grading-title">{{ currentHw?.title || '作业批改' }}</div>
            <div class="grading-meta">
              <span>{{ currentHw?.deadline ? new Date(currentHw.deadline).toLocaleString() : '不限截止' }}</span>
              <span>{{ currentHw?.total_score || 0 }} 分</span>
            </div>
          </div>
          <button class="grading-close" type="button" @click="subVisible = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>

        <div class="grading-summary">
          <div class="grading-stat">
            <span>已提交</span>
            <strong>{{ submissions.length }}</strong>
          </div>
          <div class="grading-stat">
            <span>待批改</span>
            <strong>{{ pendingSubmissionCount }}</strong>
          </div>
          <div class="grading-stat">
            <span>平均分</span>
            <strong>{{ averageSubmissionScore }}</strong>
          </div>
        </div>

        <div ref="gradingCardRef" class="grading-table-card">
          <!-- 列宽由 JS 按卡片实际宽度统一分配（见 computeGradingColLayout）：
               早期「学生列弹性(min-width) + 其余固定」在宽屏下学生列 balloon 到 600px+，
               全固定列宽又在窄卡片下横向溢出；现每列均有 [min,max] 区间，总和恒等于卡片宽度 -->
          <el-table :data="submissions" v-loading="subLoading" class="grading-table" height="100%">
            <el-table-column prop="student_name" label="学生" :width="gradingCols.student" show-overflow-tooltip />
            <el-table-column label="提交时间" :width="gradingCols.time" align="center">
              <template #default="{ row }">
                <span class="grading-muted">{{ formatTime(row.submitted_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="逾期" :width="gradingCols.late" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.is_late" type="danger" size="small" effect="light" round>逾期</el-tag>
                <span v-else class="grading-muted">正常</span>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="得分" :width="gradingCols.score" align="center">
              <template #default="{ row }">
                <span :class="row.score == null ? 'grading-muted' : 'grading-score'">{{ submissionScoreLabel(row) }}</span>
              </template>
            </el-table-column>
            <!-- 批改即发布：不再有「已批改未发布」中间状态，成绩列仅展示状态 -->
            <el-table-column label="成绩" :width="gradingCols.grade" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.correct_status === 'returned'" type="success" size="small" effect="light" round>已发布</el-tag>
                <span v-else class="grading-muted">待批改</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" :width="gradingCols.op" align="center">
              <template #default="{ row }">
                <button class="grading-action" type="button" @click="openGrade(row)">
                  查看/批改
                </button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="grading-empty">
                <el-empty :image-size="120" description="还没有学生提交" />
              </div>
            </template>
          </el-table>
        </div>
      </div>
    </el-drawer>

    <!-- 批改弹窗 -->
    <el-dialog v-model="gradeVisible" class="grade-dialog" title="批改作业" width="720px" align-center>
      <div v-if="currentHw?.mode === 'questions'" class="grade-mode-brief">
        <span>共 {{ gradeForm.answerItems.length }} 题</span>
        <span class="grade-brief-split" />
        <span>客观题已自动批改</span>
        <template v-if="pendingManualCount > 0">
          <span class="grade-brief-split" />
          <span class="grade-brief-pending">{{ pendingManualCount }} 道主观题待评分，已自动定位</span>
        </template>
        <span v-else class="grade-brief-done">主观题已全部评分</span>
      </div>
      <div v-if="currentHw?.mode === 'questions'" class="answer-review-list">
        <div
          v-for="(item, index) in gradeForm.answerItems"
          :key="item.id"
          class="answer-review-item"
          :class="{ 'is-pending': item.needs_manual_grading && item.score == null }"
        >
          <div class="answer-review-head">
            <strong>{{ index + 1 }}. {{ item.snapshot.stem }}</strong>
            <span>{{ item.score ?? '待批' }} / {{ item.fullScore }} 分</span>
          </div>
          <QuestionImage :question="item.snapshot" />
          <div class="student-answer">学生答案：{{ formatAnswer(item.student_answer, item.snapshot) || '未作答' }}</div>
          <div class="correct-answer">{{ item.snapshot.qtype === 'short' ? '参考答案' : '正确答案' }}：{{ correctAnswerLabel(item.snapshot) || '（未设置）' }}</div>
          <div v-if="item.snapshot.analysis" class="answer-analysis">解析：{{ item.snapshot.analysis }}</div>
          <div v-if="item.needs_manual_grading" class="manual-grade-row">
            <span class="manual-grade-label">评分</span>
            <el-input-number v-model="item.manualScore" :min="0" :max="item.fullScore" :step="0.5" />
            <el-input v-model="item.comment" placeholder="本题评语（选填）" />
          </div>
          <el-tag v-else :type="item.is_correct ? 'success' : (Number(item.score) > 0 ? 'warning' : 'danger')" size="small">
            {{ item.is_correct ? '自动判定正确' : (Number(item.score) > 0 ? '自动判定：部分正确' : '自动判定错误') }}
          </el-tag>
        </div>
      </div>
      <div v-else class="grade-content">
        <div class="grade-label">学生提交</div>
        <div class="grade-text">{{ gradeForm.content || '（无文本内容）' }}</div>
        <div v-if="gradeForm.attachments.length" class="student-attachments">
          <div class="grade-label">提交的附件（{{ gradeForm.attachments.length }}）</div>
          <div class="student-attachment-list">
            <a
              v-for="(file, fileIndex) in gradeForm.attachments"
              :key="fileIndex"
              class="student-attachment-item"
              :href="file.url"
              target="_blank"
              rel="noopener"
            >
              <el-image
                v-if="isImageFile(file.name)"
                :src="file.url"
                fit="cover"
                class="student-attachment-thumb"
                :preview-src-list="gradeForm.attachments.filter((f) => isImageFile(f.name)).map((f) => f.url)"
              />
              <span v-else class="student-attachment-icon"><el-icon><Document /></el-icon></span>
              <span class="student-attachment-name" :title="file.name">{{ file.name }}</span>
              <span class="student-attachment-size">{{ file.size ? formatFileSize(file.size) : '' }}</span>
            </a>
          </div>
        </div>
      </div>
      <el-form :model="gradeForm" label-width="70px">
        <el-form-item v-if="currentHw?.mode !== 'questions'" label="得分">
          <el-input-number v-model="gradeForm.score" :min="0" :max="Number(currentHw?.total_score) || 100" />
          <span class="total-hint">/ {{ currentHw?.total_score }} 分</span>
        </el-form-item>
        <el-form-item label="评语"><el-input v-model="gradeForm.comment" type="textarea" :rows="3" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="gradeVisible = false">取消</el-button>
          <el-button type="primary" :loading="grading" @click="doGrade()">提交批改</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Delete, EditPen, View, Document, Close, Promotion, Clock, ArrowUp, ArrowDown, Tickets, RefreshLeft, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import PdfScrollPreview from '@/components/PdfScrollPreview.vue'
import QuestionDetailPopover from '@/components/QuestionDetailPopover.vue'
import QuestionImage from '@/components/QuestionImage.vue'
import { uploadWithProgress } from '@/utils/upload'
import { sortedCourseNames } from '@/utils/course-sort'
import { abbrQtype, abbrDifficulty } from '@/utils/question-abbr'
import { blankAnswerText } from '@/utils/blank-answer'
import { listClasses } from '@/api/classroom'
import { listCatalogs } from '@/api/course'
import { listQuestions } from '@/api/question'
import {
  listHomeworks, createHomework, updateHomework, deleteHomework,
  removeHomeworkAttachment,
  listSubmissions, gradeSubmission,
} from '@/api/homework'

const classes = ref([])
const classId = ref(null)
const rows = ref([])
const loading = ref(false)
const route = useRoute()
const router = useRouter()
const fixedCourseId = computed(() => Number(route.params.id) || null)
const activeClassroom = computed(() => classes.value.find((item) => item.id === classId.value))
const editorContext = computed(() => {
  const classroom = activeClassroom.value
  if (!classroom) return '课程作业'
  return `${classroom.name} · ${classCourseNames(classroom)}`
})

function classCourseNames(item) {
  // 多课程名按首字母排序（英文/数字在前、中文按拼音），与班级卡片口径一致
  return sortedCourseNames(item).join('、') || '未关联课程'
}

function activeCourseId() {
  const classroom = activeClassroom.value
  return fixedCourseId.value || classroom?.course || null
}

async function loadClasses() {
  const data = await listClasses(fixedCourseId.value ? { course: fixedCourseId.value } : undefined)
  const list = data.results ?? data
  classes.value = fixedCourseId.value
    ? list.filter((item) => (item.courses || [item.course]).map(Number).includes(fixedCourseId.value))
    : list
  if (classes.value.length) {
    classId.value = classes.value[0].id
    load()
  } else {
    classId.value = null
    rows.value = []
  }
}
async function load() {
  if (!classId.value) return
  loading.value = true
  try {
    const data = await listHomeworks({ classroom: classId.value, course: activeCourseId() })
    rows.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

// ---- 发布/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({})
const originalSchedule = reactive({ start_time: '', deadline: '' })
const isFrozen = computed(() => Boolean(form.id) && form.status !== 'draft')
const selectedQuestions = ref([])
const selectedTotal = computed(() => selectedQuestions.value.reduce((sum, item) => sum + Number(item.score || 0), 0))
// 已上传附件列表：[{name, size, type, url}]（支持多个，再次上传为追加不替换）
const attachmentList = ref([])
// 上传中的任务队列：[{key, raw, name, size, progress, status, error}]（选择文件后立即上传）
const uploadTasks = ref([])
// PDF 滚动预览目标（点击附件行「预览」后展示，师生端同一组件）
const previewTarget = ref('')
const homeworkUploadRef = ref(null)
const uploading = computed(() => uploadTasks.value.some((task) => task.status === 'uploading'))
const attachmentTotalSize = computed(() => attachmentList.value.reduce((sum, item) => sum + Number(item.size || 0), 0))
const HOMEWORK_ATTACHMENT_MAX_COUNT = 9
const HOMEWORK_ATTACHMENT_EXT = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.zip', '.rar']

function formatFileSize(bytes) {
  const size = Number(bytes || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

// 提交时间：精确到秒（如 2026/10/13 12:23:08）；空值回退占位
function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function fileExtOf(name) {
  const parts = String(name || '').split('.')
  return parts.length > 1 ? String(parts.pop()).toUpperCase() : 'FILE'
}
function isImageFile(name) {
  return /\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(String(name || ''))
}
function fileNameFromUrl(url) {
  const raw = String(url || '').split('/').pop()?.split('?')[0] || '附件'
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}
// 上传进度走共享工具 utils/upload.js 的 uploadWithProgress（XHR 原生进度）
const catalogOptions = ref([])
const questionOptions = ref([])
const questionLoading = ref(false)
const questionFilters = reactive({ catalog: null, qtype: '', difficulty: '' })
const filteredQuestionOptions = computed(() => questionOptions.value.filter((item) => {
  if (questionFilters.catalog && Number(item.catalog) !== Number(questionFilters.catalog)) return false
  if (questionFilters.qtype && item.qtype !== questionFilters.qtype) return false
  if (questionFilters.difficulty && item.difficulty !== questionFilters.difficulty) return false
  return true
}))
// 已添加的题目在题库列表中整行高亮
function poolRowClass({ row }) {
  return isSelected(row.id) ? 'is-added' : ''
}
// 题干详情浮层的入参（题库行 / 已选项快照通用）
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
// 当前筛选范围是否已全部选中（按钮在「全选 N 题」/「取消全选」间切换）
const allFilteredSelected = computed(() => {
  const list = filteredQuestionOptions.value
  if (!list.length) return false
  return list.every((item) => isSelected(item.id))
})
function toggleSelectAllFiltered() {
  const list = filteredQuestionOptions.value
  if (!list.length) {
    ElMessage.warning('当前筛选范围内没有题目')
    return
  }
  if (allFilteredSelected.value) {
    // 取消全选：仅移除当前筛选范围内的题目，不影响范围外已选
    const ids = new Set(list.map((item) => Number(item.id)))
    const before = selectedQuestions.value.length
    selectedQuestions.value = selectedQuestions.value.filter((item) => !ids.has(Number(item.question)))
    const removed = before - selectedQuestions.value.length
    if (removed) ElMessage.success(`已取消 ${removed} 题`)
    return
  }
  let added = 0
  list.forEach((item) => {
    if (isSelected(item.id)) return
    selectedQuestions.value.push({
      question: item.id,
      stem: item.stem,
      qtype: item.qtype,
      difficulty: item.difficulty,
      qtype_display: item.qtype_display,
      difficulty_display: item.difficulty_display,
      score: Number(item.score) || 5,
    })
    added += 1
  })
  if (added) ElMessage.success(`已添加 ${added} 题`)
  else ElMessage.info('当前筛选范围的题目均已添加')
}

function flattenCatalogs(items, depth = 0) {
  return (items || []).flatMap((item) => [
    { id: item.id, label: `${'　'.repeat(depth)}${item.title}` },
    ...flattenCatalogs(item.children, depth + 1),
  ])
}

async function loadCatalogOptions() {
  const course = activeCourseId()
  if (!course) return
  const data = await listCatalogs({ course, tree: 1, page_size: 100 })
  catalogOptions.value = flattenCatalogs(data.results ?? data)
}

async function loadQuestionOptions() {
  if (form.mode !== 'questions' || isFrozen.value) return
  questionLoading.value = true
  try {
    const params = { course: activeCourseId(), status: 'published', page_size: 1000 }
    const data = await listQuestions(params)
    questionOptions.value = data.results ?? data
  } finally {
    questionLoading.value = false
  }
}

function parseDateTime(value) {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

function startOfDay(value) {
  const date = new Date(value)
  date.setHours(0, 0, 0, 0)
  return date
}

function range(count) {
  return Array.from({ length: Math.max(0, count) }, (_, index) => index)
}

function minDeadlineDate() {
  return parseDateTime(form.start_time) || new Date()
}

function disabledBeforeDate(date, minDate) {
  const min = startOfDay(minDate)
  const current = new Date(date)
  current.setHours(0, 0, 0, 0)
  return current.getTime() < min.getTime()
}

function selectedMatchesMinDate(value, minDate) {
  const selected = parseDateTime(value)
  return !selected || isSameDay(selected, minDate)
}

function disabledHoursFor(value, minDate) {
  if (!selectedMatchesMinDate(value, minDate)) return []
  return range(minDate.getMinutes() >= 59 ? minDate.getHours() + 1 : minDate.getHours())
}

function disabledMinutesFor(value, minDate, hour) {
  if (!selectedMatchesMinDate(value, minDate) || hour !== minDate.getHours()) return []
  return range(minDate.getMinutes() + 1)
}

function disabledSecondsFor(value, minDate, hour, minute) {
  if (!selectedMatchesMinDate(value, minDate) || hour !== minDate.getHours() || minute !== minDate.getMinutes()) return []
  return range(minDate.getSeconds() + 1)
}

function disabledStartDate(date) {
  return disabledBeforeDate(date, new Date())
}

function disabledStartHours() {
  return disabledHoursFor(form.start_time, new Date())
}

function disabledStartMinutes(hour) {
  return disabledMinutesFor(form.start_time, new Date(), hour)
}

function disabledStartSeconds(hour, minute) {
  return disabledSecondsFor(form.start_time, new Date(), hour, minute)
}

function disabledDeadlineDate(date) {
  return disabledBeforeDate(date, minDeadlineDate())
}

function disabledDeadlineHours() {
  return disabledHoursFor(form.deadline, minDeadlineDate())
}

function disabledDeadlineMinutes(hour) {
  return disabledMinutesFor(form.deadline, minDeadlineDate(), hour)
}

function disabledDeadlineSeconds(hour, minute) {
  return disabledSecondsFor(form.deadline, minDeadlineDate(), hour, minute)
}

function validateTimeRange() {
  const start = parseDateTime(form.start_time)
  const deadline = parseDateTime(form.deadline)
  const now = Date.now()
  const startChanged = form.start_time !== originalSchedule.start_time
  const deadlineChanged = form.deadline !== originalSchedule.deadline
  if (start && start.getTime() < now && startChanged) {
    form.start_time = ''
    ElMessage.warning('开始时间不能早于当前时间')
    return false
  }
  if (deadline && deadline.getTime() < now && deadlineChanged) {
    form.deadline = ''
    ElMessage.warning('截止时间不能早于当前时间')
    return false
  }
  if (start && deadline && deadline.getTime() <= start.getTime()) {
    form.deadline = ''
    ElMessage.warning('截止时间必须晚于开始时间')
    return false
  }
  return true
}

function onModeChange(mode) {
  if (mode === 'questions') {
    // 切到题库模式：清理待上传任务与预览（已上传附件仍留在作业记录上）
    uploadTasks.value = []
    previewTarget.value = ''
    homeworkUploadRef.value?.clearFiles()
    loadCatalogOptions()
    loadQuestionOptions()
  }
}

function isSelected(id) {
  return selectedQuestions.value.some((item) => Number(item.question) === Number(id))
}

function toggleQuestion(question) {
  const index = selectedQuestions.value.findIndex((item) => Number(item.question) === Number(question.id))
  if (index >= 0) selectedQuestions.value.splice(index, 1)
  else selectedQuestions.value.push({
    question: question.id,
    stem: question.stem,
    qtype: question.qtype,
    difficulty: question.difficulty,
    qtype_display: question.qtype_display,
    difficulty_display: question.difficulty_display,
    options: Array.isArray(question.options) ? question.options : [],
    answer: question.answer ?? '',
    analysis: question.analysis || '',
    score: Number(question.score) || 5,
  })
}

function moveQuestion(index, offset) {
  const target = index + offset
  if (target < 0 || target >= selectedQuestions.value.length) return
  const [item] = selectedQuestions.value.splice(index, 1)
  selectedQuestions.value.splice(target, 0, item)
}

function isPdfName(name) {
  return String(name || '').toLowerCase().endsWith('.pdf')
}

function onHomeworkFile(file) {
  const raw = file?.raw
  if (!raw) return
  const name = String(raw.name || '')
  if (!HOMEWORK_ATTACHMENT_EXT.some((ext) => name.toLowerCase().endsWith(ext))) {
    homeworkUploadRef.value?.clearFiles()
    ElMessage.warning('不支持该文件格式，请上传 PDF、Office 文档、TXT 或压缩包')
    return
  }
  if (Number(raw.size || 0) > 20 * 1024 * 1024) {
    homeworkUploadRef.value?.clearFiles()
    ElMessage.warning('附件大小不能超过 20MB')
    return
  }
  if (attachmentList.value.length + uploadTasks.value.length >= HOMEWORK_ATTACHMENT_MAX_COUNT) {
    homeworkUploadRef.value?.clearFiles()
    ElMessage.warning(`作业附件最多 ${HOMEWORK_ATTACHMENT_MAX_COUNT} 个`)
    return
  }
  // 重置上传组件内部列表（不使用 :limit，否则再次选择会被 on-exceed 拦截）
  homeworkUploadRef.value?.clearFiles()
  // reactive 任务：status/progress 变更才能触发重渲染；raw 文件对象 markRaw 防代理破坏 FormData
  const task = reactive({
    key: `t${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    raw: markRaw(raw),
    name,
    size: Number(raw.size || 0),
    progress: 0,
    status: 'pending',
    error: '',
  })
  uploadTasks.value.push(task)
  // 选择即上传：不再等待点击保存/发布；多文件各自入队并行上传
  uploadTask(task)
}

// 立即上传任务队列中的附件；新作业先自动创建草稿作为上传目标
async function uploadTask(task) {
  if (!task || task.status === 'uploading') return
  if (!form.id) {
    if (!form.title?.trim()) {
      task.status = 'error'
      task.error = '请先填写作业标题，再上传附件'
      return
    }
    if (!validateTimeRange()) {
      task.status = 'error'
      task.error = '请先校正作业时间，再上传附件'
      return
    }
    try {
      await createDraftForAttachment()
    } catch (error) {
      task.status = 'error'
      task.error = error?.message || '作业草稿创建失败，请稍后重试'
      return
    }
  }
  task.status = 'uploading'
  task.progress = 0
  task.error = ''
  try {
    const body = new FormData()
    body.append('attachments', task.raw)
    const payload = await uploadWithProgress(
      'POST',
      `/api/homeworks/${form.id}/attachments/`,
      body,
      (percent) => { task.progress = percent },
    )
    const added = payload?.data?.added || []
    // 上传成功：附件进入「已上传附件」列表（追加不替换），同时移除任务卡片
    added.forEach((item) => attachmentList.value.push(item))
    uploadTasks.value = uploadTasks.value.filter((item) => item.key !== task.key)
    if (previewTarget.value && !attachmentList.value.some((item) => item.url === previewTarget.value)) {
      previewTarget.value = ''
    }
    ElMessage.success(`附件「${task.name}」上传成功`)
  } catch (error) {
    // 上传失败：保留任务卡片，展示失败状态并提供重试
    task.status = 'error'
    task.error = error?.message || '上传失败，请重试'
  }
}

let draftCreating = null
// 新作业上传附件前，先以当前表单信息创建草稿作业（附件必须挂到已存在的作业上）
function createDraftForAttachment() {
  if (form.id) return Promise.resolve()
  if (!draftCreating) {
    const courseId = activeCourseId()
    if (!courseId) return Promise.reject(new Error('该班级尚未关联课程'))
    // 多附件并行上传时共享同一次草稿创建，避免重复建单
    draftCreating = createHomework({
      title: form.title.trim(),
      description: form.description || '',
      start_time: form.start_time || null,
      deadline: form.deadline || null,
      course: courseId,
      classroom: classId.value,
      mode: 'attachment',
      total_score: form.total_score || 100,
      status: 'draft',
    }).then((created) => {
      if (!created?.id) throw new Error('作业草稿创建失败')
      form.id = created.id
      form.status = created.status || 'draft'
    }).finally(() => { draftCreating = null })
  }
  return draftCreating
}

function removeTask(task) {
  uploadTasks.value = uploadTasks.value.filter((item) => item.key !== task.key)
  homeworkUploadRef.value?.clearFiles()
}

function retryTask(task) {
  task.status = 'pending'
  task.progress = 0
  task.error = ''
  uploadTask(task)
}

function togglePreview(item) {
  previewTarget.value = previewTarget.value === item.url ? '' : item.url
}

async function removeAttachment(index) {
  const item = attachmentList.value[index]
  if (!item) return
  try {
    await ElMessageBox.confirm('移除后需重新上传，确定移除该附件吗？', '移除附件', {
      type: 'warning',
      confirmButtonText: '移除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await removeHomeworkAttachment(form.id, item.url)
    attachmentList.value.splice(index, 1)
    if (previewTarget.value === item.url) previewTarget.value = ''
    ElMessage.success('附件已移除')
  } catch {
    // 错误信息由请求拦截器统一提示
  }
}

function openEdit(row) {
  originalSchedule.start_time = row?.start_time || ''
  originalSchedule.deadline = row?.deadline || ''
  Object.assign(form, {
    id: row?.id || null,
    title: row?.title || '',
    description: row?.description || '',
    start_time: row?.start_time || '',
    deadline: row?.deadline || '',
    total_score: Number(row?.total_score) || 100,
    mode: row?.mode || 'questions',
    status: row?.status || 'draft',
  })
  // 已上传附件：后端序列化直接返回原文件名（存储文件名为 uuid，不再回填导致显示异常）
  attachmentList.value = (row?.attachments || []).map((item) => ({ ...item }))
  uploadTasks.value = []
  previewTarget.value = ''
  homeworkUploadRef.value?.clearFiles()
  selectedQuestions.value = (row?.questions || []).map((item) => ({
    question: item.question,
    stem: item.snapshot?.stem || '题目快照',
    qtype: item.snapshot?.qtype || '',
    difficulty: item.snapshot?.difficulty || '',
    qtype_display: item.snapshot?.qtype_display || item.snapshot?.qtype || '',
    difficulty_display: item.snapshot?.difficulty_display || '',
    options: Array.isArray(item.snapshot?.options) ? item.snapshot.options : [],
    answer: item.snapshot?.answer ?? '',
    analysis: item.snapshot?.analysis || '',
    score: Number(item.score),
  }))
  questionFilters.catalog = null
  questionFilters.qtype = ''
  questionFilters.difficulty = ''
  editVisible.value = true
  if ((row?.mode || 'questions') === 'questions') {
    loadCatalogOptions()
    loadQuestionOptions()
  }
}
async function save(publish = false) {
  if (!form.title?.trim()) return ElMessage.warning('请填写标题')
  const courseId = activeCourseId()
  if (!courseId) return ElMessage.warning('该班级尚未关联课程')
  if (!validateTimeRange()) return
  // 附件为即时上传：保存前不能有上传中/待上传的任务，避免静默丢弃附件
  if (uploading.value) return ElMessage.warning('附件正在上传中，请稍候再保存')
  if (uploadTasks.value.length) return ElMessage.warning('还有附件未上传完成，请等待上传成功或先移除该文件')
  const willPublish = publish || form.status === 'published'
  if (form.mode === 'questions' && willPublish && !selectedQuestions.value.length) {
    return ElMessage.warning('发布题库作业前请至少选择一道题')
  }
  let payload = {
    title: form.title.trim(), description: form.description, start_time: form.start_time || null, deadline: form.deadline || null,
    status: publish ? 'published' : form.status,
  }
  if (!isFrozen.value) {
    payload = { ...payload, course: courseId, classroom: classId.value, mode: form.mode }
    if (form.mode === 'questions') {
      payload.question_items = selectedQuestions.value.map((item) => ({ question: item.question, score: item.score }))
    } else {
      payload.total_score = form.total_score
    }
  }
  saving.value = true
  try {
    if (form.id) {
      await updateHomework(form.id, payload)
    } else {
      await createHomework(payload)
    }
    ElMessage.success(publish ? '已发布' : (form.id ? '已更新' : '已保存'))
    editVisible.value = false
    load()
  } catch {
    // 错误信息由请求拦截器统一提示
  } finally {
    saving.value = false
  }
}
async function setStatus(row, status) {
  await updateHomework(row.id, { status })
  ElMessage.success(status === 'published' ? '已发布' : '已撤回，可继续修改')
  load()
}

// 打开作业统计页（课程空间内走课程内嵌路由，保留课程导航）
function openStats(row) {
  router.push(
    fixedCourseId.value
      ? `/teacher/courses/${fixedCourseId.value}/homework/${row.id}/stats`
      : `/teacher/homework/${row.id}/stats`,
  )
}

async function withdrawCurrent() {
  if (!form.id) return
  saving.value = true
  try {
    await updateHomework(form.id, { status: 'draft' })
    form.status = 'draft'
    ElMessage.success('已撤回，可继续修改')
    if (form.mode === 'questions') {
      await loadCatalogOptions()
      await loadQuestionOptions()
    }
    load()
  } finally {
    saving.value = false
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
    await deleteHomework(deleteTarget.value.id)
    ElMessage.success('作业已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    load()
  } finally {
    deleting.value = false
  }
}

// ---- 提交与批改 ----
const subVisible = ref(false)
const subLoading = ref(false)
const submissions = ref([])
const currentHw = ref(null)
const gradedSubmissions = computed(() => submissions.value.filter((row) => row.score !== null && row.score !== undefined && row.score !== ''))
const pendingSubmissionCount = computed(() => Math.max(submissions.value.length - gradedSubmissions.value.length, 0))
const averageSubmissionScore = computed(() => {
  if (!gradedSubmissions.value.length) return '--'
  const total = gradedSubmissions.value.reduce((sum, row) => sum + Number(row.score || 0), 0)
  return (total / gradedSubmissions.value.length).toFixed(1)
})
async function openSubmissions(row) {
  currentHw.value = row
  subVisible.value = true
  subLoading.value = true
  try {
    const data = await listSubmissions({ homework: row.id })
    submissions.value = data.results ?? data
  } finally {
    subLoading.value = false
  }
  await nextTick()
  syncGradingCardWidth()
}

// ---- 批改抽屉表格列宽：按卡片实际宽度分配，保证占满且各列均衡 ----
// el-table 只认两种列宽：数字 width（固定）或无 width（弹性列按 min-width 比例吸收全部剩余宽度）。
// 「单弹性列」在宽屏抽屉下会 balloon（学生列曾到 600px+，用户反馈某列过宽）；
// 「全固定列宽」总和超出卡片即横向溢出、不足则右侧留白。故量出卡片宽度后统一分配：
// 每列有 [min, max] 区间与目标占比，先按占比取整并钳制，余量/亏量按列轮流 ±1px 微调，总和恒等于卡片宽度。
// 注意：el-drawer 内容懒渲染，onMounted 时模板 ref 为 null，必须在抽屉打开/数据到位后主动量
// （syncGradingCardWidth）；ResizeObserver 在 ref 就绪后懒加载建立，仅负责视口缩放时的重算。
// 列宽实测基准（headless Chrome，正文 14px/600，cell padding 8px）：
//   学生姓名 2-4 字 ≈ 28-56px（该列 show-overflow-tooltip，EP 注入 white-space:nowrap，超长省略号不换行）；
//   时间「2026/10/13 14:30:22」≈ 146px；得分「客观 5 分」≈ 59px；
//   逾期/成绩标签 ≈ 40-55px；操作按钮「查看/批改」≈ 82px（含 padding/border）。
// 各列下限 = 内容实测宽 + 16px 内边距 + 安全余量；上限抑制宽屏膨胀（学生列上限 150——
//   用户反馈「学生列空了这么多」，宽屏下剩余宽度应优先给时间/操作列）。
// 实测：1440（卡片 624）→ [94,176,70,84,81,119]；1920（卡片 764）→ 时间列到 212 上限，全部单行。
const GRADING_COL_LAYOUT = [
  { key: 'student', min: 84, max: 150, share: 0.16 }, // 学生（姓名，超长省略 + tooltip，不会换行）
  { key: 'time', min: 176, max: 212, share: 0.27 },   // 提交时间（YYYY/M/D H:mm:ss 单行不换行）
  { key: 'late', min: 70, max: 92, share: 0.10 },     // 逾期（标签/正常）
  { key: 'score', min: 84, max: 100, share: 0.13 },   // 得分（客观 N 分/未批/数字）
  { key: 'grade', min: 78, max: 112, share: 0.14 },   // 成绩（待批改/已发布标签）
  { key: 'op', min: 104, max: 128, share: 0.20 },     // 操作（查看/批改按钮，white-space: nowrap）
]
const GRADING_COL_FALLBACK_W = 700
function computeGradingColLayout(total) {
  const width = total > 200 ? total : GRADING_COL_FALLBACK_W
  const cols = GRADING_COL_LAYOUT.map((col) => ({
    ...col,
    w: Math.min(col.max, Math.max(col.min, Math.round(width * col.share))),
  }))
  // 余量（width > Σw）按未达上限的列轮流 +1；亏量按未触下限的列轮流 -1，直至严格等于 width
  let diff = width - cols.reduce((sum, col) => sum + col.w, 0)
  let guard = 0
  while (diff !== 0 && guard < 4000) {
    const grow = diff > 0
    const pool = cols.filter((col) => (grow ? col.w < col.max : col.w > col.min))
    if (!pool.length) break
    const col = pool[guard % pool.length]
    col.w += grow ? 1 : -1
    diff += grow ? -1 : 1
    guard += 1
  }
  return cols
}
const gradingCardRef = ref(null)
const gradingCardW = ref(0)
const gradingCols = computed(() => {
  const cols = computeGradingColLayout(gradingCardW.value)
  return { student: cols[0].w, time: cols[1].w, late: cols[2].w, score: cols[3].w, grade: cols[4].w, op: cols[5].w }
})
// 主动量一次卡片宽度：抽屉打开/数据渲染完成/视口变化时调用。
// 不能只依赖 onMounted 里的 ResizeObserver——抽屉内容在部分场景下 ref 挂载时机不可靠。
function syncGradingCardWidth() {
  const el = gradingCardRef.value
  if (!el) return
  const w = Math.round(el.clientWidth)
  if (w > 0 && w !== gradingCardW.value) gradingCardW.value = w
  ensureGradingRO()
}
let gradingCardRO = null
function ensureGradingRO() {
  if (gradingCardRO || typeof ResizeObserver === 'undefined' || !gradingCardRef.value) return
  gradingCardRO = new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width)
    if (w > 0 && w !== gradingCardW.value) gradingCardW.value = w
  })
  gradingCardRO.observe(gradingCardRef.value)
}
onMounted(() => {
  syncGradingCardWidth()
})
onBeforeUnmount(() => {
  if (gradingCardRO) {
    gradingCardRO.disconnect()
    gradingCardRO = null
  }
})
watch(subVisible, (visible) => {
  if (visible) nextTick(syncGradingCardWidth)
})

const gradeVisible = ref(false)
const grading = ref(false)
const gradeForm = reactive({ id: null, content: '', score: 0, comment: '', attachments: [], answerItems: [] })
// 待评分主观题数量：批改弹窗摘要与「定位」提示共用
const pendingManualCount = computed(() => gradeForm.answerItems.filter((item) => item.needs_manual_grading && item.score == null).length)
// 得分列：未批改的混合作业只出了客观题分，标注「客观 X 分」避免误读为最终成绩
function submissionScoreLabel(row) {
  if (row.score == null) return '未批'
  if (row.correct_status === 'submitted') return `客观 ${row.score} 分`
  return String(row.score)
}
function openGrade(row) {
  Object.assign(gradeForm, {
    id: row.id,
    content: row.content,
    score: Number(row.score) || 0,
    comment: row.comment || '',
    attachments: [
      ...(row.attachment ? [{ name: fileNameFromUrl(row.attachment), url: row.attachment, size: 0 }] : []),
      ...(row.attachments || []),
    ],
    answerItems: (row.answer_items || []).map((item) => ({
      ...item,
      fullScore: Number(currentHw.value?.questions?.find((q) => q.id === item.homework_question)?.score || 0),
      manualScore: item.score == null ? 0 : Number(item.score),
      comment: item.comment || '',
    })),
  })
  gradeVisible.value = true
  // 题目回顾列表较长时可滚动：打开后自动定位到第一道待评分主观题，
  // 避免评分行藏在折叠线下方被漏看（历史反馈：看不到简答题批改选项）
  nextTick(() => {
    setTimeout(() => {
      const first = document.querySelector('.grade-dialog .answer-review-item.is-pending .manual-grade-row')
      if (first) first.scrollIntoView({ block: 'center' })
    }, 60)
  })
}
function formatAnswer(answer, snapshot) {
  if (!answer) return ''
  const options = snapshot?.options || []
  // 选择题：选项字母附带选项内容，避免只显示 A/B/C/D 造成困惑（与正确答案展示一致）
  const label = (key) => {
    const opt = options.find((o) => o.key === key)
    return opt ? `${key}. ${opt.text}` : String(key)
  }
  if (answer.key != null && String(answer.key) !== '') return label(answer.key)
  if (Array.isArray(answer.keys)) return answer.keys.length ? answer.keys.map(label).join('、') : ''
  if (Array.isArray(answer.blanks)) {
    const filled = answer.blanks.map((b) => String(b ?? '').trim()).filter((b) => b !== '')
    return filled.length ? filled.join('；') : ''
  }
  if (answer.text != null && String(answer.text).trim() !== '') return String(answer.text)
  return ''
}
// 正确答案展示：附带选项内容，避免只显示 A/B/C/D 字母
function correctAnswerLabel(snapshot) {
  const answer = snapshot?.answer || {}
  const options = snapshot?.options || []
  const label = (key) => {
    const opt = options.find((o) => o.key === key)
    return opt ? `${key}. ${opt.text}` : String(key)
  }
  if (answer.key != null && String(answer.key) !== '') return label(answer.key)
  if (answer.keys?.length) return answer.keys.map(label).join('、')
  if (answer.blanks?.length) return blankAnswerText(answer)
  if (answer.text != null && String(answer.text).trim()) return String(answer.text)
  return ''
}
async function doGrade() {
  // 主观题评分前端校验：空值/非数字/越界直接拦截并提示题号，
  // 避免把脏数据发给后端换回一句难懂的 400（分数框被清空是常见操作）
  if (currentHw.value?.mode === 'questions') {
    for (let index = 0; index < gradeForm.answerItems.length; index++) {
      const item = gradeForm.answerItems[index]
      if (!item.needs_manual_grading) continue
      const raw = item.manualScore
      const num = raw === null || raw === undefined || String(raw).trim() === '' ? NaN : Number(raw)
      if (!Number.isFinite(num)) {
        ElMessage.warning(`第 ${index + 1} 题（${abbrQtype(item.snapshot)}）请填写 0 ~ ${item.fullScore} 的有效分数`)
        return
      }
      if (num < 0 || num > Number(item.fullScore || 0)) {
        ElMessage.warning(`第 ${index + 1} 题评分必须在 0 ~ ${item.fullScore} 分之间`)
        return
      }
    }
  }
  grading.value = true
  try {
    const payload = { score: gradeForm.score, comment: gradeForm.comment }
    if (currentHw.value?.mode === 'questions') {
      payload.answer_scores = Object.fromEntries(
        gradeForm.answerItems
          .filter((item) => item.needs_manual_grading)
          .map((item) => [item.id, { score: item.manualScore, comment: item.comment }]),
      )
    }
    // 批改即发布：后端 grade() 直接置 RETURNED，无「已批改未发布」中间状态
    await gradeSubmission(gradeForm.id, payload)
    ElMessage.success('批改完成，成绩已发布')
    gradeVisible.value = false
    openSubmissions(currentHw.value)
  } finally {
    grading.value = false
  }
}

onMounted(loadClasses)
</script>

<style scoped>
.homework-page :deep(.data-card) { padding: 0; }
.homework-page :deep(.data-card > .el-card__body) { padding: 0; }
.module-toolbar {
  margin: 0 0 12px;
  padding: 0 0 12px;
  border-bottom: 0;
}
.module-primary-button {
  height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  box-shadow: 0 11px 22px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.module-table {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-row-hover-bg-color: transparent;
  background: transparent;
}
.module-table :deep(.el-table__inner-wrapper::before) { display: none; }
.module-table :deep(th.el-table__cell) {
  padding: 0 14px 10px;
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
  background: transparent;
}
.module-table :deep(td.el-table__cell) {
  padding: 17px 14px;
  border-bottom: 10px solid transparent;
  color: #334155;
  background: rgba(255, 255, 255, 0.8);
}
.module-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: #fff; }
.module-table :deep(.el-table__body tr > td.el-table__cell:first-child) { border-top-left-radius: 15px; border-bottom-left-radius: 15px; }
.module-table :deep(.el-table__body tr > td.el-table__cell:last-child) { border-top-right-radius: 15px; border-bottom-right-radius: 15px; }

/* 作业卡片行（与题库列表一致） */
.hw-empty-text { color: var(--gray-700, #334155); font-size: 15px; font-weight: 700; }
.hw-empty-tip { margin-top: 4px; color: var(--gray-400, #94a3b8); font-size: 13px; }
.hw-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hw-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid var(--gray-100, #e5e9f0);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.hw-row:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}
.hw-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.hw-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.hw-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gray-900, #0f172a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.hw-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.hw-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
}
.hw-score {
  color: var(--gray-500, #64748b);
  font-size: 12.5px;
  font-weight: 700;
}
.hw-action-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}
.hw-action-btn {
  height: 32px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-600, #2563eb);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.hw-action-btn:hover {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.hw-action-btn.success { color: var(--success, #16a34a); }
.hw-action-btn.warn { color: #d97706; }
.hw-action-btn.danger { color: var(--danger, #dc2626); }

@media (max-width: 768px) {
  .hw-row { flex-direction: column; align-items: stretch; gap: 12px; }
  .hw-action-group { justify-content: space-between; }
}

.homework-form-dialog :deep(.el-dialog),
:global(.homework-form-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}
.homework-form-dialog :deep(.el-dialog__header),
:global(.homework-form-dialog.el-dialog .el-dialog__header),
.homework-form-dialog :deep(.el-dialog__footer),
:global(.homework-form-dialog.el-dialog .el-dialog__footer) {
  margin: 0;
  padding: 0;
}
.homework-form-dialog :deep(.el-dialog__body),
:global(.homework-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}
.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 82px;
  padding: 18px 22px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
.creation-dialog-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  place-items: center;
  border-radius: 15px;
  font-size: 21px;
}
.homework-create-icon {
  color: #2563eb;
  background: #eaf2ff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.creation-dialog-heading { min-width: 0; }
.creation-dialog-title {
  color: #14213d;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.25;
}
.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
}
.creation-dialog-close {
  width: 32px;
  height: 32px;
  margin-left: auto;
  color: #94a3b8;
}
.creation-dialog-close:hover {
  color: #2563eb;
  background: #eff6ff;
}
.homework-creation-form { padding: 20px 24px 22px; }
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
.hw-card {
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
.hw-info-card {
  overflow: auto;
}
/* 左卡（基础信息）表单项间距收紧 */
.hw-info-card :deep(.el-form-item) {
  margin-bottom: 12px;
}
.hw-content-card {
  overflow: hidden;
}
.hw-card-head {
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
.hw-card-head :deep(.el-icon) {
  color: #2563eb;
  font-size: 15px;
}
.hw-card :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

/* 发布作业：占满内容区的编辑视图 */
.homework-editor {
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
.homework-editor,
.homework-editor * {
  scrollbar-width: none;
}
.homework-editor::-webkit-scrollbar,
.homework-editor *::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}
.hw-editor-topbar {
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
.hw-editor-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.hw-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 16px 0 12px;
  border: 1px solid rgba(37, 99, 235, 0.16);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  color: #2563eb;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}
.hw-back-btn:hover {
  background: #eff6ff;
  border-color: rgba(37, 99, 235, 0.4);
}
.hw-editor-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.9);
  font-size: 16px;
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.18),
    0 4px 10px rgba(37, 99, 235, 0.06);
}
.hw-editor-heading { min-width: 0; }
.hw-editor-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.hw-editor-kicker {
  max-width: 34vw;
  overflow: hidden;
  padding: 3px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #64748b;
  background: rgba(248, 251, 255, 0.9);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hw-editor-title {
  color: #0f172a;
  font-size: 21px;
  font-weight: 800;
  line-height: 1.2;
  white-space: nowrap;
}
.hw-editor-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 12px;
}
.hw-editor-actions {
  display: flex;
  gap: 8px;
}
.hw-editor-actions :deep(.el-button) {
  min-width: 96px;
  height: 38px;
  padding: 0 18px;
  border-radius: 11px;
  font-weight: 700;
}
.hw-editor-actions :deep(.el-button--primary) {
  border-color: #3b82f6;
  background: #3b82f6;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.2);
}
.homework-editor .homework-creation-form {
  height: 100%;
  min-height: 0;
  padding: 0;
}
.homework-editor-body {
  min-width: 0;
  min-height: 0;
  padding: 12px 14px 14px;
  overflow: hidden;
}
.hw-editor-stats {
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
.hw-editor-stats strong {
  color: #2563eb;
  font-size: 16px;
}

.homework-creation-form :deep(.el-form-item) { margin-bottom: 18px; }
.homework-creation-form :deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 8px;
  color: #475569;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
}
.homework-mode-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  width: 100%;
  max-width: 248px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.homework-mode-switch :deep(.el-radio-button) {
  min-width: 0;
  --el-radio-button-checked-bg-color: transparent;
  --el-radio-button-checked-border-color: transparent;
  --el-radio-button-checked-text-color: inherit;
}
.homework-mode-switch :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid #dbe5f2 !important;
  border-left: 0 !important;
  border-radius: 10px !important;
  background: #f8fbff !important;
  box-shadow: none !important;
  color: #64748b;
  font-size: 13px;
  font-weight: 750;
  line-height: 1;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}
.homework-mode-switch :deep(.el-radio-button__inner:hover) {
  border-color: #bfdbfe !important;
  background: #eff6ff !important;
  color: var(--el-color-primary);
}
.homework-mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: transparent !important;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
  color: #fff;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.22) !important;
}
.homework-mode-switch :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner:hover) {
  color: #fff;
}
.homework-mode-switch :deep(.el-radio-button__original-radio:disabled + .el-radio-button__inner) {
  cursor: not-allowed;
  opacity: 0.58;
}
.homework-creation-form :deep(.el-input__wrapper),
.homework-creation-form :deep(.el-date-editor.el-input),
.homework-creation-form :deep(.el-input-number) {
  min-height: 48px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: none;
}
.homework-creation-form :deep(.el-input__wrapper:focus-within),
.homework-creation-form :deep(.el-date-editor.el-input:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.homework-creation-form :deep(.el-input-number) { width: 100%; }
.homework-creation-form :deep(.el-textarea__inner) {
  min-height: 150px !important;
  padding: 12px 14px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: none;
  line-height: 1.65;
}
.homework-creation-form :deep(.el-textarea__inner:focus) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: rgba(248, 250, 252, 0.82);
}
.creation-dialog-footer :deep(.el-button) {
  min-width: 88px;
  height: 38px;
  border-radius: 10px;
  font-weight: 700;
}
:global(.platform-datetime-popper.el-popper) {
  z-index: 3200 !important;
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.48) !important;
  border-radius: 18px !important;
  background: #fff !important;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.18), 0 0 0 6px rgba(219, 234, 254, 0.16) !important;
}
:global(.el-message) {
  z-index: 5200 !important;
}
:global(.homework-filter-popper.el-popper) {
  z-index: 5200 !important;
  overflow: hidden;
  border: 1px solid #bfdbfe !important;
  border-radius: 18px !important;
  background: rgba(255, 255, 255, 0.98) !important;
  box-shadow: 0 20px 44px rgba(37, 99, 235, 0.16), 0 0 0 5px rgba(219, 234, 254, 0.28) !important;
}
:global(.homework-filter-popper .el-popper__arrow) {
  display: none;
}
:global(.homework-filter-popper .el-select-dropdown) {
  border: 0;
  border-radius: 18px;
  background: transparent;
  box-shadow: none;
}
:global(.homework-filter-popper .el-select-dropdown__wrap) {
  max-height: 360px;
}
:global(.homework-filter-popper .el-select-dropdown__list) {
  padding: 14px 0;
}
:global(.homework-filter-popper .el-select-dropdown__item) {
  height: 52px;
  padding: 0 28px;
  color: #334155;
  font-size: 16px;
  font-weight: 800;
  line-height: 52px;
}
:global(.homework-filter-popper .el-select-dropdown__item.is-hovering),
:global(.homework-filter-popper .el-select-dropdown__item:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.homework-filter-popper .el-select-dropdown__item.is-selected) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-picker-panel) {
  border: 0;
  border-radius: 18px;
  color: #334155;
  background: #fff;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker) {
  width: 560px;
}
:global(.platform-datetime-popper .el-date-picker__time-header) {
  gap: 10px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(115deg, #ffffff 0%, #f6faff 100%);
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input:first-child) {
  width: 214px;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input:last-child) {
  width: 150px;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper) {
  min-height: 36px;
  border: 1px solid #dbe5f2;
  border-radius: 10px;
  background: #f8fbff;
  box-shadow: none;
}
:global(.platform-datetime-popper .el-date-picker__time-header .el-input__wrapper:focus-within) {
  border-color: #60a5fa;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.13);
}
:global(.platform-datetime-popper .el-date-picker__header) {
  width: 320px;
  margin: 14px 18px 8px;
}
:global(.platform-datetime-popper .el-date-picker__header-label) {
  color: #334155;
  font-size: 15px;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn) {
  width: 28px;
  height: 28px;
  margin: 0 1px;
  border-radius: 8px;
  color: #64748b;
}
:global(.platform-datetime-popper .el-picker-panel__icon-btn:hover) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table th) {
  border-bottom: 0;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-picker-panel__content) {
  width: 320px;
  margin: 12px 218px 12px 18px;
}
:global(.platform-datetime-popper .el-date-table td .el-date-table-cell) {
  width: 34px;
  height: 34px;
  margin: 1px auto;
  border-radius: 10px;
}
:global(.platform-datetime-popper .el-date-table td.available:hover .el-date-table-cell) {
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-date-table td.available:hover span),
:global(.platform-datetime-popper .el-date-table td.today span) {
  color: #2563eb;
  font-weight: 750;
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) .el-date-table-cell) {
  background: linear-gradient(135deg, #60a5fa, #2563eb);
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.24);
}
:global(.platform-datetime-popper .el-date-table td.current:not(.disabled) span) {
  color: #fff;
}
:global(.platform-datetime-popper .el-picker-panel__footer) {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px 12px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button) {
  min-width: 64px;
  height: 34px;
  border-radius: 9px;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button:first-child),
:global(.platform-datetime-popper .el-picker-panel__footer .el-picker-panel__link-btn:first-child) {
  display: none !important;
}
:global(.platform-datetime-popper .el-picker-panel__footer .el-button--primary) {
  border-color: #3b82f6;
  color: #fff;
  background: #3b82f6;
}
:global(.platform-datetime-popper .el-time-panel) {
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
:global(.platform-datetime-popper .el-time-panel::before) {
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
:global(.platform-datetime-popper .el-time-panel__content) {
  height: 194px;
}
:global(.platform-datetime-popper .el-time-panel__content::before),
:global(.platform-datetime-popper .el-time-panel__content::after) {
  border-color: #e5edf7;
}
:global(.platform-datetime-popper .el-time-spinner__item) {
  color: #64748b;
}
:global(.platform-datetime-popper .el-time-spinner__item:hover:not(.is-disabled):not(.is-active)) {
  color: #2563eb;
  background: #eff6ff;
}
:global(.platform-datetime-popper .el-time-spinner__item.is-active:not(.is-disabled)) {
  color: #2563eb;
  font-weight: 800;
}
:global(.platform-datetime-popper .el-time-panel__footer) {
  height: auto;
  padding: 9px 10px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
:global(.platform-datetime-popper .el-time-panel__btn) {
  min-width: 58px;
  height: 32px;
  margin: 0 2px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 700;
}
:global(.platform-datetime-popper .el-time-panel__btn.confirm) {
  color: #fff;
  background: #3b82f6;
}
@media (max-width: 720px) {
  .homework-form-dialog :deep(.el-dialog),
  :global(.homework-form-dialog.el-dialog) { width: calc(100% - 28px) !important; }
  .creation-form-grid { grid-template-columns: 1fr; }
  .form-span-full { grid-column: auto; }
  .creation-dialog-header { padding: 16px 18px; }
  .homework-creation-form { padding: 18px; }
  .creation-dialog-footer { padding: 14px 18px 16px; }
}
.grade-content {
  border: 1px solid #e2ebf7;
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 16px;
  background: #f8fbff;
}
.grade-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 800;
  margin-bottom: 6px;
}
.grade-text {
  color: #334155;
  white-space: pre-wrap;
  line-height: 1.6;
}
.total-hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}
:global(.grade-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(191, 219, 254, 0.72);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18);
}
:global(.grade-dialog .el-dialog__header) {
  padding: 20px 22px 14px;
  border-bottom: 1px solid #edf2f8;
}
:global(.grade-dialog .el-dialog__title) {
  color: #0f172a;
  font-size: 18px;
  font-weight: 850;
}
:global(.grade-dialog .el-dialog__body) {
  padding: 18px 22px;
}
:global(.grade-dialog .el-dialog__footer) {
  padding: 14px 22px 18px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}
.freeze-tip { margin-left: 12px; color: #16a34a; font-size: 13px; }
.question-builder {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
}
/* 冻结提示独占一行，不参与左右分行 */
.question-builder :deep(.el-alert) {
  flex: none;
  margin: 0;
}
/* 左右分行容器：左题库 + 右已选 */
.question-builder-row {
  flex: 1;
  display: flex;
  flex-direction: row;
  gap: 10px;
  min-height: 0;
  min-width: 0;
}
/* 已发布（冻结）态仅剩已选列：占满宽度，避免右侧大片空白 */
.question-builder.selected-only .selected-panel {
  flex: 1 1 auto;
  max-width: 860px;
}
.question-pool-panel {
  flex: 1 1 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  min-height: 0;
}
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
.question-filters :deep(.el-select__wrapper:hover),
.question-filters :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe, 0 0 0 3px rgba(59, 130, 246, 0.09);
}
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
/* EP 默认 .cell 有 padding: 0 12px 且 overflow: hidden：窄列里会把标签右侧裁掉（表现为标签被截断/带小点）。
   题库列表列宽很紧，必须把 .cell 内边距清零，空间全部留给标签与按钮 */
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
.selected-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  margin-left: auto;
  white-space: nowrap;
}
:global(.grading-drawer-mask) {
  background: rgba(15, 23, 42, 0.38) !important;
  backdrop-filter: blur(2px);
}
:global(.grading-drawer.el-drawer) {
  margin: 18px 22px 18px 0;
  height: calc(100% - 36px) !important;
  /* 抽屉只放提交列表（批改表单是独立弹窗）：62% 在宽屏下过宽（1920 时约 1190px），
     会把表格剩余宽度全灌进学生列。封顶 820px 后卡片约 766px，六列可均衡分配 */
  max-width: 820px;
  border: 1px solid rgba(191, 219, 254, 0.72);
  border-radius: 22px;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  box-shadow: 0 28px 70px rgba(15, 23, 42, 0.22), 0 0 0 8px rgba(219, 234, 254, 0.24);
}
:global(.grading-drawer .el-drawer__body) {
  height: 100%;
  padding: 0;
}
.grading-panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
  height: 100%;
  /* 左右 26→18：1440 视口下卡片宽 +16px，配合列宽分配保证时间列不换行 */
  padding: 24px 18px 26px;
  color: #0f172a;
}
.grading-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.grading-heading {
  min-width: 0;
}
.grading-kicker {
  color: #2563eb;
  font-size: 13px;
  font-weight: 800;
}
.grading-title {
  margin-top: 6px;
  overflow: hidden;
  color: #0f172a;
  font-size: 22px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.grading-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.grading-meta span {
  padding: 5px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  font-weight: 700;
}
.grading-close {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid #dbe5f2;
  border-radius: 12px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background-color 0.18s ease;
}
.grading-close:hover {
  border-color: #bfdbfe;
  color: #2563eb;
  background: #eff6ff;
}
.grading-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  gap: 10px;
  align-items: stretch;
}
.grading-release-all {
  height: 100%;
  border-radius: 16px;
  font-weight: 700;
}
.grading-stat {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid #e2ebf7;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.055);
}
.grading-stat span {
  display: block;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 750;
}
.grading-stat strong {
  display: block;
  margin-top: 6px;
  color: #2563eb;
  font-size: 24px;
  font-weight: 850;
  line-height: 1;
}
.grading-table-card {
  min-height: 0;
  overflow: hidden;
  border: 1px solid #e2ebf7;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.07);
}
.grading-table {
  height: 100%;
  --el-table-border-color: #edf2f8;
  --el-table-header-bg-color: #f8fbff;
  --el-table-row-hover-bg-color: #eff6ff;
}
.grading-table :deep(.el-table__inner-wrapper) {
  height: 100%;
}
.grading-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.grading-table :deep(th.el-table__cell) {
  height: 52px;
  color: #64748b;
  font-weight: 800;
  background: #f8fbff;
}
.grading-table :deep(td.el-table__cell) {
  height: 58px;
  color: #334155;
  /* 字体统一：表格正文一律 14px/600。学生列无 class 曾走默认 400，
     而其他列 700/850 混杂，用户反馈「学生姓名字体跟别的列不一样」 */
  font-size: 14px;
  font-weight: 600;
}
/* 收紧单元格左右内边距（EP 默认 12px → 8px），把宽度让给内容，
   配合 JS 列宽分配保证时间列/操作按钮在窄卡片下也不换行 */
.grading-table :deep(.cell) {
  padding: 0 8px;
}
.grading-score {
  color: #2563eb;
}
.grading-muted {
  color: #94a3b8;
}
.grading-action {
  height: 30px;
  padding: 0 12px;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
  color: #2563eb;
  background: #eff6ff;
  font-size: 13px;
  font-weight: 700;
  /* 按钮文字不换行：列宽按按钮实测宽 + 安全余量分配（见 GRADING_COL_LAYOUT op 项） */
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.grading-action:hover {
  border-color: #60a5fa;
  color: #fff;
  background: #3b82f6;
}
.grading-empty {
  display: grid;
  min-height: 360px;
  place-items: center;
}
.grading-empty :deep(.el-empty__description) {
  color: #94a3b8;
  font-size: 14px;
}
.answer-review-list { display: grid; gap: 12px; max-height: 55vh; overflow: auto; margin-bottom: 18px; }
/* 批改弹窗摘要栏：一眼看清共几题、几题待评分（主观题评分行在列表下方，摘要+定位双保险） */
.grade-mode-brief {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid #dbe5ef;
  border-radius: 10px;
  background: #f6f9fd;
  color: #475569;
  font-size: 13px;
}
.grade-brief-split { width: 1px; height: 12px; background: #cbd5e1; }
.grade-brief-pending { color: #b45309; font-weight: 700; }
.grade-brief-done { color: #16a34a; font-weight: 600; }
.answer-review-item {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
/* 待评分主观题高亮：蓝色边 + 左侧色条，滚动定位后不至于再错过 */
.answer-review-item.is-pending {
  border-color: #93c5fd;
  background: #eff6ff;
  box-shadow: inset 3px 0 0 #2563eb;
}
.answer-review-head { display: flex; justify-content: space-between; gap: 16px; line-height: 1.55; }
.answer-review-head span { flex: none; color: #2563eb; }
.student-answer { color: #475569; white-space: pre-wrap; }
/* 三列网格：标签 / 分数输入 / 评语输入（原两列模板会把评语挤到第二行） */
.manual-grade-row { display: grid; grid-template-columns: 48px 160px 1fr; gap: 10px; align-items: center; }
.manual-grade-label { color: #0f172a; font-weight: 700; }
.attachment-panel {
  display: grid;
  flex: 1;
  place-items: center;
  min-height: 520px;
}
.attachment-uploader { width: min(520px, 86%); }
.attachment-uploader :deep(.el-upload),
.attachment-uploader :deep(.el-upload-dragger) { width: 100%; }
.attachment-uploader :deep(.el-upload-dragger) {
  padding: 64px 24px;
  border: 1px dashed #bfdbfe;
  border-radius: 18px;
  background: linear-gradient(145deg, #f8fbff, #f1f7ff);
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}
.attachment-uploader :deep(.el-upload-dragger:hover) {
  transform: translateY(-2px);
  border-color: #60a5fa;
  background: #eff6ff;
}
.attachment-upload-icon { color: #3b82f6; font-size: 42px; }
.attachment-upload-title { margin-top: 15px; color: #334155; font-size: 15px; font-weight: 750; }
.attachment-upload-tip { margin-top: 7px; color: #94a3b8; font-size: 13px; }
/* ---- 已上传附件列表（编辑页直接展示，支持查看 / 移除） ---- */
.uploaded-attachments {
  width: min(520px, 86%);
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid #dbeafe;
  border-radius: 14px;
  background: #f8fbff;
  display: grid;
  gap: 10px;
}
.uploaded-attachments-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
.uploaded-attachments-title {
  color: #1e293b;
  font-size: 13px;
  font-weight: 800;
}
.uploaded-attachments-title::before {
  content: '';
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 7px;
  border-radius: 50%;
  background: #16a34a;
  vertical-align: 1px;
}
.uploaded-attachments-hint { color: #94a3b8; font-size: 12px; }
.uploaded-attachment-item { display: flex; align-items: center; gap: 12px; }
.attachment-view-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}
.attachment-view-link:hover { color: #1d4ed8; text-decoration: underline; }
@media (max-width: 1180px) {
  .creation-form-grid { grid-template-columns: 320px minmax(0, 1fr); gap: 10px; }
  .hw-card { padding: 12px 12px 14px; }
  .selected-panel { flex-basis: 320px; }
}
@media (max-width: 920px) {
  .creation-form-grid { grid-template-columns: 1fr; }
  .hw-card { min-height: auto; }
  .hw-editor-topbar { flex-wrap: wrap; }
  .hw-editor-actions { width: 100%; justify-content: flex-end; }
  .homework-editor-body { overflow: auto; }
  .creation-form-grid { height: auto; }
  .form-col { min-height: auto; }
  .hw-content-card { min-height: 720px; }
  /* 窄屏：题目选择区回退上下结构（题库固定高度，已选列自适应） */
  .question-builder-row { flex-direction: column; }
  .question-pool-panel { flex: none; height: 400px; }
  .selected-panel { flex: 1 1 auto; min-height: 300px; }
}
@media (max-width: 720px) {
  .selected-header { align-items: flex-start; flex-direction: column; gap: 4px; }
  .question-pool-panel { height: 360px; }
}

/* ---- 时间选择提示 ---- */
.time-field-tip {
  padding: 0 2px 2px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

/* ---- 附件上传：文件信息 / 进度 / 状态 / 大小统计 ---- */
.upload-file-card {
  width: min(520px, 86%);
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid #dbeafe;
  border-radius: 14px;
  background: #f8fbff;
  display: grid;
  gap: 10px;
}
.upload-file-card.is-success { border-color: #bbf7d0; background: #f0fdf4; }
.upload-file-card.is-error { border-color: #fecaca; background: #fef2f2; }
.upload-file-main { display: flex; align-items: center; gap: 12px; }
.upload-file-icon {
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #2563eb;
  background: #eff6ff;
  font-size: 20px;
}
.upload-file-card.is-success .upload-file-icon { color: #16a34a; background: #dcfce7; }
.upload-file-card.is-error .upload-file-icon { color: #dc2626; background: #fee2e2; }
.upload-file-info { flex: 1; min-width: 0; }
.upload-file-name {
  color: #1e293b;
  font-size: 13px;
  font-weight: 750;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.upload-file-meta {
  margin-top: 3px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
}
.upload-file-ext {
  padding: 0 6px;
  border-radius: 5px;
  color: #2563eb;
  background: #dbeafe;
  font-size: 11px;
  font-weight: 800;
}
.upload-file-status { flex: none; display: flex; align-items: center; gap: 8px; }
.upload-status-text { font-size: 12px; font-weight: 800; }
.upload-status-text.is-uploading { color: #2563eb; }
.upload-progress-track {
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}
.upload-progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  transition: width 0.2s ease;
}
.upload-error-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.upload-error-text { color: #dc2626; font-size: 12px; }
.upload-file-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #94a3b8;
  font-size: 12px;
}
.upload-replace-tip { color: #f59e0b; }

/* 附件 PDF 滚动预览（无工具栏，师生端同一组件） */
.attachment-preview-box {
  margin-top: 12px;
}

/* ---- 批改弹窗：正确答案/解析与学生附件预览 ---- */
.correct-answer { color: #059669; font-weight: 700; }
.correct-answer::before { content: ''; }
.answer-analysis { color: #64748b; font-size: 13px; line-height: 1.6; }
.manual-grade-label { align-self: center; color: #64748b; font-size: 13px; font-weight: 700; }
.student-attachments { margin-top: 14px; }
.student-attachment-list {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.student-attachment-item {
  width: 108px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: grid;
  justify-items: center;
  gap: 6px;
  background: #fff;
  text-decoration: none;
  transition: border-color 0.18s ease, transform 0.18s ease;
}
.student-attachment-item:hover { border-color: #93c5fd; transform: translateY(-2px); }
.student-attachment-thumb {
  width: 88px;
  height: 64px;
  border-radius: 7px;
  background: #f1f5f9;
  cursor: zoom-in;
}
.student-attachment-icon { color: #64748b; font-size: 30px; line-height: 64px; }
.student-attachment-name {
  max-width: 100%;
  color: #334155;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.student-attachment-size { color: #94a3b8; font-size: 11px; }
</style>
