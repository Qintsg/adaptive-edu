<!--
MEFKT-NG 模型替换前本地交接记录
@Project : adaptive-edu
@File : MODEL_REPLACEMENT_PREPARATION_20260924.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 本地归档与替换准备

归档位于 `C:\Users\qintsg\Desktop\MEFKT-NG-20260924-archive\`。`process_data/` 含两来源首训与四来源训练/续训的逐步、逐轮指标、验证和测试预测、日志、配置、源码快照、冻结输入、预处理数组及文件级 SHA-256 清单；不含逐轮 checkpoint、RNG 或 Torch 缓存。`model_bundle/` 含选定 epoch 136 的纯权重 `model.safetensors`、目录映射、原模型结构源码和独立加载器。该权重来自 SHA-256 为 `861aca24ccc2a13f2211377c17b16a99f7e64fa2febf6ec161a9585819d99b0b` 的选定 checkpoint，导出权重 SHA-256 为 `d13aad408cf233f967eff02439109b62c8ff154bd6567e6ef5df4fc14cfc8cd9`，23 个张量逐项相等。桌面归档通过了文件数量、全部文件哈希、输入与运行配置摘要、预测数量、模型加载和 CPU 前向核验。

过拟合诊断位于 `process_data/analysis/overfitting_report.md`，曲线为 `nll_auc_curves.png`：没有明显的后期过拟合，主要是收益趋于平台。选定 epoch 136 的训练/验证 NLL 为 `0.555042/0.565196`，差值约 `0.010154`；训练到 epoch 156 时为 `0.554917/0.565153`，验证损失未持续回升。同集测试从第 120 轮版本的 AUC `0.714934` 到续训版本的 `0.715220`，提升很小且不构成新的独立泛化证据。

现有在线加载入口是 `backend/ai_services/services/mefkt/loader.py` 和 `legacy_runtime.py`，默认文件为 `backend/models/MEFKT/mefkt_model.pt`。当前加载器用 `torch.load` 读取旧版格式，并构造 `MEFKTSequenceModel` 或旧题目级融合状态；新模型是 `backend/scripts/mefkt_ng/model.py` 的 `MEFKTNG`，需从 safetensors 加载参数和冻结目录。不能把新权重直接覆盖旧 `.pt`。替换前至少需要：

1. 增加 MEFKT-NG 独立推理适配器，按模型的 `items/correct/gaps/time_known/episodes/valid` 语义构造因果序列；保持旧接口响应及统计回退。
2. 为项目真实课程构建稳定的题目和知识点映射、384 维内容向量以及测验场次边界；新课程的冻结编码器需与训练时的多语言 MiniLM 一致。
3. 在真实课程独立学习者或未来时间段上验证 AUC、NLL、Brier、ECE、分课程表现和冷启动；不要用已经查看过的公开测试集作为上线验收。
4. 完成灰度加载与快速回滚；在通过前保留现有 MEFKT `.pt` 和元数据不变。

两份新增公开训练数据分别受 EdNet CC BY-NC 4.0 与 Junyi CC BY-NC-SA 4.0 约束；在考虑商用或公开分发模型权重前，应单独核对许可。当前交接只准备本地模型包，未切换任何在线配置。

归档完整性确认后，已删除 `advisor-rhw` 中的 `mefkt-code`、`mefkt-data`、`mefkt-ng-results` 三个专用 PVC 和已完成的续训 Volcano Job；原有 `devpod` PVC 未触动，namespace 申请存储量从 170 GiB 降至 10 GiB。两块 NFS PV 已回收，`mefkt-data` 对应的 JuiceFS PV 使用 `Retain` 回收策略，仍为 `Released`，未清理 PV 或底层数据。远端 Kubernetes 操作均经 BBT-7 包装器写入 2026-09-24 操作日志。

2026-09-25 后端已加入默认 MEFKT-NG 加载和课程推理适配，旧版可显式回滚；实现范围、测试与尚未完成的业务效果验收见[后端适配记录](BACKEND_NG_ADAPTER_20260925.md)。此处前文是归档时点的状态记录。
