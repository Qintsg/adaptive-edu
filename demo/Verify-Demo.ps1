# 答辩演示数据验收脚本。默认核查交付基线，student2 必须尚未测评。
param(
    [switch]$RuntimeOnly
)

$ErrorActionPreference = 'Stop'
$composeFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'compose.yaml')).Path
$projectName = 'adaptive-edu-defense-demo'
$mode = if ($RuntimeOnly) { '--verify-runtime' } else { '--verify-baseline' }

& docker compose -f $composeFile -p $projectName exec -T backend python demo_seed.py $mode
if ($LASTEXITCODE -ne 0) { throw '演示数据验收失败。' }
