<!--
MEFKT-NG 在 prd 集群的提交、调度修订与运行记录
@Project : adaptive-edu
@File : K8S_PRD_SUBMISSION_20260924.md
@Author : Qintsg
@Date : 2026-09-24
-->

# MEFKT-NG 的 prd 提交与运行记录

> 状态：**prd 训练已完成。** 三份 PVC Bound、数据 SHA-256 校验通过；同名 Volcano Job 经 CPU 配额修订后重建，两个 g4 worker 均 `Succeeded`、零重启。最终完成 153 个 epoch，并已对选定 checkpoint 评价测试集。完整指标与留存核对见 [训练结果](TRAINING_RESULT_20260924.md)。

## 本次选择

用户选择 g4 的 2 个 4090D SHARED GPU 资源位。最初按[g4 初版清单](k8s/prd-20260924-g4-initial.yaml)创建 Job；因 CPU 不足而持续 Pending，随后只删除这个未启动的 Job，并用[仅 Job 修订文件](k8s/prd-20260924-g4-job-cpu1.yaml)重建为每 worker `1/4 CPU`。当前运行中的 Job 对应 [CPU 配额修订版](k8s/prd-20260924-g4.yaml)，命名空间 `advisor-rhw`，队列 `advisor-rhw-gpu`，优先级 `gpu-job-high`，`minAvailable=2`。保留 [5090 候选清单](k8s/prd-20260924-5090.yaml)作为后备，本次未使用。

完整清单各有五个 YAML 文档：代码 PVC、原始数据 PVC、结果 PVC、CPU 上传 Pod、Volcano GPU Job。作业 `RunId` 与名称相同；上传脚本通过 Kubernetes-bbt 的脱敏日志包装器执行。清单不含 kubeconfig、token 或 Secret。

## 初次提交与调度阻塞

1. 经 [集群操作日志](E:/Projects/BBT/Kubernetes-bbt/k8s_operation_logs/2026-09-24.log)记录的服务端 dry-run 在将上传 Pod CPU limit 调为 `400m` 后全部通过。
2. `mefkt-code` 10 Gi NFS、`mefkt-data` 100 Gi JuiceFS、`mefkt-ng-results` 50 Gi NFS 均已创建并确认 Bound。临时 CPU 上传 Pod 校验了本地 CSV/NPZ 与远端的 SHA-256，一切完成后创建 Job，并已清理上传 Pod。
3. Job 创建后，最近一次成功读取显示两个 worker 均 Pending。Volcano 事件指出 g4 64 CPU 中已有 `61690m` 被申请；原版两个 worker 每个请求 2 CPU，gang 作业无法同时调度。g4 另有 32 个共享 GPU 资源位中的 29 个已被申请。
4. 本地修订将每 worker CPU request/limit 从 `2/8` 改为 `1/4`，保留 2 GPU、batch、镜像、PVC、数据与训练参数。此修订尚未写入集群；两次服务端 dry-run 均被 Rancher API 的 OpenAPI/Job GET 超时及 EOF 阻断，并非返回新的清单准入错误。随后一次只读 Job 查询也因同一 API 故障超时。
5. 在 API 状态恢复并重新确认原 Job 仍 Pending 前，不能安全删除或重建它。当前 PVC、上传的数据和旧 Job 均保留；本记录不声称训练已开始或修订已生效。
6. **2026-09-24 11:09–11:11（Asia/Shanghai）复查**：通过 BBT-7 包装器分别查询同一 Job 和其 worker Pod，均由 Rancher API 返回 `context deadline exceeded` 与前序 EOF；两条失败及完整输出已写入当日操作日志。这次没有取得实时 Job/Pod 状态，也没有执行任何写入；最近一次成功观测到的 Pending 状态不代表当前状态。

## API 恢复、重建与训练核对

1. Rancher API 恢复后，所有检查和写入继续通过 BBT-7 日志包装器。只读确认原 Job 和两个 worker 仍 Pending，实际 CPU request/limit 为 `2/8`；g4 当前 64 CPU 中已有 `61690m` 被申请，无法同时容纳两名各申请 2 CPU 的 worker。
2. 对已有 Job 的 `1/4` CPU 修订做服务端 dry-run 时，Volcano admission webhook 明确拒绝就地更改任务容器模板。此前的 Rancher 超时与这次明确的不可变字段拒绝已分别写入操作日志。
3. 再次只读确认 Job 与两名 worker 均未开始训练后，仅删除本次 Job；确认 Job 和 worker 均已退出。三份 PVC、代码就绪标记、原始 CSV/NPZ 和 NFS 结果目录没有删除。
4. [仅 Job 修订文件](k8s/prd-20260924-g4-job-cpu1.yaml)在创建状态下通过服务端 dry-run，随后重建同名 Job。新 Job UID 为 `de24c0e6-7912-45c2-a471-0154e465c64d`，模板和两名实际 worker 均为每人 `1 CPU request / 4 CPU limit / 1 GPU`。两名 worker 都在 g4 Running/Ready、零重启。
5. 两个 rank 的逐步 JSONL 持续增加。第 1 轮完整验证集 NLL `0.533149`、AUC `0.723611`；最新一次核对的第 7 轮验证 NLL `0.525578`、AUC `0.735494`。每轮 checkpoint 与验证预测已在 NFS 结果目录写盘；第 1 轮 checkpoint 约 85 MiB，验证预测 gzip 约 3.3 MiB。尚未执行最终测试集评价。
6. 生效的 Job 修订清单已另存到结果目录 `job_manifest_revision_cpu1.yaml`，SHA-256 为 `38dba2303a4f36ea6b350f82b6dd5319e2e0ec12c4f6c28028b8e70bf7bb9235`；初次提交的完整清单也继续保留，便于核对变更。
7. Job 后续完成到 epoch 153；经只读挂载结果 PVC 核对，153 轮指标、153 份 checkpoint、153 份验证预测以及两个 rank 各 5,355 行逐步日志均在。最终测试 AUC `0.774543`，结果 PVC 仍 Bound。监测自动化已暂停。

## prd 只读盘点

使用仓库的 [集群盘点脚本](../../backend/scripts/inspect_mefkt_cluster.ps1) 和 [BBT-7 日志包装器](E:/Projects/BBT/Kubernetes-bbt/scheduling/bbt-7/Invoke-BBT7LoggedKubectl.ps1)完成，原始摘要保存在本机 [盘点 JSON](../../backend/runtime_logs/mefkt_ng_prd_inventory_20260924.json)。所有远端读取均写入 [2026-09-24 操作日志](E:/Projects/BBT/Kubernetes-bbt/k8s_operation_logs/2026-09-24.log)；没有读取 kubeconfig 凭据正文。

| 项目 | 盘点结果 | 对提交的含义 |
| --- | --- | --- |
| g4 | Ready；`NVIDIA-GeForce-RTX-4090-D-SHARED`；32 个虚拟 GPU 资源位中，运行中 Pod 请求 29 个 | 盘点时数字上还有 3 个申请位，2 位作业仍须通过 Volcano 实时调度 |
| g5 / g6 | Ready；均为 5090；各 8/8 个 GPU 已有运行中申请 | 5090 备选作业此刻可能排队 |
| 队列 | `advisor-rhw-gpu` 与父队列 `gpu-pool` 均为 Open，capability 均为 16 GPU | Open 不保证立即获取 GPU |
| 4090D 节点标签 | g4 存在，但未标 `node-type=gpu` | 必须用 `-NodeName g4` 对应 hostname selector |
| 优先级 | `gpu-job-high` 已存在 | 符合 [集群管理办法](E:/Projects/BBT/Kubernetes-bbt/集群管理办法.md) 的 GPU 作业约定 |
| 目标 namespace | `advisor-rhw` 有创建 Pod、Volcano Job、PVC 的权限 | 资源配额仍须满足 |
| 提交前已有 PVC | 仅 DevPod 的一个 10 Gi NFS PVC；训练 PVC 均未创建 | 首次提交已经创建三份训练 PVC 并上传输入 |

当前快照只统计运行中 Pod 的 GPU requests；正在排队或刚刚变化的工作负载可能影响实际调度。g4 使用共享 GPU 资源位，2 位申请不等于独占两张物理显卡，也不预先保证吞吐。

## 存储与配额

依照 `Kubernetes-bbt/集群管理办法.md` 的存储规则，把小文件 checkpoint 与随机读数据放 NFS，原始较大输入放 JuiceFS：

| PVC | StorageClass | 申请容量 | 用途 |
| --- | --- | ---: | --- |
| `mefkt-code` | `nfs-client` | 10 Gi | Python 训练代码 |
| `mefkt-data` | `juicefs-sc` | 100 Gi | 原始 canonical CSV 与内容向量 NPZ |
| `mefkt-ng-results` | `nfs-client` | 50 Gi | 预处理缓存、每步指标、验证预测、每轮 checkpoint 与日志 |

提交前目标命名空间总 storage request 为 10 Gi，硬上限 200 Gi。三份申请合计 160 Gi，已创建并 Bound 后预计 **170 / 200 Gi**；NFS 预计 70 / 200 Gi，JuiceFS 预计 100 / 500 Gi。代码 PVC 与结果 PVC 均支持两 worker 的 ReadWriteMany 挂载。运行时 `disk_budget.json` 估计全部 200 轮 checkpoint 约 **25.54 GiB**，低于结果 PVC 的 50 Gi；这个估计不包含全部验证预测、日志与其他增长项，需在训练过程中继续观察实际占用。

初版训练 Job 两个 worker 共申请 4 CPU / 32 Gi 内存、limit 16 CPU / 128 Gi 内存，因此持续 Pending。当前重建的 Job 已生效为每 worker 1 CPU request / 4 CPU limit，即合计 2 CPU request / 8 CPU limit。内存仍为每 worker 16 Gi request / 64 Gi limit，均低于 namespace 配额。CPU 上传 Pod 为短时任务，申请 100m / 256Mi、limit 400m / 1Gi，符合单容器 4 倍上限；上传结束后已由脚本删除。

## 训练配置与数据身份

- 阶段 B 的 MEFKT-NG，无图谱 sidecar；题目内容向量仍进入静态表示。
- 2 个 worker，每 worker 1 个 g4 GPU 资源位，batch 128，长度 200，历史上下文 64，隐藏维度 1024，bfloat16 AMP。
- 最大 200 个 epoch，默认学习率 `1e-4`，验证 NLL 连续 20 轮无有效改善时早停。
- 当前 1024 维无图模型有 5,393,411 个可训练参数。已开始 GPU 训练并记录逐轮验证指标；最终性能仍待训练结束及独立测试集评价。
- 事件文件：`backend/runtime_logs/mefkt_mixed/canonical/train.csv`，SHA-256 `df5e26b62520d378c9e925f04d80c55c2fed1fc756c02ae312f006d18cdd9490`。
- 内容向量：`backend/runtime_logs/mefkt_mixed/item_content_embeddings.npz`，SHA-256 `9ecfd79930c8602fd9aeb19a4db33c6415f435eda75a35f039a8c8841086021f`。
- 本地预处理已覆盖 1,098,343 条事件；目标事件 train / validation / test 为 878,210 / 109,552 / 110,581。结果输出到 `mefkt-ng-results` 的 `/results/mefkt-ng-runs/mefkt-ng-20260924-g4/`，训练输入与处理缓存分别在 `/data/mefkt-ng-inputs/` 和 `/results/mefkt-ng-prepared/`。

指标留存与续训语义详见 [训练准备说明](TRAINING_PREPARATION.md)。每轮保留 checkpoint、完整训练/验证指标和逐题验证预测；每步指标持续追加。按约定不保存每轮训练集逐题预测。测试集只在最终选定 checkpoint 后评价。

## 实际提交的执行顺序

1. 通过 BBT-7 包装器只读复查 g4、队列、配额和三份 PVC；同名 Job 存在时拒绝覆盖。
2. 使用带操作日志的 `kubectl apply` 创建缺少的三份 PVC。
3. 创建一个只申请 CPU 的 BusyBox 上传 Pod，挂载三份 PVC。先上传完整作业清单、全部 Python 模块、CSV 和 NPZ，再核对数据 SHA-256。
4. 上传完整且验证通过后，写入代码就绪标记，再创建 Volcano GPU Job。即使 Job 因 GPU 忙碌而排队，也已经具备启动所需文件。
5. 只读查询 Job 已创建；最后通过带日志的 `kubectl delete` 清理临时上传 Pod。PVC、训练结果与 Job 日志保留。

[提交脚本](../../backend/scripts/render_mefkt_ng_job.ps1) 已在用户明确授权下执行 `-Submit -UploadData`。实际影响范围仅为 `advisor-rhw` 下的 3 个保留的 PVC、已清理的临时 CPU Pod 和 1 个 `Completed` 的 Volcano Job `mefkt-ng-20260924-g4`；未修改其他 namespace、现有 DevPod 或旧模型产物。CPU 修订已通过创建状态的服务端 dry-run 并实际生效。完成后的只读审计 Pod 也已清理。所有真实集群操作及失败尝试均有当日完整脱敏日志。
