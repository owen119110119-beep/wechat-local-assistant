function Start-IndependentGatewayWorker {
    param([string]$Root,[string]$Shell)
    $scriptPath=Join-Path $Root 'scripts/start.ps1'
    if (-not (Test-Path -LiteralPath $scriptPath) -or -not (Test-Path -LiteralPath $Shell) -or $Shell -match '["\r\n]' -or $scriptPath -match '["\r\n]') { throw 'Invalid local startup target.' }
    # Preserve this process's environment, including proxy settings, without logging it.
    $variables=[string[]]@([Environment]::GetEnvironmentVariables('Process').GetEnumerator() | Where-Object { -not ([string]$_.Key).StartsWith('=') } | ForEach-Object { [string]$_.Key+'='+[string]$_.Value })
    $startup=New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0;EnvironmentVariables=$variables}
    # WMI creates the worker outside this MCP/chat process tree. No scheduled task.
    $command='"'+$Shell+'" -NoLogo -NoProfile -NonInteractive -File "'+$scriptPath+'" -Worker -RespectStop'
    $result=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$command;CurrentDirectory=$Root;ProcessStartupInformation=$startup}
    if ($result.ReturnValue -ne 0 -or $result.ProcessId -le 0) { throw ('Independent startup failed with code '+$result.ReturnValue) }
    return [int]$result.ProcessId
}
