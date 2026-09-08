# MEFKT v2 训练结果

## 结论

MEFKT v2 已正常完成训练，并在第 356 轮触发 validation loss 趋势早停。相较旧版第 75 轮的 validation loss `0.7721`，v2 最终为 `0.4761`，没有出现同等程度的过拟合爆炸。最佳可部署版本应优先使用 AUC 最优 checkpoint；如果业务更重视概率损失，则使用 loss 最优 checkpoint。

## 最佳指标

| 选择标准 | epoch | validation loss | validation AUC | test loss | test AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| 最低 validation loss | 160 | 0.469604 | 0.807333 | 0.472513 | 0.802313 |
| 最高 validation AUC | 195 | 0.470262 | 0.807651 | 0.473048 | 0.802949 |

训练停止时（epoch 356）：

- train loss：`0.440866`
- validation loss：`0.476074`
- validation AUC：`0.803454`
- test loss：`0.478493`
- test AUC：`0.799329`
- 当前学习率：`1e-5`
- stop reason：`validation_loss_rising`
- validation loss trend delta：`0.001032`

## 训练策略效果

学习率经历了 `1e-4 → 3e-5 → 1e-5` 的 plateau 降速。第 30 轮以后 validation loss 大致稳定在 `0.470–0.473`，AUC 大致稳定在 `0.804–0.808`；后期只有缓慢恶化，因此比旧版更稳定。

但 v2 的最佳 AUC `0.807651` 略低于旧版最佳 AUC `0.808322`，最佳 loss `0.469604` 也略高于旧版 `0.468426`。这说明本轮正则化和低学习率主要解决了过拟合，尚未带来绝对精度提升；下一轮若继续优化，应增加跨课程留出评估和数学域针对性，而不是单纯延长 epoch。

## 运行门禁

- 参数量：`15,268,737`
- Full 模型运行时门禁：通过
- CPU 线程：2
- GPU：RTX 5090
- GPU 峰值显存：约 `0.504 GiB`
- 8 GiB 推理显存上限：通过
- Volcano Job：`advisor-rhw/qintsg-train-20260830-191917`
- 两个 worker：均正常退出，训练期间重启次数为 0

## 本地文件

- 指标：`backend/runtime_logs/mefkt_cluster_20260830_v2/training_metrics.csv`
- 完整指标：`backend/runtime_logs/mefkt_cluster_20260830_v2/training_metrics.jsonl`
- 训练日志：`backend/runtime_logs/mefkt_cluster_20260830_v2/train.log`
- 总曲线：`backend/runtime_logs/mefkt_cluster_20260830_v2/training_curves.png`
- 最近 20 轮曲线：`backend/runtime_logs/mefkt_cluster_20260830_v2/training_curves_recent20.png`
- 运行验证：`backend/runtime_logs/mefkt_cluster_20260830_v2/runtime_validation.json`

最终 checkpoint 原件仍保存在 `advisor-rhw/mefkt-code` PVC 的 `/workspace/models/qintsg-train-20260830-191917/`。远端 SHA-256：

```text
best.pt      4e73b127768638306c966b042b82738c8adf18b1c66fa34f7647d120e2d03c9a
best_auc.pt  64b949b221fc806a4cdcc39caff50b29b17f09f65292e99c5f681545219bcfed
best_loss.pt d1c84f2e0aaca3b6d777e2f556e856ef118c83a54ef0f2b7a612deb4e1d3caf5
last.pt      b81000744e4dc52043746b57c935c5b4f47a55eb777fb5a336ed1633f9b2d934
```

本次 Kubernetes 操作日志：

`E:\Projects\BBT\Kubernetes-bbt\k8s_operation_logs\2026-09-01.log`
