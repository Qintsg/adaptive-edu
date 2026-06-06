<template>
  <div class="class-manage-view">
    <n-card class="page-header" shadow="never">
      <div class="header-content">
        <h2>班级管理</h2>
        <n-button type="primary" @click="handleAddClass">
          <n-icon>
            <Plus />
          </n-icon>创建班级
        </n-button>
      </div>
    </n-card>

    <n-card v-loading="loading" shadow="hover">
      <div class="filter-bar">
        <n-input v-model="filter.keyword" placeholder="搜索班级" clearable style="width: 200px;"
          @keyup.enter="loadClasses" />
        <n-select v-model="filter.course" placeholder="关联课程" clearable style="width: 180px;" @change="loadClasses">
          <n-option v-for="c in courseOptions" :key="c.id" :label="c.name" :value="c.id" />
        </n-select>
        <n-button type="primary" @click="loadClasses">搜索</n-button>
      </div>

      <n-table :data="classes" style="width: 100%;">
        <n-table-column prop="name" label="班级名称" />
        <n-table-column prop="course" label="关联课程" width="180">
          <template #default="{ row }">{{ row.course || '未关联课程' }}</template>
        </n-table-column>
        <n-table-column prop="teacherName" label="授课教师" width="120">
          <template #default="{ row }">{{ row.teacherName || '-' }}</template>
        </n-table-column>
        <n-table-column prop="studentCount" label="学生数" width="100">
          <template #default="{ row }">{{ row.studentCount ?? 0 }}</template>
        </n-table-column>
        <n-table-column prop="createdAt" label="创建时间" width="180">
          <template #default="{ row }">{{ row.createdAt }}</template>
        </n-table-column>
        <n-table-column label="操作" width="200">
          <template #default="{ row }">
            <n-button type="primary" link @click="viewClassDetail(row)">查看</n-button>
            <n-button type="warning" link @click="handleEditClass(row)">编辑</n-button>
            <n-button type="danger" link @click="deleteClass(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无班级数据" />
        </template>
      </n-table>

      <n-pagination class="pagination" layout="total, sizes, prev, pager, next" :total="total"
        v-model:current-page="pagination.page" v-model:page-size="pagination.pageSize" @size-change="loadClasses"
        @current-change="loadClasses" />
    </n-card>

    <!-- 创建/编辑班级 -->
    <n-dialog v-model="classDialogVisible" :title="isEditClass ? '编辑班级' : '创建班级'" width="480px">
      <n-form :model="classForm" label-width="80px">
        <n-form-item label="班级名称" required>
          <n-input v-model="classForm.name" placeholder="请输入班级名称" />
        </n-form-item>
        <n-form-item label="关联课程">
          <n-select v-model="classForm.courseId" placeholder="选择课程" style="width: 100%;">
            <n-option v-for="c in courseOptions" :key="c.id" :label="c.name" :value="c.id" />
          </n-select>
        </n-form-item>
        <n-form-item label="描述">
          <n-input type="textarea" v-model="classForm.description" placeholder="班级描述（可选）" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="classDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitClassForm">确定</n-button>
      </template>
    </n-dialog>

    <!-- 班级详情 -->
    <n-drawer v-model="detailDrawerVisible" title="班级详情" size="40%">
      <template v-if="selectedClass">
        <n-descriptions :column="1" border>
          <n-descriptions-item label="班级名称">{{ selectedClass.name }}</n-descriptions-item>
          <n-descriptions-item label="关联课程">{{ selectedClass.course }}</n-descriptions-item>
          <n-descriptions-item label="授课教师">{{ selectedClass.teacherName || '-' }}</n-descriptions-item>
          <n-descriptions-item label="学生人数">{{ selectedClass.studentCount ?? 0 }}</n-descriptions-item>
          <n-descriptions-item label="创建时间">{{ selectedClass.createdAt }}</n-descriptions-item>
        </n-descriptions>
      </template>
    </n-drawer>
  </div>
</template>

<script setup>
/**
 * 管理端 - 班级管理视图
 */
import { ref, reactive, onMounted } from 'vue'
import { appMessage, appDialog } from '@/utils/feedback'
import { Plus } from '@/theme/element-icons'
import { getClassList, deleteClass as apiDeleteClass, createClass, updateClass } from '@/api/admin/class'
import { getAllCourses } from '@/api/admin/course'

const loading = ref(false)
const filter = reactive({ keyword: '', course: '' })
const pagination = reactive({ page: 1, pageSize: 10 })
const total = ref(0)
const classes = ref([])
const courseOptions = ref([])

// 创建/编辑对话框
const classDialogVisible = ref(false)
const isEditClass = ref(false)
const classForm = reactive({ id: null, name: '', courseId: null, description: '' })

// 详情抽屉
const detailDrawerVisible = ref(false)
const selectedClass = ref(null)

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const parsedDate = new Date(dateStr)
  return Number.isNaN(parsedDate.getTime()) ? '-' : parsedDate.toLocaleString('zh-CN')
}

const normalizeCourseOption = (value, index) => {
  const course = value && typeof value === 'object' ? value : {}
  return {
    id: course?.['course_id'] ?? course?.['id'] ?? index,
    name: normalizeText(course?.['course_name'] ?? course?.['name']) || '未命名课程'
  }
}

const normalizeClassSummary = (value, index) => {
  const classItem = value && typeof value === 'object' ? value : {}
  const studentCount = Number(classItem?.['student_count'])
  return {
    id: classItem?.['id'] ?? classItem?.['class_id'] ?? index,
    name: normalizeText(classItem?.['name'] ?? classItem?.['class_name']) || '未命名班级',
    course: normalizeText(classItem?.['course'] ?? classItem?.['course_name']) || '未关联课程',
    teacherName: normalizeText(classItem?.['teacher_name']) || '-',
    studentCount: Number.isFinite(studentCount) ? studentCount : 0,
    createdAt: formatDate(classItem?.['created_at']),
    courseId: classItem?.['course_id'] ?? null,
    description: normalizeText(classItem?.['description'])
  }
}

const normalizeClassListResponse = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const rawClasses = Array.isArray(payload?.['classes']) ? payload['classes'] : []
  const items = rawClasses.map((classItem, index) => normalizeClassSummary(classItem, index))
  const totalCount = Number(payload?.['total'] ?? items.length)
  return {
    items,
    total: Number.isFinite(totalCount) ? totalCount : items.length
  }
}

const buildClassPayload = () => ({
  class_name: normalizeText(classForm.name),
  course_id: classForm.courseId,
  description: normalizeText(classForm.description)
})

/**
 * 加载课程选项
 */
const loadCourseOptions = async () => {
  try {
    const res = await getAllCourses({ page: 1, page_size: 100 })
    courseOptions.value = Array.isArray(res?.['courses'])
      ? res['courses'].map((course, index) => normalizeCourseOption(course, index))
      : []
  } catch {
    courseOptions.value = []
  }
}

/**
 * 加载班级列表
 */
const loadClasses = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize
    }
    if (filter.keyword) params.keyword = filter.keyword
    if (filter.course) params.course_id = filter.course

    const res = await getClassList(params)
    const classList = normalizeClassListResponse(res)
    classes.value = classList.items
    total.value = classList.total
  } catch (error) {
    console.error('获取班级列表失败:', error)
    appMessage.error('获取班级列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 删除班级
 */
const deleteClass = async (cls) => {
  try {
    await appDialog.confirm('确定删除该班级吗？', '删除确认', { type: 'warning' })
    await apiDeleteClass(cls.id)
    classes.value = classes.value.filter(c => c.id !== cls.id)
    appMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      appMessage.error('删除失败')
    }
  }
}

/**
 * 创建班级
 */
const handleAddClass = () => {
  isEditClass.value = false
  classForm.id = null
  classForm.name = ''
  classForm.courseId = null
  classForm.description = ''
  classDialogVisible.value = true
}

/**
 * 编辑班级
 */
const handleEditClass = (row) => {
  isEditClass.value = true
  classForm.id = row.id
  classForm.name = row.name
  classForm.courseId = row.courseId || null
  classForm.description = row.description || ''
  classDialogVisible.value = true
}

/**
 * 查看班级详情
 */
const viewClassDetail = (row) => {
  selectedClass.value = row
  detailDrawerVisible.value = true
}

/**
 * 提交创建/编辑
 */
const submitClassForm = async () => {
  const payload = buildClassPayload()
  if (!payload.class_name) return appMessage.warning('请输入班级名称')
  try {
    if (isEditClass.value && classForm.id) {
      await updateClass(classForm.id, payload)
      appMessage.success('更新成功')
    } else {
      await createClass(payload)
      appMessage.success('创建成功')
    }
    classDialogVisible.value = false
    await loadClasses()
  } catch (e) {
    appMessage.error(isEditClass.value ? '更新失败' : '创建失败')
  }
}

onMounted(() => {
  loadCourseOptions()
  loadClasses()
})
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
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
