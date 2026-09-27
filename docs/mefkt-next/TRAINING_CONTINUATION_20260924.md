<!--
MEFKT-NG 四来源训练同配置续训记录
@Project : adaptive-edu
@File : TRAINING_CONTINUATION_20260924.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 四来源训练续训记录

首段四来源训练已完成 120 轮，[结果记录](TRAINING_RESULT_4SRC_20260924.md)保存了最终测试与选定 checkpoint。用户要求继续训练后，先核验了原输入 CSV、384 维内容向量、八个训练源码文件与原运行配置的摘要全部一致；`latest.json` 指向完整的 epoch 120 checkpoint，SHA-256 为 `1cc29fa5669480f4d78f77e2d02cfb62c9f772b86c266cda4f943d97cf6edd17`。原结果 PVC 估算尚余 23.06 GiB，g4 有三个共享 GPU 申请位、CPU 申请量为 61.69/64 核，满足两个各申请一核 CPU、一个共享 GPU 的 worker。前 120 轮权威指标另存本地快照 `backend/runtime_logs/mefkt_expansion_20260924/epoch_metrics_through_0120.jsonl`，SHA-256 为 `719d815a62823b23b6e533be2d2ba29860d5d7bbdd53f1739ef467d418fede36`。

新 Volcano Job `advisor-rhw/mefkt-ng-20260924-4src-g4-r2` 于 2026-09-24 提交，使用 `-Resume` 和同一 `RunId=mefkt-ng-20260924-4src-g4`，从第 121 轮继续，目标上限第 160 轮。它恢复 epoch 120 的模型、AdamW、学习率调度器和双 rank RNG，保持原数据与源码、batch 128、序列 200、上下文 64、hidden 1024、原学习率配置和混合精度。实际恢复学习率约为 `3.125e-6`，早停仍按原来的 `patience=20` 工作，因此可能在第 160 轮之前结束。新段 ID 为 `77be5462f4aa4914b21e3f06f8102215`，指标和逐轮 checkpoint 只追加到原运行结果目录 `/results/mefkt-ng-runs/mefkt-ng-20260924-4src-g4/`；旧 `final_summary_epoch_0120.json` 和首段预测不覆盖。

启动核验时两个新 worker 均为 Ready/Running、零重启；第 121 轮已追加完整指标、双 rank 步骤日志、checkpoint 和验证预测。该轮验证 NLL `0.565458`、AUC `0.710001`，尚未刷新按 `min_delta` 选出的最佳 NLL；原 120 行指标前缀的 SHA-256 仍与冻结快照一致，原最终摘要仍存在。15 分钟定时监测已恢复。

第 120 轮前验证 NLL 已接近平台期，续训是有界的额外实验，不预设明显收益。独立测试集已在首段结束时查看；续训完成后的同集测试应标注为**复评**，不能再当成全新、未经观察的独立测试。若以后更改模型结构、数据或批量超参数，应建立新运行目录并单独保留轨迹。

## 最终结果

续训在第 156 轮触发 `validation_nll_patience` 早停，两个 worker 均正常完成、零重启。按原 `min_delta=0.0002` 规则选用 epoch 136 checkpoint，SHA-256 为 `861aca24ccc2a13f2211377c17b16a99f7e64fa2febf6ec161a9585819d99b0b`。训练学习率已降至原设定下限 `1e-6`，进一步沿用相同数据与超参数加轮次预计收益有限。

| 指标 | 首段 120 轮选定模型 | 续训 156 轮选定模型 |
| --- | ---: | ---: |
| 验证 NLL | 0.565409 | 0.565196 |
| 验证 AUC | 0.709947 | 0.710377 |
| 同集复评 NLL | 0.551933 | 0.551755 |
| 同集复评 AUC | 0.714934 | 0.715220 |
| 同集复评 Brier | 0.187041 | 0.186974 |
| 同集复评 ECE | 0.006123 | 0.005604 |

复评样本仍为 376,692 条。各来源的测试 AUC 变化为 SLAM `0.793516 → 0.793602`、ASSISTments `0.718383 → 0.718438`、EdNet `0.636821 → 0.637832`、Junyi `0.717637 → 0.717741`；改善幅度均较小。该测试集在续训前已经查看过，因此这些数值只能用于同集复核，不能据此声称新增独立泛化证据。

结果 PVC 上核对了 156 条逐轮指标、156 个 checkpoint、156 份验证预测、首段双 rank 各 18,000 条步骤日志与续训段双 rank 各 5,400 条步骤日志。前 120 行指标的 SHA-256 仍为 `719d815a62823b23b6e533be2d2ba29860d5d7bbdd53f1739ef467d418fede36`；`final_summary_epoch_0120.json` 和两次测试预测都保留。续训的 `final_summary_epoch_0156.json` SHA-256 为 `fb4842f1bf6f2ebed3070ec9ca5aebde299a2a812b7e615b6fe726eea01b5fbb`，本地副本位于 `backend/runtime_logs/mefkt_expansion_20260924/final_summary_epoch_0156.json`；156 轮指标本地副本 `epoch_metrics_through_0156.jsonl` 的 SHA-256 为 `4e8fda483d5b784faef000376d0c11329cf2b3be18d6c0a28f1031709f3ab6c9`。50 GiB 结果 PVC 审计时使用约 31.03 GiB，尚余约 18.97 GiB，数据和结果未清理。
