# A3 参赛版本 PRD

## 1. 项目背景与赛题理解

A3 赛题关注“基于大模型的个性化资源生成与学习多智能体系统开发”。参赛版本不是单纯聊天机器人，而是在课程知识库、学习画像、知识追踪和学习路径基础上，用多智能体协作生成可追溯、可学习、可反馈的个性化资源包。

AdaptiveEdu 现有底座已经覆盖学生、教师、管理员三端，包含课程知识图谱、初始测评、学习路径、任务学习、作业、反馈报告、GraphRAG 与 MEFKT。A3 版本在此基础上新增学生端“个性化智能体”主流程。

## 2. 目标用户与角色

| 角色 | 关注点 | A3 价值 |
| --- | --- | --- |
| 学生 | 不知道怎么补弱项、资料太散、学习路径不清晰 | 通过自然语言描述目标，获得资源包、路径绑定和反馈闭环 |
| 教师 | 需要让课程资源与学生画像联动 | 课程知识库和资源资产成为生成依据，而不是孤立资料 |
| 管理员 | 关注账号、课程、班级和系统可运维性 | 保持统一权限、日志、OpenAPI 和可验证命令 |
| 评审 | 关注赛题要求是否真实落地 | 通过页面、接口、数据和文档矩阵逐项验收 |

## 3. 核心问题与价值主张

- 学生输入自然语言后，系统自动抽取至少 6 个画像维度。
- 多智能体围绕画像、课程知识库、路径、资源、多模态表达和质量评估协作。
- 生成至少 5 类资源，并展示 evidence 与 warnings。
- 将生成资源绑定到学习路径节点，不破坏已完成进度。
- 通过反馈记录学习效果，为后续画像刷新和路径调整提供依据。

## 4. A3 参赛版本范围

已实现范围：

- 后端 Agent 数据模型与 admin 可查看记录。
- `/api/student/agent/*` 学生端 Agent API。
- `/student/agent-learning` 主流程页面。
- 质量守卫、防幻觉 warnings、Agent trace 和同步进度事件。
- OpenAPI 契约、测试和 A3 文档包。

非目标：

- 不在第一阶段引入 Celery、SSE 或 WebSocket 长任务。
- 不生成真实视频文件，视频能力先生成脚本和分镜。
- 不让前端直接访问图数据库、LLM Key 或 Prompt 核心逻辑。

## 5. 用户故事与典型场景

- 作为学生，我希望输入“我想两周内掌握 Spark SQL，但 HDFS 和 MapReduce 基础不太好”，系统能抽取学习目标、薄弱点、节奏、偏好和时间。
- 作为学生，我希望系统生成讲解、导图、练习、阅读和实操资源，并说明每份内容参考了哪些课程材料。
- 作为学生，我希望把生成资源应用到学习路径，并能提交完成状态、评分、难度和文字反馈。
- 作为教师，我希望生成内容优先使用本课程知识点和资源，不凭空编造资料来源。
- 作为评审，我希望看到 trace、质量报告、OpenAPI 和测试矩阵，证明功能可验收。

## 6. 核心业务流程

1. 学生在 `/student/agent-learning` 输入画像描述和学习目标。
2. 前端调用 `POST /api/student/agent/profile-dialog` 抽取画像字段。
3. 前端调用 `POST /api/student/agent/learning-package` 生成学习资源包。
4. 后端记录 `AgentRun`、生成 `GeneratedLearningResource`，输出 `agent_trace`、`quality_report`、`progress_events`。
5. 前端展示资源卡片、证据抽屉、质量 warnings 和路径绑定建议。
6. 学生点击“应用到学习路径”，调用 `POST /api/student/agent/apply-to-path`。
7. 学生提交资源反馈，调用 `POST /api/student/agent/resources/{resource_id}/feedback`。
8. 前端通过 `GET /api/student/agent/effect-summary` 展示效果摘要。

## 7. 功能需求

| 功能 | 当前状态 | 代码入口 |
| --- | --- | --- |
| 对话式画像抽取 | 已实现 | `backend/ai_services/services/agent/profile_dialog.py` |
| Agent 运行记录 | 已实现 | `backend/ai_services/models.py` |
| 多智能体 trace | 已实现 | `backend/ai_services/services/agent/trace.py` |
| 5 类资源生成 | 已实现 | `backend/ai_services/services/agent/resource_generation.py` |
| 学习包生成 | 已实现 | `backend/ai_services/services/agent/learning_package.py` |
| 质量守卫 | 已实现 | `backend/ai_services/services/agent/quality_guard.py` |
| 路径绑定 | 已实现 | `GeneratedLearningResource.metadata` 与 `NodeProgress.extra_data` |
| 反馈闭环 | 已实现 | `backend/ai_services/services/agent/feedback.py` |
| 学生端主页面 | 已实现 | `frontend/src/views/student/AgentLearningView.vue` |

## 8. 非功能需求

- 权限：仅登录学生可访问自己的 Agent 数据，课程必须属于当前学生。
- 可追溯：所有生成资源保存 evidence、画像快照和 AgentRun。
- 降级：LLM、Neo4j、GraphRAG 不可用时使用规则和模板兜底。
- 可验证：后端测试、前端构建、OpenAPI lint/bundle 均可本地运行。
- 可维护：AI 编排在 service 层，不塞进 View、Serializer 或 Model。

## 9. 数据与知识库要求

主演示课程为“大数据技术与应用”。课程资产位于 `backend/tools/自适应学习系统-课程资源/`，包括知识图谱 Excel、初始评测、PPT、教学视频、电子教材和作业库。GraphRAG 运行产物位于 `backend/runtime_logs/rag/`，不进入版本库。

## 10. 赛题要求对照

| 赛题要求 | 系统能力 | 状态 | 证据 |
| --- | --- | --- | --- |
| 对话式画像 | profile-dialog 抽取画像字段和追问 | 已实现 | `ProfileDialogService` |
| 不少于 6 个画像维度 | PROFILE_FIELDS 含 10 个维度 | 已实现 | `schemas.py` |
| 多智能体协作 | profile/knowledge/path/resource/multimodal/evaluation trace | 已实现 | `trace.py` |
| 不少于 5 类资源 | explanation/mindmap/quiz/reading/coding_case | 已实现 | `resource_generation.py` |
| 动态学习路径 | apply-to-path 绑定资源到节点 | 已实现 | `learning_package.py` |
| 进度展示 | progress_events 与前端 Timeline | 已实现 | `AgentRunTimeline.vue` |
| 防幻觉 | evidence 为空返回 warnings | 已实现 | `quality_guard.py` |
| 学习效果评估 | 资源反馈与 effect-summary | 已实现 | `feedback.py` |

## 11. 验收标准

- 访问 `/student/agent-learning` 可完成画像抽取、资源包生成、证据查看、路径绑定和反馈。
- 后端 `ai_services.tests` 全部通过。
- OpenAPI 包含所有 `/api/student/agent/*` 接口并通过 Redocly lint。
- 文档、页面和接口状态一致。

## 12. 后续扩展

- 将长流程改造成异步任务、SSE 或 WebSocket 进度。
- 引入教师审核队列，让教师确认生成资源后再推荐给更多学生。
- 增加真实视频生成、语音讲解或课件导出。
