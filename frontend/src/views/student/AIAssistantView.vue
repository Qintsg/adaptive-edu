<!-- 学生课程问答页面：逐块呈现回答并保留请求中的状态。 -->
<template>
  <div class="ai-assistant-view">
    <div class="assistant-layout">
      <n-card class="search-panel" shadow="hover">
        <template #header>
          <div class="panel-header">
            <span>查找知识点</span>
          </div>
        </template>

        <div class="search-box">
          <n-input
            v-model="searchKeyword"
            placeholder="输入知识点名称、概念或问题关键词"
            clearable
            @keyup.enter="runSearch"
          >
            <template #append>
              <n-button :loading="searchLoading" @click="runSearch">搜索</n-button>
            </template>
          </n-input>
        </div>

        <div v-if="searchResults.length" class="search-results">
          <button
            v-for="pointItem in searchResults"
            :key="pointItem.point_id"
            class="search-result-item"
            :class="{ active: selectedPoint?.point_id === pointItem.point_id }"
            @click="selectPoint(pointItem)"
          >
            <span class="search-result-main">
              <strong>{{ pointItem.point_name }}</strong>
              <span>{{ pointItem.chapter || '未分章' }}</span>
            </span>
            <span class="search-result-meta">
              <n-tag size="small" type="success">掌握度 {{ Math.round((pointItem.mastery_rate || 0) * 100) }}%</n-tag>
            </span>
            <span class="search-result-summary">{{ pointItem.description || '暂无摘要' }}</span>
          </button>
        </div>
        <n-empty v-else description="输入关键词查找知识点" />

        <div v-if="selectedPointDetail" class="point-detail-card">
          <div class="detail-header">
            <h3>{{ selectedPointDetail.point_name }}</h3>
            <n-button link type="primary" @click="goToKnowledgeMap">查看图谱</n-button>
          </div>
          <p class="point-description">{{ selectedPointDetail.description || '暂无描述' }}</p>
          <div class="point-mastery">
            <span>当前掌握度</span>
            <n-progress :percentage="Math.round((selectedPointDetail.mastery_rate || 0) * 100)" :stroke-width="10" />
          </div>
          <div class="relation-groups">
            <div>
              <span class="relation-label">前置知识</span>
              <div class="relation-tags">
                <n-tag
                  v-for="item in selectedPointDetail.prerequisites || []"
                  :key="item.point_id || item"
                  size="small"
                  type="info"
                >
                  {{ item.point_name || item }}
                </n-tag>
                <span v-if="!(selectedPointDetail.prerequisites || []).length" class="empty-text">暂无</span>
              </div>
            </div>
            <div>
              <span class="relation-label">后续知识</span>
              <div class="relation-tags">
                <n-tag
                  v-for="item in selectedPointDetail.postrequisites || []"
                  :key="item.point_id || item"
                  size="small"
                  type="warning"
                >
                  {{ item.point_name || item }}
                </n-tag>
                <span v-if="!(selectedPointDetail.postrequisites || []).length" class="empty-text">暂无</span>
              </div>
            </div>
          </div>
        </div>
      </n-card>

      <n-card class="chat-panel" shadow="hover">
        <template #header>
          <div class="panel-header">
            <span>课程问答</span>
            <span v-if="chatLoading" class="chat-stage-status">{{ chatStageText }}</span>
          </div>
        </template>

        <div ref="chatScrollRef" class="chat-history">
          <div v-for="(messageItem, index) in chatMessages" :key="index" :class="['chat-message', messageItem.role]">
            <div class="message-bubble">
              <div v-if="messageItem.content" class="message-content" v-html="renderMarkdown(messageItem.content)" />
              <div v-if="messageItem.pending" class="typing" role="status" aria-live="polite">
                <span class="typing-stage-text">{{ chatStageText }}</span>
                <span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>
              </div>
              <div v-if="messageItem.matchedPoint" class="message-context">
                <span>命中知识点：{{ messageItem.matchedPoint.point_name }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="chat-composer">
          <n-input
            v-model="questionInput"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="输入课程问题"
            @keydown="handleComposerKeydown"
            @keyup.ctrl.enter="askQuestion"
          />
          <div class="composer-actions">
            <div class="composer-context">
              <n-tag v-if="selectedPoint" size="small" type="info">当前知识点：{{ selectedPoint.point_name }}</n-tag>
              <span v-else>未选知识点，将搜索当前课程。</span>
              <span class="composer-shortcut">Enter 发送 · Shift + Enter 换行</span>
            </div>
            <n-button type="primary" :loading="chatLoading" @click="askQuestion">发送问题</n-button>
          </div>
        </div>
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { appMessage } from '@/utils/feedback'

import { isApiErrorHandled } from '@/api'
import { searchGraphRAG } from '@/api/student/ai'
import { getKnowledgePointDetail } from '@/api/student/knowledge'
import { buildCourseAnswer, useStudentAIStream } from '@/composables/useStudentAIStream'
import { awaitAIResult } from '@/utils/aiLoading'
import { useCourseStore } from '@/stores/course'
import { renderMarkdown } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()
const courseStore = useCourseStore()

const searchKeyword = ref('')
const searchLoading = ref(false)
const searchResults = ref([])
const selectedPoint = ref(null)
const selectedPointDetail = ref(null)
const questionInput = ref('')
const chatScrollRef = ref(null)
const chatMessages = ref([
  {
    role: 'assistant',
    content: '可以先查找知识点，再继续提问；也可以直接问当前课程的问题。',
    sources: [],
    matchedPoint: null
  }
])

const ensureCourseSelected = () => {
  if (!courseStore.courseId) {
    appMessage.warning('请先选择课程后再使用 AI助手')
    router.push('/student/course-select')
    return false
  }
  return true
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatScrollRef.value) {
    chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
  }
}

const {
  createAssistantMessage,
  loading: chatLoading,
  sendStreamMessage,
  stageText: chatStageText
} = useStudentAIStream({
  messages: chatMessages,
  scrollToBottom
})

const handleComposerKeydown = (event) => {
  if (
    event.key !== 'Enter'
    || event.shiftKey
    || event.ctrlKey
    || event.altKey
    || event.metaKey
    || event.isComposing
  ) {
    return
  }

  event.preventDefault()
  void askQuestion()
}

const runSearch = async () => {
  if (!ensureCourseSelected()) return
  const keyword = searchKeyword.value.trim()
  if (!keyword) {
    appMessage.warning('请输入检索关键词')
    return
  }
  searchLoading.value = true
  try {
    const data = await awaitAIResult(searchGraphRAG({
      course_id: courseStore.courseId,
      query: keyword,
      limit: 8
    }))
    searchResults.value = data.matched_points || []
    if (searchResults.value.length) {
      await selectPoint(searchResults.value[0])
    } else {
      selectedPoint.value = null
      selectedPointDetail.value = null
    }
  } catch (error) {
    console.error('GraphRAG检索失败:', error)
    if (!isApiErrorHandled(error)) {
      appMessage.error('暂时无法搜索知识点，请稍后重试')
    }
  } finally {
    searchLoading.value = false
  }
}

const selectPoint = async (pointItem) => {
  selectedPoint.value = pointItem
  try {
    selectedPointDetail.value = await getKnowledgePointDetail(pointItem.point_id, courseStore.courseId, {
      includeGraphRag: false
    })
  } catch (error) {
    console.error('加载知识点详情失败:', error)
    selectedPointDetail.value = {
      point_id: pointItem.point_id,
      point_name: pointItem.point_name,
      description: pointItem.description || '',
      mastery_rate: pointItem.mastery_rate || 0,
      prerequisites: (pointItem.prerequisites || []).map(name => ({ point_name: name })),
      postrequisites: (pointItem.postrequisites || []).map(name => ({ point_name: name }))
    }
  }
}

const askQuestion = async () => {
  if (!ensureCourseSelected()) return
  const question = questionInput.value.trim()
  if (!question || chatLoading.value) {
    return
  }

  chatMessages.value.push({ role: 'user', content: question, sources: [], matchedPoint: null })
  questionInput.value = ''
  const assistantMessage = createAssistantMessage()
  chatMessages.value.push(assistantMessage)
  await scrollToBottom()

  try {
    await sendStreamMessage({
      question,
      assistantMessage,
      payload: {
        course_id: courseStore.courseId,
        point_id: selectedPoint.value?.point_id || null,
        knowledge_point: selectedPoint.value?.point_name || '',
        course_name: courseStore.courseName || ''
      },
      onDone: async (streamPayload) => {
        if (streamPayload.matched_point && (!selectedPoint.value || selectedPoint.value.point_id !== streamPayload.matched_point.point_id)) {
          await selectPoint(streamPayload.matched_point)
        }
      }
    })

  } catch (error) {
    console.error('GraphRAG问答失败:', error)
    assistantMessage.content = buildCourseAnswer(question, {
      knowledge_point: selectedPoint.value?.point_name || '',
      course_name: courseStore.courseName || ''
    })
    assistantMessage.pending = false
  } finally {
    await scrollToBottom()
  }
}

const goToKnowledgeMap = () => {
  if (!selectedPoint.value) {
    return
  }
  router.push('/student/knowledge-map')
}

onMounted(async () => {
  if (!ensureCourseSelected()) return
  const keyword = String(route.query.keyword || '').trim()
  const pointId = Number(route.query.pointId || 0)
  if (pointId) {
    selectedPoint.value = {
      point_id: pointId,
      point_name: keyword || '当前知识点'
    }
    await selectPoint(selectedPoint.value)
  }
  if (keyword) {
    searchKeyword.value = keyword
    await runSearch()
  }
})

</script>

<style scoped src="./AIAssistantView.css"></style>
