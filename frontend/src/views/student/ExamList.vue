<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">我的考试</div>
        <div class="page-subtitle">查看可参加的考试，进入答题页后请遵守考试规则</div>
      </div>
    </div>

    <el-card shadow="never" class="data-card">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        description="点击「进入考试」后将进入答题页，请遵守考试规则；离开页面、复制粘贴等行为可能被记录。"
        style="margin-bottom: 16px"
      />
      <TableSkeleton v-if="loading" :cols="5" />
      <el-table v-else-if="exams.length" :data="exams" stripe>
        <el-table-column prop="name" label="考试名称" min-width="180" />
        <el-table-column prop="class_name" label="班级" width="150" />
        <el-table-column prop="duration" label="时长(分)" width="90" align="center" />
        <el-table-column prop="total_score" label="总分" width="80" align="center" />
        <el-table-column label="操作" width="150" fixed="right" align="center">
          <template #default="{ row }">
            <el-button type="primary" size="small" :icon="EditPen" @click="enter(row)">进入考试</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无可参加的考试">
        <template #description>
          <div class="empty-text">暂无可参加的考试</div>
          <div class="empty-tip">考试发布后会自动出现在这里</div>
        </template>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { EditPen } from '@element-plus/icons-vue'
import { listExams } from '@/api/exam'

const router = useRouter()
const exams = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await listExams()
    exams.value = data.results ?? data
  } finally {
    loading.value = false
  }
}

function enter(row) {
  router.push(`/student/exams/${row.id}/take`)
}

onMounted(load)
</script>

<style scoped>
.data-card {
  padding: 8px;
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
</style>
