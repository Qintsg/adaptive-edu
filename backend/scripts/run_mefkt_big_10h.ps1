<#
文件内容描述：MEFKT 大规格模型 10 小时 GPU 训练控制脚本。
Project: adaptive-edu
File: run_mefkt_big_10h.ps1
Author: Qintsg
Date: 2026-06-07
#>

[CmdletBinding()]
param(
    [double]$MaxHours = 10,
    [int[]]$AdoptPid = @(),
    [int]$EpochsPerRun = 80,
    [int]$PretrainEpochs = 24,
    [int]$BatchSize = 16,
    [int]$BaseSeed = 42,
    [int]$MinRemainingMinutesToStart = 35
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
Set-Location $BackendRoot

$RunId = Get-Date -Format "yyyyMMdd_HHmmss"
$Deadline = (Get-Date).AddHours($MaxHours)
$LogDir = Join-Path $BackendRoot "runtime_logs\mefkt"
$CheckpointDir = Join-Path $LogDir "checkpoints"
$ControllerLog = Join-Path $LogDir "mefkt_big_10h_$RunId.controller.log"
$StatusPath = Join-Path $LogDir "mefkt_big_10h_$RunId.status.json"
$FinalOutput = Join-Path $BackendRoot "models\MEFKT\mefkt_model.big.pt"
$FinalBackup = "$FinalOutput.bak"
$FinalMeta = [System.IO.Path]::ChangeExtension($FinalOutput, ".meta.json")
New-Item -ItemType Directory -Force -Path $LogDir, $CheckpointDir | Out-Null

$BestAuc = -1.0
$BestPath = $null
$LastPhase = "starting"

function Write-ControllerLog {
    param([string]$Message)
    $Line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $ControllerLog -Value $Line -Encoding UTF8
}

function Write-Status {
    param(
        [string]$Phase,
        [hashtable]$Extra = @{}
    )
    $script:LastPhase = $Phase
    $Payload = [ordered]@{
        run_id = $RunId
        phase = $Phase
        started_at = $RunId
        now = (Get-Date).ToString("o")
        deadline = $Deadline.ToString("o")
        max_hours = $MaxHours
        best_auc = $BestAuc
        best_path = $BestPath
        final_output = $FinalOutput
        final_backup = $FinalBackup
        final_meta = $FinalMeta
    }
    foreach ($Key in $Extra.Keys) {
        $Payload[$Key] = $Extra[$Key]
    }
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $StatusPath -Encoding UTF8
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    Write-ControllerLog "timeout: stopping process tree pid=$ProcessId"
    & taskkill.exe /PID $ProcessId /T /F | Out-String | ForEach-Object {
        if ($_.Trim()) {
            Write-ControllerLog $_.Trim()
        }
    }
}

function Wait-ControlledProcess {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Phase
    )
    while (-not $Process.HasExited) {
        $RemainingSeconds = [math]::Max(0, [int]($Deadline - (Get-Date)).TotalSeconds)
        Write-Status $Phase @{
            pid = $Process.Id
            remaining_seconds = $RemainingSeconds
        }
        if ((Get-Date) -ge $Deadline) {
            Stop-ProcessTree -ProcessId $Process.Id
            return "timeout"
        }
        Start-Sleep -Seconds ([math]::Min(30, [math]::Max(1, $RemainingSeconds)))
        try {
            $Process.Refresh()
        } catch {
            return "exited"
        }
    }
    return "completed"
}

function Register-CompletedRun {
    param([string]$OutputPath)
    $MetaPath = [System.IO.Path]::ChangeExtension($OutputPath, ".meta.json")
    $BackupPath = "$OutputPath.bak"
    if (-not (Test-Path $OutputPath) -or -not (Test-Path $MetaPath)) {
        Write-ControllerLog "skip register: missing output or metadata path=$OutputPath"
        return
    }
    $Meta = Get-Content -Path $MetaPath -Encoding UTF8 -Raw | ConvertFrom-Json
    $Auc = [double]$Meta.best_metrics.auc
    Write-ControllerLog "completed candidate path=$OutputPath val_auc=$Auc"
    if ($Auc -gt $script:BestAuc) {
        $SourceFullPath = [System.IO.Path]::GetFullPath($OutputPath)
        $FinalFullPath = [System.IO.Path]::GetFullPath($FinalOutput)
        $BackupFullPath = [System.IO.Path]::GetFullPath($BackupPath)
        $FinalBackupFullPath = [System.IO.Path]::GetFullPath($FinalBackup)
        $MetaFullPath = [System.IO.Path]::GetFullPath($MetaPath)
        $FinalMetaFullPath = [System.IO.Path]::GetFullPath($FinalMeta)
        if ($SourceFullPath -ne $FinalFullPath) {
            Copy-Item -Path $OutputPath -Destination $FinalOutput -Force
        }
        if ((Test-Path $BackupPath) -and $BackupFullPath -ne $FinalBackupFullPath) {
            Copy-Item -Path $BackupPath -Destination $FinalBackup -Force
        } elseif ($SourceFullPath -ne $FinalBackupFullPath) {
            Copy-Item -Path $OutputPath -Destination $FinalBackup -Force
        }
        if ($MetaFullPath -ne $FinalMetaFullPath) {
            Copy-Item -Path $MetaPath -Destination $FinalMeta -Force
        }
        $script:BestAuc = $Auc
        $script:BestPath = $OutputPath
        Write-ControllerLog "promoted best path=$OutputPath val_auc=$Auc final=$FinalOutput"
    }
}

function Start-TrainingRun {
    param([int]$Cycle)
    $Seed = $BaseSeed + $Cycle - 1
    $RunOutput = Join-Path $CheckpointDir ("mefkt_model.big.run{0:D3}.pt" -f $Cycle)
    $Stdout = Join-Path $LogDir ("mefkt_big_10h_$RunId.run{0:D3}.out.log" -f $Cycle)
    $Stderr = Join-Path $LogDir ("mefkt_big_10h_$RunId.run{0:D3}.err.log" -f $Cycle)
    $ArgsList = @(
        "tools.py", "train-mefkt",
        "--dataset", "kddcup2010",
        "--profile", "full",
        "--use-gpu",
        "--epochs", "$EpochsPerRun",
        "--pretrain-epochs", "$PretrainEpochs",
        "--batch-size", "$BatchSize",
        "--learning-rate", "0.00045",
        "--hidden-dim", "1024",
        "--align-dim", "1024",
        "--similarity-weight", "0.6",
        "--num-heads", "16",
        "--head-dim", "128",
        "--sequence-max-step", "96",
        "--validation-ratio", "0.2",
        "--seed", "$Seed",
        "--early-stopping-patience", "0",
        "--lr-decay", "0.975",
        "--output", $RunOutput
    )
    Write-ControllerLog "start cycle=$Cycle seed=$Seed output=$RunOutput"
    $env:PYTHONUNBUFFERED = "1"
    $Process = Start-Process `
        -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList $ArgsList `
        -WorkingDirectory $BackendRoot `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -WindowStyle Hidden `
        -PassThru
    $Result = Wait-ControlledProcess -Process $Process -Phase "training_cycle_$Cycle"
    Write-ControllerLog "cycle=$Cycle result=$Result exit_code=$($Process.ExitCode)"
    if ($Result -eq "completed" -and $Process.ExitCode -eq 0) {
        Register-CompletedRun -OutputPath $RunOutput
    }
    return $Result
}

Write-ControllerLog "MEFKT 10h controller started backend=$BackendRoot deadline=$($Deadline.ToString('o'))"
Write-Status "starting"
try {
    $GpuInfo = & nvidia-smi.exe --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader
    Write-ControllerLog "gpu=$GpuInfo"
} catch {
    Write-ControllerLog "gpu_check_failed=$($_.Exception.Message)"
}

if ((Test-Path $FinalOutput) -and (Test-Path $FinalMeta)) {
    Write-ControllerLog "register existing final checkpoint before new cycles"
    Register-CompletedRun -OutputPath $FinalOutput
}

foreach ($PidValue in $AdoptPid) {
    $Existing = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if ($null -eq $Existing) {
        continue
    }
    Write-ControllerLog "adopt existing training pid=$PidValue"
    $Result = Wait-ControlledProcess -Process $Existing -Phase "adopting_existing_training"
    Write-ControllerLog "adopted pid=$PidValue result=$Result"
    if ($Result -eq "timeout") {
        Write-Status "timeout" @{ stopped_pid = $PidValue }
        exit 0
    }
    Register-CompletedRun -OutputPath $FinalOutput
}

$Cycle = 1
while ((Get-Date) -lt $Deadline) {
    $RemainingMinutes = ($Deadline - (Get-Date)).TotalMinutes
    if ($RemainingMinutes -lt $MinRemainingMinutesToStart) {
        Write-ControllerLog "remaining minutes $RemainingMinutes below threshold, waiting until deadline"
        while ((Get-Date) -lt $Deadline) {
            Write-Status "waiting_for_deadline" @{
                remaining_seconds = [int]($Deadline - (Get-Date)).TotalSeconds
            }
            Start-Sleep -Seconds ([math]::Min(60, [math]::Max(1, [int]($Deadline - (Get-Date)).TotalSeconds)))
        }
        break
    }
    $RunResult = Start-TrainingRun -Cycle $Cycle
    if ($RunResult -eq "timeout") {
        break
    }
    $Cycle += 1
}

Write-ControllerLog "MEFKT 10h controller finished phase=$LastPhase best_auc=$BestAuc best_path=$BestPath"
Write-Status "finished" @{
    total_cycles_started = $Cycle - 1
}
