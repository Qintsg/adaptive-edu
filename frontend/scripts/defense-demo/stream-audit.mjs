/**
 * AI 助手 WebSocket 取证：区分实时模型分段与事后拆开的完整回答。
 */
import assert from 'node:assert/strict'

const CHAT_SOCKET_PATH = '/ws/student/ai/chat'
const INCREMENTAL_SCREENSHOT = '09a-student1-ai-incremental.png'

/**
 * 监听一次课程问答的 WebSocket 帧，并在正文仍在生成时保存画面。
 *
 * :param {Object} capture: 当前浏览器取证会话。
 * :returns {Object}: 可在回答结束后读取的取证句柄。
 */
export function observeAIChatStream(capture) {
  const page = capture.page
  const startMs = Date.now()
  const chunks = []
  let socketCount = 0
  let donePayload = null
  let doneAtMs = null
  let partialCapturePromise = null
  let partialCaptureError = null
  let partialScreenshot = null
  let partialChars = 0

  /**
   * 在消息尚处于生成状态时截取一张真实页面。
   *
   * :returns {Promise<void>}: 无。
   */
  async function capturePartialAnswer() {
    await page.waitForFunction(() => {
      const messages = document.querySelectorAll('.chat-message.assistant')
      const current = messages[messages.length - 1]
      return Boolean(current?.querySelector('.typing')?.getClientRects().length)
        && Boolean(current?.querySelector('.message-content')?.textContent?.trim())
    }, null, { timeout: 10000 })
    const current = page.locator('.chat-message.assistant').last()
    partialChars = (await current.locator('.message-content').innerText()).trim().length
    assert.ok(await current.locator('.typing').isVisible(), '截屏前 AI 正文已结束生成')
    partialScreenshot = await capture.saveAuxiliaryScreenshot(INCREMENTAL_SCREENSHOT)
    assert.ok(await current.locator('.typing').isVisible(), '截屏时 AI 正文已结束生成')
  }

  /**
   * 记录一次服务器帧与到达时间。
   *
   * :param {Object} frame: Playwright WebSocket 帧。
   * :returns {void}: 无。
   */
  function onFrame(frame) {
    let payload
    try {
      payload = JSON.parse(String(frame.payload))
    } catch {
      return
    }
    if (payload.type === 'chunk' && String(payload.content || '')) {
      chunks.push({ atMs: Date.now() - startMs, chars: String(payload.content).length })
      if (capture.options.requireLiveStream && !partialCapturePromise) {
        partialCapturePromise = capturePartialAnswer().catch(error => {
          partialCaptureError = error
        })
      }
    }
    if (payload.type === 'done') {
      donePayload = payload
      doneAtMs = Date.now() - startMs
    }
  }

  /**
   * 仅监听课程 AI 助手使用的 WebSocket。
   *
   * :param {Object} socket: Playwright WebSocket 对象。
   * :returns {void}: 无。
   */
  function onSocket(socket) {
    if (new URL(socket.url()).pathname !== CHAT_SOCKET_PATH) return
    socketCount += 1
    socket.on('framereceived', onFrame)
  }

  page.on('websocket', onSocket)
  return {
    /**
     * 完成监听并校验真正的实时增量显示。
     *
     * :param {number} finalChars: 最终页面回答长度。
     * :returns {Promise<Object>}: 分段数量、时间与来源记录。
     */
    async finish(finalChars) {
      page.off('websocket', onSocket)
      if (partialCapturePromise) await partialCapturePromise
      if (partialCaptureError) throw partialCaptureError
      const firstChunkAtMs = chunks[0]?.atMs ?? null
      const lastChunkAtMs = chunks.at(-1)?.atMs ?? null
      const result = {
        transport: socketCount ? 'websocket' : 'none',
        socketCount,
        chunkCount: chunks.length,
        startedAt: new Date(startMs).toISOString(),
        firstChunkAt: firstChunkAtMs === null ? null : new Date(startMs + firstChunkAtMs).toISOString(),
        completedAt: doneAtMs === null ? null : new Date(startMs + doneAtMs).toISOString(),
        firstChunkAtMs,
        lastChunkAtMs,
        doneAtMs,
        chunkSpanMs: firstChunkAtMs === null ? null : lastChunkAtMs - firstChunkAtMs,
        streamed: donePayload?.streamed === true,
        generationSource: String(donePayload?.generation_source || ''),
        demoFallback: donePayload?.demo_fallback === true,
        partialScreenshot,
        partialChars,
        finalChars
      }
      if (capture.options.requireLiveStream) {
        assert.equal(result.transport, 'websocket', '未建立 AI 助手 WebSocket')
        assert.equal(result.generationSource, 'live_model', '回答未由实时模型生成')
        assert.equal(result.demoFallback, false, '实时调用已转为备用回答')
        assert.equal(result.streamed, true, '服务端未标记真实流式回答')
        assert.ok(result.chunkCount >= 2, '模型回答没有至少两个分段')
        assert.ok(result.chunkSpanMs >= 80, '多个分段同时到达，未形成可见增量输出')
        assert.ok(result.partialScreenshot, '没有在正文生成中保存截图')
        assert.ok(result.partialChars > 0 && result.partialChars < finalChars,
          '增量截图中的正文不是最终回答的一部分')
      }
      return result
    }
  }
}
