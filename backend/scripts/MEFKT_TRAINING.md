# MEFKT / MEFKT-Lite 训练说明

当前工程提供两个共享输入/输出 interface 的知识追踪模型：

| 模型 | 内部架构 | 目标运行环境 |
|---|---|---|
| `MEFKT` | 自适应遗忘 GRU + 6 层、8 头因果 Transformer + 64 个跨窗口 memory slots | 正常 GPU 推理，设计上限制单次推理显存不超过 8GiB |
| `MEFKT-Lite` | 自适应遗忘 GRU | 少于 4 核 CPU、无 GPU |

两个模型都由 [mefkt_models.py](./mefkt_models.py) 实现，由 [mefkt_train.py](./mefkt_train.py) 统一训练。

## 统一输入 interface

训练和线上历史编码均使用：

```text
items            [B, L] long       题目内部索引，-1 为 padding
correct          [B, L] long       0/1，当前交互是否答对
gaps             [B, L] float      距离上一次交互的小时数
response_times   [B, L] float      当前题目真实答题耗时，单位秒
```

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
  --data-root runtime_data\mixed `
  --output-dir models\MEFKT\mefkt_mixed_v3
```

真正的跨学科泛化还需要训练数据中包含多个 subject/domain；架构提供通用接口并不能让只在单一学科训练的模型自动学会另一门学科。建议后续混合 EdNet、ASSISTments、Junyi 等可合规公开数据，并统一 `subject_vocab`、`skill_vocab`。

未知题目会使用 OOV ID、未知 subject 和空 skill 表示，避免线上直接崩溃；但想让新题预测有质量，仍应提供题目的 subject、skill 和数值特征，不能只依赖 OOV。

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

```powershell
pwsh -NoProfile -File .\backend\scripts\submit_mefkt_training.ps1 `
  -Namespace advisor-qintsg `
  -Queue advisor-qintsg-gpu `
  -Profile full -GpuCount 2 -Amp -FollowLogs
```

提交器使用 Volcano gang scheduling，`GpuCount=N` 创建 N 个 worker，每个 Pod 申请 1 张 NVIDIA GPU；代码使用 `nfs-client`，EdNet 数据使用 `juicefs-sc`，并挂载内存 `/dev/shm`。执行前可以用 `-RenderOnly` 只渲染清单，不访问集群。

## 质量门槛

- `MEFKT-Lite` 默认参数上限为 5M；
- `MEFKT` 默认参数上限为 50M，当前约 14.9M 参数（13,000 道题规模）；
- CUDA 可用时 runtime validation 会检查推理峰值显存是否不超过 8GiB；
- 训练早停只看 validation AUC；最终部署仍需比较 AUC、ACC、Brier、ECE、多数类 baseline 和真实业务回放；
- EdNet 使用 CC BY-NC 4.0，混合其他数据集前需要逐一确认许可证。
