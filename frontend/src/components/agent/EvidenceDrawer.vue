<script setup lang="ts">
import { computed } from 'vue'
import type { GeneratedLearningResource } from '@/api/student/agent'

const props = defineProps<{
  show: boolean
  resource: GeneratedLearningResource | null
  warnings?: string[]
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const evidenceItems = computed(() => props.resource?.evidence || [])

function evidenceTitle(item: Record<string, unknown>): string {
  return String(item.title || item.name || `证据 ${item.id || ''}`).trim()
}

function evidenceSummary(item: Record<string, unknown>): string {
  return String(item.summary || item.description || item.source_type || '课程证据').trim()
}
</script>

<template>
  <n-drawer
    :show="show"
    :width="420"
    placement="right"
    @update:show="value => emit('update:show', value)"
  >
    <n-drawer-content :title="resource?.title || '证据追溯'">
      <div class="evidence-drawer">
        <n-alert v-if="warnings?.length" type="warning" title="生成限制" :closable="false">
          <ul class="warning-list">
            <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
          </ul>
        </n-alert>

        <n-empty v-if="!evidenceItems.length" description="暂无课程证据，建议结合教师资料复核。" />

        <div v-else class="evidence-list">
          <article v-for="item in evidenceItems" :key="`${item.source_type}-${item.id}-${item.title}`" class="evidence-item">
            <div class="evidence-title-row">
              <h4>{{ evidenceTitle(item) }}</h4>
              <n-tag size="small" :bordered="false">
                {{ item.source_type || 'course' }}
              </n-tag>
            </div>
            <p>{{ evidenceSummary(item) }}</p>
            <dl>
              <template v-if="item.resource_type">
                <dt>资源类型</dt>
                <dd>{{ item.resource_type }}</dd>
              </template>
              <template v-if="item.id">
                <dt>来源 ID</dt>
                <dd>{{ item.id }}</dd>
              </template>
            </dl>
          </article>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.evidence-drawer {
  display: grid;
  gap: 16px;
}

.warning-list {
  margin: 0;
  padding-left: 18px;
}

.evidence-list {
  display: grid;
  gap: 12px;
}

.evidence-item {
  padding: 14px;
  border: 1px solid rgba(18, 154, 116, 0.14);
  border-radius: 8px;
  background: var(--bg-soft);
}

.evidence-title-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.evidence-title-row h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

.evidence-item p {
  margin: 8px 0 0;
  line-height: 1.6;
  color: var(--text-secondary);
}

.evidence-item dl {
  margin: 12px 0 0;
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 6px 10px;
  font-size: 12px;
}

.evidence-item dt {
  color: var(--text-secondary);
}

.evidence-item dd {
  margin: 0;
  color: var(--text-primary);
}
</style>
