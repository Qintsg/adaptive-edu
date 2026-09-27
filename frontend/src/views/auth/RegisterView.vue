<!-- 注册页面：角色选择使用可聚焦按钮，表单与登录页保持一致。 -->
<template>
  <div class="register-view">
    <h2 class="form-title">创建新账号</h2>

    <n-form ref="formRef" :model="form" :rules="rules" label-placement="top" class="register-form"
      @submit.prevent="handleRegister">
      <!-- 用户名 -->
      <n-form-item prop="username" label="用户名">
        <n-input v-model:value="form.username" placeholder="请输入用户名" size="large" clearable
          :input-props="{ autocomplete: 'username', name: 'username' }">
          <template #prefix>
            <AppIcon name="User" />
          </template>
        </n-input>
      </n-form-item>

      <!-- 邮箱 -->
      <n-form-item prop="email" label="邮箱（选填）">
        <n-input v-model:value="form.email" placeholder="请输入邮箱" size="large" clearable
          :input-props="{ autocomplete: 'email', name: 'email' }">
          <template #prefix>
            <AppIcon name="Mail" />
          </template>
        </n-input>
      </n-form-item>

      <!-- 密码 -->
      <n-form-item prop="password" label="密码">
        <n-input v-model:value="form.password" type="password" placeholder="请输入密码（至少8位，包含大写字母和数字）" size="large"
          show-password-on="click" :input-props="{ autocomplete: 'new-password', name: 'password' }">
          <template #prefix>
            <AppIcon name="Lock" />
          </template>
        </n-input>
      </n-form-item>

      <!-- 确认密码 -->
      <n-form-item prop="confirmPassword" label="确认密码">
        <n-input v-model:value="form.confirmPassword" type="password" placeholder="请再次输入密码" size="large"
          show-password-on="click" :input-props="{ autocomplete: 'new-password', name: 'confirm-password' }">
          <template #prefix>
            <AppIcon name="Lock" />
          </template>
        </n-input>
      </n-form-item>

      <!-- 角色选择 -->
      <n-form-item prop="role" label="身份">
        <div class="role-selector">
          <button v-for="role in roles" :key="role.value" type="button"
            :class="['role-card', { active: form.role === role.value }]"
            :aria-pressed="form.role === role.value"
            @click="form.role = role.value">
            <AppIcon class="role-icon" :name="role.icon" :size="28" />
            <span class="role-label">{{ role.label }}</span>
          </button>
        </div>
      </n-form-item>

      <!-- 激活码（教师/管理员需要） -->
      <n-form-item v-if="needActivationCode" prop="activation_code" label="教师激活码">
        <n-input v-model:value="form.activation_code" placeholder="请输入激活码" size="large">
          <template #prefix>
            <AppIcon name="Key" />
          </template>
        </n-input>
      </n-form-item>

      <!-- 注册按钮 -->
      <n-form-item>
        <n-button attr-type="submit" type="primary" size="large" class="submit-btn" :loading="loading">
          {{ loading ? '正在注册…' : '注册' }}
        </n-button>
      </n-form-item>

      <!-- 登录链接 -->
      <div class="form-footer">
        <span>已有账号？</span>
        <router-link to="/login" class="login-link">立即登录</router-link>
      </div>
    </n-form>
  </div>
</template>

<script setup>
/**
 * 注册视图组件
 * 提供用户注册功能
 */
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import AppIcon from '@/components/common/AppIcon.vue'
import { showError, showSuccess } from '@/utils/feedback'

const router = useRouter()
const userStore = useUserStore()

// 表单引用
const formRef = ref(null)

// 加载状态
const loading = ref(false)

// 角色列表
const roles = [
  { value: 'student', label: '学生', icon: 'Reading' },
  { value: 'teacher', label: '教师', icon: 'School' }
]

// 表单数据
const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  role: 'student',
  activation_code: ''
})

// 是否需要激活码
const needActivationCode = computed(() => {
  return ['teacher', 'admin'].includes(form.role)
})

// 密码验证
const validatePassword = (_rule, value) => {
  if (!value) {
    return new Error('请输入密码')
  }
  if (value.length < 8) return new Error('密码长度至少8位')
  if (!/[A-Z]/.test(value)) return new Error('密码必须包含大写字母')
  if (!/[0-9]/.test(value)) return new Error('密码必须包含数字')
  return true
}

// 确认密码验证
const validateConfirmPassword = (_rule, value) => {
  if (!value) {
    return new Error('请确认密码')
  }
  if (value !== form.password) return new Error('两次输入的密码不一致')
  return true
}

// 表单验证规则
const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度为3-50个字符', trigger: 'blur' }
  ],
  email: [
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, validator: validatePassword, trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, validator: validateConfirmPassword, trigger: 'blur' }
  ],
  role: [
    { required: true, message: '请选择身份', trigger: 'change' }
  ],
  activation_code: [
    { required: true, message: '教师/管理员需要激活码', trigger: 'blur' }
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

/**
 * 处理注册
 */
const handleRegister = async () => {
  if (loading.value) return
  // 验证表单
  const valid = await validateForm()
  if (!valid) return

  loading.value = true
  try {
    // 构建注册数据
    const registerData = {
      username: form.username,
      password: form.password,
      role: form.role
    }

    if (form.email) {
      registerData.email = form.email
    }

    if (needActivationCode.value) {
      registerData.activation_code = form.activation_code
    }

    // 调用注册API
    await userStore.register(registerData)
    showSuccess('注册成功，欢迎加入！')

    // 根据角色跳转到对应页面
    if (userStore.isAdmin) {
      await router.push({ name: 'AdminDashboard' })
    } else if (userStore.isTeacher) {
      await router.push({ name: 'TeacherDashboard' })
    } else if (userStore.isStudent) {
      await router.push({ name: 'StudentDashboard' })
    } else {
      await router.push('/')
    }
  } catch (error) {
    console.error('注册失败:', error)
    showError(error.message || '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-view {
  width: 100%;
}

.form-title {
  font-size: clamp(27px, 3vw, 34px);
  font-weight: 760;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.form-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 24px;
}

.register-form {
  width: 100%;
}

.register-form :deep(.n-form-item-label) {
  color: var(--text-regular);
  font-weight: 650;
}
.register-form :deep(.n-input) {
  min-height: 46px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fff;
}
.register-form :deep(.n-input.n-input--focus) {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(15, 108, 189, 0.12);
}

/* 角色选择器 */
.role-selector {
  width: 100%;
  display: flex;
  gap: 12px;
}

.role-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 86px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.role-card:hover {
  border-color: var(--primary-color);
  background: #f1f8fe;
}

.role-card.active {
  border-color: var(--primary-color);
  background: #eaf5ff;
  box-shadow: 0 0 0 2px rgba(15, 108, 189, 0.1);
}

.role-icon {
  font-size: 28px;
  color: var(--text-secondary);
  margin-bottom: 8px;
  transition: color 0.3s;
}

.role-card.active .role-icon {
  color: var(--primary-color);
}

.role-label {
  font-size: 14px;
  color: var(--text-regular);
  font-weight: 650;
}

.role-card.active .role-label {
  color: var(--primary-dark);
}

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
  margin-top: 16px;
}

.login-link {
  margin-left: 8px;
  color: var(--primary-color);
  text-decoration: none;
  font-weight: 700;
}

.login-link:hover {
  color: var(--primary-dark);
  text-decoration: underline;
}
</style>
