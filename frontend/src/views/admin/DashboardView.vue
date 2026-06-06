<template>
  <div class="dashboard-view" v-loading="loading">
    <n-row :gutter="20">
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card" shadow="hover">
          <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
            <n-icon>
              <User />
            </n-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.userCount.toLocaleString() }}</div>
            <div class="stat-label">用户总数</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card" shadow="hover">
          <div class="stat-icon" style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);">
            <n-icon>
              <Reading />
            </n-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.courseCount }}</div>
            <div class="stat-label">课程总数</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card" shadow="hover">
          <div class="stat-icon" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
            <n-icon>
              <School />
            </n-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.classCount }}</div>
            <div class="stat-label">班级总数</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :sm="12" :md="6">
        <n-card class="stat-card" shadow="hover">
          <div class="stat-icon" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
            <n-icon>
              <TrendCharts />
            </n-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.onlineRate }}</div>
            <div class="stat-label">系统在线率</div>
          </div>
        </n-card>
      </n-col>
    </n-row>

    <n-row :gutter="20" class="content-row">
      <n-col :xs="24" :lg="12">
        <n-card shadow="hover">
          <template #header>角色分布</template>
          <div class="role-stats">
            <div class="role-item">
              <span class="role-label">学生</span>
              <n-progress :percentage="rolePercent('student')" :stroke-width="16" color="#409eff" />
            </div>
            <div class="role-item">
              <span class="role-label">教师</span>
              <n-progress :percentage="rolePercent('teacher')" :stroke-width="16" color="#e6a23c" />
            </div>
            <div class="role-item">
              <span class="role-label">管理员</span>
              <n-progress :percentage="rolePercent('admin')" :stroke-width="16" color="#f56c6c" />
            </div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="24" :lg="12">
        <n-card shadow="hover">
          <template #header>最近活动</template>
          <n-timeline v-if="recentLogs.length">
            <n-timeline-item v-for="log in recentLogs" :key="log.id" :timestamp="log.time">
              {{ log.content }}
            </n-timeline-item>
          </n-timeline>
          <n-empty v-else description="暂无活动记录" :image-size="80" />
        </n-card>
      </n-col>
    </n-row>
  </div>
</template>

<script setup>
/**
 * 管理端仪表盘视图
 */
import { ref, onMounted } from 'vue'
import { appMessage } from '@/utils/feedback'
import { User, Reading, School, TrendCharts } from '@/theme/element-icons'
import { getOverviewStats } from '@/api/admin/statistics'
import { getLogs } from '@/api/admin/log'

const loading = ref(false)

const buildDefaultStats = () => ({
  userCount: 0,
  courseCount: 0,
  classCount: 0,
  onlineRate: '0%'
})

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeCount = (value) => {
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : 0
}

const normalizeRoleDistribution = (value) => {
  const distribution = value && typeof value === 'object' ? value : {}
  return {
    student: normalizeCount(distribution?.['student']),
    teacher: normalizeCount(distribution?.['teacher']),
    admin: normalizeCount(distribution?.['admin'])
  }
}

// 统计数据
const stats = ref(buildDefaultStats())

const roleDistribution = ref({ student: 0, teacher: 0, admin: 0 })

const rolePercent = (role) => {
  const total = stats.value.userCount || 1
  return Math.round((roleDistribution.value[role] || 0) / total * 100)
}

const recentLogs = ref([])

const normalizeOverviewStats = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  return {
    userCount: normalizeCount(payload?.['userCount'] ?? payload?.['user_count']),
    courseCount: normalizeCount(payload?.['courseCount'] ?? payload?.['course_count']),
    classCount: normalizeCount(payload?.['classCount'] ?? payload?.['class_count']),
    onlineRate: normalizeText(payload?.['onlineRate'] ?? payload?.['online_rate']) || '-',
    roleDistribution: normalizeRoleDistribution(payload?.['roleDistribution'] ?? payload?.['role_distribution'])
  }
}

const normalizeRecentLog = (value, index) => {
  const log = value && typeof value === 'object' ? value : {}
  return {
    id: log?.['id'] ?? index,
    content: normalizeText(log?.['description'] ?? log?.['action_type_display'] ?? log?.['action_type']) || '系统活动',
    time: formatTime(log?.['created_at'] ?? log?.['time'])
  }
}

const normalizeRecentLogResponse = (value) => {
  const payload = value && typeof value === 'object' ? value : {}
  const rawLogs = Array.isArray(payload?.['results']) ? payload['results'] : []
  return rawLogs.slice(0, 5).map((log, index) => normalizeRecentLog(log, index))
}

/**
 * 加载仪表盘数据
 */
const loadDashboardData = async () => {
  loading.value = true
  try {
    const [overviewStatsResult, recentLogsResult] = await Promise.allSettled([
      getOverviewStats(),
      getLogs({ page: 1, page_size: 5 })
    ])

    // 处理统计数据（响应拦截器已解包，直接拿到data对象）
    if (overviewStatsResult.status === 'fulfilled') {
      const overviewStats = normalizeOverviewStats(overviewStatsResult.value)
      stats.value = {
        userCount: overviewStats.userCount,
        courseCount: overviewStats.courseCount,
        classCount: overviewStats.classCount,
        onlineRate: overviewStats.onlineRate
      }
      roleDistribution.value = overviewStats.roleDistribution
    }

    // 处理日志数据（后端返回 results 数组和 count 总数）
    if (recentLogsResult.status === 'fulfilled') {
      recentLogs.value = normalizeRecentLogResponse(recentLogsResult.value)
    }
  } catch (error) {
    console.error('加载仪表盘数据失败:', error)
    appMessage.error('加载仪表盘数据失败')
  } finally {
    loading.value = false
  }
}

/**
 * 格式化时间为相对时间
 */
const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  if (Number.isNaN(date.getTime())) return '-'
  const now = new Date()
  const diff = Math.floor((now - date) / 1000 / 60) // 分钟差

  if (diff < 1) return '刚刚'
  if (diff < 60) return `${diff}分钟前`
  if (diff < 1440) return `${Math.floor(diff / 60)}小时前`
  return `${Math.floor(diff / 1440)}天前`
}

onMounted(() => {
  loadDashboardData()
})
</script>

<style scoped>
.dashboard-view {
  padding: 0;
}

.content-row {
  margin-top: 20px;
}

.stat-card :deep(.n-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 24px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}

.role-stats {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 10px 0;
}

.role-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.role-label {
  width: 50px;
  font-size: 14px;
  color: #606266;
  flex-shrink: 0;
}

.stat-card {
  transition: all 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .stat-card :deep(.n-card__body) {
    flex-direction: column;
    text-align: center;
    padding: 16px;
  }

  .stat-value {
    font-size: 22px;
  }
}
</style>
