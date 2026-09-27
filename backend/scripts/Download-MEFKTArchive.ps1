<#
文件内容描述：通过 BBT-7 日志包装器分块下载已冻结的 MEFKT 归档并校验摘要。
@Project : adaptive-edu
@File : Download-MEFKTArchive.ps1
@Author : Qintsg
@Date : 2026-09-24

临时分块仅存在导出 Pod 的 /scratch 与桌面归档目录。
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ArchiveName,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [string]$DesktopRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MEFKT-NG-20260924-archive'),
    [string]$Namespace = 'advisor-rhw',
    [string]$PodName = 'mefkt-ng-export-20260924',
    [int]$ChunkMiB = 32,
    [string]$LoggedKubectl = 'E:\Projects\BBT\Kubernetes-bbt\scheduling\bbt-7\Invoke-BBT7LoggedKubectl.ps1',
    [string]$Kubeconfig = (Join-Path $env:USERPROFILE '.kube\prd.yaml')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($ArchiveName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*\.tar$' -or
    $ExpectedSha256 -notmatch '^[A-Fa-f0-9]{64}$' -or $ChunkMiB -lt 1 -or $ChunkMiB -gt 64) {
    throw '归档名、SHA-256 或分块大小非法'
}
$desktop = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath('Desktop'))
$root = [System.IO.Path]::GetFullPath($DesktopRoot)
if (-not $root.StartsWith($desktop + [System.IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $root -PathType Container)) {
    throw '输出必须是桌面下已创建的归档目录'
}
$partsDirectory = Join-Path $root "transfer\$ArchiveName.parts"
$archivePath = Join-Path $root "transfer\$ArchiveName"
[System.IO.Directory]::CreateDirectory($partsDirectory) | Out-Null
$remoteFile = "/scratch/$ArchiveName"
$remoteParts = "$remoteFile.parts"

function Invoke-LoggedKubectl {
    <#
    经 BBT-7 包装器执行已记录的 kubectl。
    :param Reason: 操作原因。
    :param KubectlArgs: kubectl 参数数组。
    :returns: 包装器输出。
    #>
    param([string]$Reason, [string[]]$KubectlArgs)
    & $LoggedKubectl -Reason $Reason -Kubeconfig $Kubeconfig -KubectlArgs $KubectlArgs
}

$existing = Test-Path -LiteralPath $archivePath -PathType Leaf
if ($existing) {
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
    if ($hash.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "已有归档摘要不符，拒绝覆盖：$archivePath"
    }
    Write-Output "已存在且校验通过：$archivePath"
    return
}

$bytes = [long]$ChunkMiB * 1048576
Invoke-LoggedKubectl "将 $ArchiveName 分割为 $ChunkMiB MiB 块" @(
    'exec', '-n', $Namespace, $PodName, '--container', 'export', '--',
    'sh', '-c', "mkdir -p '$remoteParts' && split -b $bytes '$remoteFile' '$remoteParts/part-'"
) | Out-Null
$listing = (Invoke-LoggedKubectl "列出 $ArchiveName 的远端分块" @(
        'exec', '-n', $Namespace, $PodName, '--container', 'export', '--',
        'sh', '-c', "ls -1 '$remoteParts'/part-*"
    ) | Out-String).Trim()
$chunks = @($listing -split "`r?`n" | Where-Object { $_ })
if ($chunks.Count -eq 0) { throw "未找到远端分块：$ArchiveName" }

Push-Location (Split-Path -Parent $root)
try {
    foreach ($remoteChunk in $chunks) {
        $name = [System.IO.Path]::GetFileName($remoteChunk)
        if ($name -notmatch '^part-[a-z]{2,}$') { throw "远端分块名称异常：$name" }
        $localChunk = Join-Path $partsDirectory $name
        $remoteHash = ((Invoke-LoggedKubectl "核对 $ArchiveName 远端分块 $name 摘要" @(
                    'exec', '-n', $Namespace, $PodName, '--container', 'export', '--',
                    'sha256sum', $remoteChunk
                ) | Out-String).Trim() -split '\s+')[0]
        if (Test-Path -LiteralPath $localChunk -PathType Leaf) {
            $localHash = (Get-FileHash -LiteralPath $localChunk -Algorithm SHA256).Hash
            if ($localHash.ToLowerInvariant() -eq $remoteHash.ToLowerInvariant()) { continue }
            Remove-Item -LiteralPath $localChunk -Force
        }
        $relative = [System.IO.Path]::GetRelativePath((Get-Location).Path, $localChunk).Replace([char]92, [char]47)
        $copied = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Invoke-LoggedKubectl "下载 $ArchiveName 分块 $name（第 $attempt 次）" @(
                    'cp', "$Namespace/${PodName}:$remoteChunk", $relative, '--container', 'export'
                ) | Out-Null
                $localHash = (Get-FileHash -LiteralPath $localChunk -Algorithm SHA256).Hash
                if ($localHash.ToLowerInvariant() -ne $remoteHash.ToLowerInvariant()) {
                    throw "分块摘要不一致：$ArchiveName/$name"
                }
                $copied = $true
                break
            } catch {
                if (Test-Path -LiteralPath $localChunk) { Remove-Item -LiteralPath $localChunk -Force }
                if ($attempt -eq 3) { throw }
                Start-Sleep -Seconds 2
            }
        }
        if (-not $copied) { throw "下载分块失败：$ArchiveName/$name" }
    }
} finally {
    Pop-Location
}

$assembling = "$archivePath.assembling"
if (Test-Path -LiteralPath $assembling) { throw "存在未完成的归档拼接：$assembling" }
$output = [System.IO.File]::Open($assembling, [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try {
    foreach ($remoteChunk in $chunks) {
        $source = [System.IO.File]::OpenRead((Join-Path $partsDirectory ([System.IO.Path]::GetFileName($remoteChunk))))
        try { $source.CopyTo($output) }
        finally { $source.Dispose() }
    }
    $output.Flush($true)
} finally {
    $output.Dispose()
}
$actual = (Get-FileHash -LiteralPath $assembling -Algorithm SHA256).Hash
if ($actual.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "完整归档 SHA-256 不一致：$ArchiveName"
}
[System.IO.File]::Move($assembling, $archivePath)
foreach ($remoteChunk in $chunks) {
    Remove-Item -LiteralPath (Join-Path $partsDirectory ([System.IO.Path]::GetFileName($remoteChunk))) -Force
}
Remove-Item -LiteralPath $partsDirectory
[pscustomobject]@{ archive=$archivePath; bytes=(Get-Item -LiteralPath $archivePath).Length;
                   chunks=$chunks.Count; sha256=$actual.ToLowerInvariant() } | ConvertTo-Json -Compress
