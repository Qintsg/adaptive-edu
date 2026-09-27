/**
 * 答辩演示的四个角色流程：只通过真实浏览器页面执行点击与输入。
 */
import assert from 'node:assert/strict'

import { assertStudent2Baseline, completeQuestionnaire } from './assessment.mjs'
import { observeAIChatStream } from './stream-audit.mjs'

const AI_QUESTION = 'Spark SQL 和 DataFrame 有什么关系？'
const AI_WAIT_TIMEOUT_MS = 170000
const PROFILE_INPUT = '我是软件专业学生，想两周内掌握 Spark SQL，但 HDFS 和 MapReduce 基础不太好，喜欢视频、案例和练习。'
const LEARNING_TARGET = '补齐 Spark SQL 查询、DataFrame 操作和项目实操能力'

/**
 * 在登录页输入演示账号，密码始终留在密码型输入框中。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {string} username: 演示账号。
 * :param {string} password: 演示密码。
 * :param {string} role: 预期角色。
 * :returns {Promise<void>}: 无。
 */
async function login(capture, username, password, role) {
  const page = capture.page
  await page.goto(`${capture.options.baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(new RegExp(`/(${role}/|student/course-select)`), { timeout: 30000 })
  await page.locator('.sidebar-menu').waitFor({ timeout: 30000 })
}

/**
 * 从课程卡片选择指定课程。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {boolean} captureEntry: 是否截图选课入口。
 * :returns {Promise<void>}: 无。
 */
async function selectDemoCourse(capture, captureEntry) {
  const page = capture.page
  await page.goto(`${capture.options.baseUrl}/student/course-select`, { waitUntil: 'networkidle' })
  const card = page.locator('.course-card-wrapper').filter({
    hasText: capture.options.courseName
  }).first()
  await card.waitFor({ timeout: 30000 })
  if (captureEntry) {
    await capture.step('student2-course-entry', '这名学生已经加入课程，但尚未开始初始测评。')
  }
  await card.click()
  await page.getByRole('button', { name: '确认并进入课程' }).click()
  await page.waitForURL(/\/student\/dashboard/, { timeout: 30000 })
}

/**
 * 点击侧栏菜单并核对进入的路由。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {string} title: 菜单文字。
 * :param {string} route: 目标路由。
 * :returns {Promise<void>}: 无。
 */
async function clickMenu(capture, title, route) {
  const page = capture.page
  const header = page.locator('.sidebar-menu .n-menu-item-content-header')
  const target = header.getByText(title, { exact: true }).first()
  if (['在线作业', '初始评测'].includes(title) && !await target.isVisible().catch(() => false)) {
    await header.getByText('在线测评', { exact: true }).first().click()
  }
  await target.waitFor({ state: 'visible', timeout: 10000 })
  await target.click()
  await page.waitForURL(url => new URL(url).pathname === route, { timeout: 30000 })
}

/**
 * 菜单点击失败时记录障碍，再尝试直接打开同一页面继续取证。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {string} title: 菜单文字。
 * :param {string} route: 目标路由。
 * :returns {Promise<void>}: 无。
 */
async function openRoute(capture, title, route) {
  try {
    await clickMenu(capture, title, route)
  } catch (error) {
    capture.issues.push({ step: route, message: `侧栏点击失败，改为直接打开路由：${error}` })
    await capture.page.goto(`${capture.options.baseUrl}${route}`, { waitUntil: 'networkidle' })
    assert.equal(new URL(capture.page.url()).pathname, route, `路由跳转失败：${route}`)
  }
}

/**
 * 执行单个页面步骤；失败会留下截图并继续其他页面。
 *
 * :param {Object} capture: 当前取证会话。
 * :param {string} label: 英文步骤名。
 * :param {string} narration: 演示讲解词。
 * :param {Function} action: 页面交互。
 * :returns {Promise<boolean>}: 步骤是否成功。
 */
async function attempt(capture, label, narration, action) {
  try {
    await capture.step(label, narration, action)
    return true
  } catch (error) {
    await capture.captureFailure(label)
    return false
  }
}

/**
 * 等待学习画像中的 AI 建议正文出现，避免把进度条当作最终结果。
 *
 * :param {import('playwright').Page} page: 当前页面。
 * :returns {Promise<void>}: 无。
 */
async function waitForProfileSuggestions(page) {
  await page.waitForFunction(() => {
    const card = document.querySelector('.profile-view .ai-card')
    return Boolean(card?.querySelector('.suggestion-card'))
      && !card?.querySelector('.ai-loading')
  }, null, { timeout: AI_WAIT_TIMEOUT_MS })
}

/**
 * 等待测评报告的题号与对错标记真正写入折叠行。
 *
 * :param {import('playwright').Page} page: 当前页面。
 * :returns {Promise<void>}: 无。
 */
async function waitForAssessmentAnswerDetails(page) {
  await page.waitForFunction(() =>
    [...document.querySelectorAll('.assessment-report-view .n-collapse-item__header-main')]
      .some(element => element.textContent?.includes('第 1 题')),
  null, { timeout: AI_WAIT_TIMEOUT_MS })
}

/**
 * 演示 student1 已有学习记录的完整浏览路径。
 *
 * :param {Object} capture: 学生取证会话。
 * :returns {Promise<void>}: 无。
 */
export async function runStudent1(capture) {
  await login(capture, capture.options.accounts.student1.username,
    capture.options.accounts.student1.password, 'student')
  await selectDemoCourse(capture, false)
  await capture.step('student1-dashboard', '已有学习记录的学生从首页继续学习。')

  const pages = [
    ['knowledge-map', '知识图谱', '/student/knowledge-map', '知识图谱把课程知识点和学习状态放在同一张图上。'],
    ['profile', '学习画像', '/student/profile', '学习画像显示能力、习惯和知识掌握情况。'],
    ['learning-path', '学习路径', '/student/learning-path', '学习路径依据测评结果安排当前任务。']
  ]
  for (const [label, title, route, narration] of pages) {
    await attempt(capture, `student1-${label}`, narration, async () => {
      await openRoute(capture, title, route)
      if (label === 'profile') await waitForProfileSuggestions(capture.page)
    })
    if (label === 'knowledge-map') {
      const detailOpened = await attempt(capture, 'student1-knowledge-detail', '点开知识点可以查看关系与掌握情况。', async () => {
        await capture.page.locator('.graph-node').first().click()
        await capture.page.locator('.n-drawer').waitFor()
      })
      if (detailOpened) await capture.page.keyboard.press('Escape')
    }
  }

  await attempt(capture, 'student1-task', '从已完成节点进入复习任务，查看资源和练习。', async () => {
    await openRoute(capture, '学习路径', '/student/learning-path')
    const completed = capture.page.locator('.subway-station').filter({
      has: capture.page.locator('.station-dot.completed')
    }).first()
    await completed.click()
    await capture.page.getByRole('button', { name: '复习巩固' }).click()
    await capture.page.waitForURL(/\/student\/task\//, { timeout: 30000 })
    await capture.page.locator('.task-learning-view .intro-card').waitFor({ state: 'visible', timeout: 90000 })
    await capture.page.waitForFunction(() =>
      (document.querySelector('.task-learning-view .intro-card .intro-text')?.textContent?.trim().length || 0) >= 20,
    null, { timeout: 90000 })
  })

  await attempt(capture, 'student1-resources', '课程资源可以按章节和类型查看。',
    () => openRoute(capture, '课程资源', '/student/resources'))
  await attempt(capture, 'student1-ai-assistant', 'AI 助手可以先检索课程知识点，再回答课程问题。',
    () => openRoute(capture, 'AI助手', '/student/ai-assistant'))
  await attempt(capture, 'student1-ai-search', '这里检索 Spark SQL 基本操作知识点。', async () => {
    const keywordInput = capture.page.getByPlaceholder('输入知识点名称、概念或问题关键词')
    await keywordInput.fill('Spark SQL基本操作')
    await keywordInput.press('Enter')
    const target = capture.page.locator('.search-result-item').filter({
      has: capture.page.locator('strong').getByText('Spark SQL基本操作', { exact: true })
    }).first()
    await target.waitFor({ timeout: 30000 })
    await target.click()
  })
  if (capture.options.withAi) {
    await attempt(capture, 'student1-ai-answer', 'AI 助手结合课程知识解释 Spark SQL 和 DataFrame 的关系。', async () => {
      const streamAudit = observeAIChatStream(capture)
      await capture.page.getByPlaceholder('输入课程问题').fill(AI_QUESTION)
      await capture.page.getByRole('button', { name: '发送问题' }).click()
      await capture.page.waitForFunction(() =>
        document.querySelectorAll('.chat-message.assistant .message-content').length >= 2
        && !document.querySelector('.chat-message.assistant .typing'),
      null, { timeout: AI_WAIT_TIMEOUT_MS })
      const answer = (await capture.page.locator('.chat-message.assistant .message-content').last().innerText()).trim()
      assert.ok(answer.length >= 20, 'AI 回答为空或过短')
      if (capture.options.expectedAiAnswer) {
        assert.equal(answer, capture.options.expectedAiAnswer.trim(), 'AI 页面回答与预置结果不一致')
      }
      const stream = await streamAudit.finish(answer.length)
      capture.aiEvidence = { chat: { question: AI_QUESTION, answer, stream } }
    })
  }
  await attempt(capture, 'student1-agent-learning', '学生还可以按自己的目标生成课程学习资源。', async () => {
    await capture.page.goto(`${capture.options.baseUrl}/student/agent-learning`, { waitUntil: 'networkidle' })
    await capture.page.getByRole('button', { name: '生成资源包' }).first().waitFor()
    await capture.page.locator('.agent-form textarea').first().fill(PROFILE_INPUT)
    await capture.page.locator('.agent-form input').first().fill(LEARNING_TARGET)
  })
  if (capture.options.withAi) {
    await attempt(capture, 'student1-agent-profile', '先从学生的描述中提取学习目标和薄弱点。', async () => {
      const responsePromise = capture.page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/student/agent/profile-dialog', { timeout: AI_WAIT_TIMEOUT_MS })
      await capture.page.getByRole('button', { name: '提取学习信息' }).click()
      const response = await responsePromise
      assert.equal(response.status(), 200, '学习信息提取接口未成功')
      await capture.page.locator('.profile-chips').waitFor({ timeout: AI_WAIT_TIMEOUT_MS })
      capture.aiEvidence ||= {}
      capture.aiEvidence.profile = {
        input: PROFILE_INPUT,
        target: LEARNING_TARGET,
        response: await response.json(),
        visibleFields: await capture.page.locator('.profile-chips').innerText()
      }
    })
    await attempt(capture, 'student1-agent-package', '随后生成讲解、导图、练习、阅读和实操资源。', async () => {
      const responsePromise = capture.page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/student/agent/learning-package', { timeout: AI_WAIT_TIMEOUT_MS })
      await capture.page.getByRole('button', { name: '生成资源包' }).first().click()
      const response = await responsePromise
      assert.equal(response.status(), 200, '资源包接口未成功')
      await capture.page.waitForFunction(() =>
        document.querySelectorAll('.resource-grid .resource-card').length >= 5,
      null, { timeout: 90000 })
      capture.aiEvidence ||= {}
      capture.aiEvidence.package = {
        response: await response.json(),
        visibleResources: await capture.page.locator('.resource-grid .resource-card').allInnerTexts()
      }
    })
    const evidenceOpened = await attempt(capture, 'student1-agent-evidence', '资源卡片保留依据与质量提示。', async () => {
      await capture.page.locator('.resource-card .resource-actions button').first().click()
      await capture.page.locator('.n-drawer').waitFor({ timeout: 30000 })
    })
    if (evidenceOpened) await capture.page.keyboard.press('Escape')
    await attempt(capture, 'student1-agent-apply', '生成资源可以接入已有学习路径。', async () => {
      await capture.page.getByRole('button', { name: '应用到学习路径' }).click()
      await capture.page.waitForTimeout(1300)
    })
  }
  await attempt(capture, 'student1-exams', '在线作业列出待参加与已完成任务。',
    () => openRoute(capture, '在线作业', '/student/exams'))
  await attempt(capture, 'student1-completed-exams', '切到已完成作业，查看学习反馈入口。', async () => {
    await capture.page.getByText('已完成', { exact: true }).first().click()
    await capture.page.getByRole('button', { name: '查看报告' }).first().waitFor()
  })
  await attempt(capture, 'student1-feedback', '反馈报告展示得分、知识点和下一步建议。', async () => {
    await capture.page.getByRole('button', { name: '查看报告' }).first().click()
    await capture.page.waitForURL(/\/student\/feedback\//, { timeout: 30000 })
    await capture.page.waitForFunction(() => {
      const analysisCard = document.querySelector('.analysis-card')
      const status = analysisCard?.querySelector('.n-tag')?.textContent?.trim()
      const sectionText = analysisCard?.querySelector('.feedback-section')?.textContent?.trim() || ''
      const detailText = document.querySelector('.detail-card .n-collapse-item__header-main')?.textContent || ''
      return status === '已完成' && sectionText.length >= 20 && detailText.includes('第 1 题')
    }, null, { timeout: AI_WAIT_TIMEOUT_MS })
  })
}

/**
 * 演示 student2 从未测评入口到报告、画像与路径。
 *
 * :param {Object} capture: 学生取证会话。
 * :returns {Promise<void>}: 无。
 */
export async function runStudent2(capture) {
  await login(capture, capture.options.accounts.student2.username,
    capture.options.accounts.student2.password, 'student')
  await selectDemoCourse(capture, true)
  const baseline = await assertStudent2Baseline(capture.page, capture.options.baseUrl)
  capture.baseline = baseline
  await capture.step('student2-unassessed-dashboard', '新学生只有课程关系，首页会引导先做初始测评。')
  await capture.step('student2-assessment-entry', '初始测评包含知识、能力和学习习惯三项。',
    () => openRoute(capture, '初始评测', '/student/assessment'))
  await capture.step('student2-knowledge', '知识测评会覆盖这门课程的关键知识点。', async () => {
    await capture.page.getByRole('button', { name: '开始测评', exact: true }).click()
    await capture.page.waitForURL(/\/student\/assessment\/knowledge/, { timeout: 30000 })
  })
  if (!capture.options.student2Full) return

  capture.questionCounts = {}
  capture.questionCounts.knowledge = await completeQuestionnaire(capture, 'knowledge',
    '/api/student/assessments/initial/knowledge/submit')
  await capture.page.waitForURL(/\/student\/assessment\/report/, { timeout: 30000 })
  if (await capture.page.locator('.feedback-card .generating-hint').isVisible().catch(() => false)) {
    await capture.step('student2-knowledge-report-pending', '系统正在整理答题结果并生成学习建议。')
  }
  await capture.step('student2-knowledge-report', '报告展示知识点掌握度和学习建议。', async () => {
    await capture.page.locator('.feedback-card .generating-hint').waitFor({ state: 'hidden', timeout: AI_WAIT_TIMEOUT_MS })
    await capture.page.locator('.feedback-card .feedback-section').first().waitFor({ timeout: AI_WAIT_TIMEOUT_MS })
    await waitForAssessmentAnswerDetails(capture.page)
  })

  await capture.step('student2-ability', '能力评测记录阅读、推理等学习能力。', async () => {
    await openRoute(capture, '初始评测', '/student/assessment')
    await capture.page.getByRole('button', { name: '开始评测', exact: true }).click()
    await capture.page.waitForURL(/\/student\/assessment\/ability/, { timeout: 30000 })
  })
  capture.questionCounts.ability = await completeQuestionnaire(capture, 'ability',
    '/api/student/assessments/initial/ability/submit')
  await capture.page.waitForURL(/\/student\/assessment$/, { timeout: 30000 })

  await capture.step('student2-habit', '习惯问卷记录学习时间、节奏和资源偏好。', async () => {
    await capture.page.getByRole('button', { name: '开始问卷', exact: true }).click()
    await capture.page.waitForURL(/\/student\/assessment\/habit/, { timeout: 30000 })
  })
  capture.questionCounts.habit = await completeQuestionnaire(capture, 'habit',
    '/api/student/assessments/initial/habit/submit')
  await capture.page.waitForURL(/\/student\/assessment$/, { timeout: 30000 })
  await capture.step('student2-assessment-complete', '三项测评均已完成，接着查看综合结果。')
  const generateButton = capture.page.getByRole('button', { name: '生成学习画像' })
  if (await generateButton.isVisible().catch(() => false)) {
    await capture.step('student2-profile-generation', '系统将三项测评结果合并成学习画像。', async () => {
      await generateButton.click()
      await capture.page.waitForURL(/\/student\/profile/, { timeout: AI_WAIT_TIMEOUT_MS })
    })
    await openRoute(capture, '初始评测', '/student/assessment')
  }
  await capture.step('student2-final-report', '完整评测报告汇总三项结果。', async () => {
    await capture.page.getByRole('button', { name: '查看评测报告' }).click()
    await capture.page.waitForURL(/\/student\/assessment\/report/, { timeout: 30000 })
    await capture.page.locator('.score-card').waitFor({ timeout: 30000 })
    await waitForAssessmentAnswerDetails(capture.page)
  })
  await capture.step('student2-profile', '学习画像呈现学生特点和薄弱点。', async () => {
    await openRoute(capture, '学习画像', '/student/profile')
    await waitForProfileSuggestions(capture.page)
  })
  await capture.step('student2-learning-path', '学习路径把接下来的任务排成可执行顺序。',
    async () => {
      await openRoute(capture, '学习路径', '/student/learning-path')
      await capture.page.locator('.subway-station').first().waitFor({ timeout: AI_WAIT_TIMEOUT_MS })
    })
}

/**
 * 演示教师首页、课程、题库、资源和班级。
 *
 * :param {Object} capture: 教师取证会话。
 * :returns {Promise<void>}: 无。
 */
export async function runTeacher(capture) {
  await login(capture, capture.options.accounts.teacher.username,
    capture.options.accounts.teacher.password, 'teacher')
  await capture.step('teacher-dashboard', '教师首页汇总学生、课程、班级和题库情况。')
  for (const [label, title, route, narration] of [
    ['courses', '课程管理', '/teacher/courses', '教师可查看和管理自己负责的课程。'],
    ['questions', '题库管理', '/teacher/questions', '题库提供课程题目检索与管理。'],
    ['resources', '资源管理', '/teacher/resources', '课程资源汇总教材、课件和视频。'],
    ['classes', '班级管理', '/teacher/classes', '班级页展示学生和邀请码。']
  ]) {
    await attempt(capture, `teacher-${label}`, narration,
      () => openRoute(capture, title, route))
  }
}

/**
 * 演示管理员首页、用户、课程和班级。
 *
 * :param {Object} capture: 管理员取证会话。
 * :returns {Promise<void>}: 无。
 */
export async function runAdmin(capture) {
  await login(capture, capture.options.accounts.admin.username,
    capture.options.accounts.admin.password, 'admin')
  await capture.step('admin-dashboard', '管理员首页展示平台规模与最近活动。')
  for (const [label, title, route, narration] of [
    ['users', '用户管理', '/admin/users', '用户管理支持按账号和角色查找。'],
    ['courses', '课程管理', '/admin/courses', '管理员可查看平台课程。'],
    ['classes', '班级管理', '/admin/classes', '班级管理汇总课程对应班级。']
  ]) {
    await attempt(capture, `admin-${label}`, narration,
      () => openRoute(capture, title, route))
    if (label === 'users') {
      await attempt(capture, 'admin-user-search', '搜索演示学生账号，核对角色和状态。', async () => {
        await capture.page.getByPlaceholder('搜索用户名、姓名或邮箱').fill('student1')
        await capture.page.getByRole('button', { name: '搜索', exact: true }).click()
        await capture.page.locator('.app-adapter-table tbody tr').first().waitFor()
      })
    }
  }
}
