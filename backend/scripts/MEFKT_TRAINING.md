# MEFKT / MEFKT-Lite 训练说明

当前工程提供两个共享输入/输出 interface 的知识追踪模型：

| 模型 | 内部架构 | 目标运行环境 |
|---|---|---|
| `MEFKT` | 开放世界题目表示 + 自适应遗忘 GRU + 6 层、8 头因果 Transformer + 64 个跨窗口 memory slots | 正常 GPU 推理，设计上限制单次推理显存不超过 8GiB |
| `MEFKT-Lite` | 开放世界题目表示 + 自适应遗忘 GRU | 少于 4 核 CPU、无 GPU |

两个模型都由 [mefkt_models.py](./mefkt_models.py) 实现，由 [mefkt_train.py](./mefkt_train.py) 统一训练。

## 统一输入 interface

训练和线上历史编码均使用：

```text
items            [B, L] long       题目内部索引，-1 为 padding 或未知题目（未知题目必须配 valid mask）
correct          [B, L] long       0/1，当前交互是否答对
gaps             [B, L] float      距离上一次交互的小时数
response_times   [B, L] float      当前题目真实答题耗时，单位秒
```

新课程冷启动还应在课程发布阶段为每道题准备固定 384 维内容向量。生成工具为 [prepare_mefkt_content_embeddings.py](./prepare_mefkt_content_embeddings.py)，在线 Lite 推理不加载文本编码器。

预测目标是当前交互的 `correct`。模型会先利用前面的历史状态，再对当前题目给出答对 logit，因此不会使用当前题目的答案作为输入泄漏给自己。

线上候选题调用：

```python
probabilities, state = model.predict_next(
    history_items,
    history_correct,
    history_gaps,
    history_response_times,
    candidate_items,
    candidate_gaps,
)
```

返回每个候选题的独立答对概率和可传给下一窗口的 `SequenceState`。`SequenceState` 包含 GRU 状态、Transformer memory 和最后上下文；下一窗口把它作为 `initial_state` 传回，即可继续同一学习者的状态。

## 通用题目表示

模型不只依赖题目 ID，还融合每道题的：

- 题目 ID embedding；
- `subject_id`/学科 embedding；
- 多个 `skill_id`/知识点 embedding 的 masked mean pooling；
- 训练集统计难度、频率、平均交互间隔、平均答题耗时、part、tag 数量、发布时间。

EdNet 适配器将 `part` 作为 subject，将 `tags` 作为 skill。换用其他学科或其他数据集时，只要适配到同一 canonical schema，就能继续使用相同模型：

```text
user_id, item_id, timestamp, correct, response_time_seconds, subject_id, skill_ids
```

仓库中的 [mefkt_canonical_data.py](./mefkt_canonical_data.py) 已提供 CSV 适配器。CSV 需要按 `user_id,timestamp` 排序，可以直接这样训练：

```powershell
uv run python scripts\mefkt_train.py `
  --profile full --dataset canonical-csv `
  --events-file runtime_data\mixed\events.csv `
  --content-embeddings-file runtime_data\mixed\item_content_embeddings.npz `
  --data-root runtime_data\mixed `
  --output-dir models\MEFKT\mefkt_mixed_v3
```

真正的跨课程泛化需要基础训练覆盖多个课程/领域，并使用固定内容向量；架构不能让只在单一学科训练的模型自动学会完全无描述的新课程。当前可复现数据包已经混合 SLAM 语言学习与 ASSISTments 数学，正式集群训练应使用这份混合数据。后续仍建议加入许可证明确的科学等第三领域数据，并继续做完整课程留出评估，而不只做随机题目切分。

未知题目使用 `item=-1`，并传入 `candidate_features [N,7]`、`candidate_content_features [N,384]`；历史未知题还必须通过 `history_valid_mask=True` 标记为有效交互。没有内容描述时可以 OOV 运行，但不应承诺零样本质量。

## 时间与遗忘机制

历史交互同时使用两个时间量：

1. `gap`：两次学习行为之间的间隔；
2. `response_time`：学生完成当前题目的真实答题耗时。

两者都使用 log/sqrt 特征编码。遗忘率不再是单一全局标量，而是由：

```text
基础遗忘率[state_dim]
+ 当前题目/学科/知识点/时间条件[state_dim]
```

生成每个隐藏维度的正遗忘速度，再按 gap 对上一窗口状态逐维衰减。这样快速遗忘、稳定掌握和不同学科的状态维度可以有不同速度。

## 窗口状态传递

数据预处理使用重叠上下文：后续窗口保留前一窗口末尾的历史，但只对本窗口的新目标区间计算损失，避免把同一题重复当成新标签。

例如最大窗口 200、上下文 64：

```text
窗口 1：交互 0..199，目标 0..199
窗口 2：交互 136..335，目标 200..335
窗口 3：交互 272..471，目标 336..471
```

线上或长序列推理时，可以进一步传递 `SequenceState`，完整模型还会保留最近 64 个 Transformer 上下文；Lite 只保留 128 维 GRU 状态。

## 本机 smoke

```powershell
Set-Location .\backend

# CPU Lite
uv run python scripts\mefkt_train.py `
  --profile lite `
  --dataset synthetic `
  --data-root runtime_logs\mefkt_lite_v3_data `
  --output-dir runtime_logs\mefkt_lite_v3_output `
  --epochs 2 --batch-size 32 --sequence-length 48 `
  --window-context-length 16 --num-workers 0 --cpu-threads 2

# GPU Full；项目锁文件已配置 CUDA Torch，--amp 启用 CUDA 混合精度
uv run python scripts\mefkt_train.py `
  --profile full `
  --dataset synthetic `
  --data-root runtime_logs\mefkt_v3_data `
  --output-dir runtime_logs\mefkt_v3_output `
  --epochs 2 --batch-size 8 --sequence-length 48 `
  --window-context-length 16 --num-workers 0 --amp
```

当前项目使用 `pytorch-cu130` 显式源锁定 CUDA 版 Torch。首次更新依赖或换机器后执行 `uv sync`，随后可以用下面的命令确认 CUDA 环境，不要使用会绕过项目锁定的 CPU Torch：

```powershell
uv sync
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
```

## 长训上传包和日志

正式集群训练使用混合 canonical 数据（语言学习 + 数学），当前本地包的输入文件为：

```text
runtime_logs/mefkt_mixed/canonical/train.csv                 # 约 1.08M 条交互，约 198MiB
runtime_logs/mefkt_mixed/item_content_embeddings.npz         # 14,732 道题的 384 维内容向量
```

在上传前生成带 SHA-256 清单的完整包：

```powershell
pwsh -NoProfile -File .\scripts\package_mefkt_training_bundle.ps1 -Force
```

产物为 `runtime_logs/mefkt_training_bundle/` 和同名 `tar.gz`。包内包含数据、全部训练模块、运行时门禁、指标持久化和曲线脚本。提交器仍会把代码逐文件原子发布到 Code PVC、把数据逐文件原子发布到 Data PVC；这样 Pod 在上传中断时不会看到半成品。

训练输出目录固定保留以下文件：

```text
train.log                  # torchrun 所有 rank 的 stdout/stderr
run_config.json            # 参数、数据、设备和 Torch 版本
training_metrics.jsonl     # 每个 epoch 的完整嵌套指标
training_metrics.csv       # 便于表格/脚本读取的扁平指标
best.pt                    # 兼容别名，指向 validation AUC 最优权重
best_auc.pt                # validation AUC 最优权重
best_loss.pt               # validation loss 最优权重
last.pt                    # 最新可恢复权重
runtime_validation.json    # CPU/GPU 运行时门禁
diagnosis.json             # 可选的因果性和分学科诊断结果
```

训练完成或训练中途即可绘图和查看最近数值：

```powershell
uv sync --extra plot
uv run --extra plot python scripts\mefkt_plot_training.py `
  --metrics <output>\training_metrics.jsonl `
  --output <output>\training_curves.png `
  --recent-output <output>\training_curves_recent.png `
  --recent-epochs 10
```

脚本会输出最佳 validation AUC、对应 test AUC，以及最近 10 轮的 train/validation/test loss、AUC、Brier、ECE 和 ACC；总图同时高亮最近窗口。`training_metrics.jsonl` 适合断点续训，重复 epoch 会由分析脚本保留最后一次记录。

长训默认最多运行 1000 个 epoch。训练器默认使用初始学习率 `1e-4`、AdamW weight decay `5e-4` 和 `ReduceLROnPlateau`；validation loss 平台期会先降低学习率，再由趋势早停决定是否结束。默认关闭旧的 validation AUC 早停，改为监控 validation loss。早停同时支持逐轮显著上升和抗噪声滑动趋势：连续 8 轮没有实质改善、窗口后半段平均 loss 比前半段至少高 `0.001`、且当前 loss 明显差于历史最佳时才停止。单次小幅上升不会触发早停。每轮记录当前/下一轮学习率、`validation_loss_best`、`validation_loss_bad_streak`、`validation_loss_rise_streak`、`validation_loss_trend_delta` 和 `stop_reason`，便于人工判断是否真的过拟合。

已有 checkpoint 可以单独执行运行时门禁，不需要重新训练：

```powershell
uv run python scripts\validate_mefkt_checkpoint.py `
  --profile full `
  --data-root runtime_logs\slam_en_es\prepared_full `
  --checkpoint runtime_logs\slam_en_es\output_full\best.pt `
  --output runtime_logs\slam_en_es\output_full\runtime_validation_cuda.json `
  --cpu-threads 2 --sequence-length 96 --max-gpu-memory-gb 8 `
  --require-gpu
```

输出目录包括：

```text
best.pt
last.pt
item_vocab.json
subject_vocab.json
skill_vocab.json
runtime_validation.json
```

`runtime_validation.json` 会记录参数量、CPU 推理、CUDA 是否可用，以及 CUDA 可用时的峰值显存。没有 CUDA 时 `gpu_passed` 为 `null`，不会伪造 GPU 通过结果。

## 公开跨领域数据准备

一条命令下载、转换并生成内容向量：

```powershell
Set-Location .\backend
pwsh -NoProfile -File .\scripts\prepare_mefkt_public_data.ps1
```

默认输出到 `backend/runtime_data/mefkt-public`。数据构成为：

| 数据源 | 领域 | 学习者 | 交互 | 稳定题目/题型 |
|---|---|---:|---:|---:|
| `bihungba1101/slam-en-es-knowledge-tracing` | 英语-西班牙语学习 | 2,593 | 1,054,368（全切分） | 16,983（全切分） |
| `Atomi/ASSISTments2009` | 数学 | 4,148 | 274,331 | 187 |
| 混合训练集 | 语言 + 数学 | 6,741 | 1,098,343 | 14,732 |

SLAM 提供真实相对时间和真实答题耗时；ASSISTments 派生 Parquet 只提供有序交互，没有时间戳和真实耗时，因此转换器明确使用 5 分钟顺序步长和 10 秒中性默认值。模型的真实耗时规律主要由 SLAM 学习。

SLAM 仓库标记为 `license:other`，ASSISTments 派生仓库未声明 license tag。它们适合当前研发验证，但在发布、商用或向第三方分发数据/权重前，必须再次核对两个原始数据源的许可证和引用要求。

本机最终验证结果（固定 seed，CPU 2 线程）如下：

| 训练对象 | 规模 | 轮数 | validation AUC | test AUC | 运行验证 |
|---|---:|---:|---:|---:|---|
| SLAM Lite + 内容 | 512 用户 | 3 | 0.7903 | 0.7782 | 通过，1,144,737 参数 |
| SLAM Lite 无内容 ablation | 512 用户 | 3 | 0.7845 | 0.7737 | 通过 |
| SLAM Full + 内容 | 256 用户 | 1 | 0.7594 | 0.7388 | 通过，15,217,921 参数 |
| 混合 Lite + 内容 | 全量 1,098,343 交互 | 1 | 0.7843 | 0.7785 | 通过，1,160,433 参数 |
| Full CUDA smoke | 64 用户，1,175 条测试交互 | 1 | 0.7172 | 0.7301 | 通过，15,217,921 参数，GPU 门禁通过 |

这些是训练链路和架构有效性的本机基线，不是最终模型成绩。Full 只跑了 1 轮，最终质量必须以集群多轮训练、完整课程留出和业务回放为准。

## 集群续训规划（2026-08-30）

训练数据采用稳定学习者切分：80% train、10% validation、10% test。validation 只用于每 epoch 早停和选择 `best.pt`，test 不参与梯度和早停，只在每 epoch 做旁路报告并作为最终比较依据。

首轮 Full 训练已经完成到 epoch 12，validation AUC 为 0.80645、test AUC 为 0.80107。当前续训从 `last.pt` 恢复，目标总 epoch 为 1000；恢复时会先重新评估当前 checkpoint，建立 validation loss 基线，不会把旧版本缺失的 loss 字段当作 0。

当前集群盘点显示 `advisor-rhw` 配额和队列满足 2 卡提交：GPU 节点 `g5/g6` 各有 8 卡，盘点时全局剩余约 3 卡；`advisor-rhw-gpu` 为 Open，capability 为 16 GPU。正式配置为：

| 项目 | 初始规划 | 调整依据 |
|---|---:|---|
| 模型 | `full` | 目标是 GPU 推理模型 |
| 最大 epoch | 1000 | 从已完成的 epoch 12 续训，最多再运行 988 轮 |
| validation loss 早停 | 8 轮趋势窗口 | 后半窗口均值至少高 0.001，且当前值明显差于最佳值；避免单次噪声触发 |
| validation AUC 早停 | 关闭 | AUC 只用于保存最佳 checkpoint 和报告 |
| sequence length | 200 | 保留较长学习轨迹 |
| window context | 64 | 跨窗口恢复历史状态 |
| per-worker batch size | 256 | 2 卡时实际 global batch 为 512，比首轮 128/卡更激进 |
| DataLoader workers | 每 Pod 4 | 由 CPU quota 和数据 PVC 吞吐确认 |
| AMP | 开启 | CUDA bfloat16 混合精度 |
| GPU 数量 | 2 张 | 每 Pod 申请 1 卡，使用 Volcano gang scheduling |
| CPU / 内存 | 每 Pod request 6 CPU/32Gi，limit 14 CPU/48Gi | 总 request 12 CPU/64Gi，低于 namespace 配额 |
| 预计续训时间 | 约 4–6 小时 | 以首轮约 15.9 秒/epoch 为基线，batch 变化和队列等待会造成浮动 |

提交命令复用 `advisor-rhw/mefkt-code`、`advisor-rhw/mefkt-data`，从 `/workspace/models/qintsg-train-20260825-034241/last.pt` 恢复，数据复用 `/data/qintsg-train-20260825-034241/`，避免重新上传和重新预处理。正式作业名称为 `qintsg-train-{yyyyMMdd-HHmmss}`，输出和日志写入 Code PVC，预处理缓存写入 Data PVC。训练开始后重点观察 `train.log`、`training_metrics.csv` 和 `validation_loss_rise_streak`；若出现 `stop_reason=validation_loss_rising`，应保留 `best.pt`，不要用最后一轮权重覆盖部署模型。

prd 集群会自动为 Pod 注入 `bbt-ca-inject` init container。提交器会先确认当前 namespace 存在公共 `ConfigMap/bbt-root-ca`，缺失时从 `Kubernetes-bbt/resources/root_ca.crt` 创建 `roots.pem` 与 `bbt-root-ca.crt` 两个键，否则 worker 会因 `FailedMount` 停在 `PodInitializing`。该对象是公开信任锚，不是 Secret；创建与查询仍必须经过 BBT-7 日志包装器。

## 新课程小规模校准

新课程可以先零样本直接使用。积累少量带标签交互后，可冻结基础模型，仅拟合温度和偏置两个参数：

```powershell
uv run python scripts\evaluate_mefkt_unseen_course.py `
  --profile lite `
  --data-root runtime_data\mefkt-public\mixed\prepared_lite `
  --checkpoint models\MEFKT\mefkt_lite_mixed\best.pt `
  --events-file runtime_data\new-course\events.csv `
  --content-embeddings-file runtime_data\new-course\item_content_embeddings.npz `
  --predictions-output runtime_data\new-course\base_predictions.csv

uv run python scripts\fit_mefkt_course_adapter.py `
  --predictions-file runtime_data\new-course\base_predictions.csv `
  --output runtime_data\new-course\course_adapter.json `
  --course-id new-course
```

本机用“仅在语言数据上训练的 Lite → 全新数学课程”验证了该流程：12,093 条交互按学习者切分后，适配器只有 2 个参数，验证 Brier 从 0.1907 降到 0.1852、ECE 从 0.0719 降到 0.0235。校准不会改变 AUC，也不能凭空补回基础模型未学到的排序能力；交互不足时应保持基础模型回退。

## EdNet 训练

```powershell
uv run python scripts\mefkt_train.py `
  --profile full `
  --dataset ednet-kt1 `
  --data-root runtime_data\ednet-kt1 `
  --output-dir models\MEFKT\mefkt_v3 `
  --epochs 12 --batch-size 128 --sequence-length 200 `
  --window-context-length 64 --num-workers 4 --amp
```

小规模试跑可以设置 `--max-users` 或 `--max-interactions`。数据缓存会记录 preprocessing version 和窗口参数，参数变化时不会误复用旧缓存。

## Rancher/Kubernetes

先在本地只渲染最终混合训练清单，不访问集群：

```powershell
pwsh -NoProfile -File .\backend\scripts\submit_mefkt_training.ps1 `
  -Namespace advisor-rhw `
  -Queue advisor-rhw-gpu `
  -Profile full -Dataset canonical-csv -GpuCount 2 -Amp `
  -EventsFile .\backend\runtime_data\mefkt-public\mixed\canonical\train.csv `
  -ContentEmbeddingsFile .\backend\runtime_data\mefkt-public\mixed\item_content_embeddings.npz `
  -UploadData -RenderOnly
```

确认清单后移除 `-RenderOnly`，可选增加 `-FollowLogs`，才会创建 PVC、上传数据和提交训练。提交器使用 Volcano gang scheduling，Job 名称为 `qintsg-train-{yyyyMMdd-HHmmss}`；`GpuCount=N` 创建 N 个 worker，每个 Pod 申请 1 张 NVIDIA GPU。代码/模型使用 `nfs-client`，训练数据和预处理缓存使用 `juicefs-sc`，并挂载内存 `/dev/shm`。

脚本会通过 BBT 日志包装器执行所有真实 Kubernetes 命令，并写入 `Kubernetes-bbt/k8s_operation_logs/YYYY-MM-DD.log`。`-RenderOnly` 不访问集群，因此不产生集群操作日志。

### 4090D 正式长训结果（2026-08-25）

首轮正式训练已改用 `g4` 的 `NVIDIA GeForce RTX 4090 D` 共享节点完成：

| 项目 | 实际值 |
|---|---|
| Job | `advisor-rhw/qintsg-train-20260825-034241` |
| 分布式规模 | 2 个 worker，均在 `g4`，每个 1 个共享 GPU 配额 |
| 抢占策略 | `chenny-dist-no-preempt`，`Never` |
| 训练配置 | Full、12 epochs、batch 128/worker、sequence 200、AMP |
| 参数量 | 15,268,737 |
| 最终 validation / test AUC | 0.80645 / 0.80107 |
| 最终 validation / test ACC | 0.77486 / 0.77426 |
| 运行时门禁 | CPU/GPU 均通过；GPU 峰值显存约 0.443GiB |

Job 已 `Completed`，两个 worker 退出码均为 0。模型、日志和曲线数据保存在 `mefkt-code` PVC 的 `/workspace/models/qintsg-train-20260825-034241/`，完整集群操作日志位于 `Kubernetes-bbt/k8s_operation_logs/2026-08-25.log`。

### 激进续训结果（2026-08-30）

续训 Job `advisor-rhw/qintsg-train-20260830-005859` 从 epoch 12 恢复，使用 2 个 RTX 5090 worker、每 worker batch 256，实际完成到 epoch 75。训练集 loss 持续下降，但 validation loss 在 epoch 19 达到最佳约 0.468426 后持续恶化，epoch 75 达到 0.772121；validation AUC 从 0.808322 的峰值下降到 0.732496，属于明确过拟合。因此停止 Job，保留 `best.pt` 和 `last.pt`，部署建议使用 epoch 23 的 `best.pt`，而不是 epoch 75 的 `last.pt`。

本次 Job 使用的是旧版逐轮 rise streak 逻辑，导致带小波动的上升趋势没有及时触发。当前本机训练器已经改为 8 轮滑动趋势早停：回放本次曲线会在 epoch 30 自动停止；新训练包已包含该逻辑、独立评估模块和公共 CA ConfigMap 自动准备逻辑。完整结果、checkpoint SHA-256 和运行时门禁记录在 `runtime_logs/mefkt_cluster_20260825/training_summary.json`。

## 质量门槛

- `MEFKT-Lite` 默认参数上限为 5M；
- `MEFKT` 默认参数上限为 50M，当前混合词表约 15.27M 参数；
- CUDA 可用时 runtime validation 会检查推理峰值显存是否不超过 8GiB；
- 长训早停监控 validation loss 的连续明显上升；validation AUC 仍用于选择 `best.pt`，最终部署仍需比较 AUC、ACC、Brier、ECE、多数类 baseline 和真实业务回放；
- Full/Lite 的未知题目输入、内容向量输入和相邻窗口 `SequenceState` 传递均有本机回归验证；
- 当前 Windows 项目环境已通过 `pytorch-cu130` 锁定 CUDA Torch，并已完成 Full checkpoint 的 8 GiB GPU 峰值门禁与 CUDA 训练 smoke；本次集群最终权重也已通过同一运行时门禁；
- 公开数据许可证未完成发布级法律核对，当前产物仅作为研发训练准备。

## MEFKT v3（2026-09-08）

统一训练器默认使用 `--architecture-version 3`。v3 增加显式 IRT 能力—难度分解、按知识点寻址的 skill memory、在线正确率/尝试次数/同 skill 间隔/session 连续状态、学科校准和训练期题目 ID dropout；旧 checkpoint 会从 metadata 恢复 v2 配置，不会被错误加载为 v3。

默认训练参数：

```text
epochs=250
learning_rate=6e-5
lr_scheduler=warmup-piecewise
warmup_epochs=3
high_lr_epochs=15
mid_lr_epochs=20
middle_learning_rate=3e-5
min_learning_rate=1e-5
subject_balance_alpha=0.5
validation_loss_patience=12
validation_loss_min_delta=2e-4
validation_loss_plateau_patience=60
```

本机同配置短程消融显示，v3 第 3 轮 validation loss `0.50880`，低于 v2 的 `0.51408`；v3 峰值升到 `1e-4` 后会产生明显校准震荡，因此集群正式训练必须使用当前 `6e-5` 默认值。Full v3 约 15.60M 参数，Lite v3 约 0.26M 参数。
