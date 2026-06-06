<template>
  <!-- Sidebar reads its structure from the user store so role changes update navigation centrally. -->
  <n-scrollbar class="menu-scrollbar" content-class="scrollbar-wrapper">
    <n-menu
      :value="activeMenu"
      class="sidebar-menu"
      :collapsed="isCollapse"
      :collapsed-width="48"
      :collapsed-icon-size="22"
      :options="menuOptions"
      :indent="18"
      @update:value="handleMenuSelect"
    />
  </n-scrollbar>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { renderIcon } from '@/theme/icons'

defineProps({
  isCollapse: {
    type: Boolean,
    default: false
  }
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// Route path drives the active state because menu indexes already mirror router records.
const menuList = computed(() => userStore.menu)
const activeMenu = computed(() => route.path)

const toMenuOptions = (items = []) => items.map(item => ({
  key: item.index,
  label: item.title,
  icon: item.icon ? renderIcon(item.icon) : undefined,
  children: item.children && item.children.length > 0 ? toMenuOptions(item.children) : undefined
}))

const menuOptions = computed(() => toMenuOptions(menuList.value))

const handleMenuSelect = (key) => {
  if (key && key !== route.path) {
    void router.push(String(key))
  }
}
</script>

<style scoped>
/* Remove the stock menu chrome so the sidebar can inherit the shell's custom surface styling. */
.sidebar-menu {
  border-right: none;
  background-color: transparent;
  padding: 16px 12px 20px;
}

.sidebar-menu :deep(.n-menu-item-content),
.sidebar-menu :deep(.n-menu-item-content-header),
.sidebar-menu :deep(.n-submenu-children .n-menu-item-content) {
  min-height: 46px;
  margin-bottom: 6px;
  border-radius: 16px !important;
  color: var(--sidebar-text) !important;
  font-weight: 600;
  transition: all 0.28s ease;
}

.sidebar-menu :deep(.n-menu-item-content__icon) {
  color: var(--sidebar-icon) !important;
  transition: color 0.28s ease, transform 0.28s ease;
}

.sidebar-menu :deep(.n-menu-item-content.n-menu-item-content--selected) {
  /* Elevated active state makes the current workspace destination scan quickly. */
  color: var(--sidebar-active-text) !important;
  background: var(--sidebar-active-bg) !important;
  box-shadow: 0 12px 24px rgba(15, 108, 189, 0.24);
}

.sidebar-menu :deep(.n-menu-item-content.n-menu-item-content--selected .n-menu-item-content__icon),
.sidebar-menu :deep(.n-menu-item-content.n-menu-item-content--selected .n-menu-item-content-header) {
  color: var(--sidebar-active-text) !important;
  transform: scale(1.04);
}

.sidebar-menu :deep(.n-menu-item-content:hover) {
  background-color: var(--sidebar-hover-bg) !important;
  color: var(--sidebar-text) !important;
  transform: translateX(2px);
}

.sidebar-menu :deep(.n-menu-item-content:hover .n-menu-item-content__icon) {
  color: var(--sidebar-icon) !important;
}

.sidebar-menu :deep(.n-submenu-children) {
  /* Nested menu background creates a clear second level without adding extra separators. */
  background-color: var(--sidebar-submenu-bg) !important;
  border: 1px solid var(--border-light);
  border-radius: 18px;
  margin: 4px 0 10px;
  padding: 6px;
}

.sidebar-menu :deep(.n-menu-item-content--collapsed) {
  /* Collapsed mode centers icons on the actual collapsed menu root, not a nonexistent child wrapper. */
  justify-content: center;
  width: 100%;
  min-width: 0;
  padding-inline: 0 !important;
}

.sidebar-menu :deep(.n-menu-item-content--collapsed .n-menu-item-content__icon) {
  margin: 0 !important;
}

.sidebar-menu :deep(.n-menu-item-content--collapsed:hover) {
  transform: none;
}

.sidebar-menu :deep(.n-menu-item-content__arrow) {
  color: var(--sidebar-text-muted) !important;
}
</style>
