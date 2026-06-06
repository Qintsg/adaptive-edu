<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { AgentProgressEvent, AgentTraceItem } from '@/api/student/agent'

const props = defineProps<{
  trace: AgentTraceItem[]
  progressEvents?: AgentProgressEvent[]
}>()

const statusTypeMap = {
  completed: 'success',
  warning: 'warning',
  failed: 'error',
  running: 'info',
  pending: 'default',
  cancelled: 'default'
} as const

const orderedTrace = computed(() => props.trace || [])
const progressPercent = computed(() => {
  const events = props.progressEvents || []
  return events.length ? Math.max(...events.map(event => Number(event.percent) || 0)) : 0
})

function statusText(status: string): string {
  const map: Record<string, string> = {
    completed: '完成',
    warning: '需复核',
    failed: '失败',
    running: '运行中',
    pending: '等待',
    cancelled: '取消'
  }
  return map[status] || status
}

function agentLabel(agent: string): string {
  const map: Record<string, string> = {
    profile_agent: '画像智能体',
    knowledge_agent: '知识检索',
    path_agent: '路径规划',
    resource_agent: '资源生成',
    multimodal_agent: '多模态',
    evaluation_agent: '评测校验',
    package_agent: '资源包',
    quality_guard: '质量守卫'
  }
  return map[agent] || agent
}
</script>

<template>
  <section class="agent-timeline">
    <div class="timeline-header">
      <div>
        <h3>编排进度</h3>
        <p>展示每个智能体角色的处理状态与可复核提示。</p>
      </div>
      <n-progress
        type="circle"
        :percentage="progressPercent"
        :width="70"
        :stroke-width="8"
      />
    </div>

    <div v-if="progressEvents?.length" class="progress-events">
      <div v-for="event in progressEvents" :key="event.stage" class="progress-event">
        <span>{{ event.message }}</span>
        <n-tag :type="statusTypeMap[event.status] || 'default'" size="small">
          {{ event.percent }}%
        </n-tag>
      </div>
    </div>

    <div class="trace-list">
      <div v-for="item in orderedTrace" :key="`${item.agent}-${item.summary}`" class="trace-item">
        <div class="trace-icon" :class="item.status">
          <AppIcon :name="item.status === 'warning' ? 'Warning' : item.status === 'failed' ? 'ErrorCircle' : 'Sparkle'" />
        </div>
        <div class="trace-copy">
          <div class="trace-title">
            <strong>{{ agentLabel(item.agent) }}</strong>
            <n-tag :type="statusTypeMap[item.status] || 'default'" size="small">
              {{ statusText(item.status) }}
            </n-tag>
          </div>
          <p>{{ item.summary }}</p>
          <p v-if="item.error" class="trace-error">{{ item.error }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-timeline {
  display: grid;
  gap: 16px;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: center;
}

.timeline-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.timeline-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.progress-events {
  display: grid;
  gap: 8px;
}

.progress-event,
.trace-item {
  display: flex;
  gap: 10px;
  align-items: center;
}

.progress-event {
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-soft);
  font-size: 13px;
  color: var(--text-regular);
}

.trace-list {
  display: grid;
  gap: 12px;
}

.trace-item {
  align-items: flex-start;
}

.trace-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: var(--primary-color);
  background: rgba(18, 154, 116, 0.12);
}

.trace-icon.warning {
  color: var(--warning-color);
  background: rgba(245, 159, 0, 0.14);
}

.trace-icon.failed {
  color: var(--danger-color);
  background: rgba(214, 69, 65, 0.12);
}

.trace-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.trace-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.trace-title strong {
  font-size: 14px;
  color: var(--text-primary);
}

.trace-copy p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.trace-error {
  color: var(--danger-color) !important;
}
</style>
