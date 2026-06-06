# AI 工具使用、开源合规与素材授权说明

## 1. 文档目的

本文用于 A3 参赛提交材料，说明 AdaptiveEdu 使用的开源依赖、AI 工具、模型服务、课程资源和非代码资产授权边界，并给出内容安全与防幻觉措施。

## 2. 源代码许可证

项目源代码使用 Academic Free License version 3.0（AFL-3.0），详见根目录：

```text
LICENSE
```

版权归 Qintsg(饶弘玮) 所有。

## 3. 主要开源依赖

后端依赖来源：

```text
backend/pyproject.toml
backend/uv.lock
```

主要类别：

- Django、Django REST Framework、Channels。
- PostgreSQL 驱动 `psycopg2-binary`。
- LangChain、langchain-openai。
- Neo4j、neo4j-graphrag、Qdrant。
- pandas、openpyxl、xlrd。
- scikit-learn、sentence-transformers、torch。

前端依赖来源：

```text
frontend/package.json
frontend/package-lock.json
```

主要类别：

- Vue 3、Vite、TypeScript、Pinia、Vue Router。
- Naive UI、`@vicons/fluent`。
- D3、ECharts、marked、axios。

## 4. 大模型与 AI 服务使用说明

当前配置入口：

```text
backend/config.ini
backend/.env.example
```

非敏感默认配置在 `backend/config.ini`；API Key、数据库密码等敏感信息只放本地 `backend/.env`，不得提交。

AI 能力包括：

- DeepSeek / 通义千问等 OpenAI 兼容 LLM 客户端。
- LangChain Agent。
- GraphRAG 课程证据检索。
- MEFKT 知识追踪。
- Tavily 外部学习资源搜索。
- A3 Agent 模板化兜底资源生成。

## 5. AI 生成内容边界

系统生成的讲解、导图、练习、阅读、代码案例和视频脚本是学习辅助材料，不作为绝对事实。生成内容应满足：

- 优先基于课程知识点和课程资源 evidence。
- evidence 为空时必须返回 warnings。
- 不伪造教材、论文、链接或资源来源。
- 重要内容由教师或使用者复核后再用于正式教学。

## 6. 第三方数据和课程资源边界

课程资产位置：

```text
backend/tools/自适应学习系统-课程资源/
```

这些材料包括 PPT、视频、PDF、Excel 题库和知识图谱源文件。它们是非代码资产，不随 AFL-3.0 源代码许可证自动授权。公开传播、二次分发或商业使用前，应确认具体素材的权利来源和授权范围。

## 7. 多媒体与 Git LFS 资产说明

`.mp4`、`.mov`、`.ppt`、`.pptx`、`.pdf`、`.xls`、`.xlsx` 等文件可能由 Git LFS 或普通 Git 管理，但是否在仓库中出现不等于自动开放授权。参赛提交时应只展示必要片段，并保留来源说明。

## 8. 内容安全与防幻觉措施

- `AgentQualityGuard` 校验资源标题、正文、类型、证据和结构。
- `ResourceGenerationService` 在 evidence 为空时返回 warning。
- `EvidenceDrawer` 在前端展示证据和生成限制。
- LLM 不可用时使用模板化内容，不阻断流程。
- 权限校验保证学生只能访问自己的课程和 Agent 数据。
- 运行日志不得记录 API Key、密码或敏感环境变量值。

## 9. 密钥和隐私数据处理

不得提交：

- `backend/.env`
- `backend/runtime_logs/`
- `frontend/dist/`
- `node_modules/`

可提交：

- `backend/.env.example`
- `backend/config.ini`
- 依赖锁文件。
- 非敏感测试数据和课程样例资产。

## 10. 提交材料合规自查

- 源代码许可证与根 `README.md` 一致。
- 文档没有真实 API Key、密码或私有账号密码。
- AI 生成内容说明了证据追溯和人工复核边界。
- 非代码资产授权边界与根 `README.md` 不冲突。
- OpenAPI 和页面不暴露内部敏感路径。
