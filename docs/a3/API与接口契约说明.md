# A3 Agent API 与接口契约说明

## 1. 契约来源

OpenAPI 源文件：

```text
docs/openapi/openapi.yaml
docs/openapi/paths/student_agent.yaml
docs/openapi/components/schemas/
```

打包产物：

```text
docs/api.yaml
```

校验和打包：

```bash
npx @redocly/cli lint adaptiveedu@v1
npx @redocly/cli bundle adaptiveedu@v1
```

## 2. 统一响应格式

后端统一使用 `common.http.responses`：

```json
{
  "code": 200,
  "msg": "OK",
  "data": {}
}
```

错误响应会保留 `code/msg/data`，并可附加 `error`：

```json
{
  "code": 403,
  "msg": "您未选修该课程",
  "data": null,
  "error": {
    "type": "HTTP_403",
    "details": null
  }
}
```

前端 Axios 会自动解包 `data`，业务 API 不返回裸 DRF 格式。

## 3. 接口列表

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/student/agent/profile-dialog` | 对话式画像抽取 |
| POST | `/api/student/agent/generate-resources` | 生成至少 5 类个性化资源 |
| POST | `/api/student/agent/learning-package` | 生成学习资源包、进度事件、质量报告和路径建议 |
| POST | `/api/student/agent/apply-to-path` | 将生成资源绑定到学习路径 |
| GET | `/api/student/agent/runs/{run_id}` | 查询 Agent 运行详情 |
| POST | `/api/student/agent/runs/{run_id}/complete` | 标记本次 Agent 学习完成 |
| GET | `/api/student/agent/resources` | 查询当前课程生成资源 |
| POST | `/api/student/agent/resources/{resource_id}/feedback` | 提交生成资源学习反馈 |
| GET | `/api/student/agent/effect-summary` | 查询生成资源学习效果摘要 |

## 4. 关键 Schema

- `AgentRun`：运行 ID、状态、输入、画像快照、trace、结果、错误信息、时间和资源列表。
- `ProfileDialogResult`：画像字段、缺失字段、下一轮追问、置信度和 trace。
- `GeneratedLearningResource`：资源类型、标题、内容、结构化 payload、证据、画像快照、metadata 和知识点。
- `AgentLearningPackage`：画像、trace、进度、资源、质量报告、路径建议和 warnings。
- `AgentQualityReport`：状态、得分、缺失类型、warnings、errors 和单资源检查结果。
- `AgentPathBindingResult`：路径 ID、run ID、bindings、节点摘要和 warnings。
- `GeneratedResourceFeedbackRequest`：完成状态、评分、难度、有用性、文本反馈、练习结果和学习耗时。
- `AgentEffectSummary`：资源数、反馈数、完成率、平均评分和画像/路径更新摘要。

## 5. 请求示例

画像对话：

```http
POST /api/student/agent/profile-dialog
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "course_id": 1,
  "message": "我是软件专业学生，想两周内掌握 Spark SQL，但 HDFS 基础不太好，喜欢案例和练习。"
}
```

学习包生成：

```json
{
  "course_id": 1,
  "target": "补齐 Spark SQL 查询和 DataFrame 操作",
  "resource_types": ["explanation", "mindmap", "quiz", "reading", "coding_case"],
  "profile": {
    "pace": "fast",
    "preferred_resource": ["coding_case", "quiz"]
  }
}
```

资源反馈：

```json
{
  "course_id": 1,
  "completed": true,
  "rating": 5,
  "usefulness": "useful",
  "difficulty": "moderate",
  "feedback": "练习题和代码案例帮助我理解了查询流程。",
  "time_spent_seconds": 1200
}
```

## 6. 常见错误场景

| 场景 | 状态 | 响应 |
| --- | --- | --- |
| 未登录 | 401 | JWT 认证错误 |
| 非学生访问 | 403 | `仅学生可以访问个性化智能体接口` |
| 未选修课程 | 403 | `您未选修该课程` |
| 缺少 `course_id` | 400 | `缺少 course_id 参数` |
| 空画像输入 | 400 | `请输入画像对话内容` |
| 知识点不属于课程 | 404 | `知识点不存在或不属于当前课程` |
| run/resource 不属于当前学生 | 404 | `不存在或无权访问` |

## 7. 联调方式

前端 API 封装位于：

```text
frontend/src/api/student/agent.ts
```

学生端页面位于：

```text
frontend/src/views/student/AgentLearningView.vue
```

推荐联调步骤：

1. 登录学生账号。
2. 选择课程。
3. 调用 `profile-dialog` 抽取画像。
4. 调用 `learning-package` 生成资源包。
5. 调用 `apply-to-path` 绑定资源。
6. 调用 `feedback` 提交学习反馈。
7. 调用 `effect-summary` 检查反馈汇总。

## 8. 验证命令

```bash
cd backend
uv run python manage.py test ai_services.tests.student.test_agent_api --verbosity 2

cd ..
npx @redocly/cli lint adaptiveedu@v1
npx @redocly/cli bundle adaptiveedu@v1
```
