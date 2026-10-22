param([switch]$RespectStop)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stopPath = Join-Path $projectRoot '.runtime/stop.request'
if ($RespectStop -and (Test-Path -LiteralPath $stopPath)) { Write-Host 'Automatic start paused by user.'; exit 0 }
. (Join-Path $PSScriptRoot 'gateway-state.ps1')
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
    Add-Content -LiteralPath (Join-Path $runtime 'lifecycle.log') -Value ("{0:o} started pid={1} launcher={2} route=local-starter" -f (Get-Date),$proc.Id,$PID) -Encoding utf8
}
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 600
    if (Test-Path -LiteralPath $statusPath) {
        $current = Read-GatewayState -Path $statusPath
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'running' -and $current.codex -eq 'ready') {
            Write-Host "微信 Codex 网关已启动。PID=$($proc.Id)"
            exit 0
        }
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'failed') { throw "Gateway startup failed: $($current.error); stage=$($current.stage); reason=$($current.reason)" }
    }
    if ($proc.HasExited) { throw 'Gateway exited. Check .runtime\stderr.log.' }
}
throw 'Gateway startup timed out. Check .runtime\status.json.'

} finally {
    if ($launchOwned) { $launchMutex.ReleaseMutex() }
    if ($launchMutex) { $launchMutex.Dispose() }
}
