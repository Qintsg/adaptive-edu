<template>
    <div class="course-detail-view">
        <n-card class="course-header" shadow="never">
            <div class="header-row">
                <div class="header-info">
                    <n-button text :icon="ArrowLeft" @click="$router.push('/teacher/courses')">返回课程列表</n-button>
                    <h2>{{ courseInfo.name || '课程详情' }}</h2>
                    <n-tag v-if="courseInfo.isPublic" type="success">已发布</n-tag>
                    <n-tag v-else type="info">草稿</n-tag>
                </div>
                <div class="header-actions">
                    <n-button type="primary" @click="editCourse">编辑课程</n-button>
                </div>
            </div>
            <p class="course-desc" v-if="courseInfo.description">{{ courseInfo.description }}</p>
        </n-card>

        <n-row :gutter="16" class="stat-row">
            <n-col :xs="12" :sm="6">
                <n-card shadow="hover" class="stat-card">
                    <n-statistic title="班级数" :value="stats.classCount" />
                </n-card>
            </n-col>
            <n-col :xs="12" :sm="6">
                <n-card shadow="hover" class="stat-card">
                    <n-statistic title="知识点" :value="stats.knowledgeCount" />
                </n-card>
            </n-col>
            <n-col :xs="12" :sm="6">
                <n-card shadow="hover" class="stat-card">
                    <n-statistic title="题目数" :value="stats.questionCount" />
                </n-card>
            </n-col>
            <n-col :xs="12" :sm="6">
                <n-card shadow="hover" class="stat-card">
                    <n-statistic title="作业数" :value="stats.examCount" />
                </n-card>
            </n-col>
        </n-row>

        <n-card shadow="hover">
            <n-tabs v-model="activeTab" type="border-card">
                <n-tab-pane label="班级管理" name="classes">
                    <div class="tab-toolbar">
                        <n-button type="primary" size="small" @click="showCreateClassDialog = true">
                            <n-icon>
                                <Plus />
                            </n-icon> 创建班级
                        </n-button>
                    </div>
                    <n-table :data="classes" v-loading="classLoading" style="width: 100%">
                        <n-table-column prop="name" label="班级名称" />
                        <n-table-column prop="studentCount" label="学生数" width="100" />
                        <n-table-column prop="semester" label="学期" width="120" />
                        <n-table-column label="操作" width="200">
                            <template #default="{ row }">
                                <n-button type="primary" link @click="viewClass(row)">查看详情</n-button>
                                <n-button type="danger" link @click="deleteClass(row)">删除</n-button>
                            </template>
                        </n-table-column>
                        <template #empty>
                            <n-empty description="暂无班级" :image-size="60" />
                        </template>
                    </n-table>
                </n-tab-pane>

                <n-tab-pane label="知识图谱" name="knowledge">
                    <div class="tab-toolbar">
                        <n-button-group>
                            <n-button :type="knowledgeViewMode === 'graph' ? 'primary' : ''" size="small"
                                @click="knowledgeViewMode = 'graph'">图谱视图</n-button>
                            <n-button :type="knowledgeViewMode === 'list' ? 'primary' : ''" size="small"
                                @click="knowledgeViewMode = 'list'">列表视图</n-button>
                        </n-button-group>
                    </div>
                    <div v-if="knowledgeViewMode === 'graph'" class="graph-container" style="height: 500px;">
                        <KnowledgeGraphECharts v-if="knowledgePoints.length" :data="graphData" mode="edit" :height="500"
                            :courseId="courseId" @save="handleSaveGraph" />
                        <n-empty v-else description="暂无知识图谱数据" />
                    </div>
                    <div v-else>
                        <n-table :data="knowledgePoints" v-loading="knowledgeLoading">
                            <n-table-column prop="name" label="知识点名称" />
                            <n-table-column prop="chapter" label="章节" width="150" />
                            <n-table-column prop="difficulty" label="难度" width="80" />
                            <n-table-column prop="description" label="描述" show-overflow-tooltip />
                        </n-table>
                    </div>
                </n-tab-pane>

                <n-tab-pane label="题库管理" name="questions">
                    <div class="tab-toolbar">
                        <n-select v-model="questionFilter.type" placeholder="题目类型" clearable size="small"
                            style="width: 120px;" @change="loadQuestions">
                            <n-option label="单选题" value="single_choice" />
                            <n-option label="多选题" value="multiple_choice" />
                            <n-option label="判断题" value="true_false" />
                            <n-option label="填空题" value="fill_blank" />
                        </n-select>
                        <n-input v-model="questionFilter.keyword" placeholder="搜索题目" clearable size="small"
                            style="width: 200px;" @keyup.enter="loadQuestions" />
                        <n-button size="small" @click="loadQuestions">搜索</n-button>
                        <n-button type="primary" size="small"
                            @click="$router.push(`/teacher/courses/${courseId}/workspace/questions`)">前往完整题库</n-button>
                    </div>
                    <n-table :data="questions" v-loading="questionLoading">
                        <n-table-column type="index" label="序号" width="60" />
                        <n-table-column label="题目内容" show-overflow-tooltip>
                            <template #default="{ row }">
                                {{ stripHtml(row.content) }}
                            </template>
                        </n-table-column>
                        <n-table-column prop="typeName" label="类型" width="100" />
                        <n-table-column prop="difficultyText" label="难度" width="80" />
                        <n-table-column prop="knowledgePointName" label="知识点" width="150" />
                        <template #empty>
                            <n-empty description="暂无题目" :image-size="60" />
                        </template>
                    </n-table>
                    <n-pagination v-if="questionTotal > 0" class="pagination" layout="total, prev, pager, next"
                        :total="questionTotal" :page-size="10" v-model:current-page="questionFilter.page"
                        @current-change="loadQuestions" />
                </n-tab-pane>

                <n-tab-pane label="作业管理" name="exams">
                    <div class="tab-toolbar">
                        <n-button type="primary" size="small"
                            @click="$router.push('/teacher/exams')">前往完整作业管理</n-button>
                    </div>
                    <n-table :data="exams" v-loading="examLoading">
                        <n-table-column prop="title" label="作业名称" />
                        <n-table-column prop="examType" label="类型" width="120" />
                        <n-table-column prop="totalScore" label="总分" width="80" />
                        <n-table-column prop="statusText" label="状态" width="100">
                            <template #default="{ row }">
                                <n-tag :type="row.statusTagType" size="small">
                                    {{ row.statusText }}
                                </n-tag>
                            </template>
                        </n-table-column>
                        <n-table-column label="操作" width="150">
                            <template #default="{ row }">
                                <n-button type="primary" link size="small"
                                    @click="$router.push('/teacher/exams')">管理</n-button>
                            </template>
                        </n-table-column>
                        <template #empty>
                            <n-empty description="暂无作业" :image-size="60" />
                        </template>
                    </n-table>
                </n-tab-pane>
            </n-tabs>
        </n-card>

        <n-dialog v-model="showCreateClassDialog" title="创建班级" width="400px">
            <n-form :model="classForm" label-width="80px">
                <n-form-item label="班级名称" required>
                    <n-input v-model="classForm.name" placeholder="请输入班级名称" />
                </n-form-item>
                <n-form-item label="学期">
                    <n-input v-model="classForm.semester" placeholder="如：2025-2026第一学期" />
                </n-form-item>
            </n-form>
            <template #footer>
                <n-button @click="showCreateClassDialog = false">取消</n-button>
                <n-button type="primary" @click="createClass">确定</n-button>
            </template>
        </n-dialog>
    </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { appMessage, appDialog } from '@/utils/feedback'
import { Plus, ArrowLeft } from '@/theme/element-icons'
import { getCourseDetail } from '@/api/teacher/course'
import { getMyClasses, createClass as apiCreateClass, deleteClass as apiDeleteClass } from '@/api/teacher/class'
import { getKnowledgePoints, getKnowledgeRelations } from '@/api/teacher/knowledge'
import { getQuestions } from '@/api/teacher/question'
import { getExams } from '@/api/teacher/exam'
import KnowledgeGraphECharts from '@/components/knowledge/KnowledgeGraphECharts.vue'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => route.params['courseId'])

const normalizeText = (value) => {
    if (value === null || value === undefined) return ''
    return String(value).trim()
}

const normalizeIdentifier = (value) => {
    const normalized = normalizeText(value)
    return normalized || ''
}

const normalizeNumber = (value, fallback = 0) => {
    const parsedValue = Number(value)
    return Number.isFinite(parsedValue) ? parsedValue : fallback
}

const stripHtml = (text) => {
    if (!text) return ''
    return text.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').trim()
}

const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    const parsedDate = new Date(dateStr)
    return Number.isNaN(parsedDate.getTime()) ? '-' : parsedDate.toLocaleString('zh-CN')
}

const normalizeCourseInfo = (value) => {
    const course = value && typeof value === 'object' ? value : {}
    return {
        id: course?.['course_id'] ?? course?.['id'] ?? courseId.value,
        name: normalizeText(course?.['course_name'] ?? course?.['name']) || '课程详情',
        description: normalizeText(course?.['course_description'] ?? course?.['description']),
        isPublic: Boolean(course?.['is_public'])
    }
}

const normalizeClassSummary = (value, index) => {
    const classItem = value && typeof value === 'object' ? value : {}
    return {
        id: classItem?.['class_id'] ?? classItem?.['id'] ?? index,
        name: normalizeText(classItem?.['name'] ?? classItem?.['class_name']) || '未命名班级',
        course: normalizeText(classItem?.['course_name']) || '未关联课程',
        studentCount: normalizeNumber(classItem?.['student_count'] ?? classItem?.['studentCount']),
        semester: normalizeText(classItem?.['semester']) || '-',
        teacherName: normalizeText(classItem?.['teacher_name']) || '-',
        createdAt: formatDate(classItem?.['created_at'])
    }
}

const normalizeKnowledgePoint = (value, index) => {
    const point = value && typeof value === 'object' ? value : {}
    return {
        id: point?.['id'] ?? point?.['point_id'] ?? index,
        name: normalizeText(point?.['name'] ?? point?.['point_name']) || `知识点 ${index + 1}`,
        chapter: normalizeText(point?.['chapter_number'] ?? point?.['chapter']) || '-',
        difficulty: normalizeText(point?.['difficulty_display'] ?? point?.['difficulty']) || '-',
        description: normalizeText(point?.['description']) || '-'
    }
}

const normalizeKnowledgeRelation = (value, index) => {
    const relation = value && typeof value === 'object' ? value : {}
    return {
        id: relation?.['id'] ?? relation?.['relation_id'] ?? index,
        sourceKey: normalizeIdentifier(relation?.['source_id'] ?? relation?.['source'] ?? relation?.['pre_point_id'] ?? relation?.['pre_point']),
        sourceName: normalizeText(relation?.['source'] ?? relation?.['pre_point']),
        targetKey: normalizeIdentifier(relation?.['target_id'] ?? relation?.['target'] ?? relation?.['post_point_id'] ?? relation?.['post_point']),
        targetName: normalizeText(relation?.['target'] ?? relation?.['post_point']),
        relationType: normalizeText(relation?.['relation_type']) || 'prerequisite'
    }
}

const normalizeQuestionSummary = (value, index) => {
    const question = value && typeof value === 'object' ? value : {}
    return {
        id: question?.['question_id'] ?? question?.['id'] ?? index,
        content: normalizeText(question?.['content']) || `题目 ${index + 1}`,
        typeName: normalizeText(question?.['type_name'] ?? question?.['question_type_display'] ?? question?.['question_type'] ?? question?.['type']) || '-',
        difficultyText: normalizeText(question?.['difficulty_display'] ?? question?.['difficulty']) || '-',
        knowledgePointName: normalizeText(question?.['knowledge_point_name']) || '-'
    }
}

const mapExamStatus = (value) => {
    if (value === 'published') return { text: '已发布', tagType: 'success' }
    if (value === 'ended') return { text: '已结束', tagType: 'info' }
    return { text: '草稿', tagType: 'info' }
}

const normalizeExamSummary = (value, index) => {
    const exam = value && typeof value === 'object' ? value : {}
    const status = normalizeText(exam?.['status']) || 'draft'
    const statusDisplay = mapExamStatus(status)
    return {
        id: exam?.['exam_id'] ?? exam?.['id'] ?? index,
        title: normalizeText(exam?.['title'] ?? exam?.['exam_name'] ?? exam?.['name']) || `作业 ${index + 1}`,
        examType: normalizeText(exam?.['exam_type_display'] ?? exam?.['exam_type'] ?? exam?.['type']) || '-',
        totalScore: normalizeNumber(exam?.['total_score']),
        status,
        statusText: statusDisplay.text,
        statusTagType: statusDisplay.tagType
    }
}

const normalizeListFromPayload = (value, key, mapper) => {
    const payload = value && typeof value === 'object' ? value : {}
    const items = Array.isArray(payload?.[key])
        ? payload[key]
        : Array.isArray(value)
            ? value
            : []
    return items.map((item, index) => mapper(item, index))
}

const normalizePaginatedList = (value, key, mapper) => {
    const items = normalizeListFromPayload(value, key, mapper)
    const payload = value && typeof value === 'object' ? value : {}
    return {
        items,
        total: normalizeNumber(payload?.['total'], items.length)
    }
}

const activeTab = ref('classes')
const courseInfo = ref(normalizeCourseInfo(null))

const stats = reactive({ classCount: 0, knowledgeCount: 0, questionCount: 0, examCount: 0 })

const classes = ref([])
const classLoading = ref(false)
const showCreateClassDialog = ref(false)
const classForm = reactive({ name: '', semester: '' })

const knowledgePoints = ref([])
const knowledgeRelations = ref([])
const knowledgeLoading = ref(false)
const knowledgeViewMode = ref('graph')

const questions = ref([])
const questionLoading = ref(false)
const questionTotal = ref(0)
const questionFilter = reactive({ type: '', keyword: '', page: 1 })

const exams = ref([])
const examLoading = ref(false)

const graphData = computed(() => {
    const pointIdMap = new Map()
    const nodes = knowledgePoints.value.map((point) => {
        const normalizedId = String(point.id)
        pointIdMap.set(normalizedId, normalizedId)
        if (point.name) pointIdMap.set(point.name, normalizedId)
        return {
            id: normalizedId,
            name: point.name,
            chapter: point.chapter,
            description: point.description
        }
    })
    const edges = knowledgeRelations.value
        .map((relation) => {
            const source = pointIdMap.get(relation.sourceKey) || pointIdMap.get(relation.sourceName) || relation.sourceKey || relation.sourceName
            const target = pointIdMap.get(relation.targetKey) || pointIdMap.get(relation.targetName) || relation.targetKey || relation.targetName
            if (!source || !target) return null
            return {
                source: String(source),
                target: String(target),
                relation_type: relation.relationType
            }
        })
        .filter(Boolean)
    return { nodes, edges }
})

const loadCourseDetail = async () => {
    try {
        courseInfo.value = normalizeCourseInfo(await getCourseDetail(courseId.value))
    } catch (e) {
        console.error('获取课程详情失败:', e)
    }
}

const loadClasses = async () => {
    classLoading.value = true
    try {
        const classList = normalizePaginatedList(
            await getMyClasses({ course_id: courseId.value }),
            'classes',
            (classItem, index) => normalizeClassSummary(classItem, index)
        )
        classes.value = classList.items
        stats.classCount = classList.total
    } catch (e) {
        console.error('获取班级列表失败:', e)
    } finally {
        classLoading.value = false
    }
}

const loadKnowledge = async () => {
    knowledgeLoading.value = true
    try {
        const [pointsRes, relationsRes] = await Promise.all([
            getKnowledgePoints(courseId.value),
            getKnowledgeRelations(courseId.value)
        ])
        knowledgePoints.value = normalizeListFromPayload(pointsRes, 'points', (point, index) => normalizeKnowledgePoint(point, index))
        knowledgeRelations.value = normalizeListFromPayload(relationsRes, 'relations', (relation, index) => normalizeKnowledgeRelation(relation, index))
        stats.knowledgeCount = knowledgePoints.value.length
    } catch (e) {
        console.error('获取知识点失败:', e)
    } finally {
        knowledgeLoading.value = false
    }
}

const loadQuestions = async () => {
    questionLoading.value = true
    try {
        const params = { course_id: courseId.value, page: questionFilter.page, page_size: 10 }
        if (questionFilter.type) {
            params.question_type = questionFilter.type
            params.type = questionFilter.type
        }
        const keyword = normalizeText(questionFilter.keyword)
        if (keyword) params.keyword = keyword
        const questionList = normalizePaginatedList(
            await getQuestions(params),
            'questions',
            (question, index) => normalizeQuestionSummary(question, index)
        )
        questions.value = questionList.items
        questionTotal.value = questionList.total
        stats.questionCount = questionTotal.value
    } catch (e) {
        console.error('获取题目失败:', e)
    } finally {
        questionLoading.value = false
    }
}

const loadExams = async () => {
    examLoading.value = true
    try {
        exams.value = normalizeListFromPayload(await getExams(courseId.value), 'exams', (exam, index) => normalizeExamSummary(exam, index))
        stats.examCount = exams.value.length
    } catch (e) {
        console.error('获取作业列表失败:', e)
    } finally {
        examLoading.value = false
    }
}

const editCourse = () => {
    router.push(`/teacher/courses/${courseId.value}/edit`)
}

const viewClass = (cls) => {
    router.push(`/teacher/classes/${cls.id}`)
}

const createClass = async () => {
    const className = normalizeText(classForm.name)
    if (!className) {
        appMessage.warning('请输入班级名称')
        return
    }
    try {
        await apiCreateClass({
            class_name: className,
            semester: normalizeText(classForm.semester),
            course_id: courseId.value
        })
        appMessage.success('班级创建成功')
        showCreateClassDialog.value = false
        classForm.name = ''
        classForm.semester = ''
        await loadClasses()
    } catch (e) {
        console.error('创建班级失败:', e)
        appMessage.error('创建班级失败')
    }
}

const deleteClass = async (cls) => {
    try {
        await appDialog.confirm(`确定删除班级"${cls.name}"吗？`, '删除确认', { type: 'warning' })
        await apiDeleteClass(cls.id)
        appMessage.success('删除成功')
        await loadClasses()
    } catch (e) {
        if (e !== 'cancel') appMessage.error('删除失败')
    }
}

const handleSaveGraph = () => {
    appMessage.success('图谱数据已保存')
}

onMounted(() => {
    loadCourseDetail()
    loadClasses()
    loadKnowledge()
    loadQuestions()
    loadExams()
})
</script>

<style scoped src="./CourseDetailView.css"></style>
