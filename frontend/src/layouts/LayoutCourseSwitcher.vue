<template>
  <!-- Only render the trigger when course context exists, avoiding an empty header affordance. -->
  <n-dropdown
    v-if="visible && currentCourse"
    trigger="click"
    :options="courseOptions"
    @select="handleSelect"
  >
    <span class="course-selector">
      <AppIcon name="Reading" />
      <span class="course-name">{{ currentCourse.course_name }}</span>
      <AppIcon name="ChevronDown" class="dropdown-arrow" />
    </span>
  </n-dropdown>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { renderIcon } from '@/theme/icons'

// The command payload is either a full course object or the student-only "switch" sentinel action.
const props = defineProps({
  visible: { type: Boolean, default: false },
  currentCourse: { type: Object, default: null },
  courses: { type: Array, default: () => [] },
  userRole: { type: String, default: '' }
})

const emit = defineEmits(['change'])

const courseCommandMap = computed(() => {
  const commandMap = new Map()
  props.courses.forEach(course => {
    commandMap.set(`course:${course.course_id}`, course)
  })
  return commandMap
})

const courseOptions = computed(() => {
  const options = props.courses.map(course => ({
    label: course.course_name,
    key: `course:${course.course_id}`,
    icon: renderIcon(course.course_id === props.currentCourse?.course_id ? 'CheckCircle' : 'Reading')
  }))

  if (props.userRole === 'student') {
    options.push(
      { type: 'divider', key: 'divider' },
      { label: '切换课程', key: 'switch', icon: renderIcon('ArrowSync') }
    )
  }

  return options
})

const handleSelect = (key) => {
  if (key === 'switch') {
    emit('change', 'switch')
    return
  }
  const course = courseCommandMap.value.get(key)
  if (course) {
    emit('change', course)
  }
}
</script>

<style scoped>
/* Pill styling helps the current course read like navigational context rather than a plain button. */
.course-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 999px;
  cursor: pointer;
  color: var(--text-regular);
  background: rgba(15, 108, 189, 0.08);
  border: 1px solid rgba(15, 108, 189, 0.12);
  transition: all 0.3s;
}

.course-selector:hover {
  background: rgba(15, 108, 189, 0.12);
  color: var(--primary-color);
}

.course-name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-arrow {
  color: var(--text-secondary);
}
</style>
