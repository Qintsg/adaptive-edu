/**
 * 答辩演示录制入口：按角色操作真实页面，保存截图、视频和镜像对应清单。
 */
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'

import { DEFAULT_PASSWORDS } from './browser-audit/constants.mjs'
import {
  CaptureSession,
  resolveContainerImageDigest,
  resolveImageDigest,
  sha256File
} from './defense-demo/capture.mjs'
import { runAdmin, runStudent1, runStudent2, runTeacher } from './defense-demo/flows.mjs'

const DEFAULT_OUTPUT = path.join(os.homedir(), 'Desktop', 'adaptive-edu-defense-20260927')
const ROLE_FLOWS = {
  student1: runStudent1,
  teacher: runTeacher,
  admin: runAdmin,
  student2: runStudent2
}

/**
 * 读取命令行参数并挡住可能破坏 student2 基线的误操作。
 *
 * :param {Array<string>} argv: 命令行参数。
 * :returns {Object}: 已校验的取证选项。
 */
function parseArgs(argv) {
  const options = {
    baseUrl: 'http://127.0.0.1:3000',
    outputDir: DEFAULT_OUTPUT,
    courseName: '大数据技术与应用',
    imageRef: null,
    appContainer: null,
    backendImageRef: null,
    backendContainer: null,
    expectedAiAnswerFile: null,
    roles: ['student1', 'teacher', 'admin', 'student2'],
    student2Full: false,
    withAi: false,
    allowStateChanges: false,
    disposableStack: false,
    final: false,
    headed: false,
    settleMs: 500,
    dwellMs: 1200,
    questionPauseMs: 160,
    accounts: {
      student1: { username: process.env.DEMO_STUDENT1_USER || 'student1', password: process.env.DEMO_STUDENT1_PASSWORD || DEFAULT_PASSWORDS.student1 },
      student2: { username: process.env.DEMO_STUDENT2_USER || 'student2', password: process.env.DEMO_STUDENT2_PASSWORD || DEFAULT_PASSWORDS.student2 },
      teacher: { username: process.env.DEMO_TEACHER_USER || 'teacher1', password: process.env.DEMO_TEACHER_PASSWORD || DEFAULT_PASSWORDS.teacher1 },
      admin: { username: process.env.DEMO_ADMIN_USER || 'admin', password: process.env.DEMO_ADMIN_PASSWORD || DEFAULT_PASSWORDS.admin }
    }
  }
  const scalar = new Map([
    ['--base-url', 'baseUrl'], ['--output-dir', 'outputDir'],
    ['--course-name', 'courseName'], ['--image-ref', 'imageRef'],
    ['--app-container', 'appContainer'],
    ['--backend-image-ref', 'backendImageRef'],
    ['--backend-container', 'backendContainer'],
    ['--expected-ai-answer-file', 'expectedAiAnswerFile'],
    ['--settle-ms', 'settleMs'], ['--dwell-ms', 'dwellMs'],
    ['--question-pause-ms', 'questionPauseMs']
  ])
  for (let index = 2; index < argv.length; index += 1) {
    const current = argv[index]
    if (scalar.has(current)) {
      const value = argv[++index]
      if (!value || value.startsWith('--')) throw new Error(`${current} 缺少参数值`)
      const key = scalar.get(current)
      options[key] = key.endsWith('Ms') ? Number(value) : value
      continue
    }
    if (current === '--roles') {
      options.roles = (argv[++index] || '').split(',').filter(Boolean)
      continue
    }
    if (current === '--student2-full') options.student2Full = true
    else if (current === '--with-ai') options.withAi = true
    else if (current === '--allow-state-changes') options.allowStateChanges = true
    else if (current === '--disposable-stack') options.disposableStack = true
    else if (current === '--final') options.final = true
    else if (current === '--headed') options.headed = true
    else if (current === '--help') options.help = true
    else throw new Error(`未知参数：${current}`)
  }
  if (options.help) return options
  options.baseUrl = options.baseUrl.replace(/\/$/, '')
  if (!/^https?:\/\//.test(options.baseUrl)) throw new Error('--base-url 需要 http 或 https 地址')
  if (!options.roles.length || options.roles.some(role => !ROLE_FLOWS[role])) {
    throw new Error('--roles 只能使用 student1,student2,teacher,admin')
  }
  if (!Number.isFinite(options.settleMs) || !Number.isFinite(options.dwellMs)
    || !Number.isFinite(options.questionPauseMs)) {
    throw new Error('等待时间需要填写数字')
  }
  if ((options.student2Full || options.withAi)
    && !(options.allowStateChanges && options.disposableStack)) {
    throw new Error('完整测评或 AI 提问必须同时带 --allow-state-changes 和 --disposable-stack')
  }
  if (options.final && !options.imageRef) {
    throw new Error('正式取证必须带 --image-ref，以绑定最终镜像摘要')
  }
  if (options.final && !options.appContainer) {
    throw new Error('正式取证必须带 --app-container，以核对网页来自最终镜像')
  }
  if (options.final && (!options.backendImageRef || !options.backendContainer)) {
    throw new Error('正式取证必须带后端镜像名及 --backend-container，以核对 API 代码版本')
  }
  if (options.final && options.withAi && !options.expectedAiAnswerFile) {
    throw new Error('正式 AI 录制需要 --expected-ai-answer-file 核对预置回答')
  }
  options.outputDir = path.resolve(options.outputDir)
  return options
}

/**
 * 输出命令用法。
 *
 * :returns {void}: 无。
 */
function printHelp() {
  process.stdout.write(`用法：node scripts/defense-demo.mjs [选项]\n\n`)
  process.stdout.write(`--base-url URL          前端地址，默认 http://127.0.0.1:3000\n`)
  process.stdout.write(`--output-dir DIR        输出目录，默认桌面 adaptive-edu-defense-20260927\n`)
  process.stdout.write(`--image-ref IMAGE       运行中的应用镜像名；--final 时必须填写\n`)
  process.stdout.write(`--app-container NAME    提供网页的应用容器名；--final 时必须填写\n`)
  process.stdout.write(`--backend-image-ref IMAGE  运行中的后端镜像名；--final 时必须填写\n`)
  process.stdout.write(`--backend-container NAME  提供 API 的后端容器名；--final 时必须填写\n`)
  process.stdout.write(`--expected-ai-answer-file FILE  实际模型回答的校对文本\n`)
  process.stdout.write(`--roles LIST           逗号分隔，默认 student1,teacher,admin,student2\n`)
  process.stdout.write(`--student2-full        录完整初始测评并提交；必须在临时栈运行\n`)
  process.stdout.write(`--with-ai              提交一次 AI 问题；必须在临时栈运行\n`)
  process.stdout.write(`--allow-state-changes --disposable-stack  确认临时栈可丢弃\n`)
  process.stdout.write(`--final                正式取证，强制镜像摘要检查\n`)
}

/**
 * 正式取证拒绝混用上一次的截图、录屏或清单。
 *
 * :param {Object} options: 输出参数。
 * :returns {Promise<void>}: 无。
 */
async function assertFreshFinalOutput(options) {
  if (!options.final) return
  for (const role of options.roles) {
    const screenshotDir = path.join(options.outputDir, 'screenshots', role)
    const existing = await fs.readdir(screenshotDir).catch(error => {
      if (error.code === 'ENOENT') return []
      throw error
    })
    if (existing.length) {
      throw new Error(`该角色已有旧截图，请先人工归档后重录：${screenshotDir}`)
    }
  }
  const ownedFiles = [
    path.join(options.outputDir, 'evidence', 'capture-manifest.json'),
    ...options.roles.flatMap(role => [
      path.join(options.outputDir, 'evidence', `${role}.json`),
      path.join(options.outputDir, 'recordings', 'raw', `${role}.webm`),
      path.join(options.outputDir, 'recordings', 'raw', `${role}.mp4`)
    ])
  ]
  for (const filePath of ownedFiles) {
    const exists = await fs.stat(filePath).then(() => true, error => {
      if (error.code === 'ENOENT') return false
      throw error
    })
    if (exists) {
      throw new Error(`该路径已有旧取证文件，请先人工归档后重录：${filePath}`)
    }
  }
}

/**
 * 运行所有指定角色并写入总证据清单。
 *
 * :returns {Promise<void>}: 无。
 */
async function main() {
  const options = parseArgs(process.argv)
  if (options.help) return printHelp()
  await assertFreshFinalOutput(options)
  options.imageDigest = await resolveImageDigest(options.imageRef)
  const containerDigest = await resolveContainerImageDigest(options.appContainer)
  if (containerDigest && containerDigest !== options.imageDigest) {
    throw new Error('应用容器实际镜像与 --image-ref 不一致')
  }
  options.backendImageDigest = await resolveImageDigest(options.backendImageRef)
  const backendContainerDigest = await resolveContainerImageDigest(options.backendContainer)
  if (backendContainerDigest && backendContainerDigest !== options.backendImageDigest) {
    throw new Error('后端容器实际镜像与 --backend-image-ref 不一致')
  }
  if (options.expectedAiAnswerFile) {
    options.expectedAiAnswer = await fs.readFile(options.expectedAiAnswerFile, 'utf8')
    options.expectedAiAnswerSha256 = await sha256File(options.expectedAiAnswerFile)
  }
  await fs.mkdir(path.join(options.outputDir, 'evidence'), { recursive: true })
  const browser = await chromium.launch({ headless: !options.headed })
  const reports = []
  try {
    for (const role of options.roles) {
      const capture = new CaptureSession(browser, options, role)
      await capture.start()
      try {
        await ROLE_FLOWS[role](capture)
      } catch (error) {
        capture.issues.push({ step: 'role-flow', message: String(error) })
        await capture.captureFailure('role-flow')
      } finally {
        reports.push(await capture.finish())
      }
    }
  } finally {
    await browser.close()
  }
  const digestAfter = await resolveImageDigest(options.imageRef)
  const containerDigestAfter = await resolveContainerImageDigest(options.appContainer)
  const backendDigestAfter = await resolveImageDigest(options.backendImageRef)
  const backendContainerDigestAfter = await resolveContainerImageDigest(options.backendContainer)
  if (digestAfter !== options.imageDigest || containerDigestAfter !== containerDigest
    || backendDigestAfter !== options.backendImageDigest
    || backendContainerDigestAfter !== backendContainerDigest) {
    throw new Error('录制期间 Web 或后端镜像、容器发生变化，本轮证据不可交付')
  }
  const manifest = {
    capturedAt: new Date().toISOString(),
    baseUrl: options.baseUrl,
    courseName: options.courseName,
    imageRef: options.imageRef,
    imageDigest: options.imageDigest,
    appContainer: options.appContainer,
    backendImageRef: options.backendImageRef,
    backendImageDigest: options.backendImageDigest,
    backendContainer: options.backendContainer,
    expectedAiAnswerSha256: options.expectedAiAnswerSha256 || null,
    final: options.final,
    disposableStack: options.disposableStack,
    student2Full: options.student2Full,
    withAi: options.withAi,
    roles: reports.map(report => ({
      role: report.role,
      steps: report.steps.length,
      issues: report.issues.length,
      browserErrors: report.browserErrors.length,
      browserWarnings: report.browserWarnings.length,
      failedRequests: report.failedRequests.length,
      httpErrors: report.httpErrors.length
    })),
    artifacts: reports.flatMap(report => report.artifacts)
  }
  const manifestPath = path.join(options.outputDir, 'evidence', 'capture-manifest.json')
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  process.stdout.write(`${manifestPath}\n`)
  if (manifest.roles.some(role => role.issues || role.browserErrors || role.browserWarnings
    || role.failedRequests || role.httpErrors)) {
    process.exitCode = 1
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`)
  process.exitCode = 1
})
