<#
文件内容描述：创建并验证 MEFKT 长期训练使用的 advisor namespace、配额、限制和 Volcano GPU 队列。
@Project : adaptive-edu
@File : provision_mefkt_namespace.ps1
@Author : Qintsg
@Date : 2026-08-25

所有远端 Kubernetes 操作都通过 BBT-7 日志包装器执行。
#>

[CmdletBinding()]
param(
    [string]$Namespace = "advisor-rhw",
    [string]$Queue = "advisor-rhw-gpu",
    [string]$KubernetesRoot = "E:\Projects\BBT\Kubernetes-bbt",
    [string]$Kubeconfig = "$env:USERPROFILE\.kube\prd.yaml",
    [switch]$RenderOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$KubernetesRoot = (Resolve-Path $KubernetesRoot).Path
$Wrapper = Join-Path $KubernetesRoot "scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1"
$ManifestPath = Join-Path $env:TEMP "$Namespace-mefkt.yaml"

if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
    throw "找不到 BBT-7 Kubernetes 日志包装器：$Wrapper"
}
if ($Namespace -notmatch '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$') {
    throw "Namespace 不是合法的 Kubernetes DNS 名称：$Namespace"
}
if ($Queue -notmatch '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$') {
    throw "Queue 不是合法的 Kubernetes DNS 名称：$Queue"
}

function New-MefktNamespaceManifest {
    <#
    生成 MEFKT 长期训练 namespace 的声明式清单。

    :returns: 多文档 YAML 文本。
    #>
    return @"
apiVersion: v1
kind: Namespace
metadata:
  name: $Namespace
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: ns-default-quota
  namespace: $Namespace
  labels:
    hpc.bbt.sspu.edu.cn/quota-tier: default
spec:
  hard:
    count/configmaps: "50"
    count/jobs.batch: "20"
    count/jobs.batch.volcano.sh: "20"
    count/persistentvolumeclaims: "15"
    count/pods: "30"
    count/secrets: "30"
    count/services: "5"
    juicefs-sc.storageclass.storage.k8s.io/requests.storage: 500Gi
    limits.cpu: "32"
    limits.memory: 256Gi
    nfs-client.storageclass.storage.k8s.io/requests.storage: 200Gi
    requests.cpu: "16"
    requests.memory: 128Gi
    requests.storage: 200Gi
---
apiVersion: v1
kind: LimitRange
metadata:
  name: ns-default-limits
  namespace: $Namespace
  labels:
    hpc.bbt.sspu.edu.cn/managed-by: kubectl
  annotations:
    hpc.bbt.sspu.edu.cn/description: 默认 LimitRange。新 Pod 若不写 resources，自动注入默认值。
spec:
  limits:
    - type: Container
      min:
        cpu: 100m
        memory: 128Mi
      max:
        cpu: "32"
        memory: 256Gi
      default:
        cpu: "2"
        memory: 4Gi
      defaultRequest:
        cpu: "1"
        memory: 2Gi
      maxLimitRequestRatio:
        cpu: "4"
        memory: "4"
    - type: PersistentVolumeClaim
      min:
        storage: 1Gi
      max:
        storage: 200Gi
---
apiVersion: queue.gro.sspu.edu.cn/v1alpha1
kind: Queue
metadata:
  name: $Queue
  annotations:
    scheduling.volcano.sh/parent-queue: gpu-pool
spec:
  capability:
    nvidia.com/gpu: "16"
  reclaimable: true
  weight: 1
---
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: $Queue
spec:
  weight: 1
  parent: root
  reclaimable: true
  dequeueStrategy: traverse
  capability:
    nvidia.com/gpu: "16"
"@
}

function Invoke-LoggedKubectl {
    <#
    通过 BBT-7 日志包装器执行一条 Kubernetes 命令。

    :param Reason: 操作原因。
    :param KubectlArgs: 传给 kubectl 的参数数组。
    :returns: kubectl 标准输出。
    #>
    param(
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string[]]$KubectlArgs
    )
    & $Wrapper -Reason $Reason -Kubeconfig $Kubeconfig -KubectlArgs $KubectlArgs
}

$manifest = New-MefktNamespaceManifest
if ($RenderOnly) {
    Write-Output $manifest
    return
}

try {
    [System.IO.File]::WriteAllText($ManifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))
    Invoke-LoggedKubectl "创建或更新 MEFKT 长期训练 namespace、配额和限制" @(
        "apply", "--filename", $ManifestPath
    ) | Out-Host

    Invoke-LoggedKubectl "验证 MEFKT namespace $Namespace" @(
        "get", "namespace", $Namespace, "--request-timeout=15s",
        "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase"
    ) | Out-Host
    Invoke-LoggedKubectl "验证 MEFKT namespace $Namespace 配额和限制" @(
        "get", "resourcequota,limitrange", "--namespace", $Namespace,
        "--request-timeout=15s", "-o", "wide"
    ) | Out-Host
    Invoke-LoggedKubectl "验证 MEFKT GRO GPU 队列 $Queue" @(
        "get", "queues.queue.gro.sspu.edu.cn", $Queue, "--request-timeout=15s", "-o", "wide"
    ) | Out-Host
    Invoke-LoggedKubectl "验证 MEFKT 原生 Volcano GPU 队列 $Queue" @(
        "get", "queues.scheduling.volcano.sh", $Queue, "--request-timeout=15s", "-o", "wide"
    ) | Out-Host
} finally {
    if (Test-Path -LiteralPath $ManifestPath) {
        Remove-Item -LiteralPath $ManifestPath -Force
    }
}
