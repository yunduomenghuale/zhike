<template>
  <div class="page-container">
    <Teleport to="body">
    <div
      v-if="videoVisible && videoMode === 'player'"
      v-loading="videoLoading"
      class="full-lecture-page"
    >
      <header class="full-lecture-header">
        <div class="full-lecture-title-wrap">
          <div class="full-lecture-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="full-lecture-title-copy">
            <div class="full-lecture-title-line">
              <h1>完整讲解</h1>
              <span class="full-lecture-kicker">{{ courseName }}</span>
            </div>
            <p>{{ videoNode?.title }}</p>
          </div>
        </div>
        <div class="full-lecture-actions">
          <div v-if="videoScripts.length" class="full-lecture-stats">
            <span><strong>{{ videoScripts.length }}</strong> 页讲解稿</span>
            <span><strong>{{ currentAudioCount }}</strong> 页配音</span>
            <el-tag :type="currentAudioCount ? 'success' : 'info'" effect="light" round>
              {{ videoDetail?.gen_status_display || videoDetail?.gen_status || '已生成' }}
            </el-tag>
          </div>
          <el-button
            class="full-lecture-soft-btn"
            :class="{ 'is-active': dockVisible && dockTab !== 'script' }"
            :icon="ChatDotRound"
            @click="toggleDock"
          >AI 助教</el-button>
          <el-button
            class="full-lecture-soft-btn"
            :class="{ 'is-active': dockVisible && dockTab === 'script' }"
            :icon="Document"
            @click="toggleScriptDock"
          >讲解稿</el-button>
          <el-button class="full-lecture-soft-btn" @click="videoVisible = false">退出讲解</el-button>
        </div>
      </header>

      <div class="full-lecture-body">
      <main class="full-lecture-main">
        <section v-if="playerPages.length" class="full-lecture-stage-card">
          <div class="full-lecture-stage">
            <div class="ppt-stage-count">{{ playerPageIndex + 1 }} / {{ playerPages.length }}</div>
            <img
              v-if="currentPlayerPage?.image || currentPlayerPage?.image_url"
              class="full-lecture-image"
              :src="currentPlayerPage.image || currentPlayerPage.image_url"
              :alt="currentPlayerPage?.title || `第 ${currentPlayerPage?.page || playerPageIndex + 1} 页`"
            />
            <template v-else>
              <div class="ppt-stage-title">{{ currentPlayerPage?.title || `第 ${currentPlayerPage?.page || playerPageIndex + 1} 页` }}</div>
              <div class="ppt-stage-body">{{ currentPlayerPage?.body || '（本页无文本内容）' }}</div>
            </template>
          </div>

          <div class="full-lecture-control-panel">
            <audio
              v-if="currentPlayerScript?.audio_url"
              ref="playerAudioRef"
              :key="currentPlayerPage?.page"
              :src="currentPlayerScript.audio_url"
              :autoplay="playerAutoPlay"
              style="display: none"
              @ended="onPlayerAudioEnded"
              @play="onPlayerPlay"
              @pause="onPlayerAudioPause"
              @timeupdate="onPlayerTimeUpdate"
              @loadedmetadata="onPlayerLoadedMeta"
            />

            <el-button class="lecture-nav-btn" :icon="ArrowLeft" :disabled="playerPageIndex === 0" @click="prevPlayerPage">上一页</el-button>

            <button class="lecture-play-btn" :disabled="!currentPlayerScript?.audio_url" @click="togglePlayer">
              <el-icon><VideoPause v-if="playerAutoPlay" /><VideoPlay v-else /></el-icon>
            </button>

            <template v-if="currentPlayerScript?.audio_url">
              <span class="lecture-time">{{ fmtTime(playerCurrent) }}</span>
              <div class="lecture-progress" @click="seekPlayer">
                <div class="lecture-progress-fill" :style="{ width: playerProgress + '%' }"></div>
              </div>
              <span class="lecture-time">{{ fmtTime(playerDuration) }}</span>
            </template>
            <span v-else class="lecture-no-audio">该页暂无配音，播放会自动跳到下一有配音的页</span>

            <el-button class="lecture-nav-btn" :disabled="playerPageIndex >= playerPages.length - 1" @click="nextPlayerPage">
              下一页 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </section>

        <div v-else-if="!videoLoading" class="full-lecture-empty">
          <el-empty description="还没有可播放的 PPT 页面，请先上传课件" />
        </div>
      </main>

      <transition name="dock-slide">
        <aside v-if="dockVisible" class="full-lecture-dock">
          <div class="dock-tabs">
            <button
              class="dock-tab"
              :class="{ active: dockTab === 'chat' }"
              @click="dockTab = 'chat'"
            ><el-icon><ChatDotRound /></el-icon> AI 问答</button>
            <button
              class="dock-tab"
              :class="{ active: dockTab === 'materials' }"
              @click="switchDockTab('materials')"
            ><el-icon><Folder /></el-icon> 相关资料</button>
            <button
              class="dock-tab"
              :class="{ active: dockTab === 'script' }"
              @click="switchDockTab('script')"
            ><el-icon><Document /></el-icon> 讲解稿</button>
            <button class="dock-close" title="收起" @click="dockVisible = false">
              <el-icon><Close /></el-icon>
            </button>
          </div>

          <!-- 对话 -->
          <div v-show="dockTab === 'chat'" class="dock-chat">
            <div ref="chatScrollRef" class="chat-messages">
              <div v-if="!chatMessages.length" class="chat-empty">
                <div class="chat-empty-hero">
                  <span class="chat-empty-glow"></span>
                  <div class="chat-empty-icon"><el-icon><MagicStick /></el-icon></div>
                </div>
                <p class="chat-empty-title">课程 AI 助教</p>
                <p class="chat-empty-desc">结合本课程的课件、讲义与知识库为你解答，也能帮你梳理重点、举例说明。</p>
                <div class="chat-suggests">
                  <div class="chat-suggests-label">试试这样问</div>
                  <button
                    v-for="q in chatSuggests"
                    :key="q"
                    class="chat-suggest"
                    @click="askChat(q)"
                  >{{ q }}</button>
                </div>
              </div>

              <div
                v-for="(m, i) in chatMessages"
                :key="i"
                class="chat-row"
                :class="m.role"
              >
                <div class="chat-bubble" :class="{ bare: m.imageOnly }">
                  <span v-if="m.streaming && !m.content" class="chat-typing"><i></i><i></i><i></i></span>
                  <div
                    v-else-if="m.role === 'assistant'"
                    class="chat-text chat-md"
                    v-html="renderMd(m.content + (m.streaming ? ' ▍' : ''))"
                  ></div>
                  <div v-else class="chat-text">
                    <img v-if="m.image" :src="m.image" class="q-image" alt="提问图片" />
                    <template v-if="!m.imageOnly">{{ m.content }}</template>
                  </div>
                </div>
              </div>
            </div>

            <div class="chat-input">
              <div v-if="chatImage" class="chat-image-preview">
                <img :src="chatImage" alt="待发送图片" />
                <button class="preview-remove" title="移除图片" @click="chatImage = ''">
                  <el-icon :size="11"><Close /></el-icon>
                </button>
              </div>
              <textarea
                ref="chatTextareaRef"
                v-model="chatInput"
                class="chat-textarea"
                rows="1"
                placeholder="就本课程知识库提问…（Enter 发送）"
                @input="autoGrowInput"
                @keydown.enter.exact.prevent="askChat()"
              ></textarea>
              <div class="chat-input-bar">
                <input ref="chatFileRef" type="file" accept="image/*" hidden @change="onPickChatImage" />
                <button class="chat-tool" title="提交图片提问" @click="chatFileRef?.click()">
                  <el-icon :size="15"><Picture /></el-icon>
                  图片
                </button>
                <button
                  class="chat-send"
                  title="发送"
                  :disabled="chatLoading || (!chatInput.trim() && !chatImage)"
                  @click="askChat()"
                ><el-icon><Promotion /></el-icon></button>
              </div>
            </div>
          </div>

          <!-- 相关资料 -->
          <div v-show="dockTab === 'materials'" class="dock-materials">
            <div v-if="materialsLoading" class="dock-loading">
              <el-icon class="is-loading"><Loading /></el-icon> 正在加载资料…
            </div>
            <template v-else>
              <div v-if="!materials.length" class="dock-empty">
                <el-empty description="本课程还没有上传知识库资料" :image-size="90" />
              </div>
              <a
                v-for="m in materials"
                :key="m.id"
                class="material-item"
                :href="fileUrl(m.file)"
                target="_blank"
                rel="noopener"
              >
                <span class="material-icon" :class="'ext-' + (m.file_type || 'file')">
                  <el-icon><Document /></el-icon>
                </span>
                <span class="material-copy">
                  <span class="material-name">{{ m.file_name }}</span>
                  <span class="material-meta">
                    {{ (m.file_type || '文件').toUpperCase() }}
                    · {{ m.chunk_count || 0 }} 片段
                    · {{ m.parse_status_display }}
                  </span>
                </span>
                <el-icon class="material-open"><Right /></el-icon>
              </a>
            </template>
          </div>

          <!-- 逐页讲解稿 -->
          <div v-show="dockTab === 'script'" class="dock-scripts">
            <div class="dock-script-summary">
              <div>
                <strong>逐页讲解稿</strong>
                <span>跟随当前 PPT 页面同步显示</span>
              </div>
              <span class="dock-script-progress">
                {{ playerPages.length ? playerPageIndex + 1 : 0 }} / {{ videoScripts.length }}
              </span>
            </div>

            <div v-if="videoScripts.length" ref="scriptDockListRef" class="dock-script-list">
              <button
                v-for="item in videoScripts"
                :key="item.page"
                type="button"
                class="dock-script-item"
                :class="{ active: currentPlayerPage?.page === item.page }"
                :data-script-page="item.page"
                @click="selectScriptPage(item)"
              >
                <span class="dock-script-item-head">
                  <span>第 {{ item.page }} 页</span>
                  <span class="dock-script-audio" :class="{ ready: item.audio_url }">
                    {{ item.audio_url ? '已配音' : '未配音' }}
                  </span>
                </span>
                <span class="dock-script-text">{{ item.script || '本页暂无讲解稿' }}</span>
              </button>
            </div>
            <div v-else-if="!videoLoading" class="dock-empty">
              <el-empty description="当前章节还没有讲解稿" :image-size="90" />
            </div>
          </div>
        </aside>
      </transition>
      </div>
    </div>
    </Teleport>

    <el-card shadow="never" class="data-card">
      <div class="catalog-toolbar">
        <div class="catalog-toolbar-actions">
          <el-button class="catalog-action-btn catalog-action-secondary" :icon="MagicStick" @click="openPlanDialog">授课计划识别目录</el-button>
          <el-button class="catalog-action-btn catalog-action-primary" type="primary" :icon="Plus" @click="openEdit(null, null)">添加章</el-button>
        </div>
      </div>
      <el-tree
        v-if="tree.length"
        class="catalog-tree"
        :data="tree"
        node-key="id"
        default-expand-all
        :expand-on-click-node="false"
      >
        <template #default="{ data }">
          <div class="tree-node" :class="{ 'is-child': data.parent }">
            <div class="node-main">
              <div class="node-left">
                <span class="node-icon-wrap">
                  <el-icon class="node-icon"><Folder v-if="!data.parent" /><Document v-else /></el-icon>
                </span>
                <span class="node-copy">
                  <span class="node-title-row">
                    <span class="node-title">{{ data.title }}</span>
                    <el-tag v-if="data.is_published" size="small" type="primary" effect="plain" round>已发布</el-tag>
                  </span>
                </span>
              </div>
              <div class="node-tags">
                <el-tag v-if="pptMap[data.id]" size="small" type="success" effect="light" round>
                  课件 {{ pptMap[data.id].pages }} 页
                </el-tag>
                <el-tag v-else size="small" type="info" effect="plain" round>无课件</el-tag>
                <el-tag v-if="scriptCount(videoMap[data.id])" size="small" type="primary" effect="light" round>
                  讲解稿 {{ scriptCount(videoMap[data.id]) }} 页
                </el-tag>
                <el-tag v-if="audioCount(videoMap[data.id])" size="small" type="warning" effect="light" round>
                  配音 {{ audioCount(videoMap[data.id]) }} 页
                </el-tag>
              </div>
            </div>
            <div class="node-actions">
              <div class="node-action-group">
                <el-button class="node-action-btn" :icon="Upload" @click.stop="openPpt(data)">课件</el-button>
                <el-button class="node-action-btn" :icon="Microphone" :loading="scriptLoading === data.id" @click.stop="openScript(data)">
                  {{ scriptCount(videoMap[data.id]) ? '讲稿' : '生成讲稿' }}
                </el-button>
                <el-button class="node-action-btn" :icon="Headset" :loading="audioLoading === data.id" @click.stop="genAudio(data)">配音</el-button>
                <el-button class="node-action-btn" :icon="VideoPlay" @click.stop="openVideo(data, 'player')">完整讲解</el-button>
              </div>
              <div class="node-manage-group">
                <el-switch
                  size="small"
                  :model-value="data.is_published"
                  @change="(v) => togglePublish(data, v)"
                  @click.stop
                />
                <el-button class="node-icon-btn" text circle :icon="Edit" @click.stop="openEdit(data, null)" />
                <el-button
                  class="node-icon-btn"
                  text
                  circle
                  type="danger"
                  :icon="Delete"
                  title="删除目录"
                  @click.stop="openDeleteNode(data)"
                />
              </div>
            </div>
          </div>
        </template>
      </el-tree>
      <el-empty v-else :description="emptyDescription" />
    </el-card>

    <!-- 新建/编辑章节 -->
    <el-dialog
      v-model="editVisible"
      width="560px"
      align-center
      class="chapter-form-dialog"
      :show-close="false"
    >
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon chapter-create-icon">
            <el-icon><Folder /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ editTitle }}</div>
            <div class="creation-dialog-subtitle">
              {{ form.parent ? '小节基础信息' : '章节基础信息' }}
            </div>
          </div>
          <el-button
            text
            circle
            class="creation-dialog-close"
            :icon="Close"
            aria-label="关闭"
            @click="editVisible = false"
          />
        </div>
      </template>

      <el-form :model="form" label-position="top" class="creation-form chapter-creation-form">
        <div class="chapter-form-grid">
          <el-form-item label="标题">
            <el-input v-model="form.title" placeholder="如 第一章 绪论 / 1.1 概述" clearable />
          </el-form-item>
          <el-form-item label="排序号">
            <el-input-number v-model="form.order" :min="0" controls-position="right" />
          </el-form-item>
          <el-form-item label="简介" class="form-span-full">
            <el-input v-model="form.intro" type="textarea" :rows="3" placeholder="请输入章节简介" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">
            {{ form.id ? '保存修改' : form.parent ? '添加小节' : '添加章节' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      :title="deleteTarget?.parent ? '删除小节' : '删除章节'"
      :item-name="deleteTarget?.title"
      :description="deleteTarget?.parent
        ? '删除后，该小节将无法继续访问，此操作无法撤销。'
        : '删除后，该章节及关联课件、讲解稿和配音将无法继续访问，此操作无法撤销。'"
      :loading="deleting"
      @confirm="confirmDeleteNode"
    />

    <!-- 新增课程目录 -->
    <el-dialog
      v-model="planVisible"
      width="760px"
      align-center
      class="catalog-dialog"
      :show-close="false"
      @closed="resetPlanDialog"
    >
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon chapter-create-icon">
            <el-icon><Folder /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">新增课程目录</div>
            <div class="creation-dialog-subtitle">{{ courseName }}</div>
          </div>
          <el-button
            text
            circle
            class="creation-dialog-close"
            :icon="Close"
            aria-label="关闭"
            @click="planVisible = false"
          />
        </div>
      </template>

      <div class="catalog-body">
        <div class="mode-switch" role="tablist">
          <button
            type="button"
            class="mode-option"
            :class="{ active: planMode === 'upload' }"
            @click="planMode = 'upload'"
          >
            <el-icon><UploadFilled /></el-icon>
            <span>上传授课文件</span>
          </button>
          <button
            type="button"
            class="mode-option"
            :class="{ active: planMode === 'manual' }"
            @click="planMode = 'manual'"
          >
            <el-icon><Edit /></el-icon>
            <span>手动添加</span>
          </button>
        </div>

        <section v-if="planMode === 'upload'" class="catalog-section">
          <el-upload
            drag
            :show-file-list="false"
            :before-upload="handlePlanUpload"
            :accept="outlineFileAccept"
            class="course-upload"
          >
            <div class="upload-inner">
              <div class="upload-mark">
                <el-icon><UploadFilled /></el-icon>
              </div>
              <div class="upload-main">拖入或选择授课文件</div>
              <div class="upload-sub">PPT、PDF、Word、TXT、Markdown、CSV</div>
            </div>
          </el-upload>

          <div v-if="planFile" class="file-status">
            <div class="file-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="file-meta">
              <div class="file-name">{{ planFile.name }}</div>
              <div class="file-note">
                {{
                  planChapterTree.length
                    ? `已识别 ${planChapterTree.length} 个章目录`
                    : '未识别到章目录，可手动添加或稍后维护'
                }}
              </div>
            </div>
            <el-tag size="small" :type="planChapterTree.length ? 'success' : 'warning'" effect="light">
              {{ planChapterTree.length ? '已解析' : '需调整' }}
            </el-tag>
          </div>

          <div v-if="planChapterTree.length" class="outline-preview">
            <div class="preview-head">
              <span>目录预览</span>
              <el-button link type="primary" :icon="Edit" @click="planMode = 'manual'">
                调整
              </el-button>
            </div>
            <ul>
              <li v-for="(chapter, i) in planChapterTree" :key="`${chapter.title}-${i}`">
                {{ chapter.title }}
              </li>
            </ul>
          </div>

          <el-alert
            v-else-if="planFile && !planLoading"
            class="outline-alert"
            type="warning"
            show-icon
            :closable="false"
            title="只会保存“第1章 / 第一章”这类章目录，1.1 等小节不会进入目录"
          />
        </section>

        <section v-else-if="planMode === 'manual'" class="catalog-section">
          <div class="manual-panel">
            <div class="manual-head">
              <div>
                <div class="manual-title">手动创建章目录</div>
              </div>
              <el-tag size="small" type="primary" effect="light" round>
                {{ validManualChapterCount }} 章
              </el-tag>
            </div>

            <div class="manual-list">
              <div
                v-for="(chapter, chapterIndex) in manualPlanChapters"
                :key="chapter.uid"
                class="manual-chapter"
              >
                <div class="manual-index">{{ chapterIndex + 1 }}</div>
                <el-input
                  v-model="chapter.title"
                  class="manual-input"
                  clearable
                  placeholder="章标题，如 第1章 Java语言概述"
                />
                <el-button
                  class="manual-delete"
                  :icon="Delete"
                  text
                  circle
                  type="danger"
                  @click="removePlanChapter(chapterIndex)"
                />
              </div>
            </div>

            <button type="button" class="manual-add-card" @click="addPlanChapter">
              <el-icon><Plus /></el-icon>
              <span>添加章</span>
            </button>
          </div>
        </section>

      </div>

      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="planVisible = false">取消</el-button>
          <el-button
            type="primary"
            :disabled="!canSavePlan"
            :loading="importing || planLoading"
            @click="importPlan"
          >
            保存目录
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 章节课件 -->
    <el-dialog v-model="pptVisible" width="560px" align-center class="ppt-dialog">
      <template #header>
        <div class="ppt-dialog-head">
          <div class="ppt-head-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="ppt-head-copy">
            <div class="ppt-head-title">章节课件</div>
            <div class="ppt-head-subtitle">{{ currentNode?.title }}</div>
          </div>
        </div>
      </template>

      <div v-if="currentPpt" class="ppt-current">
        <div class="ppt-file-icon">
          <el-icon><Document /></el-icon>
        </div>
        <div class="ppt-file-info">
          <div class="ppt-file-name">{{ currentPpt.file_name }}</div>
          <div class="ppt-file-meta">
            {{ currentPpt.pages ? `已解析 ${currentPpt.pages} 页` : '未解析到可用页面文本' }}
          </div>
        </div>
        <el-tag size="small" :type="currentPpt.pages ? 'success' : 'warning'" effect="light" round>
          {{ currentPpt.pages ? '可用于 AI' : '需检查' }}
        </el-tag>
      </div>
      <div v-else class="ppt-empty-state">
        <div class="ppt-empty-icon">
          <el-icon><Document /></el-icon>
        </div>
        <div class="ppt-empty-title">该章节还没有课件</div>
        <div class="ppt-empty-desc">上传 PPT 后，系统会自动解析页面文本用于出题和讲解稿生成。</div>
      </div>

      <el-upload
        drag
        :show-file-list="false"
        :before-upload="handlePptUpload"
        :accept="fileAccept"
        :disabled="uploading"
        class="ppt-upload"
      >
        <div class="ppt-upload-inner">
          <div class="ppt-upload-icon">
            <el-icon><UploadFilled /></el-icon>
          </div>
          <div class="ppt-upload-title">{{ uploading ? '正在上传解析...' : '拖入或选择 PPT 课件' }}</div>
          <div class="ppt-upload-desc">仅支持 .ppt / .pptx 文件</div>
        </div>
      </el-upload>
      <div v-if="currentPpt?.parsed_pages?.length" class="ppt-page-preview">
        <div class="ppt-preview-head">
          <span>解析预览</span>
          <el-tag size="small" effect="plain">{{ currentPpt.parsed_pages.length }} 页</el-tag>
        </div>
        <div class="ppt-page-list">
          <div
            v-for="page in currentPpt.parsed_pages.slice(0, 5)"
            :key="page.page"
            class="ppt-page-item"
          >
            <div class="ppt-page-index">第 {{ page.page }} 页</div>
            <div class="ppt-page-content">
              <div class="ppt-page-title">{{ page.title || '未识别标题' }}</div>
              <div class="ppt-page-body">{{ page.body || '本页未识别到正文文本' }}</div>
            </div>
          </div>
        </div>
      </div>
      <div class="ppt-tip">上传后会替换当前章节课件，并自动解析文本作为 AI 出题与讲解稿生成依据。</div>
    </el-dialog>

    <!-- 完整讲解 / 讲解稿 -->
    <el-dialog
      v-if="videoMode !== 'player'"
      v-model="videoVisible"
      width="720px"
      align-center
      class="script-dialog"
      :close-on-click-modal="true"
    >
      <template #header>
        <div class="script-dialog-head">
          <div class="script-head-icon">
            <el-icon><Document /></el-icon>
          </div>
          <div class="script-head-copy">
            <div class="script-head-title">{{ videoMode === 'player' ? '完整讲解' : '讲解稿与配音' }}</div>
            <div class="script-head-subtitle">{{ videoNode?.title }}</div>
          </div>
        </div>
      </template>

      <div v-loading="videoLoading" class="script-dialog-body">
        <div v-if="videoScripts.length" class="script-summary">
          <div class="script-stat">
            <span class="script-stat-value">{{ videoScripts.length }}</span>
            <span class="script-stat-label">页讲解稿</span>
          </div>
          <div class="script-stat">
            <span class="script-stat-value">{{ currentAudioCount }}</span>
            <span class="script-stat-label">页配音</span>
          </div>
          <el-tag :type="currentAudioCount ? 'success' : 'info'" effect="light" round>
            {{ videoDetail?.gen_status_display || videoDetail?.gen_status || '已生成' }}
          </el-tag>
          <el-segmented
            v-model="videoMode"
            size="small"
            :options="[
              { label: '完整讲解', value: 'player' },
              { label: '讲解稿', value: 'script' },
            ]"
          />
          <el-button
            v-if="videoMode === 'player'"
            size="small"
            type="primary"
            :icon="VideoPlay"
            :disabled="!playerPages.length"
            @click="togglePlayer"
          >
            {{ playerAutoPlay ? '停止播放' : '播放课件' }}
          </el-button>
        </div>

        <div v-if="videoMode === 'player' && playerPages.length" class="ppt-player">
          <div class="ppt-stage">
            <div class="ppt-stage-count">{{ playerPageIndex + 1 }} / {{ playerPages.length }}</div>
            <img
              v-if="currentPlayerPage?.image || currentPlayerPage?.image_url"
              class="ppt-stage-image"
              :src="currentPlayerPage.image || currentPlayerPage.image_url"
              :alt="currentPlayerPage?.title || `第 ${currentPlayerPage?.page || playerPageIndex + 1} 页`"
            />
            <template v-else>
              <div class="ppt-stage-title">{{ currentPlayerPage?.title || `第 ${currentPlayerPage?.page || playerPageIndex + 1} 页` }}</div>
              <div class="ppt-stage-body">{{ currentPlayerPage?.body || '（本页无文本内容）' }}</div>
            </template>
          </div>
          <div class="ppt-player-script">
            <div class="ppt-player-script-head">
              <span>当前页配音</span>
              <el-tag v-if="currentPlayerScript?.audio_url" size="small" type="success" effect="light" round>已配音</el-tag>
              <el-tag v-else size="small" type="info" effect="plain" round>未配音</el-tag>
            </div>
            <audio
              v-if="currentPlayerScript?.audio_url"
              ref="playerAudioRef"
              :key="currentPlayerPage?.page"
              class="script-audio"
              :src="currentPlayerScript.audio_url"
              controls
              :autoplay="playerAutoPlay"
              @ended="onPlayerAudioEnded"
              @play="playerAutoPlay = true"
              @pause="onPlayerAudioPause"
            />
            <div v-else class="script-muted">该页还没有配音，播放会自动跳到下一页有配音的页面。</div>
          </div>
          <div class="ppt-player-bar">
            <el-button :icon="ArrowLeft" :disabled="playerPageIndex === 0" @click="prevPlayerPage">上一页</el-button>
            <el-button type="primary" :icon="VideoPlay" :disabled="!currentPlayerScript?.audio_url" @click="togglePlayer">
              {{ playerAutoPlay ? '暂停' : '播放' }}
            </el-button>
            <el-button :disabled="playerPageIndex >= playerPages.length - 1" @click="nextPlayerPage">
              下一页<el-icon class="el-icon--right"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </div>

        <div v-else-if="videoMode === 'player' && !playerPages.length && !videoLoading" class="player-empty">
          <el-empty description="还没有可播放的 PPT 页面，请先上传课件" />
        </div>

        <div v-if="videoMode === 'script' && videoDetail?.video_url" class="script-video">
          <video :src="videoDetail.video_url" controls />
        </div>
        <el-alert
          v-else-if="videoMode === 'script' && videoScripts.length"
          type="info"
          :closable="false"
          show-icon
          class="script-alert"
          title="这里用于查看和校对逐页讲解稿；完整连续播放请切到「完整讲解」。"
        />

        <div v-if="videoMode === 'script' && videoScripts.length" class="script-list">
          <div
            v-for="item in videoScripts"
            :key="item.page"
            class="script-item"
          >
            <div class="script-item-head">
              <div class="script-page">第 {{ item.page }} 页</div>
              <div class="script-page-actions">
                <el-tag v-if="item.audio_url" size="small" type="success" effect="light" round>已配音</el-tag>
                <el-tag v-else size="small" type="info" effect="plain" round>未配音</el-tag>
                <el-button
                  size="small"
                  text
                  type="primary"
                  :loading="pageScriptLoading === item.page"
                  @click="regenerateScriptPage(item)"
                >
                  重新生成本页
                </el-button>
              </div>
            </div>
            <el-input
              v-model="item.script"
              class="script-editor"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              @focus="stopPlayer"
            />
            <div class="script-edit-actions">
              <span v-if="item.audio_url && isScriptDirty(item)" class="script-dirty-tip">
                保存后该页需要重新配音
              </span>
              <span v-else-if="isScriptDirty(item)" class="script-dirty-tip">
                内容已修改，记得保存
              </span>
              <el-button
                size="small"
                type="primary"
                plain
                :disabled="!isScriptDirty(item)"
                :loading="scriptSaving === item.page"
                @click="saveScriptItem(item)"
              >
                保存修改
              </el-button>
            </div>
            <audio v-if="item.audio_url" class="script-audio" :src="item.audio_url" controls @play="stopPlayer" />
          </div>
        </div>
        <el-empty v-else-if="videoMode === 'script' && !videoLoading" description="还没有讲稿，先点击章节右侧「讲稿」生成" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowRight, Plus, Edit, Delete, Upload, MagicStick, Folder, Document, Microphone, Headset, UploadFilled, VideoPlay, VideoPause, ChatDotRound, Close, Promotion, Picture, Loading, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import {
  listCourses, listCatalogs, createCatalog, updateCatalog, deleteCatalog,
  previewCatalogFromFile, listPpts, uploadPpt, generateScript, generateAudio, listVideos, updateVideoScript, regenerateVideoScriptPage,
} from '@/api/course'
import { listMaterials } from '@/api/knowledge'
import MarkdownIt from 'markdown-it'

// html:false 会转义原始 HTML 标签，天然防止模型输出注入脚本
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
function renderMd(text) {
  return md.render(text || '')
}

const route = useRoute()
const courseId = Number(route.params.id)
const courseName = ref('')
const rawTree = ref([])
const catalogSearch = computed(() => String(route.query.search || '').trim().toLowerCase())
const tree = computed(() => filterCatalogTree(rawTree.value, catalogSearch.value))
const emptyDescription = computed(() => (
  catalogSearch.value
    ? `没有找到包含“${route.query.search}”的章节`
    : '还没有章节，点击「添加章」或用授课计划自动识别'
))
const pptMap = reactive({}) // catalogId -> {file_name, pages}
const videoMap = reactive({}) // catalogId -> TeachingVideo
const currentPpt = computed(() => (currentNode.value ? pptMap[String(currentNode.value.id)] : null))
const fileAccept = '.ppt,.pptx'

async function loadCourseName() {
  const data = await listCourses()
  const list = data.results ?? data
  courseName.value = list.find((c) => c.id === courseId)?.name || ''
}

async function loadTree() {
  const data = await listCatalogs({ course: courseId, tree: 1 })
  rawTree.value = data.results ?? data
  await Promise.all([loadPpts(), loadVideos()])
}

function filterCatalogTree(nodes, keyword) {
  if (!keyword) return nodes
  return (nodes || [])
    .map((node) => {
      const children = filterCatalogTree(node.children || [], keyword)
      const text = `${node.title || ''} ${node.intro || ''}`.toLowerCase()
      if (text.includes(keyword) || children.length) {
        return { ...node, children }
      }
      return null
    })
    .filter(Boolean)
}

async function loadPpts({ reset = true } = {}) {
  const data = await listPpts({ course: courseId })
  const list = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : []
  if (reset) Object.keys(pptMap).forEach((k) => delete pptMap[k])
  list.forEach((p) => {
    if (p.is_active || p.parse_status === 'done') setPptMapItem(p)
  })
}

async function loadVideos({ reset = true } = {}) {
  const data = await listVideos({ course: courseId })
  const list = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : []
  if (reset) Object.keys(videoMap).forEach((k) => delete videoMap[k])
  list.forEach(setVideoMapItem)
}

function setVideoMapItem(video) {
  if (!video?.catalog) return
  videoMap[String(video.catalog)] = video
}

function scriptCount(video) {
  return Array.isArray(video?.scripts) ? video.scripts.length : 0
}

function audioCount(video) {
  return Array.isArray(video?.scripts)
    ? video.scripts.filter((item) => item?.audio_url).length
    : 0
}

// ---- 新建/编辑 ----
const editVisible = ref(false)
const saving = ref(false)
const editTitle = ref('添加章')
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)
const form = reactive({ id: null, parent: null, title: '', order: 0, intro: '' })
function openEdit(node, parentNode) {
  if (node) {
    editTitle.value = '编辑'
    Object.assign(form, { id: node.id, parent: node.parent, title: node.title, order: node.order, intro: node.intro || '' })
  } else {
    editTitle.value = parentNode ? `在「${parentNode.title}」下加节` : '添加章'
    Object.assign(form, { id: null, parent: parentNode?.id || null, title: '', order: 0, intro: '' })
  }
  editVisible.value = true
}
async function save() {
  if (!form.title) return ElMessage.warning('请填写标题')
  saving.value = true
  try {
      const payload = { course: courseId, parent: form.parent, title: form.title, order: form.order, intro: form.intro }
      if (form.id) await updateCatalog(form.id, payload)
      else await createCatalog({ ...payload, is_published: true })
    ElMessage.success('已保存')
    editVisible.value = false
    loadTree()
  } finally {
    saving.value = false
  }
}
async function togglePublish(node, v) {
  await updateCatalog(node.id, { is_published: v })
  node.is_published = v
  ElMessage.success(v ? '已发布' : '已取消发布')
}
function openDeleteNode(node) {
  deleteTarget.value = node
  deleteVisible.value = true
}

async function confirmDeleteNode() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteCatalog(deleteTarget.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    await loadTree()
  } finally {
    deleting.value = false
  }
}

// ---- 授课计划识别 ----
const planVisible = ref(false)
const planLoading = ref(false)
const planTree = ref([])
const importing = ref(false)
const planMode = ref('upload')
const planFile = ref(null)
const manualPlanChapters = ref([])
const outlineFileAccept = '.ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv'
const planChapterTree = computed(() => onlyTopLevel(normalizeCatalogTree(planTree.value)))
const canSavePlan = computed(() => buildPlanTreeForSave().length > 0)
const validManualChapterCount = computed(() => manualPlanChapters.value.filter((chapter) => chapter.title.trim()).length)

function newPlanChapter(title = '') {
  return { uid: `${Date.now()}-${Math.random()}`, title, children: [] }
}

function openPlanDialog() {
  resetPlanDialog()
  planVisible.value = true
}

function resetPlanDialog() {
  planMode.value = 'upload'
  planFile.value = null
  planTree.value = []
  manualPlanChapters.value = [newPlanChapter()]
}

function addPlanChapter() {
  manualPlanChapters.value.push(newPlanChapter())
}

function removePlanChapter(index) {
  manualPlanChapters.value.splice(index, 1)
  if (!manualPlanChapters.value.length) addPlanChapter()
}

async function handlePlanUpload(file) {
  planFile.value = file
  planTree.value = []
  planLoading.value = true
  try {
    const res = await previewCatalogFromFile(file)
    const parsedTree = normalizeCatalogTree(res.catalog_tree || [])
    const fallbackTree = parsedTree.length ? parsedTree : chaptersFromPreviewPages(res.pages || [])
    const chapters = onlyTopLevel(fallbackTree)
    planTree.value = fallbackTree
    manualPlanChapters.value = chapters.length
      ? chapters.map((chapter) => newPlanChapter(chapter.title))
      : [newPlanChapter()]
    if (chapters.length) {
      ElMessage.success(`已从文件识别 ${chapters.length} 个章目录`)
    } else {
      ElMessage.warning('未识别到“第1章/第一章”这类章目录，请手动添加或稍后维护')
    }
  } catch (error) {
    manualPlanChapters.value = [newPlanChapter()]
    ElMessage.info('文件解析失败，可手动添加章目录或稍后维护')
  } finally {
    planLoading.value = false
  }
  return false
}

async function importPlan() {
  const chapters = buildPlanTreeForSave()
  if (!chapters.length) return ElMessage.warning('未找到可保存的章目录')
  importing.value = true
  try {
    for (let order = 0; order < chapters.length; order += 1) {
      const chapter = chapters[order]
        await createCatalog({ course: courseId, parent: null, title: chapter.title, order, is_published: true })
    }
    ElMessage.success('目录已保存')
    planVisible.value = false
    loadTree()
  } finally {
    importing.value = false
  }
}

function buildPlanTreeForSave() {
  if (planMode.value === 'manual') return onlyTopLevel(normalizeCatalogTree(manualPlanChapters.value))
  return planChapterTree.value
}

function normalizeCatalogTree(nodes) {
  return (nodes || [])
    .map((node) => ({
      title: String(node.title || '').trim(),
      children: normalizeCatalogTree(node.children || []),
    }))
    .filter((node) => node.title)
}

function chaptersFromPreviewPages(pages) {
  const chapters = []
  const seen = new Set()
  ;(pages || []).forEach((page) => {
    const text = `${page?.title || ''}\n${page?.body || ''}`
    text.split(/\n|；|;/).forEach((line) => {
      const title = extractChapterTitle(line)
      const key = title.replace(/\s+/g, '')
      if (title && !seen.has(key)) {
        chapters.push({ title, children: [] })
        seen.add(key)
      }
    })
  })
  return chapters
}

function onlyTopLevel(nodes) {
  const chapters = []
  const seen = new Set()

  function collect(list) {
    ;(list || []).forEach((node) => {
      const title = String(node.title || '').trim()
      if (isChapterTitle(title) && !seen.has(title)) {
        seen.add(title)
        chapters.push({ title, children: [] })
      }
      collect(node.children || [])
    })
  }

  collect(nodes)
  return chapters
}

function isChapterTitle(title) {
  const text = String(title || '').trim()
  return /^(第\s*[一二三四五六七八九十百千万\d]+\s*(章|讲|单元)|\d+\s*[、.．]\s*(?!\d)|[一二三四五六七八九十]+\s*[、.．]|chapter\s+\d+)/i.test(text)
}

function extractChapterTitle(line) {
  const text = String(line || '').replace(/\s+/g, ' ').trim()
  const match = text.match(/(第\s*[一二三四五六七八九十百千万\d]+\s*(?:章|讲|单元)\s*[^；;\n]*)/i)
  if (!match) return ''
  return match[1]
    .split(/\s+(?:\d+\.\d+|第\s*[一二三四五六七八九十百千万\d]+\s*节|实验\d*|习题|作业|学时|课时|考核|教材|参考|备注)/)[0]
    .replace(/^(第)\s+([一二三四五六七八九十百千万\d]+)\s+(章|讲|单元)/, '$1$2$3')
    .replace(/^(第[一二三四五六七八九十百千万\d]+(?:章|讲|单元))(?=\S)/, '$1 ')
    .trim()
}

// ---- AI 讲解稿 ----
const scriptLoading = ref(null)
async function openScript(node) {
  if (scriptCount(videoMap[String(node.id)])) {
    await openVideo(node, 'script')
    return
  }
  await genScript(node)
}

async function genScript(node) {
  scriptLoading.value = node.id
  try {
    const res = await generateScript(node.id)
    ElMessage.success(res.cached
      ? `「${node.title}」已有 ${res.pages} 页讲解稿`
      : `已为「${node.title}」生成 ${res.pages} 页讲解稿`)
    await loadVideos()
    await openVideo(node, 'script')
  } finally {
    scriptLoading.value = null
  }
}

// ---- AI 配音 ----
const audioLoading = ref(null)
async function genAudio(node) {
  audioLoading.value = node.id
  ElMessage.info('正在逐页合成配音，请稍候…')
  try {
    const res = await generateAudio(node.id)
    if (res.audio_pages === res.total_pages) {
      ElMessage.success(`已为「${node.title}」完成 ${res.audio_pages}/${res.total_pages} 页配音`)
    } else {
      ElMessage.warning(`已完成 ${res.audio_pages}/${res.total_pages} 页配音，未完成页可再次点击「配音」继续补齐`)
    }
    await loadVideos()
    await openVideo(node, 'player')
  } finally {
    audioLoading.value = null
  }
}

// ---- 讲解稿 / 配音查看 ----
const videoVisible = ref(false)
const videoLoading = ref(false)
const videoNode = ref(null)
const videoDetail = ref(null)
const videoMode = ref('player')
const scriptSaving = ref(null)
const pageScriptLoading = ref(null)
const scriptOriginals = ref({})
const videoScripts = computed(() => (
  Array.isArray(videoDetail.value?.scripts) ? videoDetail.value.scripts : []
))
const currentAudioCount = computed(() => audioCount(videoDetail.value))
const playerPages = computed(() => {
  const ppt = videoNode.value ? pptMap[String(videoNode.value.id)] : null
  return Array.isArray(ppt?.parsed_pages) ? ppt.parsed_pages : []
})
const playerPageIndex = ref(0)
const playerAutoPlay = ref(false)
const playerAudioRef = ref(null)
const playerCurrent = ref(0)
const playerDuration = ref(0)
const playerProgress = computed(() =>
  playerDuration.value ? (playerCurrent.value / playerDuration.value) * 100 : 0,
)

let progressRaf = 0
function onPlayerPlay() {
  playerAutoPlay.value = true
  cancelAnimationFrame(progressRaf)
  const step = () => {
    const a = playerAudioRef.value
    if (a && !a.paused) {
      playerCurrent.value = a.currentTime || 0
      progressRaf = requestAnimationFrame(step) // 逐帧更新，进度条平滑
    }
  }
  progressRaf = requestAnimationFrame(step)
}
function onPlayerTimeUpdate() {
  const a = playerAudioRef.value
  if (a && a.paused) playerCurrent.value = a.currentTime || 0
}
function onPlayerLoadedMeta() {
  const a = playerAudioRef.value
  if (a) playerDuration.value = a.duration || 0
}
function seekPlayer(event) {
  const a = playerAudioRef.value
  if (!a || !playerDuration.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
  a.currentTime = ratio * playerDuration.value
  playerCurrent.value = a.currentTime
}
function fmtTime(sec) {
  if (!sec || Number.isNaN(sec)) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

// ---- 讲解页内嵌 AI 助教（知识库 RAG 问答 + 相关资料）----
const dockVisible = ref(false)
const dockTab = ref('chat')
const chatMessages = ref([])
const chatInput = ref('')
const chatImage = ref('')
const chatFileRef = ref(null)
const chatSessionId = crypto.randomUUID()

function onPickChatImage(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) return ElMessage.warning('请选择图片文件')
  if (file.size > 6 * 1024 * 1024) return ElMessage.warning('图片不能超过 6MB')
  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      const max = 1024
      let { width, height } = img
      if (Math.max(width, height) > max) {
        const scale = max / Math.max(width, height)
        width = Math.round(width * scale)
        height = Math.round(height * scale)
      }
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      canvas.getContext('2d').drawImage(img, 0, 0, width, height)
      // PNG 保留原格式（避免透明背景转 JPEG 变黑），其余统一 JPEG 压缩
      chatImage.value = file.type === 'image/png'
        ? canvas.toDataURL('image/png')
        : canvas.toDataURL('image/jpeg', 0.85)
    }
    img.src = reader.result
  }
  reader.readAsDataURL(file)
}
const chatLoading = ref(false)
const chatScrollRef = ref(null)
const scriptDockListRef = ref(null)
const chatSuggests = ['这一章的重点是什么？', '帮我总结一下核心概念', '这部分内容有什么例子？']
const chatTextareaRef = ref(null)
const materials = ref([])
const materialsLoading = ref(false)
let materialsLoaded = false

function toggleDock() {
  if (dockVisible.value && dockTab.value !== 'script') {
    dockVisible.value = false
    return
  }
  dockTab.value = 'chat'
  dockVisible.value = true
}

function toggleScriptDock() {
  if (dockVisible.value && dockTab.value === 'script') {
    dockVisible.value = false
    return
  }
  dockTab.value = 'script'
  dockVisible.value = true
  scrollCurrentScriptIntoView()
}

function switchDockTab(tab) {
  dockTab.value = tab
  if (tab === 'materials') ensureMaterials()
  if (tab === 'script') scrollCurrentScriptIntoView()
}

function selectScriptPage(item) {
  const index = playerPages.value.findIndex((page) => page.page === item.page)
  if (index < 0) return
  stopPlayer()
  playerPageIndex.value = index
}

function scrollCurrentScriptIntoView() {
  nextTick(() => {
    const page = currentPlayerPage.value?.page
    if (page == null) return
    scriptDockListRef.value
      ?.querySelector(`[data-script-page="${page}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

async function ensureMaterials(force = false) {
  if (materialsLoaded && !force) return
  materialsLoading.value = true
  try {
    const data = await listMaterials({ course: courseId })
    materials.value = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : []
    materialsLoaded = true
  } catch {
    materials.value = []
  } finally {
    materialsLoading.value = false
  }
}

function autoGrowInput() {
  const el = chatTextareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  // 仅当内容超过最大高度时才显示滚动条，避免单行时也冒出滑动条
  el.style.overflowY = el.scrollHeight > 120 ? 'auto' : 'hidden'
}

async function askChat(preset) {
  const q = (preset ?? chatInput.value).trim()
  const img = chatImage.value
  if ((!q && !img) || chatLoading.value) return
  const text = q || '请描述并解读这张图片'
  chatMessages.value.push({ role: 'user', content: text, image: img, imageOnly: !q })
  chatInput.value = ''
  chatImage.value = ''
  nextTick(autoGrowInput)
  chatLoading.value = true
  // 预置一条空的助教消息，流式往里追加
  const idx = chatMessages.value.push({ role: 'assistant', content: '', cited: [], streaming: true }) - 1
  scrollChatToBottom()
  try {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/qa-records/ask-stream/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ course: courseId, catalog: videoNode.value?.id, question: text, session: chatSessionId, ...(img ? { image: img } : {}) }),
    })
    if (!resp.ok || !resp.body) throw new Error('bad response')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? '' // 末尾可能是不完整帧，留到下一轮
      for (const frame of frames) {
        const line = frame.trim()
        if (!line.startsWith('data:')) continue
        const jsonStr = line.slice(5).trim()
        if (!jsonStr) continue
        let evt
        try { evt = JSON.parse(jsonStr) } catch { continue }
        if (evt.type === 'meta') {
          chatMessages.value[idx].cited = evt.cited || []
        } else if (evt.type === 'delta') {
          if (chatLoading.value) chatLoading.value = false
          chatMessages.value[idx].content += evt.text || ''
          scrollChatToBottom()
        } else if (evt.type === 'error') {
          chatMessages.value[idx].content += `\n[出错] ${evt.message || '生成失败'}`
        }
      }
    }
    chatMessages.value[idx].streaming = false
  } catch {
    chatMessages.value[idx].content = chatMessages.value[idx].content || '抱歉，回答失败，请稍后重试。'
    chatMessages.value[idx].streaming = false
  } finally {
    chatLoading.value = false
    scrollChatToBottom()
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatScrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function fileUrl(file) {
  return file || '#'
}

const currentPlayerPage = computed(() => playerPages.value[playerPageIndex.value] || null)
const currentPlayerScript = computed(() => {
  const page = currentPlayerPage.value?.page
  return videoScripts.value.find((item) => item.page === page) || null
})

async function openVideo(node, mode = 'player') {
  stopPlayer()
  videoNode.value = node
  videoMode.value = mode
  videoVisible.value = true
  playerPageIndex.value = 0
  videoDetail.value = videoMap[String(node.id)] || null
  videoLoading.value = true
  try {
    const data = await listVideos({ catalog: node.id })
    const list = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : []
    videoDetail.value = list[0] || null
    if (videoDetail.value) setVideoMapItem(videoDetail.value)
    resetScriptOriginals()
  } finally {
    videoLoading.value = false
  }
}

function resetScriptOriginals() {
  scriptOriginals.value = Object.fromEntries(
    videoScripts.value.map((item) => [String(item.page), item.script || '']),
  )
}

function isScriptDirty(item) {
  return (item?.script || '') !== (scriptOriginals.value[String(item?.page)] || '')
}

async function saveScriptItem(item) {
  if (!videoDetail.value?.id || !item?.page) return
  scriptSaving.value = item.page
  try {
    const updated = await updateVideoScript(videoDetail.value.id, {
      page: item.page,
      script: item.script,
    })
    videoDetail.value = updated
    setVideoMapItem(updated)
    resetScriptOriginals()
    ElMessage.success('讲稿已保存，该页需要重新配音')
  } finally {
    scriptSaving.value = null
  }
}

async function regenerateScriptPage(item) {
  if (!videoDetail.value?.id || !item?.page) return
  if (item.audio_url) {
    try {
      await ElMessageBox.confirm(
        '重新生成只会覆盖当前页讲稿，并清空当前页配音。确认继续吗？',
        `重新生成第 ${item.page} 页`,
        {
          type: 'warning',
          confirmButtonText: '重新生成本页',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  }
  pageScriptLoading.value = item.page
  try {
    const updated = await regenerateVideoScriptPage(videoDetail.value.id, { page: item.page })
    videoDetail.value = updated
    setVideoMapItem(updated)
    resetScriptOriginals()
    ElMessage.success(`第 ${item.page} 页讲稿已重新生成，该页需要重新配音`)
  } finally {
    pageScriptLoading.value = null
  }
}

function togglePlayer() {
  if (playerAutoPlay.value) {
    stopPlayer()
    return
  }
  playerAutoPlay.value = true
  if (!currentPlayerScript.value?.audio_url) {
    const next = findNextAudioPage(playerPageIndex.value - 1)
    if (next >= 0) playerPageIndex.value = next
  }
  setTimeout(() => playerAudioRef.value?.play?.(), 0)
}

function onPlayerAudioEnded() {
  if (!playerAutoPlay.value) return
  const next = findNextAudioPage(playerPageIndex.value)
  if (next >= 0) {
    playerPageIndex.value = next
  } else {
    playerAutoPlay.value = false
  }
}

function onPlayerAudioPause() {
  const audio = playerAudioRef.value
  if (audio && audio.currentTime < audio.duration) playerAutoPlay.value = false
}

function stopPlayer() {
  playerAutoPlay.value = false
  playerAudioRef.value?.pause?.()
}

function prevPlayerPage() {
  if (playerPageIndex.value <= 0) return
  playerPageIndex.value -= 1
}

function nextPlayerPage() {
  if (playerPageIndex.value >= playerPages.value.length - 1) return
  playerPageIndex.value += 1
}

function findNextAudioPage(startIndex) {
  for (let i = startIndex + 1; i < playerPages.value.length; i += 1) {
    const page = playerPages.value[i]?.page
    const script = videoScripts.value.find((item) => item.page === page)
    if (script?.audio_url) return i
  }
  return -1
}

watch(videoVisible, (visible) => {
  if (!visible) stopPlayer()
})

watch(videoMode, (mode) => {
  if (mode !== 'player') stopPlayer()
})

watch(playerPageIndex, () => {
  if (dockVisible.value && dockTab.value === 'script') scrollCurrentScriptIntoView()
})

// ---- 课件 ----
const pptVisible = ref(false)
const uploading = ref(false)
const currentNode = ref(null)
function openPpt(node) {
  currentNode.value = node
  pptVisible.value = true
}
async function handlePptUpload(file) {
  if (!isPptFile(file)) {
    ElMessage.warning('课件只支持上传 PPT / PPTX 文件')
    return false
  }
  uploading.value = true
  try {
    const created = await uploadPpt({ course: courseId, catalog: currentNode.value.id, file })
    const currentCatalogId = currentNode.value.id
    const savedPpt = created && typeof created === 'object'
      ? created
      : { catalog: currentCatalogId, file_name: file.name, parsed_pages: [] }
    setPptMapItem(savedPpt, currentCatalogId)
    ElMessage.success((savedPpt.parsed_pages || []).length ? '上传并解析完成' : '已上传，但未解析到页面文本')
    loadPpts({ reset: false }).catch(() => {})
  } finally {
    uploading.value = false
  }
  return false
}

function isPptFile(file) {
  return /\.(ppt|pptx)$/i.test(file?.name || '')
}

function setPptMapItem(ppt, fallbackCatalogId = null) {
  if (!ppt) return
  const catalogId = ppt.catalog ?? fallbackCatalogId
  if (!catalogId) return
  const parsedPages = Array.isArray(ppt.parsed_pages) ? ppt.parsed_pages : []
  const key = String(catalogId)
  const current = pptMap[key]
  const nextActive = Boolean(ppt.is_active)
  const currentActive = Boolean(current?.is_active)
  const nextVersion = Number(ppt.version || 0)
  const currentVersion = Number(current?.version || 0)
  const nextId = Number(ppt.id || 0)
  const currentId = Number(current?.id || 0)
  if (currentActive && !nextActive) return
  if (!currentActive && nextActive) {
    // Active uploads should replace inactive fallbacks regardless of version drift.
  } else if (current && nextVersion < currentVersion) return
  else if (current && nextVersion === currentVersion && nextId < currentId) return

  pptMap[key] = {
    id: ppt.id,
    file_name: ppt.file_name || '已上传课件',
    pages: parsedPages.length,
    parsed_pages: parsedPages,
    parse_status: ppt.parse_status,
    version: nextVersion,
    is_active: nextActive,
  }
}

onMounted(() => { loadCourseName(); loadTree() })
</script>

<style scoped>
.catalog-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  padding: 0 0 12px;
  margin-bottom: 12px;
}

.catalog-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.catalog-action-btn {
  height: 40px;
  padding: 0 18px;
  border-radius: 12px;
  font-weight: 720;
  letter-spacing: 0;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease;
}

.catalog-action-secondary {
  color: #334155;
  border-color: rgba(148, 163, 184, 0.32);
  background: rgba(255, 255, 255, 0.84);
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.catalog-action-secondary :deep(.el-icon) {
  color: #3b82f6;
}

.catalog-action-secondary:hover,
.catalog-action-secondary:focus {
  color: #1d4ed8;
  border-color: rgba(96, 165, 250, 0.58);
  background: #fff;
  box-shadow:
    0 10px 22px rgba(37, 99, 235, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 1);
  transform: translateY(-1px);
}

.catalog-action-primary {
  border: 0;
  background: #3b82f6;
  box-shadow:
    0 4px 10px rgba(37, 99, 235, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.catalog-action-primary:hover,
.catalog-action-primary:focus {
  background: #2563eb;
  box-shadow:
    0 12px 26px rgba(37, 99, 235, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.26);
  transform: translateY(-1px);
}

.catalog-action-btn:active {
  transform: translateY(1px);
  box-shadow:
    0 4px 10px rgba(37, 99, 235, 0.12),
    inset 0 2px 4px rgba(15, 23, 42, 0.1);
}

.data-card {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.data-card :deep(.el-card__body) {
  padding: 0;
}

.catalog-tree {
  background: transparent;
}

/* 章节行入场交错浮现（el-tree 深层节点） */
.catalog-tree :deep(.el-tree-node) {
  animation: row-enter 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.catalog-tree :deep(.el-tree-node:nth-child(1)) { animation-delay: 0.02s; }
.catalog-tree :deep(.el-tree-node:nth-child(2)) { animation-delay: 0.06s; }
.catalog-tree :deep(.el-tree-node:nth-child(3)) { animation-delay: 0.1s; }
.catalog-tree :deep(.el-tree-node:nth-child(4)) { animation-delay: 0.14s; }
.catalog-tree :deep(.el-tree-node:nth-child(5)) { animation-delay: 0.18s; }
.catalog-tree :deep(.el-tree-node:nth-child(6)) { animation-delay: 0.22s; }
.catalog-tree :deep(.el-tree-node:nth-child(7)) { animation-delay: 0.26s; }
.catalog-tree :deep(.el-tree-node:nth-child(8)) { animation-delay: 0.3s; }
.catalog-tree :deep(.el-tree-node:nth-child(9)) { animation-delay: 0.34s; }
.catalog-tree :deep(.el-tree-node:nth-child(n + 10)) { animation-delay: 0.38s; }

.tree-node {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
  min-width: 0;
  padding: 13px 18px;
  border: 1px solid var(--gray-100);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.tree-node:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.2);
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
}

.tree-node.is-child {
  margin-left: 6px;
}

.node-main {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.node-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 0 1 auto;
}

.node-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  transition: transform 0.18s ease;
}

.tree-node:hover .node-icon-wrap {
  transform: scale(1.04);
}

.tree-node.is-child .node-icon-wrap {
  width: 30px;
  height: 30px;
  background: var(--el-fill-color-light);
}

.node-icon {
  font-size: 17px;
}

.node-copy {
  display: block;
  min-width: 0;
}

.node-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.node-title {
  max-width: 420px;
  font-size: 15px;
  font-weight: 650;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
  flex: 0 0 auto;
}

.node-tags :deep(.el-tag) {
  border-radius: 999px;
}

.node-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.node-action-group,
.node-manage-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.node-action-group {
  padding: 4px 6px;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(31, 45, 61, 0.02);
}

.node-action-btn,
.node-manage-btn {
  height: 30px;
  padding: 0 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--el-color-primary);
  font-weight: 600;
}

.node-action-btn:hover,
.node-manage-btn:hover {
  background: #fff;
  color: var(--el-color-primary);
  box-shadow: var(--shadow-xs);
}

.node-manage-group {
  min-width: 116px;
  padding-left: 10px;
  border-left: 1px solid var(--el-border-color-lighter);
  justify-content: flex-end;
  gap: 10px;
}

.node-manage-group :deep(.el-switch) {
  margin-right: 8px;
}

.node-icon-btn {
  width: 28px;
  height: 28px;
  color: var(--el-text-color-regular);
  font-size: 15px;
}

.tree-node:not(:hover) .node-icon-btn {
  opacity: 0.7;
}

:deep(.el-tree-node__content) {
  height: auto;
  min-height: 0;
  padding: 0;
  margin-bottom: 12px;
  border-radius: 16px;
  background: transparent;
}

:deep(.el-tree-node__content:hover) {
  background: transparent;
}

/* 隐藏展开箭头占位，让章节卡片与知识库/题库列表一样铺满整宽 */
:deep(.el-tree-node__expand-icon) {
  display: none;
}

:deep(.el-tree-node__content) {
  padding-left: 0 !important;
}

:deep(.el-tree-node__children) {
  margin-left: 10px;
  border-left: 1px dashed var(--el-border-color-lighter);
}

html.dark .tree-node {
  background: #1e293b;
  border-color: #334155;
}

@media (max-width: 1280px) {
  .tree-node {
    align-items: flex-start;
    grid-template-columns: 1fr;
  }

  .node-main {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .node-tags {
    padding-left: 46px;
  }

  .node-actions {
    width: 100%;
    justify-content: space-between;
  }
}

@media (max-width: 768px) {
  .catalog-toolbar,
  .catalog-toolbar-actions,
  .node-actions,
  .node-action-group,
  .node-manage-group {
    align-items: stretch;
    flex-direction: column;
  }

  .node-left {
    min-width: 0;
  }

  .node-action-group,
  .node-manage-group {
    width: 100%;
  }
}

:global(.chapter-form-dialog.el-dialog),
:global(.catalog-dialog.el-dialog) {
  max-width: calc(100vw - 32px);
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(191, 219, 254, 0.72);
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

:global(.chapter-form-dialog.el-dialog .el-dialog__header),
:global(.catalog-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}

:global(.chapter-form-dialog.el-dialog .el-dialog__body),
:global(.catalog-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}

:global(.chapter-form-dialog.el-dialog .el-dialog__footer),
:global(.catalog-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}

.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 84px;
  padding: 20px 24px 18px;
  border-bottom: 1px solid #edf2f8;
  background: linear-gradient(135deg, #f8fbff 0%, #ffffff 62%);
}

.creation-dialog-icon {
  width: 46px;
  height: 46px;
  display: grid;
  flex: 0 0 46px;
  place-items: center;
  border: 1px solid #dbeafe;
  border-radius: 15px;
  color: #2563eb;
  font-size: 21px;
  background: #eff6ff;
}

.chapter-create-icon {
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.08);
}

.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}

.creation-dialog-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 850;
  line-height: 1.25;
}

.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.creation-dialog-close {
  width: 34px;
  height: 34px;
  color: #94a3b8;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.creation-dialog-close:hover {
  color: #2563eb;
  background: #eff6ff;
}

.chapter-creation-form {
  padding: 22px 24px 26px;
}

.chapter-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 142px;
  gap: 2px 16px;
}

.form-span-full {
  grid-column: 1 / -1;
}

.creation-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.creation-form :deep(.el-form-item__label) {
  height: auto;
  padding: 0 0 8px;
  color: #475569;
  font-size: 13px;
  font-weight: 780;
  line-height: 1.2;
}

.creation-form :deep(.el-input__wrapper),
.creation-form :deep(.el-input-number) {
  width: 100%;
}

.creation-form :deep(.el-input__wrapper),
.creation-form :deep(.el-input-number .el-input__wrapper) {
  min-height: 44px;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
  transition: box-shadow 0.2s ease, background-color 0.2s ease;
}

.creation-form :deep(.el-input__wrapper:hover),
.creation-form :deep(.el-input-number .el-input__wrapper:hover) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}

.creation-form :deep(.el-input__wrapper.is-focus),
.creation-form :deep(.el-input-number .el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.creation-form :deep(.el-textarea__inner) {
  min-height: 104px !important;
  padding: 12px 13px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  background: #f8fbff;
  box-shadow: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.creation-form :deep(.el-textarea__inner:hover) {
  border-color: #bfdbfe;
  background: #fff;
}

.creation-form :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.catalog-body {
  padding: 22px 24px 24px;
}

.mode-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.mode-option {
  height: 46px;
  border: 1px solid #dbe5f2;
  border-radius: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  background: #f8fbff;
  color: #64748b;
  font-size: 14px;
  font-weight: 780;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.mode-option:hover {
  border-color: #bfdbfe;
  background: #fff;
  color: #2563eb;
}

.mode-option.active {
  border-color: transparent;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #fff;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.22);
  transform: translateY(-1px);
}

.catalog-section {
  min-height: 252px;
}

.course-upload :deep(.el-upload) {
  width: 100%;
}

.course-upload :deep(.el-upload-dragger) {
  width: 100%;
  height: 196px;
  border: 1px dashed #bfdbfe;
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}

.course-upload :deep(.el-upload-dragger:hover) {
  border-color: #3b82f6;
  background: #fff;
  box-shadow: 0 14px 32px rgba(37, 99, 235, 0.1);
}

.upload-inner {
  display: grid;
  justify-items: center;
  gap: 8px;
}

.upload-mark {
  width: 52px;
  height: 52px;
  border-radius: 15px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #60a5fa 0%, #2563eb 100%);
  color: #fff;
  font-size: 26px;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.2);
}

.upload-main {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.upload-sub {
  font-size: 13px;
  color: #94a3b8;
}

.file-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 12px 13px;
  border: 1px solid #e2ebf7;
  border-radius: 14px;
  background: #f8fbff;
}

.file-icon {
  width: 36px;
  height: 36px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: #fff;
  color: #2563eb;
  flex-shrink: 0;
}

.file-meta {
  min-width: 0;
  flex: 1;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #0f172a;
  font-weight: 760;
}

.file-note {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.outline-preview {
  margin-top: 14px;
  padding: 14px 16px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #e2ebf7;
  border-radius: 14px;
  background: #fff;
}

.outline-alert {
  margin-top: 14px;
}

.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 800;
  color: #0f172a;
}

.outline-preview ul {
  margin: 0;
  padding-left: 20px;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}

.manual-panel {
  padding: 16px;
  border: 1px solid #e2ebf7;
  border-radius: 16px;
  background: rgba(248, 251, 255, 0.82);
}

.manual-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.manual-title {
  font-size: 15px;
  font-weight: 820;
  color: #0f172a;
}

.manual-list {
  display: grid;
  gap: 10px;
}

.manual-chapter {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 34px;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid #e2ebf7;
  border-radius: 13px;
  background: #fff;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.manual-chapter:focus-within {
  border-color: #bfdbfe;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.09);
}

.manual-index {
  width: 30px;
  height: 30px;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #2563eb;
  background: #eff6ff;
  font-weight: 820;
  font-size: 13px;
}

.manual-input :deep(.el-input__wrapper) {
  min-height: 40px;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px transparent;
}

.manual-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 0 0 1px #3b82f6, 0 0 0 3px rgba(59, 130, 246, 0.12);
  background: #fff;
}

.manual-delete {
  color: var(--el-color-danger);
}

.manual-add-card {
  width: 100%;
  height: 44px;
  margin-top: 12px;
  border: 1px dashed #bfdbfe;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 780;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease, transform 0.18s ease;
}

.manual-add-card:hover {
  border-color: #3b82f6;
  background: #fff;
  transform: translateY(-1px);
}

.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 18px;
  border-top: 1px solid #edf2f8;
  background: #f8fbff;
}

.creation-dialog-footer :deep(.el-button) {
  height: 38px;
  padding: 0 17px;
  border-radius: 11px;
  font-weight: 760;
}

.creation-dialog-footer :deep(.el-button--primary) {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border-color: transparent;
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.24);
}

@media (max-width: 640px) {
  .creation-dialog-header {
    min-height: 76px;
    padding: 17px 18px 15px;
  }

  .creation-dialog-title {
    font-size: 18px;
  }

  .chapter-creation-form,
  .catalog-body {
    padding-right: 18px;
    padding-left: 18px;
  }

  .chapter-form-grid {
    grid-template-columns: 1fr;
  }

  .creation-dialog-footer {
    padding: 14px 18px 18px;
  }
}

.ppt-dialog-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ppt-head-icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: 20px;
}

.ppt-head-copy {
  min-width: 0;
}

.ppt-head-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.25;
}

.ppt-head-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ppt-current {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 14px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.ppt-file-icon {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--el-color-primary);
  background: #fff;
}

.ppt-file-info {
  min-width: 0;
  flex: 1;
}

.ppt-file-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ppt-file-meta {
  margin-top: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.ppt-empty-state {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 22px 16px 18px;
  margin-bottom: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: linear-gradient(180deg, #fff 0%, var(--el-fill-color-lighter) 100%);
  text-align: center;
}

.ppt-empty-icon {
  width: 52px;
  height: 52px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: 24px;
}

.ppt-empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.ppt-empty-desc {
  max-width: 340px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.ppt-upload {
  width: 100%;
}

.ppt-upload :deep(.el-upload) {
  width: 100%;
}

.ppt-upload :deep(.el-upload-dragger) {
  width: 100%;
  height: 176px;
  border-radius: 8px;
  border: 1px dashed var(--el-color-primary-light-3);
  background: linear-gradient(180deg, #ffffff 0%, var(--el-color-primary-light-9) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.ppt-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--el-color-primary);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}

.ppt-upload-inner {
  display: grid;
  justify-items: center;
  gap: 8px;
}

.ppt-upload-icon {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
  font-size: 24px;
  box-shadow: var(--shadow-sm);
}

.ppt-upload-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.ppt-upload-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.ppt-page-preview {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.ppt-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.ppt-page-list {
  display: grid;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
}

.ppt-page-item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.ppt-page-index {
  font-size: 12px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.ppt-page-content {
  min-width: 0;
}

.ppt-page-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ppt-page-body {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.ppt-tip {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.full-lecture-page {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  background:
    radial-gradient(circle at 12% 12%, rgba(191, 219, 254, 0.58), transparent 34rem),
    radial-gradient(circle at 88% 16%, rgba(219, 234, 254, 0.5), transparent 30rem),
    linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  color: #0f172a;
}

.full-lecture-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  padding: 12px 26px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.1);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.07);
  backdrop-filter: blur(20px) saturate(1.14);
}

.full-lecture-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.full-lecture-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.9);
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.18),
    0 4px 10px rgba(37, 99, 235, 0.06);
  font-size: 16px;
}

.full-lecture-title-copy {
  min-width: 0;
}

.full-lecture-title-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.full-lecture-kicker {
  max-width: 34vw;
  overflow: hidden;
  padding: 3px 9px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  background: rgba(248, 251, 255, 0.9);
}

.full-lecture-title-copy h1 {
  margin: 0;
  font-size: 21px;
  line-height: 1.2;
  color: #0f172a;
  white-space: nowrap;
}

.full-lecture-title-copy p {
  max-width: 56vw;
  margin: 4px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #64748b;
}

.full-lecture-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.full-lecture-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
  color: #64748b;
  font-size: 12px;
}

.full-lecture-stats strong {
  color: #2563eb;
  font-size: 16px;
}

.full-lecture-soft-btn {
  height: 36px;
  padding: 0 15px;
  border-radius: 999px;
  border-color: rgba(37, 99, 235, 0.12);
  background: rgba(255, 255, 255, 0.78);
  box-shadow:
    0 10px 24px rgba(37, 99, 235, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  font-weight: 700;
}

.full-lecture-body {
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.full-lecture-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 22px 28px 26px;
}

.full-lecture-soft-btn.is-active {
  color: #2563eb;
  border-color: rgba(37, 99, 235, 0.4);
  background: linear-gradient(180deg, #eff6ff, #dbeafe);
}

/* ---- 右侧 AI 助教 Dock ---- */
.full-lecture-dock {
  flex: 0 0 clamp(420px, 32vw, 560px);
  width: clamp(420px, 32vw, 560px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin: 22px 22px 26px 0;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow:
    0 28px 70px rgba(37, 99, 235, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(20px) saturate(1.1);
  overflow: hidden;
}

.dock-slide-enter-active,
.dock-slide-leave-active {
  transition: transform 0.32s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.28s ease;
}
.dock-slide-enter-from,
.dock-slide-leave-to {
  transform: translateX(24px);
  opacity: 0;
}

.dock-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 12px 10px;
  border-bottom: 1px solid rgba(37, 99, 235, 0.08);
}

.dock-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
}
.dock-tab:hover {
  color: #2563eb;
  background: rgba(37, 99, 235, 0.06);
}
.dock-tab.active {
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.28);
}
.dock-close {
  margin-left: auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.14);
  color: #64748b;
  cursor: pointer;
  transition: all 0.18s ease;
}
.dock-close:hover {
  background: rgba(239, 68, 68, 0.14);
  color: #ef4444;
}

/* 对话区 */
.dock-chat {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat-empty {
  margin: auto 0;
  text-align: center;
  padding: 12px 8px;
  animation: chat-empty-in 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes chat-empty-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-empty-hero {
  position: relative;
  width: 76px;
  height: 76px;
  margin: 4px auto 16px;
  display: grid;
  place-items: center;
}
.chat-empty-glow {
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.42), rgba(59, 130, 246, 0) 70%);
  filter: blur(6px);
  animation: chat-glow-pulse 2.8s ease-in-out infinite;
}
@keyframes chat-glow-pulse {
  0%, 100% { transform: scale(0.9); opacity: 0.65; }
  50% { transform: scale(1.12); opacity: 1; }
}
.chat-empty-icon {
  position: relative;
  width: 62px;
  height: 62px;
  display: grid;
  place-items: center;
  border-radius: 20px;
  font-size: 29px;
  color: #fff;
  background: linear-gradient(140deg, #60a5fa 0%, #3b82f6 45%, #2563eb 100%);
  box-shadow:
    0 16px 32px rgba(37, 99, 235, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
  animation: chat-icon-float 3.4s ease-in-out infinite;
}
@keyframes chat-icon-float {
  0%, 100% { transform: translateY(0) rotate(-2deg); }
  50% { transform: translateY(-6px) rotate(2deg); }
}
.chat-empty-title {
  margin: 0;
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0.01em;
  background: linear-gradient(120deg, #1e3a8a, #2563eb 55%, #60a5fa);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.chat-empty-desc {
  max-width: 300px;
  margin: 8px auto 20px;
  font-size: 13px;
  line-height: 1.7;
  color: #64748b;
}
.chat-suggests {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
}
.chat-suggests-label {
  align-self: stretch;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 2px 2px;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #94a3b8;
}
.chat-suggests-label::before,
.chat-suggests-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.3), transparent);
}
.chat-suggest {
  max-width: 100%;
  padding: 9px 16px;
  border: 1px solid rgba(37, 99, 235, 0.14);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  color: #334155;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.chat-suggest:hover {
  border-color: rgba(37, 99, 235, 0.4);
  background: #eff6ff;
  transform: translateY(-1px);
}

.chat-row {
  display: flex;
  align-items: flex-start;
}
.chat-row.user {
  justify-content: flex-end;
}
.chat-bubble {
  max-width: 100%;
  padding: 2px 0;
  font-size: 13.5px;
  line-height: 1.75;
}
.chat-row.assistant .chat-bubble {
  color: #1e293b;
}
.chat-row.user .chat-bubble {
  max-width: 86%;
  padding: 9px 14px;
  border-radius: 16px;
  border-bottom-right-radius: 6px;
  background: #f1f3f5;
  color: #334155;
}
.chat-row.user .chat-bubble.bare {
  padding: 0;
  background: transparent;
}
.chat-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* Markdown 渲染样式（助教回答） */
.chat-md {
  white-space: normal;
}
.chat-md :first-child { margin-top: 0; }
.chat-md :last-child { margin-bottom: 0; }
.chat-md p { margin: 0 0 8px; }
.chat-md h1,
.chat-md h2,
.chat-md h3,
.chat-md h4 {
  margin: 12px 0 6px;
  font-size: 14.5px;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.4;
}
.chat-md h1 { font-size: 16px; }
.chat-md h2 { font-size: 15px; }
.chat-md ul,
.chat-md ol {
  margin: 4px 0 8px;
  padding-left: 20px;
}
.chat-md li { margin: 3px 0; }
.chat-md li > p { margin: 0; }
.chat-md strong { font-weight: 800; color: #1d4ed8; }
.chat-md em { color: #475569; }
.chat-md a { color: #2563eb; text-decoration: underline; }
.chat-md code {
  padding: 1px 5px;
  border-radius: 5px;
  background: rgba(37, 99, 235, 0.09);
  color: #be123c;
  font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
  font-size: 12.5px;
}
.chat-md pre {
  margin: 8px 0;
  padding: 11px 13px;
  border-radius: 10px;
  background: #0f172a;
  overflow-x: auto;
}
.chat-md pre code {
  padding: 0;
  background: transparent;
  color: #e2e8f0;
  font-size: 12.5px;
  line-height: 1.6;
}
.chat-md blockquote {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid rgba(37, 99, 235, 0.4);
  background: rgba(37, 99, 235, 0.05);
  color: #475569;
  border-radius: 0 8px 8px 0;
}
.chat-md hr {
  margin: 12px 0;
  border: 0;
  border-top: 1px dashed rgba(37, 99, 235, 0.2);
}
.chat-md table {
  width: 100%;
  margin: 8px 0;
  border-collapse: collapse;
  font-size: 12.5px;
}
.chat-md th,
.chat-md td {
  padding: 6px 9px;
  border: 1px solid rgba(37, 99, 235, 0.14);
  text-align: left;
}
.chat-md th { background: rgba(37, 99, 235, 0.06); font-weight: 700; }
.chat-cited {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(37, 99, 235, 0.18);
}
.chat-cited-title {
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: #2563eb;
  margin-bottom: 7px;
}
.chat-cited-item {
  margin-bottom: 8px;
  padding: 7px 9px;
  border-radius: 9px;
  background: rgba(37, 99, 235, 0.05);
}
.chat-cited-item:last-child {
  margin-bottom: 0;
}
.chat-cited-name {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}
.chat-cited-snippet {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #94a3b8;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.chat-typing {
  display: inline-flex;
  gap: 4px;
  padding: 3px 0;
}
.chat-typing i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #93c5fd;
  animation: chat-blink 1.2s infinite ease-in-out;
}
.chat-typing i:nth-child(2) { animation-delay: 0.2s; }
.chat-typing i:nth-child(3) { animation-delay: 0.4s; }
@keyframes chat-blink {
  0%, 80%, 100% { opacity: 0.3; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

.chat-caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  border-radius: 1px;
  animation: chat-caret-blink 0.9s steps(1) infinite;
}
@keyframes chat-caret-blink {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}

.chat-input {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0 14px 14px;
  padding: 10px 10px 8px 14px;
  border: 1px solid #dbe5f2;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(37, 99, 235, 0.1);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.chat-input:focus-within {
  border-color: var(--primary-500, #3b82f6);
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.14), 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.chat-textarea {
  flex: 1;
  min-height: 24px;
  max-height: 120px;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: #1e293b;
  font-size: 14px;
  line-height: 1.6;
  font-family: inherit;
  resize: none;
  outline: none;
  overflow-y: hidden;
}
.chat-textarea::placeholder {
  color: #94a3b8;
}
.chat-input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.chat-tool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid rgba(96, 165, 250, 0.35);
  border-radius: 999px;
  background: rgba(248, 251, 255, 0.9);
  color: #2563eb;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.chat-tool:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}
.chat-image-preview {
  position: relative;
  width: 64px;
  margin-bottom: 6px;
}
.chat-image-preview img {
  width: 64px;
  height: 64px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  object-fit: cover;
}
.preview-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: #475569;
  color: #fff;
  cursor: pointer;
}
.preview-remove:hover {
  background: #ef4444;
}
.q-image {
  display: block;
  max-width: 220px;
  max-height: 150px;
  margin-bottom: 6px;
  border-radius: 10px;
}
.chat-send {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3);
  transition: transform 0.15s ease, box-shadow 0.2s ease;
}
.chat-send:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.04);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.42);
}
.chat-send:active:not(:disabled) {
  transform: scale(0.94);
}
.chat-send:disabled {
  background: #cbd5e1;
  box-shadow: none;
  cursor: not-allowed;
}

/* 资料区 */
.dock-materials {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dock-loading {
  margin: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
}
.dock-empty {
  margin: auto;
}
.material-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.8);
  text-decoration: none;
  transition: all 0.18s ease;
}
.material-item:hover {
  border-color: rgba(37, 99, 235, 0.34);
  background: #f6faff;
  transform: translateY(-2px);
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.12);
}
.material-icon {
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  font-size: 19px;
  color: #2563eb;
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.material-icon.ext-pdf { color: #ef4444; background: linear-gradient(145deg, #fef2f2, #fff); }
.material-icon.ext-ppt { color: #ea580c; background: linear-gradient(145deg, #fff7ed, #fff); }
.material-icon.ext-word { color: #2563eb; background: linear-gradient(145deg, #eff6ff, #fff); }
.material-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.material-name {
  font-size: 13.5px;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.material-meta {
  font-size: 11.5px;
  color: #94a3b8;
}
.material-open {
  flex: 0 0 auto;
  color: #cbd5e1;
  font-size: 16px;
  transition: transform 0.18s ease, color 0.18s ease;
}
.material-item:hover .material-open {
  color: #2563eb;
  transform: translateX(2px);
}

/* 讲解稿区 */
.dock-scripts {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
}

.dock-script-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 4px 14px;
}

.dock-script-summary > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dock-script-summary strong {
  color: #172033;
  font-size: 16px;
}

.dock-script-summary span {
  color: #94a3b8;
  font-size: 12px;
}

.dock-script-progress {
  flex: 0 0 auto;
  min-width: 58px;
  padding: 7px 10px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb !important;
  text-align: center;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.dock-script-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 4px 6px;
  scroll-behavior: smooth;
}

.dock-script-item {
  width: 100%;
  padding: 13px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  color: #475569;
  text-align: left;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.dock-script-item:hover {
  border-color: rgba(37, 99, 235, 0.28);
  background: #f8fbff;
  transform: translateY(-1px);
}

.dock-script-item.active {
  border-color: rgba(37, 99, 235, 0.4);
  background: linear-gradient(145deg, #eff6ff, #ffffff);
  box-shadow:
    0 12px 26px rgba(37, 99, 235, 0.12),
    inset 3px 0 0 #3b82f6;
}

.dock-script-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  color: #1e293b;
  font-size: 13px;
  font-weight: 800;
}

.dock-script-audio {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
}

.dock-script-audio.ready {
  background: #ecfdf3;
  color: #22a447;
}

.dock-script-text {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.75;
}

.dock-script-item.active .dock-script-text {
  display: block;
  overflow: visible;
  color: #334155;
}

.full-lecture-stage-card {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 14px;
}

.full-lecture-stage {
  position: relative;
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 18px;
  overflow: hidden;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow:
    0 28px 70px rgba(37, 99, 235, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(16px) saturate(1.08);
}

.full-lecture-image {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  object-fit: contain;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.08);
}

/* 统一自定义播放器：上一页 | 播放 | 时间 | 进度条 | 时间 | 下一页 */
.full-lecture-control-panel {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 13px 20px;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(244, 248, 255, 0.9));
  box-shadow:
    0 16px 40px rgba(37, 99, 235, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
}

.lecture-nav-btn {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 10px 18px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.lecture-nav-btn:not(.is-disabled):hover {
  transform: translateY(-1px);
}

.lecture-play-btn {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  font-size: 17px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
  transition: transform 0.15s ease, box-shadow 0.2s ease;
}

.lecture-play-btn:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.42);
}

.lecture-play-btn:active {
  transform: scale(0.94);
}

.lecture-play-btn:disabled {
  background: #cbd5e1;
  box-shadow: none;
  cursor: not-allowed;
}

.lecture-time {
  flex: 0 0 auto;
  min-width: 44px;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.lecture-progress {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.12);
  cursor: pointer;
  position: relative;
  transition: height 0.15s ease;
}

.lecture-progress:hover {
  height: 9px;
}

.lecture-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  position: relative;
}

.lecture-progress-fill::after {
  content: "";
  position: absolute;
  right: -5px;
  top: 50%;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #2563eb;
  box-shadow: 0 1px 4px rgba(37, 99, 235, 0.35);
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.lecture-progress:hover .lecture-progress-fill::after {
  opacity: 1;
  transform: translateY(-50%) scale(1.15);
}

.lecture-no-audio {
  flex: 1;
  color: #94a3b8;
  font-size: 14px;
  text-align: center;
}

.full-lecture-empty {
  height: 100%;
  min-height: 0;
  display: grid;
  place-items: center;
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 28px 70px rgba(37, 99, 235, 0.14);
}

.script-dialog-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.script-head-icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: 20px;
}

.script-head-copy {
  min-width: 0;
}

.script-head-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.25;
}

.script-head-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-dialog-body {
  min-height: 240px;
}

.script-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.script-summary :deep(.el-segmented) {
  margin-left: auto;
}

.script-stat {
  display: flex;
  align-items: baseline;
  gap: 5px;
  min-width: 96px;
}

.script-stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.script-stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.script-alert {
  margin-bottom: 12px;
}

.ppt-player {
  display: grid;
  gap: 12px;
  margin-bottom: 12px;
}

.ppt-stage {
  position: relative;
  min-height: 300px;
  padding: 18px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: linear-gradient(135deg, #ffffff 0%, #eef5ff 100%);
  box-shadow: inset 0 0 0 1px rgba(64, 158, 255, 0.06);
}

.ppt-stage-count {
  position: absolute;
  top: 14px;
  right: 18px;
  z-index: 1;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.86);
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.ppt-stage-image {
  display: block;
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  border-radius: 6px;
  background: #fff;
}

.ppt-stage-title {
  font-size: 26px;
  font-weight: 800;
  line-height: 1.35;
  color: var(--el-text-color-primary);
  text-align: center;
  margin: 22px 0 24px;
}

.ppt-stage-body {
  white-space: pre-wrap;
  line-height: 1.9;
  color: var(--el-text-color-regular);
  font-size: 16px;
}

.ppt-player-script {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.ppt-player-script-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.ppt-player-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

:global(.script-dialog.el-dialog.is-fullscreen) {
  width: 100vw;
  height: 100vh;
  margin: 0;
  border-radius: 0;
  background:
    radial-gradient(circle at 18% 18%, rgba(191, 219, 254, 0.36), transparent 30rem),
    linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

:global(.script-dialog.el-dialog.is-fullscreen .el-dialog__header) {
  padding: 18px 28px 14px;
  margin: 0;
  border-bottom: 1px solid rgba(37, 99, 235, 0.1);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px) saturate(1.12);
}

:global(.script-dialog.el-dialog.is-fullscreen .el-dialog__body) {
  flex: 1;
  min-height: 0;
  padding: 18px 28px 24px;
  overflow: hidden;
}

:global(.script-dialog.el-dialog.is-fullscreen .script-dialog-body) {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

:global(.script-dialog.el-dialog.is-fullscreen .script-summary) {
  flex-shrink: 0;
  margin-bottom: 0;
  padding: 10px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow:
    0 12px 28px rgba(37, 99, 235, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.84);
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-player) {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto auto;
  gap: 14px;
  margin-bottom: 0;
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-stage) {
  min-height: 0;
  height: 100%;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow:
    0 22px 58px rgba(37, 99, 235, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
  overflow: hidden;
  display: grid;
  place-items: center;
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-stage-image) {
  width: 100%;
  height: 100%;
  max-height: none;
  object-fit: contain;
  border-radius: 12px;
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-stage-title) {
  align-self: end;
  margin: 0 0 14px;
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-stage-body) {
  align-self: start;
  max-width: min(980px, 84vw);
  font-size: 18px;
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-player-script) {
  flex-shrink: 0;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow:
    0 12px 28px rgba(37, 99, 235, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
}

:global(.script-dialog.el-dialog.is-fullscreen .ppt-player-bar) {
  flex-shrink: 0;
  padding: 0 0 2px;
}

@media (max-width: 900px) {
  :global(.script-dialog.el-dialog.is-fullscreen .el-dialog__body) {
    padding: 12px 14px 18px;
  }

  :global(.script-dialog.el-dialog.is-fullscreen .script-summary) {
    flex-wrap: wrap;
  }
}

.script-muted {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.player-empty {
  padding: 24px 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.script-video {
  margin-bottom: 12px;
  border-radius: 8px;
  overflow: hidden;
  background: #000;
}

.script-video video {
  display: block;
  width: 100%;
  max-height: 320px;
}

.script-list {
  display: grid;
  gap: 10px;
  max-height: 460px;
  overflow-y: auto;
  padding-right: 4px;
}

.script-item {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.script-item.is-playing {
  border-color: var(--el-color-primary-light-3);
  background: var(--el-color-primary-light-9);
}

.script-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.script-page-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.script-page {
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.script-text {
  font-size: 14px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
}

.script-editor {
  width: 100%;
}

.script-editor :deep(.el-textarea__inner) {
  line-height: 1.8;
  color: var(--el-text-color-regular);
  resize: vertical;
}

.script-edit-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}

.script-dirty-tip {
  margin-right: auto;
  color: var(--el-color-warning);
  font-size: 12px;
}

.script-audio {
  width: 100%;
  height: 36px;
  margin-top: 10px;
}
</style>
