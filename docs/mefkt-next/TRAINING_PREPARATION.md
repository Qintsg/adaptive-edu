<!--
MEFKT-NG 首阶段训练脚本、集群作业和指标留存说明
@Project : adaptive-edu
@File : TRAINING_PREPARATION.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 首阶段训练准备

> 状态：阶段 B 首次 prd 训练已完成 153 个 epoch，最终测试集指标和产物留存见 [训练结果](TRAINING_RESULT_20260924.md)。本文保留脚本与数据协议说明；实现的是 [架构设计](README.md) 的阶段 B 核心，不代表所有候选扩展均已落地或已经接入线上。

## 已准备的范围

- [训练入口](../../backend/scripts/mefkt_ng_train.py) 接受 canonical CSV、已有 384 维题目内容向量，以及可选的有类型知识关系 JSON。
- [数据适配器](../../backend/scripts/mefkt_ng/data.py) 按学生稳定切分 80/10/10，保留原始记录行号、真实时间是否已知、同场测验边界，以及仅供状态恢复的重叠上下文。未评分记录不会被当成错误。
- [模型核心](../../backend/scripts/mefkt_ng/model.py) 对题目和知识点内容建模，按知识点维护能力均值、估计方差和稳定时间尺度；题目预测先于答案更新，同一测验场次的结果一起更新。没有来源可验证的学习活动暂不改变能力。
- 可选知识图谱边支持 `prerequisite`、`part_of`、`includes`、`related`，关系方向保留。未传图文件时仅用内容分支。
- [训练循环](../../backend/scripts/mefkt_ng/training_loop.py) 兼容单 GPU 与 `torchrun` 多 Pod DDP。4090D/5090 可启用 bfloat16 AMP，状态滤波保持 float32。原始 CSV/NPZ 留在 JuiceFS 数据 PVC；随机读取的预处理数组、逐轮 checkpoint 和小文件指标写入独立 NFS 结果 PVC。
- [Volcano 清单脚本](../../backend/scripts/render_mefkt_ng_job.ps1) 默认只输出 YAML；只有显式 `-Submit` 才访问集群，并通过 Kubernetes-bbt 日志包装器记录每条 kubectl 操作。

本阶段尚未实现 Full 的学习事件上下文与资源学习增益，也不接管线上 KT 服务。`--hidden-dim` 可在集群硬件允许时提高；模型的实际收益和适用容量需由后续训练验证。以当前无图目录计算，1024 维配置有 **5,393,411 个可训练参数**，这是结构计数，不是训练结果。

## 输入条件

仓库当前可用的输入示例：

```text
backend/runtime_logs/mefkt_mixed/canonical/train.csv
backend/runtime_logs/mefkt_mixed/item_content_embeddings.npz
```

输入数据和缓存都在 `runtime_logs`，不进入 Git。题目向量 NPZ 须包含与 CSV 题目 ID 一一对应的 `item_ids`、`embeddings [N,384]` 和编码器版本。缺失内容向量会导致预处理失败，避免在声称使用内容泛化时实际退化为全零向量。

知识关系为可选 JSON 列表；ID 必须使用 canonical `skill_ids` 中的稳定标识：

```json
[
  {"from": "course:hdfs", "to": "course:mapreduce", "type": "prerequisite"},
  {"from": "course:spark-sql", "to": "course:hive", "type": "related"}
]
```

当前 canonical 文件没有结果首次可见时间。适配器记录了“每题结果即时可见”的**离线假设**，不把它当作真实线上时间；有 `submission_id` / `episode_id` 时整场测验共享考前状态。不存在可靠逐题耗时或提示记录时，该阶段不消费这些特征。

## 本地只读预检

在项目根目录运行；以下命令不会训练或写输出：

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\scripts\mefkt_ng_train.py `
  --events-file .\backend\runtime_logs\mefkt_mixed\canonical\train.csv `
  --content-embeddings-file .\backend\runtime_logs\mefkt_mixed\item_content_embeddings.npz `
  --data-root .\backend\runtime_logs\mefkt_ng_prepared `
  --output-dir .\backend\runtime_logs\mefkt_ng_run `
  --dry-run
```

预处理可通过 `prepare_data` 单独执行，不会更新模型参数。当前仓库的输入已经完成一次本地预处理核对：1,098,343 条事件、6,741 名学习者、14,732 道题、119 个知识点；训练/验证/测试目标事件分别为 878,210 / 109,552 / 110,581。这仅是数据适配结果，不是模型效果。

## 全程留存的产物

一个运行使用独立 `output-dir`，所有记录写入 NFS 结果 PVC 的持久目录：

```text
run_config.json                  输入摘要、参数、设备、代码摘要
job_manifest_<job>.yaml         实际提交的 Volcano 清单
training_source.zip             实际 Python 训练源码快照
disk_budget.json                每轮保留 checkpoint 的磁盘预算估计
segments.jsonl                  启动、续训和完成记录
steps/rank_NNN_<segment>.jsonl   每个 rank 的每个优化步骤
epoch_metrics.jsonl             每个已完成 epoch 的完整嵌套指标
epoch_metrics.csv               从 JSONL 派生的表格指标
predictions/validation_*.csv.gz 每轮逐题验证预测及原始行号
checkpoints/epoch_*.pt          每轮完整模型、优化器、调度器、数据标识
rng/epoch_*_rank_*.pt           每轮各 rank 的随机数状态
latest.json / best_nll.json     指向永久保留 checkpoint 的索引
final_summary_epoch_*.json      训练结束后的最佳验证与最终测试结果
predictions/test_final_*.csv.gz 最终选定 checkpoint 的逐题测试预测
logs/rank-*.log                 集群 Pod 标准输出（集群脚本）
torch_cache/rank_*/             当前运行专用 PyTorch 缓存
```

逐步日志记录学习率、优化目标、普通 BCE、有效目标数、裁剪前梯度范数、耗时、CUDA 已分配峰值和该 batch 的 NLL/AUC/Brier/ECE/准确率。批次 AUC 仅反映当时正在更新的模型；每轮另在固定权重下重新评价**完整训练集**与完整验证集，保存 NLL、AUC、Brier、ECE、准确率、样本量和分学科指标。验证预测每轮可按 `source_row` 与原始 CSV 回连。**不保存每轮训练集逐题预测**，按本次约定控制磁盘占用；每轮聚合指标仍完整保留。

测试集只在训练结束、根据验证 NLL 确定 checkpoint 后评价一次；不会参与早停或模型选择。AUC 遇单一类别输出 `null`，不会伪装为 0.5。

checkpoint 不覆盖旧轮次。断点续训会保留此前步骤日志、验证预测、指标和权重，并为新启动生成 `segment_id`。中断轮次的步骤日志也保留；分析时以已提交的 epoch checkpoint 和指标为准，避免将中断后重新执行的步骤误算成额外训练轮次。续训检查输入、图谱、模型结构和训练源码摘要；有差异须新建运行目录。

提交清单准备三份 PVC：`mefkt-code` 10 Gi NFS 放代码，`mefkt-data` 100 Gi JuiceFS 放原始 CSV/NPZ，`mefkt-ng-results` 50 Gi NFS 放随机读取的预处理数组、日志、预测和每轮 checkpoint；缺少时由显式 `-Submit` 的脚本创建。每轮权重和优化器状态会累积，提交前须核对 namespace 总存储配额，用 `disk_budget.json` 核对运行所需空间。

## 4090D / 5090 集群清单预览

在项目根目录运行下面命令，只渲染 Volcano YAML，不连接集群：

```powershell
pwsh -NoProfile -File .\backend\scripts\render_mefkt_ng_job.ps1 `
  -JobName mefkt-ng-preview -RunId mefkt-ng-preview `
  -GpuCount 2 -BatchSize 128 -HiddenDim 1024
```

渲染结果包含三份 PVC、一个 CPU 上传 Pod 和一个 Volcano Job，共五份清单。生成的作业每个 worker 请求 1 张 NVIDIA GPU，GPU 作业默认 1024 维表示（本地 CPU 入口默认为 384 维）；允许通过 `-HiddenDim` 与 `--max-parameters` 调整容量。默认 `node-type=gpu`；需要指定已知的 4090D 或 5090 节点时传 `-NodeName <实际节点名>`。作业遵循集群管理办法使用 `advisor-rhw-gpu` 队列、`gpu-job-high` 优先级和 PyTorch 镜像；正式运行前仍需核对节点、PVC、队列与容量。

用户授权后已显式执行 `-Submit -UploadData`。脚本通过带操作日志的包装器创建 PVC，先在 CPU Pod 上传源码与数据、校验远端 SHA-256 并发布 `.ready` 标记，然后创建 GPU Volcano Job。初版 Job 因 g4 CPU request 不足 Pending；确认尚未训练且 Volcano 禁止就地修改模板后，只重建了这个 Job，`1/4 CPU` 版已在 g4 Running。初版与生效版清单、操作过程和当前指标见 [prd 提交记录](K8S_PRD_SUBMISSION_20260924.md)。

续训使用新的 `JobName` 和原来的 `RunId`，加 `-Resume`，让新 Pod 读取 NFS 结果 PVC 中原运行的 `output-dir`。已完成的 checkpoint、指标与预测继续保留；不可随意修改原运行源码或输入。

## 验证范围

已通过 [无训练单测](../../backend/scripts/test_mefkt_ng.py) 覆盖：当前标签不泄漏、同场试卷不逐题泄漏、不同知识点不互相写入、等待时间不提高回忆、窗口不重复计目标、未评分不当作错、日志只追加及 checkpoint 不覆盖。[假集群提交测试](../../backend/scripts/test_render_mefkt_ng_job.ps1) 验证了先上传后提交的命令顺序；Volcano YAML 已完成本地解析。正式 DDP/GPU 运行与指标表现须在后续集群训练时验证。
