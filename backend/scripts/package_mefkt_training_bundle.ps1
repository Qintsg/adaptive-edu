<#
文件内容描述：准备可上传到 Rancher/Kubernetes 训练 PVC 的 MEFKT 代码和数据包。
@Project : adaptive-edu
@File : package_mefkt_training_bundle.ps1
@Author : Qintsg
@Date : 2026-08-25

包结构：
  code/  训练、验证和曲线分析脚本
  data/  canonical 事件 CSV 和固定内容向量
  bundle_manifest.json  文件大小、SHA-256 和训练入口说明
#>

[CmdletBinding()]
param(
    [string]$BackendRoot = "",
    [string]$EventsFile = "",
    [string]$ContentEmbeddingsFile = "",
    [string]$OutputRoot = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BackendRoot) {
    # Windows PowerShell 5.1 在参数默认值求值时可能尚未初始化 $PSScriptRoot。
    $BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
}

if (-not $EventsFile) {
    $EventsFile = Join-Path $BackendRoot "runtime_logs\mefkt_mixed\canonical\train.csv"
}
if (-not $ContentEmbeddingsFile) {
    $ContentEmbeddingsFile = Join-Path $BackendRoot "runtime_logs\mefkt_mixed\item_content_embeddings.npz"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $BackendRoot "runtime_logs\mefkt_training_bundle"
}

$codeFiles = @(
    "mefkt_lite_data.py",
    "mefkt_data_core.py",
    "mefkt_canonical_data.py",
    "mefkt_early_stopping.py",
    "mefkt_evaluation.py",
    "mefkt_open_world.py",
    "mefkt_encoders.py",
    "mefkt_model_config.py",
    "mefkt_models.py",
    "mefkt_v3_models.py",
    "mefkt_optimization.py",
    "mefkt_reporting.py",
    "mefkt_plot_training.py",
    "mefkt_runtime.py",
    "mefkt_training_args.py",
    "mefkt_training_core.py",
    "mefkt_training_runtime.py",
    "mefkt_train.py",
    "diagnose_mefkt_checkpoint.py",
    "validate_mefkt_checkpoint.py"
)

function Get-FileRecord {
    <#
    生成训练包文件的校验记录。

    :param Path: 文件路径。
    :param RelativePath: 包内相对路径。
    :returns: 文件元数据。
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$RelativePath
    )
    $item = Get-Item -LiteralPath $Path
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    return [ordered]@{
        path = $RelativePath.Replace("\", "/")
        bytes = [int64]$item.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

foreach ($required in @($EventsFile, $ContentEmbeddingsFile)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "训练数据文件不存在：$required"
    }
}
$BackendRoot = (Resolve-Path -LiteralPath $BackendRoot).Path
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if ((Test-Path -LiteralPath $OutputRoot) -and -not $Force) {
    throw "输出目录已存在，如需覆盖请显式传入 -Force：$OutputRoot"
}
if (Test-Path -LiteralPath $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}

$codeRoot = Join-Path $OutputRoot "code"
$dataRoot = Join-Path $OutputRoot "data"
New-Item -ItemType Directory -Force -Path $codeRoot, $dataRoot | Out-Null

$records = [System.Collections.Generic.List[object]]::new()
foreach ($fileName in $codeFiles) {
    $source = Join-Path $BackendRoot "scripts\$fileName"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "训练包代码文件不存在：$source"
    }
    $destination = Join-Path $codeRoot $fileName
    Copy-Item -LiteralPath $source -Destination $destination
    $records.Add((Get-FileRecord -Path $destination -RelativePath "code/$fileName"))
}

$dataPairs = @(
    @($EventsFile, "train.csv"),
    @($ContentEmbeddingsFile, "item_content_embeddings.npz")
)
foreach ($pair in $dataPairs) {
    $destination = Join-Path $dataRoot ([string]$pair[1])
    Copy-Item -LiteralPath ([string]$pair[0]) -Destination $destination
    $records.Add((Get-FileRecord -Path $destination -RelativePath "data/$([string]$pair[1])"))
}

$manifest = [ordered]@{
    schema = "mefkt-training-bundle-v1"
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    profile = "full"
    dataset = "canonical-csv"
    files = @($records)
    remote_layout = [ordered]@{
        events_file = "<remote_data_root>/train.csv"
        content_embeddings_file = "<remote_data_root>/item_content_embeddings.npz"
        output_dir = "<code_pvc>/models/<job_name>"
    }
    artifacts = @(
        "train.log",
        "run_config.json",
        "training_metrics.jsonl",
        "training_metrics.csv",
        "best.pt",
        "best_auc.pt",
        "best_loss.pt",
        "last.pt",
        "runtime_validation.json",
        "diagnosis.json"
    )
}
$manifestPath = Join-Path $OutputRoot "bundle_manifest.json"
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8

$archivePath = "$OutputRoot.tar.gz"
if (Get-Command tar -ErrorAction SilentlyContinue) {
    & tar -czf $archivePath -C (Split-Path -Parent $OutputRoot) (Split-Path -Leaf $OutputRoot)
    if ($LASTEXITCODE -ne 0) {
        throw "tar 打包失败，exit=$LASTEXITCODE"
    }
} else {
    throw "系统缺少 tar，无法生成 Linux Pod 可直接解包的 tar.gz。"
}

$archiveRecord = Get-FileRecord -Path $archivePath -RelativePath ([System.IO.Path]::GetFileName($archivePath))

Write-Output "bundle_root=$OutputRoot"
Write-Output "archive=$archivePath"
Write-Output "file_count=$($records.Count)"
Write-Output "archive_bytes=$($archiveRecord.bytes)"
Write-Output "archive_sha256=$($archiveRecord.sha256)"
