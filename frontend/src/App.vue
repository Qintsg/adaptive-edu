<script setup lang="ts">
/**
 * 主应用组件
 * 提供全局配置和根路由视图
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  NConfigProvider,
  NDialogProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NNotificationProvider,
  dateZhCN,
  zhCN
} from 'naive-ui'
import AppFeedbackProvider from '@/components/common/AppFeedbackProvider.vue'
import { naiveThemeOverrides } from '@/theme/naive'

const route = useRoute()

// 根据当前路由判断是否需要显示布局过渡动画
const transitionName = computed(() => {
  return String(route.meta.transition || 'fade')
})
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="naiveThemeOverrides">
    <n-message-provider placement="top-right">
      <n-dialog-provider>
        <n-notification-provider placement="top-right">
          <n-loading-bar-provider>
            <app-feedback-provider>
              <router-view v-slot="{ Component }">
                <transition :name="transitionName" mode="out-in">
                  <component :is="Component" />
                </transition>
              </router-view>
            </app-feedback-provider>
          </n-loading-bar-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
/* 全局过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 滑动过渡动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from {
  opacity: 0;
  transform: translateX(30px);
}

.slide-leave-to {
  opacity: 0;
  transform: translateX(-30px);
}
</style>
