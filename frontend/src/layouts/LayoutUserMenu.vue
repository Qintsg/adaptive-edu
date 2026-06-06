<template>
  <!-- Account menu groups profile actions and role-specific shortcuts behind one stable trigger. -->
  <n-dropdown trigger="click" :options="menuOptions" @select="$emit('command', $event)">
    <div class="user-dropdown">
      <n-avatar v-if="avatarUrl" :size="32" :src="avatarUrl" class="user-avatar" />
      <n-avatar v-else :size="32" class="user-avatar">
        {{ avatarText }}
      </n-avatar>
      <span class="user-name">{{ displayName }}</span>
      <AppIcon name="ChevronDown" class="dropdown-arrow" />
    </div>
  </n-dropdown>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { renderIcon } from '@/theme/icons'

// The parent decides command handling so this menu stays presentational and reusable.
const props = defineProps({
  avatarUrl: { type: String, default: null },
  avatarText: { type: String, default: '' },
  displayName: { type: String, default: '用户' },
  userRole: { type: String, default: '' }
})

defineEmits(['command'])

const menuOptions = computed(() => {
  const options = [
    { label: '个人信息', key: 'profile', icon: renderIcon('User') },
    { label: '个人设置', key: 'settings', icon: renderIcon('Setting') }
  ]

  if (props.userRole === 'admin') {
    options.push({ label: '系统设置', key: 'system-settings', icon: renderIcon('Settings') })
  }

  options.push(
    { type: 'divider', key: 'divider' },
    { label: '退出登录', key: 'logout', icon: renderIcon('SignOut') }
  )

  return options
})
</script>

<style scoped>
/* Rounded container keeps the header action visually lightweight next to course switching. */
.user-dropdown {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 10px;
  border-radius: 999px;
  cursor: pointer;
  border: 1px solid var(--border-light);
  background: var(--bg-elevated);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  transition: all 0.3s;
}

.user-dropdown:hover {
  background: var(--bg-soft-alt);
}

.user-avatar {
  /* Fallback initials need the same emphasis as uploaded avatars. */
  background: var(--primary-color);
  color: #fff;
  font-weight: 600;
}

.user-name {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 700;
}

.dropdown-arrow {
  color: var(--text-secondary);
}

</style>
