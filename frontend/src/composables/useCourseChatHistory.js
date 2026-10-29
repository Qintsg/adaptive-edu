/**
 * 文件描述：按用户和课程保存问答记录、草稿及选中知识点。
 * 项目名：adaptive-edu；文件名：useCourseChatHistory.js；作者：Qintsg；日期：2026-10-29。
 */
import { computed, onBeforeUnmount, watch } from 'vue'
import { useCourseStore } from '@/stores/course'
import { useUserStore } from '@/stores/user'

/**
 * 恢复并保存当前课程的问答界面。
 * :param messages: 问答消息引用。
 * :param draft: 输入草稿引用。
 * :param selectedPoint: 选中知识点引用。
 * :param selectedDetail: 知识点详情引用。
 * :returns: 保存会话的方法。
 */
export function useCourseChatHistory(messages, draft, selectedPoint = null, selectedDetail = null) {
  const userStore = useUserStore()
  const courseStore = useCourseStore()
  const defaults = messages.value.map(message => ({ ...message }))
  const key = computed(() => userStore.userId && courseStore.courseId
    ? `course-chat:${userStore.userId}:${courseStore.courseId}` : '')
  let activeKey = ''
  let active = true

  /**
   * 保存已完成的对话，并保留尚未完成的问题草稿。
   * :param completed: 当前回答是否已经完整返回。
   * :returns: 无。
   */
  function persist(completed = false) {
    if (!activeKey || !active) return
    const items = messages.value
    const pending = !completed && items.at(-1)?.pending
    const savedMessages = pending ? items.slice(0, -2) : items
    const previous = JSON.parse(localStorage.getItem(activeKey) || '{}')
    localStorage.setItem(activeKey, JSON.stringify({
      ...previous,
      messages: savedMessages.filter(item => item.content).map(item => ({ ...item, pending: false })),
      draft: pending ? items.at(-2)?.content || draft.value : draft.value,
      ...(selectedPoint ? { selectedPoint: selectedPoint.value } : {}),
      ...(selectedDetail ? { selectedDetail: selectedDetail.value } : {})
    }))
  }

  watch(key, nextKey => {
    persist()
    activeKey = nextKey
    if (!activeKey) return
    const raw = localStorage.getItem(activeKey)
    const saved = raw ? JSON.parse(raw) : null
    messages.value = saved?.messages?.length ? saved.messages : defaults.map(message => ({ ...message }))
    draft.value = saved?.draft || ''
    if (selectedPoint) selectedPoint.value = saved?.selectedPoint || null
    if (selectedDetail) selectedDetail.value = saved?.selectedDetail || null
  }, { immediate: true })
  watch([draft, ...(selectedPoint ? [selectedPoint] : [])], () => persist())
  onBeforeUnmount(() => {
    persist()
    active = false
  })
  return { persist }
}
