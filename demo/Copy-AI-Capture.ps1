# 从运行容器取回真实 AI 采样结果，供最终后端镜像使用。
param(
    [string]$ContainerPath = '/app/backend/demo_state/deepseek-v41-flash.jsonl',
    [string]$ReportOutputDirectory = 'C:\Users\qintsg\Desktop\adaptive-edu-defense-20260927\evidence'
)

$ErrorActionPreference = 'Stop'
$composeFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'compose.yaml')).Path
$projectName = 'adaptive-edu-defense-demo'
$backendContainer = (& docker compose -f $composeFile -p $projectName ps -q backend).Trim()
if (-not $backendContainer) { throw '找不到演示后端容器。' }

$presetPath = Join-Path $PSScriptRoot 'presets\deepseek-v41-flash.jsonl'
& docker cp "${backendContainer}:${ContainerPath}" $presetPath
if ($LASTEXITCODE -ne 0) { throw '真实 AI 采样结果复制失败。' }
if ((Get-Item -LiteralPath $presetPath).Length -eq 0) { throw '真实 AI 采样文件为空。' }

$reportDirectory = (New-Item -ItemType Directory -Path $ReportOutputDirectory -Force).FullName
$reportPath = Join-Path $reportDirectory 'real-ai-capture-report.json'
& docker cp "${backendContainer}:/app/backend/demo_state/real-ai-capture-report.json" $reportPath
if ($LASTEXITCODE -ne 0) { throw '真实 AI 采样报告复制失败。' }
if ((Get-Item -LiteralPath $reportPath).Length -eq 0) { throw '真实 AI 采样报告为空。' }

Write-Host "采样结果已复制到：$presetPath"
Write-Host "采样报告已复制到：$reportPath"
