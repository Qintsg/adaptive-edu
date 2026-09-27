# 答辩演示包恢复脚本。只重置演示专用 Compose 项目及其卷。
param(
    [string]$BundleDirectory = 'C:\Users\qintsg\Desktop\adaptive-edu-defense-20260927',
    [switch]$KeepCurrentImages,
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
$adjacentBundle = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $BundleDirectory -PathType Container) -and
    (Test-Path -LiteralPath (Join-Path $adjacentBundle 'images.tar') -PathType Leaf)) {
    $BundleDirectory = $adjacentBundle
}
$bundlePath = (Resolve-Path -LiteralPath $BundleDirectory).Path
$imageArchive = Join-Path $bundlePath 'images.tar'
$dbArchive = Join-Path $bundlePath 'postgres-baseline.dump'
$assetsArchive = Join-Path $bundlePath 'media-rag-baseline.tar'

$requiredArchives = @($dbArchive, $assetsArchive)
if (-not $KeepCurrentImages) { $requiredArchives += $imageArchive }
foreach ($archive in $requiredArchives) {
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "缺少恢复文件：$archive" }
}

$manifestPath = Join-Path $bundlePath 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    $manifestPath = Join-Path $bundlePath 'baseline-manifest.json'
}
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($item in $manifest.archives) {
        if ($KeepCurrentImages -and $item.name -eq 'images.tar') { continue }
        $archivePath = Join-Path $bundlePath $item.name
        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $item.sha256) { throw "恢复文件校验失败：$($item.name)" }
    }
}

if (-not $KeepCurrentImages) {
    & docker load -i $imageArchive
    if ($LASTEXITCODE -ne 0) { throw 'Docker 镜像载入失败。' }
}

& docker @composeArgs down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw '演示专用卷重置失败。' }

& docker @composeArgs up -d --wait --no-build postgres neo4j
if ($LASTEXITCODE -ne 0) { throw '演示数据库启动失败。' }

$postgresContainer = (& docker @composeArgs ps -q postgres).Trim()
if (-not $postgresContainer) { throw '找不到演示 PostgreSQL 容器。' }
& docker cp $dbArchive "${postgresContainer}:/tmp/postgres-baseline.dump"
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 快照传入失败。' }
& docker exec $postgresContainer pg_restore -U demo -d adaptive_edu_demo `
    --clean --if-exists --no-owner --no-privileges --exit-on-error /tmp/postgres-baseline.dump
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 快照恢复失败。' }

& docker @composeArgs up -d --wait --no-build backend
if ($LASTEXITCODE -ne 0) { throw '演示后端启动失败。' }

$backendContainer = (& docker @composeArgs ps -q backend).Trim()
if (-not $backendContainer) { throw '找不到演示后端容器。' }
& docker cp $assetsArchive "${backendContainer}:/tmp/media-rag-baseline.tar"
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 归档传入失败。' }
& docker exec $backendContainer tar -C /app/backend -xf /tmp/media-rag-baseline.tar
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 归档恢复失败。' }

& docker @composeArgs exec -T backend python tools.py neo4j-sync-all
if ($LASTEXITCODE -ne 0) { throw 'Neo4j 图谱重建失败。' }
& docker @composeArgs exec -T backend python demo_seed.py --verify-baseline
if ($LASTEXITCODE -ne 0) { throw '恢复后演示基线验收失败。' }

& docker @composeArgs up -d --wait --no-build web
if ($LASTEXITCODE -ne 0) { throw '演示网页启动失败。' }

Write-Host '演示基线已恢复：http://127.0.0.1:18080'
