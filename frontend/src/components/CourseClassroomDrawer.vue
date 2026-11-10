<template>
  <el-drawer
    v-model="visible"
    size="480px"
    :with-header="true"
    class="course-classroom-drawer"
  >
    <template #header>
      <div class="drawer-head">
        <div class="drawer-title">授课班级</div>
        <div class="drawer-sub">{{ courseName }} · 学生只在这门课挂过的班里看到它</div>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <div class="section-head">
        已关联 <b>{{ linkedRooms.length }}</b> 个班
      </div>
      <el-empty
        v-if="!loading && !linkedRooms.length"
        description="还没有关联班级：学生目前看不到这门课"
        :image-size="64"
      />
      <div v-for="room in linkedRooms" :key="room.id" class="room-row is-linked">
        <div class="room-main">
          <div class="room-main-text">
            <b>{{ room.name }}</b>
            <span class="room-code">{{ room.code }}</span>
          </div>
          <div class="room-meta">
            {{ room.student_count }} 人 · {{ room.status_display }}
          </div>
        </div>
        <!-- 解除关联暂不开放：影响面是学生的全部学习数据（作业/考试/视频/错题/学情），
             不止实验提交——待影响面提示模型明确后再开放（后端 DELETE /classrooms 已就绪） -->
      </div>

      <div class="section-head second">添加班级</div>
      <el-select
        v-model="selected"
        multiple
        filterable
        :disabled="!unlinkedRooms.length"
        :placeholder="unlinkedRooms.length ? '选择要关联的班级（可多选）' : '所有班级都已关联'"
        class="room-select"
      >
        <el-option
          v-for="room in unlinkedRooms"
          :key="room.id"
          :value="room.id"
          :label="`${room.name}（${room.code}）· ${room.student_count} 人`"
        />
      </el-select>
      <div class="drawer-tip">
        关联后该班学生即可看到本课程；如需移除请联系管理员在班级管理中调整。
      </div>
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="visible = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!selected.length"
          @click="save"
        >
          添加为授课班级
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getClassroomOptions, linkClassrooms, unlinkClassroom } from '@/api/course'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courseId: { type: [Number, String], default: null },
  courseName: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'done'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const loading = ref(false)
const saving = ref(false)
const rooms = ref([])
const selected = ref([])

const linkedRooms = computed(() => rooms.value.filter((room) => room.linked))
const unlinkedRooms = computed(() => rooms.value.filter((room) => !room.linked))

async function load() {
  if (!props.courseId) return
  loading.value = true
  try {
    const data = await getClassroomOptions(props.courseId)
    rooms.value = data.classrooms || []
    selected.value = []
  } catch (error) {
    ElMessage.error(error?.message || '班级列表加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!selected.value.length) return
  saving.value = true
  try {
    const res = await linkClassrooms(props.courseId, selected.value)
    ElMessage.success(res?.message || '已关联')
    await load()
    emit('done')
  } catch (error) {
    ElMessage.error(error?.message || '关联失败')
  } finally {
    saving.value = false
  }
}

// 解除关联：该班已有实验提交时后端返回 require_confirm，弹确认框后二次带 confirm 重发
// 解除关联（UI 暂隐藏）：影响面是学生的全部学习数据，不止实验提交——
// 待影响面提示模型明确后再开放按钮；后端 DELETE /courses/{id}/classrooms/ 已就绪
const unlinking = ref(null)
async function unlink(room) {
  if (unlinking.value) return
  unlinking.value = room.id
  const finish = () => {
    unlinking.value = null
    return load().then(() => emit('done'))
  }
  try {
    await unlinkClassroom(props.courseId, room.id)
    ElMessage.success(`已解除「${room.name}」的关联`)
    await finish()
    return
  } catch (error) {
    // 400 响应体是 { code, message, data: { require_confirm, ... } }——require_confirm 在 data 里
    const respBody = error?.response?.data || error || {}
    const payload = respBody?.data || respBody || {}
    if (!payload.require_confirm) {
      ElMessage.error(payload.message || respBody.message || error?.message || '解除失败')
      unlinking.value = null
      return
    }
    try {
      await ElMessageBox.confirm(
        `${payload.message || '该班级已有实验提交'}。确定解除关联吗？`,
        '解除关联确认',
        { type: 'warning', confirmButtonText: '仍要解除', cancelButtonText: '取消' },
      )
    } catch {
      unlinking.value = null
      return
    }
    try {
      await unlinkClassroom(props.courseId, room.id, true)
      ElMessage.success(`已解除「${room.name}」的关联`)
      await finish()
    } catch (e2) {
      ElMessage.error(e2?.message || '解除失败')
      unlinking.value = null
    }
  }
}

watch(
  () => [props.modelValue, props.courseId],
  ([open]) => {
    if (open) load()
  },
)
</script>

<style scoped>
.drawer-head {
  padding: 2px 0;
}
.drawer-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2733;
}
.drawer-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7785;
}
.drawer-body {
  min-height: 320px;
}
.section-head {
  margin: 4px 0 10px;
  font-size: 13px;
  color: #4a5563;
}
.section-head.second {
  margin-top: 22px;
}
.room-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #e6e9ee;
  border-radius: 8px;
  margin-bottom: 8px;
  background: #fafbfc;
}
.room-row.is-linked {
  border-color: #cfe3d6;
  background: #f6fbf7;
}
.room-main-text b {
  font-size: 14px;
  color: #1f2733;
}
.room-main-text {
  margin-bottom: 2px;
}
.room-code {
  margin-left: 8px;
  font-size: 12px;
  color: #8a94a2;
}
.room-meta {
  font-size: 12px;
  color: #6b7785;
  white-space: nowrap;
}
.room-select {
  width: 100%;
}
.drawer-tip {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #8a94a2;
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
