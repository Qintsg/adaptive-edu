<!-- 学生首页：以当前课程、下一步学习和真实进度为核心。 -->
<template>
  <div class="dashboard-view" v-loading="loading">
    <section class="dashboard-hero" aria-labelledby="dashboard-title">
      <div class="hero-copy">
        <p class="hero-eyebrow">学习总览 <span aria-hidden="true">/</span> {{ currentCourseName }}</p>
        <h1 id="dashboard-title">欢迎回来，{{ username }}<span class="hero-title-mark">。</span></h1>
        <div class="hero-actions flex flex-wrap gap-3">
          <n-button type="primary" @click="goToLearningPath">
            <template #icon><n-icon><Guide /></n-icon></template>
            继续学习
          </n-button>
          <button class="hero-secondary" type="button" @click="$router.push('/student/knowledge-map')">
            查看知识图谱 <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
      <div class="hero-progress" :aria-label="`当前学习进度 ${learningProgress}%`">
        <div class="progress-orbit" :style="{ '--progress': `${learningProgress}%` }">
          <span class="orbit-point orbit-point--one" />
          <span class="orbit-point orbit-point--two" />
          <span class="orbit-point orbit-point--three" />
          <div class="progress-core">
            <span class="progress-caption">当前课程进度</span>
            <strong>{{ learningProgress }}<small>%</small></strong>
          </div>
        </div>
      </div>
    </section>

    <!-- 未选课程提示 -->
    <n-alert v-if="!courseStore.courseId" title="请先选择课程" type="info" show-icon description="请在顶部课程选择器中选择一门课程，以查看学习数据"
      :closable="false" style="margin-top: 20px;" />

    <n-row :gutter="20" class="stats-row">
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card stat-card-1" shadow="hover">
          <div class="stat-icon"><n-icon>
              <TrendCharts />
            </n-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ learningProgress }}%</div>
            <div class="stat-label">学习进度</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card stat-card-2" shadow="hover">
          <div class="stat-icon"><n-icon>
              <Checked />
            </n-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ masteredPoints }}</div>
            <div class="stat-label">已掌握知识点</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card stat-card-3" shadow="hover">
          <div class="stat-icon"><n-icon>
              <Timer />
            </n-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ studyHours }}h</div>
            <div class="stat-label">累计学习时长</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card stat-card-4" shadow="hover">
          <div class="stat-icon"><n-icon>
              <Finished />
            </n-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ completedTasks }}</div>
            <div class="stat-label">已完成路径节点</div>
          </div>
        </n-card>
      </n-col>
    </n-row>

    <n-row :gutter="20" class="content-row">
      <!-- 学习路径概览 -->
      <n-col :xs="24" :lg="16">
        <n-card class="path-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>学习路径</span>
              <n-button type="primary" link @click="goToLearningPath">查看全部</n-button>
            </div>
          </template>
          <div v-if="learningNodes.length" class="path-content">
            <n-timeline>
              <n-timeline-item v-for="node in learningNodes" :key="node.id"
                :type="node.status === 'completed' ? 'success' : node.status === 'current' ? 'primary' : 'info'"
                :hollow="node.status !== 'completed'">
                <div class="timeline-node">
                  <span class="node-title">{{ node.title }}</span>
                  <n-tag :type="getNodeTagType(node.status)" size="small">
                    {{ getNodeStatusText(node.status) }}
                  </n-tag>
                </div>
              </n-timeline-item>
            </n-timeline>
          </div>
          <div v-else class="empty-path">
            <span class="empty-path-symbol"><n-icon><Guide /></n-icon></span>
            <h3>还没有学习路径</h3>
            <p>完成初始测评后，系统会生成适合你的学习顺序。</p>
            <n-button type="primary" size="small" @click="$router.push('/student/assessment')">
              前往初始测评
            </n-button>
          </div>
        </n-card>

        <!-- 待完成作业 -->
        <n-card v-if="pendingExams.length" class="exams-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>待完成作业</span>
              <n-button type="primary" link @click="$router.push('/student/exams')">查看全部</n-button>
            </div>
          </template>
          <div v-for="exam in pendingExams" :key="exam.id" class="exam-item">
            <div class="exam-info">
              <span class="exam-title">{{ exam.title }}</span>
              <n-tag size="small" type="warning">{{ exam.examTypeText }}</n-tag>
            </div>
            <n-button size="small" type="primary" @click="startExam(exam)">
              开始作业
            </n-button>
          </div>
        </n-card>
      </n-col>

      <!-- 右侧栏 -->
      <n-col :xs="24" :lg="8">
        <!-- 快捷入口 -->
        <n-card class="quick-card" shadow="hover">
          <template #header><span>快捷入口</span></template>
          <div class="quick-actions">
            <button class="quick-item" type="button" @click="$router.push('/student/knowledge-map')">
              <n-icon>
                <Share />
              </n-icon>
              <span>知识图谱</span>
            </button>
            <button class="quick-item" type="button" @click="$router.push('/student/exams')">
              <n-icon>
                <Document />
              </n-icon>
              <span>在线作业</span>
            </button>
            <button class="quick-item" type="button" @click="$router.push('/student/profile')">
              <n-icon>
                <User />
              </n-icon>
              <span>学习画像</span>
            </button>
            <button class="quick-item" type="button" @click="$router.push('/student/resources')">
              <n-icon>
                <FolderOpened />
              </n-icon>
              <span>课程资源</span>
            </button>
            <button class="quick-item" type="button" @click="$router.push('/student/ai-assistant')">
              <n-icon>
                <ChatDotRound />
              </n-icon>
              <span>AI助手</span>
            </button>
          </div>
        </n-card>

        <!-- 最近学习的知识点 -->
        <n-card class="recent-card" shadow="hover">
          <template #header><span>最近学习</span></template>
          <div v-if="recentMastery.length" class="recent-list">
            <div v-for="item in recentMastery" :key="item.name" class="recent-item">
              <span class="recent-name">{{ item.name }}</span>
              <n-progress :percentage="item.value" :stroke-width="6" :color="getProgressColor(item.value)"
                style="flex: 1;" />
            </div>
          </div>
          <n-empty v-else description="暂无学习记录" :image-size="60" />
        </n-card>
      </n-col>
    </n-row>
  </div>
</template>

<script setup>
/**
 * 学生仪表盘视图
 * 展示学习概览、进度统计、快捷入口等
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useCourseStore } from '@/stores/course'
import { getLearningProgress, getLearningPath } from '@/api/student/learning'
import { getProfile } from '@/api/student/profile'
import {
  Guide, TrendCharts, Checked, Timer, Finished,
  Share, Document, User, FolderOpened, ChatDotRound
} from '@/theme/element-icons'

const router = useRouter()
const userStore = useUserStore()
const courseStore = useCourseStore()

const loading = ref(true)
const username = computed(() => userStore.username || '同学')
const currentCourseName = computed(() => courseStore.courseName || '请选择课程')

// 动态问候语
const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeNumber = (value) => {
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : 0
}

const normalizeIdentifier = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : value
}

const normalizeBoolean = (value) => {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const normalizedValue = value.trim().toLowerCase()
    return ['true', '1', 'yes', 'published', 'completed', 'started', 'active'].includes(normalizedValue)
  }
  return false
}

const parseTimestamp = (value) => {
  if (!value) return 0
  const parsedValue = Date.parse(String(value))
  return Number.isNaN(parsedValue) ? 0 : parsedValue
}

const learningProgress = ref(0)
const masteredPoints = ref(0)
const studyHours = ref(0)
const completedTasks = ref(0)
const learningNodes = ref([])
const pendingExams = ref([])
const recentMastery = ref([])

const resolveLearningNodeStatus = (value) => {
  const node = value && typeof value === 'object' ? value : {}
  const rawStatus = normalizeText(node?.['status']).toLowerCase()
  if (normalizeBoolean(node?.['completed']) || rawStatus === 'completed') return 'completed'
  if (normalizeBoolean(node?.['started']) || rawStatus === 'in_progress' || rawStatus === 'active') return 'current'
  return 'pending'
}

const normalizeLearningProgressSummary = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const progressRate = normalizeNumber(payload?.['progress'] ?? payload?.['progress_rate'])
  const studyMinutes = normalizeNumber(payload?.['study_time'] ?? payload?.['studyTime'])
  return {
    progressPercent: Math.min(100, Math.max(0, Math.round(progressRate * 100))),
    studyHours: Math.round(studyMinutes / 6) / 10,
    completedTasks: normalizeNumber(payload?.['completed_nodes'] ?? payload?.['completedNodes'])
  }
}

const extractLearningPathNodes = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  if (Array.isArray(payload?.['nodes'])) return payload['nodes']
  if (payload?.['data'] && typeof payload['data'] === 'object' && Array.isArray(payload['data']['nodes'])) {
    return payload['data']['nodes']
  }
  return []
}

const normalizeMasterySummary = (value, index) => {
  const mastery = value && typeof value === 'object' ? value : {}
  return {
    id: normalizeIdentifier(mastery?.['point_id'] ?? mastery?.['id'], index),
    name: normalizeText(mastery?.['point_name'] ?? mastery?.['name']) || '未知',
    masteryRate: normalizeNumber(mastery?.['mastery_rate']),
    updatedAt: normalizeText(mastery?.['updated_at'])
  }
}

const normalizeProfileSummary = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const knowledgeMastery = Array.isArray(payload?.['knowledge_mastery'])
    ? payload['knowledge_mastery'].map((mastery, index) => normalizeMasterySummary(mastery, index))
    : []
  return {
    masteredPointCount: knowledgeMastery.filter((mastery) => mastery.masteryRate >= 0.8).length,
    recentMasteryList: [...knowledgeMastery]
      .sort((leftItem, rightItem) => parseTimestamp(rightItem.updatedAt) - parseTimestamp(leftItem.updatedAt))
      .slice(0, 5)
      .map((mastery) => ({
        name: mastery.name,
        value: Math.min(100, Math.max(0, Math.round(mastery.masteryRate * 100)))
      }))
  }
}

const normalizePendingExamList = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const rawExams = Array.isArray(payload?.['exams']) ? payload['exams'] : []
  return rawExams
    .map((exam, index) => {
      const examItem = exam && typeof exam === 'object' ? exam : {}
      return {
        id: normalizeIdentifier(examItem?.['exam_id'] ?? examItem?.['id'], index),
        title: normalizeText(examItem?.['title']) || '未命名作业',
        examTypeText: normalizeText(examItem?.['exam_type_display'] ?? examItem?.['exam_type']) || '未分类',
        status: normalizeText(examItem?.['status']).toLowerCase(),
        submitted: normalizeBoolean(examItem?.['submitted'])
      }
    })
    .filter((exam) => exam.status === 'published' && !exam.submitted)
    .slice(0, 3)
}

const buildDashboardPathPreview = (nodes) => {
  if (!Array.isArray(nodes) || !nodes.length) {
    return []
  }

  const normalizedNodes = nodes.map((node, index) => ({
    id: normalizeIdentifier(node?.['node_id'] ?? node?.['id'], index),
    title: normalizeText(node?.['knowledge_point_name'] ?? node?.['title']) || `节点${index + 1}`,
    status: resolveLearningNodeStatus(node)
  }))

  const lastCompletedIndex = normalizedNodes.reduce((lastIndex, node, index) => {
    return node.status === 'completed' ? index : lastIndex
  }, -1)

  const startIndex = Math.max(lastCompletedIndex + 1, 0)
  const previewNodes = normalizedNodes.slice(startIndex, startIndex + 5)
  return previewNodes.length ? previewNodes : normalizedNodes.slice(0, 5)
}

const getProgressColor = (value) => {
  if (value >= 80) return '#22a06b'
  if (value >= 60) return 'var(--primary-color)'
  if (value >= 40) return '#dd8f1d'
  return '#d45050'
}

let dashboardRequestVersion = 0

/**
 * 清空当前课程的概览，避免切换课程时显示上一门课的数据。
 */
const resetDashboardSummary = () => {
  learningProgress.value = 0
  masteredPoints.value = 0
  studyHours.value = 0
  completedTasks.value = 0
  learningNodes.value = []
  pendingExams.value = []
  recentMastery.value = []
}

/**
 * 加载仪表盘数据
 */
const loadDashboardData = async () => {
  const requestVersion = ++dashboardRequestVersion
  const courseId = courseStore.courseId
  resetDashboardSummary()
  // 检查课程ID
  if (!courseId) {
    loading.value = false
    return
  }

  loading.value = true
  try {
    // 并行加载多个数据（注意：拦截器已返回 data 字段本身）
    const [progressRes, pathRes, profileRes] = await Promise.allSettled([
      getLearningProgress(courseId),
      getLearningPath(courseId),
      getProfile(courseId)
    ])
    if (requestVersion !== dashboardRequestVersion) return

    // 处理学习进度
    if (progressRes.status === 'fulfilled' && progressRes.value) {
      const progressSummary = normalizeLearningProgressSummary(progressRes.value)
      learningProgress.value = progressSummary.progressPercent
      studyHours.value = progressSummary.studyHours
      completedTasks.value = progressSummary.completedTasks
    }

    // 处理学习路径（仅预览前 5 个节点）
    if (pathRes.status === 'fulfilled' && pathRes.value) {
      const nodes = extractLearningPathNodes(pathRes.value)
      learningNodes.value = buildDashboardPathPreview(nodes)
    }

    // 处理画像数据，统计高掌握度知识点数量
    if (profileRes.status === 'fulfilled' && profileRes.value) {
      const profileSummary = normalizeProfileSummary(profileRes.value)
      masteredPoints.value = profileSummary.masteredPointCount
      recentMastery.value = profileSummary.recentMasteryList
    }

    // 加载待完成考试
    try {
      const { getExamList } = await import('@/api/student/exam')
      const examRes = await getExamList(courseId)
      if (requestVersion === dashboardRequestVersion) {
        pendingExams.value = normalizePendingExamList(examRes)
      }
    } catch { /* ignore */ }
  } catch (error) {
    console.error('加载仪表盘数据失败:', error)
  } finally {
    if (requestVersion === dashboardRequestVersion) loading.value = false
  }
}

/**
 * 跳转到学习路径
 */
const goToLearningPath = () => {
  router.push('/student/learning-path')
}

const startExam = (exam) => {
  router.push(`/student/exam/${exam.id}`)
}

/**
 * 获取节点标签类型
 */
const getNodeTagType = (status) => {
  const types = {
    completed: 'success',
    current: 'primary',
    pending: 'info'
  }
  return types[status] || 'info'
}

/**
 * 获取节点状态文本
 */
const getNodeStatusText = (status) => {
  const texts = {
    completed: '已完成',
    current: '学习中',
    pending: '待学习'
  }
  return texts[status] || '待学习'
}

onMounted(() => {
  loadDashboardData()
})

// 同一课程可能属于多个班级，班级变化也需要刷新作业与学习概览。
watch(() => [courseStore.courseId, courseStore.classId], (current, previous) => {
  if (current[0] !== previous[0] || current[1] !== previous[1]) {
    void loadDashboardData()
  }
})
</script>

<style scoped src="./DashboardView.css"></style>
