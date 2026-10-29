<!-- 文件描述：学习资源生成。项目：adaptive-edu；文件：AgentLearningView.vue；作者：Qintsg；日期：2026-10-29。 -->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AgentRunTimeline from '@/components/agent/AgentRunTimeline.vue'
import EvidenceDrawer from '@/components/agent/EvidenceDrawer.vue'
import GeneratedResourceCard from '@/components/agent/GeneratedResourceCard.vue'
import ResourceFeedbackPanel from '@/components/agent/ResourceFeedbackPanel.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import PageHero from '@/components/common/PageHero.vue'
import SectionCard from '@/components/common/SectionCard.vue'
import ToolbarRow from '@/components/common/ToolbarRow.vue'
import {
  applyGeneratedResourcesToPath,
  completeAgentRun,
  generateLearningPackage,
  getAgentEffectSummary,
  listGeneratedResources,
  submitGeneratedResourceFeedback,
  submitProfileDialog,
  type AgentResourceType,
  type EffectSummary,
  type GeneratedLearningResource,
  type LearningPackageResult,
  type ResourceFeedbackRequest
} from '@/api/student/agent'
import { useCourseStore } from '@/stores/course'
import { awaitAIResult } from '@/utils/aiLoading'
import { showError, showSuccess, showWarning } from '@/utils/feedback'

const courseStore = useCourseStore()
const loadingPackage = ref(false)
const profileLoading = ref(false)
const applyingPath = ref(false)
const feedbackLoading = ref(false)
const existingLoading = ref(false)
const packageResult = ref<LearningPackageResult | null>(null)
const existingResources = ref<GeneratedLearningResource[]>([])
const selectedEvidenceResource = ref<GeneratedLearningResource | null>(null)
const selectedFeedbackResource = ref<GeneratedLearningResource | null>(null)
const evidenceVisible = ref(false)
const feedbackVisible = ref(false)
const effectSummary = ref<EffectSummary | null>(null)

const form = reactive({
  profileMessage: '我是软件专业学生，想两周内掌握 Spark SQL，但 HDFS 和 MapReduce 基础不太好，喜欢视频、案例和练习。',
  target: '补齐 Spark SQL 查询、DataFrame 操作和项目实操能力',
  resourceTypes: ['explanation', 'mindmap', 'quiz', 'reading', 'coding_case'] as AgentResourceType[],
  profile: {} as Record<string, unknown>
})

const resourceOptions = [
  { label: '讲解', value: 'explanation' },
  { label: '导图', value: 'mindmap' },
  { label: '练习', value: 'quiz' },
  { label: '阅读', value: 'reading' },
  { label: '实操', value: 'coding_case' },
  { label: '脚本', value: 'video_script' }
]

const currentCourseId = computed(() => courseStore.courseId)
const resources = computed(() => packageResult.value?.resources || existingResources.value)
const warnings = computed(() => packageResult.value?.warnings || [])
const qualityReport = computed(() => packageResult.value?.quality_report || null)
const qualityScoreText = computed(() => {
  const rawScore = Number(qualityReport.value?.score ?? 0)
  const percentage = rawScore <= 1 ? rawScore * 100 : rawScore
  return `${Math.round(percentage)}%`
})
const canGenerate = computed(() => Boolean(currentCourseId.value && form.target.trim()))
const profileLabels: Record<string, string> = {
  course_goal: '学习目标', weaknesses: '薄弱内容', preferred_resource: '资源偏好',
  learning_style: '学习方式', practice_preference: '练习偏好', pace: '学习节奏',
  available_time: '学习时间', major_or_background: '专业背景', knowledge_foundation: '知识基础'
}
const profileValues: Record<string, string> = {
  video: '视频', coding_case: '实操', exercise: '练习', reading: '阅读',
  visual: '视觉学习', auditory: '听觉学习', kinesthetic: '实践学习',
  hands_on: '动手练习', fast: '快速', medium: '适中', slow: '循序渐进'
}
const profileFields = computed(() => Object.entries(form.profile)
  .filter(([key, value]) => profileLabels[key] && value)
  .map(([key, value]) => [profileLabels[key], (Array.isArray(value) ? value : [value])
    .map(item => profileValues[String(item)] || String(item)).join('、')]))
const pathBindings = computed(() => packageResult.value?.path_suggestion.suggested_bindings || [])
const qualityStatusType = computed(() => {
  const status = qualityReport.value?.status
  if (status === 'failed') return 'error'
  if (status === 'warning') return 'warning'
  return 'success'
})

onMounted(async () => {
  courseStore.init()
  if (!currentCourseId.value) {
    await courseStore.fetchCourses()
  }
  await Promise.all([loadExistingResources(), loadEffectSummary()])
})

async function extractProfile(): Promise<void> {
  if (!currentCourseId.value) {
    showWarning('请先选择课程')
    return
  }
  const message = form.profileMessage.trim()
  if (!message) {
    showWarning('请描述当前学习情况')
    return
  }
  profileLoading.value = true
  try {
    const result = await awaitAIResult(submitProfileDialog(currentCourseId.value, message))
    form.profile = result.profile
    showSuccess('学习信息已更新')
  } catch {
    showError('暂时无法读取学习信息，请重试')
  } finally {
    profileLoading.value = false
  }
}

async function generatePackage(): Promise<void> {
  if (!currentCourseId.value || !canGenerate.value) {
    showWarning('请先选择课程并填写学习目标')
    return
  }
  loadingPackage.value = true
  try {
    if (!profileFields.value.length && form.profileMessage.trim()) {
      const profileResult = await awaitAIResult(submitProfileDialog(currentCourseId.value, form.profileMessage.trim()))
      form.profile = profileResult.profile
    }
    packageResult.value = await awaitAIResult(generateLearningPackage({
      course_id: currentCourseId.value,
      target: form.target.trim(),
      profile: form.profile,
      resource_types: form.resourceTypes
    }))
    existingResources.value = []
    await loadEffectSummary()
    showSuccess('学习资源包已生成')
  } catch {
    showError('暂时无法生成资源包，请重试')
  } finally {
    loadingPackage.value = false
  }
}

async function applyToPath(): Promise<void> {
  if (!currentCourseId.value || !packageResult.value) return
  applyingPath.value = true
  try {
    const result = await applyGeneratedResourcesToPath(currentCourseId.value, packageResult.value.run_id)
    if (result.warnings.length) {
      showWarning(result.warnings[0])
    } else {
      showSuccess('已应用到学习路径')
    }
  } catch {
    showError('暂时无法加入学习路径，请重试')
  } finally {
    applyingPath.value = false
  }
}

async function markRunComplete(): Promise<void> {
  if (!currentCourseId.value || !packageResult.value) return
  try {
    await completeAgentRun(currentCourseId.value, packageResult.value.run_id)
    showSuccess('本次资源生成已完成')
  } catch {
    showError('暂时无法结束本次生成，请重试')
  }
}

async function loadExistingResources(): Promise<void> {
  if (!currentCourseId.value) return
  existingLoading.value = true
  try {
    const result = await listGeneratedResources(currentCourseId.value, 12)
    existingResources.value = result.resources
  } catch {
    existingResources.value = []
  } finally {
    existingLoading.value = false
  }
}

async function loadEffectSummary(): Promise<void> {
  if (!currentCourseId.value) return
  try {
    effectSummary.value = await getAgentEffectSummary(currentCourseId.value)
  } catch {
    effectSummary.value = null
  }
}

function showEvidence(resource: GeneratedLearningResource): void {
  selectedEvidenceResource.value = resource
  evidenceVisible.value = true
}

function showFeedback(resource: GeneratedLearningResource): void {
  selectedFeedbackResource.value = resource
  feedbackVisible.value = true
}

async function submitFeedback(resourceId: number, payload: ResourceFeedbackRequest): Promise<void> {
  feedbackLoading.value = true
  try {
    await submitGeneratedResourceFeedback(resourceId, payload)
    feedbackVisible.value = false
    await loadEffectSummary()
    showSuccess('学习反馈已记录')
  } catch {
    showError('暂时无法记录反馈，请重试')
  } finally {
    feedbackLoading.value = false
  }
}
</script>

<template>
  <div class="agent-learning-view">
    <PageHero
      title="生成学习资源"
    >
      <template #actions>
        <n-button type="primary" :loading="loadingPackage" :disabled="!canGenerate" @click="generatePackage">
          <template #icon><AppIcon name="Sparkle" /></template>
          生成资源包
        </n-button>
        <n-button :loading="existingLoading" @click="loadExistingResources">
          <template #icon><AppIcon name="ArrowSync" /></template>
          刷新资源
        </n-button>
      </template>
      <template #meta>
        <div class="hero-meta">
          <n-tag :bordered="false">课程：{{ courseStore.courseName || '未选择' }}</n-tag>
          <n-tag v-if="qualityReport" :type="qualityStatusType" :bordered="false">
            质量分 {{ qualityScoreText }}
          </n-tag>
        </div>
      </template>
    </PageHero>

    <div class="agent-grid">
      <div class="main-column">
        <SectionCard title="学习目标与情况">
          <n-form label-placement="top" class="agent-form">
            <n-form-item label="当前学习情况">
              <n-input
                v-model:value="form.profileMessage"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 6 }"
                maxlength="800"
                show-count
              />
            </n-form-item>
            <n-form-item label="学习目标">
              <n-input v-model:value="form.target" maxlength="300" show-count />
            </n-form-item>
            <n-form-item label="资源类型">
              <n-checkbox-group v-model:value="form.resourceTypes">
                <n-space>
                  <n-checkbox
                    v-for="option in resourceOptions"
                    :key="option.value"
                    :value="option.value"
                    :label="option.label"
                  />
                </n-space>
              </n-checkbox-group>
            </n-form-item>
          </n-form>

          <ToolbarRow>
            <template #start>
              <n-button :loading="profileLoading" :disabled="loadingPackage" @click="extractProfile">
                <template #icon><AppIcon name="User" /></template>
                提取学习信息
              </n-button>
            </template>
            <template #end>
              <n-button type="primary" :loading="loadingPackage" :disabled="!canGenerate" @click="generatePackage">
                <template #icon><AppIcon name="MagicStick" /></template>
                生成资源包
              </n-button>
            </template>
          </ToolbarRow>

          <n-alert v-if="profileLoading" title="正在整理学习信息…" type="info" :closable="false" />

          <div v-if="profileFields.length" class="profile-chips">
            <n-tag v-for="[key, value] in profileFields" :key="key" :bordered="false">
              {{ key }}：{{ value }}
            </n-tag>
          </div>
        </SectionCard>

        <SectionCard title="生成资源">
          <n-alert v-if="loadingPackage" title="正在生成学习资源…" type="info" :closable="false" />
          <n-empty v-if="!resources.length && !loadingPackage" description="填写学习目标，生成资源包" />
          <n-skeleton v-if="loadingPackage" :rows="8" animated />
          <div v-else class="resource-grid">
            <GeneratedResourceCard
              v-for="resource in resources"
              :key="resource.resource_id"
              :resource="resource"
              @evidence="showEvidence"
              @feedback="showFeedback"
            />
          </div>
        </SectionCard>
      </div>

      <aside class="side-column">
        <SectionCard title="生成过程">
          <AgentRunTimeline
            :trace="packageResult?.agent_trace || []"
            :progress-events="packageResult?.progress_events || []"
          />
        </SectionCard>

        <SectionCard title="加入学习路径">
          <n-empty v-if="!pathBindings.length" description="生成资源后查看" />
          <div v-else class="binding-list">
            <article v-for="binding in pathBindings" :key="binding.resource_id" class="binding-item">
              <strong>{{ binding.title }}</strong>
              <p>{{ binding.suggested_node_title || '将插入补充节点' }}</p>
              <span>{{ binding.reason }}</span>
            </article>
          </div>
          <n-button
            type="primary"
            block
            :disabled="!packageResult"
            :loading="applyingPath"
            class="path-action"
            @click="applyToPath"
          >
            <template #icon><AppIcon name="Guide" /></template>
            应用到学习路径
          </n-button>
          <n-button block :disabled="!packageResult" class="path-action" @click="markRunComplete">
            结束本次生成
          </n-button>
        </SectionCard>

        <SectionCard title="使用情况">
          <div class="effect-grid">
            <div>
              <strong>{{ effectSummary?.resource_count || 0 }}</strong>
              <span>生成资源</span>
            </div>
            <div>
              <strong>{{ effectSummary?.completed_count || 0 }}</strong>
              <span>已完成</span>
            </div>
            <div>
              <strong>{{ effectSummary?.average_rating || 0 }}</strong>
              <span>平均评分</span>
            </div>
          </div>
        </SectionCard>
      </aside>
    </div>

    <EvidenceDrawer
      v-model:show="evidenceVisible"
      :resource="selectedEvidenceResource"
      :warnings="warnings"
    />
    <ResourceFeedbackPanel
      v-model:show="feedbackVisible"
      :resource="selectedFeedbackResource"
      :course-id="currentCourseId"
      :loading="feedbackLoading"
      @submit="submitFeedback"
    />
  </div>
</template>

<style scoped>
.agent-learning-view {
  display: grid;
  gap: 20px;
}

.hero-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.agent-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 20px;
  align-items: start;
}

.main-column,
.side-column {
  display: grid;
  gap: 20px;
}

.agent-form {
  margin-bottom: 14px;
}

.profile-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.binding-list {
  display: grid;
  gap: 10px;
}

.binding-item {
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-soft);
}

.binding-item strong {
  color: var(--text-primary);
}

.binding-item p,
.binding-item span {
  display: block;
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.path-action {
  margin-top: 12px;
}

.effect-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.effect-grid div {
  display: grid;
  place-items: center;
  gap: 4px;
  padding: 12px 8px;
  border-radius: 8px;
  background: var(--bg-soft);
}

.effect-grid strong {
  color: var(--text-primary);
  font-size: 20px;
}

.effect-grid span {
  color: var(--text-secondary);
  font-size: 12px;
}

.warning-alert {
  margin-top: 14px;
}

@media (max-width: 1180px) {
  .agent-grid {
    grid-template-columns: 1fr;
  }

  .side-column {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .resource-grid,
  .side-column {
    grid-template-columns: 1fr;
  }
}
</style>
