<template>
  <div class="user-manage-view">
    <n-card class="page-header" shadow="never">
      <div class="header-content">
        <h2>用户管理</h2>
        <n-button type="primary" @click="openCreateDialog">
          <n-icon>
            <Plus />
          </n-icon> 添加用户
        </n-button>
      </div>
    </n-card>

    <n-card shadow="hover">
      <div class="filter-bar">
        <n-select v-model="userFilter.roleCode" placeholder="用户角色" clearable style="width: 120px;" @change="loadUsers">
          <n-option label="学生" value="student" />
          <n-option label="教师" value="teacher" />
          <n-option label="管理员" value="admin" />
        </n-select>
        <n-input v-model="userFilter.keywordText" placeholder="搜索用户名" clearable style="width: 200px;"
          @keyup.enter="loadUsers" />
        <n-button type="primary" @click="loadUsers">搜索</n-button>
      </div>

      <n-table :data="userRecords" v-loading="loading" style="width: 100%;">
        <n-table-column prop="username" label="用户名" width="120" />
        <n-table-column prop="realNameText" label="姓名" width="100">
          <template #default="{ row }">{{ row.realNameText || '-' }}</template>
        </n-table-column>
        <n-table-column prop="emailText" label="邮箱" />
        <n-table-column prop="phoneText" label="手机号" width="130">
          <template #default="{ row }">{{ row.phoneText || '-' }}</template>
        </n-table-column>
        <n-table-column prop="roleCode" label="角色" width="100">
          <template #default="{ row }">
            <n-tag :type="getRoleType(row.roleCode)">{{ getRoleText(row.roleCode) }}</n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="statusText" label="状态" width="80">
          <template #default="{ row }">
            <n-tag :type="row.statusText === 'active' ? 'success' : 'danger'" size="small">
              {{ row.statusText === 'active' ? '正常' : '禁用' }}
            </n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="lastLoginText" label="最后登录" width="160" />
        <n-table-column prop="createdAtText" label="注册时间" width="120" />
        <n-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <n-button type="primary" link @click="editUser(row)">编辑</n-button>
            <n-button :type="row.statusText === 'active' ? 'warning' : 'success'" link @click="toggleStatus(row)">
              {{ row.statusText === 'active' ? '禁用' : '启用' }}
            </n-button>
            <n-button type="danger" link @click="deleteUser(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无用户数据" />
        </template>
      </n-table>

      <n-pagination class="pagination" layout="total, sizes, prev, pager, next" :total="totalUserCount"
        :page-sizes="[10, 20, 50]" v-model:current-page="pagination.currentPage" v-model:page-size="pagination.pageSize"
        @size-change="loadUsers" @current-change="loadUsers" />
    </n-card>

    <!-- 创建/编辑用户对话框 -->
    <n-dialog v-model="isUserDialogVisible" :title="isEditingUser ? '编辑用户' : '添加用户'" width="500px">
      <n-form :model="userForm" label-width="80px">
        <n-form-item label="用户名" required>
          <n-input v-model="userForm.username" placeholder="请输入用户名" :disabled="isEditingUser" />
        </n-form-item>
        <n-form-item label="姓名">
          <n-input v-model="userForm.realName" placeholder="请输入真实姓名" />
        </n-form-item>
        <n-form-item label="邮箱">
          <n-input v-model="userForm.email" placeholder="请输入邮箱" />
        </n-form-item>
        <n-form-item label="手机号">
          <n-input v-model="userForm.phone" placeholder="请输入手机号" />
        </n-form-item>
        <n-form-item label="密码" :required="!isEditingUser">
          <n-input v-model="userForm.password" type="password" :placeholder="isEditingUser ? '留空则不修改' : '请输入密码'" />
        </n-form-item>
        <n-form-item label="角色" required>
          <n-select v-model="userForm.roleCode" placeholder="请选择角色" style="width: 100%;">
            <n-option label="学生" value="student" />
            <n-option label="教师" value="teacher" />
            <n-option label="管理员" value="admin" />
          </n-select>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="closeUserDialog">取消</n-button>
        <n-button type="primary" :loading="saveLoading" @click="saveUser">保存</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
/**
 * 管理端 - 用户管理视图
 * 管理用户、添加/编辑/删除用户、启用/禁用用户等功能
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { appMessage, appDialog } from '@/utils/feedback'
import { Plus } from '@/theme/element-icons'
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser as apiDeleteUser,
  enableUser,
  disableUser
} from '@/api/admin/user'

/**
 * 收敛文本值，避免模板直接依赖后端动态字段。
 * @param {unknown} rawValue
 * @returns {string}
 */
const normalizeText = (rawValue) => {
  if (typeof rawValue === 'string') {
    return rawValue
  }
  if (typeof rawValue === 'number') {
    return String(rawValue)
  }
  return ''
}

/**
 * 收敛标识符。
 * @param {unknown} rawValue
 * @returns {string}
 */
const normalizeIdentifier = (rawValue) => {
  return normalizeText(rawValue).trim()
}

/**
 * 收敛数值。
 * @param {unknown} rawValue
 * @param {number} fallbackValue
 * @returns {number}
 */
const normalizeNumber = (rawValue, fallbackValue = 0) => {
  const parsedValue = Number(rawValue)
  return Number.isFinite(parsedValue) ? parsedValue : fallbackValue
}

/**
 * 收敛布尔值。
 * @param {unknown} rawValue
 * @param {boolean} fallbackValue
 * @returns {boolean}
 */
const normalizeBoolean = (rawValue, fallbackValue = false) => {
  if (typeof rawValue === 'boolean') {
    return rawValue
  }
  if (typeof rawValue === 'number') {
    return rawValue !== 0
  }
  if (typeof rawValue === 'string') {
    const loweredValue = rawValue.trim().toLowerCase()
    if (['true', '1', 'yes', 'active'].includes(loweredValue)) {
      return true
    }
    if (['false', '0', 'no', 'inactive', 'disabled'].includes(loweredValue)) {
      return false
    }
  }
  return fallbackValue
}

/**
 * 将任意 payload 收敛为对象。
 * @param {unknown} rawValue
 * @returns {Record<string, unknown>}
 */
const normalizeObjectFromPayload = (rawValue) => {
  return rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)
    ? rawValue
    : {}
}

/**
 * 将任意 payload 收敛为数组。
 * @param {unknown} rawValue
 * @returns {Array<Record<string, unknown>>}
 */
const normalizeListFromPayload = (rawValue) => {
  return Array.isArray(rawValue) ? rawValue : []
}

const buildDefaultUserRecord = () => ({
  userId: '',
  username: '',
  realNameText: '',
  emailText: '',
  phoneText: '',
  roleCode: 'student',
  statusText: 'active',
  lastLoginText: '',
  createdAtText: ''
})

const buildDefaultUserForm = () => ({
  username: '',
  realName: '',
  email: '',
  phone: '',
  password: '',
  roleCode: 'student'
})

/**
 * 格式化日期展示。
 * @param {unknown} rawDateText
 * @returns {string}
 */
const formatDate = (rawDateText) => {
  const dateText = normalizeText(rawDateText)
  if (!dateText) {
    return ''
  }
  const parsedDate = new Date(dateText)
  return Number.isNaN(parsedDate.getTime()) ? dateText : parsedDate.toLocaleDateString('zh-CN')
}

/**
 * 统一收敛用户状态。
 * @param {unknown} rawStatus
 * @param {unknown} rawIsActive
 * @returns {'active' | 'disabled'}
 */
const normalizeUserStatus = (rawStatus, rawIsActive) => {
  const statusText = normalizeText(rawStatus).trim().toLowerCase()
  if (statusText === 'active') {
    return 'active'
  }
  if (['inactive', 'disabled'].includes(statusText)) {
    return 'disabled'
  }
  return normalizeBoolean(rawIsActive, true) ? 'active' : 'disabled'
}

/**
 * 收敛用户列表项。
 * @param {unknown} rawPayload
 * @returns {{userId: string, username: string, realNameText: string, emailText: string, phoneText: string, roleCode: string, statusText: 'active' | 'disabled', lastLoginText: string, createdAtText: string}}
 */
const normalizeUserRecord = (rawPayload) => {
  const payload = normalizeObjectFromPayload(rawPayload)
  return {
    userId: normalizeIdentifier(payload.user_id ?? payload.id),
    username: normalizeText(payload.username),
    realNameText: normalizeText(payload.real_name ?? payload.first_name),
    emailText: normalizeText(payload.email),
    phoneText: normalizeText(payload.phone ?? payload.phone_number),
    roleCode: normalizeText(payload.role) || 'student',
    statusText: normalizeUserStatus(payload.status, payload.is_active),
    lastLoginText: formatDate(payload.last_login),
    createdAtText: formatDate(payload.date_joined ?? payload.created_at)
  }
}

/**
 * 收敛用户列表接口数据。
 * @param {unknown} rawPayload
 * @returns {{records: Array, totalCount: number}}
 */
const normalizeUserListPayload = (rawPayload) => {
  const payload = normalizeObjectFromPayload(rawPayload)
  const records = normalizeListFromPayload(payload.users).map(normalizeUserRecord)
  return {
    records,
    totalCount: normalizeNumber(payload.total, records.length)
  }
}

const resetUserForm = (userForm) => {
  Object.assign(userForm, buildDefaultUserForm())
}

// 加载状态
const loading = ref(true)
const saveLoading = ref(false)

// 筛选条件
const userFilter = reactive({ roleCode: '', keywordText: '' })

// 分页
const pagination = reactive({ currentPage: 1, pageSize: 10 })
const totalUserCount = ref(0)

// 用户列表
const userRecords = ref([])

// 创建/编辑对话框
const isUserDialogVisible = ref(false)
const editingUserRecord = ref(buildDefaultUserRecord())
const isEditingUser = computed(() => Boolean(editingUserRecord.value.userId))
const userForm = reactive(buildDefaultUserForm())

/**
 * 加载用户列表
 */
const loadUsers = async () => {
  loading.value = true
  try {
    const requestParams = {
      page: pagination.currentPage,
      size: pagination.pageSize
    }
    if (userFilter.roleCode) requestParams.role = userFilter.roleCode
    if (userFilter.keywordText) requestParams.query = userFilter.keywordText

    const { records, totalCount } = normalizeUserListPayload(await getUsers(requestParams))
    userRecords.value = records
    totalUserCount.value = totalCount
  } catch (error) {
    console.error('获取用户列表失败:', error)
    appMessage.error('获取用户列表失败')
  } finally {
    loading.value = false
  }
}

/**
 * 获取角色类型
 */
const getRoleType = (roleCode) => ({ admin: 'danger', teacher: 'warning', student: 'primary' }[roleCode] || 'info')

/**
 * 获取角色文本
 */
const getRoleText = (roleCode) => ({ admin: '管理员', teacher: '教师', student: '学生' }[roleCode] || '未知')

/**
 * 打开创建用户对话框。
 */
const openCreateDialog = () => {
  editingUserRecord.value = buildDefaultUserRecord()
  resetUserForm(userForm)
  isUserDialogVisible.value = true
}

/**
 * 编辑用户
 */
const editUser = (userRecord) => {
  editingUserRecord.value = { ...userRecord }
  Object.assign(userForm, {
    username: userRecord.username,
    realName: userRecord.realNameText || '',
    email: userRecord.emailText,
    phone: userRecord.phoneText || '',
    password: '',
    roleCode: userRecord.roleCode
  })
  isUserDialogVisible.value = true
}

/**
 * 关闭对话框
 */
const closeUserDialog = () => {
  isUserDialogVisible.value = false
  editingUserRecord.value = buildDefaultUserRecord()
  resetUserForm(userForm)
}

/**
 * 保存用户
 */
const saveUser = async () => {
  if (!userForm.username) {
    appMessage.warning('请输入用户名')
    return
  }
  if (!isEditingUser.value && !userForm.password) {
    appMessage.warning('请输入密码')
    return
  }
  if (!userForm.roleCode) {
    appMessage.warning('请选择角色')
    return
  }

  saveLoading.value = true
  try {
    const isEditingCurrentUser = isEditingUser.value
    const userPayload = {
      username: userForm.username,
      real_name: userForm.realName,
      email: userForm.email,
      phone: userForm.phone,
      role: userForm.roleCode
    }
    if (userForm.password) {
      userPayload.password = userForm.password
    }

    if (isEditingCurrentUser) {
      await updateUser(editingUserRecord.value.userId, userPayload)
    } else {
      await createUser(userPayload)
    }

    appMessage.success(isEditingCurrentUser ? '用户更新成功' : '用户创建成功')
    closeUserDialog()
    await loadUsers()
  } catch (error) {
    console.error('保存用户失败:', error)
    appMessage.error('保存用户失败')
  } finally {
    saveLoading.value = false
  }
}

/**
 * 切换用户状态
 */
const toggleStatus = async (userRecord) => {
  try {
    if (userRecord.statusText === 'active') {
      await disableUser(userRecord.userId)
    } else {
      await enableUser(userRecord.userId)
    }
    userRecord.statusText = userRecord.statusText === 'active' ? 'disabled' : 'active'
    appMessage.success('状态已更新')
  } catch (error) {
    console.error('更新状态失败:', error)
    appMessage.error('更新状态失败')
  }
}

/**
 * 删除用户
 */
const deleteUser = async (userRecord) => {
  try {
    await appDialog.confirm('确定删除该用户吗？此操作不可恢复。', '删除确认', { type: 'warning' })
    await apiDeleteUser(userRecord.userId)
    appMessage.success('删除成功')
    await loadUsers()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除用户失败:', error)
      appMessage.error('删除用户失败')
    }
  }
}

onMounted(() => {
  void loadUsers()
})
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h2 {
  margin: 0;
  font-size: 20px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}
</style>
