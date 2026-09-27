<!-- 登录页面：保留角色跳转与记住登录状态，统一表单视觉和键盘提交。 -->
<template>
  <!-- 登录表单同时提供密码找回提示与注册入口。 -->
  <div class="login-view w-full">
    <div class="form-heading">
      <h2 class="form-title">登录自适应学习</h2>
      <p class="form-desc">登录后查看课程、学习路径和最近进展。</p>
    </div>

    <n-form ref="formRef" :model="form" :rules="rules" label-placement="top" class="login-form"
      @submit.prevent="handleLogin">
      <n-form-item prop="username" label="用户名">
        <n-input v-model:value="form.username" placeholder="请输入用户名" size="large" clearable
          :input-props="{ autocomplete: 'username', name: 'username' }">
          <template #prefix>
            <AppIcon name="User" />
          </template>
        </n-input>
      </n-form-item>

      <n-form-item prop="password" label="密码">
        <n-input v-model:value="form.password" type="password" placeholder="请输入密码" size="large"
          show-password-on="click" :input-props="{ autocomplete: 'current-password', name: 'password' }">
          <template #prefix>
            <AppIcon name="Lock" />
          </template>
        </n-input>
      </n-form-item>

      <n-form-item>
        <div class="form-options">
          <n-checkbox v-model:checked="rememberMe">记住我</n-checkbox>
          <button type="button" class="forgot-link" @click="showForgotPasswordHint">忘记密码？</button>
        </div>
      </n-form-item>

      <n-form-item>
        <n-button attr-type="submit" type="primary" size="large" class="submit-btn" :loading="loading">
          {{ loading ? '正在登录…' : '登录' }}
        </n-button>
      </n-form-item>

      <div class="form-footer mt-6">
        <span>还没有账号？</span>
        <router-link to="/register" class="register-link">立即注册</router-link>
      </div>
    </n-form>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { extractApiErrorMessage, isApiErrorHandled } from '@/api'
import { useUserStore } from '@/stores/user'
import AppIcon from '@/components/common/AppIcon.vue'
import { showError, showInfo, showSuccess } from '@/utils/feedback'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref(null)
const loading = ref(false)

// 登录状态的持久化策略由用户状态仓库决定。
const rememberMe = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度为3-50个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码长度不能少于8位', trigger: 'blur' }
  ]
}

const validateForm = async () => {
  try {
    await formRef.value?.validate()
    return true
  } catch {
    return false
  }
}

const showForgotPasswordHint = () => {
  showInfo('请联系管理员重置密码')
}

const handleLogin = async () => {
  if (loading.value) return
  // 键盘和按钮提交共用表单校验。
  const valid = await validateForm()
  if (!valid) return

  loading.value = true
  try {
    await userStore.login({ ...form, rememberMe: rememberMe.value })
    showSuccess('登录成功，欢迎回来！')

    // 优先返回登录前页面，否则进入当前角色首页。
    const redirect = route.query.redirect
    if (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) {
      await router.push(redirect)
    } else if (userStore.isAdmin) {
      await router.push({ name: 'AdminDashboard' })
    } else if (userStore.isTeacher) {
      await router.push({ name: 'TeacherDashboard' })
    } else if (userStore.isStudent) {
      await router.push({ name: 'StudentDashboard' })
    } else {
      await router.push('/')
    }
  } catch (error) {
    // Surface backend auth feedback while still logging the raw error for local diagnosis.
    console.error('登录失败:', error)
    if (!isApiErrorHandled(error)) {
      showError(extractApiErrorMessage(error, '登录失败，请检查用户名和密码'))
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.form-heading { margin-bottom: 32px; }
.form-title {
  font-size: clamp(27px, 3vw, 34px);
  font-weight: 760;
  color: var(--text-primary);
  line-height: 1.35;
  letter-spacing: -0.03em;
  margin: 0 0 10px;
}
.form-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}
.login-form :deep(.n-form-item-label) {
  color: var(--text-regular);
  font-weight: 650;
}
.login-form :deep(.n-input) {
  min-height: 46px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fff;
}
.login-form :deep(.n-input.n-input--focus) {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(15, 108, 189, 0.12);
}
.form-options {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.forgot-link {
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: var(--primary-color);
  font-size: 14px;
  cursor: pointer;
}
.forgot-link:hover { color: var(--primary-dark); text-decoration: underline; }
.submit-btn {
  width: 100%;
  height: 48px;
  font-size: 15px;
  font-weight: 700;
  border-radius: 12px;
  background: var(--primary-color) !important;
  color: #fff !important;
  box-shadow: 0 10px 22px rgba(15, 108, 189, 0.2);
}
.submit-btn:hover {
  background: var(--primary-dark) !important;
  box-shadow: 0 12px 25px rgba(15, 108, 189, 0.24);
}
.form-footer {
  text-align: center;
  font-size: 14px;
  color: var(--text-secondary);
}
.register-link {
  margin-left: 8px;
  color: var(--primary-color);
  text-decoration: none;
  font-weight: 700;
}
.register-link:hover { color: var(--primary-dark); text-decoration: underline; }
</style>
