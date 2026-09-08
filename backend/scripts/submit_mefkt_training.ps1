<#
文件内容描述：通过 Rancher/Kubernetes + Volcano 提交 MEFKT 多 GPU 训练任务。
@Project : adaptive-edu
@File : submit_mefkt_training.ps1
@Author : Qintsg
@Date : 2026-08-25

说明：
1. 本脚本只在用户明确执行时访问集群；本次开发验证不会调用它。
2. 训练代码通过 nfs-client PVC 上传，训练数据和缓存通过 juicefs-sc PVC 保存。
3. 每个 Volcano worker Pod 申请 1 张 NVIDIA GPU，Pod 数量就是 GPU 数量。
4. canonical-csv 数据可以使用 -UploadData 上传训练 CSV 和内容向量 sidecar；不上传时复用 Data PVC 中已有文件。
#>

[CmdletBinding()]
param(
    [string]$Namespace = "advisor-rhw",
    [string]$Queue = "advisor-rhw-gpu",
    [int]$GpuCount = 2,
    [string]$KubernetesRoot = "E:\Projects\BBT\Kubernetes-bbt",
    [string]$Kubeconfig = "$env:USERPROFILE\.kube\prd.yaml",
    [string]$JobName = "",
    [switch]$ReuseExistingJob,
    [string]$Image = "nvcr.io/nvidia/pytorch:26.04-py3",
    [string]$NodeName = "",
    [string]$PriorityClassName = "chenny-dist-no-preempt",
    [ValidateSet("full", "lite")]
    [string]$Profile = "full",
    [ValidateSet(2, 3)]
    [int]$ArchitectureVersion = 3,
    [ValidateSet("canonical-csv", "ednet-kt1")]
    [string]$Dataset = "canonical-csv",
    [string]$CodePvcName = "mefkt-code",
    [string]$DataPvcName = "mefkt-data",
    [string]$CodeStorageSize = "10Gi",
    [string]$DataStorageSize = "100Gi",
    [int]$Epochs = 250,
    [int]$BatchSize = 256,
    [int]$SequenceLength = 200,
    [int]$MinSequenceLength = 20,
    [int]$NumWorkers = 4,
    [int]$MaxUsers = 0,
    [int]$MaxInteractions = 0,
    [int]$WindowContextLength = -1,
    [double]$LearningRate = 0.00006,
    [double]$WeightDecay = 0.0005,
    [ValidateSet("none", "plateau", "cosine", "warmup-piecewise")]
    [string]$LrScheduler = "warmup-piecewise",
    [double]$LrSchedulerFactor = 0.5,
    [int]$LrSchedulerPatience = 3,
    [double]$MinLearningRate = 0.00001,
    [int]$WarmupEpochs = 3,
    [int]$HighLrEpochs = 15,
    [int]$MidLrEpochs = 20,
    [double]$SubjectBalanceAlpha = 0.5,
    [int]$Patience = 0,
    [int]$ValidationLossPatience = 12,
    [double]$ValidationLossMinDelta = 0.0002,
    [int]$ValidationLossPlateauPatience = 60,
    [string]$EventsFile = "",
    [string]$ContentEmbeddingsFile = "",
    [string]$RemoteDataRoot = "",
    [string]$RemoteEventsFile = "",
    [string]$RemoteContentEmbeddingsFile = "",
    [string]$RemoteOutputDir = "",
    [switch]$UploadData,
    [switch]$ForcePreprocess,
    [switch]$Resume,
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
if ($LearningRate -le 0 -or $WeightDecay -lt 0 -or $LrSchedulerFactor -le 0 -or $LrSchedulerFactor -ge 1 -or $LrSchedulerPatience -lt 0 -or $MinLearningRate -lt 0 -or $WarmupEpochs -lt 0 -or $HighLrEpochs -lt $WarmupEpochs -or $MidLrEpochs -lt 0 -or $SubjectBalanceAlpha -lt 0 -or $SubjectBalanceAlpha -gt 1) {
    throw "学习率、权重衰减或调度器参数不合法。"
}
if ($Patience -lt 0 -or $ValidationLossPatience -lt 0 -or $ValidationLossMinDelta -lt 0 -or $ValidationLossPlateauPatience -lt 0) {
    throw "Patience、ValidationLossPatience 和 ValidationLossMinDelta 不能为负数。"
}
if ($NodeName -and $NodeName -notmatch '^[a-z0-9][a-z0-9.-]*$') {
    throw "NodeName 不是合法的 Kubernetes 节点名称：$NodeName"
}
if ($PriorityClassName -notmatch '^[a-z0-9][a-z0-9.-]*$') {
    throw "PriorityClassName 不是合法的 Kubernetes 资源名称：$PriorityClassName"
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$KubernetesRoot = (Resolve-Path $KubernetesRoot).Path
$EventsFile = if ($EventsFile) { $EventsFile } else { Join-Path $BackendRoot "runtime_logs\mefkt_mixed\canonical\train.csv" }
$ContentEmbeddingsFile = if ($ContentEmbeddingsFile) { $ContentEmbeddingsFile } else { Join-Path $BackendRoot "runtime_logs\mefkt_mixed\item_content_embeddings.npz" }
$LoggedKubectl = Join-Path $KubernetesRoot "scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1"
$RootCaFile = Join-Path $KubernetesRoot "resources\root_ca.crt"
$DataScript = Join-Path $ScriptRoot "mefkt_lite_data.py"
$DataCoreScript = Join-Path $ScriptRoot "mefkt_data_core.py"
$CanonicalDataScript = Join-Path $ScriptRoot "mefkt_canonical_data.py"
$EarlyStoppingScript = Join-Path $ScriptRoot "mefkt_early_stopping.py"
$EvaluationScript = Join-Path $ScriptRoot "mefkt_evaluation.py"
$OpenWorldScript = Join-Path $ScriptRoot "mefkt_open_world.py"
$EncoderScript = Join-Path $ScriptRoot "mefkt_encoders.py"
$ConfigScript = Join-Path $ScriptRoot "mefkt_model_config.py"
$ModelScript = Join-Path $ScriptRoot "mefkt_models.py"
$V3ModelScript = Join-Path $ScriptRoot "mefkt_v3_models.py"
$OptimizationScript = Join-Path $ScriptRoot "mefkt_optimization.py"
$ReportingScript = Join-Path $ScriptRoot "mefkt_reporting.py"
$PlotScript = Join-Path $ScriptRoot "mefkt_plot_training.py"
$TrainScript = Join-Path $ScriptRoot "mefkt_train.py"
$RuntimeScript = Join-Path $ScriptRoot "mefkt_runtime.py"
$TrainingArgsScript = Join-Path $ScriptRoot "mefkt_training_args.py"
$TrainingCoreScript = Join-Path $ScriptRoot "mefkt_training_core.py"
$TrainingRuntimeScript = Join-Path $ScriptRoot "mefkt_training_runtime.py"
$DiagnosisScript = Join-Path $ScriptRoot "diagnose_mefkt_checkpoint.py"
$ValidateScript = Join-Path $ScriptRoot "validate_mefkt_checkpoint.py"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$JobName = if ($JobName) { $JobName } else { "qintsg-train-$RunStamp" }
if ($JobName -notmatch '^[a-z0-9][a-z0-9.-]*$') {
    throw "JobName 不是合法的 Kubernetes 资源名称：$JobName"
}
$OutputDir = if ($RemoteOutputDir) { $RemoteOutputDir } else { "/workspace/models/$JobName" }
$RemoteDataRoot = if ($RemoteDataRoot) { $RemoteDataRoot } else { "/data/$JobName" }
$RemoteEventsFile = if ($RemoteEventsFile) { $RemoteEventsFile } else { "$RemoteDataRoot/train.csv" }
if (-not $RemoteContentEmbeddingsFile -and $UploadData) {
    $RemoteContentEmbeddingsFile = "$RemoteDataRoot/item_content_embeddings.npz"
}
$PvcManifestPath = Join-Path $env:TEMP "$JobName-pvc.yaml"
$JobManifestPath = Join-Path $env:TEMP "$JobName-job.yaml"

$DataFiles = @(
    $DataScript,
    $DataCoreScript,
    $CanonicalDataScript,
    $EarlyStoppingScript,
    $EvaluationScript,
    $OpenWorldScript,
    $EncoderScript,
    $ConfigScript,
    $ModelScript,
    $V3ModelScript,
    $OptimizationScript,
    $ReportingScript,
    $PlotScript,
    $TrainScript,
    $RuntimeScript,
    $TrainingArgsScript,
    $TrainingCoreScript,
    $TrainingRuntimeScript,
    $DiagnosisScript,
    $ValidateScript
)
foreach ($path in @($LoggedKubectl) + $DataFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "找不到必需文件：$path"
    }
}
if ($UploadData) {
    if ($Dataset -ne "canonical-csv") {
        throw "-UploadData 当前只支持 -Dataset canonical-csv。EdNet 请先准备到 Data PVC。"
    }
    foreach ($path in @($EventsFile, $ContentEmbeddingsFile)) {
        if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "-UploadData 需要存在的本地文件：$path"
        }
    }
}

function ConvertTo-BashLiteral {
    <#
    将 PowerShell 字符串安全嵌入 bash 单引号字符串。

    :param Value: 待嵌入的文本。
    :returns: bash 单引号字面量。
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    if ($Value.Contains("'")) {
        throw "训练路径不能包含单引号：$Value"
    }
    return "'" + $Value + "'"
}

foreach ($remotePath in @($RemoteDataRoot, $RemoteEventsFile, $RemoteContentEmbeddingsFile, $OutputDir)) {
    if ($remotePath -and $remotePath.Contains("'")) {
        throw "远程训练路径不能包含单引号：$remotePath"
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

function ConvertTo-KubectlLocalPath {
    <#
    将 Windows 本地路径转换为 kubectl cp 可识别的相对路径，避免盘符冒号被判定为远端路径。

    :param Path: 本地文件路径。
    :returns: 相对于当前工作目录的本地路径。
    #>
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "kubectl cp 本地文件不存在：$Path"
    }
    $relativePath = Resolve-Path -LiteralPath $Path -Relative
    return $relativePath.Replace('\', '/')
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
    app.kubernetes.io/name: mefkt
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

function Ensure-RootCaConfigMap {
    <#
    确保集群 CA 注入 webhook 引用的公共 ConfigMap 存在。

    :returns: None。
    #>
    $existing = (Invoke-LoggedKubectl "检查公共 CA ConfigMap bbt-root-ca 是否已存在" @(
            "get", "configmap", "bbt-root-ca", "--namespace", $Namespace,
            "--ignore-not-found", "--output", "name"
        ) | Out-String).Trim()
    if ($existing) {
        Write-Host "复用 ConfigMap：$Namespace/bbt-root-ca"
        return
    }
    if (-not (Test-Path -LiteralPath $RootCaFile -PathType Leaf)) {
        throw "缺少集群公共 Root CA 文件：$RootCaFile"
    }
    Invoke-LoggedKubectl "创建 MEFKT worker CA 注入所需公共 ConfigMap" @(
        "create", "configmap", "bbt-root-ca", "--namespace", $Namespace,
        "--from-file=roots.pem=$RootCaFile",
        "--from-file=bbt-root-ca.crt=$RootCaFile"
    ) | Out-Host
}

function New-TrainingManifest {
    <#
    生成 Volcano Job 清单。

    :returns: 可提交的 Volcano Job YAML 文本。
    #>
    $ampArgument = if ($Amp) { "--amp" } else { "" }
    $nodeSelector = if ($NodeName) {
        "kubernetes.io/hostname: $NodeName"
    } else {
        "node-type: gpu"
    }
    $datasetArguments = "--dataset $(ConvertTo-BashLiteral $Dataset) --data-root $(ConvertTo-BashLiteral $RemoteDataRoot)"
    if ($Dataset -eq "canonical-csv") {
        $datasetArguments += " --events-file $(ConvertTo-BashLiteral $RemoteEventsFile)"
        if ($RemoteContentEmbeddingsFile) {
            $datasetArguments += " --content-embeddings-file $(ConvertTo-BashLiteral $RemoteContentEmbeddingsFile)"
        }
    } elseif ($RemoteContentEmbeddingsFile) {
        $datasetArguments += " --content-embeddings-file $(ConvertTo-BashLiteral $RemoteContentEmbeddingsFile)"
    }
    if ($WindowContextLength -ge 0) {
        $datasetArguments += " --window-context-length $WindowContextLength"
    }
    $preprocessArgument = if ($ForcePreprocess) { "--force-preprocess" } else { "" }
    $resumeArgument = if ($Resume) { "--resume" } else { "" }
    $trainLog = "$OutputDir/train.log"
    $command = @'
set -euo pipefail
until test -s /workspace/jobs/mefkt_lite_data.py && test -s /workspace/jobs/mefkt_data_core.py && test -s /workspace/jobs/mefkt_canonical_data.py && test -s /workspace/jobs/mefkt_early_stopping.py && test -s /workspace/jobs/mefkt_evaluation.py && test -s /workspace/jobs/mefkt_open_world.py && test -s /workspace/jobs/mefkt_encoders.py && test -s /workspace/jobs/mefkt_model_config.py && test -s /workspace/jobs/mefkt_models.py && test -s /workspace/jobs/mefkt_v3_models.py && test -s /workspace/jobs/mefkt_optimization.py && test -s /workspace/jobs/mefkt_reporting.py && test -s /workspace/jobs/mefkt_plot_training.py && test -s /workspace/jobs/mefkt_runtime.py && test -s /workspace/jobs/mefkt_training_args.py && test -s /workspace/jobs/mefkt_training_core.py && test -s /workspace/jobs/mefkt_training_runtime.py && test -s /workspace/jobs/mefkt_train.py && test -s /workspace/jobs/validate_mefkt_checkpoint.py && test -f __READY_FILE__; do
  sleep 5
done
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export MASTER_ADDR="${VC_WORKER_HOSTS%%,*}"
export MASTER_PORT=23456
export WORLD_SIZE="${VC_WORKER_NUM}"
if [ -n "${VK_TASK_INDEX:-}" ]; then
  export RANK="${VK_TASK_INDEX}"
elif [[ "${HOSTNAME:-}" =~ -worker-([0-9]+)$ ]]; then
  export RANK="${BASH_REMATCH[1]}"
else
  export RANK=0
fi
export LOCAL_RANK=0
mkdir -p __OUTPUT_DIR__
set +e
torchrun \
  --nnodes="${WORLD_SIZE}" \
  --node_rank="${RANK}" \
  --nproc_per_node=1 \
  --master_addr="${MASTER_ADDR}" \
  --master_port="${MASTER_PORT}" \
  /workspace/jobs/mefkt_train.py \
  --profile __PROFILE__ \
  --architecture-version __ARCHITECTURE_VERSION__ \
  __DATASET_ARGUMENTS__ \
  --output-dir __OUTPUT_DIR__ \
  --epochs __EPOCHS__ \
  --batch-size __BATCH_SIZE__ \
  --sequence-length __SEQUENCE_LENGTH__ \
  --min-sequence-length __MIN_SEQUENCE_LENGTH__ \
  --learning-rate __LEARNING_RATE__ \
  --weight-decay __WEIGHT_DECAY__ \
  --lr-scheduler __LR_SCHEDULER__ \
  --lr-scheduler-factor __LR_SCHEDULER_FACTOR__ \
  --lr-scheduler-patience __LR_SCHEDULER_PATIENCE__ \
  --min-learning-rate __MIN_LEARNING_RATE__ \
  --warmup-epochs __WARMUP_EPOCHS__ \
  --high-lr-epochs __HIGH_LR_EPOCHS__ \
  --mid-lr-epochs __MID_LR_EPOCHS__ \
  --subject-balance-alpha __SUBJECT_BALANCE_ALPHA__ \
  --num-workers __NUM_WORKERS__ \
  --max-users __MAX_USERS__ \
  --max-interactions __MAX_INTERACTIONS__ \
  --patience __PATIENCE__ \
  --validation-loss-patience __VALIDATION_LOSS_PATIENCE__ \
  --validation-loss-min-delta __VALIDATION_LOSS_MIN_DELTA__ \
  --validation-loss-plateau-patience __VALIDATION_LOSS_PLATEAU_PATIENCE__ \
  --cpu-threads 2 __PREPROCESS_ARGUMENT__ __RESUME_ARGUMENT__ __AMP_ARGUMENT__ 2>&1 | tee -a __TRAIN_LOG__
status=${PIPESTATUS[0]}
set -e
exit "$status"
'@
    foreach ($pair in @(
            @("__DATASET_ARGUMENTS__", $datasetArguments),
            @("__OUTPUT_DIR__", $OutputDir),
            @("__TRAIN_LOG__", (ConvertTo-BashLiteral $trainLog)),
            @("__READY_FILE__", "/workspace/jobs/.ready-$JobName"),
            @("__PROFILE__", $Profile),
            @("__ARCHITECTURE_VERSION__", $ArchitectureVersion),
            @("__EPOCHS__", $Epochs),
            @("__BATCH_SIZE__", $BatchSize),
            @("__SEQUENCE_LENGTH__", $SequenceLength),
            @("__MIN_SEQUENCE_LENGTH__", $MinSequenceLength),
            @("__LEARNING_RATE__", $LearningRate.ToString([Globalization.CultureInfo]::InvariantCulture)),
            @("__WEIGHT_DECAY__", $WeightDecay.ToString([Globalization.CultureInfo]::InvariantCulture)),
            @("__LR_SCHEDULER__", $LrScheduler),
            @("__LR_SCHEDULER_FACTOR__", $LrSchedulerFactor.ToString([Globalization.CultureInfo]::InvariantCulture)),
            @("__LR_SCHEDULER_PATIENCE__", $LrSchedulerPatience),
            @("__MIN_LEARNING_RATE__", $MinLearningRate.ToString([Globalization.CultureInfo]::InvariantCulture)),
            @("__WARMUP_EPOCHS__", $WarmupEpochs),
            @("__HIGH_LR_EPOCHS__", $HighLrEpochs),
            @("__MID_LR_EPOCHS__", $MidLrEpochs),
            @("__SUBJECT_BALANCE_ALPHA__", $SubjectBalanceAlpha.ToString([Globalization.CultureInfo]::InvariantCulture)),
            @("__NUM_WORKERS__", $NumWorkers),
            @("__MAX_USERS__", $MaxUsers),
            @("__MAX_INTERACTIONS__", $MaxInteractions),
            @("__PATIENCE__", $Patience),
            @("__VALIDATION_LOSS_PATIENCE__", $ValidationLossPatience),
            @("__VALIDATION_LOSS_MIN_DELTA__", $ValidationLossMinDelta),
            @("__VALIDATION_LOSS_PLATEAU_PATIENCE__", $ValidationLossPlateauPatience),
            @("__PREPROCESS_ARGUMENT__", $preprocessArgument),
            @("__RESUME_ARGUMENT__", $resumeArgument),
            @("__AMP_ARGUMENT__", $ampArgument),
            @("__NODE_SELECTOR__", $nodeSelector)
        )) {
        $command = $command.Replace([string]$pair[0], [string]$pair[1])
    }
    $manifest = @"
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata:
  name: $JobName
  namespace: $Namespace
  labels:
    app.kubernetes.io/part-of: adaptive-edu
    app.kubernetes.io/name: mefkt
    mefkt-run: $JobName
spec:
  schedulerName: volcano
  queue: $Queue
  priorityClassName: $PriorityClassName
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
            app.kubernetes.io/name: mefkt
            mefkt-run: $JobName
        spec:
          nodeSelector:
            __NODE_SELECTOR__
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
                  cpu: "6"
                  memory: 32Gi
                limits:
                  nvidia.com/gpu: "1"
                  cpu: "14"
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
    return $manifest.Replace("__NODE_SELECTOR__", $nodeSelector)
}

if ($RenderOnly) {
    # 本地只渲染清单，便于在不访问集群时检查多卡参数和挂载关系。
    New-TrainingManifest
    return
}

try {
    $jobExists = (Invoke-LoggedKubectl "检查训练 Volcano Job $JobName 是否已存在" @(
            "get", "vcjob", $JobName, "--namespace", $Namespace,
            "--ignore-not-found", "--output", "name"
        ) | Out-String).Trim()
    if ($jobExists) {
        if (-not $ReuseExistingJob) {
            throw "训练 Job 已存在；确认要继续完成其上传时请传入 -ReuseExistingJob：$Namespace/$JobName"
        }
        Write-Host "继续完成已有训练 Job：$Namespace/$JobName"
    }

    Ensure-Pvc -Name $CodePvcName -StorageClass "nfs-client" -Size $CodeStorageSize
    Ensure-Pvc -Name $DataPvcName -StorageClass "juicefs-sc" -Size $DataStorageSize
    Ensure-RootCaConfigMap

    if (-not $jobExists) {
        $jobManifest = New-TrainingManifest
        [System.IO.File]::WriteAllText($JobManifestPath, $jobManifest, [System.Text.UTF8Encoding]::new($false))
        Invoke-LoggedKubectl "提交 Volcano MEFKT 多 GPU Job $JobName" @(
            "apply", "--namespace", $Namespace, "--filename", $JobManifestPath
        ) | Out-Host
    }

    $podName = $null
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        $podOutput = (Invoke-LoggedKubectl "查找训练 Job $JobName 的 Pod（第 $attempt 次）" @(
                "get", "pods", "--namespace", $Namespace,
                "--selector", "mefkt-run=$JobName",
                "--output", "name"
            ) | Out-String).Trim()
        $podCandidates = @($podOutput -split '\r?\n' | Where-Object { $_ -and $_.Trim() } | Select-Object -First 1)
        $podName = if ($podCandidates.Count -gt 0) {
            ([string]$podCandidates[0]).Trim() -replace '^pod/', ''
        } else {
            $null
        }
        if ($podName) { break }
        Start-Sleep -Seconds 5
    }
    if (-not $podName) {
        throw "等待训练 Pod 超时：$Namespace/$JobName"
    }
    $allWorkersReady = $false
    for ($attempt = 1; $attempt -le 240; $attempt++) {
        $podStateText = Invoke-LoggedKubectl "检查训练 Job $JobName worker Ready 状态（第 $attempt 次）" @(
            "get", "pods", "--namespace", $Namespace,
            "--selector", "mefkt-run=$JobName", "--output", "json"
        )
        $podState = $podStateText | ConvertFrom-Json
        $workers = @($podState.items)
        $readyWorkers = @($workers | Where-Object {
                $statusesProperty = $_.status.PSObject.Properties["containerStatuses"]
                $containerStatuses = if ($null -ne $statusesProperty) { @($statusesProperty.Value) } else { @() }
                @($containerStatuses | Where-Object {
                        $_.name -eq "trainer" -and $_.ready
                    }).Count -gt 0
            })
        if ($workers.Count -ge $GpuCount -and $readyWorkers.Count -ge $GpuCount) {
            $allWorkersReady = $true
            break
        }
        Start-Sleep -Seconds 5
    }
    if (-not $allWorkersReady) {
        throw "等待训练 Job 全部 worker Ready 超时：$Namespace/$JobName"
    }

    if ($UploadData) {
        Invoke-LoggedKubectl "创建 MEFKT 训练数据目录 $RemoteDataRoot" @(
            "exec", "--namespace", $Namespace, $podName, "--container", "trainer", "--", "bash", "-lc",
            "mkdir -p '$RemoteDataRoot'"
        ) | Out-Host
        Invoke-LoggedKubectl "上传 MEFKT canonical 训练事件到 $JobName" @(
            "cp", (ConvertTo-KubectlLocalPath $EventsFile), "$Namespace/${podName}:$RemoteEventsFile.uploading",
            "--container", "trainer"
        ) | Out-Host
        Invoke-LoggedKubectl "上传 MEFKT 内容向量 sidecar 到 $JobName" @(
            "cp", (ConvertTo-KubectlLocalPath $ContentEmbeddingsFile), "$Namespace/${podName}:$RemoteContentEmbeddingsFile.uploading",
            "--container", "trainer"
        ) | Out-Host
        Invoke-LoggedKubectl "原子发布 MEFKT 训练数据到共享 PVC" @(
            "exec", "--namespace", $Namespace, $podName, "--container", "trainer", "--", "bash", "-lc",
            "mv '$RemoteEventsFile.uploading' '$RemoteEventsFile' && mv '$RemoteContentEmbeddingsFile.uploading' '$RemoteContentEmbeddingsFile'"
        ) | Out-Host
    }
    foreach ($dataFile in $DataFiles) {
        $fileName = Split-Path -Leaf $dataFile
        Invoke-LoggedKubectl "上传 MEFKT 模块 $fileName 到 $JobName" @(
            "cp", (ConvertTo-KubectlLocalPath $dataFile), "$Namespace/${podName}:/workspace/jobs/.$fileName.uploading",
            "--container", "trainer"
        ) | Out-Host
    }
    $publishCommands = @(
        "mv /workspace/jobs/.mefkt_lite_data.py.uploading /workspace/jobs/mefkt_lite_data.py",
        "mv /workspace/jobs/.mefkt_data_core.py.uploading /workspace/jobs/mefkt_data_core.py",
        "mv /workspace/jobs/.mefkt_canonical_data.py.uploading /workspace/jobs/mefkt_canonical_data.py",
        "mv /workspace/jobs/.mefkt_early_stopping.py.uploading /workspace/jobs/mefkt_early_stopping.py",
        "mv /workspace/jobs/.mefkt_evaluation.py.uploading /workspace/jobs/mefkt_evaluation.py",
        "mv /workspace/jobs/.mefkt_open_world.py.uploading /workspace/jobs/mefkt_open_world.py",
        "mv /workspace/jobs/.mefkt_encoders.py.uploading /workspace/jobs/mefkt_encoders.py",
        "mv /workspace/jobs/.mefkt_model_config.py.uploading /workspace/jobs/mefkt_model_config.py",
        "mv /workspace/jobs/.mefkt_models.py.uploading /workspace/jobs/mefkt_models.py",
        "mv /workspace/jobs/.mefkt_v3_models.py.uploading /workspace/jobs/mefkt_v3_models.py",
        "mv /workspace/jobs/.mefkt_optimization.py.uploading /workspace/jobs/mefkt_optimization.py",
        "mv /workspace/jobs/.mefkt_reporting.py.uploading /workspace/jobs/mefkt_reporting.py",
        "mv /workspace/jobs/.mefkt_plot_training.py.uploading /workspace/jobs/mefkt_plot_training.py",
        "mv /workspace/jobs/.mefkt_runtime.py.uploading /workspace/jobs/mefkt_runtime.py",
        "mv /workspace/jobs/.mefkt_training_args.py.uploading /workspace/jobs/mefkt_training_args.py",
        "mv /workspace/jobs/.mefkt_training_core.py.uploading /workspace/jobs/mefkt_training_core.py",
        "mv /workspace/jobs/.mefkt_training_runtime.py.uploading /workspace/jobs/mefkt_training_runtime.py",
        "mv /workspace/jobs/.mefkt_train.py.uploading /workspace/jobs/mefkt_train.py",
        "mv /workspace/jobs/.diagnose_mefkt_checkpoint.py.uploading /workspace/jobs/diagnose_mefkt_checkpoint.py",
        "mv /workspace/jobs/.validate_mefkt_checkpoint.py.uploading /workspace/jobs/validate_mefkt_checkpoint.py",
        "touch /workspace/jobs/.ready-$JobName"
    )
    Invoke-LoggedKubectl "原子发布 MEFKT 训练脚本到共享 PVC" @(
        "exec", "--namespace", $Namespace, $podName, "--container", "trainer", "--", "bash", "-lc",
        ($publishCommands -join " && ")
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
