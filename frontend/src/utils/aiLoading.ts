/**
 * AI 请求加载状态的最短可见时间。
 *
 * 请求仍按原顺序执行；快速响应时补足短暂等待，便于用户看清处理状态。
 */

/**
 * 等待异步请求并保留最短加载时间。
 *
 * :param {Promise<T>} requestPromise: 已发起的请求。
 * :param {number} minimumMs: 最短加载毫秒数。
 * :returns {Promise<T>}: 请求结果。
 */
export async function awaitAIResult<T>(requestPromise: Promise<T>, minimumMs = 900): Promise<T> {
  const startedAt = performance.now()
  try {
    return await requestPromise
  } finally {
    const remainingMs = minimumMs - (performance.now() - startedAt)
    if (remainingMs > 0) {
      await new Promise(resolve => window.setTimeout(resolve, remainingMs))
    }
  }
}
