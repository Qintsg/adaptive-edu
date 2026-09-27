<#
文件内容描述：通过 BBT-7 日志包装器分块上传 MEFKT 大文件，绕开长 WebSocket 传输中断。
@Project : adaptive-edu
@File : Invoke-MEFKTChunkedUpload.ps1
@Author : Qintsg
@Date : 2026-09-24
#>

function Invoke-MEFKTChunkedUpload {
    <#
    将大文件按小块复制到上传 Pod，逐块拼接后原子替换目标。
    :param LoggedKubectl: BBT-7 带日志包装器。
    :param Kubeconfig: prd kubeconfig 路径。
    :param Namespace: 训练 namespace。
    :param PodName: 已 Ready 的上传 Pod。
    :param LocalFile: 本地源文件。
    :param RemoteFile: 数据 PVC 上的绝对目标路径。
    :param ChunkMiB: 每个 kubectl cp 的 MiB 大小。
    :returns: 无。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$LoggedKubectl,
        [Parameter(Mandatory)][string]$Kubeconfig,
        [Parameter(Mandatory)][string]$Namespace,
        [Parameter(Mandatory)][string]$PodName,
        [Parameter(Mandatory)][string]$LocalFile,
        [Parameter(Mandatory)][string]$RemoteFile,
        [ValidateRange(1, 256)][int]$ChunkMiB = 64
    )

    if (-not (Test-Path -LiteralPath $LocalFile -PathType Leaf)) {
        throw "分块上传源文件不存在：$LocalFile"
    }
    if ($RemoteFile -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteFile.Contains('..')) {
        throw "分块上传目标路径非法：$RemoteFile"
    }
    $source = [System.IO.File]::OpenRead($LocalFile)
    $remoteTemporary = "$RemoteFile.uploading-$([guid]::NewGuid().ToString('N'))"
    $remoteChunk = ''
    $complete = $false
    $chunkBytes = $ChunkMiB * 1048576
    $buffer = [byte[]]::new($chunkBytes)
    $chunkDirectory = Join-Path (Get-Location).Path 'backend/runtime_logs/mefkt_ng_upload_chunks'
    [System.IO.Directory]::CreateDirectory($chunkDirectory) | Out-Null
    $index = 0
    try {
        while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $localChunk = Join-Path $chunkDirectory "$([guid]::NewGuid().ToString('N')).chunk"
            $relativeChunk = [System.IO.Path]::GetRelativePath((Get-Location).Path, $localChunk).Replace([char]92, [char]47)
            $remoteChunk = "$remoteTemporary.$index.chunk"
            try {
                $chunkStream = [System.IO.File]::Open($localChunk,
                    [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None)
                try { $chunkStream.Write($buffer, 0, $read) }
                finally { $chunkStream.Dispose() }
                $copied = $false
                for ($attempt = 1; $attempt -le 3; $attempt++) {
                    try {
                        & $LoggedKubectl -Reason "分块上传 MEFKT 数据 $index（第 $attempt 次）" `
                            -Kubeconfig $Kubeconfig -KubectlArgs @(
                                'cp', $relativeChunk, "$Namespace/${PodName}:$remoteChunk", '--container', 'uploader'
                            ) | Out-Host
                        $copied = $true
                        break
                    } catch {
                        if ($attempt -eq 3) { throw }
                        Start-Sleep -Seconds 2
                    }
                }
                if (-not $copied) { throw "分块上传失败：$index" }
                & $LoggedKubectl -Reason "拼接 MEFKT 数据块 $index" `
                    -Kubeconfig $Kubeconfig -KubectlArgs @(
                        'exec', '--namespace', $Namespace, $PodName, '--container', 'uploader', '--',
                        'sh', '-c', "cat '$remoteChunk' >> '$remoteTemporary' && rm -f '$remoteChunk'"
                    ) | Out-Host
                $remoteChunk = ''
                $index++
            } finally {
                if (Test-Path -LiteralPath $localChunk) {
                    Remove-Item -LiteralPath $localChunk -Force
                }
            }
        }
        if ($index -eq 0) { throw "不允许上传空文件：$LocalFile" }
        & $LoggedKubectl -Reason "完成 MEFKT 分块上传并原子替换目标" `
            -Kubeconfig $Kubeconfig -KubectlArgs @(
                'exec', '--namespace', $Namespace, $PodName, '--container', 'uploader', '--',
                'sh', '-c', "mv -f '$remoteTemporary' '$RemoteFile'"
            ) | Out-Host
        $complete = $true
        Write-Host "分块上传完成：$index 块，目标 $RemoteFile"
    } finally {
        $source.Dispose()
        if (-not $complete) {
            try {
                & $LoggedKubectl -Reason "清理失败的 MEFKT 上传临时块" `
                    -Kubeconfig $Kubeconfig -KubectlArgs @(
                        'exec', '--namespace', $Namespace, $PodName, '--container', 'uploader', '--',
                        'sh', '-c', "rm -f '$remoteTemporary' '$remoteChunk'"
                    ) | Out-Host
            } catch { Write-Warning "远端临时块清理失败：$remoteTemporary" }
        }
    }
}
