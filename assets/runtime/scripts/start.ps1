param([switch]$RespectStop,[switch]$Worker,[switch]$Handoff)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stopPath = Join-Path $projectRoot '.runtime/stop.request'
if ($RespectStop -and (Test-Path -LiteralPath $stopPath)) { Write-Host 'Automatic start paused by user.'; exit 0 }
. (Join-Path $PSScriptRoot 'gateway-state.ps1')
$runtime=Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (-not $Worker) {
    if (-not $RespectStop -and (Test-Path -LiteralPath $stopPath)) { Remove-Item -LiteralPath $stopPath }
    . (Join-Path $PSScriptRoot 'gateway-launch.ps1')
    $started=(Get-Date).ToUniversalTime()
    $workerPid=Start-IndependentGatewayWorker -Root $projectRoot -Shell (Get-Process -Id $PID).Path
    Add-Content -LiteralPath (Join-Path $runtime 'lifecycle.log') -Value ("{0:o} handoff worker={1} requester={2} route=wmi" -f (Get-Date),$workerPid,$PID) -Encoding utf8
    if ($Handoff) { Write-Host 'Gateway startup handed off.'; exit 0 }
    $deadline=(Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 600
        $current=Read-GatewayState -Path (Join-Path $runtime 'status.json')
        if ($current -and $current.state -eq 'running' -and $current.codex -eq 'ready') {
            $matches=@(Find-GatewayProcess -Processes @(Get-CimInstance Win32_Process -Filter "ProcessId=$($current.pid)") -GatewayPath (Join-Path $projectRoot 'src/gateway.mjs'))
            if ($matches.Count -eq 1) { Write-Host "微信 Codex 网关已启动。PID=$($current.pid)";exit 0 }
        }
        if ($current -and $current.state -eq 'failed' -and [datetime]$current.updatedAt -ge $started) { throw "Gateway startup failed: $($current.error); stage=$($current.stage); reason=$($current.reason)" }
    }
    throw 'Independent startup timed out. Check lifecycle.log and status.json.'
}
$launchMutex=$null
$launchOwned=$false
if ($true) {
    $launchHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Substring(0,16)
    $launchMutex=[Threading.Mutex]::new($false,('Local\WeixinAgentStart-'+$launchHash))
    try { $launchOwned=$launchMutex.WaitOne(120000) } catch [Threading.AbandonedMutexException] { $launchOwned=$true }
    if (-not $launchOwned) { $launchMutex.Dispose();throw 'Another gateway startup is still active.' }
}
try {
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config\local.json') -Raw | ConvertFrom-Json
if ($config.agentMode -eq $true) {
    $selection = & $config.nodePath (Join-Path $projectRoot 'src\runtime.mjs') $config.codexPath
    if ($LASTEXITCODE -ne 0) { throw 'Codex runtime components are incomplete; repair the official installation.' }
    $candidate = ($selection | ConvertFrom-Json).codexPath
    if (-not $candidate) { throw 'Codex runtime selection failed.' }
    if ($candidate -ne $config.codexPath) {
    $config.codexPath = $candidate
    $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $projectRoot 'config\local.json') -Encoding utf8
    }
}
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (-not $RespectStop -and (Test-Path -LiteralPath $stopPath)) { Remove-Item -LiteralPath $stopPath }
$statusPath = Join-Path $runtime 'status.json'
$gatewayPath = Join-Path $projectRoot 'src\gateway.mjs'
$proc = $null
$status = Read-GatewayState -Path $statusPath
$existing = @(Find-GatewayProcess -Processes @(Get-CimInstance Win32_Process -Filter "Name='node.exe'") -GatewayPath $gatewayPath)
if ($existing.Count -gt 1) { throw 'Multiple gateway processes found for this directory; review before starting.' }
if ($existing.Count -eq 1) {
    if ($status -and $status.pid -eq $existing[0].ProcessId -and $status.state -eq 'running' -and $status.codex -eq 'ready') {
        Write-Host "Gateway already running. PID=$($status.pid)"
        exit 0
    }
    $proc = Get-Process -Id $existing[0].ProcessId
}
if (-not $proc) {
    $proc = Start-Process -FilePath $config.nodePath -ArgumentList @('"' + $gatewayPath + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log')
    Add-Content -LiteralPath (Join-Path $runtime 'lifecycle.log') -Value ("{0:o} started pid={1} launcher={2} route=independent-worker" -f (Get-Date),$proc.Id,$PID) -Encoding utf8
}
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 600
    if (Test-Path -LiteralPath $statusPath) {
        $current = Read-GatewayState -Path $statusPath
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'running' -and $current.codex -eq 'ready') {
            Add-Content -LiteralPath (Join-Path $runtime 'lifecycle.log') -Value ("{0:o} ready pid={1} launcher={2}" -f (Get-Date),$proc.Id,$PID) -Encoding utf8
            Write-Host "微信 Codex 网关已启动。PID=$($proc.Id)"
            exit 0
        }
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'failed') { throw "Gateway startup failed: $($current.error); stage=$($current.stage); reason=$($current.reason)" }
    }
    if ($proc.HasExited) { throw 'Gateway exited. Check .runtime\stderr.log.' }
}
throw 'Gateway startup timed out. Check .runtime\status.json.'

} catch {
    Add-Content -LiteralPath (Join-Path $runtime 'lifecycle.log') -Value ("{0:o} startup_failed launcher={1} error_type={2}" -f (Get-Date),$PID,$_.Exception.GetType().Name) -Encoding utf8
    throw
} finally {
    if ($launchOwned) { $launchMutex.ReleaseMutex() }
    if ($launchMutex) { $launchMutex.Dispose() }
}
