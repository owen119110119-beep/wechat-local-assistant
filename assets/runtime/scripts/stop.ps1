$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'gateway-state.ps1')
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Content -LiteralPath (Join-Path $runtime 'stop.request') -Value 'stop' -Encoding utf8
$statusPath = Join-Path $runtime 'status.json'
$gatewayPath = Join-Path $projectRoot 'src\gateway.mjs'
$existing = @(Find-GatewayProcess -Processes @(Get-CimInstance Win32_Process -Filter "Name='node.exe'") -GatewayPath $gatewayPath)
if (-not $existing.Count) { Write-Host 'Gateway is not running.'; exit 0 }
if ($existing.Count -gt 1) { throw 'Multiple gateway processes found; no stop requested.' }
for ($attempt=0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $current = Read-GatewayState -Path $statusPath
    if ($current -and $current.pid -eq $existing[0].ProcessId -and $current.state -eq 'stopped') { Write-Host '微信 Codex 网关已停止。'; exit 0 }
}
throw 'Graceful stop timed out. Process was not force-killed; check status.'
