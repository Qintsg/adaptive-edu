/**
 * 三端关键交互巡检：使用真实后端与测试账号，不创建业务数据。
 */
import assert from 'node:assert/strict'
import path from 'node:path'

import { DEFAULT_PASSWORDS } from './constants.mjs'
import { ensureDir, writeJson } from './files.mjs'

/**
 * 登录现有测试账号，并等待角色工作区出现。
 * :param {import('playwright').Page} page - 浏览器页面
 * :param {string} frontendUrl - 前端地址
 * :param {string} username - 测试账号
 * :param {string} password - 测试密码
 * :param {string} role - 用户角色
 * :returns {Promise<void>} 无
 */
async function login(page, frontendUrl, username, password, role) {
  await page.goto(`${frontendUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(new RegExp(`/${role}/`))
}

/**
 * 创建带控制台与请求失败记录的浏览器会话。
 * :param {import('playwright').Browser} browser - 浏览器实例
 * :returns {Promise<Object>} 会话、页面和错误列表
 */
async function createSession(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  page.on('console', message => {
    if (['error', 'warning'].includes(message.type())) errors.push(message.text())
  })
  page.on('requestfailed', request => {
    const reason = request.failure()?.errorText || 'requestfailed'
    if (!reason.includes('ERR_ABORTED')) errors.push(`${request.url()}: ${reason}`)
  })
  return { context, page, errors }
}

/**
 * 记录一个交互检查的结果。
 * :param {Array} steps - 结果列表
 * :param {string} name - 检查名称
 * :param {Function} action - 检查操作
 * :returns {Promise<void>} 无
 */
async function check(steps, name, action) {
  try {
    await action()
    steps.push({ name, ok: true })
  } catch (error) {
    steps.push({ name, ok: false, error: String(error) })
    throw error
  }
}

/**
 * 巡检学生的选课、作业、图谱与手机端导航。
 * :param {import('playwright').Page} page - 浏览器页面
 * :param {string} frontendUrl - 前端地址
 * :param {string} screenshotDir - 截图目录
 * :param {Array} steps - 结果列表
 * :returns {Promise<void>} 无
 */
async function inspectStudent(page, frontendUrl, screenshotDir, steps) {
  await login(page, frontendUrl, 'student1', DEFAULT_PASSWORDS.student1, 'student')
  await check(steps, '学生选课进入首页', async () => {
    await page.locator('.course-card-wrapper').first().click()
    await page.getByRole('button', { name: '确认并进入课程' }).click()
    await page.locator('#dashboard-title').waitFor()
    assert.equal(await page.locator('.layout-main').evaluate(element => element.scrollTop), 0)
  })

  await check(steps, '作业标签页显示并可切换', async () => {
    await page.goto(`${frontendUrl}/student/exams`, { waitUntil: 'networkidle' })
    await page.locator('.n-tabs-tab').first().waitFor()
    assert.equal(await page.locator('.n-tabs-tab').count(), 2)
    await page.getByText('已完成', { exact: true }).first().click()
    assert.match(await page.locator('.n-tabs-tab--active').innerText(), /已完成/)
    await page.screenshot({ path: path.join(screenshotDir, 'student-exams.png') })
  })

  await check(steps, '知识图谱章节筛选与键盘详情', async () => {
    await page.goto(`${frontendUrl}/student/knowledge-map`, { waitUntil: 'networkidle' })
    await page.locator('.graph-node').first().waitFor()
    const overviewCount = await page.locator('.graph-node').count()
    assert.ok(overviewCount > 0)
    await page.locator('.graph-toolbar .n-select').click()
    await page.locator('.n-base-select-option:visible').first().click()
    await page.waitForFunction(count => document.querySelectorAll('.graph-node').length < count, overviewCount)
    await page.locator('.graph-node').first().focus()
    await page.keyboard.press('Enter')
    await page.locator('.n-drawer').waitFor()
    await page.screenshot({ path: path.join(screenshotDir, 'student-knowledge-detail.png') })
  })

  await check(steps, '手机导航抽屉', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`${frontendUrl}/student/dashboard`, { waitUntil: 'networkidle' })
    await page.locator('#dashboard-title').waitFor()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.getByRole('button', { name: '打开导航菜单' }).click()
    assert.ok((await page.locator('.layout-sidebar').getAttribute('class')).includes('is-mobile-open'))
    await page.keyboard.press('Escape')
    assert.ok(!(await page.locator('.layout-sidebar').getAttribute('class')).includes('is-mobile-open'))
    await page.screenshot({ path: path.join(screenshotDir, 'student-mobile.png') })
  })
}

/**
 * 巡检教师设置标签页与班级卡片键盘入口。
 * :param {import('playwright').Page} page - 浏览器页面
 * :param {string} frontendUrl - 前端地址
 * :param {string} _screenshotDir - 保持巡检函数参数一致
 * :param {Array} steps - 结果列表
 * :returns {Promise<void>} 无
 */
async function inspectTeacher(page, frontendUrl, _screenshotDir, steps) {
  await login(page, frontendUrl, 'teacher1', DEFAULT_PASSWORDS.teacher1, 'teacher')
  await check(steps, '教师设置标签页', async () => {
    await page.goto(`${frontendUrl}/teacher/settings`, { waitUntil: 'networkidle' })
    await page.locator('.n-tabs-tab').first().waitFor()
    assert.equal(await page.locator('.n-tabs-tab').count(), 3)
    await page.getByText('课程配置', { exact: true }).click()
    assert.match(await page.locator('.n-tabs-tab--active').innerText(), /课程配置/)
  })
  await check(steps, '班级卡片键盘入口', async () => {
    await page.goto(`${frontendUrl}/teacher/classes`, { waitUntil: 'networkidle' })
    const card = page.locator('.class-card').first()
    await card.waitFor()
    await card.focus()
    await page.keyboard.press('Enter')
    await page.waitForURL(/\/teacher\/classes\/\d+/)
  })
}

/**
 * 巡检管理员搜索、角色筛选与手机弹窗。
 * :param {import('playwright').Page} page - 浏览器页面
 * :param {string} frontendUrl - 前端地址
 * :param {string} screenshotDir - 截图目录
 * :param {Array} steps - 结果列表
 * :returns {Promise<void>} 无
 */
async function inspectAdmin(page, frontendUrl, screenshotDir, steps) {
  await login(page, frontendUrl, 'admin', DEFAULT_PASSWORDS.admin, 'admin')
  await page.goto(`${frontendUrl}/admin/users`, { waitUntil: 'networkidle' })
  await check(steps, '用户搜索与重置', async () => {
    await page.getByPlaceholder('搜索用户名、姓名或邮箱').fill('student1')
    await page.getByRole('button', { name: '搜索' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.app-adapter-table tbody tr').length === 1)
    await page.getByRole('button', { name: '重置' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.app-adapter-table tbody tr').length > 1)
  })
  await check(steps, '用户角色筛选', async () => {
    await page.locator('.filter-bar .n-select').click()
    await page.locator('.n-base-select-option:visible').filter({ hasText: '教师' }).click()
    await page.waitForFunction(() => document.querySelectorAll('.app-adapter-table tbody tr').length === 2)
  })
  await check(steps, '手机端用户弹窗', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '添加用户' }).click()
    const modal = page.locator('.n-modal')
    await modal.waitFor()
    const bounds = await modal.boundingBox()
    assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 390)
    await page.screenshot({ path: path.join(screenshotDir, 'admin-user-modal.png') })
  })
}

/**
 * 执行真实后端交互巡检并保存报告。
 * :param {import('playwright').Browser} browser - 浏览器实例
 * :param {Object} args - 命令行参数
 * :returns {Promise<void>} 无
 */
export async function runInteractionScenario(browser, args) {
  const screenshotDir = path.resolve(args.outputDir, 'interaction-screenshots')
  await ensureDir(screenshotDir)
  const reports = []
  try {
    for (const [role, inspect] of [
      ['student', inspectStudent],
      ['teacher', inspectTeacher],
      ['admin', inspectAdmin]
    ]) {
      const session = await createSession(browser)
      const report = { role, steps: [], errors: session.errors }
      reports.push(report)
      try {
        await inspect(session.page, args.frontendUrl, screenshotDir, report.steps)
        assert.deepEqual(session.errors, [])
      } finally {
        await session.context.close()
      }
    }
  } finally {
    await writeJson(path.resolve(args.outputDir, 'interaction-report.json'), reports)
  }
}
