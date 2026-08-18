<template>
  <view class="page">
    <!-- 添加章节 -->
    <view class="add-bar">
      <input v-model="newChapter" class="input" placeholder="输入章节标题，添加一章" placeholder-class="ph" />
      <button class="primary-btn small" :disabled="adding" @click="addChapter">添加</button>
    </view>

    <view v-if="loading" class="tip">加载中…</view>
    <template v-else>
      <view v-if="!rows.length" class="tip">暂无章节，先添加一章</view>
      <view v-for="row in rows" :key="row.node.id" class="node" :class="{ child: row.isChild }">
        <view class="node-main">
          <view class="node-title">{{ row.node.title }}</view>
          <text class="chip" :class="{ success: row.node.is_published }">
            {{ row.node.is_published ? '已发布' : '未发布' }}
          </text>
        </view>
        <view class="node-ops">
          <text class="op" @click="startRename(row.node)">改名</text>
          <text v-if="!row.isChild" class="op" @click="startAddSection(row.node)">加小节</text>
          <text class="op" @click="togglePublish(row.node)">{{ row.node.is_published ? '下线' : '发布' }}</text>
          <text class="op danger" @click="removeNode(row.node)">删除</text>
        </view>

        <!-- 行内编辑/加小节 -->
        <view v-if="editingId === row.node.id" class="inline-edit">
          <input v-model="editText" class="input" :placeholder="editMode === 'rename' ? '新标题' : '小节标题'" placeholder-class="ph" />
          <button class="primary-btn small" @click="confirmEdit(row.node)">确定</button>
          <button class="ghost-btn small" @click="editingId = null">取消</button>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { listCatalogs, createCatalog, updateCatalog, deleteCatalog } from '@/api/course.js'

const courseId = ref(null)
const tree = ref([])
const rows = ref([])
const loading = ref(false)
const newChapter = ref('')
const adding = ref(false)
const editingId = ref(null)
const editMode = ref('rename') // rename | section
const editText = ref('')

onLoad((q) => {
  courseId.value = Number(q.course) || null
  if (q.name) uni.setNavigationBarTitle({ title: `章节 · ${decodeURIComponent(q.name)}` })
  load()
})

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const data = await listCatalogs({ course: courseId.value, tree: 1 })
    tree.value = data.results ?? data
    const flat = []
    for (const n of tree.value) {
      flat.push({ node: n, isChild: false })
      for (const c of n.children || []) flat.push({ node: c, isChild: true })
    }
    rows.value = flat
  } finally {
    loading.value = false
  }
}

async function addChapter() {
  const title = newChapter.value.trim()
  if (!title) return uni.showToast({ title: '请输入章节标题', icon: 'none' })
  adding.value = true
  try {
    await createCatalog({ course: courseId.value, title, parent: null, order: tree.value.length + 1 })
    newChapter.value = ''
    uni.showToast({ title: '已添加', icon: 'success' })
    load()
  } finally {
    adding.value = false
  }
}

function startRename(node) {
  editingId.value = node.id
  editMode.value = 'rename'
  editText.value = node.title
}

function startAddSection(node) {
  editingId.value = node.id
  editMode.value = 'section'
  editText.value = ''
}

async function confirmEdit(node) {
  const title = editText.value.trim()
  if (!title) return uni.showToast({ title: '请输入标题', icon: 'none' })
  if (editMode.value === 'rename') {
    await updateCatalog(node.id, { title })
  } else {
    await createCatalog({
      course: courseId.value,
      title,
      parent: node.id,
      order: (node.children?.length || 0) + 1,
    })
  }
  editingId.value = null
  uni.showToast({ title: '已保存', icon: 'success' })
  load()
}

async function togglePublish(node) {
  await updateCatalog(node.id, { is_published: !node.is_published })
  uni.showToast({ title: node.is_published ? '已下线' : '已发布', icon: 'none' })
  load()
}

function removeNode(node) {
  uni.showModal({
    title: '删除章节',
    content: `确定删除「${node.title}」吗？${node.isChild ? '' : '其下小节将一并删除。'}`,
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      await deleteCatalog(node.id)
      uni.showToast({ title: '已删除', icon: 'none' })
      load()
    },
  })
}
</script>

<style scoped>
.page { padding: 28rpx; }
.add-bar { display: flex; gap: 14rpx; margin-bottom: 20rpx; }
.add-bar .input { flex: 1; }
.input { height: 76rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; border: 1rpx solid transparent; font-size: 26rpx; box-sizing: border-box; }
.ph { color: #94a3b8; }
.primary-btn { height: 80rpx; line-height: 80rpx; border-radius: 20rpx; background: #2563eb; color: #fff; font-size: 28rpx; font-weight: 600; }
.primary-btn::after { border: none; }
.primary-btn.small { width: auto; height: 76rpx; line-height: 76rpx; padding: 0 28rpx; font-size: 24rpx; flex-shrink: 0; }
.ghost-btn.small { width: auto; height: 76rpx; line-height: 76rpx; padding: 0 24rpx; border-radius: 20rpx; background: #f1f5f9; color: #64748b; font-size: 24rpx; flex-shrink: 0; }
.ghost-btn.small::after { border: none; }
.tip { padding: 80rpx 0; text-align: center; font-size: 26rpx; color: #94a3b8; }
.node { margin-bottom: 16rpx; padding: 24rpx 26rpx; border-radius: 20rpx; background: #fff; border: 1rpx solid #f1f5f9; box-shadow: 0 2rpx 6rpx rgba(15,23,42,0.04); }
.node.child { margin-left: 48rpx; background: #fafbfd; }
.node-main { display: flex; align-items: center; justify-content: space-between; gap: 14rpx; }
.node-title { flex: 1; overflow: hidden; font-size: 28rpx; font-weight: 600; color: #0f172a; text-overflow: ellipsis; white-space: nowrap; }
.chip { flex-shrink: 0; padding: 4rpx 16rpx; border-radius: 999rpx; background: #f1f5f9; color: #94a3b8; font-size: 22rpx; }
.chip.success { background: #ecfdf5; color: #10b981; }
.node-ops { display: flex; gap: 24rpx; margin-top: 14rpx; }
.op { font-size: 24rpx; color: #2563eb; }
.op.danger { color: #ef4444; }
.inline-edit { display: flex; gap: 12rpx; margin-top: 16rpx; }
.inline-edit .input { flex: 1; }
</style>
