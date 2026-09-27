<!-- 默认工作区布局：桌面侧栏与移动端抽屉共享同一套角色导航。 -->
<template>
  <div class="default-layout">
    <button v-if="isMobile && isMobileMenuOpen" class="mobile-backdrop" type="button"
      aria-label="关闭导航菜单" @click="closeMobileMenu" />
    <aside class="layout-sidebar glass-sidebar" :class="{ 'is-mobile-open': isMobileMenuOpen }"
      :style="{ width: isMobile ? '264px' : isCollapsed ? '72px' : '252px' }"
      :aria-hidden="isMobile && !isMobileMenuOpen" :inert="isMobile && !isMobileMenuOpen">
      <button class="sidebar-logo" :class="{ 'is-collapsed': isCollapsed && !isMobile }" type="button"
        aria-label="返回首页" @click="goHome">
        <img src="/images/logo.svg" alt="Logo" class="logo-image" />
        <transition name="fade">
          <span v-show="isMobile || !isCollapsed" class="logo-text">{{ systemTitle }}</span>
        </transition>
      </button>

      <TheSidebar :is-collapse="!isMobile && isCollapsed" @navigate="closeMobileMenu" />
    </aside>

    <section class="layout-main-container">
      <div class="layout-ambient" aria-hidden="true">
        <span class="ambient-orb ambient-orb--primary" />
        <span class="ambient-orb ambient-orb--accent" />
      </div>

      <header class="layout-header glass-header">
        <div class="header-left">
          <button class="collapse-trigger" type="button" :aria-label="isMobile ? '打开导航菜单' : '切换侧边栏'"
            :aria-expanded="isMobile ? isMobileMenuOpen : !isCollapsed" @click="toggleCollapse">
            <AppIcon :name="isMobile || !isCollapsed ? 'List' : 'Navigation'" :size="22" />
          </button>

          <nav class="breadcrumb" aria-label="当前位置">
            <button type="button" class="breadcrumb-link" @click="goHome">首页</button>
            <span v-if="currentPageTitle" class="breadcrumb-separator">/</span>
            <span v-if="currentPageTitle" class="breadcrumb-current">
              {{ currentPageTitle }}
            </span>
          </nav>
        </div>

        <div class="header-right">
          <LayoutCourseSwitcher :visible="showCourseSelector" :current-course="currentCourse" :courses="courses"
            :user-role="userRole" @change="handleCourseChange" />

          <LayoutUserMenu :avatar-url="avatarUrl" :avatar-text="avatarText" :display-name="displayName"
            :user-role="userRole" @command="handleUserCommand" />
        </div>
      </header>

      <main ref="mainScrollRef" class="layout-main">
        <router-view v-slot="{ Component, route: viewRoute }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" :key="resolveRouteKey(viewRoute)" />
          </transition>
        </router-view>
      </main>
    </section>
  </div>
</template>

<script setup>
/**
 * 默认布局组件
 * 适用于学生端、教师端、管理端
 * 包含侧边栏导航、顶部栏、面包屑、用户菜单等
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useCourseStore } from '@/stores/course'
import { selectCourse as selectCourseApi } from '@/api/course'
import TheSidebar from './TheSidebar.vue'
import LayoutCourseSwitcher from './LayoutCourseSwitcher.vue'
import LayoutUserMenu from './LayoutUserMenu.vue'
import { toBackendAbsoluteUrl } from '@/api/backend'
import AppIcon from '@/components/common/AppIcon.vue'
import { confirmAction, showError, showSuccess } from '@/utils/feedback'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const courseStore = useCourseStore()

const normalizeText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const normalizeUserProfile = (value) => {
  const userInfo = value && typeof value === 'object' ? value : {}
  const displayName = normalizeText(userInfo?.['real_name'] ?? userInfo?.['username']) || '用户'
  return {
    displayName,
    avatar: normalizeText(userInfo?.['avatar']),
    username: normalizeText(userInfo?.['username']) || displayName
  }
}

const normalizeCourseSummary = (value) => {
  const courseInfo = value && typeof value === 'object' ? value : {}
  return {
    courseId: courseInfo?.['course_id'] ?? courseInfo?.['id'] ?? null,
    classId: courseInfo?.['class_id'] ?? courseInfo?.['classId'] ?? null,
    courseName: normalizeText(courseInfo?.['course_name'] ?? courseInfo?.['name']),
    className: normalizeText(courseInfo?.['class_name'] ?? courseInfo?.['className'])
  }
}

const resolveRouteKey = (value) => {
  const routeInfo = value && typeof value === 'object' ? value : {}
  return normalizeText(routeInfo?.['fullPath'] ?? routeInfo?.['path'] ?? routeInfo?.['name']) || homeRoute.value
}

const isCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
const isMobile = ref(window.innerWidth < 992)
const isMobileMenuOpen = ref(false)
const mainScrollRef = ref(null)
const userRole = computed(() => userStore.userRole)

const currentUserProfile = computed(() => normalizeUserProfile(userStore.user))
const displayName = computed(() => currentUserProfile.value.displayName)
const avatarUrl = computed(() => {
  const rawAvatar = currentUserProfile.value.avatar
  if (!rawAvatar) return null
  return toBackendAbsoluteUrl(rawAvatar)
})

const avatarText = computed(() => {
  const name = displayName.value
  return name.charAt(0).toUpperCase()
})

const showCourseSelector = computed(() => {
  return ['student', 'teacher'].includes(userRole.value)
})

const currentCourse = computed(() => courseStore.currentCourse)
const courses = computed(() => courseStore.courses)
const systemTitle = computed(() => {
  const titles = {
    student: '自适应学习',
    teacher: '教师端',
    admin: '管理后台'
  }
  return titles[userRole.value] || '自适应学习'
})

const homeRoute = computed(() => {
  const homes = {
    student: '/student/dashboard',
    teacher: '/teacher/dashboard',
    admin: '/admin/dashboard'
  }
  return homes[userRole.value] || '/'
})

const currentPageTitle = computed(() => normalizeText(route?.['meta']?.['title']))

onMounted(async () => {
  await userStore.fetchMenu()
})

/**
 * 切换侧边栏折叠状态
 */
const toggleCollapse = () => {
  if (isMobile.value) {
    isMobileMenuOpen.value = !isMobileMenuOpen.value
    return
  }
  isCollapsed.value = !isCollapsed.value
  localStorage.setItem('sidebar_collapsed', isCollapsed.value)
}

/**
 * 关闭移动端导航抽屉。
 */
const closeMobileMenu = () => {
  isMobileMenuOpen.value = false
}

const handleResize = () => {
  isMobile.value = window.innerWidth < 992
  closeMobileMenu()
}

/**
 * 支持 Escape 键关闭移动端导航。
 * :param {KeyboardEvent} event - 键盘事件
 */
const handleKeydown = (event) => {
  if (event.key === 'Escape') closeMobileMenu()
}
onMounted(() => {
  handleResize()
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleKeydown)
})
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleKeydown)
})

/**
 * 返回首页
 */
const goHome = () => {
  closeMobileMenu()
  void router.push(homeRoute.value)
}

/**
 * 处理课程切换
 * @param {Object|string} command - 课程对象或命令
 */
const handleCourseChange = async (command) => {
  if (command === 'switch') {
    await router.push({ name: 'CourseSelect' })
  } else {
    const selectedCourse = normalizeCourseSummary(command)
    if (!selectedCourse.courseId) return

    try {
      const selectedCourseResponse = normalizeCourseSummary(await selectCourseApi({
        course_id: selectedCourse.courseId,
        class_id: selectedCourse.classId
      }))
      courseStore.setCurrentCourse({
        course_id: selectedCourseResponse.courseId || selectedCourse.courseId,
        course_name: selectedCourseResponse.courseName || selectedCourse.courseName,
        class_id: selectedCourseResponse.classId || selectedCourse.classId,
        class_name: selectedCourseResponse.className || selectedCourse.className
      })
      showSuccess(`已切换到课程：${selectedCourseResponse.courseName || selectedCourse.courseName}`)
    } catch (error) {
      console.error('切换课程失败:', error)
      showError('切换课程失败，请稍后重试')
    }
  }
}

/**
 * 处理用户菜单命令
 * @param {string} command - 菜单命令
 */
const handleUserCommand = async (command) => {
  switch (command) {
    case 'profile':
      if (userRole.value === 'student') {
        await router.push({ name: 'StudentProfile' })
      } else if (userRole.value === 'teacher') {
        await router.push({ name: 'TeacherSettings' })
      } else if (userRole.value === 'admin') {
        await router.push({ name: 'AdminSettings' })
      }
      break
    case 'settings':
      if (userRole.value === 'student') {
        await router.push({ name: 'StudentSettings' })
      } else if (userRole.value === 'teacher') {
        await router.push({ name: 'TeacherSettings' })
      } else if (userRole.value === 'admin') {
        await router.push({ name: 'AdminSettings' })
      }
      break
    case 'system-settings':
      if (userRole.value === 'admin') {
        await router.push({ name: 'AdminSettings' })
      }
      break
    case 'logout':
      await handleLogout()
      break
  }
}

/**
 * 处理退出登录
 */
const handleLogout = async () => {
  try {
    await confirmAction({
      title: '退出确认',
      content: '确定要退出登录吗？',
      positiveText: '确定退出',
      negativeText: '取消'
    })

    // 先退出登录并跳转，避免当前页面在卸载前响应课程清空导致额外警告
    userStore.logout()

    showSuccess('已退出登录')
    setTimeout(() => {
      courseStore.clearSelection()
    }, 0)
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  if (showCourseSelector.value) {
    void courseStore.fetchCourses()
  }
})

watch(
  () => resolveRouteKey(route),
  () => {
    closeMobileMenu()
    if (mainScrollRef.value) mainScrollRef.value.scrollTop = 0
    if (showCourseSelector.value && (!courses.value.length || !currentCourse.value)) {
      void courseStore.fetchCourses()
    }
  }
)
</script>

<style scoped src="./DefaultLayout.css"></style>
