/**
 * 学生端 A3 个性化智能体 API。
 */
import request from '../index'

export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'warning'

export type AgentResourceType = 'explanation' | 'mindmap' | 'quiz' | 'reading' | 'coding_case' | 'video_script'

export interface AgentTraceItem {
  agent: string
  status: AgentStatus
  summary: string
  duration_ms?: number
  detail?: Record<string, unknown>
  error?: string
}

export interface AgentProgressEvent {
  stage: string
  status: AgentStatus
  percent: number
  message: string
}

export interface GeneratedLearningResource {
  resource_id: number
  resource_type: AgentResourceType
  title: string
  content: string
  content_payload?: Record<string, unknown>
  evidence: Array<Record<string, unknown>>
  profile_snapshot: Record<string, unknown>
  metadata: Record<string, unknown>
  knowledge_point_id?: number | null
  knowledge_point_name?: string
  status: string
  created_at?: string | null
}

export interface AgentQualityReport {
  status: AgentStatus
  score: number
  resource_count: number
  required_types: AgentResourceType[]
  missing_types: AgentResourceType[]
  warnings: string[]
  errors: string[]
  resources: Array<Record<string, unknown>>
}

export interface AgentPathBindingSuggestion {
  resource_id: number
  resource_type: AgentResourceType
  title: string
  suggested_node_id?: number | null
  suggested_node_title?: string
  reason: string
}

export interface AgentPathSuggestion {
  path_id?: number | null
  candidate_nodes: Array<Record<string, unknown>>
  suggested_bindings: AgentPathBindingSuggestion[]
  preserve_completed: boolean
}

export interface LearningPackageRequest {
  course_id: number
  target: string
  knowledge_point_id?: number | null
  profile?: Record<string, unknown>
  resource_types?: AgentResourceType[]
}

export interface LearningPackageResult {
  run_id: number
  status: AgentStatus
  target: string
  profile: Record<string, unknown>
  agent_trace: AgentTraceItem[]
  progress_events: AgentProgressEvent[]
  resources: GeneratedLearningResource[]
  quality_report: AgentQualityReport
  path_suggestion: AgentPathSuggestion
  warnings: string[]
}

export interface ProfileDialogResult {
  run_id: number
  profile: Record<string, unknown>
  missing_slots: string[]
  next_question: string
  confidence: number
  agent_trace: AgentTraceItem[]
}

export interface ApplyToPathResult {
  ok: boolean
  path_id: number
  run_id: number
  bindings: Array<Record<string, unknown>>
  nodes: Array<Record<string, unknown>>
  warnings: string[]
}

export interface AgentRunDetail {
  run_id: number
  run_type: string
  status: AgentStatus
  input_text: string
  profile_snapshot: Record<string, unknown>
  agent_trace: AgentTraceItem[]
  result_payload: Record<string, unknown>
  error_message: string
  started_at?: string | null
  finished_at?: string | null
  resources: GeneratedLearningResource[]
}

export interface ResourceFeedbackRequest {
  course_id: number
  completed: boolean
  rating?: number | null
  usefulness?: 'useful' | 'neutral' | 'not_useful'
  difficulty?: 'easy' | 'moderate' | 'hard'
  feedback?: string
  quiz_result?: Record<string, unknown>
  time_spent_seconds?: number | null
}

export interface EffectSummary {
  resource_count: number
  feedback_count: number
  completed_count: number
  completion_rate: number
  average_rating: number
  useful_count: number
  recent_feedback: Array<Record<string, unknown>>
  update_summary: Record<string, unknown>
}

export function submitProfileDialog(courseId: number, message: string): Promise<ProfileDialogResult> {
  return request.post('/api/student/agent/profile-dialog', {
    course_id: courseId,
    message
  })
}

export function generateLearningPackage(payload: LearningPackageRequest): Promise<LearningPackageResult> {
  return request.post('/api/student/agent/learning-package', payload, {
    timeout: 120000
  })
}

export function applyGeneratedResourcesToPath(courseId: number, runId: number, resourceIds?: number[]): Promise<ApplyToPathResult> {
  return request.post('/api/student/agent/apply-to-path', {
    course_id: courseId,
    run_id: runId,
    ...(resourceIds?.length ? { resource_ids: resourceIds } : {})
  })
}

export function getAgentRun(courseId: number, runId: number): Promise<AgentRunDetail> {
  return request.get(`/api/student/agent/runs/${runId}`, {
    params: { course_id: courseId }
  })
}

export function completeAgentRun(courseId: number, runId: number): Promise<AgentRunDetail> {
  return request.post(`/api/student/agent/runs/${runId}/complete`, {
    course_id: courseId
  })
}

export function listGeneratedResources(courseId: number, limit = 30, resourceType = ''): Promise<{ resources: GeneratedLearningResource[]; count: number }> {
  return request.get('/api/student/agent/resources', {
    params: {
      course_id: courseId,
      limit,
      ...(resourceType ? { resource_type: resourceType } : {})
    }
  })
}

export function submitGeneratedResourceFeedback(resourceId: number, payload: ResourceFeedbackRequest): Promise<Record<string, unknown>> {
  return request.post(`/api/student/agent/resources/${resourceId}/feedback`, payload)
}

export function getAgentEffectSummary(courseId: number): Promise<EffectSummary> {
  return request.get('/api/student/agent/effect-summary', {
    params: { course_id: courseId }
  })
}
