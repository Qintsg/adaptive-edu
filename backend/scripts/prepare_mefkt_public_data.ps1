<#
文件内容描述：下载、转换并合并 MEFKT 跨领域公开训练数据。
@Project : adaptive-edu
@File : prepare_mefkt_public_data.ps1
@Author : Qintsg
@Date : 2026-08-24

说明：
1. 下载 SLAM English-Spanish 与 Atomi/ASSISTments2009 的公开 Parquet。
2. 生成统一 canonical CSV 和冻结 384 维内容向量。
3. 不访问 Kubernetes；输出可直接交给 submit_mefkt_training.ps1 上传。
#>

[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [int]$EmbeddingBatchSize = 128,
    [ValidateSet("cpu", "cuda")]
    [string]$EmbeddingDevice = "cpu",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$OutputRoot = if ($OutputRoot) {
    [System.IO.Path]::GetFullPath($OutputRoot, $BackendRoot)
} else {
    Join-Path $BackendRoot "runtime_data\mefkt-public"
}

$SlamRoot = Join-Path $OutputRoot "slam-en-es"
$AssistmentsRoot = Join-Path $OutputRoot "assistments2009"
$MixedRoot = Join-Path $OutputRoot "mixed"
$SlamRaw = Join-Path $SlamRoot "raw"
$SlamCanonical = Join-Path $SlamRoot "canonical"
$AssistmentsRaw = Join-Path $AssistmentsRoot "raw"
$AssistmentsCanonical = Join-Path $AssistmentsRoot "canonical"
$MixedCanonical = Join-Path $MixedRoot "canonical"

function Invoke-CheckedCommand {
    <#
    执行外部命令并检查退出码。

    :param FilePath: 可执行文件路径或名称。
    :param Arguments: 参数数组。
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令执行失败：$FilePath $($Arguments -join ' ')"
    }
}

function Save-PublicFile {
    <#
    下载公开文件，已有非空文件时直接复用。

    :param Url: HTTPS 下载地址。
    :param Destination: 本地目标文件。
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destination
    )
    if (-not $Force -and (Test-Path -LiteralPath $Destination -PathType Leaf) -and (Get-Item -LiteralPath $Destination).Length -gt 0) {
        Write-Host "复用公开数据：$Destination"
        return
    }
    New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
    $partial = "$Destination.part"
    if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
    }
    Invoke-CheckedCommand "curl.exe" @("-L", "--fail", "--show-error", "--output", $partial, $Url)
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

foreach ($directory in @($SlamRaw, $SlamCanonical, $AssistmentsRaw, $AssistmentsCanonical, $MixedCanonical)) {
    New-Item -ItemType Directory -Force $directory | Out-Null
}

$SlamBaseUrl = "https://huggingface.co/datasets/bihungba1101/slam-en-es-knowledge-tracing/resolve/refs%2Fconvert%2Fparquet/default"
foreach ($split in @("train", "validation", "test")) {
    Save-PublicFile "$SlamBaseUrl/$split/0000.parquet" (Join-Path $SlamRaw "$split.parquet")
}
$AssistmentsUrl = "https://huggingface.co/datasets/Atomi/ASSISTments2009/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet"
Save-PublicFile $AssistmentsUrl (Join-Path $AssistmentsRaw "train.parquet")

Push-Location $BackendRoot
try {
    Invoke-CheckedCommand "uv" @(
        "run", "python", "scripts\convert_slam_to_canonical.py",
        "--input-dir", $SlamRaw,
        "--output-dir", $SlamCanonical
    )
    Invoke-CheckedCommand "uv" @(
        "run", "python", "scripts\convert_assistments_to_canonical.py",
        "--input", (Join-Path $AssistmentsRaw "train.parquet"),
        "--output", (Join-Path $AssistmentsCanonical "events.csv")
    )
    Invoke-CheckedCommand "uv" @(
        "run", "python", "scripts\merge_mefkt_canonical.py",
        "--input", (Join-Path $SlamCanonical "train.csv"),
        "--input", (Join-Path $AssistmentsCanonical "events.csv"),
        "--output", (Join-Path $MixedCanonical "train.csv")
    )
    Invoke-CheckedCommand "uv" @(
        "run", "python", "scripts\prepare_mefkt_content_embeddings.py",
        "--events-file", (Join-Path $MixedCanonical "train.csv"),
        "--output", (Join-Path $MixedRoot "item_content_embeddings.npz"),
        "--batch-size", [string]$EmbeddingBatchSize,
        "--device", $EmbeddingDevice
    )
} finally {
    Pop-Location
}

Write-Host "公开训练数据准备完成："
Write-Host "  events=$(Join-Path $MixedCanonical 'train.csv')"
Write-Host "  embeddings=$(Join-Path $MixedRoot 'item_content_embeddings.npz')"
