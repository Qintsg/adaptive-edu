<#
文件内容描述：通过 Rancher/Kubernetes + Volcano 提交 MEFKT-Lite 多 GPU 训练任务。
@Project : adaptive-edu
@File : submit_mefkt_training.ps1
@Author : Qintsg
@Date : 2026-08-24

说明：
1. 本脚本只在用户明确执行时访问集群；本次开发验证不会调用它。
2. 训练代码通过 nfs-client PVC 上传，EdNet 缓存通过 juicefs-sc PVC 保存。
3. 每个 Volcano worker Pod 申请 1 张 NVIDIA GPU，Pod 数量就是 GPU 数量。
#>

[CmdletBinding()]
param(
    [string]$Namespace = "advisor-qintsg",
    [string]$Queue = "advisor-qintsg-gpu",
    [int]$GpuCount = 2,
    [string]$KubernetesRoot = "E:\Projects\BBT\Kubernetes-bbt",
    [string]$Kubeconfig = "$env:USERPROFILE\.kube\prd.yaml",
    [string]$Image = "nvcr.io/nvidia/pytorch:26.04-py3",
    [ValidateSet("full", "lite")]
    [string]$Profile = "full",
    [string]$CodePvcName = "mefkt-code",
    [string]$DataPvcName = "mefkt-data",
    [string]$CodeStorageSize = "10Gi",
    [string]$DataStorageSize = "300Gi",
    [int]$Epochs = 12,
    [int]$BatchSize = 128,
    [int]$SequenceLength = 200,
    [int]$MinSequenceLength = 20,
    [int]$NumWorkers = 4,
    [int]$MaxUsers = 0,
    [int]$MaxInteractions = 0,
    [switch]$Amp,
    [switch]$FollowLogs,
    [switch]$RenderOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()

if ($GpuCount -lt 1) {
    throw "GpuCount 必须至少为 1。"
}
if ($Epochs -lt 1 -or $BatchSize -lt 1 -or $SequenceLength -lt 2 -or $MinSequenceLength -lt 2) {
    throw "Epochs、BatchSize、SequenceLength 和 MinSequenceLength 必须为有效正数。"
}
if ($MinSequenceLength -gt $SequenceLength) {
    throw "MinSequenceLength 不能大于 SequenceLength。"
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$KubernetesRoot = (Resolve-Path $KubernetesRoot).Path
$LoggedKubectl = Join-Path $KubernetesRoot "scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1"
$DataScript = Join-Path $ScriptRoot "mefkt_lite_data.py"
$DataCoreScript = Join-Path $ScriptRoot "mefkt_data_core.py"
$ModelScript = Join-Path $ScriptRoot "mefkt_models.py"
$TrainScript = Join-Path $ScriptRoot "mefkt_train.py"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$JobName = "qintsg-train-$RunStamp"
$OutputDir = "/workspace/models/$JobName"
$PvcManifestPath = Join-Path $env:TEMP "$JobName-pvc.yaml"
$JobManifestPath = Join-Path $env:TEMP "$JobName-job.yaml"

foreach ($path in @($LoggedKubectl, $DataScript, $DataCoreScript, $ModelScript, $TrainScript)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "找不到必需文件：$path"
    }
}

function Invoke-LoggedKubectl {
    <#
    通过 BBT 日志包装器执行一条 Kubernetes 命令。

    :param Reason: 脱敏操作日志中的操作原因。
    :param KubectlArgs: 传给 kubectl 的参数数组。
    :returns: kubectl 标准输出。
    #>
    param(
        [Parameter(Mandatory)]
        [string]$Reason,
        [Parameter(Mandatory)]
        [string[]]$KubectlArgs
    )
    & $LoggedKubectl -Reason $Reason -Kubeconfig $Kubeconfig -KubectlArgs $KubectlArgs
}

function Ensure-Pvc {
    <#
    确保存储 PVC 存在；已存在的 PVC 直接复用。

    :param Name: PVC 名称。
    :param StorageClass: StorageClass 名称。
    :param Size: PVC 请求容量。
    #>
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$StorageClass,
        [Parameter(Mandatory)]
        [string]$Size
    )
    $existing = (Invoke-LoggedKubectl "检查 PVC $Name 是否已存在" @(
            "get", "pvc", $Name, "--namespace", $Namespace,
            "--ignore-not-found", "--output", "name"
        ) | Out-String).Trim()
    if ($existing) {
        Write-Host "复用 PVC：$Namespace/$Name"
        return
    }
    Write-Host "创建 PVC：$Namespace/$Name storageClass=$StorageClass size=$Size"
    $manifest = @"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $Name
  namespace: $Namespace
  labels:
    app.kubernetes.io/part-of: adaptive-edu
    app.kubernetes.io/name: mefkt-lite
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: $StorageClass
  resources:
    requests:
      storage: $Size
"@
    [System.IO.File]::WriteAllText($PvcManifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))
    Invoke-LoggedKubectl "创建 MEFKT 训练 PVC $Name" @(
        "apply", "--namespace", $Namespace, "--filename", $PvcManifestPath
    ) | Out-Host
}

function New-TrainingManifest {
    <#
    生成 Volcano Job 清单。

    :returns: 可提交的 Volcano Job YAML 文本。
    #>
    $ampArgument = if ($Amp) { "--amp" } else { "" }
    $command = @'
set -euo pipefail
until test -s /workspace/jobs/mefkt_lite_data.py && test -s /workspace/jobs/mefkt_data_core.py && test -s /workspace/jobs/mefkt_models.py && test -s /workspace/jobs/mefkt_train.py && test -f __READY_FILE__; do
  sleep 5
done
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export MASTER_ADDR="${VC_WORKER_HOSTS%%,*}"
export MASTER_PORT=23456
export WORLD_SIZE="${VC_WORKER_NUM}"
export RANK="${VK_TASK_INDEX}"
export LOCAL_RANK=0
exec torchrun \
  --nnodes="${WORLD_SIZE}" \
  --node_rank="${RANK}" \
  --nproc_per_node=1 \
  --master_addr="${MASTER_ADDR}" \
  --master_port="${MASTER_PORT}" \
  /workspace/jobs/mefkt_train.py \
  --profile __PROFILE__ \
  --dataset ednet-kt1 \
  --data-root __DATA_ROOT__ \
  --output-dir __OUTPUT_DIR__ \
  --epochs __EPOCHS__ \
  --batch-size __BATCH_SIZE__ \
  --sequence-length __SEQUENCE_LENGTH__ \
  --min-sequence-length __MIN_SEQUENCE_LENGTH__ \
  --num-workers __NUM_WORKERS__ \
  --max-users __MAX_USERS__ \
  --max-interactions __MAX_INTERACTIONS__ \
  --cpu-threads 2 __AMP_ARGUMENT__
'@
    foreach ($pair in @(
            @("__DATA_ROOT__", "/data/ednet-kt1"),
            @("__OUTPUT_DIR__", $OutputDir),
            @("__READY_FILE__", "/workspace/jobs/.ready-$JobName"),
            @("__PROFILE__", $Profile),
            @("__EPOCHS__", $Epochs),
            @("__BATCH_SIZE__", $BatchSize),
            @("__SEQUENCE_LENGTH__", $SequenceLength),
            @("__MIN_SEQUENCE_LENGTH__", $MinSequenceLength),
            @("__NUM_WORKERS__", $NumWorkers),
            @("__MAX_USERS__", $MaxUsers),
            @("__MAX_INTERACTIONS__", $MaxInteractions),
            @("__AMP_ARGUMENT__", $ampArgument)
        )) {
        $command = $command.Replace([string]$pair[0], [string]$pair[1])
    }
    return @"
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata:
  name: $JobName
  namespace: $Namespace
  labels:
    app.kubernetes.io/part-of: adaptive-edu
    app.kubernetes.io/name: mefkt-lite
    adaptive-edu/run: $JobName
spec:
  schedulerName: volcano
  queue: $Queue
  priorityClassName: gpu-job-high
  minAvailable: $GpuCount
  maxRetry: 2
  plugins:
    svc:
      - --publish-not-ready-addresses=true
  policies:
    - event: PodEvicted
      action: RestartJob
  tasks:
    - name: worker
      replicas: $GpuCount
      template:
        metadata:
          labels:
            app.kubernetes.io/part-of: adaptive-edu
            app.kubernetes.io/name: mefkt-lite
        spec:
          nodeSelector:
            node-type: gpu
          restartPolicy: OnFailure
          containers:
            - name: trainer
              image: $Image
              imagePullPolicy: IfNotPresent
              workingDir: /workspace/jobs
              command:
                - bash
                - -lc
              args:
                - |
$($command -replace '(?m)^', '                  ')
              env:
                - name: PYTHONUNBUFFERED
                  value: "1"
                - name: PYTORCH_CUDA_ALLOC_CONF
                  value: expandable_segments:True
              ports:
                - name: torchrun
                  containerPort: 23456
                  protocol: TCP
              resources:
                requests:
                  nvidia.com/gpu: "1"
                  cpu: "8"
                  memory: 32Gi
                limits:
                  nvidia.com/gpu: "1"
                  cpu: "16"
                  memory: 48Gi
              volumeMounts:
                - name: code
                  mountPath: /workspace
                - name: data
                  mountPath: /data
                - name: dshm
                  mountPath: /dev/shm
          volumes:
            - name: code
              persistentVolumeClaim:
                claimName: $CodePvcName
            - name: data
              persistentVolumeClaim:
                claimName: $DataPvcName
            - name: dshm
              emptyDir:
                medium: Memory
"@
}

if ($RenderOnly) {
    # 本地只渲染清单，便于在不访问集群时检查多卡参数和挂载关系。
    New-TrainingManifest
    return
}

try {
    $jobExists = (Invoke-LoggedKubectl "检查训练 Job $JobName 是否已存在" @(
            "get", "job", $JobName, "--namespace", $Namespace,
            "--ignore-not-found", "--output", "name"
        ) | Out-String).Trim()
    if ($jobExists) {
        throw "训练 Job 已存在，为避免覆盖请更换时间戳后重试：$Namespace/$JobName"
    }

    Ensure-Pvc -Name $CodePvcName -StorageClass "nfs-client" -Size $CodeStorageSize
    Ensure-Pvc -Name $DataPvcName -StorageClass "juicefs-sc" -Size $DataStorageSize

    $jobManifest = New-TrainingManifest
    [System.IO.File]::WriteAllText($JobManifestPath, $jobManifest, [System.Text.UTF8Encoding]::new($false))
    Invoke-LoggedKubectl "提交 Volcano MEFKT 多 GPU Job $JobName" @(
        "apply", "--namespace", $Namespace, "--filename", $JobManifestPath
    ) | Out-Host

    $podName = $null
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        $podName = (Invoke-LoggedKubectl "查找训练 Job $JobName 的 Pod（第 $attempt 次）" @(
                "get", "pods", "--namespace", $Namespace,
                "--selector", "volcano.sh/job-name=$JobName",
                "--output", "jsonpath={.items[0].metadata.name}"
            ) | Out-String).Trim()
        if ($podName) { break }
        Start-Sleep -Seconds 5
    }
    if (-not $podName) {
        throw "等待训练 Pod 超时：$Namespace/$JobName"
    }
    Invoke-LoggedKubectl "等待训练 Job $JobName 的全部 worker Pod Ready" @(
        "wait", "--namespace", $Namespace, "--for=condition=Ready",
        "pod", "--selector", "volcano.sh/job-name=$JobName", "--timeout=20m"
    ) | Out-Host

    Invoke-LoggedKubectl "上传 MEFKT 数据脚本到 $JobName" @(
        "cp", $DataScript, "$Namespace/${podName}:/workspace/jobs/.mefkt_lite_data.py.uploading"
    ) | Out-Host
    Invoke-LoggedKubectl "上传 MEFKT 数据核心模块到 $JobName" @(
        "cp", $DataCoreScript, "$Namespace/${podName}:/workspace/jobs/.mefkt_data_core.py.uploading"
    ) | Out-Host
    Invoke-LoggedKubectl "上传 MEFKT 模型模块到 $JobName" @(
        "cp", $ModelScript, "$Namespace/${podName}:/workspace/jobs/.mefkt_models.py.uploading"
    ) | Out-Host
    Invoke-LoggedKubectl "上传 MEFKT 训练入口到 $JobName" @(
        "cp", $TrainScript, "$Namespace/${podName}:/workspace/jobs/.mefkt_train.py.uploading"
    ) | Out-Host
    Invoke-LoggedKubectl "原子发布 MEFKT 训练脚本到共享 PVC" @(
        "exec", "--namespace", $Namespace, $podName, "--", "bash", "-lc",
        "mv /workspace/jobs/.mefkt_lite_data.py.uploading /workspace/jobs/mefkt_lite_data.py && mv /workspace/jobs/.mefkt_data_core.py.uploading /workspace/jobs/mefkt_data_core.py && mv /workspace/jobs/.mefkt_models.py.uploading /workspace/jobs/mefkt_models.py && mv /workspace/jobs/.mefkt_train.py.uploading /workspace/jobs/mefkt_train.py && touch /workspace/jobs/.ready-$JobName"
    ) | Out-Host

    Write-Host "训练已启动：Job=$Namespace/$JobName"
    Write-Host "Pod 名称由 Volcano 生成（通常为 ${JobName}-worker-0 等）"
    Write-Host "模型输出：PVC=$CodePvcName path=$OutputDir"
    Write-Host "查看状态：kubectl --kubeconfig `"$Kubeconfig`" get vcjob,pod -n $Namespace -l volcano.sh/job-name=$JobName"
    if ($FollowLogs) {
        Invoke-LoggedKubectl "跟随 rank 0 训练日志 $JobName" @(
            "logs", "--namespace", $Namespace, $podName, "--follow", "--container", "trainer"
        ) | Out-Host
    }
} finally {
    foreach ($temporaryPath in @($PvcManifestPath, $JobManifestPath)) {
        if ($temporaryPath -and (Test-Path -LiteralPath $temporaryPath)) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}
