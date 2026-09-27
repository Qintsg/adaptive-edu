# 答辩演示包导出脚本：保存镜像、PostgreSQL 基线和媒体/RAG 文件。
param(
    [string]$OutputDirectory = 'C:\Users\qintsg\Desktop\adaptive-edu-defense-20260927'
)

$ErrorActionPreference = 'Stop'
$composeFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'compose.yaml')).Path
$projectName = 'adaptive-edu-defense-demo'
$composeArgs = @('compose', '-f', $composeFile, '-p', $projectName)
$outputPath = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$imageArchive = Join-Path $outputPath 'images.tar'
$dbArchive = Join-Path $outputPath 'postgres-baseline.dump'
$assetsArchive = Join-Path $outputPath 'media-rag-baseline.tar'
$artifactSource = Join-Path $PSScriptRoot 'artifacts'
$screenshotDirectory = Join-Path $artifactSource 'screenshots'
$recordingDirectory = Join-Path $artifactSource 'recordings'
$screenshots = @(Get-ChildItem -LiteralPath $screenshotDirectory -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @('.png', '.jpg', '.jpeg') })
$recordings = @(Get-ChildItem -LiteralPath $recordingDirectory -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @('.mp4', '.webm') })
if ($screenshots.Count -eq 0 -or $recordings.Count -eq 0) {
    throw '请先把页面截图和录屏放入 demo/artifacts，再导出最终演示包。'
}

& docker @composeArgs exec -T backend python demo_seed.py --verify-baseline
if ($LASTEXITCODE -ne 0) { throw 'student2 已产生测评或演示数据不完整，不能导出基线。' }

$postgresContainer = (& docker @composeArgs ps -q postgres).Trim()
$backendContainer = (& docker @composeArgs ps -q backend).Trim()
if (-not $postgresContainer -or -not $backendContainer) { throw '演示容器未启动。' }

& docker exec $postgresContainer pg_dump -U demo -d adaptive_edu_demo -Fc -f /tmp/postgres-baseline.dump
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 快照导出失败。' }
& docker cp "${postgresContainer}:/tmp/postgres-baseline.dump" $dbArchive
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 快照复制失败。' }

& docker exec $backendContainer tar -C /app/backend -cf /tmp/media-rag-baseline.tar media runtime_logs/rag
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 归档失败。' }
& docker cp "${backendContainer}:/tmp/media-rag-baseline.tar" $assetsArchive
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 归档复制失败。' }

& docker @composeArgs build artifacts
if ($LASTEXITCODE -ne 0) { throw '演示工件镜像构建失败。' }

& docker save -o $imageArchive `
    adaptive-edu-defense-backend:2026-09-27 `
    adaptive-edu-defense-web:2026-09-27 `
    adaptive-edu-defense-artifacts:2026-09-27 `
    postgres:17.10-alpine3.23 `
    neo4j:2026.06.0
if ($LASTEXITCODE -ne 0) { throw 'Docker 镜像导出失败。' }

$artifactTarget = Join-Path $outputPath 'artifacts'
New-Item -ItemType Directory -Path $artifactTarget -Force | Out-Null
Copy-Item -Path (Join-Path $artifactSource '*') -Destination $artifactTarget -Recurse -Force

$portableDemoDirectory = Join-Path $outputPath 'demo'
New-Item -ItemType Directory -Path $portableDemoDirectory -Force | Out-Null
foreach ($fileName in @(
    'compose.yaml',
    'Start-Demo.ps1',
    'Restore-Demo.ps1',
    'Verify-Demo.ps1',
    'Save-Baseline.ps1',
    'Copy-AI-Capture.ps1',
    'Extract-Artifacts.ps1',
    '.env.example'
)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $fileName) -Destination (Join-Path $portableDemoDirectory $fileName) -Force
}

$archives = @($imageArchive, $dbArchive, $assetsArchive)
$imageNames = @(
    'adaptive-edu-defense-backend:2026-09-27',
    'adaptive-edu-defense-web:2026-09-27',
    'adaptive-edu-defense-artifacts:2026-09-27',
    'postgres:17.10-alpine3.23',
    'neo4j:2026.06.0'
)
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourcePaths = @(& git -C $repositoryRoot -c core.quotePath=false ls-files --cached --others --exclude-standard -- backend frontend demo)
$sourceFiles = @($sourcePaths | Sort-Object -Unique | ForEach-Object {
    $sourcePath = Join-Path $repositoryRoot ($_ -replace '/', '\')
    if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        [ordered]@{
            path = $_
            sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
})
$manifest = [ordered]@{
    project = $projectName
    created_at = (Get-Date).ToString('o')
    web_url = 'http://127.0.0.1:18080'
    source_commit = (& git -C $repositoryRoot rev-parse HEAD).Trim()
    source_dirty = [bool](& git -C $repositoryRoot status --porcelain -- backend frontend demo)
    source_files = $sourceFiles
    images = @($imageNames | ForEach-Object {
        [ordered]@{
            name = $_
            id = (& docker image inspect --format '{{.Id}}' $_).Trim()
        }
    })
    archives = @($archives | ForEach-Object {
        $item = Get-Item -LiteralPath $_
        [ordered]@{
            name = $item.Name
            bytes = $item.Length
            sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputPath 'manifest.json') -Encoding utf8
Write-Host "演示包已导出到：$outputPath"
