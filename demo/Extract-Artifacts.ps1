# 从答辩工件镜像中提取手册、截图和录屏。
param(
    [string]$OutputDirectory = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'adaptive-edu-defense-20260927\artifacts'),
    [string]$Image = 'adaptive-edu-defense-artifacts:2026-09-27'
)

$ErrorActionPreference = 'Stop'
$outputPath = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$containerId = (& docker create $Image).Trim()
if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw '无法创建工件镜像临时容器。' }

try {
    & docker cp "${containerId}:/artifacts/." $outputPath
    if ($LASTEXITCODE -ne 0) { throw '工件提取失败。' }
} finally {
    & docker rm $containerId | Out-Null
}

Write-Host "工件已提取到：$outputPath"
