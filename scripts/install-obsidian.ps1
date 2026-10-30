param([switch]$DetectOnly,[switch]$Json)
$ErrorActionPreference = 'Stop'
function Finish-Detection([string]$Status,[string]$Message) {
    if ($Json) { @{status=$Status;message=$Message} | ConvertTo-Json -Compress } else { Write-Output $Message }
    exit 0
}
$processInspectionFailed = $false
try { $running = Get-CimInstance Win32_Process -Filter "Name='Obsidian.exe'" -OperationTimeoutSec 8 -ErrorAction Stop | Where-Object ExecutablePath | Select-Object -First 1 }
catch { $processInspectionFailed = $true }
if ($running -and (Test-Path -LiteralPath $running.ExecutablePath -PathType Leaf)) { Finish-Detection 'installed' 'Obsidian 已在运行，保留自定义安装路径、版本及配置。' }
$registryRoots = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
$registered = $registryRoots | ForEach-Object { Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue } | Where-Object { $_.DisplayName -match '^Obsidian(?:\s|$)' } | Select-Object -First 1
$userLocal = Join-Path $env:USERPROFILE 'AppData\Local'
$paths = @((Join-Path $userLocal 'Obsidian\Obsidian.exe'),(Join-Path $userLocal 'Programs\Obsidian\Obsidian.exe'),(Join-Path $env:LOCALAPPDATA 'Obsidian\Obsidian.exe'),(Join-Path $env:ProgramFiles 'Obsidian\Obsidian.exe'))
$installed = $paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ($installed) { Finish-Detection 'installed' 'Obsidian 已安装，保留当前版本及配置。' }
if ($registered) { Finish-Detection 'unverified' '已有Obsidian安装记录，但未核实程序位置；请提供现有程序路径，不重复安装。' }
if ($processInspectionFailed) { Finish-Detection 'unknown' '本机进程检测未完成，请在获准环境核对现有程序位置，不盲目重装。' }
if ($DetectOnly) { Finish-Detection 'not_found' '未检测到 Obsidian；未执行安装。' }
if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw '未找到 winget。请从 https://obsidian.md/download 安装 Obsidian。' }
$installer = Start-Process -FilePath (Get-Command winget.exe).Source -ArgumentList @('install','--id','Obsidian.Obsidian','--exact','--source','winget','--scope','user','--accept-source-agreements','--accept-package-agreements','--disable-interactivity') -WindowStyle Hidden -PassThru
if (-not $installer.WaitForExit(180000)) { $installer.Kill(); throw 'Obsidian安装等待超时；先核对是否有安装器仍在运行或软件已经装好，勿重复启动。可从https://obsidian.md/download安装。' }
if ($installer.ExitCode -ne 0) { throw 'Obsidian 安装未完成；请使用官方安装器。' }
if (-not ($paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })) { throw '安装返回成功，但未核实 Obsidian.exe。需要检查实际安装目录。' }
Finish-Detection 'installed' 'Obsidian 已安装；请打开所选知识库目录。'
