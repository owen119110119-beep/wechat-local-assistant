param([ValidateSet('Enable','Disable','Status')][string]$Mode = 'Status')
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Substring(0,12)
$taskName = 'WeixinAgent-' + $taskHash
$runnerPath = Join-Path $PSScriptRoot 'autostart.ps1'
$guiLauncherPath = Join-Path $projectRoot '.runtime\autostart-launch.exe'
$legacyGuiPath = Join-Path $PSScriptRoot 'autostart-launch.vbs'
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runnerPath + '*')) -and -not ($existing.Actions.Arguments -like ('*' + $legacyGuiPath + '*')) -and $existing.Actions.Execute -ne $guiLauncherPath) {
    throw 'Task name belongs to another target. No task was modified.'
}
if ($Mode -eq 'Disable') {
    if ($existing) { Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false }
    Write-Host '已移除微信助理登录自启，当前网关不受影响。'
    exit 0
}
if ($Mode -eq 'Enable') {
    $shellPath = (Get-Process -Id $PID).Path
    if ([IO.Path]::GetFileName($shellPath) -ne 'pwsh.exe') { throw 'Run this script with PowerShell 7.' }
    $config = Get-Content -LiteralPath (Join-Path $projectRoot 'config/local.json') -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $config.nodePath) -or -not (Test-Path -LiteralPath $config.codexPath)) {
        throw 'Gateway runtime dependency is missing.'
    }
    if ($existing) {
        $runtime = Join-Path $projectRoot '.runtime'
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        Export-ScheduledTask -TaskName $taskName -TaskPath '\' |
            Set-Content -LiteralPath (Join-Path $runtime ('autostart-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.xml')) -Encoding utf8
    }
    $compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    $sourcePath = Join-Path $PSScriptRoot 'autostart-launch.cs'
    if (-not (Test-Path -LiteralPath $compilerPath)) { throw 'Local GUI launcher compiler not found.' }
    New-Item -ItemType Directory -Path (Join-Path $projectRoot '.runtime') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $projectRoot '.runtime') -Force | Out-Null
    & $compilerPath /nologo /target:winexe (('/out:' + $guiLauncherPath)) $sourcePath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $guiLauncherPath)) { throw 'GUI launcher compilation failed.' }
    $action = New-ScheduledTaskAction -Execute $guiLauncherPath -Argument ('"' + $shellPath + '"') -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
    $trigger.Delay = 'PT20S'
    $principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    # Task Scheduler can keep the task running while the detached gateway lives.
    # A finite limit would kill that healthy child process after logon.
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '旧登录启动入口，当前改为Codex启动后接入。' -Force | Out-Null
}
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if (-not $task) { Write-Host '微信助理登录自启尚未配置。'; exit 0 }
[pscustomobject]@{
    TaskName = $task.TaskName
    State = [string]$task.State
    Enabled = $task.Settings.Enabled
    User = $task.Principal.UserId
    LogonType = [string]$task.Principal.LogonType
    RunLevel = [string]$task.Principal.RunLevel
    Trigger = $task.Triggers.CimClass.CimClassName
    TriggerUser = $task.Triggers.UserId
    Delay = $task.Triggers.Delay
    Executable = $task.Actions.Execute
    Arguments = $task.Actions.Arguments
    WorkingDirectory = $task.Actions.WorkingDirectory
    MultipleInstances = [string]$task.Settings.MultipleInstances
    ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
} | ConvertTo-Json
