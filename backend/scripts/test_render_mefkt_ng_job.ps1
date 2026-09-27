<#
文件内容描述：只使用假包装器验证 prd 提交顺序与源码上传路径。
@Project : adaptive-edu
@File : test_render_mefkt_ng_job.ps1
@Author : Qintsg
@Date : 2026-09-24
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptRoot '..\..')).Path
$caseId = "mefkt-ng-mock-$(Get-Date -Format 'yyyyMMddHHmmss')"
$fakeRoot = Join-Path $repoRoot "backend\runtime_logs\mefkt_ng_mock\$caseId"
$wrapperDir = Join-Path $fakeRoot 'scheduling\bbt-7'
[System.IO.Directory]::CreateDirectory($wrapperDir) | Out-Null
Copy-Item -LiteralPath (Join-Path $scriptRoot 'tests\Mock-MEFKTNGLoggedKubectl.ps1') `
    -Destination (Join-Path $wrapperDir 'Invoke-BBT7LoggedKubectl.ps1')
$fakeConfig = Join-Path $fakeRoot 'fake-kubeconfig.yaml'
$events = Join-Path $fakeRoot 'events.csv'
$content = Join-Path $fakeRoot 'content.npz'
[System.IO.File]::WriteAllText($fakeConfig, 'mock only')
[System.IO.File]::WriteAllBytes($events, [byte[]]::new(2 * 1024 * 1024 + 1))
[System.IO.File]::WriteAllText($content, 'mock sidecar')
$env:MEFKTNG_MOCK_ROOT = $fakeRoot
$env:MEFKTNG_MOCK_EVENTS = $events
$env:MEFKTNG_MOCK_CONTENT = $content
try {
    & (Join-Path $scriptRoot 'render_mefkt_ng_job.ps1') `
        -JobName $caseId -RunId $caseId -GpuCount 2 -NodeName g4 `
        -KubernetesRoot $fakeRoot -Kubeconfig $fakeConfig `
        -UploadData -LocalEventsFile $events -LocalContentFile $content `
        -ChunkUploadThresholdMiB 1 -UploadChunkMiB 1 -Submit | Out-Null
    $calls = @(Get-Content -LiteralPath (Join-Path $fakeRoot 'calls.log'))
    $uploaderCreate = @($calls | Select-String 'apply.*upload.*yaml').Count
    $codeCopy = @($calls | Select-String 'cp.*mefkt_ng/model.py').Count
    $entryCopy = @($calls | Select-String 'cp.*mefkt_ng_train.py').Count
    $dataCopy = @($calls | Select-String 'cp.*\.chunk').Count
    $invalidLocalCopy = @($calls | Where-Object { $_ -match '^cp [A-Za-z]:' }).Count
    $jobApplyIndices = @(for ($index = 0; $index -lt $calls.Count; $index++) {
        if ($calls[$index] -match 'apply.*\.yaml') { $index }
    })
    $lastCopy = -1
    for ($index = 0; $index -lt $calls.Count; $index++) {
        if ($calls[$index] -match '^cp ') { $lastCopy = $index }
    }
    if ($uploaderCreate -lt 1 -or $codeCopy -lt 1 -or $entryCopy -lt 1 -or $dataCopy -lt 3 -or
        $invalidLocalCopy -gt 0 -or
        $jobApplyIndices.Count -lt 5 -or $jobApplyIndices[-1] -le $lastCopy) {
        throw '上传 Pod、代码/数据上传或最终 Job 提交顺序不符合预期'
    }
    Write-Output "本地假集群验证通过：$($calls.Count) 条模拟命令，上传完成后才提交 Volcano Job"
} finally {
    Remove-Item Env:MEFKTNG_MOCK_ROOT,Env:MEFKTNG_MOCK_EVENTS,Env:MEFKTNG_MOCK_CONTENT -ErrorAction SilentlyContinue
}
