<template>
  <div class="course-list-view">
    <PageHero eyebrow="Teacher Workspace" title="课程管理" description="统一管理课程基本信息，并从课程详情进入题库、资源、图谱与作业工作台。">
      <template #actions>
        <n-button type="primary" @click="createCourse">
          <n-icon>
            <Plus />
          </n-icon> 创建课程
        </n-button>
        <n-button plain @click="openImportCoursePage">
          <n-icon>
            <Plus />
          </n-icon> 导入建课
        </n-button>
      </template>
    </PageHero>

    <n-card shadow="hover">
      <n-table :data="courses" v-loading="loading" style="width: 100%">
        <n-table-column prop="name" label="课程名称" />
        <n-table-column prop="description" label="课程描述" show-overflow-tooltip />
        <n-table-column prop="isPublic" label="状态" width="100">
          <template #default="{ row }">
            <n-tag :type="row.isPublic ? 'success' : 'info'">{{ row.isPublic ? '公开' : '未公开' }}</n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="createdAt" label="创建时间" width="180" />
        <n-table-column label="操作" width="250">
          <template #default="{ row }">
            <n-button type="primary" link @click="viewCourse(row)">查看详情</n-button>
            <n-button type="warning" link @click="editCourse(row)">编辑</n-button>
            <n-button type="danger" link @click="deleteCourse(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无课程，点击右上角创建" />
        </template>
      </n-table>
    </n-card>
  </div>
</template>

<script setup>
/**
 * 教师端 - 课程列表视图
 * 管理课程、创建课程等功能
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { appMessage, appDialog } from '@/utils/feedback'
import { Plus } from '@/theme/element-icons'
import { getMyCourses, deleteCourse as apiDeleteCourse } from '@/api/teacher/course'
import PageHero from '@/components/common/PageHero.vue'

const router = useRouter()

// 加载状态
const loading = ref(true)

// 课程列表
const courses = ref([])

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const formatDateTime = (value) => {
  if (!value) return '-'
  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) return '-'
  return parsedDate.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

const normalizeCourseSummary = (value, index) => {
  const course = value && typeof value === 'object' ? value : {}
  return {
    id: course?.['course_id'] ?? course?.['id'] ?? index,
    name: normalizeText(course?.['course_name'] ?? course?.['name']) || '未命名课程',
    description: normalizeText(course?.['course_description'] ?? course?.['description']),
    isPublic: Boolean(course?.['is_public']),
    createdAt: formatDateTime(course?.['created_at'])
  }
}

/**
 * 加载课程列表
 */
const loadCourses = async () => {
  loading.value = true
  try {
    const res = await getMyCourses()
    const courseList = Array.isArray(res?.['courses']) ? res['courses'] : Array.isArray(res) ? res : []
    courses.value = courseList.map((course, index) => normalizeCourseSummary(course, index))
  } catch (error) {
    console.error('获取课程列表失败:', error)
    appMessage.error('获取课程列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 创建课程
 */
const createCourse = () => router.push('/teacher/courses/create')
const openImportCoursePage = () => {
  const targetRoute = router.resolve({ path: '/teacher/courses/create' })
  window.open(targetRoute.href, '_blank', 'noopener')
}
const viewCourse = (course) => router.push(`/teacher/courses/${course.id}`)
const editCourse = (course) => router.push(`/teacher/courses/${course.id}/edit`)

/**
 * 删除课程
 */
const deleteCourse = async (course) => {
  try {
    await appDialog.confirm('确定删除该课程吗？此操作不可恢复。', '删除确认', { type: 'warning' })

    await apiDeleteCourse(course.id)
    courses.value = courses.value.filter(c => c.id !== course.id)
    appMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除课程失败:', error)
      appMessage.error('删除课程失败')
    }
  }
}

onMounted(() => {
  loadCourses()
})
</script>

<style scoped>
.course-list-view {
  display: grid;
  gap: 20px;
}
</style>
