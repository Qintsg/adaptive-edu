/**
 * 兼容旧模板的 v-loading 指令与覆盖层生命周期。
 */
const loadingStyle = `
.app-loading-host {
  position: relative;
}
.app-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--primary-color, #0f6cbd);
  background: rgba(255, 255, 255, 0.74);
  backdrop-filter: blur(2px);
}
.app-loading-overlay.is-fullscreen {
  position: fixed;
}
.app-loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(15, 108, 189, 0.18);
  border-top-color: var(--primary-color, #0f6cbd);
  border-radius: 50%;
  animation: app-loading-spin 0.8s linear infinite;
}
.app-loading-text {
  max-width: 520px;
  padding: 0 24px;
  color: var(--text-secondary, #616161);
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}
@keyframes app-loading-spin {
  to {
    transform: rotate(360deg);
  }
}
`

/**
 * 注入一次覆盖层样式。
 * :returns {void}
 */
function ensureLoadingStyle() {
  if (typeof document === 'undefined' || document.getElementById('app-loading-directive-style')) return
  const style = document.createElement('style')
  style.id = 'app-loading-directive-style'
  style.textContent = loadingStyle
  document.head.appendChild(style)
}

/**
 * 读取旧模板使用的加载提示文本。
 * :param {HTMLElement} el - 指令所在元素
 * :returns {string} 提示文本
 */
function getLoadingText(el) {
  return el.getAttribute('element-loading-text') || el.getAttribute('data-element-loading-text') || ''
}

/**
 * 卸载覆盖层并恢复元素定位。
 * :param {HTMLElement} el - 指令所在元素
 * :returns {void}
 */
function removeLoadingOverlay(el) {
  const state = el.__appLoadingState
  if (!state) return
  state.overlay.remove()
  if (state.target === el && state.restorePosition) {
    el.style.position = state.originalPosition
  }
  if (state.target === el) {
    el.classList.remove('app-loading-host')
  }
  delete el.__appLoadingState
}

/**
 * 按绑定状态创建或更新覆盖层。
 * :param {HTMLElement} el - 指令所在元素
 * :param {Object} binding - Vue 指令绑定值
 * :returns {void}
 */
function updateLoading(el, binding) {
  const active = Boolean(binding.value)
  if (!active) {
    removeLoadingOverlay(el)
    return
  }
  ensureLoadingStyle()
  const fullscreen = Boolean(binding.modifiers?.fullscreen)
  const target = fullscreen ? document.body : el
  if (el.__appLoadingState) {
    const textNode = el.__appLoadingState.overlay.querySelector('.app-loading-text')
    if (textNode) textNode.textContent = getLoadingText(el)
    return
  }
  const overlay = document.createElement('div')
  overlay.className = fullscreen ? 'app-loading-overlay is-fullscreen' : 'app-loading-overlay'
  overlay.innerHTML = `<span class="app-loading-spinner"></span><span class="app-loading-text"></span>`
  overlay.querySelector('.app-loading-text').textContent = getLoadingText(el)

  const originalPosition = el.style.position
  const restorePosition = !fullscreen && getComputedStyle(el).position === 'static'
  if (!fullscreen) {
    el.classList.add('app-loading-host')
    if (restorePosition) el.style.position = 'relative'
  }
  target.appendChild(overlay)
  el.__appLoadingState = { overlay, target, originalPosition, restorePosition }
}

export const loadingDirective = {
  mounted: updateLoading,
  updated: updateLoading,
  beforeUnmount: removeLoadingOverlay
}
