/**
 * 学生端 AI 问答流状态管理。
 *
 * :returns: 可响应 WebSocket 增量消息的问答状态。
 */
import { nextTick, onUnmounted, reactive, ref } from 'vue'
import { aiChat, createStudentAIChatSocket } from '@/api/student/ai'

const DEFAULT_STAGE_TEXT = '正在连接 AI 助手'
const HTTP_FALLBACK_STAGE_TEXT = '正在准备回答'

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeChunkText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value)
}

/**
 * 创建可响应增量写入的助手消息。
 *
 * :returns {object}: 助手消息。
 */
const createAssistantMessage = () => reactive({
  role: 'assistant',
  content: '',
  pending: true,
  sources: [],
  matchedPoint: null,
  mode: '',
  queryModes: [],
  keyPoints: [],
  streamed: false
})

const normalizeSourceList = (value) => Array.isArray(value) ? value : []

/**
 * 网络链路均不可用时，给出完整的课程学习引导。
 *
 * :param {string} questionText: 学生问题。
 * :param {object} payload: 当前课程与知识点上下文。
 * :returns {string}: 可直接显示的课程引导。
 */
export const buildCourseAnswer = (questionText, payload) => {
  const topic = normalizeText(payload.knowledge_point || payload.course_name) || '当前课程'
  return `关于“${questionText}”，可以先梳理${topic}中的核心概念和关键步骤，再对照课程资源中的示例完成一道练习。把具体题目、代码或解题过程补充进来后，还可以继续逐步分析。`
}

/**
 * 学生端 AI WebSocket 流式问答状态机。
 */
export function useStudentAIStream(options = {}) {
  const messages = options.messages || ref([])
  const loading = ref(false)
  const stageText = ref(DEFAULT_STAGE_TEXT)
  const activeSocket = ref(null)
  const lastMode = ref('graph_rag')
  const httpFallback = options.httpFallback || aiChat

  /**
   * 将本地课程引导作为完整回答写入消息。
   *
   * :param {object} assistantMessage: 助手消息。
   * :param {string} questionText: 学生问题。
   * :param {object} payload: 课程上下文。
   * :param {Function} onDone: 完成回调。
   * :returns {Promise<void>}: 无。
   */
  const applyCourseAnswer = async (assistantMessage, questionText, payload, onDone) => {
    const reply = buildCourseAnswer(questionText, payload)
    assistantMessage.content = reply
    assistantMessage.sources = []
    assistantMessage.matchedPoint = null
    assistantMessage.mode = 'course_rules'
    assistantMessage.streamed = false
    lastMode.value = 'course_rules'
    if (typeof onDone === 'function') {
      await onDone({ type: 'done', reply, mode: 'course_rules', streamed: false }, assistantMessage)
    }
  }

  const applyChatResult = async (assistantMessage, resultPayload, onDone) => {
    const streamPayload = {
      type: 'done',
      reply: normalizeText(resultPayload?.reply ?? resultPayload?.answer) || '暂无回复',
      sources: normalizeSourceList(resultPayload?.sources),
      matched_point: resultPayload?.matched_point || null,
      mode: normalizeText(resultPayload?.mode) || 'llm_fallback',
      query_modes: normalizeSourceList(resultPayload?.query_modes),
      key_points: normalizeSourceList(resultPayload?.key_points),
      streamed: false
    }
    assistantMessage.content = streamPayload.reply
    assistantMessage.sources = streamPayload.sources
    assistantMessage.matchedPoint = streamPayload.matched_point
    assistantMessage.mode = streamPayload.mode
    assistantMessage.queryModes = streamPayload.query_modes
    assistantMessage.keyPoints = streamPayload.key_points
    assistantMessage.streamed = false
    lastMode.value = assistantMessage.mode
    if (typeof onDone === 'function') await onDone(streamPayload, assistantMessage)
  }

  const runHttpFallback = async ({
    questionText,
    payload,
    history,
    assistantMessage,
    onDone
  }) => {
    if (!httpFallback) throw new Error('HTTP chat is unavailable')
    stageText.value = HTTP_FALLBACK_STAGE_TEXT
    const resultPayload = await httpFallback({
      ...payload,
      question: questionText,
      message: questionText,
      history
    })
    if (!normalizeText(resultPayload?.reply ?? resultPayload?.answer)) {
      throw new Error('HTTP chat returned an empty reply')
    }
    await applyChatResult(assistantMessage, resultPayload, onDone)
    return true
  }

  const scrollToBottom = async () => {
    await nextTick()
    if (typeof options.scrollToBottom === 'function') {
      await options.scrollToBottom()
    }
  }

  const closeSocket = () => {
    if (!activeSocket.value) return
    try {
      activeSocket.value.close()
    } catch {
      // 关闭失败不影响页面卸载。
    }
    activeSocket.value = null
  }

  const sendStreamMessage = async ({
    question,
    payload = {},
    history = [],
    assistantMessage = createAssistantMessage(),
    onDone
  }) => {
    const questionText = normalizeText(question)
    if (!questionText || loading.value) return null

    closeSocket()
    loading.value = true
    assistantMessage.pending = true
    stageText.value = DEFAULT_STAGE_TEXT
    const startedAt = performance.now()

    /**
     * 快速返回的问答也保留短暂可见的处理状态。
     *
     * :returns {Promise<void>}: 最短展示时间到达时完成。
     */
    const waitForMinimumPending = async () => {
      const remainingMs = 900 - (performance.now() - startedAt)
      if (remainingMs > 0) {
        await new Promise(resolveWait => window.setTimeout(resolveWait, remainingMs))
      }
    }

    let socket = null
    try {
      socket = createStudentAIChatSocket()
    } catch (error) {
      try {
        await runHttpFallback({ questionText, payload, history, assistantMessage, onDone })
      } catch (fallbackError) {
        console.warn('AI 问答链路不可用:', fallbackError || error)
        await applyCourseAnswer(assistantMessage, questionText, payload, onDone)
      }
      await waitForMinimumPending()
      loading.value = false
      assistantMessage.pending = false
      await scrollToBottom()
      return assistantMessage
    }

    activeSocket.value = socket
    let settled = false
    let receivedDone = false
    let receivedText = ''
    let handlingTransportFailure = false
    const pendingChunks = []
    const drainResolvers = []
    let displayFrame = 0

    /**
     * 每帧写入一小段已收到的文本，让快速返回的内容也能逐步呈现。
     *
     * :returns {void}: 无。
     */
    const flushDisplayQueue = () => {
      displayFrame = 0
      const count = Math.max(1, Math.ceil(pendingChunks.length / 12))
      assistantMessage.content += pendingChunks.splice(0, count).join('')
      void scrollToBottom()
      if (pendingChunks.length) {
        displayFrame = window.requestAnimationFrame(flushDisplayQueue)
        return
      }
      drainResolvers.splice(0).forEach(resolveDrain => resolveDrain())
    }

    /**
     * 将服务端 chunk 加入显示队列，不阻塞 WebSocket 接收。
     *
     * :param {string} chunkText: 服务端文本片段。
     * :returns {void}: 无。
     */
    const enqueueChunk = (chunkText) => {
      pendingChunks.push(chunkText)
      if (!displayFrame) displayFrame = window.requestAnimationFrame(flushDisplayQueue)
    }

    /**
     * 等待已收到的 chunk 全部显示，再处理完成事件。
     *
     * :returns {Promise<void>}: 队列清空时完成。
     */
    const waitForDisplayDrain = () => {
      if (!pendingChunks.length && !displayFrame) return Promise.resolve()
      return new Promise(resolveDrain => drainResolvers.push(resolveDrain))
    }

    /**
     * 完成消息替换流式正文时，丢弃尚未显示的旧文本。
     *
     * :returns {void}: 无。
     */
    const cancelDisplayQueue = () => {
      if (displayFrame) window.cancelAnimationFrame(displayFrame)
      displayFrame = 0
      pendingChunks.length = 0
      drainResolvers.splice(0).forEach(resolveDrain => resolveDrain())
    }

    return new Promise((resolve) => {
      const finish = async () => {
        if (settled) return
        settled = true
        loading.value = false
        assistantMessage.pending = false
        if (activeSocket.value === socket) activeSocket.value = null
        await scrollToBottom()
        resolve(assistantMessage)
      }

      const finishWithTransportFallback = async (error = null) => {
        if (settled || handlingTransportFailure) return
        handlingTransportFailure = true
        try {
          if (activeSocket.value === socket) activeSocket.value = null
          try {
            socket.close()
          } catch {
            // WebSocket 已处于关闭态时无需额外处理。
          }
          cancelDisplayQueue()
          assistantMessage.content = ''
          try {
            await runHttpFallback({ questionText, payload, history, assistantMessage, onDone })
          } catch (fallbackError) {
            console.warn('AI 问答链路不可用:', fallbackError || error)
            await applyCourseAnswer(assistantMessage, questionText, payload, onDone)
          }
        } finally {
          await waitForMinimumPending()
          await finish()
        }
      }

      socket.onopen = async () => {
        if (settled || handlingTransportFailure || receivedDone) return
        try {
          socket.send(JSON.stringify({
            ...payload,
            question: questionText,
            message: questionText,
            history
          }))
        } catch (error) {
          await finishWithTransportFallback(error)
        }
      }

      socket.onmessage = async (event) => {
        if (settled || handlingTransportFailure || receivedDone) return
        let streamPayload = {}
        try {
          streamPayload = JSON.parse(event.data || '{}')
        } catch {
          return
        }

        if (streamPayload.type === 'stage') {
          stageText.value = normalizeText(streamPayload.message) || DEFAULT_STAGE_TEXT
          return
        }

        if (streamPayload.type === 'chunk') {
          const chunkText = normalizeChunkText(streamPayload.content)
          if (!chunkText) return
          receivedText += chunkText
          stageText.value = '正在生成回答'
          enqueueChunk(chunkText)
          return
        }

        if (streamPayload.type === 'done') {
          receivedDone = true
          stageText.value = '正在整理回答'
          const finalReply = normalizeText(streamPayload.reply)
          if (finalReply && finalReply !== normalizeText(receivedText)) {
            cancelDisplayQueue()
          } else {
            await waitForDisplayDrain()
          }
          if (finalReply && finalReply !== normalizeText(assistantMessage.content)) {
            assistantMessage.content = finalReply
          }
          assistantMessage.sources = normalizeSourceList(streamPayload.sources)
          assistantMessage.matchedPoint = streamPayload.matched_point || null
          assistantMessage.mode = normalizeText(streamPayload.mode) || 'graph_rag'
          assistantMessage.queryModes = normalizeSourceList(streamPayload.query_modes)
          assistantMessage.keyPoints = normalizeSourceList(streamPayload.key_points)
          assistantMessage.streamed = Boolean(streamPayload.streamed)
          lastMode.value = assistantMessage.mode
          if (typeof onDone === 'function') await onDone(streamPayload, assistantMessage)
          socket.close()
          await waitForMinimumPending()
          await finish()
          return
        }

        if (streamPayload.type === 'error') {
          await finishWithTransportFallback(streamPayload)
        }
      }

      socket.onerror = async (event) => {
        if (receivedDone) return
        await finishWithTransportFallback(event)
      }

      socket.onclose = async (event) => {
        if (settled || handlingTransportFailure || receivedDone) return
        await finishWithTransportFallback(event)
      }
    })
  }

  onUnmounted(() => {
    closeSocket()
  })

  return {
    closeSocket,
    createAssistantMessage,
    lastMode,
    loading,
    messages,
    sendStreamMessage,
    stageText
  }
}
