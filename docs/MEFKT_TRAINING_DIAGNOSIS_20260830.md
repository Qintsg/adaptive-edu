# MEFKT 训练诊断与下一轮方案

## 结论

当前模型不是“完全欠拟合”。推荐使用 `best.pt`，不要使用第 75 轮的 `last.pt`：

- 最佳 validation loss：约 `0.4684`（第 19 轮）。
- 最佳 validation AUC：约 `0.8083`（第 23 轮）。
- 对应 test AUC：约 `0.8033`。
- validation 正例率约 `0.7083`；固定预测正例率的 BCE 基线约 `0.6036`。
- 最佳 validation loss 比固定先验低约 `21.9%`。

第 23 轮以后，训练 loss 继续下降，但 validation loss 和 AUC 持续恶化。第 75 轮已经达到 train loss `0.2495`、validation loss `0.7721`、validation AUC `0.7325`，这是明显过拟合。旧训练一直使用 `3e-4` 学习率且没有 plateau 调度，导致模型在泛化平台期后继续拟合训练窗口。

## 因果性检查

使用真实 validation batch 对当前位置做了敏感性测试：

- 翻转当前位置 `correct`，当前位置 logit 最大绝对变化：`0.0`。
- 将当前位置 `response_time` 放大约十倍，当前位置 logit 最大绝对变化：`0.0`。

因此当前 forward 路径满足“先用历史状态预测当前题，再吸收当前答案和耗时更新状态”的因果语义，没有发现当前标签或当前答题耗时泄漏。

## 分学科结果

| 数据切分 | 学科 | 样本数 | loss | AUC | 固定先验 BCE | 相对基线改善 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| validation | SLAM Spanish-English | 80,336 | 0.4564 | 0.8174 | 0.5907 | 22.7% |
| validation | ASSISTments 2009 Mathematics | 22,427 | 0.5239 | 0.7727 | 0.6422 | 18.4% |
| test | SLAM Spanish-English | 81,806 | 0.4575 | 0.8138 | 0.5861 | 21.9% |
| test | ASSISTments 2009 Mathematics | 26,404 | 0.5268 | 0.7670 | 0.6388 | 17.5% |

数学域是当前主要弱项，但 test 与 validation 的差距不大；优先方向是降低题目 ID 记忆、改善训练优化和增加跨课程评估，而不是单纯增加 epoch。

## 已实现的训练改动

下一次从头训练时，训练器默认使用：

- 初始学习率 `1e-4`。
- AdamW weight decay `5e-4`。
- Full 模型 dropout `0.20`。
- `ReduceLROnPlateau`：validation loss 连续若干轮没有改善后，将学习率乘以 `0.3`，最低 `1e-5`。
- 已有的 validation loss 趋势早停：连续明显恶化达到 8 轮或滑动趋势确认后停止。
- checkpoint 内保存 scheduler 状态，支持安全续训。
- 同时保存 `best_auc.pt` 和 `best_loss.pt`；兼容别名 `best.pt` 仍指向 AUC 最优版本。

`none` 和 `cosine` 仍可通过参数选择；默认 `plateau` 更适合当前已观察到的验证集平台期。

## 推荐的集群运行参数

这是一轮新的 baseline v2，使用新的输出目录，不覆盖旧结果：

```powershell
& .\backend\scripts\submit_mefkt_training.ps1 `
  -Kubeconfig C:\Users\qintsg\.kube\prd.yaml `
  -Namespace advisor-rhw `
  -GpuCount 2 `
  -Profile full `
  -Epochs 1000 `
  -BatchSize 256 `
  -SequenceLength 200 `
  -MinSequenceLength 20 `
  -LearningRate 0.0001 `
  -WeightDecay 0.0005 `
  -LrScheduler plateau `
  -LrSchedulerFactor 0.3 `
  -LrSchedulerPatience 3 `
  -MinLearningRate 0.00001 `
  -ValidationLossPatience 8 `
  -ValidationLossMinDelta 0.001 `
  -Amp `
  -RemoteDataRoot /data/qintsg-train-20260825-034241 `
  -RemoteEventsFile /data/qintsg-train-20260825-034241/train.csv `
  -RemoteContentEmbeddingsFile /data/qintsg-train-20260825-034241/item_content_embeddings.npz `
  -JobName qintsg-train-20260830-mefkt-v2
```

建议仍申请 2 张 GPU、每 worker batch `256`。`1000` 只是硬上限，预期有效训练区间约为 20–80 轮；真正决定停止的是 validation loss 趋势，而不是跑满 1000 轮。

训练完成后应重点比较：overall validation/test AUC、两个学科的 AUC/loss、Brier/ECE、最佳轮数、最终学习率以及是否触发早停。用下面的脚本可以复核 checkpoint 和输出分学科诊断：

```powershell
uv run --project . python .\backend\scripts\diagnose_mefkt_checkpoint.py `
  --profile full `
  --data-root .\backend\runtime_logs\<prepared-data-root> `
  --checkpoint .\backend\runtime_logs\<run-output>\best.pt `
  --device cuda `
  --output .\backend\runtime_logs\<run-output>\diagnosis.json
```

## 暂不处理的事项

当前结果足以支持下一轮优化训练，但要把“新课程无需重新训练”做得可靠，还应在后续实验中增加：

1. 完全留出一个课程的跨课程测试，而不仅是学习者级 80/10/10 切分。
2. 新课程题目的外部 subject/skill 元数据输入，避免开放世界题目只能依赖内容向量和默认未知类别。
3. 题目 ID dropout 或降低 ID embedding 维度的对照实验，确认模型是否过度依赖已见题目。
