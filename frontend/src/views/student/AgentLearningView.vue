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
import { showError, showSuccess, showWarning } from '@/utils/feedback'

const courseStore = useCourseStore()
const loadingPackage = ref(false)
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
const canGenerate = computed(() => Boolean(currentCourseId.value && form.target.trim()))
const profileFields = computed(() => Object.entries(form.profile).filter(([, value]) => value))
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
    showWarning('请输入画像描述')
    return
  }
  try {
    const result = await submitProfileDialog(currentCourseId.value, message)
    form.profile = result.profile
    showSuccess(result.next_question ? `画像已更新：${result.next_question}` : '画像已更新')
  } catch {
    showError('画像抽取失败')
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
      const profileResult = await submitProfileDialog(currentCourseId.value, form.profileMessage.trim())
      form.profile = profileResult.profile
    }
    packageResult.value = await generateLearningPackage({
      course_id: currentCourseId.value,
      target: form.target.trim(),
      profile: form.profile,
      resource_types: form.resourceTypes
    })
    existingResources.value = []
    await loadEffectSummary()
    showSuccess('学习资源包已生成')
  } catch {
    showError('学习资源包生成失败')
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
    showError('应用到路径失败')
  } finally {
    applyingPath.value = false
  }
}

async function markRunComplete(): Promise<void> {
  if (!currentCourseId.value || !packageResult.value) return
  try {
    await completeAgentRun(currentCourseId.value, packageResult.value.run_id)
    showSuccess('本次智能体学习已收口')
  } catch {
    showError('运行收口失败')
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
    showError('反馈提交失败')
  } finally {
    feedbackLoading.value = false
  }
}
</script>

<template>
  <div class="agent-learning-view">
    <PageHero
      eyebrow="A3 Agent"
      title="个性化智能体"
      description="把学习画像、课程证据、资源生成、路径绑定和反馈闭环放在同一张工作台里。"
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
            质量分 {{ qualityReport.score }}
          </n-tag>
        </div>
      </template>
    </PageHero>

    <div class="agent-grid">
      <div class="main-column">
        <SectionCard title="学习目标与画像" description="先抽取画像，再生成个性化资源包。">
          <n-form label-placement="top" class="agent-form">
            <n-form-item label="画像描述">
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
              <n-button @click="extractProfile">
                <template #icon><AppIcon name="User" /></template>
                抽取画像
              </n-button>
            </template>
            <template #end>
              <n-button type="primary" :loading="loadingPackage" :disabled="!canGenerate" @click="generatePackage">
                <template #icon><AppIcon name="MagicStick" /></template>
                生成资源包
              </n-button>
            </template>
          </ToolbarRow>

          <div v-if="profileFields.length" class="profile-chips">
            <n-tag v-for="[key, value] in profileFields" :key="key" :bordered="false">
              {{ key }}：{{ Array.isArray(value) ? value.join('、') : value }}
            </n-tag>
          </div>
        </SectionCard>

        <SectionCard title="生成资源" description="每张卡片保留证据追溯与学习反馈入口。">
          <n-empty v-if="!resources.length && !loadingPackage" description="暂无生成资源，先生成一个学习资源包。" />
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
        <SectionCard title="运行轨迹" description="同步编排结果，供演示和排查使用。">
          <AgentRunTimeline
            :trace="packageResult?.agent_trace || []"
            :progress-events="packageResult?.progress_events || []"
          />
        </SectionCard>

        <SectionCard title="路径绑定" description="生成资源优先绑定到相同知识点节点。">
          <n-empty v-if="!pathBindings.length" description="生成资源包后显示路径建议。" />
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
            标记本次学习完成
          </n-button>
        </SectionCard>

        <SectionCard title="效果摘要" description="基于生成资源反馈形成下一轮画像和路径输入。">
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
          <n-alert v-if="warnings.length" type="warning" title="生成提示" :closable="false" class="warning-alert">
            {{ warnings[0] }}
          </n-alert>
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
