<#
文件内容描述：MEFKT-NG 提交器本地验证用的 kubectl 假包装器；不访问集群。
@Project : adaptive-edu
@File : Mock-MEFKTNGLoggedKubectl.ps1
@Author : Qintsg
@Date : 2026-09-24
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$KubectlArgs,
    [string]$Kubeconfig = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mockRoot = $env:MEFKTNG_MOCK_ROOT
if (-not $mockRoot -or -not (Test-Path -LiteralPath $mockRoot)) {
    throw 'MEFKTNG_MOCK_ROOT 未设置'
}
[System.IO.File]::AppendAllText((Join-Path $mockRoot 'calls.log'),
    (($KubectlArgs -join ' ') + "`n"), [System.Text.UTF8Encoding]::new($false))

$verb = $KubectlArgs[0]
switch ($verb) {
    'get' {
        if ($KubectlArgs[1] -eq 'vcjob') {
            if (Test-Path -LiteralPath (Join-Path $mockRoot 'job-created')) {
                Write-Output "job.batch.volcano.sh/$($KubectlArgs[2])"
            }
        } elseif ($KubectlArgs[1] -eq 'pod') {
            Write-Output '{"status":{"containerStatuses":[{"name":"uploader","ready":true}]}}'
        }
    }
    'apply' {
        $manifest = [System.IO.File]::ReadAllText($KubectlArgs[-1])
        if ($manifest -match '(?m)^kind: Job$') {
            [System.IO.File]::WriteAllText((Join-Path $mockRoot 'job-created'), 'yes')
        }
        Write-Output 'mock-applied'
    }
    'exec' {
        $remoteCommand = $KubectlArgs[-1]
        if ($remoteCommand -like 'sha256sum*') {
            $localFile = if ($remoteCommand -like '*.npz*') {
                $env:MEFKTNG_MOCK_CONTENT
            } else {
                $env:MEFKTNG_MOCK_EVENTS
            }
            Write-Output "$((Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant())  remote-file"
        } else {
            Write-Output 'mock-exec-ok'
        }
    }
    'cp' { Write-Output 'mock-cp-ok' }
    'delete' { Write-Output 'mock-deleted' }
    default { throw "未模拟的 kubectl 动作：$verb" }
}
