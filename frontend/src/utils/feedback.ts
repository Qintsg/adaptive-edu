interface MessageBridge {
  success: (content: string, options?: Record<string, unknown>) => unknown
  error: (content: string, options?: Record<string, unknown>) => unknown
  warning: (content: string, options?: Record<string, unknown>) => unknown
  info: (content: string, options?: Record<string, unknown>) => unknown
}

interface DialogBridge {
  warning: (options: Record<string, unknown>) => unknown
  info: (options: Record<string, unknown>) => unknown
}

interface NotificationBridge {
  success: (options: Record<string, unknown>) => unknown
  error: (options: Record<string, unknown>) => unknown
  warning: (options: Record<string, unknown>) => unknown
  info: (options: Record<string, unknown>) => unknown
}

interface LoadingBarBridge {
  start: () => void
  finish: () => void
  error: () => void
}

export interface FeedbackApiBridge {
  message: MessageBridge
  dialog: DialogBridge
  notification: NotificationBridge
  loadingBar: LoadingBarBridge
}

export interface ConfirmActionOptions {
  title?: string
  content: string
  positiveText?: string
  negativeText?: string
}

export interface PromptActionOptions extends ConfirmActionOptions {
  defaultValue?: string
}

let feedbackApi: FeedbackApiBridge | null = null

export function setFeedbackApi(api: FeedbackApiBridge): void {
  feedbackApi = api
}

export function clearFeedbackApi(): void {
  feedbackApi = null
}

export function showSuccess(message: string): void {
  feedbackApi?.message.success(message)
}

export function showError(message: string): void {
  feedbackApi?.message.error(message || '操作失败')
}

export function showWarning(message: string): void {
  feedbackApi?.message.warning(message)
}

export function showInfo(message: string): void {
  feedbackApi?.message.info(message)
}

export function notifySuccess(title: string, content?: string): void {
  feedbackApi?.notification.success({ title, content })
}

export function notifyError(title: string, content?: string): void {
  feedbackApi?.notification.error({ title, content })
}

export function startLoadingBar(): void {
  feedbackApi?.loadingBar.start()
}

export function finishLoadingBar(): void {
  feedbackApi?.loadingBar.finish()
}

export function failLoadingBar(): void {
  feedbackApi?.loadingBar.error()
}

export function confirmAction(options: ConfirmActionOptions): Promise<void> {
  const title = options.title ?? '确认操作'
  const content = options.content

  if (!feedbackApi) {
    return window.confirm(content) ? Promise.resolve() : Promise.reject('cancel')
  }

  return new Promise((resolve, reject) => {
    feedbackApi?.dialog.warning({
      title,
      content,
      positiveText: options.positiveText ?? '确认',
      negativeText: options.negativeText ?? '取消',
      onPositiveClick: () => resolve(),
      onNegativeClick: () => reject('cancel'),
      onClose: () => reject('cancel')
    })
  })
}

export function promptAction(options: PromptActionOptions): Promise<string> {
  const input = window.prompt(options.content, options.defaultValue ?? '')
  return input === null ? Promise.reject('cancel') : Promise.resolve(input)
}

export const appMessage = {
  success: showSuccess,
  error: showError,
  warning: showWarning,
  info: showInfo
}

export const appDialog = {
  confirm(content: string, title?: string, options?: Record<string, unknown>): Promise<void> {
    return confirmAction({
      title: title || '确认操作',
      content,
      positiveText: String(options?.confirmButtonText ?? '确认'),
      negativeText: String(options?.cancelButtonText ?? '取消')
    })
  },
  async prompt(content: string, title?: string, options?: Record<string, unknown>): Promise<{ value: string }> {
    const value = await promptAction({
      title: title || '输入内容',
      content,
      positiveText: String(options?.confirmButtonText ?? '确认'),
      negativeText: String(options?.cancelButtonText ?? '取消'),
      defaultValue: String(options?.inputValue ?? '')
    })
    return { value }
  }
}

export const appLoading = {
  service(options?: { text?: string }): { close: () => void } {
    startLoadingBar()
    if (options?.text) showInfo(options.text)
    return {
      close: finishLoadingBar
    }
  }
}
