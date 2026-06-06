# A3 参赛文档总览

> 面向中国软件杯 A3 赛题“基于大模型的个性化资源生成与学习多智能体系统开发”的交付材料入口。

## 阅读顺序

1. `PRD.md`：先理解参赛版本要解决什么问题、面向哪些角色、验收范围是什么。
2. `架构设计说明.md`：理解前端、后端、知识库、GraphRAG、MEFKT、LLM 与 Agent 的边界。
3. `多智能体与资源生成说明.md`：理解画像对话、多智能体编排、资源生成、证据追溯、质量守卫和反馈闭环。
4. `数据与知识库说明.md`：理解“大数据技术与应用”课程知识库、资源资产、样例数据和索引构建。
5. `API与接口契约说明.md`：面向前后端联调和接口验收。
6. `部署与验收手册.md`：从本地启动到自动化验证、浏览器巡检和故障排查。
7. `演示脚本与录屏提纲.md`：7 分钟视频、现场演示点击路径和 PPT 大纲。
8. `测试与验收矩阵.md`：按赛题要求逐项自查。
9. `AI工具使用与开源合规说明.md`：说明 AI 工具、开源依赖、素材授权与密钥边界。

## 交付清单

| 文档 | 用途 | 对应 Issue |
| --- | --- | --- |
| `README.md` | A3 专题入口和提交前检查清单 | #11 #20 |
| `PRD.md` | 产品目标、角色、范围与赛题需求对照 | #12 |
| `架构设计说明.md` | 系统架构、模块边界、AI 能力边界与降级策略 | #13 |
| `多智能体与资源生成说明.md` | 智能体角色、资源类型、证据追溯和反馈闭环 | #14 |
| `数据与知识库说明.md` | 课程资产、知识图谱、题库、GraphRAG、MEFKT 与演示数据 | #15 |
| `API与接口契约说明.md` | Agent API、统一响应、OpenAPI 和联调方法 | #16 |
| `部署与验收手册.md` | 启动、样例数据、验证命令、浏览器巡检和排障 | #17 |
| `演示脚本与录屏提纲.md` | 录屏脚本、现场演示清单和 PPT 大纲 | #18 |
| `测试与验收矩阵.md` | 赛题要求、功能、非功能、文档和演示验收矩阵 | #19 |
| `AI工具使用与开源合规说明.md` | 源代码许可、AI 工具、依赖和非代码资产授权边界 | #21 |

## 当前 A3 代码状态

- 已实现 A3 Agent 数据底座：`AgentRun`、`ProfileDialogTurn`、`GeneratedLearningResource`、`GeneratedResourceFeedback`。
- 已实现学生端 Agent API：画像对话、资源生成、学习包、路径绑定、运行详情、资源列表、反馈、运行完成和效果摘要。
- 已实现学生端页面 `/student/agent-learning`，包含画像输入、生成进度、资源卡片、证据抽屉、路径绑定建议和反馈面板。
- 已实现至少 5 类资源生成：讲解文档、思维导图、练习题、拓展阅读、代码实操案例；可选生成视频脚本。
- 已实现质量守卫和防幻觉提示：证据为空时返回 warnings，不伪造来源。
- 已实现 OpenAPI 契约和 `docs/api.yaml` 打包产物。

## 提交前检查清单

- `cd backend && uv run python manage.py check`
- `cd backend && uv run python manage.py makemigrations --check --dry-run`
- `cd backend && uv run python manage.py test ai_services.tests --verbosity 2`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `npx @redocly/cli lint adaptiveedu@v1`
- `npx @redocly/cli bundle adaptiveedu@v1`
- 本地服务启动后访问 `/health/`、`/student/agent-learning` 并完成一次生成资源包、应用到路径、提交反馈。

## 维护边界

- 不提交 `backend/.env`、`backend/runtime_logs/`、`frontend/dist/`、`node_modules/`。
- API 变化先改 `docs/openapi/` 源文件，再打包 `docs/api.yaml`。
- 文档只描述当前仓库真实能力；后续扩展必须标注对应 Issue 或明确为规划。
