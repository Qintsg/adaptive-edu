<template>
  <div class="class-list-view">
    <n-card class="page-header" shadow="never">
      <div class="header-content">
        <h2>班级管理</h2>
        <n-button type="primary" @click="showCreateDialog = true">
          <n-icon>
            <Plus />
          </n-icon> 创建班级
        </n-button>
      </div>
    </n-card>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <n-skeleton :rows="6" animated />
    </div>

    <!-- 班级列表 -->
    <n-row v-else :gutter="20" class="class-grid">
      <n-col v-for="cls in classes" :key="cls.id" :xs="24" :sm="12" :lg="8">
        <n-card class="class-card" shadow="hover" @click="viewClass(cls)">
          <div class="class-header">
            <div class="class-avatar">{{ cls.name.charAt(0) }}</div>
            <div class="class-info">
              <h3>{{ cls.name }}</h3>
              <p>{{ cls.courseName }}</p>
            </div>
          </div>
          <div class="class-stats">
            <div class="class-stat">
              <n-icon>
                <User />
              </n-icon>
              <span>{{ cls.studentCount }} 名学生</span>
            </div>
            <div v-if="cls.inviteCode" class="class-stat">
              <n-icon>
                <Key />
              </n-icon>
              <span>邀请码: {{ cls.inviteCode }}</span>
            </div>
          </div>
        </n-card>
      </n-col>
      <n-col v-if="!classes.length" :span="24">
        <n-card class="empty-card" shadow="never">
          <n-empty description="暂无班级">
            <n-button type="primary" @click="showCreateDialog = true">创建第一个班级</n-button>
          </n-empty>
        </n-card>
      </n-col>
    </n-row>

    <!-- 创建班级对话框 -->
    <n-dialog v-model="showCreateDialog" title="创建班级" width="400px">
      <n-form :model="createForm" label-width="80px">
        <n-form-item label="班级名称">
          <n-input v-model="createForm.name" placeholder="请输入班级名称" />
        </n-form-item>
        <n-form-item label="关联课程">
          <n-select v-model="createForm.courseId" placeholder="请选择课程" style="width: 100%;">
            <n-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" />
          </n-select>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="showCreateDialog = false">取消</n-button>
        <n-button type="primary" :loading="createLoading" @click="createClass">创建</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
/**
 * 教师端 - 班级列表视图
 * 管理班级、创建班级等功能
 */
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { appMessage } from '@/utils/feedback'
import { Plus, User, Key } from '@/theme/element-icons'
import { getMyClasses, createClass as apiCreateClass } from '@/api/teacher/class'
import { getMyCourses } from '@/api/teacher/course'

const router = useRouter()

// 加载状态
const loading = ref(true)

// 班级列表
const classes = ref([])

// 课程列表
const courses = ref([])

// 创建班级对话框
const showCreateDialog = ref(false)
const createLoading = ref(false)
const createForm = reactive({ name: '', courseId: null })

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeClassSummary = (value, index) => {
  const classItem = value && typeof value === 'object' ? value : {}
  const studentCount = Number(classItem?.['student_count'])
  return {
    id: classItem?.['class_id'] ?? classItem?.['id'] ?? index,
    name: normalizeText(classItem?.['class_name'] ?? classItem?.['name']) || '未命名班级',
    courseName: normalizeText(classItem?.['course_name']),
    studentCount: Number.isFinite(studentCount) ? studentCount : 0,
    inviteCode: normalizeText(classItem?.['invite_code'])
  }
}

const normalizeCourseSummary = (value, index) => {
  const courseItem = value && typeof value === 'object' ? value : {}
  return {
    id: courseItem?.['course_id'] ?? courseItem?.['id'] ?? index,
    name: normalizeText(courseItem?.['course_name'] ?? courseItem?.['name']) || '未命名课程'
  }
}

/**
 * 加载班级列表
 */
const loadClasses = async () => {
  loading.value = true
  try {
    const res = await getMyClasses()
    const classList = Array.isArray(res?.['classes']) ? res['classes'] : []
    classes.value = classList.map((classItem, index) => normalizeClassSummary(classItem, index))
  } catch (error) {
    console.error('获取班级列表失败:', error)
    appMessage.error('获取班级列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 加载课程列表（用于创建班级时选择）
 */
const loadCourses = async () => {
  try {
    const res = await getMyCourses()
    const courseList = Array.isArray(res?.['courses']) ? res['courses'] : []
    courses.value = courseList.map((courseItem, index) => normalizeCourseSummary(courseItem, index))
  } catch (error) {
    console.error('获取课程列表失败:', error)
  }
}

/**
 * 查看班级详情
 */
const viewClass = (cls) => router.push(`/teacher/classes/${cls.id}`)

/**
 * 创建班级
 */
const createClass = async () => {
  const className = normalizeText(createForm.name)
  if (!className) {
    appMessage.warning('请输入班级名称')
    return
  }
  if (!createForm.courseId) {
    appMessage.warning('请选择关联课程')
    return
  }

  createLoading.value = true
  try {
    await apiCreateClass({
      class_name: className,
      course_id: createForm.courseId
    })
    // 注意：响应拦截器已自动提取data字段
    appMessage.success('班级创建成功')
    showCreateDialog.value = false
    createForm.name = ''
    createForm.courseId = null
    await loadClasses()
  } catch (error) {
    console.error('创建班级失败:', error)
    appMessage.error('创建班级失败')
  } finally {
    createLoading.value = false
  }
}

onMounted(() => {
  loadClasses()
  loadCourses()
})
</script>

<style scoped>
.page-header {
  margin-bottom: 24px;
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

.loading-container {
  padding: 20px;
}

.class-grid {
  margin-top: 4px;
}

.class-card {
  margin-bottom: 20px;
  cursor: pointer;
  transition: all 0.3s;
  border-radius: 12px;
}

.class-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.class-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.class-avatar {
  width: 52px;
  height: 52px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 22px;
  font-weight: 600;
  flex-shrink: 0;
}

.class-info h3 {
  margin: 0 0 4px;
  font-size: 16px;
  color: #303133;
}

.class-info p {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.class-stats {
  display: flex;
  gap: 20px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.class-stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #606266;
}

.class-stat .n-icon {
  color: #909399;
}

.empty-card {
  border-radius: 12px;
}
</style>
