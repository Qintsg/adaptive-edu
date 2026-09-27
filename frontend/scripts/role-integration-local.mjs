/**
 * 本机 Docker 数据库联调：分别模拟访客、新学生、已完成学生、受限学生、教师和管理员。
 * 仅连接 localhost 开发服务，不记录令牌或密码。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright'

import { DEFAULT_PASSWORDS } from './browser-audit/constants.mjs'

const frontendUrl = 'http://127.0.0.1:3000'
const outputDir = path.resolve('../output/role-integration-20260925')
const browser = await chromium.launch({ headless: true })
const results = []

/**
 * 创建角色隔离的浏览器会话。
 * :returns {Promise<Object>} 浏览器上下文、页面及控制台错误。
 */
async function newSession() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return { context, page, errors }
}

/**
 * 在真实登录页面获取当前角色会话。
 * :param {Object} session - 浏览器会话。
 * :param {string} username - 本地测试用户名。
 * :param {string} password - 本地测试密码。
 * :param {string} role - 期望角色路径。
 * :returns {Promise<string>} 仅在内存中使用的访问令牌。
 */
async function login(session, username, password, role) {
  await session.page.goto(`${frontendUrl}/login`, { waitUntil: 'networkidle' })
  await session.page.getByPlaceholder('请输入用户名').fill(username)
  await session.page.getByPlaceholder('请输入密码').fill(password)
  await session.page.getByRole('button', { name: '登录', exact: true }).click()
  await session.page.waitForURL(new RegExp(`/${role}/`), { timeout: 30000 })
  const token = await session.page.evaluate(() => {
    for (const store of [localStorage, sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.toLowerCase().includes('access')) return store.getItem(key)
      }
    }
    return null
  })
  assert.ok(token, `${username} 缺少访问令牌`)
  return token
}

/**
 * 发起带角色令牌的真实 API 请求。
 * :param {Object} session - 浏览器会话。
 * :param {string} token - 访问令牌。
 * :param {string} route - API 路径。
 * :param {Object|null} body - POST 正文，为 null 时使用 GET。
 * :returns {Promise<Object>} 状态码及数据体。
 */
async function requestAs(session, token, route, body = null) {
  const options = { headers: { Authorization: `Bearer ${token}` } }
  const response = body === null
    ? await session.context.request.get(`${frontendUrl}${route}`, options)
    : await session.context.request.post(`${frontendUrl}${route}`, { ...options, data: body })
  return { status: response.status(), body: await response.json() }
}

/**
 * 选择一门课程并进入学生首页。
 * :param {Object} session - 浏览器会话。
 * :param {string} courseName - 课程名称。
 * :returns {Promise<void>} 无。
 */
async function selectCourse(session, courseName) {
  await session.page.goto(`${frontendUrl}/student/course-select`, { waitUntil: 'networkidle' })
  await session.page.locator('.course-card-wrapper', { hasText: courseName }).first().click()
  await session.page.getByRole('button', { name: '确认并进入课程' }).click()
  await session.page.waitForURL(/\/student\/dashboard/, { timeout: 30000 })
}

/**
 * 执行并记录一个角色场景。
 * :param {string} role - 场景名称。
 * :param {Function} action - 浏览器操作。
 * :returns {Promise<void>} 无。
 */
async function runRole(role, action) {
  const session = await newSession()
  try {
    const detail = await action(session)
    results.push({ role, ok: true, detail, browserErrors: session.errors })
  } catch (error) {
    results.push({ role, ok: false, error: String(error), browserErrors: session.errors })
    throw error
  } finally {
    await session.context.close()
  }
}

try {
  await fs.mkdir(outputDir, { recursive: true })

  await runRole('guest', async session => {
    await session.page.goto(`${frontendUrl}/student/dashboard`, { waitUntil: 'networkidle' })
    await session.page.waitForURL(/\/login/, { timeout: 15000 })
    const response = await session.context.request.get(
      `${frontendUrl}/api/student/assessments/initial/knowledge?course_id=3`
    )
    assert.equal(response.status(), 401)
    assert.deepEqual(session.errors, [])
    return { guardedRoute: new URL(session.page.url()).pathname, apiStatus: 401 }
  })

  await runRole('new-student', async session => {
    const token = await login(session, 'student2', DEFAULT_PASSWORDS.student2, 'student')
    await selectCourse(session, '数据可视化基础')
    const status = await requestAs(session, token, '/api/student/assessments/status?course_id=3')
    assert.equal(status.status, 200)
    assert.equal(status.body.data.knowledge_done, false)
    await session.page.goto(`${frontendUrl}/student/learning-path`, { waitUntil: 'networkidle' })
    await session.page.getByText('请先完成学习能力评测').first().waitFor()
    await session.page.screenshot({ path: path.join(outputDir, 'new-student-path.png') })
    assert.deepEqual(session.errors, [])
    return { assessmentRequired: true, courseId: 3 }
  })

  await runRole('completed-student', async session => {
    const token = await login(session, 'student1', DEFAULT_PASSWORDS.student1, 'student')
    await selectCourse(session, '大数据技术与应用')
    const status = await requestAs(session, token, '/api/student/assessments/status?course_id=1')
    assert.equal(status.body.data.knowledge_done, true)
    const result = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge/result?course_id=1')
    assert.equal(result.status, 200)
    await session.page.goto(`${frontendUrl}/student/learning-path`, { waitUntil: 'networkidle' })
    const learningPath = await requestAs(session, token, '/api/student/learning-path?course_id=1')
    assert.equal(learningPath.status, 200)
    assert.ok(learningPath.body.data.nodes.length > 0)
    await session.page.goto(`${frontendUrl}/student/agent-learning`, { waitUntil: 'networkidle' })
    await session.page.getByRole('heading', { name: '生成学习资源' }).first().waitFor()
    await session.page.screenshot({ path: path.join(outputDir, 'student-resource-generation.png') })
    assert.deepEqual(session.errors, [])
    return { completed: true, pathNodes: learningPath.body.data.nodes.length,
      resourceGenerationLoaded: true }
  })

  await runRole('restricted-student', async session => {
    const token = await login(session, 'student3', DEFAULT_PASSWORDS.student3, 'student')
    await selectCourse(session, '大数据技术与应用')
    const fetched = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge?course_id=3')
    const submitted = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge/submit',
      { course_id: 3, answers: [{ question_id: 51, answer: 'A' }] })
    assert.equal(fetched.status, 403)
    assert.equal(submitted.status, 403)
    await session.page.goto(`${frontendUrl}/admin/dashboard`, { waitUntil: 'networkidle' })
    await session.page.waitForURL(/\/403/, { timeout: 15000 })
    return { foreignCourseGet: 403, foreignCourseSubmit: 403, roleGuard: '/403' }
  })

  await runRole('teacher', async session => {
    const token = await login(session, 'teacher1', DEFAULT_PASSWORDS.teacher1, 'teacher')
    const own = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge?course_id=1')
    const foreign = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge?course_id=2')
    assert.equal(own.status, 200)
    assert.ok(own.body.data.questions.length > 0)
    assert.equal(foreign.status, 403)
    await session.page.goto(`${frontendUrl}/teacher/courses/1/workspace/questions`, {
      waitUntil: 'networkidle'
    })
    assert.match(await session.page.locator('body').innerText(), /题库|题目/)
    assert.deepEqual(session.errors, [])
    return { ownedCourse: 200, foreignCourse: 403 }
  })

  await runRole('admin', async session => {
    const token = await login(session, 'admin', DEFAULT_PASSWORDS.admin, 'admin')
    const preview = await requestAs(session, token,
      '/api/student/assessments/initial/knowledge?course_id=3')
    assert.equal(preview.status, 200)
    assert.ok(preview.body.data.questions.length > 0)
    assert.equal('analysis' in preview.body.data.questions[0], false)
    await session.page.goto(`${frontendUrl}/admin/users`, { waitUntil: 'networkidle' })
    await session.page.getByPlaceholder('搜索用户名、姓名或邮箱').waitFor()
    assert.deepEqual(session.errors, [])
    return { crossCoursePreview: 200, userManagementLoaded: true }
  })

  console.log(JSON.stringify(results.map(({ role, ok, detail }) => ({ role, ok, detail })), null, 2))
} finally {
  await fs.writeFile(path.join(outputDir, 'role-permissions-report.json'),
    JSON.stringify(results, null, 2), 'utf8')
  await browser.close()
}
