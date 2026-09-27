<!--
MEFKT-NG 阶段 B 在 prd 的首次正式训练结果
@Project : adaptive-edu
@File : TRAINING_RESULT_20260924.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 阶段 B 首次正式训练结果

> 状态：2026-09-24，`advisor-rhw/mefkt-ng-20260924-g4` 已 `Completed`。两个 g4 worker 均 `Succeeded`、重启数为 0。任务使用 2 个 4090D SHARED GPU 资源位；最终测试结果来自**训练器选定的第 133 轮 checkpoint**。线上 KT 未切换到该模型。

## 最终结果

| 指标 | 选定 checkpoint 的验证集 | 最终测试集 |
| --- | ---: | ---: |
| checkpoint epoch | 133 | 使用 epoch 133 |
| 样本数 | 109,552 | 110,581 |
| NLL | 0.494840 | 0.496230 |
| ROC-AUC | 0.775578 | 0.774543 |
| Brier | 0.164212 | 0.165104 |
| ECE | 0.009544 | 0.006414 |

测试集分领域结果：

| 领域 | 样本数 | NLL | ROC-AUC |
| --- | ---: | ---: | ---: |
| SLAM 西英语言 | 82,239 | 0.471536 | 0.791588 |
| ASSISTments 2009 数学 | 28,342 | 0.567886 | 0.717857 |

训练在第 **153** 轮停止，未跑满 200 轮。`epoch_metrics.jsonl`、worker 日志和训练脚本表明停止条件为验证 NLL 的早停耐心；没有 worker 失败、OOM 或重启。以上数值是该混合公开数据的结果，不能直接等同本项目“大数据技术与应用”课程的实际学习效果，也不能与切分或输入不同的旧 MEFKT 结果直接比较。

## 模型选择口径

训练器使用 `min_delta=0.0002` 判断验证 NLL 是否构成一次**足够大的改善**，并据此更新 `best_nll.json` 和早停状态。因此选定的是：

```text
checkpoints/epoch_0133_0b6d2f5c54044fb8961b8b501142096a.pt
SHA-256 f29efed8df16ad7b0e0abc49de41ebb4fc341b40975bdbe13e85ee7b3b8927c4
```

查看全部 153 个 epoch 的 rank 0 日志后，**原始验证 NLL 最低点和 AUC 最高点均在 epoch 153**：NLL `0.494669`、AUC `0.775813`。两者比 epoch 133 略好，但 NLL 改善未越过最近一次选点所要求的 `min_delta`，所以训练器没有改变选定 checkpoint。epoch 153 的 checkpoint 和验证预测均完整保留；**它未进行本次最终测试集评价**，不能把 epoch 133 的测试指标贴到 epoch 153 上。

如以后需要选择精确最低 NLL，应先明确新的选择规则，并仅根据验证集与已有完整轨迹选定权重，再单独评价；保留本次原始最终摘要和测试结果，不覆盖或混合不同选择策略的指标。

## 数据和产物留存

结果 PVC `advisor-rhw/mefkt-ng-results` 为 `nfs-client`、50 GiB，任务结束后仍为 `Bound`。通过临时**只读**审计 Pod 从 `/results/mefkt-ng-runs/mefkt-ng-20260924-g4/` 核对：

| 产物 | 核对结果 |
| --- | ---: |
| `epoch_metrics.jsonl` | 153 行 |
| `steps/rank_000_*.jsonl` | 5,355 行 |
| `steps/rank_001_*.jsonl` | 5,355 行 |
| `checkpoints/epoch_*.pt` | 153 份 |
| `predictions/validation_epoch_*.csv.gz` | 153 份 |
| `predictions/test_final_*.csv.gz` | 1 份 |
| `training_source.zip` | 存在 |
| `final_summary_epoch_0153.json` | 存在，内容已与 worker 最终日志核对 |
| 结果目录总用量 | 约 13.06 GiB |

训练脚本保留了每步 loss、AUC、Brier、ECE 等批次指标，每轮完整训练/验证指标与逐题验证预测，以及每轮可恢复 checkpoint。按用户约定，没有导出每轮训练集逐题预测。原始输入的 SHA-256 和脚本源码快照包含在运行配置中，便于后续重算与分析。

最终测试逐题预测文件为 `predictions/test_final_epoch_0153.csv.gz`，SHA-256 `e1fe618edb23cd0b6ff94b20cf9341ca9158d508990435583087fc06e793540b`。权威结果是 NFS 上的 `final_summary_epoch_0153.json`；本机另存了可直接阅读的[摘要副本](../../backend/runtime_logs/mefkt_ng_final_summary_20260924.json)，不替代远端完整数据。

所有远端检查、Job 修订以及临时只读审计 Pod 的创建和清理都通过 BBT-7 日志包装器，记录在 [2026-09-24 Kubernetes 操作日志](E:/Projects/BBT/Kubernetes-bbt/k8s_operation_logs/2026-09-24.log)。临时审计 Pod 已确认不存在；三份训练 PVC 和全部结果保留。自动监测 `mefkt-ng-prd` 已在任务完成后暂停。
