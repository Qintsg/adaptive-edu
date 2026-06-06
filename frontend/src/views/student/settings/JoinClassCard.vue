<template>
  <n-card class="settings-card" shadow="hover">
    <template #header>
      <span>加入班级</span>
    </template>

    <n-form :model="joinClassForm" label-width="100px" class="settings-form" @submit.prevent="joinClassByInvitation">
      <n-form-item label="邀请码">
        <n-input v-model="joinClassForm.invitationCode" placeholder="请输入班级邀请码" clearable maxlength="20"
          @keyup.enter="joinClassByInvitation" />
      </n-form-item>

      <n-form-item>
        <n-button type="primary" :loading="joiningClass" :disabled="!normalizeText(joinClassForm.invitationCode)"
          @click="joinClassByInvitation">加入班级</n-button>
      </n-form-item>
    </n-form>
  </n-card>
</template>

<script setup>
/**
 * 学生设置页的班级邀请码加入卡片。
 */
import { reactive, ref } from 'vue'
import { appMessage } from '@/utils/feedback'

import { joinClass as apiJoinClass } from '@/api/student/class'
import { useCourseStore } from '@/stores/course'
import { useUserStore } from '@/stores/user'

const courseStore = useCourseStore()
const userStore = useUserStore()
const joiningClass = ref(false)
const joinClassForm = reactive({
  invitationCode: ''
})

const normalizeText = (rawValue) => {
  if (rawValue === null || rawValue === undefined) return ''
  return String(rawValue).trim()
}

const refreshLearningContext = async () => {
  courseStore.invalidateCoursesCache()
  await Promise.allSettled([
    userStore.fetchUserInfo(),
    courseStore.fetchCourses()
  ])
}

const joinClassByInvitation = async () => {
  const invitationCode = normalizeText(joinClassForm.invitationCode)
  if (!invitationCode) {
    appMessage.warning('请输入班级邀请码')
    return
  }

  joiningClass.value = true
  try {
    const joinedClass = await apiJoinClass({ code: invitationCode })
    const joinedClassName = normalizeText(joinedClass?.class_name ?? joinedClass?.name)
    joinClassForm.invitationCode = ''
    await refreshLearningContext()
    appMessage.success(joinedClassName ? `已加入${joinedClassName}` : '加入班级成功')
  } catch (error) {
    console.error('加入班级失败:', error)
    if (!error?.handledByInterceptor) {
      appMessage.error(error?.message || '加入失败，请检查邀请码是否正确')
    }
  } finally {
    joiningClass.value = false
  }
}
</script>

<style scoped>
.settings-card {
  margin-bottom: 20px;
}

.settings-form {
  max-width: 500px;
}
</style>
