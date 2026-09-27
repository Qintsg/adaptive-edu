<!--
MEFKT-NG 后端替换与回滚说明
@Project : adaptive-edu
@File : BACKEND_NG_ADAPTER_20260925.md
@Author : Qintsg
@Date : 2026-09-25
-->

# MEFKT-NG 后端替换与回滚

后端默认模型包改为 `backend/models/MEFKT_NG/`：选定 epoch 136 的 `model.safetensors`、目录映射、元数据和精确模型结构源码一同保留。权重 SHA-256 为 `d13aad408cf233f967eff02439109b62c8ff154bd6567e6ef5df4fc14cfc8cd9`。原 `backend/models/MEFKT/mefkt_model.pt` 与元数据未覆盖，可供显式回滚。

`ai_services.services.mefkt.inference.MEFKTPredictor` 保持公开 `load_model`、`predict` 和 `get_info` 接口。新目录由 `ng_runtime.py` 加载：先核对模型、目录与结构源码摘要，然后只迁移训练好的共享参数；`ng_course_data.py` 从当前课程的可见题目及其知识点关联中建立无答案的静态快照，`ng_catalog.py` 用训练时相同的冻结多语言 MiniLM 生成 384 维内容向量并构造课程局部模型。课程快照修订变化时缓存会重建，最多保留四门课程。`ng_sequence.py` 按时间和场次恢复已评分历史，候选题同场预测且不提前吸收虚拟答案；知识点概率由其关联候选题聚合。

默认运行模式是 MEFKT-NG，`KT_MEFKT_NG_BUNDLE_PATH` 可覆盖模型包路径。为了防止旧 `.env` 悄悄重新启用旧权重，默认模式忽略遗留的 `KT_MEFKT_MODEL_PATH`；仅 `KT_MEFKT_RUNTIME=legacy` 时使用该路径和旧 `.pt`。`KT_MEFKT_NG_ENCODER_PATH` 可指定与训练时相同编码器的本地目录，`KT_MEFKT_NG_DEVICE` 默认 `cpu`。运行时先尝试从本机缓存离线加载编码器；缓存缺失时才尝试获取固定模型。课程无关联题目、编码器不可用或模型无法覆盖目标知识点时，KT 服务回退到原有统计估计，并且不会把回退结果标记为真实 MEFKT-NG。现有本机 `.env` 的 `KT_MEFKT_MODEL_PATH` 仍指向旧权重；已通过真实课程烟测确认新默认逻辑不会被此遗留配置覆盖。

新模型仍使用旧 KT 返回结构：`predictions` 为知识点 ID 到答对概率的映射，保留 `confidence`、`question_predictions`、`analysis` 和模式元数据；`model_type` 为 `mefkt_ng`。下游 `is_mefkt_prediction` 已识别该类型，因此初测、学习路径等现有调用链能够使用新结果。无历史作答时仍返回未观测基线。

验证包括：真实导出权重包严格加载、课程修订缓存、答错 `0` 与整场考试边界、答对/答错单调方向、数据库可见题过滤和无答案泄漏、KT 服务完整返回结构、编码器失效时统计回退、旧版权重显式回滚。还在本机实际课程的只读题库上，以合成作答和真实多语言编码器完成服务烟测；默认新模型返回有效的知识点概率。测试命令：

```powershell
cd backend
.venv/Scripts/python.exe manage.py test ai_services.tests.kt --noinput
.venv/Scripts/python.exe manage.py test assessments.tests.test_knowledge_mastery_blending assessments.tests.test_knowledge_result_refresh --noinput
```

该改动是**本地后端代码替换，尚未发布到远端服务**。四来源公开测试 AUC `0.715220` 是已查看过测试集后的续训复评；目前没有真实业务课程的独立效果指标。正式发布前需预置冻结编码器，并以真实课程独立学习者或未来时间段验证 AUC、NLL、Brier、ECE、冷启动、延迟和课程分布变化。EdNet 与 Junyi 的非商业许可也需在部署场景下核对。

本机 50 道题课程的只读合成作答烟测中，默认服务已确认使用 `runtime_mode=ng`；首次请求约 12.4 秒，缓存后约 0.18 秒。首次加载编码器的耗时在多进程部署中会按 worker 重复发生，需在部署前预热并测量真实负载。

另以本机 141 道题课程、100 条**合成**历史和 10 个目标知识点测试，默认服务输出了 10 个有效概率；首次约 14.6 秒、同进程缓存后约 0.23 秒。未读取真实学生作答；这些时间仅是本机观察值，不替代部署压测。

本机答题历史按课程盘点后仅有一门课程、1 名学习者和 50 条记录，不足以进行独立学习者泛化验收；因此此次完成的是后端代码与推理契约替换，尚不能据此证明新模型在业务课程上优于旧模型。

## 本地前后端联调

使用本机 Docker PostgreSQL、Django 开发服务与 Vite 开发服务，以独立学生账号在浏览器走完登录、选择“数据可视化基础”、知识测评、报告、能力评测、习惯问卷和学习路径。知识测评提交与各接口均返回 200；KT 单模型接口返回 `model_type=mefkt_ng`，知识点 5 的预测为 `0.6748`；学习路径生成 4 个节点，浏览器无控制台错误。该联调仅验证业务链路与数据契约，不是模型精度验收。

联调发现能力评测页面原先未传 `course_id`，后端旧客户端默认取同班第一门课程，使成绩归属错误。现前端页面和测评 store 均传当前课程，后端在缺少显式课程 ID 时优先读取已选课程上下文。用新测试账号复核：能力成绩只写入课程 3，课程 3 的能力、习惯与知识测评状态均为完成；对应回归测试与前端类型检查、生产构建已通过。

本地复测可在已运行的 Django `127.0.0.1:8000` 和 Vite `127.0.0.1:3000` 开发服务上执行：

```powershell
cd backend
.venv/Scripts/python.exe scripts/prepare_mefkt_ng_local_e2e.py
cd ../frontend
node scripts/mefkt-ng-local-e2e.mjs
```

准备脚本只接受 DEBUG 模式的本机数据库，要求已有“数据可视化基础”课程及全局问卷；它创建一次性学生账号，凭据仅写到系统临时目录，不纳入仓库。浏览器脚本会提交真实本地测评并检查模型类型、报告、状态、学习路径与浏览器错误。

输入检查修复了三处问题：外课题目不会被映射成本课作答；`0.0/1.0` 评分会正常保留；本课没有可识别作答时，NG 不把内容冷启动概率当作有效预测，上层改用统计回退。并发检查还发现，三路冷请求曾重复构建三份课程目录；现在同一课程修订只构建一次。针对性测试和本机 50 题课程核对均已通过。
