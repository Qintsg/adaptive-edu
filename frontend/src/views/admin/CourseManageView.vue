<template>
  <div class="course-manage-view">
    <n-card class="page-header" shadow="never">
      <div class="header-content">
        <h2>课程管理</h2>
        <n-button type="primary" @click="handleAdd">
          <n-icon>
            <Plus />
          </n-icon>创建课程
        </n-button>
      </div>
    </n-card>

    <n-card v-loading="loading" shadow="hover">
      <div class="filter-bar">
        <n-input v-model="filter.keyword" placeholder="搜索课程" clearable style="width: 200px;"
          @keyup.enter="loadCourses" />
        <n-select v-model="filter.teacherId" placeholder="负责教师" clearable style="width: 150px;" @change="loadCourses">
          <n-option v-for="t in teachers" :key="getTeacherId(t)" :label="getTeacherLabel(t)"
            :value="getTeacherId(t)" />
        </n-select>
        <n-button type="primary" @click="loadCourses">搜索</n-button>
      </div>

      <n-table :data="courses" style="width: 100%;">
        <n-table-column prop="name" label="课程名称" />
        <n-table-column prop="teacherName" label="负责教师" width="120">
          <template #default="{ row }">{{ row.teacherName || '未分配' }}</template>
        </n-table-column>
        <n-table-column prop="studentCount" label="学生数" width="100">
          <template #default="{ row }">{{ row.studentCount ?? 0 }}</template>
        </n-table-column>
        <n-table-column prop="isPublic" label="状态" width="100">
          <template #default="{ row }">
            <n-tag :type="row.isPublic ? 'success' : 'info'">
              {{ row.isPublic ? '已发布' : '草稿' }}
            </n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="createdAt" label="创建时间" width="180" />
        <n-table-column label="操作" width="250">
          <template #default="{ row }">
            <n-button type="primary" link @click="handleEdit(row)">编辑</n-button>
            <n-button type="warning" link @click="handleAssignTeacher(row)">分配教师</n-button>
            <n-button type="danger" link @click="deleteCourse(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无课程数据" />
        </template>
      </n-table>

      <n-pagination class="pagination" layout="total, sizes, prev, pager, next" :total="total"
        v-model:current-page="pagination.page" v-model:page-size="pagination.pageSize" @size-change="loadCourses"
        @current-change="loadCourses" />
    </n-card>

    <!-- 创建/编辑对话框 -->
    <n-dialog v-model="dialogVisible" :title="isEdit ? '编辑课程' : '创建课程'" width="500px">
      <n-form :model="form" label-width="80px">
        <n-form-item label="课程名称">
          <n-input v-model="form.name" />
        </n-form-item>
        <n-form-item label="课程描述">
          <n-input type="textarea" v-model="form.description" />
        </n-form-item>
        <n-form-item label="负责教师">
          <n-select v-model="form.teacherId" placeholder="选择教师" style="width: 100%">
            <n-option v-for="t in teachers" :key="getTeacherId(t)" :label="getTeacherLabel(t)"
              :value="getTeacherId(t)" />
          </n-select>
        </n-form-item>
        <n-form-item label="状态" v-if="isEdit">
          <n-switch v-model="form.isPublic" active-text="发布" inactive-text="草稿" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="dialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitForm">确定</n-button>
      </template>
    </n-dialog>

    <!-- 分配教师对话框 -->
    <n-dialog v-model="assignDialogVisible" title="分配教师" width="400px">
      <n-form>
        <n-form-item label="选择教师">
          <n-select v-model="assignTeacherId" placeholder="选择教师" style="width: 100%">
            <n-option v-for="t in teachers" :key="getTeacherId(t)" :label="getTeacherLabel(t)"
              :value="getTeacherId(t)" />
          </n-select>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="assignDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitAssign">确定</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { appMessage, appDialog } from '@/utils/feedback'
import { Plus } from '@/theme/element-icons'
import { getAllCourses, createCourse, updateCourse, deleteCourse as apiDeleteCourse, assignCourseTeacher } from '@/api/admin/course'
import { getUsers } from '@/api/admin/user'

const loading = ref(false)
const filter = reactive({ keyword: '', teacherId: '' })
const pagination = reactive({ page: 1, pageSize: 10 })
const total = ref(0)
const courses = ref([])
const teachers = ref([])

const dialogVisible = ref(false)
const isEdit = ref(false)
const form = reactive({ id: null, name: '', description: '', teacherId: null, isPublic: true })

const assignDialogVisible = ref(false)
const assignCourseId = ref(null)
const assignTeacherId = ref(null)

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeBoolean = (value, defaultValue = false) => {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const normalizedValue = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'published'].includes(normalizedValue)) return true
    if (['false', '0', 'no', 'draft'].includes(normalizedValue)) return false
  }
  return defaultValue
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const parsedDate = new Date(dateStr)
  return Number.isNaN(parsedDate.getTime()) ? '-' : parsedDate.toLocaleString('zh-CN')
}

const normalizeTeacherSummary = (value, index) => {
  const teacher = value && typeof value === 'object' ? value : {}
  return {
    id: teacher?.['user_id'] ?? teacher?.['id'] ?? index,
    username: normalizeText(teacher?.['username']),
    realName: normalizeText(teacher?.['real_name']),
    displayName: normalizeText(teacher?.['real_name'] ?? teacher?.['username']) || '未命名教师'
  }
}

const normalizeTeacherList = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const rawTeachers = Array.isArray(payload?.['users']) ? payload['users'] : []
  return rawTeachers.map((teacher, index) => normalizeTeacherSummary(teacher, index))
}

const normalizeCourseSummary = (value, index) => {
  const course = value && typeof value === 'object' ? value : {}
  const studentCount = Number(course?.['student_count'])
  return {
    id: course?.['id'] ?? course?.['course_id'] ?? index,
    name: normalizeText(course?.['name'] ?? course?.['course_name']) || '未命名课程',
    description: normalizeText(course?.['description'] ?? course?.['course_description']),
    teacherId: course?.['teacher_id'] ?? null,
    teacherName: normalizeText(course?.['teacher_name']),
    studentCount: Number.isFinite(studentCount) ? studentCount : 0,
    isPublic: normalizeBoolean(course?.['is_public']),
    createdAt: formatDate(course?.['created_at'])
  }
}

const normalizeCourseListResponse = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const rawCourses = Array.isArray(payload?.['courses']) ? payload['courses'] : []
  const items = rawCourses.map((course, index) => normalizeCourseSummary(course, index))
  const totalCount = Number(payload?.['total'] ?? items.length)
  return {
    items,
    total: Number.isFinite(totalCount) ? totalCount : items.length
  }
}

const buildCoursePayload = () => ({
  course_name: normalizeText(form.name),
  course_description: normalizeText(form.description),
  teacher_id: form.teacherId,
  is_public: form.isPublic
})

const getTeacherId = (teacher) => teacher?.id ?? null
const getTeacherLabel = (teacher) => teacher?.displayName ?? '未命名教师'

const loadTeachers = async () => {
  try {
    const teacherResponse = await getUsers({ role: 'teacher', page: 1, size: 100 })
    teachers.value = normalizeTeacherList(teacherResponse)
  } catch (error) {
    console.error('获取教师列表失败:', error)
    teachers.value = []
  }
}

const loadCourses = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
    }
    if (normalizeText(filter.keyword)) params.keyword = normalizeText(filter.keyword)
    if (filter.teacherId) params.teacher_id = filter.teacherId

    const courseResponse = await getAllCourses(params)
    const courseList = normalizeCourseListResponse(courseResponse)
    courses.value = courseList.items
    total.value = courseList.total
  } catch (error) {
    appMessage.error('获取课程列表失败')
  } finally {
    loading.value = false
  }
}

const handleAdd = () => {
  isEdit.value = false
  form.id = null
  form.name = ''
  form.description = ''
  form.teacherId = null
  form.isPublic = true
  dialogVisible.value = true
}

const handleEdit = (row) => {
  isEdit.value = true
  form.id = row.id
  form.name = row.name
  form.description = row.description
  const matchedTeacher = teachers.value.find((teacher) => {
    const hasSameId = teacher.id !== null && row.teacherId !== null
      && String(teacher.id) === String(row.teacherId)
    return hasSameId || teacher.username === row.teacherName || teacher.realName === row.teacherName
  })
  form.teacherId = matchedTeacher ? getTeacherId(matchedTeacher) : (row.teacherId ?? null)
  form.isPublic = row.isPublic
  dialogVisible.value = true
}

const handleAssignTeacher = (row) => {
  assignCourseId.value = row.id
  assignTeacherId.value = null
  assignDialogVisible.value = true
}

const submitAssign = async () => {
  if (!assignTeacherId.value) return appMessage.warning('请选择教师')
  try {
    await assignCourseTeacher(assignCourseId.value, assignTeacherId.value)
    appMessage.success('分配成功')
    assignDialogVisible.value = false
    await loadCourses()
  } catch (e) {
    appMessage.error('分配失败')
  }
}

const submitForm = async () => {
  const payload = buildCoursePayload()
  if (!payload.course_name) return appMessage.warning('请输入课程名称')
  try {
    if (isEdit.value && form.id) {
      await updateCourse(form.id, payload)
      appMessage.success('更新成功')
    } else {
      await createCourse(payload)
      appMessage.success('创建成功')
    }
    dialogVisible.value = false
    await loadCourses()
  } catch (error) {
    appMessage.error(isEdit.value ? '更新失败' : '创建失败')
  }
}

const deleteCourse = async (course) => {
  try {
    await appDialog.confirm('确定删除该课程吗？', '提示', { type: 'warning' })
    await apiDeleteCourse(course.id)
    appMessage.success('删除成功')
    await loadCourses()
  } catch (error) {
    if (error !== 'cancel') appMessage.error('删除失败')
  }
}

onMounted(() => {
  loadTeachers()
  loadCourses()
})
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h2 {
  margin: 0;
  font-size: 20px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}
</style>
