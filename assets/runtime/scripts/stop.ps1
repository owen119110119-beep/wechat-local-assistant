$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $projectRoot '.runtime'
$statusPath = Join-Path $runtime 'status.json'
if (-not (Test-Path -LiteralPath $statusPath)) { Write-Host 'Gateway is not running.'; exit 0 }
$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($status.pid)"
if (-not $existing -or $existing.CommandLine -notlike ('*' + (Join-Path $projectRoot 'src\gateway.mjs') + '*')) { Write-Host 'Gateway is not running.'; exit 0 }
Set-Content -LiteralPath (Join-Path $runtime 'stop.request') -Value 'stop' -Encoding utf8
for ($attempt=0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $current = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($current.state -eq 'stopped') { Write-Host '微信 Codex 网关已停止。'; exit 0 }
}
throw 'Graceful stop timed out. Process was not force-killed; check status.'
