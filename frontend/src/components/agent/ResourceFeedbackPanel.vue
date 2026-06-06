<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { GeneratedLearningResource, ResourceFeedbackRequest } from '@/api/student/agent'

const props = defineProps<{
  show: boolean
  resource: GeneratedLearningResource | null
  courseId: number | null
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [resourceId: number, payload: ResourceFeedbackRequest]
}>()

const form = reactive({
  completed: true,
  rating: 5,
  usefulness: 'useful' as ResourceFeedbackRequest['usefulness'],
  difficulty: 'moderate' as ResourceFeedbackRequest['difficulty'],
  feedback: '',
  timeSpentMinutes: 20
})

watch(
  () => props.resource?.resource_id,
  () => {
    form.completed = true
    form.rating = 5
    form.usefulness = 'useful'
    form.difficulty = 'moderate'
    form.feedback = ''
    form.timeSpentMinutes = 20
  }
)

function submitFeedback(): void {
  if (!props.resource || !props.courseId) return
  emit('submit', props.resource.resource_id, {
    course_id: props.courseId,
    completed: form.completed,
    rating: form.rating,
    usefulness: form.usefulness,
    difficulty: form.difficulty,
    feedback: form.feedback,
    time_spent_seconds: Math.max(0, Number(form.timeSpentMinutes || 0)) * 60
  })
}
</script>

<template>
  <n-drawer
    :show="show"
    :width="420"
    placement="right"
    @update:show="value => emit('update:show', value)"
  >
    <n-drawer-content :title="resource ? `反馈：${resource.title}` : '学习反馈'">
      <n-form class="feedback-form" label-placement="top">
        <n-form-item label="学习状态">
          <n-switch v-model:value="form.completed">
            <template #checked>已完成</template>
            <template #unchecked>学习中</template>
          </n-switch>
        </n-form-item>

        <n-form-item label="评分">
          <n-rate v-model:value="form.rating" />
        </n-form-item>

        <n-form-item label="有用性">
          <n-segmented
            v-model:value="form.usefulness"
            :options="[
              { label: '有帮助', value: 'useful' },
              { label: '一般', value: 'neutral' },
              { label: '无帮助', value: 'not_useful' }
            ]"
          />
        </n-form-item>

        <n-form-item label="难度感受">
          <n-segmented
            v-model:value="form.difficulty"
            :options="[
              { label: '偏简单', value: 'easy' },
              { label: '适中', value: 'moderate' },
              { label: '偏困难', value: 'hard' }
            ]"
          />
        </n-form-item>

        <n-form-item label="学习耗时">
          <n-input-number
            v-model:value="form.timeSpentMinutes"
            :min="0"
            :max="480"
            :step="5"
            class="time-input"
          >
            <template #suffix>分钟</template>
          </n-input-number>
        </n-form-item>

        <n-form-item label="补充反馈">
          <n-input
            v-model:value="form.feedback"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 7 }"
            maxlength="500"
            show-count
            placeholder="记录这份资源是否解决了你的问题，或者还缺什么。"
          />
        </n-form-item>

        <div class="feedback-actions">
          <n-button @click="emit('update:show', false)">取消</n-button>
          <n-button type="primary" :loading="loading" :disabled="!resource || !courseId" @click="submitFeedback">
            提交反馈
          </n-button>
        </div>
      </n-form>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.feedback-form {
  display: grid;
  gap: 4px;
}

.time-input {
  width: 180px;
}

.feedback-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}
</style>
