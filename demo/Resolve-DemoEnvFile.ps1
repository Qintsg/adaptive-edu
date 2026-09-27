# 答辩环境配置文件定位：只返回文件路径，不读取或打印密钥值。

function Test-DemoEnvHasApiKey {
    <#
    .SYNOPSIS
    判断配置文件是否包含非空的演示模型密钥。
    .PARAMETER Path
    待检查的 env 文件路径。
    .OUTPUTS
    System.Boolean
    #>
    param([Parameter(Mandatory)][string]$Path)

    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        if ($line -match '^\s*DEMO_LLM_API_KEY\s*=\s*(.*)$') {
            $value = $Matches[1].Trim().Trim('"').Trim("'")
            return $value.Length -gt 0
        }
    }
    return $false
}

function Resolve-DemoEnvFile {
    <#
    .SYNOPSIS
    按显式参数、环境变量、同目录文件、用户私有文件查找 Compose 配置。
    .PARAMETER EnvFile
    显式指定的 env 文件。指定后若不存在，直接报错。
    .PARAMETER ScriptDirectory
    demo 脚本所在目录。
    .OUTPUTS
    System.String
    #>
    param(
        [string]$EnvFile,
        [Parameter(Mandatory)][string]$ScriptDirectory
    )

    $selected = if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
        $EnvFile
    } elseif (-not [string]::IsNullOrWhiteSpace($env:ADAPTIVE_EDU_DEMO_ENV_FILE)) {
        $env:ADAPTIVE_EDU_DEMO_ENV_FILE
    } else {
        ''
    }
    if ($selected) {
        if (-not (Test-Path -LiteralPath $selected -PathType Leaf)) {
            throw "指定的 AI 配置文件不存在：$selected"
        }
        return (Resolve-Path -LiteralPath $selected).Path
    }

    $localFile = Join-Path $ScriptDirectory '.env.local'
    $userProfile = [Environment]::GetFolderPath('UserProfile')
    $privateFile = Join-Path $userProfile '.agents\secrets\adaptive-edu-deepseek.env'
    if ((Test-Path -LiteralPath $localFile -PathType Leaf) -and
        (Test-DemoEnvHasApiKey -Path $localFile)) {
        return (Resolve-Path -LiteralPath $localFile).Path
    }
    if (Test-Path -LiteralPath $privateFile -PathType Leaf) {
        return (Resolve-Path -LiteralPath $privateFile).Path
    }
    if (Test-Path -LiteralPath $localFile -PathType Leaf) {
        return (Resolve-Path -LiteralPath $localFile).Path
    }
    return ''
}
