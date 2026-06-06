<template>
  <div class="resource-manage">
    <PageHero eyebrow="Resource Library" title="资源库管理" description="维护课程视频、文档与外部链接资源，并将资源精确挂接到知识点和课程上下文中。">
      <template #actions>
        <n-button type="primary" @click="showCreateDialog">
          <n-icon>
            <Plus />
          </n-icon> 新增资源
        </n-button>
        <n-button @click="showImportDialog">
          <n-icon>
            <Upload />
          </n-icon> 批量导入
        </n-button>
      </template>
    </PageHero>

    <!-- 搜索筛选 -->
    <n-card class="filter-card">
      <n-form :inline="true" :model="resourceSearchForm">
        <n-form-item label="资源名称">
          <n-input v-model="resourceSearchForm.titleKeyword" placeholder="搜索资源名称" clearable class="filter-input" />
        </n-form-item>
        <n-form-item label="资源类型">
          <n-select v-model="resourceSearchForm.resourceType" placeholder="全部" clearable class="filter-select">
            <n-option v-for="resourceTypeOption in resourceTypeOptions" :key="resourceTypeOption.optionValue"
              :label="resourceTypeOption.optionLabel" :value="resourceTypeOption.optionValue" />
          </n-select>
        </n-form-item>
        <n-form-item label="关联知识点">
          <n-select v-model="resourceSearchForm.pointId" placeholder="全部" clearable class="filter-select">
            <n-option v-for="knowledgePoint in knowledgePointOptions" :key="knowledgePoint.pointId"
              :label="knowledgePoint.pointName" :value="knowledgePoint.pointId" />
          </n-select>
        </n-form-item>
        <n-form-item>
          <n-button type="primary" @click="handleSearch">搜索</n-button>
          <n-button @click="resetSearch">重置</n-button>
        </n-form-item>
      </n-form>
    </n-card>

    <!-- 资源列表 -->
    <n-card class="list-card">
      <n-table :data="resourceRecords" v-loading="loading" stripe>
        <n-table-column prop="titleText" label="资源名称" min-width="200" />
        <n-table-column prop="typeLabel" label="类型" width="100">
          <template #default="{ row }">
            <n-tag :type="row.typeTagType">{{ row.typeLabel }}</n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="pointNameText" label="关联知识点" width="150" />
        <n-table-column prop="createdAtText" label="上传时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.createdAtText) }}
          </template>
        </n-table-column>
        <n-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <n-button type="primary" link @click="editResource(row)">编辑</n-button>
            <n-button type="primary" link @click="previewResource(row)">预览</n-button>
            <n-button type="danger" link @click="deleteResource(row)">删除</n-button>
          </template>
        </n-table-column>
      </n-table>

      <n-pagination v-model:current-page="pagination.page" v-model:page-size="pagination.pageSize"
        :total="totalResourceCount" layout="total, sizes, prev, pager, next" @size-change="handleResourcePageSizeChange"
        @current-change="handleResourcePageChange" />
    </n-card>

    <!-- 新增/编辑对话框 -->
    <n-dialog v-model="isResourceDialogVisible" :title="isEditingResource ? '编辑资源' : '新增资源'" width="500px">
      <n-form ref="formRef" :model="resourceForm" :rules="formRules" label-width="100px">
        <n-form-item label="资源名称" prop="titleText">
          <n-input v-model="resourceForm.titleText" placeholder="请输入资源名称" />
        </n-form-item>
        <n-form-item label="资源类型" prop="resourceType">
          <n-select v-model="resourceForm.resourceType" placeholder="请选择类型" style="width: 100%">
            <n-option v-for="resourceTypeOption in resourceTypeOptions" :key="resourceTypeOption.optionValue"
              :label="resourceTypeOption.optionLabel" :value="resourceTypeOption.optionValue" />
          </n-select>
        </n-form-item>
        <n-form-item label="关联知识点" prop="pointId">
          <n-select v-model="resourceForm.pointId" placeholder="请选择知识点" style="width: 100%">
            <n-option v-for="knowledgePoint in knowledgePointOptions" :key="knowledgePoint.pointId"
              :label="knowledgePoint.pointName" :value="knowledgePoint.pointId" />
          </n-select>
        </n-form-item>
        <n-form-item v-if="resourceForm.resourceType === 'link'" label="链接地址" prop="linkUrl">
          <n-input v-model="resourceForm.linkUrl" placeholder="请输入链接地址" />
        </n-form-item>
        <n-form-item v-else label="上传文件" prop="fileObject">
          <n-upload :auto-upload="false" :on-change="handleFileChange" :before-upload="beforeFileUpload" :limit="1"
            :file-list="fileList" :accept="getAcceptTypes(resourceForm.resourceType)">
            <n-button type="primary">选择文件</n-button>
            <template #tip>
              <div class="el-upload__tip">
                {{ getUploadTipText(resourceForm.resourceType) }}
              </div>
            </template>
          </n-upload>
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model="resourceForm.descriptionText" type="textarea" :rows="3" placeholder="请输入资源描述" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="isResourceDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitForm" :loading="submitting">确定</n-button>
      </template>
    </n-dialog>

    <!-- 批量导入对话框 -->
    <n-dialog v-model="importDialogVisible" title="批量导入资源" width="400px">
      <n-upload drag :auto-upload="false" :on-change="handleImportFile" :limit="1" accept=".xlsx,.xls,.csv">
        <n-icon class="el-icon--upload">
          <Upload />
        </n-icon>
        <div class="el-upload__text">拖拽文件到此处，或 <em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 xlsx, xls, csv 格式</div>
        </template>
      </n-upload>
      <template #footer>
        <n-button @click="importDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitImport" :loading="importing">导入</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
import { Plus, Upload } from '@/theme/element-icons'
import PageHero from '@/components/common/PageHero.vue'
import { useTeacherResourceManage } from './useTeacherResourceManage'

const {
  beforeFileUpload,
  deleteResource,
  editResource,
  fileList,
  formRef,
  formRules,
  formatTime,
  getAcceptTypes,
  getUploadTipText,
  handleFileChange,
  handleImportFile,
  handleResourcePageChange,
  handleResourcePageSizeChange,
  handleSearch,
  importDialogVisible,
  importing,
  isEditingResource,
  isResourceDialogVisible,
  knowledgePointOptions,
  loading,
  pagination,
  previewResource,
  resetSearch,
  resourceForm,
  resourceRecords,
  resourceSearchForm,
  resourceTypeOptions,
  showCreateDialog,
  showImportDialog,
  submitForm,
  submitImport,
  submitting,
  totalResourceCount
} = useTeacherResourceManage()
</script>

<style scoped src="./ResourceManage.css"></style>
