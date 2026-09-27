# 答辩演示环境启动脚本。仅操作 adaptive-edu-defense-demo 项目。
param(
    [switch]$SkipBuild,
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-DemoEnvFile.ps1')
$composeFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'compose.yaml')).Path
$projectName = 'adaptive-edu-defense-demo'
$composeArgs = @('compose', '-f', $composeFile, '-p', $projectName)
$selectedEnvFile = Resolve-DemoEnvFile -EnvFile $EnvFile -ScriptDirectory $PSScriptRoot
if ($selectedEnvFile) {
    $composeArgs += @('--env-file', $selectedEnvFile)
}

$sourceRoot = Split-Path -Parent $PSScriptRoot
$hasSource = Test-Path -LiteralPath (Join-Path $sourceRoot 'backend\pyproject.toml') -PathType Leaf
if (-not $SkipBuild -and $hasSource) {
    & docker @composeArgs build backend web
    if ($LASTEXITCODE -ne 0) { throw '演示镜像构建失败。' }
}

& docker @composeArgs up -d --wait --no-build
if ($LASTEXITCODE -ne 0) { throw '演示环境启动失败。' }

& docker @composeArgs exec -T backend python demo_seed.py --verify-runtime
if ($LASTEXITCODE -ne 0) { throw '演示数据运行状态验收失败。' }

Write-Host '演示环境已启动：http://127.0.0.1:18080'
