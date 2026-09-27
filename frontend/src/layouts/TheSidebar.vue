<!-- 角色导航菜单，桌面侧栏与移动端抽屉复用。 -->
<template>
  <!-- 菜单从用户状态读取，角色变化时集中更新导航。 -->
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

const emit = defineEmits(['navigate'])

defineProps({
  isCollapse: {
    type: Boolean,
    default: false
  }
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 菜单路径与路由一致，使用当前路由决定激活项。
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
  emit('navigate')
}
</script>

<style scoped>
/* 移除菜单默认边框，使侧栏沿用工作区表面样式。 */
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
  /* 当前菜单项使用明显的高亮表面。 */
  color: var(--sidebar-active-text) !important;
  background: var(--sidebar-active-bg) !important;
  box-shadow: 0 8px 18px rgba(3, 20, 38, 0.18);
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

.sidebar-menu :deep(.n-menu-item-content.n-menu-item-content--selected:hover) {
  background: var(--sidebar-active-bg) !important;
  color: var(--sidebar-active-text) !important;
}

.sidebar-menu :deep(.n-menu-item-content.n-menu-item-content--selected:hover .n-menu-item-content__icon) {
  color: var(--sidebar-active-text) !important;
}

.sidebar-menu :deep(.n-submenu-children) {
  /* 子菜单通过背景区分层级。 */
  background-color: var(--sidebar-submenu-bg) !important;
  border: 1px solid var(--border-light);
  border-radius: 18px;
  margin: 4px 0 10px;
  padding: 6px;
}

.sidebar-menu :deep(.n-menu-item-content--collapsed) {
  /* 折叠状态在菜单根节点居中图标。 */
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
