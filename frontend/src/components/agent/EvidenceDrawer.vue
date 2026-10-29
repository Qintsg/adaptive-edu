<!-- 文件描述：课程资料来源。项目：adaptive-edu；文件：EvidenceDrawer.vue；作者：Qintsg；日期：2026-10-29。 -->
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

/**
 * 获取资料标题。
 * :param item: 课程资料。
 * :returns: 标题。
 */
function evidenceTitle(item: Record<string, unknown>): string {
  return String(item.title || item.name || `证据 ${item.id || ''}`).trim()
}

/**
 * 获取资料摘要。
 * :param item: 课程资料。
 * :returns: 摘要。
 */
function evidenceSummary(item: Record<string, unknown>): string {
  return String(item.summary || item.description || '').trim()
}
</script>

<template>
  <n-drawer
    :show="show"
    :width="420"
    placement="right"
    @update:show="value => emit('update:show', value)"
  >
    <n-drawer-content :title="resource?.title || '课程资料'">
      <div class="evidence-drawer">
        <n-alert v-if="warnings?.length" type="warning" title="资源说明" :closable="false">
          <ul class="warning-list">
            <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
          </ul>
        </n-alert>

        <n-empty v-if="!evidenceItems.length" description="暂无关联资料" />

        <div v-else class="evidence-list">
          <article v-for="item in evidenceItems" :key="`${item.source_type}-${item.id}-${item.title}`" class="evidence-item">
            <div class="evidence-title-row">
              <h4>{{ evidenceTitle(item) }}</h4>
            </div>
            <p v-if="evidenceSummary(item)">{{ evidenceSummary(item) }}</p>
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
