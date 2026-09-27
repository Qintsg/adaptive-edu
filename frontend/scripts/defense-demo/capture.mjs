/**
 * 答辩演示取证：记录真实浏览器画面、逐步截图和版本校验信息。
 */
import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const FORBIDDEN_VISIBLE_TEXT = [
  '失败', '回退', '兜底', '模拟数据', '测试数据', '演示专用', '用于演示',
  'demo_fallback', 'verified_ai_preset', 'demo_mode'
]
const CAPTURE_WIDTH = 1920
const CAPTURE_HEIGHT = 1080

/**
 * 生成适合文件名的步骤标识。
 *
 * :param {string} label: 步骤名称。
 * :returns {string}: 文件名片段。
 */
function slug(label) {
  return label.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-|-$/g, '')
}

/**
 * 计算文件的 SHA-256。
 *
 * :param {string} filePath: 文件绝对路径。
 * :returns {Promise<string>}: 十六进制摘要。
 */
export async function sha256File(filePath) {
  const content = await fs.readFile(filePath)
  return createHash('sha256').update(content).digest('hex')
}

/**
 * 确认截图文件是现场要求的 1920×1080 PNG。
 *
 * :param {string} filePath: 截图绝对路径。
 * :returns {Promise<void>}: 无。
 */
async function assertScreenshotSize(filePath) {
  const png = await fs.readFile(filePath)
  const width = png.readUInt32BE(16)
  const height = png.readUInt32BE(20)
  if (width !== CAPTURE_WIDTH || height !== CAPTURE_HEIGHT) {
    throw new Error(`截图尺寸为 ${width}×${height}，要求 ${CAPTURE_WIDTH}×${CAPTURE_HEIGHT}`)
  }
}

/**
 * 查询本机 Docker 镜像 ID，保证一轮取证固定对应同一个镜像。
 *
 * :param {string|null} imageRef: 镜像名或摘要。
 * :returns {Promise<string|null>}: 镜像内容摘要。
 */
export async function resolveImageDigest(imageRef) {
  if (!imageRef) return null
  const { stdout } = await execFileAsync('docker', [
    'image', 'inspect', '--format', '{{.Id}}', imageRef
  ])
  const digest = stdout.trim()
  if (!/^sha256:[a-f0-9]{64}$/.test(digest)) {
    throw new Error(`无法确认镜像摘要：${imageRef}`)
  }
  return digest
}

/**
 * 查询运行中容器实际使用的镜像 ID。
 *
 * :param {string|null} containerName: 应用容器名。
 * :returns {Promise<string|null>}: 容器镜像摘要。
 */
export async function resolveContainerImageDigest(containerName) {
  if (!containerName) return null
  const { stdout } = await execFileAsync('docker', [
    'inspect', '--format', '{{.Image}}', containerName
  ])
  const digest = stdout.trim()
  if (!/^sha256:[a-f0-9]{64}$/.test(digest)) {
    throw new Error(`无法确认容器镜像摘要：${containerName}`)
  }
  return digest
}

/**
 * 页面交互与视觉取证会话。
 */
export class CaptureSession {
  /**
   * 创建会话记录器。
   *
   * :param {import('playwright').Browser} browser: Chromium 浏览器。
   * :param {Object} options: 输出和取证参数。
   * :param {string} role: 当前演示角色。
   */
  constructor(browser, options, role) {
    this.browser = browser
    this.options = options
    this.role = role
    this.context = null
    this.page = null
    this.startedAt = null
    this.steps = []
    this.issues = []
    this.browserErrors = []
    this.browserWarnings = []
    this.failedRequests = []
    this.httpErrors = []
    this.artifacts = []
  }

  /**
   * 启动独立浏览器上下文并录制网页视频。
   *
   * :returns {Promise<void>}: 无。
   */
  async start() {
    const rawDir = path.join(this.options.outputDir, 'recordings', 'raw')
    await fs.mkdir(rawDir, { recursive: true })
    await fs.mkdir(path.join(this.options.outputDir, 'screenshots', this.role), { recursive: true })
    this.context = await this.browser.newContext({
      viewport: { width: CAPTURE_WIDTH, height: CAPTURE_HEIGHT },
      deviceScaleFactor: 1,
      recordVideo: { dir: rawDir, size: { width: CAPTURE_WIDTH, height: CAPTURE_HEIGHT } }
    })
    this.page = await this.context.newPage()
    this.page.on('pageerror', error => this.browserErrors.push({
      url: this.page.url(), kind: 'pageerror', message: String(error)
    }))
    this.page.on('console', message => {
      if (message.type() === 'error') {
        this.browserErrors.push({
          url: this.page.url(), kind: 'console', message: message.text()
        })
      } else if (message.type() === 'warning') {
        this.browserWarnings.push({ url: this.page.url(), message: message.text() })
      }
    })
    this.page.on('response', response => {
      if (response.status() >= 400 && new URL(response.url()).pathname.startsWith('/api/')) {
        this.httpErrors.push({ url: response.url(), status: response.status() })
      }
    })
    this.page.on('requestfailed', request => {
      const reason = request.failure()?.errorText || 'requestfailed'
      if (!reason.includes('ERR_ABORTED')) {
        this.failedRequests.push({ url: request.url(), reason })
      }
    })
    this.startedAt = Date.now()
  }

  /**
   * 等待路由切换动画结束，避免把空白主区误存成正式截图。
   *
   * :returns {Promise<void>}: 无。
   */
  async waitForStablePage() {
    if (!await this.page.locator('.layout-main').count()) return
    await this.page.waitForTimeout(300)
    await this.page.waitForFunction(() => {
      const main = document.querySelector('.layout-main')
      if (!main) return false
      const visibleChildren = [...main.children].filter(element => element.getClientRects().length > 0)
      return visibleChildren.length > 0
        && !main.querySelector('.page-fade-enter-active, .page-fade-leave-active')
        && main.innerText.trim().length >= 6
    }, null, { timeout: 30000 })
  }

  /**
   * 等待短暂提示消失，保证顶栏与账号菜单完整出镜。
   *
   * :returns {Promise<void>}: 无。
   */
  async waitForTransientMessages() {
    await this.page.waitForFunction(() =>
      [...document.querySelectorAll('.n-message-container .n-message')]
        .every(element => element.getClientRects().length === 0),
    null, { timeout: 5500 })
  }

  /**
   * 记录真实操作完成后的页面状态。
   *
   * :param {string} label: 英文步骤标识。
   * :param {string} narration: 演示者讲解词。
   * :param {Function|null} action: 可选的真实页面操作。
   * :returns {Promise<Object>}: 步骤记录。
   */
  async step(label, narration, action = null) {
    try {
      if (action) await action()
      await this.waitForStablePage()
      await this.page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {})
      await this.page.waitForTimeout(this.options.settleMs)
      await this.waitForTransientMessages()
      if (this.options.final) {
        const visibleText = (await this.page.locator('body').innerText()).toLowerCase()
        const blocked = FORBIDDEN_VISIBLE_TEXT.find(value => visibleText.includes(value.toLowerCase()))
        if (blocked) throw new Error(`正式画面出现禁用文字“${blocked}”，本轮需要修复后重录`)
      }
      const sequence = String(this.steps.length + 1).padStart(2, '0')
      const relativePath = path.join('screenshots', this.role, `${sequence}-${slug(label)}.png`)
      const screenshotPath = path.join(this.options.outputDir, relativePath)
      await this.page.screenshot({ path: screenshotPath, fullPage: false, animations: 'disabled' })
      await assertScreenshotSize(screenshotPath)
      const viewport = await this.page.evaluate(() => ({
        width: innerWidth,
        pageWidth: document.documentElement.scrollWidth,
        pageHeight: document.documentElement.scrollHeight
      }))
      if (viewport.pageWidth > viewport.width + 2) {
        this.issues.push({ step: label, message: `页面横向溢出 ${viewport.pageWidth - viewport.width}px` })
      }
      const result = {
        label,
        narration,
        elapsedMs: Date.now() - this.startedAt,
        url: this.page.url(),
        screenshot: relativePath.replaceAll('\\', '/'),
        viewport
      }
      this.steps.push(result)
      this.artifacts.push(screenshotPath)
      await this.page.waitForTimeout(this.options.dwellMs)
      return result
    } catch (error) {
      this.issues.push({ step: label, message: String(error) })
      throw error
    }
  }

  /**
   * 在普通步骤之间保存一张仍在变化的页面，不改变步骤编号。
   *
   * :param {string} fileName: 当前角色截图目录下的文件名。
   * :returns {Promise<string>}: 相对输出目录的文件路径。
   */
  async saveAuxiliaryScreenshot(fileName) {
    const relativePath = path.join('screenshots', this.role, path.basename(fileName))
    const screenshotPath = path.join(this.options.outputDir, relativePath)
    if (this.options.final) {
      const visibleText = (await this.page.locator('body').innerText()).toLowerCase()
      const blocked = FORBIDDEN_VISIBLE_TEXT.find(value => visibleText.includes(value.toLowerCase()))
      if (blocked) throw new Error(`正式画面出现禁用文字“${blocked}”，本轮需要修复后重录`)
    }
    await this.page.screenshot({ path: screenshotPath, fullPage: false, animations: 'disabled' })
    await assertScreenshotSize(screenshotPath)
    this.artifacts.push(screenshotPath)
    return relativePath.replaceAll('\\', '/')
  }

  /**
   * 保存失败时页面，便于定位真实流程障碍。
   *
   * :param {string} label: 失败步骤。
   * :returns {Promise<void>}: 无。
   */
  async captureFailure(label) {
    if (!this.page) return
    if (this.options.final) {
      const visibleText = (await this.page.locator('body').innerText().catch(() => '')).toLowerCase()
      if (FORBIDDEN_VISIBLE_TEXT.some(value => visibleText.includes(value.toLowerCase()))) return
    }
    const filePath = path.join(this.options.outputDir, 'screenshots', this.role, `error-${slug(label)}.png`)
    try {
      await this.page.screenshot({ path: filePath, fullPage: false })
      await assertScreenshotSize(filePath)
      this.artifacts.push(filePath)
    } catch {
      this.issues.push({ step: label, message: '失败时截图也未能保存' })
    }
  }

  /**
   * 关闭会话，将浏览器原始视频转成便于播放的 MP4。
   *
   * :returns {Promise<Object>}: 角色取证报告。
   */
  async finish() {
    const video = this.page?.video()
    await this.context?.close()
    const rawPath = path.join(this.options.outputDir, 'recordings', 'raw', `${this.role}.webm`)
    const mp4Path = path.join(this.options.outputDir, 'recordings', 'raw', `${this.role}.mp4`)
    if (video) {
      const generatedPath = await video.path()
      await fs.rename(generatedPath, rawPath)
      this.artifacts.push(rawPath)
      try {
        await execFileAsync('ffmpeg', [
          '-y', '-loglevel', 'error', '-i', rawPath,
          '-c:v', 'libx264', '-crf', '22', '-preset', 'veryfast',
          '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', mp4Path
        ])
        this.artifacts.push(mp4Path)
      } catch (error) {
        this.issues.push({ step: 'video-transcode', message: `MP4 转码失败：${error}` })
      }
    }
    const report = {
      role: this.role,
      imageDigest: this.options.imageDigest,
      backendImageDigest: this.options.backendImageDigest,
      baseUrl: this.options.baseUrl,
      startedAt: new Date(this.startedAt).toISOString(),
      baseline: this.baseline || null,
      questionCounts: this.questionCounts || null,
      aiEvidence: this.aiEvidence || null,
      steps: this.steps,
      issues: this.issues,
      browserErrors: this.browserErrors,
      browserWarnings: this.browserWarnings,
      failedRequests: this.failedRequests,
      httpErrors: this.httpErrors,
      artifacts: await Promise.all(this.artifacts.map(async filePath => ({
        path: path.relative(this.options.outputDir, filePath).replaceAll('\\', '/'),
        sha256: await sha256File(filePath),
        imageDigest: this.options.imageDigest,
        backendImageDigest: this.options.backendImageDigest
      })))
    }
    const reportPath = path.join(this.options.outputDir, 'evidence', `${this.role}.json`)
    await fs.mkdir(path.dirname(reportPath), { recursive: true })
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
    return report
  }
}
