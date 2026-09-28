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
$imagesBuilt = $false
if (-not $SkipBuild -and $hasSource) {
    if (-not $selectedEnvFile -or -not (Test-DemoEnvHasApiKey -Path $selectedEnvFile)) {
        throw '从源码构建答辩镜像前，需要在私有 env 文件中配置 DEMO_LLM_API_KEY。'
    }
    & docker @composeArgs build backend web
    if ($LASTEXITCODE -ne 0) { throw '演示镜像构建失败。' }
    $imagesBuilt = $true
}

& docker @composeArgs up -d --wait --no-build
if ($LASTEXITCODE -ne 0) { throw '演示环境启动失败。' }

if ($imagesBuilt) {
    & docker @composeArgs up -d --wait --no-build --force-recreate --no-deps backend web
    if ($LASTEXITCODE -ne 0) { throw '新构建的应用镜像切换失败。' }
}

& docker @composeArgs exec -T backend python demo_seed.py --verify-runtime
if ($LASTEXITCODE -ne 0) { throw '演示数据运行状态验收失败。' }

Write-Host '演示环境已启动：http://127.0.0.1:18080'
