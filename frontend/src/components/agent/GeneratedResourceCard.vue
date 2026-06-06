<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { GeneratedLearningResource } from '@/api/student/agent'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  resource: GeneratedLearningResource
}>()

const emit = defineEmits<{
  evidence: [resource: GeneratedLearningResource]
  feedback: [resource: GeneratedLearningResource]
}>()

const typeLabelMap: Record<string, string> = {
  explanation: '讲解',
  mindmap: '导图',
  quiz: '练习',
  reading: '阅读',
  coding_case: '实操',
  video_script: '脚本'
}

const typeIconMap: Record<string, string> = {
  explanation: 'Document',
  mindmap: 'Share',
  quiz: 'Question',
  reading: 'Reading',
  coding_case: 'Task',
  video_script: 'Video'
}

const payload = computed(() => props.resource.content_payload || {})
const recommendationReason = computed(() => {
  const metadata = props.resource.metadata || {}
  return String(metadata.recommendation_reason || '')
})

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(item => typeof item === 'object' && item !== null) as Array<Record<string, unknown>> : []
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => String(item)) : []
}
</script>

<template>
  <n-card class="resource-card" hoverable>
    <template #header>
      <div class="resource-header">
        <div class="resource-kind">
          <span class="resource-icon">
            <AppIcon :name="typeIconMap[resource.resource_type]" />
          </span>
          <div>
            <n-tag size="small" :bordered="false">{{ typeLabelMap[resource.resource_type] }}</n-tag>
            <h3>{{ resource.title }}</h3>
          </div>
        </div>
        <div class="resource-actions">
          <n-tooltip trigger="hover">
            <template #trigger>
              <n-button circle quaternary @click="emit('evidence', resource)">
                <AppIcon name="Info" />
              </n-button>
            </template>
            查看证据
          </n-tooltip>
          <n-tooltip trigger="hover">
            <template #trigger>
              <n-button circle quaternary @click="emit('feedback', resource)">
                <AppIcon name="CheckCircle" />
              </n-button>
            </template>
            学习反馈
          </n-tooltip>
        </div>
      </div>
    </template>

    <div class="resource-body">
      <p v-if="recommendationReason" class="reason">{{ recommendationReason }}</p>

      <div v-if="resource.resource_type === 'explanation'" class="markdown-body" v-html="renderMarkdown(resource.content)" />

      <div v-else-if="resource.resource_type === 'mindmap'" class="mindmap-body">
        <pre>{{ payload.mermaid || resource.content }}</pre>
        <div v-if="asArray(payload.nodes).length" class="node-chips">
          <n-tag v-for="node in asArray(payload.nodes)" :key="String(node.label)" size="small">
            {{ node.label }}
          </n-tag>
        </div>
      </div>

      <div v-else-if="resource.resource_type === 'quiz'" class="quiz-body">
        <article v-for="(question, index) in asArray(payload.questions)" :key="`${question.stem}-${index}`" class="quiz-item">
          <strong>{{ index + 1 }}. {{ question.stem }}</strong>
          <ol v-if="asStringArray(question.options).length">
            <li v-for="option in asStringArray(question.options)" :key="option">{{ option }}</li>
          </ol>
          <p>答案：{{ question.answer }}</p>
          <p>{{ question.analysis }}</p>
        </article>
      </div>

      <div v-else-if="resource.resource_type === 'reading'" class="reading-body">
        <article v-for="item in asArray(payload.items)" :key="String(item.title)" class="reading-item">
          <strong>{{ item.title }}</strong>
          <p>{{ item.reason }}</p>
        </article>
      </div>

      <div v-else-if="resource.resource_type === 'coding_case'" class="coding-body">
        <p>{{ payload.scenario }}</p>
        <ol>
          <li v-for="step in asStringArray(payload.steps)" :key="step">{{ step }}</li>
        </ol>
        <pre>{{ payload.code }}</pre>
      </div>

      <div v-else-if="resource.resource_type === 'video_script'" class="script-body">
        <article v-for="shot in asArray(payload.shots)" :key="String(shot.time)" class="script-shot">
          <strong>{{ shot.time }} · {{ shot.visual }}</strong>
          <p>{{ shot.narration }}</p>
        </article>
      </div>

      <pre v-else>{{ resource.content }}</pre>
    </div>

    <template #footer>
      <div class="resource-footer">
        <span>{{ resource.knowledge_point_name || '课程综合目标' }}</span>
        <span>{{ resource.evidence.length }} 条证据</span>
      </div>
    </template>
  </n-card>
</template>

<style scoped>
.resource-card {
  height: 100%;
  border-radius: 8px;
}

.resource-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.resource-kind {
  display: flex;
  gap: 12px;
  min-width: 0;
}

.resource-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 8px;
  color: var(--primary-color);
  background: rgba(18, 154, 116, 0.12);
}

.resource-kind h3 {
  margin: 6px 0 0;
  font-size: 15px;
  line-height: 1.35;
  color: var(--text-primary);
  word-break: break-word;
}

.resource-actions {
  display: flex;
  gap: 4px;
  flex: 0 0 auto;
}

.resource-body {
  display: grid;
  gap: 12px;
  color: var(--text-regular);
}

.reason {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg-soft);
  color: var(--text-secondary);
  line-height: 1.6;
}

.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(p) {
  margin-top: 0;
}

.markdown-body :deep(p),
.markdown-body :deep(li) {
  line-height: 1.75;
}

pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #10201a;
  color: #edf7ef;
  font-size: 12px;
  line-height: 1.6;
}

.node-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.quiz-body,
.reading-body,
.script-body {
  display: grid;
  gap: 12px;
}

.quiz-item,
.reading-item,
.script-shot {
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-soft);
}

.quiz-item strong,
.reading-item strong,
.script-shot strong {
  color: var(--text-primary);
}

.quiz-item p,
.reading-item p,
.script-shot p,
.coding-body p,
.coding-body li {
  margin: 8px 0 0;
  color: var(--text-secondary);
  line-height: 1.6;
}

.coding-body ol,
.quiz-item ol {
  margin: 8px 0 0;
  padding-left: 20px;
}

.resource-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
