/**
 * 在最终空密钥网页核对固定 AI 回答，并保存可用于正式录屏的纯文本。
 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { marked } from 'marked'
import { chromium } from 'playwright'

import { DEFAULT_PASSWORDS } from './browser-audit/constants.mjs'

const BASE_URL = 'http://127.0.0.1:18080'
const QUESTION = 'Spark SQL 和 DataFrame 有什么关系？'
const POINT_NAME = 'Spark SQL基本操作'
const PRESET_FILE = path.resolve('../demo/presets/deepseek-v41-flash.jsonl')
const EVIDENCE_DIR = path.join(os.homedir(), 'Desktop', 'adaptive-edu-defense-20260927', 'evidence')

/**
 * 计算证据内容的 SHA256。
 *
 * :param {string} value: 输入文本。
 * :returns {string}: SHA256 十六进制摘要。
 */
function sha256(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

/**
 * 读取已经经过真实模型采样的固定问答。
 *
 * :returns {Promise<string>}: 彩排原始回答。
 */
async function readVerifiedAnswer() {
  const lines = (await fs.readFile(PRESET_FILE, 'utf8')).split(/\r?\n/).filter(Boolean)
  const entries = lines.map(line => JSON.parse(line))
  const matches = entries.filter(entry => entry.model === 'deepseek-flash'
    && entry.kind === 'api_json' && entry.call_type === 'student_chat')
  assert.equal(matches.length, 1, '固定 student_chat 彩排条目应当恰好一条')
  const answer = String(matches[0].response?.reply || '')
  assert.ok(answer.length >= 20, '真实彩排回答为空')
  return answer
}

/**
 * 登录 student1 并打开真实 AI 助手页面。
 *
 * :param {import('playwright').Page} page: 浏览器页面。
 * :returns {Promise<void>}: 无。
 */
async function openAssistant(page) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入用户名').fill('student1')
  await page.getByPlaceholder('请输入密码').fill(
    process.env.DEMO_STUDENT1_PASSWORD || DEFAULT_PASSWORDS.student1
  )
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(/\/student\//, { timeout: 30000 })
  await page.goto(`${BASE_URL}/student/course-select`, { waitUntil: 'networkidle' })
  const courseCard = page.locator('.course-card-wrapper').filter({ hasText: '大数据技术与应用' }).first()
  await courseCard.waitFor()
  await courseCard.click()
  await page.getByRole('button', { name: '确认并进入课程' }).click()
  await page.waitForURL(/\/student\/dashboard/, { timeout: 30000 })
  await page.goto(`${BASE_URL}/student/ai-assistant`, { waitUntil: 'networkidle' })
  await page.getByPlaceholder('输入知识点名称、概念或问题关键词').waitFor()
}

/**
 * 在页面中选定与彩排完全相同的知识点。
 *
 * :param {import('playwright').Page} page: 浏览器页面。
 * :returns {Promise<number>}: 后端知识点 ID。
 */
async function selectVerifiedPoint(page) {
  await page.getByPlaceholder('输入知识点名称、概念或问题关键词').fill(POINT_NAME)
  const [response] = await Promise.all([
    page.waitForResponse(value =>
      new URL(value.url()).pathname.includes('/api/student/ai/graph-rag/search'),
    { timeout: 30000 }),
    page.getByPlaceholder('输入知识点名称、概念或问题关键词').press('Enter')
  ])
  assert.equal(response.status(), 200, '知识点搜索接口失败')
  const payload = (await response.json()).data || {}
  const point = (payload.matched_points || []).find(item => item.point_name === POINT_NAME)
  assert.ok(point, '页面搜索结果缺少彩排知识点')
  const match = page.locator('.search-result-item').filter({
    has: page.locator('strong').getByText(POINT_NAME, { exact: true })
  }).first()
  await match.click()
  await page.getByText(`当前知识点：${POINT_NAME}`).waitFor()
  return Number(point.point_id)
}

/**
 * 从页面提出固定问题并读取最终显示文本。
 *
 * :param {import('playwright').Page} page: 浏览器页面。
 * :returns {Promise<string>}: 浏览器显示的纯文本。
 */
async function askFixedQuestion(page) {
  await page.getByPlaceholder('输入课程问题').fill(QUESTION)
  await page.getByRole('button', { name: '发送问题' }).click()
  await page.waitForFunction(() =>
    document.querySelectorAll('.chat-message.assistant .message-content').length >= 2
    && !document.querySelector('.chat-message.assistant .typing'),
  null, { timeout: 90000 })
  return (await page.locator('.chat-message.assistant .message-content').last().innerText())
    .replace(/\r\n?/g, '\n').trim()
}

/**
 * 用前端相同的 marked 设置把彩排 Markdown 转成页面纯文本。
 *
 * :param {import('playwright').Page} page: 浏览器页面。
 * :param {string} answer: 彩排原始回答。
 * :returns {Promise<string>}: 理论页面显示文本。
 */
async function renderExpectedText(page, answer) {
  marked.setOptions({ breaks: true, gfm: true })
  const html = marked.parse(answer)
  return page.evaluate(value => {
    const element = document.createElement('div')
    element.className = 'message-content'
    element.innerHTML = value
    document.body.appendChild(element)
    const rendered = element.innerText.replace(/\r\n?/g, '\n').trim()
    element.remove()
    return rendered
  }, html)
}

/**
 * 执行同镜像页面校验，证据只写哈希与来源信息。
 *
 * :returns {Promise<void>}: 无。
 */
async function main() {
  const presetAnswer = await readVerifiedAnswer()
  await fs.mkdir(EVIDENCE_DIR, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  const websocketDone = []
  const httpDone = []
  page.on('websocket', socket => socket.on('framereceived', frame => {
    try {
      const payload = JSON.parse(frame.payload)
      if (payload.type === 'done') websocketDone.push(payload)
    } catch { /* 其他帧交给页面处理。 */ }
  }))
  page.on('response', async response => {
    if (!/\/api\/student\/ai\/(?:chat|graph-rag\/ask)$/.test(new URL(response.url()).pathname)) return
    try { httpDone.push((await response.json()).data || {}) } catch { /* 非 JSON 响应不参与核对。 */ }
  })
  try {
    await openAssistant(page)
    const pointId = await selectVerifiedPoint(page)
    assert.equal(pointId, 26, '页面选中的知识点与彩排不一致')
    const uiText = await askFixedQuestion(page)
    const renderedPreset = await renderExpectedText(page, presetAnswer)
    const screenshot = path.join(EVIDENCE_DIR, 'student1-ai-answer-verified.png')
    await page.screenshot({ path: screenshot, fullPage: false })
    assert.equal(uiText, renderedPreset, '页面文字与真实 DeepSeek 彩排内容不一致')
    const source = websocketDone.at(-1) || httpDone.at(-1) || {}
    assert.equal(source.generation_source, 'verified_ai_preset', '页面响应未命中真实彩排预置')
    const answerPath = path.join(EVIDENCE_DIR, 'expected-ai-answer.txt')
    await fs.writeFile(answerPath, uiText, 'utf8')
    const evidence = {
      model: 'deepseek-flash',
      pointId,
      transport: websocketDone.length ? 'websocket' : 'http',
      generationSource: source.generation_source,
      originalAnswerSha256: sha256(presetAnswer),
      renderedAnswerSha256: sha256(renderedPreset),
      pageAnswerSha256: sha256(uiText),
      exactPageMatch: true,
      screenshot,
      expectedAnswerFile: answerPath,
    }
    await fs.writeFile(path.join(EVIDENCE_DIR, 'ai-answer-ui-verify.json'),
      `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
    process.stdout.write(`${JSON.stringify(evidence)}\n`)
  } catch (error) {
    await page.screenshot({ path: path.join(EVIDENCE_DIR, 'ai-answer-ui-check-error.png'), fullPage: true })
    process.stderr.write(`browser_url=${page.url()}\n`)
    throw error
  } finally {
    await browser.close()
  }
}

main().catch(error => {
  process.stderr.write(`${error?.stack || error}\n`)
  process.exitCode = 1
})
