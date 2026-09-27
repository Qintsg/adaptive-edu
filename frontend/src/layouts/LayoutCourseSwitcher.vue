<!-- 当前课程切换入口，未选课程时仍提供学生选课操作。 -->
<template>
  <!-- 学生未选课程时仍显示入口，方便进入选课页。 -->
  <n-dropdown
    v-if="visible && (currentCourse || userRole === 'student')"
    trigger="click"
    :options="courseOptions"
    @select="handleSelect"
  >
    <button class="course-selector" type="button" :aria-label="currentCourseLabel" :title="currentCourseLabel">
      <AppIcon name="Reading" />
      <span class="course-name">
        <span class="course-name-main">{{ currentCourse?.course_name || '选择课程' }}</span>
        <small v-if="hasDuplicateCurrentCourse && currentCourse?.class_name" class="course-class">
          {{ currentCourse.class_name }}
        </small>
      </span>
      <AppIcon name="ChevronDown" class="dropdown-arrow" />
    </button>
  </n-dropdown>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { renderIcon } from '@/theme/icons'

// 切换命令可以是课程对象，也可以是学生端的选课入口标识。
const props = defineProps({
  visible: { type: Boolean, default: false },
  currentCourse: { type: Object, default: null },
  courses: { type: Array, default: () => [] },
  userRole: { type: String, default: '' }
})

const emit = defineEmits(['change'])

/**
 * 为同一课程在不同班级的记录生成唯一菜单键。
 * :param {Object} course - 课程与班级摘要
 * :returns {string} 菜单键
 */
const getCourseKey = (course) => {
  const courseId = course?.course_id ?? course?.id ?? 'none'
  const classId = course?.class_id ?? course?.class_obj_id ?? 'none'
  return `course:${courseId}:class:${classId}`
}

const hasDuplicateCurrentCourse = computed(() => {
  if (!props.currentCourse) return false
  return props.courses.filter(course => (
    String(course.course_id) === String(props.currentCourse.course_id)
  )).length > 1
})

const currentCourseLabel = computed(() => {
  if (!props.currentCourse) return '选择课程'
  const className = props.currentCourse.class_name
  return className ? `切换当前课程：${props.currentCourse.course_name} · ${className}` : `切换当前课程：${props.currentCourse.course_name}`
})

const courseCommandMap = computed(() => {
  const commandMap = new Map()
  props.courses.forEach(course => {
    commandMap.set(getCourseKey(course), course)
  })
  return commandMap
})

const courseOptions = computed(() => {
  const options = props.courses.map(course => ({
    label: props.userRole === 'student' && course.class_name
      ? `${course.course_name} · ${course.class_name}`
      : course.course_name,
    key: getCourseKey(course),
    icon: renderIcon(getCourseKey(course) === getCourseKey(props.currentCourse) ? 'CheckCircle' : 'Reading')
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
/* 当前课程以胶囊样式显示为导航上下文。 */
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
  font: inherit;
}

.course-selector:hover {
  background: rgba(15, 108, 189, 0.12);
  color: var(--primary-color);
}

.course-name {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 150px;
  line-height: 1.2;
}

.course-name-main,
.course-class {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-class { margin-top: 2px; color: var(--text-secondary); font-size: 10px; }

.dropdown-arrow {
  color: var(--text-secondary);
}

@media (max-width: 640px) {
  .course-selector { padding: 8px 10px; }
  .course-name { max-width: min(25vw, 100px); }
}
</style>
