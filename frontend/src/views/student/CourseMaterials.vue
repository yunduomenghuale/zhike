<template>
  <div class="page-container materials-page">
    <div v-loading="loading" class="materials-list course-standard-list">
      <article v-for="item in materials" :key="item.id" class="material-row course-standard-row">
        <div class="material-left">
          <div class="file-badge">
            <el-icon><Document /></el-icon>
          </div>
          <div class="material-main">
            <div class="material-title">{{ item.file_name }}</div>
            <div class="material-meta">
              <span>{{ (item.file_type || '文件').toUpperCase() }}</span>
              <span>{{ item.chunk_count || 0 }} 个知识片段</span>
              <span :class="['status-pill', item.parse_status]">{{ item.parse_status_display || item.parse_status }}</span>
              <span :class="['qa-pill', item.qa_open ? 'open' : 'closed']">
                {{ item.qa_open ? '已接入 AI 助教' : '未开放问答' }}
              </span>
            </div>
          </div>
        </div>
        <div v-if="item.file" class="material-actions course-standard-actions">
          <a class="open-btn course-standard-action-btn" :href="item.file" target="_blank" rel="noreferrer">
            查看资料
          </a>
        </div>
      </article>

      <el-empty v-if="!loading && !materials.length" description="暂无课程资料">
        <template #description>
          <div class="empty-title">暂无课程资料</div>
          <div class="empty-tip">老师上传并解析资料后，会显示在这里。</div>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Document } from '@element-plus/icons-vue'
import { listMaterials } from '@/api/knowledge'

const route = useRoute()
const courseId = computed(() => Number(route.params.id) || null)
const loading = ref(false)
const materials = ref([])

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    const data = await listMaterials({ course: courseId.value })
    materials.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

watch(courseId, load)
onMounted(load)
</script>

<style scoped>
.materials-list {
  display: grid;
}

.material-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.material-left {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-badge {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: #2563eb;
  background: #eff6ff;
  font-size: 17px;
}

.material-main {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 12px;
}

.material-title {
  max-width: 420px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.material-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #64748b;
  font-size: 12.5px;
}

.status-pill,
.qa-pill {
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  font-weight: 700;
}

.status-pill.done {
  color: #16a34a;
  background: #f0fdf4;
}

.status-pill.failed {
  color: #ef4444;
  background: #fef2f2;
}

.status-pill.pending,
.status-pill.parsing {
  color: #d97706;
  background: #fff7ed;
}

.qa-pill.open {
  color: #2563eb;
  background: #eff6ff;
}

.qa-pill.closed {
  color: #64748b;
  background: #f1f5f9;
}

.open-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.open-btn:hover {
  background: #fff;
  box-shadow: var(--shadow-xs);
}

.empty-title {
  color: #64748b;
  font-size: 14px;
  margin-bottom: 4px;
}

.empty-tip {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 720px) {
  .material-row {
    align-items: stretch;
    flex-direction: column;
  }

  .material-left {
    align-items: flex-start;
  }

  .material-main {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
