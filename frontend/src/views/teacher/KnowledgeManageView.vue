<template>
  <div class="knowledge-manage-view">
    <n-card class="page-header" shadow="never">
      <div class="header-content">
        <h2>知识图谱管理</h2>
        <div class="header-actions">
          <n-button-group>
            <n-button :type="showGraph ? 'primary' : ''" @click="showGraph = true">
              <n-icon>
                <Connection />
              </n-icon> 图谱模式
            </n-button>
            <n-button :type="!showGraph ? 'primary' : ''" @click="showGraph = false">
              <n-icon>
                <List />
              </n-icon> 列表模式
            </n-button>
          </n-button-group>
          <n-button type="primary" @click="addPoint">
            <n-icon>
              <Plus />
            </n-icon> 添加知识点
          </n-button>
          <n-button :loading="indexBuilding" @click="buildRagIndex">构建 GraphRAG 索引</n-button>
          <n-button @click="loadAll">刷新</n-button>
        </div>
      </div>
    </n-card>

    <n-row :gutter="16" class="stats-row">
      <n-col :xs="12" :md="6">
        <n-card shadow="hover">
          <div class="stat-item">
            <div class="label">知识点总数</div>
            <div class="value">{{ stats.totalPoints }}</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="12" :md="6">
        <n-card shadow="hover">
          <div class="stat-item">
            <div class="label">关系总数</div>
            <div class="value">{{ stats.totalRelations }}</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="12" :md="6">
        <n-card shadow="hover">
          <div class="stat-item">
            <div class="label">章节数</div>
            <div class="value">{{ stats.totalChapters }}</div>
          </div>
        </n-card>
      </n-col>
      <n-col :xs="12" :md="6">
        <n-card shadow="hover">
          <div class="stat-item">
            <div class="label">孤立点</div>
            <div class="value">{{ stats.isolatedPoints }}</div>
          </div>
        </n-card>
      </n-col>
    </n-row>

    <!-- 图谱展示区域 -->
    <n-card v-if="showGraph" class="graph-card" shadow="hover" style="margin-bottom: 20px;">
      <template #header>
        <div class="card-title">知识图谱可视化编辑</div>
      </template>
      <div class="graph-container" style="min-height: 600px; height: calc(100vh - 300px);">
        <KnowledgeGraphECharts v-if="knowledgePoints.length" :data="graphData" mode="edit" :height="'100%'"
          @save="handleGraphSave" @node-click="handleNodeClick" />
        <n-empty v-else description="暂无知识图谱数据" />
      </div>
    </n-card>

    <n-row :gutter="16" v-show="!showGraph">
      <n-col :xs="24" :lg="12">
        <n-card shadow="hover" body-style="padding: 12px 16px">
          <template #header>
            <div class="card-title">按章节展示（完整）</div>
          </template>
          <n-tree v-loading="loading" :data="knowledgeTree" :props="{ label: 'labelText', children: 'children' }"
            node-key="treeId" default-expand-all>
            <template #default="{ node, data }">
              <div class="tree-node">
                <span>{{ node.label }}</span>
                <span v-if="data.treeNodeType === 'point'" class="node-actions">
                  <n-button type="primary" link size="small" @click.stop="editPoint(data)">编辑</n-button>
                  <n-button type="danger" link size="small" @click.stop="deletePoint(data)">删除</n-button>
                </span>
              </div>
            </template>
          </n-tree>
        </n-card>
      </n-col>

      <n-col :xs="24" :lg="12">
        <n-card shadow="hover" body-style="padding: 12px 16px">
          <template #header>
            <div class="card-title">关系明细（完整）</div>
          </template>
          <n-input v-model="relationKeyword" clearable placeholder="筛选关系（知识点名）" style="margin-bottom: 12px" />
          <n-table v-loading="loading" :data="filteredRelations" size="small" stripe max-height="520">
            <n-table-column prop="fromPointName" label="前置知识点" min-width="150" show-overflow-tooltip />
            <n-table-column prop="relationTypeText" label="关系" width="110" />
            <n-table-column prop="toPointName" label="后续知识点" min-width="150" show-overflow-tooltip />
          </n-table>
        </n-card>
      </n-col>
    </n-row>

    <!-- 添加/编辑知识点对话框 -->
    <n-dialog v-model="pointDialogVisible" :title="editingPoint ? '编辑知识点' : '添加知识点'" width="500px">
      <n-form :model="pointForm" label-width="80px" ref="pointFormRef" :rules="pointRules">
        <n-form-item label="知识点名" prop="pointName">
          <n-input v-model="pointForm.pointName" placeholder="请输入知识点名称" />
        </n-form-item>
        <n-form-item label="所属章节" prop="chapterText">
          <n-select v-model="pointForm.chapterText" filterable allow-create clearable placeholder="选择或输入章节"
            style="width: 100%;">
            <n-option v-for="c in existingChapters" :key="c" :label="c" :value="c" />
          </n-select>
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model="pointForm.descriptionText" type="textarea" :rows="3" placeholder="知识点描述（可选）" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="pointDialogVisible = false">取消</n-button>
        <n-button type="primary" @click="submitPointForm" :loading="submitting">确定</n-button>
      </template>
    </n-dialog>
  </div>
</template>

<script setup>
import { Plus, Connection, List } from '@/theme/element-icons'
import KnowledgeGraphECharts from '@/components/knowledge/KnowledgeGraphECharts.vue'
import { useTeacherKnowledgeManage } from './useTeacherKnowledgeManage'

const {
  addPoint,
  buildRagIndex,
  deletePoint,
  editPoint,
  editingPoint,
  existingChapters,
  filteredRelations,
  graphData,
  handleGraphSave,
  handleNodeClick,
  indexBuilding,
  knowledgePoints,
  knowledgeTree,
  loadAll,
  loading,
  pointDialogVisible,
  pointForm,
  pointFormRef,
  pointRules,
  relationKeyword,
  showGraph,
  stats,
  submitting,
  submitPointForm
} = useTeacherKnowledgeManage()
</script>

<style scoped src="./KnowledgeManageView.css"></style>
