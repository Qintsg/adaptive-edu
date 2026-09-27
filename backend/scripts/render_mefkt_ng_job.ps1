<#
文件内容描述：渲染 MEFKT-NG Volcano 作业；显式 -Submit 才访问集群。
@Project : adaptive-edu
@File : render_mefkt_ng_job.ps1
@Author : Qintsg
@Date : 2026-09-24

所有实际 kubectl 操作必须经过 Kubernetes-bbt 的日志包装器。
原始输入写 Data PVC；指标、逐轮 checkpoint 和预测写 NFS 结果 PVC。
#>
[CmdletBinding()]
param(
    [string]$Namespace = "advisor-rhw",
    [string]$Queue = "advisor-rhw-gpu",
    [int]$GpuCount = 2,
    [string]$JobName = "",
    [string]$RunId = "",
    [string]$Image = "nvcr.io/nvidia/pytorch:26.04-py3",
    [string]$NodeName = "",
    [string]$PriorityClassName = "gpu-job-high",
    [string]$CodePvcName = "mefkt-code",
    [string]$CodePvcSize = "10Gi",
    [string]$DataPvcName = "mefkt-data",
    [string]$DataPvcSize = "100Gi",
    [string]$OutputPvcName = "mefkt-ng-results",
    [string]$OutputPvcSize = "50Gi",
    [string]$RemoteEventsFile = "",
    [string]$RemoteContentFile = "",
    [string]$RemoteGraphFile = "",
    [string]$LocalEventsFile = "",
    [string]$LocalContentFile = "",
    [string]$LocalGraphFile = "",
    [int]$Epochs = 200,
    [int]$BatchSize = 128,
    [int]$SequenceLength = 200,
    [int]$ContextLength = 64,
    [int]$HiddenDim = 1024,
    [double]$LearningRate = 0.0001,
    [int]$NumWorkers = 0,
    [string]$InitialCheckpoint = "",
    [string]$InitialCheckpointSha256 = "",
    [int]$MinResultsFreeGiB = 0,
    [ValidateRange(1, 1024)][int]$ChunkUploadThresholdMiB = 256,
    [ValidateRange(1, 256)][int]$UploadChunkMiB = 64,
    [switch]$Resume,
    [switch]$UploadData,
    [switch]$Submit,
    [string]$KubernetesRoot = "E:\Projects\BBT\Kubernetes-bbt",
    [string]$Kubeconfig = "$env:USERPROFILE\.kube\prd.yaml"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$JobName = if ($JobName) { $JobName } else { "mefkt-ng-$stamp" }
$RunId = if ($RunId) { $RunId } else { $JobName }
foreach ($entry in @(@("Namespace", $Namespace), @("Queue", $Queue), @("JobName", $JobName),
        @("RunId", $RunId), @("PriorityClassName", $PriorityClassName),
        @("CodePvcName", $CodePvcName), @("DataPvcName", $DataPvcName),
        @("OutputPvcName", $OutputPvcName))) {
    if ($entry[1] -notmatch '^[a-z0-9][a-z0-9.-]*$') {
        throw "$($entry[0]) 不是合法的资源名称：$($entry[1])"
    }
}
if ($NodeName -and $NodeName -notmatch '^[a-z0-9][a-z0-9.-]*$') {
    throw "NodeName 不是合法节点名称：$NodeName"
}
if ($Image -notmatch '^[a-zA-Z0-9._:/-]+$') {
    throw "Image 包含不允许的字符"
}
if (@($CodePvcSize, $DataPvcSize, $OutputPvcSize) | Where-Object { $_ -notmatch '^[1-9][0-9]*Gi$' }) {
    throw "PVC 容量必须是正 Gi 整数"
}
if ($GpuCount -lt 1 -or $Epochs -lt 1 -or $BatchSize -lt 1 -or $SequenceLength -lt 2 -or
    $ContextLength -lt 0 -or $ContextLength -ge $SequenceLength -or $HiddenDim -lt 32 -or
    $LearningRate -le 0 -or $NumWorkers -lt 0) {
    throw "GPU、轮次、batch、序列、隐藏维度或学习率参数非法"
}
if (($InitialCheckpointSha256 -and (-not $InitialCheckpoint -or $InitialCheckpointSha256 -notmatch '^[a-fA-F0-9]{64}$')) -or
    $MinResultsFreeGiB -lt 0 -or $MinResultsFreeGiB -gt [int]$OutputPvcSize.Substring(0, $OutputPvcSize.Length - 2)) {
    throw "初始 checkpoint 摘要或结果 PVC 空间阈值非法"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$codeRoot = "/workspace/jobs/$JobName"
$inputRoot = "/data/mefkt-ng-inputs/$RunId"
$outputRoot = "/results/mefkt-ng-runs/$RunId"
$preparedRoot = "/results/mefkt-ng-prepared/$RunId"
$RemoteEventsFile = if ($RemoteEventsFile) { $RemoteEventsFile } else { "$inputRoot/train.csv" }
$RemoteContentFile = if ($RemoteContentFile) { $RemoteContentFile } else { "$inputRoot/item_content_embeddings.npz" }
if ($LocalGraphFile -and -not $RemoteGraphFile) {
    $RemoteGraphFile = "$inputRoot/knowledge_relations.json"
}
foreach ($path in @($codeRoot, $inputRoot, $outputRoot, $preparedRoot, $RemoteEventsFile, $RemoteContentFile) +
    @($RemoteGraphFile, $InitialCheckpoint | Where-Object { $_ })) {
    if ($path -notmatch '^/[A-Za-z0-9._/-]+$' -or $path.Contains("..")) {
        throw "远程路径不安全：$path"
    }
}
$nodeSelector = if ($NodeName) {
    "kubernetes.io/hostname: $NodeName"
} else {
    "node-type: gpu"
}
$graphArg = if ($RemoteGraphFile) { "--graph-file $RemoteGraphFile" } else { "" }
$resumeArg = if ($Resume) { "--resume" } else { "" }
$initialArg = if ($InitialCheckpoint) { "--initial-checkpoint $InitialCheckpoint" } else { "" }
if ($Resume -and $InitialCheckpoint) { throw "-Resume 与 -InitialCheckpoint 不能同时使用" }
$learningRateText = $LearningRate.ToString([Globalization.CultureInfo]::InvariantCulture)

$command = @'
set -euo pipefail
until test -f __CODE_ROOT__/.ready; do sleep 5; done
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
mkdir -p __OUTPUT_ROOT__/logs
set +e
torchrun --nnodes="${WORLD_SIZE}" --node_rank="${RANK}" --nproc_per_node=1 \
  --master_addr="${MASTER_ADDR}" --master_port="${MASTER_PORT}" \
  __CODE_ROOT__/mefkt_ng_train.py \
  --events-file __EVENTS__ --content-embeddings-file __CONTENT__ __GRAPH_ARG__ \
  --data-root __PREPARED_ROOT__ --output-dir __OUTPUT_ROOT__ \
  --epochs __EPOCHS__ --batch-size __BATCH__ --sequence-length __LENGTH__ \
  --context-length __CONTEXT__ --hidden-dim __HIDDEN__ \
  --learning-rate __LR__ --num-workers __WORKERS__ --device cuda --amp __RESUME__ __INITIAL__ \
  2>&1 | tee -a __OUTPUT_ROOT__/logs/rank-${RANK}.log
status=${PIPESTATUS[0]}
set -e
exit "$status"
'@
$replacements = @(
    @("__CODE_ROOT__", $codeRoot), @("__OUTPUT_ROOT__", $outputRoot),
    @("__INPUT_ROOT__", $inputRoot), @("__PREPARED_ROOT__", $preparedRoot),
    @("__EVENTS__", $RemoteEventsFile),
    @("__CONTENT__", $RemoteContentFile), @("__GRAPH_ARG__", $graphArg),
    @("__EPOCHS__", "$Epochs"), @("__BATCH__", "$BatchSize"),
    @("__LENGTH__", "$SequenceLength"), @("__CONTEXT__", "$ContextLength"),
    @("__HIDDEN__", "$HiddenDim"), @("__LR__", $learningRateText),
    @("__WORKERS__", "$NumWorkers"), @("__RESUME__", $resumeArg),
    @("__INITIAL__", $initialArg)
)
foreach ($pair in $replacements) {
    $command = $command.Replace([string]$pair[0], [string]$pair[1])
}
$indentedCommand = (($command -split "`r?`n") | ForEach-Object { "                  $_" }) -join "`n"
$manifest = @"
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata:
  name: $JobName
  namespace: $Namespace
  labels:
    app.kubernetes.io/name: mefkt-ng
    mefkt-ng-run: $RunId
    mefkt-ng-job: $JobName
spec:
  schedulerName: volcano
  queue: $Queue
  priorityClassName: $PriorityClassName
  minAvailable: $GpuCount
  maxRetry: 2
  plugins:
    svc:
      - --publish-not-ready-addresses=true
  tasks:
    - name: worker
      replicas: $GpuCount
      template:
        metadata:
          labels:
            mefkt-ng-job: $JobName
        spec:
          nodeSelector:
            $nodeSelector
          restartPolicy: OnFailure
          containers:
            - name: trainer
              image: $Image
              imagePullPolicy: IfNotPresent
              command: ["bash", "-lc"]
              args:
                - |
$indentedCommand
              resources:
                requests:
                  cpu: "1"
                  memory: 16Gi
                  nvidia.com/gpu: "1"
                limits:
                  cpu: "4"
                  memory: 64Gi
                  nvidia.com/gpu: "1"
              ports:
                - name: torchrun
                  containerPort: 23456
              volumeMounts:
                - name: code
                  mountPath: /workspace
                - name: data
                  mountPath: /data
                - name: results
                  mountPath: /results
                - name: shm
                  mountPath: /dev/shm
          volumes:
            - name: code
              persistentVolumeClaim:
                claimName: $CodePvcName
            - name: data
              persistentVolumeClaim:
                claimName: $DataPvcName
            - name: results
              persistentVolumeClaim:
                claimName: $OutputPvcName
            - name: shm
              emptyDir:
                medium: Memory
                sizeLimit: 16Gi
"@
$codePvcManifest = @"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $CodePvcName
  namespace: $Namespace
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: $CodePvcSize
"@
$dataPvcManifest = @"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $DataPvcName
  namespace: $Namespace
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: juicefs-sc
  resources:
    requests:
      storage: $DataPvcSize
"@
$pvcManifest = @"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $OutputPvcName
  namespace: $Namespace
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: $OutputPvcSize
"@
$uploaderName = "$JobName-upload"
$uploaderManifest = @"
apiVersion: v1
kind: Pod
metadata:
  name: $uploaderName
  namespace: $Namespace
  labels:
    app.kubernetes.io/name: mefkt-ng-uploader
    mefkt-ng-job: $JobName
spec:
  nodeSelector:
    node-type: cpu
  restartPolicy: Never
  containers:
    - name: uploader
      image: busybox:1.36
      command: ["sh", "-c", "sleep 7200"]
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          cpu: 400m
          memory: 1Gi
      volumeMounts:
        - name: code
          mountPath: /workspace
        - name: data
          mountPath: /data
        - name: results
          mountPath: /results
  volumes:
    - name: code
      persistentVolumeClaim:
        claimName: $CodePvcName
    - name: data
      persistentVolumeClaim:
        claimName: $DataPvcName
    - name: results
      persistentVolumeClaim:
        claimName: $OutputPvcName
"@

if (-not $Submit) {
    (@($codePvcManifest, $dataPvcManifest, $pvcManifest, $uploaderManifest, $manifest) -join "`n---`n")
    return
}

$loggedKubectl = Join-Path $KubernetesRoot "scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1"
if (-not (Test-Path -LiteralPath $loggedKubectl -PathType Leaf)) {
    throw "缺少带操作日志的 kubectl 包装器：$loggedKubectl"
}
. (Join-Path $scriptRoot 'Invoke-MEFKTChunkedUpload.ps1')
$sourceFiles = @((Join-Path $scriptRoot "mefkt_ng_train.py")) +
    @(Get-ChildItem -LiteralPath (Join-Path $scriptRoot "mefkt_ng") -Filter '*.py' | Select-Object -ExpandProperty FullName)
foreach ($source in $sourceFiles) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "训练源码不存在：$source"
    }
}
if ($UploadData) {
    foreach ($localFile in @($LocalEventsFile, $LocalContentFile)) {
        if (-not $localFile -or -not (Test-Path -LiteralPath $localFile -PathType Leaf)) {
            throw "-UploadData 必须提供存在的 LocalEventsFile 与 LocalContentFile"
        }
    }
    if ($RemoteGraphFile -and -not (Test-Path -LiteralPath $LocalGraphFile -PathType Leaf)) {
        throw "指定图文件时必须提供存在的 LocalGraphFile"
    }
    $LocalEventsFile = (Resolve-Path -LiteralPath $LocalEventsFile).Path
    $LocalContentFile = (Resolve-Path -LiteralPath $LocalContentFile).Path
    if ($RemoteGraphFile) { $LocalGraphFile = (Resolve-Path -LiteralPath $LocalGraphFile).Path }
}

function Invoke-LoggedKubectl {
    <#
    用仓库要求的操作日志包装器执行 kubectl。
    :param Reason: 日志说明。
    :param KubectlArgs: kubectl 参数数组。
    :returns: 命令输出。
    #>
    param([string]$Reason, [string[]]$KubectlArgs)
    & $loggedKubectl -Reason $Reason -Kubeconfig $Kubeconfig -KubectlArgs $KubectlArgs
}

$existing = (Invoke-LoggedKubectl "检查 MEFKT-NG 作业 $JobName" @(
        "get", "vcjob", $JobName, "--namespace", $Namespace,
        "--ignore-not-found", "--output", "name"
    ) | Out-String).Trim()
if ($existing) {
    throw "同名训练 Job 已存在，拒绝改写运行中作业：$Namespace/$JobName"
}
$pvcPlans = @(
    [pscustomobject]@{ Name = $CodePvcName; Size = $CodePvcSize; Class = 'nfs-client'; Manifest = $codePvcManifest; Exists = $false },
    [pscustomobject]@{ Name = $DataPvcName; Size = $DataPvcSize; Class = 'juicefs-sc'; Manifest = $dataPvcManifest; Exists = $false },
    [pscustomobject]@{ Name = $OutputPvcName; Size = $OutputPvcSize; Class = 'nfs-client'; Manifest = $pvcManifest; Exists = $false }
)
foreach ($plan in $pvcPlans) {
    $found = (Invoke-LoggedKubectl "核对 MEFKT-NG PVC $($plan.Name)" @(
            "get", "pvc", $plan.Name, "--namespace", $Namespace,
            "--ignore-not-found", "--output", "json"
        ) | Out-String).Trim()
    if ($found) {
        $claim = $found | ConvertFrom-Json
        if ($claim.spec.storageClassName -ne $plan.Class -or
            $claim.spec.resources.requests.storage -ne $plan.Size) {
            throw "现有 PVC 的 StorageClass 或容量与清单不一致：$Namespace/$($plan.Name)"
        }
        $plan.Exists = $true
    }
}
if (-not $UploadData -and -not ($pvcPlans | Where-Object { $_.Name -eq $DataPvcName }).Exists) {
    throw "数据 PVC 尚未创建；首次提交必须使用 -UploadData 提供训练 CSV 和内容向量"
}

$temporaryManifest = Join-Path ([System.IO.Path]::GetTempPath()) "$JobName-$(New-Guid).yaml"
$temporaryPvcManifest = Join-Path ([System.IO.Path]::GetTempPath()) "$OutputPvcName-$(New-Guid).yaml"
$temporaryUploaderManifest = Join-Path ([System.IO.Path]::GetTempPath()) "$uploaderName-$(New-Guid).yaml"
$manifestDirectory = Join-Path $repoRoot "backend\runtime_logs\mefkt_ng_manifests"
[System.IO.Directory]::CreateDirectory($manifestDirectory) | Out-Null
$manifestCopy = Join-Path $manifestDirectory "$JobName.yaml"
$completeManifest = (@($codePvcManifest, $dataPvcManifest, $pvcManifest, $uploaderManifest, $manifest) -join "`n---`n")
if (Test-Path -LiteralPath $manifestCopy) {
    if ([System.IO.File]::ReadAllText($manifestCopy) -ne $completeManifest) {
        throw "已存在同名但内容不同的作业清单：$manifestCopy"
    }
} else {
    [System.IO.File]::WriteAllText($manifestCopy, $completeManifest, [System.Text.UTF8Encoding]::new($false))
}
$uploaderCreated = $false
try {
    foreach ($plan in $pvcPlans) {
        if (-not $plan.Exists) {
            [System.IO.File]::WriteAllText($temporaryPvcManifest, $plan.Manifest, [System.Text.UTF8Encoding]::new($false))
            Invoke-LoggedKubectl "创建 MEFKT-NG PVC $($plan.Name)（$($plan.Class) $($plan.Size)）" @(
                "apply", "--namespace", $Namespace, "--filename", $temporaryPvcManifest
            ) | Out-Host
        }
    }
    [System.IO.File]::WriteAllText($temporaryUploaderManifest, $uploaderManifest, [System.Text.UTF8Encoding]::new($false))
    Invoke-LoggedKubectl "创建 MEFKT-NG CPU 上传 Pod $uploaderName" @(
        "apply", "--namespace", $Namespace, "--filename", $temporaryUploaderManifest
    ) | Out-Host
    $uploaderCreated = $true
    $podReady = $false
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        $statusText = Invoke-LoggedKubectl "检查 MEFKT-NG 上传 Pod 就绪状态" @(
            "get", "pod", $uploaderName, "--namespace", $Namespace, "--output", "json"
        )
        $status = $statusText | ConvertFrom-Json
        $statusesProperty = $status.status.PSObject.Properties["containerStatuses"]
        $containerStatuses = if ($null -ne $statusesProperty) { @($statusesProperty.Value) } else { @() }
        $podReady = @($containerStatuses | Where-Object { $_.name -eq "uploader" -and $_.ready }).Count -gt 0
        if ($podReady) { break }
        Start-Sleep -Seconds 5
    }
    if (-not $podReady) { throw "等待上传 Pod Ready 超时：$Namespace/$uploaderName" }
    Invoke-LoggedKubectl "创建 MEFKT-NG 代码和数据目录" @(
        "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
        "sh", "-c", "mkdir -p '$codeRoot/mefkt_ng' '$inputRoot' '$preparedRoot' '$outputRoot'"
    ) | Out-Host
    $moduleDirectory = (Resolve-Path -LiteralPath (Join-Path $scriptRoot 'mefkt_ng')).Path
    Push-Location $repoRoot
    try {
        $relativeManifest = [System.IO.Path]::GetRelativePath($repoRoot, $manifestCopy).Replace([char]92, [char]47)
        Invoke-LoggedKubectl "归档 MEFKT-NG 作业清单 $JobName" @(
            "cp", $relativeManifest, "$Namespace/${uploaderName}:$outputRoot/job_manifest_$JobName.yaml", "--container", "uploader"
        ) | Out-Host
        foreach ($source in $sourceFiles) {
            $relative = [System.IO.Path]::GetRelativePath($repoRoot, $source).Replace([char]92, [char]47)
            $target = if ((Split-Path -Parent $source) -eq $moduleDirectory) {
                "$codeRoot/mefkt_ng/$(Split-Path -Leaf $source)"
            } else {
                "$codeRoot/mefkt_ng_train.py"
            }
            Invoke-LoggedKubectl "上传 MEFKT-NG 模块 $relative" @(
                "cp", $relative, "$Namespace/${uploaderName}:$target", "--container", "uploader"
            ) | Out-Host
        }
        if ($UploadData) {
            $uploads = @(@{ Local = $LocalEventsFile; Remote = $RemoteEventsFile },
                         @{ Local = $LocalContentFile; Remote = $RemoteContentFile })
            if ($RemoteGraphFile) { $uploads += @{ Local = $LocalGraphFile; Remote = $RemoteGraphFile } }
            foreach ($upload in $uploads) {
                $relative = [System.IO.Path]::GetRelativePath($repoRoot, $upload.Local).Replace([char]92, [char]47)
                if ((Get-Item -LiteralPath $upload.Local).Length -ge [long]$ChunkUploadThresholdMiB * 1048576) {
                    Invoke-MEFKTChunkedUpload -LoggedKubectl $loggedKubectl -Kubeconfig $Kubeconfig `
                        -Namespace $Namespace -PodName $uploaderName -LocalFile $upload.Local `
                        -RemoteFile $upload.Remote -ChunkMiB $UploadChunkMiB
                } else {
                    Invoke-LoggedKubectl "上传 MEFKT-NG 数据 $(Split-Path -Leaf $upload.Local)" @(
                        "cp", $relative, "$Namespace/${uploaderName}:$($upload.Remote)", "--container", "uploader"
                    ) | Out-Host
                }
                $remoteHash = (Invoke-LoggedKubectl "校验 MEFKT-NG 上传数据摘要 $(Split-Path -Leaf $upload.Local)" @(
                        "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
                        "sh", "-c", "sha256sum '$($upload.Remote)'"
                    ) | Out-String).Trim().Split(' ')[0]
                if ($remoteHash.ToLowerInvariant() -ne (Get-FileHash -LiteralPath $upload.Local -Algorithm SHA256).Hash.ToLowerInvariant()) {
                    throw "上传数据 SHA-256 不匹配：$($upload.Remote)"
                }
            }
        }
    } finally {
        Pop-Location
    }
    $required = @($RemoteEventsFile, $RemoteContentFile)
    if ($RemoteGraphFile) { $required += $RemoteGraphFile }
    if ($InitialCheckpoint) { $required += $InitialCheckpoint }
    $checks = ($required | ForEach-Object { "test -s '$_'" }) -join ' && '
    $checks = "test -s '$codeRoot/mefkt_ng_train.py' && $checks"
    Invoke-LoggedKubectl "检查 MEFKT-NG 所有远程训练输入" @(
        "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
        "sh", "-c", $checks
    ) | Out-Host
    if ($InitialCheckpointSha256) {
        $actualHash = (Invoke-LoggedKubectl "校验旧运行初始 checkpoint 摘要" @(
                "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
                "sh", "-c", "sha256sum '$InitialCheckpoint'"
            ) | Out-String).Trim().Split(' ')[0]
        if ($actualHash.ToLowerInvariant() -ne $InitialCheckpointSha256.ToLowerInvariant()) {
            throw "旧运行 checkpoint SHA-256 不匹配，拒绝开始扩充训练"
        }
    }
    if ($MinResultsFreeGiB -gt 0) {
        $usedText = (Invoke-LoggedKubectl "核对 MEFKT-NG 结果 PVC 已用空间" @(
                "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
                "sh", "-c", "du -sk /results"
            ) | Out-String).Trim()
        $usedKiB = [long](($usedText -split '\s+')[0])
        $capacityGiB = [int]$OutputPvcSize.Substring(0, $OutputPvcSize.Length - 2)
        $freeGiB = $capacityGiB - ($usedKiB / 1048576.0)
        if ($freeGiB -lt $MinResultsFreeGiB) {
            throw "结果 PVC 空间不足：估算剩余 $([math]::Round($freeGiB, 2)) GiB，小于要求 $MinResultsFreeGiB GiB"
        }
        Write-Host "结果 PVC 估算剩余 $([math]::Round($freeGiB, 2)) GiB"
    }
    Invoke-LoggedKubectl "发布 MEFKT-NG 作业代码就绪标记" @(
        "exec", "--namespace", $Namespace, $uploaderName, "--container", "uploader", "--",
        "sh", "-c", "touch '$codeRoot/.ready'"
    ) | Out-Host
    [System.IO.File]::WriteAllText($temporaryManifest, $manifest, [System.Text.UTF8Encoding]::new($false))
    Invoke-LoggedKubectl "提交 MEFKT-NG Volcano 作业 $JobName" @(
        "apply", "--namespace", $Namespace, "--filename", $temporaryManifest
    ) | Out-Host
    $jobState = (Invoke-LoggedKubectl "只读确认 MEFKT-NG Volcano 作业已创建" @(
            "get", "vcjob", $JobName, "--namespace", $Namespace, "--output", "name"
        ) | Out-String).Trim()
    if (-not $jobState) { throw "提交后未查到 Volcano 作业：$Namespace/$JobName" }
    Write-Host "训练已提交：$Namespace/$JobName，输出：$outputRoot"
} finally {
    if ($uploaderCreated) {
        try {
            Invoke-LoggedKubectl "清理 MEFKT-NG CPU 上传 Pod $uploaderName" @(
                "delete", "pod", $uploaderName, "--namespace", $Namespace, "--ignore-not-found", "--wait=false"
            ) | Out-Host
        } catch { Write-Warning "CPU 上传 Pod 清理失败，需稍后检查：$uploaderName" }
    }
    foreach ($tempFile in @($temporaryManifest, $temporaryPvcManifest, $temporaryUploaderManifest)) {
        if (Test-Path -LiteralPath $tempFile) {
            Remove-Item -LiteralPath $tempFile -Force
        }
    }
}
