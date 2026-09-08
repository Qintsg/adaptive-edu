<#
文件内容描述：按文件名顺序重组分片保存的 MEFKT PyTorch checkpoint。
@Project : adaptive-edu
@File : repair_mefkt_checkpoint_parts.ps1
@Author : Qintsg
@Date : 2026-08-30

脚本先写入临时文件；使用 -Force 替换已有目标时，会先保留原文件备份。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PartsDirectory,
    [Parameter(Mandatory)]
    [string]$OutputPath,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Repair-CheckpointParts {
    <#
    将 checkpoint 分片顺序复制到一个完整文件。

    :param PartsDirectory: 分片所在目录。
    :param OutputPath: 输出 checkpoint 路径。
    :param Force: 是否在备份后替换已有输出文件。
    :returns: 输出文件信息。
    #>
    param(
        [Parameter(Mandatory)][string]$PartsDirectory,
        [Parameter(Mandatory)][string]$OutputPath,
        [switch]$Force
    )

    $partsPath = [System.IO.Path]::GetFullPath($PartsDirectory)
    $outputPath = [System.IO.Path]::GetFullPath($OutputPath)
    if (-not (Test-Path -LiteralPath $partsPath -PathType Container)) {
        throw "找不到 checkpoint 分片目录：$partsPath"
    }

    $parts = @(Get-ChildItem -LiteralPath $partsPath -File | Where-Object {$_.Name -match '\.part-[a-z]+$'} | Sort-Object Name)
    if ($parts.Count -eq 0) {
        throw "分片目录中没有匹配 *.part-* 的文件：$partsPath"
    }
    if ((Test-Path -LiteralPath $outputPath) -and -not $Force) {
        throw "输出文件已存在；如需替换请显式指定 -Force：$outputPath"
    }

    $outputDirectory = Split-Path -Parent $outputPath
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $temporaryPath = "$outputPath.repairing"
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }

    $totalBytes = [int64]0
    $bufferSize = 1024 * 1024
    $outputStream = [System.IO.File]::Open($temporaryPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        foreach ($part in $parts) {
            $inputStream = [System.IO.File]::OpenRead($part.FullName)
            try {
                $inputStream.CopyTo($outputStream, $bufferSize)
            } finally {
                $inputStream.Dispose()
            }
            $totalBytes += [int64]$part.Length
        }
    } finally {
        $outputStream.Dispose()
    }

    $temporaryBytes = (Get-Item -LiteralPath $temporaryPath).Length
    if ($temporaryBytes -ne $totalBytes -or $temporaryBytes -le 0) {
        Remove-Item -LiteralPath $temporaryPath -Force
        throw "分片重组大小校验失败：expected=$totalBytes actual=$temporaryBytes"
    }

    $backupPath = $null
    if (Test-Path -LiteralPath $outputPath) {
        $backupPath = "$outputPath.corrupt-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Move-Item -LiteralPath $outputPath -Destination $backupPath
    }
    Move-Item -LiteralPath $temporaryPath -Destination $outputPath

    [ordered]@{
        output = $outputPath
        parts = $parts.Count
        bytes = $totalBytes
        backup = $backupPath
    }
}

Repair-CheckpointParts -PartsDirectory $PartsDirectory -OutputPath $OutputPath -Force:$Force | ConvertTo-Json -Compress
