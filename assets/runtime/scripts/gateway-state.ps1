function Read-GatewayState {
    param([string]$Path)
    try {
        $value = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $gatewayPid = 0
        if ($null -eq $value -or -not [int]::TryParse([string]$value.pid, [ref]$gatewayPid) -or $gatewayPid -le 0) { return $null }
        return $value
    } catch { return $null }
}

function Find-GatewayProcess {
    param([object[]]$Processes, [string]$GatewayPath)
    $pattern = '(?:^|\s|")' + [regex]::Escape($GatewayPath.Replace('/', '\')) + '(?:"|\s|$)'
    @($Processes | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -and $_.CommandLine.Replace('/', '\') -match $pattern })
}
