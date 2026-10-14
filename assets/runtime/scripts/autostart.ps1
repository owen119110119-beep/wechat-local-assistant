$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$logPath = Join-Path $runtime 'autostart.log'
$shellPath = (Get-Process -Id $PID).Path
for ($attempt = 1; $attempt -le 12; $attempt++) {
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) startup_attempt=$attempt" -Encoding utf8
    # Isolate start.ps1's exit statements from this retry wrapper.
    $launcher = Start-Process -FilePath $shellPath -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-File',('"' + (Join-Path $PSScriptRoot 'start.ps1') + '"')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $runtime 'autostart-start.stdout.log') -RedirectStandardError (Join-Path $runtime 'autostart-start.stderr.log')
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) startup_exit=$($launcher.ExitCode)" -Encoding utf8
    if ($launcher.ExitCode -eq 0) { exit 0 }
    if ($attempt -lt 12) { Start-Sleep -Seconds 15 }
}
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) startup_failed" -Encoding utf8
exit 1
