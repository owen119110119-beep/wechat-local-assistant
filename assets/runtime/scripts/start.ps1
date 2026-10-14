$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config\local.json') -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $config.codexPath -PathType Leaf)) {
    $codexBin = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    $candidate = Get-ChildItem -LiteralPath $codexBin -Directory -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object { Join-Path $_.FullName 'codex.exe' } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $candidate) { throw 'Codex executable was not found in its installation directory.' }
    $version = & $candidate --version
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^codex-cli ') { throw 'Codex executable verification failed.' }
    $config.codexPath = $candidate
    $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $projectRoot 'config\local.json') -Encoding utf8
}
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$statusPath = Join-Path $runtime 'status.json'
$proc = $null
if (Test-Path -LiteralPath $statusPath) {
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($status.pid)"
    if ($existing -and $existing.CommandLine -like ('*' + (Join-Path $projectRoot 'src\gateway.mjs') + '*')) {
        if ($status.state -eq 'running' -and $status.codex -eq 'ready') {
            Write-Host "Gateway already running. PID=$($status.pid)"
            exit 0
        }
        $proc = Get-Process -Id $existing.ProcessId
    }
}
$gatewayPath = Join-Path $projectRoot 'src\gateway.mjs'
if (-not $proc) { $proc = Start-Process -FilePath $config.nodePath -ArgumentList @('"' + $gatewayPath + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log') }
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 600
    if (Test-Path -LiteralPath $statusPath) {
        try { $current = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json } catch { $current = $null }
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'running' -and $current.codex -eq 'ready') {
            Write-Host "微信 Codex 网关已启动。PID=$($proc.Id)"
            exit 0
        }
        if ($current -and $current.pid -eq $proc.Id -and $current.state -eq 'failed') { throw "Gateway startup failed: $($current.error); stage=$($current.stage); reason=$($current.reason)" }
    }
    if ($proc.HasExited) { throw 'Gateway exited. Check .runtime\stderr.log.' }
}
throw 'Gateway startup timed out. Check .runtime\status.json.'
