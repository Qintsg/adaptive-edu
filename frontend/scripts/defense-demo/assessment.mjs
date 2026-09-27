/**
 * 答辩演示测评操作：从真实题目页面逐题点击并核对提交结果。
 */
import assert from 'node:assert/strict'

/**
 * 从当前会话读取学生所选课程和访问令牌。
 *
 * :param {import('playwright').Page} page: 当前页面。
 * :returns {Promise<Object>}: 课程 ID 和令牌。
 */
async function getStudentSession(page) {
  const session = await page.evaluate(() => {
    const raw = localStorage.getItem('current_course')
    const course = raw ? JSON.parse(raw) : null
    return {
      courseId: course?.course_id ?? course?.id,
      token: localStorage.getItem('access_token') || sessionStorage.getItem('access_token')
    }
  })
  assert.ok(session.courseId, '当前学生没有选定课程')
  assert.ok(session.token, '当前学生缺少访问令牌')
  return session
}

/**
 * 校验 student2 只有选课数据，尚未完成任何初始测评。
 *
 * :param {import('playwright').Page} page: 当前页面。
 * :param {string} baseUrl: 站点地址。
 * :returns {Promise<Object>}: 课程和测评状态。
 */
export async function assertStudent2Baseline(page, baseUrl) {
  const session = await getStudentSession(page)
  const response = await page.context().request.get(
    `${baseUrl}/api/student/assessments/status?course_id=${session.courseId}`,
    { headers: { Authorization: `Bearer ${session.token}` } }
  )
  assert.equal(response.status(), 200, '无法核对 student2 的未测评基线')
  const body = await response.json()
  const status = body.data || {}
  for (const key of ['knowledge_done', 'ability_done', 'habit_done']) {
    assert.equal(Boolean(status[key]), false, `student2 的 ${key} 已完成，不能重录初测`)
  }
  return { courseId: session.courseId, status }
}

/**
 * 根据当前题型用真实鼠标或键盘输入一个演示答案。
 *
 * :param {import('playwright').Page} page: 当前测评页面。
 * :returns {Promise<void>}: 无。
 */
async function answerVisibleQuestion(page) {
  const content = page.locator('.question-content')
  const radio = content.locator('.n-radio.option-item')
  const checkbox = content.locator('.n-checkbox.option-item')
  if (await radio.count()) {
    await radio.first().click()
    return
  }
  if (await checkbox.count()) {
    await checkbox.first().click()
    return
  }
  const textInput = content.locator('textarea, input').first()
  if (await textInput.count()) {
    await textInput.fill('结合课程材料完成分析和实践。')
    return
  }
  throw new Error(`当前题型无法自动作答：${await content.innerText()}`)
}

/**
 * 完成一组测评题目，并在首题、中途和末题留下视觉证据。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {string} kind: knowledge、ability 或 habit。
 * :param {string} submitPath: 提交接口路径。
 * :returns {Promise<number>}: 实际答题数。
 */
export async function completeQuestionnaire(capture, kind, submitPath) {
  const page = capture.page
  const label = { knowledge: '知识测评', ability: '能力评测', habit: '习惯问卷' }[kind]
  assert.ok(label, `未知测评类型：${kind}`)
  await page.locator('.question-content .option-item, .question-content input, .question-content textarea')
    .first().waitFor({ timeout: 30000 })
  const totalText = await page.locator('.question-card .card-header').first().innerText()
  const fraction = totalText.match(/1\s*\/\s*(\d+)/)
  const expected = fraction ? Number(fraction[1]) : null
  let answered = 0
  let halfwayCaptured = false

  for (let index = 0; index < 200; index += 1) {
    await answerVisibleQuestion(page)
    answered += 1
    const isLast = await page.getByRole('button', { name: '提交', exact: true }).count() > 0
    if (!halfwayCaptured && expected && answered >= Math.ceil(expected / 2) && !isLast) {
      await capture.step(`${kind}-halfway`, `${label}已经完成一半，答题卡会同步记录进度。`)
      halfwayCaptured = true
    }
    if (isLast) {
      await capture.step(`${kind}-last-question`, `${label}来到最后一题，提交后立即查看结果。`)
      const responsePromise = page.waitForResponse(response =>
        new URL(response.url()).pathname.includes(submitPath), { timeout: 90000 })
      await page.getByRole('button', { name: '提交', exact: true }).click()
      const response = await responsePromise
      assert.equal(response.status(), 200, `${label}提交失败：HTTP ${response.status()}`)
      break
    }
    await page.getByRole('button', { name: '下一题', exact: true }).click()
    await page.waitForTimeout(capture.options.questionPauseMs)
  }

  assert.ok(answered < 200, `${label}超过 200 题，已停止自动点击`)
  if (expected) assert.equal(answered, expected, `${label}实际作答数与页面题量不符`)
  return answered
}
