<template>
  <div class="page-container">
    <div class="course-board">
      <TableSkeleton v-if="loading" :cols="3" />
      <div v-else class="course-grid animate-list">
        <button type="button" class="course-add-card" @click="openDialog()">
          <span class="add-icon">
            <el-icon><Plus /></el-icon>
          </span>
          <span class="add-main">新建课程</span>
          <span class="add-sub">填写课程信息，并继续新增目录</span>
        </button>

        <article
          v-for="row in rows"
          :key="row.id"
          class="course-card"
          @click="goCatalog(row)"
        >
          <div class="course-icon">
            <el-icon><Collection /></el-icon>
          </div>

          <div class="course-main">
            <div class="course-name">{{ row.name }}</div>
            <div class="course-term">{{ row.term || '未设置学期' }}</div>
            <div class="course-meta">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="light" round>
                {{ row.status_display }}
              </el-tag>
              <span class="course-intro">{{ row.intro || '暂无课程简介' }}</span>
            </div>
          </div>

          <div class="course-actions" @click.stop>
            <el-button text circle :icon="Edit" @click="openDialog(row)" />
            <el-button text circle type="danger" :icon="Delete" title="删除课程" @click="openDelete(row)" />
          </div>
          <el-icon class="course-arrow"><ArrowRightBold /></el-icon>
        </article>
      </div>

      <el-pagination
        v-if="total > pageSize"
        class="pager"
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="(p) => { page = p; load() }"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      width="620px"
      align-center
      :show-close="false"
      class="course-form-dialog"
    >
      <template #header>
        <div class="creation-dialog-header">
          <span class="creation-dialog-icon course-create-icon">
            <el-icon><Collection /></el-icon>
          </span>
          <div class="creation-dialog-heading">
            <div class="creation-dialog-title">{{ editing ? '编辑课程' : '新建课程' }}</div>
            <div class="creation-dialog-subtitle">课程基础信息</div>
          </div>
          <el-button text circle class="creation-dialog-close" :icon="Close" @click="dialogVisible = false" />
        </div>
      </template>

      <el-form :model="form" label-position="top" class="creation-form course-creation-form">
        <div class="creation-form-grid">
          <el-form-item label="课程名称" class="form-span-full">
            <el-input v-model="form.name" placeholder="请输入课程名称" />
          </el-form-item>
          <el-form-item label="学期">
            <el-input v-model="form.term" placeholder="如 2026 春" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="form.status" style="width: 100%">
              <el-option label="启用" value="active" />
              <el-option label="停用" value="inactive" />
              <el-option label="归档" value="archived" />
            </el-select>
          </el-form-item>
          <el-form-item label="课程简介" class="form-span-full form-intro-item">
            <el-input v-model="form.intro" type="textarea" :rows="4" resize="none" placeholder="请输入课程简介" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="creation-dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveCourse">
            {{ editing ? '保存' : '保存并新增目录' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="catalogVisible"
      width="760px"
      align-center
      class="catalog-dialog"
      :show-close="true"
    >
      <template #header>
        <div class="catalog-header">
          <div class="course-badge">
            <el-icon><Collection /></el-icon>
          </div>
          <div class="catalog-heading">
            <div class="catalog-title">新增课程目录</div>
            <div class="catalog-course-name">{{ catalogCourse?.name }}</div>
          </div>
        </div>
      </template>

      <div class="catalog-body">
        <div class="mode-switch" role="tablist">
          <button
            type="button"
            class="mode-option"
            :class="{ active: outlineMode === 'upload' }"
            @click="outlineMode = 'upload'"
          >
            <el-icon><UploadFilled /></el-icon>
            <span>上传授课文件</span>
          </button>
          <button
            type="button"
            class="mode-option"
            :class="{ active: outlineMode === 'manual' }"
            @click="outlineMode = 'manual'"
          >
            <el-icon><EditPen /></el-icon>
            <span>手动添加</span>
          </button>
          <button
            type="button"
            class="mode-option"
            :class="{ active: outlineMode === 'empty' }"
            @click="outlineMode = 'empty'"
          >
            <el-icon><Collection /></el-icon>
            <span>稍后维护</span>
          </button>
        </div>

        <section v-if="outlineMode === 'upload'" class="catalog-section">
          <el-upload
            drag
            :show-file-list="false"
            :before-upload="handleOutlineUpload"
            :accept="fileAccept"
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

          <div v-if="outlineFile" class="file-status">
            <div class="file-icon">
              <el-icon><Document /></el-icon>
            </div>
            <div class="file-meta">
              <div class="file-name">{{ outlineFile.name }}</div>
              <div class="file-note">
                {{
                  chapterOutlineTree.length
                    ? `已识别 ${chapterOutlineTree.length} 个章目录`
                    : '未识别到章目录，可手动添加或稍后维护'
                }}
              </div>
            </div>
            <el-tag
              size="small"
              :type="chapterOutlineTree.length ? 'success' : 'warning'"
              effect="light"
            >
              {{ chapterOutlineTree.length ? '已解析' : '需调整' }}
            </el-tag>
          </div>

          <div v-if="chapterOutlineTree.length" class="outline-preview">
            <div class="preview-head">
              <span>目录预览</span>
              <el-button link type="primary" :icon="EditPen" @click="outlineMode = 'manual'">
                调整
              </el-button>
            </div>
            <ul>
              <li v-for="(chapter, i) in chapterOutlineTree" :key="`${chapter.title}-${i}`">
                {{ chapter.title }}
              </li>
            </ul>
          </div>

          <el-alert
            v-else-if="outlineFile && !previewing"
            class="outline-alert"
            type="warning"
            show-icon
            :closable="false"
            title="只会保存“第1章 / 第一章”这类章目录，1.1 等小节不会进入初始目录"
          />
        </section>

        <section v-else-if="outlineMode === 'manual'" class="catalog-section">
          <div
            v-for="(chapter, chapterIndex) in manualChapters"
            :key="chapter.uid"
            class="manual-chapter"
          >
            <div class="manual-row">
              <el-input v-model="chapter.title" placeholder="章标题，如 第1章 Java语言概述" />
              <el-button :icon="Delete" type="danger" plain @click="removeChapter(chapterIndex)" />
            </div>
          </div>
          <el-button :icon="Plus" type="primary" plain @click="addChapter">添加章</el-button>
        </section>

        <section v-else class="empty-section">
          <div class="empty-icon">
            <el-icon><Collection /></el-icon>
          </div>
          <div class="empty-title">目录可在课程详情中继续维护</div>
        </section>
      </div>

      <template #footer>
        <div class="catalog-footer">
          <el-button @click="finishCatalogLater">稍后维护</el-button>
          <el-button
            type="primary"
            :disabled="outlineMode === 'empty'"
            :loading="catalogSaving || previewing"
            @click="saveCatalogSetup"
          >
            保存目录
          </el-button>
        </div>
      </template>
    </el-dialog>

    <DeleteConfirmDialog
      v-model="deleteVisible"
      title="删除课程"
      :item-name="deleteTarget?.name"
      description="删除后，与该课程关联的目录和教学内容将无法继续访问，此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRightBold,
  Collection,
  Delete,
  Document,
  Edit,
  EditPen,
  Close,
  Plus,
  UploadFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import TableSkeleton from '@/components/TableSkeleton.vue'
import DeleteConfirmDialog from '@/components/DeleteConfirmDialog.vue'
import {
  listCourses,
  createCourse,
  updateCourse,
  deleteCourse,
  createCatalog,
  previewCatalogFromFile,
  uploadPpt,
} from '@/api/course'

const route = useRoute()
const router = useRouter()
const rows = ref([])
const loading = ref(false)
const search = ref(String(route.query.search || ''))
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)
const form = reactive({ name: '', term: '', intro: '', status: 'active' })

const catalogVisible = ref(false)
const catalogSaving = ref(false)
const previewing = ref(false)
const catalogCourse = ref(null)
const fileAccept = '.ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv'
const outlineMode = ref('upload')
const outlineFile = ref(null)
const outlineTree = ref([])
const chapterOutlineTree = computed(() => onlyTopLevel(normalizeTree(outlineTree.value)))
const manualChapters = ref([])

async function load() {
  loading.value = true
  try {
    const data = await listCourses({ search: search.value, page: page.value })
    rows.value = data.results ?? data
    total.value = data.total ?? rows.value.length
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  editing.value = row || null
  Object.assign(form, row ? { ...row } : { name: '', term: '', intro: '', status: 'active' })
  dialogVisible.value = true
}

function goCatalog(row) {
  router.push({ name: 'course-chapters', params: { id: row.id } })
}

async function saveCourse() {
  if (!form.name.trim()) return ElMessage.warning('请填写课程名称')
  saving.value = true
  try {
    const payload = {
      name: form.name,
      term: form.term,
      intro: form.intro,
      status: form.status,
    }

    if (editing.value) {
      await updateCourse(editing.value.id, payload)
      ElMessage.success('已更新')
      dialogVisible.value = false
      load()
      return
    }

    const course = await createCourse(payload)
    ElMessage.success('课程已创建，请继续新增目录')
    dialogVisible.value = false
    catalogCourse.value = course
    resetOutline()
    catalogVisible.value = true
    load()
  } finally {
    saving.value = false
  }
}

function resetOutline() {
  outlineMode.value = 'upload'
  outlineFile.value = null
  outlineTree.value = []
  manualChapters.value = [newChapter()]
}

function newChapter(title = '') {
  return { uid: crypto.randomUUID(), title, children: [] }
}

function addChapter() {
  manualChapters.value.push(newChapter())
}

function removeChapter(index) {
  manualChapters.value.splice(index, 1)
  if (!manualChapters.value.length) addChapter()
}

async function handleOutlineUpload(file) {
  outlineFile.value = file
  outlineTree.value = []
  previewing.value = true
  try {
    const res = await previewCatalogFromFile(file)
    const parsedTree = normalizeTree(res.catalog_tree || [])
    const fallbackTree = parsedTree.length ? parsedTree : chaptersFromPreviewPages(res.pages || [])
    const chapters = onlyTopLevel(fallbackTree)
    outlineTree.value = fallbackTree
    manualChapters.value = cloneToManual(chapters)
    if (chapters.length) {
      ElMessage.success(`已从文件识别 ${chapters.length} 个章目录`)
    } else {
      ElMessage.warning('未识别到“第1章/第一章”这类章目录，请手动添加或稍后维护')
    }
  } catch (error) {
    manualChapters.value = [newChapter()]
    ElMessage.info('文件解析失败，可手动添加章目录或稍后维护')
  } finally {
    previewing.value = false
  }
  return false
}

async function saveCatalogSetup() {
  if (!catalogCourse.value) return
  const tree = buildTreeForSave()
  if (!tree.length) return ElMessage.warning('未找到可保存的章目录，请保留“第1章/第一章”这类标题')

  catalogSaving.value = true
  try {
    const firstCatalogId = await importCatalogTree(catalogCourse.value.id, tree)
    const shouldUploadCourseware = outlineFile.value && firstCatalogId && isPptFile(outlineFile.value)
    if (shouldUploadCourseware) {
      await uploadPpt({
        course: catalogCourse.value.id,
        catalog: firstCatalogId,
        file: outlineFile.value,
      })
    }
    ElMessage.success(shouldUploadCourseware ? '目录和 PPT 课件已保存' : '目录已保存')
    catalogVisible.value = false
    router.push({ name: 'course-chapters', params: { id: catalogCourse.value.id } })
  } finally {
    catalogSaving.value = false
  }
}

function finishCatalogLater() {
  catalogVisible.value = false
}

function buildTreeForSave() {
  if (outlineMode.value === 'empty') return []
  if (outlineMode.value === 'manual') return onlyTopLevel(normalizeTree(manualChapters.value))
  if (outlineTree.value.length) return chapterOutlineTree.value
  return []
}

async function importCatalogTree(courseId, tree) {
  let firstCatalogId = null
  for (let i = 0; i < tree.length; i += 1) {
    const chapter = tree[i]
    const createdChapter = await createCatalog({
      course: courseId,
      parent: null,
      title: chapter.title,
      order: i,
      is_published: false,
    })
    if (!firstCatalogId) firstCatalogId = createdChapter.id

    for (let j = 0; j < (chapter.children || []).length; j += 1) {
      const section = chapter.children[j]
      await createCatalog({
        course: courseId,
        parent: createdChapter.id,
        title: section.title,
        order: j,
        is_published: false,
      })
    }
  }
  return firstCatalogId
}

function normalizeTree(tree) {
  return (tree || [])
    .map((chapter) => ({
      title: String(chapter.title || '').trim(),
      children: normalizeTree(chapter.children || []),
    }))
    .filter((chapter) => chapter.title)
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

function onlyTopLevel(tree) {
  const chapters = []
  const seen = new Set()

  function collect(nodes) {
    (nodes || []).forEach((node) => {
      const title = String(node.title || '').trim()
      if (isChapterTitle(title) && !seen.has(title)) {
        seen.add(title)
        chapters.push({ title, children: [] })
      }
      collect(node.children || [])
    })
  }

  collect(tree)
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

function isPptFile(file) {
  return /\.(ppt|pptx)$/i.test(file?.name || '')
}

function cloneToManual(tree) {
  const cloned = normalizeTree(tree).map((chapter) => ({
    uid: crypto.randomUUID(),
    title: chapter.title,
    children: [],
  }))
  return cloned.length ? cloned : [newChapter()]
}

function openDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteCourse(deleteTarget.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    deleteTarget.value = null
    await load()
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  resetOutline()
  load()
})

watch(
  () => route.query.search,
  (value) => {
    search.value = String(value || '')
    page.value = 1
    load()
  },
)
</script>

<style scoped>
.course-board {
  display: grid;
  gap: 18px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.course-add-card {
  min-height: 148px;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 8px;
  padding: 20px;
  border: 1px dashed var(--el-color-primary-light-5);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--el-color-primary);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
}

.course-add-card:hover {
  transform: translateY(-2px);
  border-color: var(--el-color-primary);
  background: #fff;
  box-shadow: var(--shadow-md);
}

.add-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: var(--el-color-primary-light-9);
  font-size: 25px;
  transition: transform 0.25s ease, background-color 0.2s ease;
}

.course-add-card:hover .add-icon {
  transform: scale(1.08) rotate(3deg);
  background: var(--primary-50);
}

.add-main {
  font-size: 18px;
  font-weight: 750;
  line-height: 1.25;
}

.add-sub {
  max-width: 220px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.course-card {
  position: relative;
  min-height: 148px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 48px 20px 20px;
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  background: #fff;
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.course-card:hover {
  transform: translateY(-2px);
  border-color: var(--el-color-primary-light-7);
  box-shadow: var(--shadow-md);
}

.course-icon {
  width: 62px;
  height: 62px;
  border-radius: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--primary-600);
  background: var(--primary-50);
  font-size: 30px;
  transition: transform 0.25s ease;
}

.course-card:hover .course-icon {
  transform: scale(1.08) rotate(-3deg);
}

.course-main {
  min-width: 0;
  flex: 1;
  padding-right: 18px;
}

.course-name {
  font-size: 20px;
  font-weight: 750;
  line-height: 1.35;
  color: var(--gray-900);
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.course-term {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  margin-top: 8px;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  min-width: 0;
}

.course-meta :deep(.el-tag) {
  flex-shrink: 0;
}

.course-intro {
  min-width: 0;
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-actions {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 6px;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.course-card:hover .course-actions {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.course-actions :deep(.el-button) {
  width: 28px;
  height: 28px;
  background: rgba(255, 255, 255, 0.86);
}

.course-arrow {
  position: absolute;
  top: 50%;
  right: 20px;
  transform: translateY(-50%) translateX(-4px);
  color: var(--el-text-color-placeholder);
  font-size: 24px;
  opacity: 0.62;
  transition: opacity 0.2s ease, transform 0.2s ease, color 0.2s ease;
}

.course-card:hover .course-arrow {
  opacity: 1;
  color: var(--el-color-primary);
  transform: translateY(-50%) translateX(0);
}

.course-card::after {
  content: "";
  position: absolute;
  inset: auto 18px 0;
  height: 3px;
  border-radius: 999px 999px 0 0;
  background: var(--el-color-primary);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.2s ease;
}

.course-card:hover::after {
  transform: scaleX(1);
}

.course-form-dialog :deep(.el-dialog),
:global(.course-form-dialog.el-dialog) {
  overflow: hidden;
  border: 1px solid rgba(147, 197, 253, 0.45);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.2), 0 0 0 8px rgba(219, 234, 254, 0.18);
}

.course-form-dialog :deep(.el-dialog__header),
:global(.course-form-dialog.el-dialog .el-dialog__header) {
  margin: 0;
  padding: 0;
}

.course-form-dialog :deep(.el-dialog__body),
:global(.course-form-dialog.el-dialog .el-dialog__body) {
  padding: 0;
}

.course-form-dialog :deep(.el-dialog__footer),
:global(.course-form-dialog.el-dialog .el-dialog__footer) {
  padding: 0;
}

.creation-dialog-header {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 86px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.88);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(255, 255, 255, 0.98) 58%);
}

.creation-dialog-icon {
  width: 44px;
  height: 44px;
  display: grid;
  flex: 0 0 44px;
  place-items: center;
  border-radius: 14px;
  color: var(--primary-600);
  font-size: 21px;
}

.course-create-icon {
  background: #eaf2ff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.11);
}

.creation-dialog-heading {
  min-width: 0;
  flex: 1;
}

.creation-dialog-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 760;
  line-height: 1.25;
}

.creation-dialog-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.3;
}

.creation-dialog-close {
  width: 32px;
  height: 32px;
  color: #94a3b8;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.creation-dialog-close:hover {
  color: #475569;
  background: rgba(226, 232, 240, 0.7);
}

.course-creation-form {
  padding: 22px 24px 26px;
}

.creation-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  padding: 0 0 7px;
  color: #475569;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

.creation-form :deep(.el-input__wrapper),
.creation-form :deep(.el-select__wrapper) {
  min-height: 44px;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: inset 0 0 0 1px #dbe5f2;
  transition: box-shadow 0.2s ease, background-color 0.2s ease;
}

.creation-form :deep(.el-input__wrapper:hover),
.creation-form :deep(.el-select__wrapper:hover) {
  background: #fff;
  box-shadow: inset 0 0 0 1px #bfdbfe;
}

.creation-form :deep(.el-input__wrapper.is-focus),
.creation-form :deep(.el-select__wrapper.is-focused) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--primary-500), 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.creation-form :deep(.el-textarea__inner) {
  min-height: 112px !important;
  padding: 12px 13px;
  border: 1px solid #dbe5f2;
  border-radius: 11px;
  background: #f8fbff;
  box-shadow: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.creation-form :deep(.el-textarea__inner:hover) {
  background: #fff;
  border-color: #bfdbfe;
}

.creation-form :deep(.el-textarea__inner:focus) {
  background: #fff;
  border-color: var(--primary-500);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.creation-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 20px;
  border-top: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.8);
}

.creation-dialog-footer :deep(.el-button) {
  height: 40px;
  padding: 0 17px;
  border-radius: 10px;
}

.creation-dialog-footer :deep(.el-button--primary) {
  box-shadow: 0 9px 18px rgba(37, 99, 235, 0.22);
}

@media (max-width: 768px) {
  .course-grid {
    grid-template-columns: 1fr;
  }

  .course-card {
    min-height: 158px;
    padding: 22px 54px 22px 20px;
  }

  .course-add-card {
    min-height: 158px;
  }

  .course-icon {
    width: 64px;
    height: 64px;
    font-size: 30px;
  }

  .course-name {
    font-size: 20px;
  }

  .course-actions {
    top: 12px;
    right: 16px;
  }

  .course-form-dialog :deep(.el-dialog),
  :global(.course-form-dialog.el-dialog) {
    width: calc(100% - 28px) !important;
  }

  .creation-form-grid {
    grid-template-columns: 1fr;
  }

  .form-span-full {
    grid-column: auto;
  }
}

.catalog-dialog :deep(.el-dialog) {
  border-radius: 8px;
}

.catalog-dialog :deep(.el-dialog__header) {
  padding: 22px 26px 16px;
  margin-right: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.catalog-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.catalog-dialog :deep(.el-dialog__footer) {
  padding: 16px 26px 22px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.catalog-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.course-badge {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 18px;
}

.catalog-heading {
  min-width: 0;
}

.catalog-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.25;
}

.catalog-course-name {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-body {
  padding: 22px 26px 20px;
}

.mode-switch {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 4px;
  margin-bottom: 18px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.mode-option {
  height: 42px;
  border: 0;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  background: transparent;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.mode-option.active {
  background: #fff;
  color: var(--el-color-primary);
  box-shadow: var(--shadow-xs);
  font-weight: 600;
}

.catalog-section {
  min-height: 260px;
}

.course-upload :deep(.el-upload) {
  width: 100%;
}

.course-upload :deep(.el-upload-dragger) {
  width: 100%;
  height: 188px;
  border-radius: 8px;
  border: 1px dashed var(--el-color-primary-light-3);
  background: linear-gradient(180deg, #ffffff 0%, var(--el-color-primary-light-9) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}

.course-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--el-color-primary);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}

.upload-inner {
  display: grid;
  justify-items: center;
  gap: 8px;
}

.upload-mark {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
  font-size: 26px;
  box-shadow: var(--shadow-sm);
}

.upload-main {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.upload-sub {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.file-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.file-icon {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
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
  color: var(--el-text-color-primary);
  font-weight: 600;
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
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
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
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.outline-preview ul {
  margin: 0;
  padding-left: 20px;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}

.manual-chapter {
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.manual-row,
.section-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0 24px;
}

.empty-section {
  min-height: 240px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
  font-size: 22px;
}

.empty-title {
  font-size: 14px;
}

.catalog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 768px) {
  .mode-switch {
    grid-template-columns: 1fr;
  }

  .manual-row,
  .section-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>

<style>
.catalog-dialog.el-dialog,
.catalog-dialog .el-dialog {
  border-radius: 8px;
  overflow: hidden;
}

.catalog-dialog.el-dialog .el-dialog__header,
.catalog-dialog .el-dialog__header {
  padding: 22px 26px 16px;
  margin-right: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.catalog-dialog.el-dialog .el-dialog__body,
.catalog-dialog .el-dialog__body {
  padding: 0;
}

.catalog-dialog.el-dialog .el-dialog__footer,
.catalog-dialog .el-dialog__footer {
  padding: 16px 26px 22px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.catalog-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.course-badge {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 18px;
}

.catalog-heading {
  min-width: 0;
}

.catalog-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.25;
}

.catalog-course-name {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-body {
  padding: 22px 26px 20px;
}

.mode-switch {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 4px;
  margin-bottom: 18px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.mode-option {
  height: 42px;
  border: 0;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  background: transparent;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.mode-option.active {
  background: #fff;
  color: var(--el-color-primary);
  box-shadow: var(--shadow-xs);
  font-weight: 600;
}

.catalog-section {
  min-height: 260px;
}

.course-upload .el-upload {
  width: 100%;
}

.course-upload .el-upload-dragger {
  width: 100%;
  height: 188px;
  border-radius: 8px;
  border: 1px dashed var(--el-color-primary-light-3);
  background: linear-gradient(180deg, #ffffff 0%, var(--el-color-primary-light-9) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}

.course-upload .el-upload-dragger:hover {
  border-color: var(--el-color-primary);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08);
}

.upload-inner {
  display: grid;
  justify-items: center;
  gap: 8px;
}

.upload-mark {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
  font-size: 26px;
  box-shadow: var(--shadow-sm);
}

.upload-main {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.upload-sub {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.file-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.file-icon {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--el-color-primary);
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
  color: var(--el-text-color-primary);
  font-weight: 600;
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
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
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
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.outline-preview ul {
  margin: 0;
  padding-left: 20px;
  color: var(--el-text-color-regular);
  line-height: 1.8;
}

.manual-chapter {
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.manual-row,
.section-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0 24px;
}

.empty-section {
  min-height: 240px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
  font-size: 22px;
}

.empty-title {
  font-size: 14px;
}

.catalog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 768px) {
  .mode-switch {
    grid-template-columns: 1fr;
  }

  .manual-row,
  .section-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
