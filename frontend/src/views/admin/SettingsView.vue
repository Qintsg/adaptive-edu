<template>
  <!-- Settings are grouped by administrator intent so simple system toggles stay easy to scan. -->
  <div class="settings-view">
    <n-card class="settings-card" shadow="hover">
      <template #header>
        <span>基本设置</span>
      </template>
      <n-form :model="basicSettings" label-width="120px" style="max-width: 600px;">
        <n-form-item label="系统名称">
          <n-input v-model="basicSettings.siteName" />
        </n-form-item>
        <n-form-item label="系统描述">
          <n-input v-model="basicSettings.siteDesc" type="textarea" :rows="3" />
        </n-form-item>
        <n-form-item label="联系邮箱">
          <n-input v-model="basicSettings.contactEmail" />
        </n-form-item>
        <n-form-item>
          <n-button type="primary" @click="saveBasic">保存设置</n-button>
        </n-form-item>
      </n-form>
    </n-card>

    <n-card class="settings-card" shadow="hover">
      <template #header>
        <span>安全设置</span>
      </template>
      <n-form :model="securitySettings" label-width="120px" style="max-width: 600px;">
        <n-form-item label="允许注册">
          <n-switch v-model="securitySettings.allowRegister" />
        </n-form-item>
        <n-form-item label="登录验证码">
          <n-switch v-model="securitySettings.loginCaptcha" />
        </n-form-item>
        <n-form-item label="密码强度要求">
          <n-select v-model="securitySettings.passwordStrength" style="width: 200px;">
            <n-option label="低（6位以上）" value="low" />
            <n-option label="中（8位+数字）" value="medium" />
            <n-option label="高（8位+大写+数字）" value="high" />
          </n-select>
        </n-form-item>
        <n-form-item>
          <n-button type="primary" @click="saveSecurity">保存设置</n-button>
        </n-form-item>
      </n-form>
    </n-card>

    <n-card class="settings-card" shadow="hover">
      <template #header>
        <span>数据管理</span>
      </template>
      <div class="data-actions">
        <n-button @click="backupData">备份数据</n-button>
        <n-button type="warning" @click="clearCache">清除缓存</n-button>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { appMessage } from '@/utils/feedback'

// Local reactive state keeps the demo form editable even before backend persistence is wired in.
const basicSettings = reactive({
  siteName: '自适应学习系统',
  siteDesc: '知识图谱驱动的个性化自适应学习系统',
  contactEmail: 'admin@adaptive-edu.com'
})

const securitySettings = reactive({
  allowRegister: true,
  loginCaptcha: false,
  passwordStrength: 'high'
})

// Feedback is intentionally immediate because these actions currently represent placeholder admin flows.
const saveBasic = () => appMessage.success('基本设置已保存')
const saveSecurity = () => appMessage.success('安全设置已保存')
const backupData = () => appMessage.success('数据备份已开始')
const clearCache = () => appMessage.success('缓存已清除')
</script>

<style scoped>
/* Constrain width so long form labels remain readable on large admin dashboards. */
.settings-view {
  max-width: 900px;
}

.settings-card {
  margin-bottom: 20px;
}

.data-actions {
  display: flex;
  gap: 12px;
}
</style>
