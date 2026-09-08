# MEFKT 长期训练 Kubernetes 环境

## 目的

MEFKT 长训固定使用独立的 `advisor-rhw` namespace，避免与其他课程、实验或临时 DevPod 混用。namespace、ResourceQuota、LimitRange 和 Volcano GPU Queue 均声明式维护；训练结束后只停止或删除 Job，namespace、PVC 和训练产物默认保留。

正式训练 Job 名称约定为：

```text
qintsg-train-{yyyyMMdd-HHmmss}
```

本文件主要记录长期环境；正式训练结果见文末“4090D 首次正式长训记录”。

## 已创建资源

创建时间：2026-08-25（Asia/Shanghai）。所有集群操作均通过 BBT-7 日志包装器执行，操作日志位于：

```text
E:\Projects\BBT\Kubernetes-bbt\k8s_operation_logs\2026-08-25.log
```

| 资源 | 名称 | 状态/用途 |
| --- | --- | --- |
| Namespace | `advisor-rhw` | `Active`，长期保留 |
| ResourceQuota | `ns-default-quota` | 标准 advisor 配额 |
| LimitRange | `ns-default-limits` | 标准 advisor 默认容器限制 |
| Volcano Queue | `advisor-rhw-gpu` | `Open`，父队列 `gpu-pool` |

创建和复核脚本为 [`provision_mefkt_namespace.ps1`](../backend/scripts/provision_mefkt_namespace.ps1)。脚本可以重复执行；它只更新上述四类资源，不删除其他资源。

## 配额和限制

配置参考现有标准 advisor namespace `advisor-sszzqin`，没有复制 Rancher 运行时生成的 project ID、UID 或状态 annotation。

ResourceQuota：

| 项目 | hard |
| --- | ---: |
| CPU request | 16 |
| 内存 request | 128Gi |
| CPU limit | 32 |
| 内存 limit | 256Gi |
| 总 storage request | 200Gi |
| `nfs-client` storage request | 200Gi |
| `juicefs-sc` storage request | 500Gi |
| Pod 数量 | 30 |
| Volcano Job 数量 | 20 |
| PVC 数量 | 15 |
| ConfigMap / Secret / Service | 50 / 30 / 5 |

LimitRange：

- 新容器默认 request：1 CPU、2Gi 内存。
- 新容器默认 limit：2 CPU、4Gi 内存。
- 单容器最大：32 CPU、256Gi 内存。
- 单容器最小：100m CPU、128Mi 内存。
- CPU 和内存的 limit/request 最大比例均为 4。
- PVC 单个容量范围：1Gi 到 200Gi。

训练提交器为每个 worker 设置 6 CPU / 32Gi request 和 14 CPU / 48Gi limit。2 GPU、2 个 worker 的合计为 12 CPU / 64Gi request 和 28 CPU / 96Gi limit；加上当前监视 DevPod 的 1 CPU / 2Gi request 和 2 CPU / 4Gi limit 后，总计为 13 CPU / 64Gi request 和 30 CPU / 100Gi limit，保留配额余量。

## GPU 队列

`advisor-rhw-gpu` 是 cluster-scoped Queue，不属于某个 namespace。当前配置：

```yaml
metadata:
  annotations:
    scheduling.volcano.sh/parent-queue: gpu-pool
spec:
  capability:
    nvidia.com/gpu: "16"
  reclaimable: true
  weight: 1
```

Queue 的 capability 是调度上限/能力声明，不代表当前已经预留 16 张卡。提交训练时仍需要根据当时 GPU 节点和等待队列状态决定使用 2 卡还是 4 卡。

## 持久化存储

训练提交器默认创建并复用以下 PVC：

| PVC | StorageClass | 默认容量 | 用途 |
| --- | --- | ---: | --- |
| `mefkt-code` | `nfs-client` | 10Gi | 训练代码、checkpoint、日志和曲线 |
| `mefkt-data` | `juicefs-sc` | 100Gi | 训练 CSV、内容向量和预处理缓存 |

数据 PVC 默认从 300Gi 调整为 100Gi，是为了满足标准 advisor namespace 的 200Gi 总 storage request 配额；当前 MEFKT 混合数据包约 36.7MiB，100Gi 有足够余量。PVC 不会因为 Volcano Job 结束而自动删除，除非明确执行删除操作。

## DevPod 人工监视方案

可以使用 DevPod，但 DevPod 不承载正式多 GPU 训练。正式训练仍运行在 Volcano Job 中，DevPod 只作为无 GPU 的交互式监视/调试终端。

集群当前有 Active 的 `devpod` namespace，且当前账号可以读取 Pod 日志。当前 `advisor-rhw` 内已有监视 DevPod `devpod-default-vs-b29a7`，运行在 `n5`，使用 Python 3.12 镜像和独立的 10Gi `nfs-client` PVC。该工作区 PVC 与训练提交器之后创建的 `mefkt-code` 不是同一个 PVC；如果要在 DevPod 中直接查看训练产物，需要在 DevPod 配置中额外挂载 `mefkt-code`，或使用本机 `kubectl logs` 监视训练 Pod。PVC 按 namespace 隔离，不能直接挂载其他 namespace 的 PVC。因此有两种监视方式：

1. 最简单：在本机使用 `kubectl logs --follow` 跟随训练 Pod 的 `trainer` 容器日志。
2. 更完整：使用当前 `advisor-rhw` 内的 DevPod，待训练提交器创建 `mefkt-code` 后，将该 PVC 作为额外挂载；在其中查看 `train.log`、`training_metrics.jsonl` / `.csv`，并运行 `mefkt_plot_training.py` 生成总曲线和最近 N 个 epoch 曲线。

监视 DevPod 应满足：

- 不申请 `nvidia.com/gpu`。
- CPU request 建议不超过 1，内存 request 建议不超过 2Gi。
- 只读挂载 `mefkt-code` 更安全；如果需要生成 PNG，挂载输出目录可写或将图输出到独立 PVC。
- 不要让 DevPod 成为训练进程的父进程，避免 DevPod 重启影响训练。

训练输出目录的主要文件：

```text
/workspace/models/<job_name>/train.log
/workspace/models/<job_name>/training_metrics.jsonl
/workspace/models/<job_name>/training_metrics.csv
/workspace/models/<job_name>/run_config.json
/workspace/models/<job_name>/checkpoints/
```

曲线脚本支持总曲线、最近 N 个 epoch 曲线和数值摘要：

```bash
python /workspace/jobs/mefkt_plot_training.py \
  --metrics /workspace/models/<job_name>/training_metrics.jsonl \
  --output-dir /workspace/models/<job_name>/plots \
  --recent-epochs 10
```

## 当前集群快照

盘点文件：[`mefkt_cluster_inventory_20260825-030447.json`](../backend/runtime_logs/mefkt_cluster_inventory_20260825-030447.json)。

本次快照显示：

- 调度目标 GPU 节点：`g5`、`g6`，均为 Ready，每节点 8 张 NVIDIA GPU，总计 16 张。
- `g5`、`g6` 的 GPU 型号标签均为 `NVIDIA-GeForce-RTX-5090`，显存标签为 `32607MiB`，可按约 32GiB/卡规划。
- `g5` 上当前已有 8 张 GPU request，`g6` 上当前已有 3 张 GPU request；快照时 g6 至少有 5 张未被 request 的 GPU，但实际可用性仍以提交时调度结果为准。
- `advisor-rhw-gpu` 状态为 `Open`。
- 新 namespace 当前只有 DevPod 监视工作区 PVC/Pod，尚无 MEFKT 训练 PVC 或 Volcano Job。
- 当前账号具备创建 Pod、PVC、Volcano Job 的 namespace 权限，以及读取节点、配额、LimitRange 和 Queue 的权限。

## 后续启动边界

namespace 环境已准备好，但正式长训仍需单独执行提交脚本并确认当时的 GPU 空闲情况。建议首轮使用 2 GPU：

```powershell
$kube = Join-Path $HOME '.kube\prd.yaml'
& .\backend\scripts\submit_mefkt_training.ps1 `
  -Namespace advisor-rhw `
  -Queue advisor-rhw-gpu `
  -GpuCount 2 `
  -Epochs 30 `
  -Patience 5 `
  -BatchSize 128 `
  -SequenceLength 200 `
  -WindowContextLength 64 `
  -NumWorkers 4 `
  -Amp `
  -UploadData `
  -EventsFile .\backend\runtime_logs\mefkt_mixed\canonical\train.csv `
  -ContentEmbeddingsFile .\backend\runtime_logs\mefkt_mixed\item_content_embeddings.npz `
  -Kubeconfig $kube `
  -FollowLogs
```

提交前应再次运行 `inspect_mefkt_cluster.ps1 -Namespace advisor-rhw`，并根据当时的 GPU 空闲数、Queue 等待情况和 PVC 状态决定是否启动。正式训练创建的 Job、Pod 和 PVC 仍应保留日志与 checkpoint，停止训练不等于删除 namespace。

## namespace 改名迁移

原 `advisor-bbtqintsg` namespace 在迁移期间曾存在 DevPod 工作区。Kubernetes 不支持 namespace 原地改名，因此最终使用新建的 `advisor-rhw` 环境。错误拼写的临时 namespace `advistor-rhw` 也已清理。

训练提交器和本文件默认均已切换到 `advisor-rhw`。旧 namespace 与错误拼写 namespace 清理前已复核没有训练 Pod、PVC 或 Volcano Job；正式环境中的 DevPod 监视工作区保留。

## 4090D 首次正式长训记录

2026-08-25 已使用 Rancher/Kubernetes 正式提交并完成首轮长训：

- Job：`advisor-rhw/qintsg-train-20260825-034241`
- 节点：`g4`，GPU 型号为 `NVIDIA GeForce RTX 4090 D`（共享 GPU 配额）
- 规模：2 个 Volcano worker，每个申请 1 个 `nvidia.com/gpu`；两个 worker 均固定在 `g4`
- 抢占策略：`chenny-dist-no-preempt`，`preemptionPolicy=Never`，不抢占其他应用
- 配置：Full、canonical 混合公开数据、12 epochs、batch size 128、sequence length 200、AMP
- 结果：Job `Completed`，两个 worker 退出码 0、重启 0；参数量 15,268,737
- 最终指标：validation AUC 0.80645、test AUC 0.80107、validation ACC 0.77486、test ACC 0.77426
- 运行时门禁：CPU/GPU 均通过；GPU 峰值显存约 0.443GiB，低于 8GiB 上限
- 产物目录：`mefkt-code` PVC 的 `/workspace/models/qintsg-train-20260825-034241/`
- 关键产物：`best.pt`、`last.pt`、`run_config.json`、`training_metrics.jsonl`、`training_metrics.csv`、`train.log`

完整 Kubernetes 操作记录仍位于：

```text
E:\Projects\BBT\Kubernetes-bbt\k8s_operation_logs\2026-08-25.log
```
