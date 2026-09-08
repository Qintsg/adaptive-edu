<#
文件内容描述：只读盘点 MEFKT 训练所需的 Kubernetes GPU、配额、队列和权限。
@Project : adaptive-edu
@File : inspect_mefkt_cluster.ps1
@Author : Qintsg
@Date : 2026-08-25

所有远端查询都通过 BBT-7 日志包装器执行。脚本不读取 Secret，不执行写入。
#>

[CmdletBinding()]
param(
    [string]$Namespace = "advisor-rhw",
    [string]$KubernetesRoot = "E:\Projects\BBT\Kubernetes-bbt",
    [string]$Kubeconfig = "$env:USERPROFILE\.kube\prd.yaml",
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$wrapper = Join-Path $KubernetesRoot "scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1"
if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) {
    throw "找不到 BBT-7 Kubernetes 日志包装器：$wrapper"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path (Join-Path $PSScriptRoot "..") "runtime_logs\mefkt_cluster_inventory_$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
}

$errors = [System.Collections.Generic.List[string]]::new()

function Invoke-LoggedRead {
    <#
    通过 BBT-7 包装器执行只读 kubectl。

    :param Reason: 操作原因。
    :param Arguments: kubectl 参数数组。
    :returns: 命令输出文本或空值。
    #>
    param(
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    try {
        return (& $wrapper -Reason $Reason -Kubeconfig $Kubeconfig -KubectlArgs $Arguments | Out-String).Trim()
    } catch {
        $message = "$Reason：$($_.Exception.Message)"
        $errors.Add($message)
        Write-Warning $message
        return $null
    }
}

function Get-JsonOutput {
    <#
    执行 JSON 输出查询并转换为对象。

    :param Reason: 操作原因。
    :param Arguments: kubectl 参数数组。
    :returns: JSON 对象或空值。
    #>
    param(
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $text = Invoke-LoggedRead $Reason $Arguments
    if (-not $text) { return $null }
    try {
        # ConvertFrom-Json 在 Windows PowerShell 5.1 没有 -Depth 参数；Kubernetes
        # 返回的 JSON 仍可完整解析，深度控制只需要在序列化汇总时使用。
        return $text | ConvertFrom-Json
    } catch {
        $message = "$Reason 返回内容不是有效 JSON：$($_.Exception.Message)"
        $errors.Add($message)
        Write-Warning $message
        return $null
    }
}

function Get-ResourceValue {
    <#
    从 Kubernetes resource map 中读取指定资源。

    :param ResourceMap: Kubernetes 资源字典。
    :param Name: 资源名称。
    :returns: 资源数量或空值。
    #>
    param(
        [AllowNull()][object]$ResourceMap,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $ResourceMap) { return $null }
    $property = $ResourceMap.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return [string]$property.Value
}

function Get-NestedResourceValue {
    <#
    从容器 resources 的 requests 或 limits map 中读取指定资源。

    :param Resources: 容器 resources 对象。
    :param MapName: 资源 map 名称，通常为 requests 或 limits。
    :param Name: 资源名称。
    :returns: 资源数量或空值。
    #>
    param(
        [AllowNull()][object]$Resources,
        [Parameter(Mandatory)][string]$MapName,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $Resources) { return $null }
    $mapProperty = $Resources.PSObject.Properties[$MapName]
    if ($null -eq $mapProperty) { return $null }
    return Get-ResourceValue $mapProperty.Value $Name
}

function Get-OptionalPropertyValue {
    <#
    安全读取对象的可选属性，兼容不同版本 CRD 返回的字段差异。

    :param Object: 待读取对象。
    :param Name: 属性名称。
    :returns: 属性值或空值。
    #>
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory)][string]$Name
    )
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

$apiVersion = Invoke-LoggedRead "查看 MEFKT 集群 API 版本" @("get", "--raw=/version", "--request-timeout=15s")
$gpuNodeData = Get-JsonOutput "盘点 GPU 节点可分配 CPU 内存和 NVIDIA GPU" @(
    "get", "nodes", "--selector", "node-type=gpu", "--output", "json", "--request-timeout=15s"
)
$podData = Get-JsonOutput "盘点所有 namespace 的 GPU Pod 占用和状态" @(
    "get", "pods", "--all-namespaces", "--field-selector", "status.phase=Running", "--output", "json", "--request-timeout=15s"
)
$quotaData = Get-JsonOutput "盘点所有 namespace ResourceQuota hard 和 used" @(
    "get", "resourcequota", "--all-namespaces", "--output", "json", "--request-timeout=15s"
)
$limitData = Get-JsonOutput "盘点所有 namespace LimitRange" @(
    "get", "limitrange", "--all-namespaces", "--output", "json", "--request-timeout=15s"
)
$queueData = Get-JsonOutput "盘点 Volcano Queue capability 和当前状态" @(
    "get", "queue", "--all-namespaces", "--output", "json", "--request-timeout=15s"
)
$jobData = Get-JsonOutput "盘点所有 Volcano Job 状态" @(
    "get", "vcjob", "--all-namespaces", "--output", "json", "--request-timeout=15s"
)
$storageData = Get-JsonOutput "盘点 Kubernetes StorageClass" @(
    "get", "storageclass", "--output", "json", "--request-timeout=15s"
)
$targetNamespace = Get-JsonOutput "查看 MEFKT 目标 namespace" @(
    "get", "namespace", $Namespace, "--output", "json", "--request-timeout=15s"
)
$targetQuota = Get-JsonOutput "查看 MEFKT 目标 namespace ResourceQuota" @(
    "get", "resourcequota", "--namespace", $Namespace, "--output", "json", "--request-timeout=15s"
)
$targetLimits = Get-JsonOutput "查看 MEFKT 目标 namespace LimitRange" @(
    "get", "limitrange", "--namespace", $Namespace, "--output", "json", "--request-timeout=15s"
)
$targetPvc = Get-JsonOutput "查看 MEFKT 目标 namespace PVC" @(
    "get", "pvc", "--namespace", $Namespace, "--output", "json", "--request-timeout=15s"
)

$gpuNodes = @()
if ($gpuNodeData) {
    $gpuNodes = @($gpuNodeData.items | ForEach-Object {
            $ready = @($_.status.conditions | Where-Object {$_.type -eq "Ready"} | Select-Object -Last 1).status
            [ordered]@{
                name = $_.metadata.name
                ready = $ready
                cpu_allocatable = Get-ResourceValue $_.status.allocatable "cpu"
                memory_allocatable = Get-ResourceValue $_.status.allocatable "memory"
                gpu_allocatable = Get-ResourceValue $_.status.allocatable "nvidia.com/gpu"
                gpu_capacity = Get-ResourceValue $_.status.capacity "nvidia.com/gpu"
            }
        })
}

$gpuPods = @()
if ($podData) {
    $gpuPods = @($podData.items | ForEach-Object {
            $gpu = @($_.spec.containers | ForEach-Object {
                    Get-NestedResourceValue $_.resources "requests" "nvidia.com/gpu"
                } | Where-Object {$_})
            if ($gpu.Count -gt 0) {
                [ordered]@{
                    namespace = $_.metadata.namespace
                    name = $_.metadata.name
                    node = $_.spec.nodeName
                    phase = $_.status.phase
                    gpu_requests = @($gpu)
                }
            }
        } | Where-Object {$_})
}

$quotas = @()
if ($quotaData) {
    $quotas = @($quotaData.items | ForEach-Object {
            [ordered]@{
                namespace = $_.metadata.namespace
                name = $_.metadata.name
                hard = $_.status.hard
                used = $_.status.used
            }
        })
}

$queues = @()
if ($queueData) {
    $queues = @($queueData.items | ForEach-Object {
            $queueNamespace = Get-OptionalPropertyValue $_.metadata "namespace"
            $queueNamespace = if ($queueNamespace) {
                [string]$queueNamespace
            } else {
                "<cluster-scoped>"
            }
            $annotations = Get-OptionalPropertyValue $_.metadata "annotations"
            $parent = Get-OptionalPropertyValue $annotations "scheduling.volcano.sh/parent-queue"
            [ordered]@{
                namespace = $queueNamespace
                name = $_.metadata.name
                state = Get-OptionalPropertyValue $_.status "state"
                weight = Get-OptionalPropertyValue $_.spec "weight"
                parent = $parent
                reclaimable = Get-OptionalPropertyValue $_.spec "reclaimable"
                capability = Get-OptionalPropertyValue $_.spec "capability"
                deserved = Get-OptionalPropertyValue $_.status "deserved"
            }
        })
}

$jobs = @()
if ($jobData) {
    $jobs = @($jobData.items | ForEach-Object {
            [ordered]@{
                namespace = $_.metadata.namespace
                name = $_.metadata.name
                phase = $_.status.state.phase
                min_available = $_.spec.minAvailable
                queue = $_.spec.queue
                created = $_.metadata.creationTimestamp
            }
        })
}

$permissions = [ordered]@{}
foreach ($check in @(
        @("get", "nodes"),
        @("get", "resourcequotas", "--all-namespaces"),
        @("get", "limitranges", "--all-namespaces"),
        @("get", "queue", "--all-namespaces"),
        @("create", "pods", "--namespace", $Namespace),
        @("create", "jobs.batch.volcano.sh", "--namespace", $Namespace),
        @("create", "persistentvolumeclaims", "--namespace", $Namespace)
    )) {
    $key = ($check -join " ")
    $permissions[$key] = Invoke-LoggedRead "检查 MEFKT 权限 $key" (@("auth", "can-i") + $check)
}

$summary = [ordered]@{
    schema = "mefkt-cluster-inventory-v1"
    recorded_at_utc = [DateTime]::UtcNow.ToString("o")
    namespace = $Namespace
    kubeconfig = "<redacted-prd-kubeconfig>"
    api_version = $apiVersion
    gpu_nodes = $gpuNodes
    running_gpu_pods = $gpuPods
    resource_quotas = $quotas
    limit_ranges = if ($limitData) { @($limitData.items) } else { @() }
    volcano_queues = $queues
    volcano_jobs = $jobs
    storage_classes = if ($storageData) { @($storageData.items | ForEach-Object {[ordered]@{name = $_.metadata.name; provisioner = $_.provisioner; reclaim_policy = $_.reclaimPolicy; volume_binding_mode = $_.volumeBindingMode}}) } else { @() }
    target_namespace = if ($targetNamespace) {[ordered]@{name = $targetNamespace.metadata.name; phase = $targetNamespace.status.phase}} else {$null}
    target_resource_quotas = if ($targetQuota) {@($targetQuota.items)} else {@()}
    target_limit_ranges = if ($targetLimits) {@($targetLimits.items)} else {@()}
    target_pvcs = if ($targetPvc) {@($targetPvc.items | ForEach-Object {[ordered]@{name = $_.metadata.name; status = $_.status.phase; storage_class = $_.spec.storageClassName; capacity = $_.status.capacity}})} else {@()}
    permissions = $permissions
    errors = @($errors)
}

$output = [System.IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
$summary | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $output -Encoding utf8
Write-Output "inventory=$output"
Write-Output "gpu_nodes=$($gpuNodes.Count) running_gpu_pods=$($gpuPods.Count) resource_quotas=$($quotas.Count) queues=$($queues.Count) jobs=$($jobs.Count) errors=$($errors.Count)"
