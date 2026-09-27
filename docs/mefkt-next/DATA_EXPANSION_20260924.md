# MEFKT-NG 公开数据扩充与第二次训练

## 数据来源与边界

新运行只使用真实公开作答记录，保留已有 SLAM Spanish-English 和 ASSISTments 2009 输入，并增加两个独立来源：

| 来源 | 原始发布 | 许可证 | 本次接入 |
| --- | --- | --- | --- |
| EdNet-KT1 | [Riiid 官方仓库](https://github.com/riiid/ednet) 中的 KT1 与 Contents | CC BY-NC 4.0，仅非商业研究使用 | 按学习者 SHA-256 哈希取约 1/64，保留完整入选者序列；用官方正确答案与作答比对得到标签，用官方 tags 作知识点。题目原文未发布，冻结内容向量只编码 part、bundle 与标签等静态元数据。 |
| Junyi Academy v9 | [Junyi 官方 Kaggle 数据集](https://www.kaggle.com/datasets/junyiacademy/learning-activity-public-dataset-by-junyi-academy) | CC BY-NC-SA 4.0，需署名并遵守非商业、相同方式共享条件 | 按学习者 SHA-256 哈希取约 1/10，保留完整入选者序列；以练习 `ucid` 为稳定题目与知识点，使用官方中文练习名称、难度与层级元数据。未使用 `Info_UserData.csv`。 |

Junyi 的时间戳精度为 15 分钟。同一学习者同一时间槽的作答统一作为一个场次，模型在场次结束前不能吸收其中任何答案。两个时间槽共 406 条记录超过 200 题窗口，无法在不引入标签泄漏的情况下拆分，因此仅排除这两个时间槽；其余记录保留。相关过滤数量和输入哈希见本地 `backend/runtime_logs/mefkt_expansion_20260924/canonical/train_v2.manifest.json`。初次候选 `train.csv` 保留作转换审计，不作为训练输入。

## 冻结输入

本次正式输入为 `backend/runtime_logs/mefkt_expansion_20260924/canonical/train_v2.csv` 和 `backend/runtime_logs/mefkt_expansion_20260924/item_content_embeddings_v2.npz`。前者 SHA-256 为 `347cf1087d996b3c4bf30ca9d0be1893cca404d76834e416ffce1a3e47c28469`，后者为 `9ad1b4e52969bbdce5496015e564b20eab67f672d41f0949b60d06841cf3a3dd`。原始 ZIP 保存在同级 `raw/`，未纳入 Git，也不随模型发布。

全量流式审计结果见 `canonical/train_v2.audit.json`：4,209,110 条有效作答、26,286 名学习者、28,248 个稳定题目；最大场次 150 题。训练、验证、测试按学习者稳定哈希切分，分别为 3,387,661、444,757、376,692 条；四个学科来源都有独立的验证与测试指标。

| 学科来源 | 作答条数 | 正确率 |
| --- | ---: | ---: |
| SLAM Spanish-English | 824,012 | 0.7223 |
| ASSISTments 2009 math | 274,331 | 0.6616 |
| EdNet English | 1,548,687 | 0.6525 |
| Junyi math | 1,562,080 | 0.7042 |

转换器是 `backend/scripts/prepare_mefkt_expanded_data.py`；审计器是 `backend/scripts/validate_mefkt_expanded_data.py`。内容向量由同一冻结多语言 MiniLM 编码器产生，原有 14,732 个题目向量直接复用，新数据增加 13,516 个。所有编码文本都是静态题目或练习元数据，不使用当前或未来的作答结果。

## 后续训练

新运行使用独立的作业名、输入目录、预处理目录和结果目录，从首轮运行按既定验证 NLL 规则选出的 epoch 133 checkpoint **只迁移可训练参数**，为新题目和知识点重新构建冻结目录与图缓冲区，并从零建立优化器。首轮运行的所有 epoch 指标、两个 rank 的步骤日志、验证预测、checkpoint 与测试预测保持原样。新运行继续逐步、逐轮记录 loss、AUC、Brier、ECE 等指标，逐轮保存验证预测和 checkpoint；每轮训练集逐题预测仍按用户先前选择不保存。

2026-09-24 已提交 prd `advisor-rhw` 中的 Volcano Job `mefkt-ng-20260924-4src-g4`，两个 worker 在 g4 共享 GPU 上启动，最多 120 epochs，单 GPU batch 128、隐藏维度 1024。新运行结果写入 `/results/mefkt-ng-runs/mefkt-ng-20260924-4src-g4/`，预处理数据写入 `/results/mefkt-ng-prepared/mefkt-ng-20260924-4src-g4/`。首次运行选定的初始 checkpoint SHA-256 是 `f29efed8df16ad7b0e0abc49de41ebb4fc341b40975bdbe13e85ee7b3b8927c4`；新运行 `run_config.json` 已记录来源 run、epoch、哈希以及 5,393,411 个迁移参数。提交前 50 GiB 结果 PVC 估算剩余 36.88 GiB；新运行 120 个 checkpoint 的保守预算约 20.1 GB。训练完成前最终测试集保持封存。

训练完成前不应将两个数据分布的总体 AUC 直接比较。应优先比较共同的 SLAM 与 ASSISTments 分学科指标，并单独检查 EdNet 与 Junyi 的冷启动、校准和时间泛化表现。
