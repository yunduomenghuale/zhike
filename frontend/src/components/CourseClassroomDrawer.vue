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
          <b>{{ room.name }}</b>
          <span class="room-code">{{ room.code }}</span>
        </div>
        <div class="room-meta">
          {{ room.student_count }} 人 · {{ room.status_display }}
        </div>
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
        只能添加，不能在这里移除（避免误操作影响在用班级）；需要移除请联系管理员在班级管理中调整。
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
import { ElMessage } from 'element-plus'
import { getClassroomOptions, linkClassrooms } from '@/api/course'

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
.room-main b {
  font-size: 14px;
  color: #1f2733;
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
