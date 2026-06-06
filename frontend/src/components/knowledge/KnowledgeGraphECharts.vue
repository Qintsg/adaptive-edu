<template>
  <div class="knowledge-graph-container" ref="containerRef">
    <!-- Toolbar keeps filtering, search, zoom, and edit actions in one stable control band. -->
    <div class="graph-toolbar glass-panel">
      <template v-if="mode === 'edit'">
        <n-button-group>
          <n-button type="primary" size="small" @click="addNode">添加节点</n-button>
          <n-button type="warning" size="small" @click="saveGraph">保存图谱</n-button>
        </n-button-group>
        <div class="toolbar-divider"></div>
      </template>

      <n-select v-model:value="chapterFilter" placeholder="全部章节" clearable size="small" :options="chapterOptions"
        style="width: 150px" />
      <n-input v-model:value="searchText" placeholder="搜索知识点..." size="small" style="width: 180px" clearable />
      <n-button-group>
        <n-button size="small" title="放大" @click="zoomIn">+</n-button>
        <n-button size="small" title="缩小" @click="zoomOut">-</n-button>
        <n-button size="small" title="适配" @click="fitView">⊡</n-button>
      </n-button-group>
    </div>

    <!-- Legend swaps node meaning between learner view and graph editing view. -->
    <div class="graph-legend glass-panel">
      <template v-if="mode === 'view'">
        <span class="legend-item"><span class="legend-dot mastered"></span>已掌握</span>
        <span class="legend-item"><span class="legend-dot reinforce"></span>需巩固</span>
        <span class="legend-item"><span class="legend-dot weak"></span>薄弱</span>
        <span class="legend-item"><span class="legend-dot unknown"></span>未学习</span>
      </template>
      <template v-else>
        <span class="legend-item"><span class="legend-dot chapter"></span>章节节点</span>
      </template>
      <span class="legend-item"><span class="legend-line prerequisite"></span>先修关系</span>
      <span class="legend-item"><span class="legend-line related"></span>关联关系</span>
      <span class="legend-item"><span class="legend-line includes"></span>包含关系</span>
    </div>

    <!-- SVG stays inside a dedicated surface so resize and fit logic can read stable bounds. -->
    <div ref="graphSurfaceRef" class="graph-surface"
      :style="{ height: typeof height === 'number' ? `${height}px` : height }">
      <svg ref="svgRef" class="graph-svg"></svg>
    </div>

    <!-- Drawer shows either readonly detail or inline edit controls for the selected node. -->
    <n-drawer v-model:show="drawerVisible" width="30%" display-directive="if">
      <n-drawer-content :title="drawerTitle" closable>
        <div v-if="selectedNode" class="node-drawer">
        <!-- Base node fields are always shown so selection has a predictable detail layout. -->
        <n-form label-placement="top">
          <n-form-item label="名称">
            <n-input v-model:value="selectedNode.nodeName" :disabled="mode === 'view'" />
          </n-form-item>
          <n-form-item label="章节">
            <n-input v-model:value="selectedNode.chapterText" :disabled="mode === 'view'" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="selectedNode.nodeDescription" type="textarea" :autosize="{ minRows: 3 }"
              :disabled="mode === 'view'" />
          </n-form-item>
          <n-form-item v-if="mode === 'view' && selectedNode.masteryRate !== null" label="掌握度">
            <n-progress :percentage="Math.round((selectedNode.masteryRate || 0) * 100)"
              :color="getMasteryColor(selectedNode.masteryRate)" />
          </n-form-item>
        </n-form>

        <!-- Resource links are loaded lazily only for the active node in student view. -->
        <div v-if="nodeResources.length" class="resources-section">
          <h4>相关资源</h4>
          <div class="drawer-resource-list">
            <div v-for="resource in nodeResources" :key="resource.resourceId" class="drawer-resource-item">
              <span>{{ resource.resourceTitle }}</span>
              <a :href="resource.resourceUrl" target="_blank" rel="noopener noreferrer" class="resource-link">打开</a>
            </div>
          </div>
        </div>

        <div class="drawer-actions" v-if="mode === 'edit'">
          <n-button type="primary" @click="updateNodeData">更新节点</n-button>
          <n-button type="error" @click="deleteNode">删除节点</n-button>
        </div>
      </div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useKnowledgeGraphD3 } from './useKnowledgeGraphD3'

const props = defineProps({
  data: {
    type: Object,
    required: true,
    default: () => ({ nodes: [], edges: [] })
  },
  mode: {
    type: String,
    default: 'view'
  },
  height: {
    type: [Number, String],
    default: 600
  },
  courseId: {
    type: [Number, String],
    default: null
  },
  showDrawer: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['save', 'node-click', 'resource-link'])

const {
  addNode,
  chapterFilter,
  chapterList,
  containerRef,
  deleteNode,
  drawerTitle,
  drawerVisible,
  fitView,
  getMasteryColor,
  graphSurfaceRef,
  nodeResources,
  saveGraph,
  searchText,
  selectedNode,
  svgRef,
  updateNodeData,
  zoomIn,
  zoomOut
} = useKnowledgeGraphD3(props, emit)

const chapterOptions = computed(() => chapterList.value.map(chapter => ({
  label: chapter,
  value: chapter
})))
</script>

<style scoped src="./KnowledgeGraphECharts.css"></style>
