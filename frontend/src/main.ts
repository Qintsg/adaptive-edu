/**
 * 应用入口文件
 * 初始化Vue应用，注册插件和全局组件
 */
import { createApp } from 'vue'
import * as FluentIconsVue from './theme/element-icons'

import { pinia } from './stores'
import router from './router'
import App from './App.vue'
import './styles/index.css'
import './styles/glassmorphism.css'
import { createLogger, installConsoleFormat } from './utils/logger'
import { installNaiveElementAdapter } from './plugins/naive-element-adapter'

installConsoleFormat()
const appLogger = createLogger('应用')

// 创建Vue应用实例
const app = createApp(App)

// 注册 Fluent 图标兼容名，迁移期间保持既有模板图标名可用。
for (const [key, component] of Object.entries(FluentIconsVue)) {
  app.component(key, component)
}

// 注册插件
app.use(pinia)        // Pinia状态管理
app.use(router)       // Vue Router路由
installNaiveElementAdapter(app)

// 全局错误处理
app.config.errorHandler = (err, vm, info) => {
  appLogger.error('全局错误', err)
  appLogger.error('错误信息', info)
}

// 挂载应用
app.mount('#app')
