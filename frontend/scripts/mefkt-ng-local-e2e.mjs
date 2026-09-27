/**
 * 本地 Docker 数据库上的 MEFKT-NG 前后端联调脚本。
 * 先运行 backend/scripts/prepare_mefkt_ng_local_e2e.py 创建一次性账号。
 * 凭据由临时文件提供，避免测试账号密码写入仓库。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright'

const baseUrl = process.env.MEFKT_E2E_BASE_URL || 'http://127.0.0.1:3000'
const credentialPath = process.env.MEFKT_E2E_CREDENTIALS
  || path.join(os.tmpdir(), 'mefkt_ng_e2e_credentials.json')
const credential = JSON.parse(await fs.readFile(credentialPath, 'utf8'))
assert.match(baseUrl, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/)
assert.match(credential.username, /^mefkt_ng_e2e_/)
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const failures = []
const observed = []

page.on('pageerror', error => failures.push(`pageerror: ${error.message}`))
page.on('console', message => {
  if (message.type() === 'error') failures.push(`console: ${message.text()}`)
})
page.on('response', response => {
  const requestUrl = response.url()
  if (new URL(requestUrl).pathname.startsWith('/api/')) {
    observed.push({ status: response.status(), url: new URL(requestUrl).pathname })
  }
})

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.locator('input[name="username"]').fill(credential.username)
  await page.locator('input[name="password"]').fill(credential.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(/\/student\//, { timeout: 30000 })
  console.log('登录后路径:', new URL(page.url()).pathname)

  await page.goto(`${baseUrl}/student/course-select`, { waitUntil: 'networkidle' })
  await page.locator('.course-card-wrapper', { hasText: credential.course_name }).click()
  await page.getByRole('button', { name: '确认并进入课程' }).click()
  await page.waitForURL(/\/student\/dashboard/, { timeout: 30000 })
  console.log('课程选择:', (await page.locator('body').innerText()).includes(credential.course_name))

  const courseId = Number(credential.course_id)
  await page.goto(`${baseUrl}/student/assessment/knowledge?course_id=${courseId}`, {
    waitUntil: 'networkidle'
  })
  await page.getByText(credential.question_content).waitFor({ timeout: 30000 })
  console.log('测评页面:', (await page.locator('body').innerText()).slice(0, 800))
  await page.locator('.option-item').first().click()
  const submitResponsePromise = page.waitForResponse(response =>
    response.url().includes('/api/student/assessments/initial/knowledge/submit')
  )
  await page.getByRole('button', { name: '提交', exact: true }).click()
  const submitResponse = await submitResponsePromise
  const submitted = await submitResponse.json()
  assert.equal(submitResponse.status(), 200)
  assert.ok(Array.isArray(submitted.data?.mastery))
  assert.ok(submitted.data.mastery.length >= 1)
  await page.waitForURL(/\/student\/assessment\/report/, { timeout: 30000 })
  await page.getByText(credential.knowledge_point_name).first().waitFor({ timeout: 30000 })
  console.log('提交结果:', JSON.stringify({
    score: submitted.data.score,
    mastery: submitted.data.mastery,
    path: new URL(page.url()).pathname
  }))

  const token = await page.evaluate(() => {
    for (const store of [localStorage, sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.toLowerCase().includes('access')) return store.getItem(key)
      }
    }
    return null
  })
  assert.ok(token, '浏览器未保存登录访问令牌')
  const ktResponse = await context.request.post(`${baseUrl}/api/ai/kt/predict`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      course_id: courseId,
      knowledge_points: [credential.knowledge_point_id],
      answer_history: [{
        question_id: credential.question_id,
        knowledge_point_id: credential.knowledge_point_id,
        correct: 1
      }]
    }
  })
  const kt = await ktResponse.json()
  assert.equal(ktResponse.status(), 200)
  assert.equal(kt.data?.model_type, 'mefkt_ng')
  assert.ok(Number.isFinite(Number(
    kt.data?.predictions?.[String(credential.knowledge_point_id)]
  )))
  console.log('KT 模型:', JSON.stringify({
    model_type: kt.data.model_type,
    prediction_mode: kt.data.prediction_mode,
    predictions: kt.data.predictions
  }))

  await page.goto(`${baseUrl}/student/assessment/ability`, { waitUntil: 'networkidle' })
  await page.locator('.question-card .option-item').first().waitFor()
  for (let index = 0; index < credential.ability_question_count; index += 1) {
    await page.locator('.question-card .option-item').first().click()
    if (index < credential.ability_question_count - 1) {
      await page.getByRole('button', { name: '下一题', exact: true }).click()
    } else {
      const responsePromise = page.waitForResponse(response =>
        response.url().includes('/api/student/assessments/initial/ability/submit')
      )
      await page.getByRole('button', { name: '提交', exact: true }).click()
      const response = await responsePromise
      assert.equal(response.status(), 200)
      assert.equal(response.request().postDataJSON().course_id, courseId)
    }
  }
  await page.waitForURL(/\/student\/assessment$/, { timeout: 30000 })

  await page.goto(`${baseUrl}/student/assessment/habit`, { waitUntil: 'networkidle' })
  await page.locator('.question-card .option-item').first().waitFor()
  for (let index = 0; index < credential.habit_question_count; index += 1) {
    await page.locator('.question-card .option-item').first().click()
    if (index < credential.habit_question_count - 1) {
      await page.getByRole('button', { name: '下一题', exact: true }).click()
    } else {
      const responsePromise = page.waitForResponse(response =>
        response.url().includes('/api/student/assessments/initial/habit/submit')
      )
      await page.getByRole('button', { name: '提交', exact: true }).click()
      assert.equal((await responsePromise).status(), 200)
    }
  }
  await page.waitForURL(/\/student\/assessment$/, { timeout: 30000 })
  const statusResponse = await context.request.get(
    `${baseUrl}/api/student/assessments/status?course_id=${courseId}`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  const status = await statusResponse.json()
  console.log('三项测评状态:', JSON.stringify(status.data))
  assert.equal(status.data?.knowledge_done, true)
  assert.equal(status.data?.ability_done, true)
  assert.equal(status.data?.habit_done, true)

  const pathResponsePromise = page.waitForResponse(response =>
    response.url().includes('/api/student/learning-path?course_id=')
  )
  await page.goto(`${baseUrl}/student/learning-path`, { waitUntil: 'networkidle' })
  const pathPayload = await (await pathResponsePromise).json()
  assert.ok(Array.isArray(pathPayload.data?.nodes))
  assert.ok(pathPayload.data.nodes.length > 0)
  await page.getByText('学习路径').first().waitFor({ timeout: 30000 })
  assert.equal((await page.getByText('请先完成学习能力评测').count()), 0)
  await page.screenshot({ path: path.join(os.tmpdir(), 'mefkt_ng_e2e_learning_path.png') })
  console.log('学习路径节点数:', pathPayload.data.nodes.length)
  console.log('学习路径页面:', (await page.locator('body').innerText()).slice(0, 900))

  console.log('接口响应:', JSON.stringify(observed))
  assert.deepEqual(failures, [], `浏览器错误：${failures.join('; ')}`)
  console.log('MEFKT-NG 前后端联调通过')
} finally {
  await browser.close()
}
