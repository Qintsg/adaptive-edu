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

# GPU Full；有 CUDA 时增加 --amp
uv run python scripts\mefkt_train.py `
  --profile full `
  --dataset synthetic `
  --data-root runtime_logs\mefkt_v3_data `
  --output-dir runtime_logs\mefkt_v3_output `
  --epochs 2 --batch-size 8 --sequence-length 48 `
  --window-context-length 16 --num-workers 0 --amp
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

这些是训练链路和架构有效性的本机基线，不是最终模型成绩。Full 只跑了 1 轮，最终质量必须以集群多轮训练、完整课程留出和业务回放为准。

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
  -Namespace advisor-qintsg `
  -Queue advisor-qintsg-gpu `
  -Profile full -Dataset canonical-csv -GpuCount 2 -Amp `
  -EventsFile .\backend\runtime_data\mefkt-public\mixed\canonical\train.csv `
  -ContentEmbeddingsFile .\backend\runtime_data\mefkt-public\mixed\item_content_embeddings.npz `
  -UploadData -RenderOnly
```

确认清单后移除 `-RenderOnly`，可选增加 `-FollowLogs`，才会创建 PVC、上传数据和提交训练。提交器使用 Volcano gang scheduling，Job 名称为 `qintsg-train-{yyyyMMdd-HHmmss}`；`GpuCount=N` 创建 N 个 worker，每个 Pod 申请 1 张 NVIDIA GPU。代码/模型使用 `nfs-client`，训练数据和预处理缓存使用 `juicefs-sc`，并挂载内存 `/dev/shm`。

脚本会通过 BBT 日志包装器执行所有真实 Kubernetes 命令，并写入 `Kubernetes-bbt/k8s_operation_logs/YYYY-MM-DD.log`。`-RenderOnly` 不访问集群，因此不产生集群操作日志。

## 质量门槛

- `MEFKT-Lite` 默认参数上限为 5M；
- `MEFKT` 默认参数上限为 50M，当前混合词表约 15.27M 参数；
- CUDA 可用时 runtime validation 会检查推理峰值显存是否不超过 8GiB；
- 训练早停只看 validation AUC；最终部署仍需比较 AUC、ACC、Brier、ECE、多数类 baseline 和真实业务回放；
- Full/Lite 的未知题目输入、内容向量输入和相邻窗口 `SequenceState` 传递均有本机回归验证；
- 当前本机没有 CUDA，因此 8GiB GPU 峰值门槛尚未实测，必须作为集群训练后的部署门禁；
- 公开数据许可证未完成发布级法律核对，当前产物仅作为研发训练准备。
