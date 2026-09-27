<!--
MEFKT-NG 四来源扩充训练结果
@Project : adaptive-edu
@File : TRAINING_RESULT_4SRC_20260924.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 四来源扩充训练结果

2026-09-24，prd `advisor-rhw` 的 Volcano Job `mefkt-ng-20260924-4src-g4` 在 g4 的两个共享 GPU worker 上完成 120 轮训练。两个 worker 均以 `Completed` 结束，重启次数为 0，没有 Warning 事件。新运行从首轮 `mefkt-ng-20260924-g4` 的 epoch 133 checkpoint 迁移 5,393,411 个可训练参数，重新构建新题目与知识点的冻结目录，并使用独立优化器及结果目录；旧运行产物未改动。完整来源与转换记录见[数据扩充记录](DATA_EXPANSION_20260924.md)。

按验证 NLL 的 `min_delta=0.0002` 规则，最终选用 epoch 118 checkpoint，SHA-256 为 `88244a6924c8cc04ffea4d910bb9c377518090c613475aa222bf9a04407aef3d`。epoch 119 原始 NLL 略低，但改善不足预设阈值，因此没有替换选定 checkpoint。独立测试集仅在选定 checkpoint 上评估一次。

| 切分 | 作答数 | NLL | AUC | Brier | ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| 验证 | 444,757 | 0.565409 | 0.709947 | 0.192590 | 0.002855 |
| 测试 | 376,692 | 0.551933 | 0.714934 | 0.187041 | 0.006123 |

测试集分来源结果：

| 来源 | 作答数 | NLL | AUC | Brier | ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| SLAM Spanish-English | 82,239 | 0.469882 | 0.793516 | 0.154864 | 0.005611 |
| ASSISTments 2009 math | 28,342 | 0.567801 | 0.718383 | 0.192778 | 0.022420 |
| EdNet English | 122,310 | 0.621263 | 0.636821 | 0.215993 | 0.008169 |
| Junyi math | 143,801 | 0.536763 | 0.717637 | 0.179688 | 0.006703 |

原有 SLAM 与 ASSISTments 的测试学习者和作答数保持不变，可以与首轮运行的对应分来源测试指标比较：SLAM AUC `0.791588 → 0.793516`，ASSISTments AUC `0.717857 → 0.718383`。四来源总体 AUC 与首轮两来源总体 AUC 的样本组成不同，不能直接作为模型退化或提升的证据。EdNet 未公开题目原文，模型只获得静态 part、bundle 和 tag 作为内容信息，这限制了该来源的语义泛化。

完整运行目录是 `/results/mefkt-ng-runs/mefkt-ng-20260924-4src-g4/`，预处理目录是 `/results/mefkt-ng-prepared/mefkt-ng-20260924-4src-g4/`，冻结输入目录是 `/data/mefkt-ng-inputs/mefkt-ng-20260924-4src-g4/`。结果 PVC 上已核对 120 条 `epoch_metrics.jsonl`、双 rank 各 18,000 条步骤记录、120 个逐轮 checkpoint、120 份验证预测、1 份最终测试预测、训练源码快照及 `provenance/` 中的数据转换源码与审计清单；没有保存每轮训练集逐题预测。审计时 50 GiB NFS 结果 PVC 使用约 26.94 GiB，尚余约 23.06 GiB，原始文件和结果均保留。

最终摘要是 `final_summary_epoch_0120.json`，本地核验副本位于 `backend/runtime_logs/mefkt_expansion_20260924/final_summary_epoch_0120.json`，SHA-256 为 `887644dbeb8a9ca49d0fbcf483c7d5c4704d9d4a9de60818b03fedbfce6e55a5`。checkpoint、测试预测的摘要与最终 summary 记录一致。所有集群读写均经 BBT-7 日志包装器记录到 `E:\Projects\BBT\Kubernetes-bbt\k8s_operation_logs\2026-09-24.log`。
