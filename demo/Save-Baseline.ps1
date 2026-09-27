# 保存未测评数据基线，供真实 AI 采样后恢复，不导出应用镜像。
param(
    [string]$OutputDirectory = 'C:\Users\qintsg\Desktop\adaptive-edu-defense-20260927'
)

$ErrorActionPreference = 'Stop'
$composeFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'compose.yaml')).Path
$projectName = 'adaptive-edu-defense-demo'
$composeArgs = @('compose', '-f', $composeFile, '-p', $projectName)
$outputPath = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$dbArchive = Join-Path $outputPath 'postgres-baseline.dump'
$assetsArchive = Join-Path $outputPath 'media-rag-baseline.tar'

& docker @composeArgs exec -T backend python demo_seed.py --verify-baseline
if ($LASTEXITCODE -ne 0) { throw 'student2 已产生测评，不能保存未测评基线。' }

$postgresContainer = (& docker @composeArgs ps -q postgres).Trim()
$backendContainer = (& docker @composeArgs ps -q backend).Trim()
if (-not $postgresContainer -or -not $backendContainer) { throw '演示容器未启动。' }

& docker exec $postgresContainer pg_dump -U demo -d adaptive_edu_demo -Fc -f /tmp/postgres-baseline.dump
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 基线导出失败。' }
& docker cp "${postgresContainer}:/tmp/postgres-baseline.dump" $dbArchive
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 基线复制失败。' }

& docker exec $backendContainer tar -C /app/backend -cf /tmp/media-rag-baseline.tar media runtime_logs/rag
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 基线归档失败。' }
& docker cp "${backendContainer}:/tmp/media-rag-baseline.tar" $assetsArchive
if ($LASTEXITCODE -ne 0) { throw '课程文件与 RAG 基线复制失败。' }

$manifest = [ordered]@{
    project = $projectName
    created_at = (Get-Date).ToString('o')
    archives = @(@($dbArchive, $assetsArchive) | ForEach-Object {
        $item = Get-Item -LiteralPath $_
        [ordered]@{
            name = $item.Name
            bytes = $item.Length
            sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputPath 'baseline-manifest.json') -Encoding utf8
Write-Host "数据基线已保存到：$outputPath"
