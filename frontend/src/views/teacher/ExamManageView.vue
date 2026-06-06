<template>
  <div class="exam-manage-view">
    <PageHero eyebrow="Assessment" title="作业管理" description="从当前课程题库快速组卷、发布到班级，并跟踪作业状态、题目结构与结果分析。">
      <template #actions>
        <n-button type="primary" @click="showCreateDialog = true">
          <n-icon>
            <Plus />
          </n-icon> 创建作业
        </n-button>
      </template>
    </PageHero>

    <n-card shadow="hover">
      <n-table :data="exams" v-loading="loading" style="width: 100%;">
        <n-table-column prop="title" label="作业名称" />
        <n-table-column prop="examTypeText" label="类型" width="120" />
        <n-table-column prop="totalScore" label="总分" width="100" />
        <n-table-column prop="durationMinutes" label="时长(分钟)" width="100" />
        <n-table-column prop="statusText" label="状态" width="100">
          <template #default="{ row }">
            <n-tag :type="row.statusTagType">{{ row.statusText }}</n-tag>
          </template>
        </n-table-column>
        <n-table-column label="操作" width="280">
          <template #default="{ row }">
            <n-button type="primary" link @click="viewExam(row)">查看</n-button>
            <n-button type="warning" link v-if="row.isDraft" @click="editExam(row)">编辑</n-button>
            <n-button type="success" link v-if="row.isDraft" @click="publishExam(row)">发布</n-button>
            <n-button type="warning" link v-if="row.isPublished" @click="unpublishExam(row)">取消发布</n-button>
            <n-button type="danger" link @click="deleteExam(row)">删除</n-button>
          </template>
        </n-table-column>
        <template #empty>
          <n-empty description="暂无作业，点击右上角创建" />
        </template>
      </n-table>

      <n-pagination class="pagination" layout="total, sizes, prev, pager, next" :total="examTotal"
        :page-sizes="[10, 20, 50]" v-model:current-page="pagination.page" v-model:page-size="pagination.pageSize"
        @size-change="loadExams" @current-change="loadExams" />
    </n-card>

    <!-- 创建作业对话框 -->
    <n-dialog v-model="showCreateDialog" :title="editingExam ? '编辑作业' : '创建作业'" width="500px">
      <n-form :model="createForm" :rules="examRules" ref="examFormRef" label-width="100px">
        <n-form-item label="作业名称" prop="title">
          <n-input v-model="createForm.title" placeholder="请输入作业名称" />
        </n-form-item>
        <n-form-item label="作业类型" prop="exam_type">
          <n-select v-model="createForm.exam_type" placeholder="请选择类型" style="width: 100%;">
            <n-option label="章节测试" value="chapter" />
            <n-option label="期中作业" value="midterm" />
            <n-option label="期末作业" value="final" />
          </n-select>
        </n-form-item>
        <n-form-item label="关联班级">
          <n-select v-model="createForm.target_class" placeholder="请选择班级" style="width: 100%;" clearable>
            <n-option v-for="cls in classes" :key="cls.id" :label="cls.name" :value="cls.id" />
          </n-select>
        </n-form-item>
        <n-form-item label="作答时长">
          <n-input-number v-model="createForm.duration" :min="10" :max="300" /> 分钟
        </n-form-item>
        <n-form-item label="总分">
          <n-input-number v-model="createForm.total_score" :min="1" :max="1000" />
        </n-form-item>
        <n-form-item label="及格分">
          <n-input-number v-model="createForm.pass_score" :min="0" :max="1000" />
        </n-form-item>
        <n-form-item label="选择题目" prop="questions">
          <n-input v-model="questionSearchKeyword" placeholder="按题干关键词筛选题目" clearable style="margin-bottom: 8px;" />
          <n-select v-model="createForm.questions" multiple filterable collapse-tags collapse-tags-tooltip
            placeholder="请选择题目" style="width: 100%;">
            <n-option v-for="questionItem in filteredQuestionList" :key="questionItem.id" :label="questionItem.content"
              :value="questionItem.id">
              <div class="question-option-row">
                <span>{{ questionItem.content }}</span>
                <n-tag size="small" :type="questionTagType(questionItem.type)">{{ questionTypeName(questionItem.type)
                }}</n-tag>
              </div>
            </n-option>
          </n-select>
          <div v-if="createForm.questions.length" class="question-selection-summary">
            <span>已选择 {{ createForm.questions.length }} 道题目</span>
            <n-button type="primary" link @click="createForm.questions = []">清空已选</n-button>
          </div>
          <div v-if="selectedQuestionPreview.length" class="question-preview-list">
            <div v-for="questionItem in selectedQuestionPreview" :key="questionItem.id" class="question-preview-item">
              <span>{{ questionItem.content }}</span>
              <n-tag size="small" :type="questionTagType(questionItem.type)">{{ questionTypeName(questionItem.type)
              }}</n-tag>
            </div>
          </div>
        </n-form-item>
        <n-form-item label="作业说明">
          <n-input v-model="createForm.description" type="textarea" placeholder="请输入作业说明" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="showCreateDialog = false">取消</n-button>
        <n-button type="primary" :loading="createLoading" @click="submitExam">{{ editingExam ? '保存' : '创建'
        }}</n-button>
      </template>
    </n-dialog>

    <!-- 作业详情对话框 -->
    <n-dialog v-model="showDetailDialog" title="作业详情" width="720px">
      <div v-loading="detailLoading">
        <n-descriptions :column="2" border>
          <n-descriptions-item label="作业名称">{{ examDetail.title }}</n-descriptions-item>
          <n-descriptions-item label="作业类型">
            <n-tag size="small">{{ examDetail.examTypeText }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="总分">{{ examDetail.totalScore }}</n-descriptions-item>
          <n-descriptions-item label="及格分">{{ examDetail.passScore }}</n-descriptions-item>
          <n-descriptions-item label="作答时长">{{ examDetail.durationMinutes }} 分钟</n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="examDetail.statusTagType">{{ examDetail.statusText }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="题目数量">{{ examDetail.questionCount }}</n-descriptions-item>
          <n-descriptions-item label="创建时间">{{ examDetail.createdAtText }}</n-descriptions-item>
        </n-descriptions>
        <div v-if="examDetail.description" style="margin-top: 16px;">
          <strong>作业说明：</strong>
          <p style="color: #606266;">{{ examDetail.description }}</p>
        </div>

        <!-- 题目列表预览 -->
        <div v-if="(examDetail.questions || []).length" style="margin-top: 20px;">
          <h4 style="margin-bottom: 12px; font-size: 15px;">题目列表</h4>
          <n-table :data="examDetail.questions" border size="small" max-height="360">
            <n-table-column type="index" label="#" width="50" />
            <n-table-column label="题目内容" min-width="240">
              <template #default="{ row }">
                <span>{{ row.contentPreview }}</span>
              </template>
            </n-table-column>
            <n-table-column label="题型" width="80" align="center">
              <template #default="{ row }">
                <n-tag size="small" :type="row.typeTag">{{ row.typeText }}</n-tag>
              </template>
            </n-table-column>
            <n-table-column prop="score" label="分值" width="70" align="center" />
          </n-table>
        </div>
      </div>
      <template #footer>
        <n-button @click="showDetailDialog = false">关闭</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
import { Plus } from '@/theme/element-icons'
import PageHero from '@/components/common/PageHero.vue'
import { useTeacherExamManage } from './useTeacherExamManage'

const {
  classes,
  createForm,
  createLoading,
  deleteExam,
  detailLoading,
  editExam,
  editingExam,
  examDetail,
  examFormRef,
  examRules,
  examTotal,
  exams,
  filteredQuestionList,
  loadExams,
  loading,
  pagination,
  publishExam,
  questionSearchKeyword,
  questionTagType,
  questionTypeName,
  selectedQuestionPreview,
  showCreateDialog,
  showDetailDialog,
  submitExam,
  unpublishExam,
  viewExam
} = useTeacherExamManage()
</script>

<style scoped src="./ExamManageView.css"></style>
