<template>
  <div class="question-list-view">
    <PageHero eyebrow="Content Bank" title="题库管理" description="围绕当前课程维护题目内容、知识点关联、难度与分值，为组卷和阶段测评提供稳定题源。">
      <template #actions>
        <n-upload :auto-upload="false" :show-file-list="false" accept=".xlsx,.xls,.csv" :on-change="handleImportFile">
          <n-button plain><n-icon>
              <Upload />
            </n-icon> 批量导入</n-button>
        </n-upload>
        <n-button type="primary" @click="openCreateDialog">
          <n-icon>
            <Plus />
          </n-icon> 添加题目
        </n-button>
      </template>
    </PageHero>

    <n-card shadow="hover">
      <div class="filter-bar">
        <n-select v-model="questionFilter.questionType" placeholder="题目类型" clearable style="width: 120px;"
          @change="handleQuestionSearch">
          <n-option v-for="typeOption in questionTypeOptions" :key="typeOption.optionValue"
            :label="typeOption.optionLabel" :value="typeOption.optionValue" />
        </n-select>
        <n-select v-model="questionFilter.pointId" placeholder="知识点" clearable style="width: 150px;"
          @change="handleQuestionSearch">
          <n-option v-for="knowledgePoint in knowledgePointOptions" :key="knowledgePoint.pointId"
            :label="knowledgePoint.pointName" :value="knowledgePoint.pointId" />
        </n-select>
        <n-input v-model="questionFilter.keyword" placeholder="搜索题目" clearable style="width: 200px;"
          @keyup.enter="handleQuestionSearch" />
        <n-button @click="handleQuestionSearch">搜索</n-button>
      </div>

      <n-table :data="questionRecords" v-loading="loading" style="width: 100%;">
        <n-table-column prop="contentText" label="题目内容" show-overflow-tooltip />
        <n-table-column prop="typeLabel" label="类型" width="100">
          <template #default="{ row }">
            <n-tag>{{ row.typeLabel }}</n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="difficultyLabel" label="难度" width="80">
          <template #default="{ row }">
            <n-tag :type="getDifficultyTagType(row.difficultyText)" size="small">
              {{ row.difficultyLabel }}
            </n-tag>
          </template>
        </n-table-column>
        <n-table-column prop="knowledgePointText" label="知识点" width="150" />
        <n-table-column prop="scoreValue" label="分值" width="70">
          <template #default="{ row }">
            {{ formatScoreText(row.scoreValue) }}
          </template>
        </n-table-column>
        <n-table-column label="操作" width="150">
          <template #default="{ row }">
            <n-button type="primary" link @click="editQuestion(row)">编辑</n-button>
            <n-button type="danger" link @click="deleteQuestion(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无题目，点击右上角添加" />
        </template>
      </n-table>

      <n-pagination class="pagination" layout="total, sizes, prev, pager, next" :total="totalQuestionCount"
        :page-sizes="[10, 20, 50]" v-model:current-page="pagination.page" v-model:page-size="pagination.pageSize"
        @size-change="handleQuestionPageSizeChange" @current-change="handleQuestionPageChange" />
    </n-card>

    <!-- 创建/编辑题目对话框 -->
    <n-dialog v-model="isQuestionDialogVisible" :title="editingQuestionRecord ? '编辑题目' : '添加题目'" width="600px">
      <n-form :model="questionForm" :rules="questionRules" ref="questionFormRef" label-width="100px">
        <n-form-item label="题目类型" prop="questionType">
          <n-select v-model="questionForm.questionType" placeholder="请选择类型" style="width: 100%;">
            <n-option v-for="typeOption in questionTypeOptions" :key="typeOption.optionValue"
              :label="typeOption.optionLabel" :value="typeOption.optionValue" />
          </n-select>
        </n-form-item>
        <n-form-item label="题目内容" prop="contentText">
          <n-input v-model="questionForm.contentText" type="textarea" :rows="3" placeholder="请输入题目内容" />
        </n-form-item>
        <n-form-item label="选项" v-if="supportsOptions(questionForm.questionType)">
          <div v-for="(optionText, optionIndex) in questionForm.optionTextList" :key="optionIndex" class="option-item">
            <div class="option-row">
              <span class="option-label">{{ getOptionLabel(optionIndex) }}</span>
              <n-input v-model="questionForm.optionTextList[optionIndex]"
                :placeholder="`选项${getOptionLabel(optionIndex)}`" />
              <n-button v-if="questionForm.optionTextList.length > 2" type="danger" link
                @click="removeOption(optionIndex)">删除</n-button>
            </div>
          </div>
          <n-button v-if="questionForm.optionTextList.length < 8" text type="primary" @click="addOption">+
            添加选项</n-button>
        </n-form-item>
        <n-form-item label="正确答案" prop="answerText">
          <n-input v-model="questionForm.answerText" placeholder="请输入正确答案（如A或AB）" />
        </n-form-item>
        <n-form-item label="解析">
          <n-input v-model="questionForm.analysisText" type="textarea" :rows="2" placeholder="题目解析" />
        </n-form-item>
        <n-form-item label="难度" required>
          <n-select v-model="questionForm.difficultyText" style="width: 100%;">
            <n-option v-for="difficultyOption in difficultyOptions" :key="difficultyOption.optionValue"
              :label="difficultyOption.optionLabel" :value="difficultyOption.optionValue" />
          </n-select>
        </n-form-item>
        <n-form-item label="分值">
          <n-input-number v-model="questionForm.scoreValue" :min="1" :max="100" :step="1" style="width: 100%;" />
        </n-form-item>
        <n-form-item label="关联知识点">
          <n-select v-model="questionForm.pointIdList" multiple placeholder="请选择知识点" style="width: 100%;">
            <n-option v-for="knowledgePoint in knowledgePointOptions" :key="knowledgePoint.pointId"
              :label="knowledgePoint.pointName" :value="knowledgePoint.pointId" />
          </n-select>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="closeCreateDialog">取消</n-button>
        <n-button type="primary" :loading="saveLoading" @click="saveQuestion">保存</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
import { Plus, Upload } from '@/theme/element-icons'
import PageHero from '@/components/common/PageHero.vue'
import { useTeacherQuestionList } from './useTeacherQuestionList'

const {
  addOption,
  closeCreateDialog,
  deleteQuestion,
  difficultyOptions,
  editQuestion,
  editingQuestionRecord,
  formatScoreText,
  getDifficultyTagType,
  getOptionLabel,
  handleImportFile,
  handleQuestionPageChange,
  handleQuestionPageSizeChange,
  handleQuestionSearch,
  isQuestionDialogVisible,
  knowledgePointOptions,
  loading,
  openCreateDialog,
  pagination,
  questionFilter,
  questionForm,
  questionFormRef,
  questionRecords,
  questionRules,
  questionTypeOptions,
  removeOption,
  saveLoading,
  saveQuestion,
  supportsOptions,
  totalQuestionCount
} = useTeacherQuestionList()
</script>

<style scoped src="./QuestionListView.css"></style>
