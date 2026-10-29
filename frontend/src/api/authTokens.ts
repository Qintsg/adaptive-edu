/**
 * 文件描述：认证状态的存储、恢复和清理。
 * 项目名：adaptive-edu；文件名：authTokens.ts；作者：Qintsg；日期：2026-10-29。
 */

const SESSION_KEYS = ['access_token', 'token', 'refresh_token', 'userInfo']

/**
 * 读取当前认证存储，并恢复已有标签页中的登录。
 * :returns: 当前认证信息所在的存储。
 */
export function getAuthStorage(): Storage {
  if (localStorage.getItem('access_token') || localStorage.getItem('token')) {
    return localStorage
  }
  if (sessionStorage.getItem('access_token') || sessionStorage.getItem('token')) {
    if (localStorage.getItem('auth_remember_me') !== 'false') {
      SESSION_KEYS.forEach(key => {
        const value = sessionStorage.getItem(key)
        if (value !== null) localStorage.setItem(key, value)
        else localStorage.removeItem(key)
        sessionStorage.removeItem(key)
      })
      return localStorage
    }
    return sessionStorage
  }
  return localStorage
}

/**
 * 读取当前会话的访问令牌。
 * :returns: 访问令牌或空值。
 */
export function getStoredAccessToken(): string | null {
  const storage = getAuthStorage()
  return storage.getItem('access_token') || storage.getItem('token')
}

/**
 * 读取当前会话的刷新令牌。
 * :returns: 与访问令牌属于同一会话的刷新令牌。
 */
export function getStoredRefreshToken(): string | null {
  return getAuthStorage().getItem('refresh_token')
}

/**
 * 清除已保存的认证信息和当前课程。
 * :returns: 无。
 */
export function clearStoredAuthTokens(): void {
  const keys = ['access_token', 'refresh_token', 'token', 'userInfo', 'current_course']
  keys.forEach(key => {
    localStorage.removeItem(key)
    sessionStorage.removeItem(key)
  })
}
