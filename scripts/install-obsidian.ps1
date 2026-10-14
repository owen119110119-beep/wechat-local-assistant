param([switch]$DetectOnly)
$ErrorActionPreference = 'Stop'
$processInspectionFailed = $false
try { $running = Get-CimInstance Win32_Process -Filter "Name='Obsidian.exe'" -ErrorAction Stop | Where-Object ExecutablePath | Select-Object -First 1 }
catch { $processInspectionFailed = $true }
if ($running -and (Test-Path -LiteralPath $running.ExecutablePath -PathType Leaf)) { Write-Output 'Obsidian 已在运行，保留自定义安装路径、版本及配置。'; exit 0 }
$registryRoots = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
$registered = $registryRoots | ForEach-Object { Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue } | Where-Object { $_.DisplayName -match '^Obsidian(?:\s|$)' } | Select-Object -First 1
if ($registered) { Write-Output '已有 Obsidian 安装记录，保留版本和配置；需要修复时应单独核实，不重复安装。'; exit 0 }
$userLocal = Join-Path $env:USERPROFILE 'AppData\Local'
$paths = @((Join-Path $userLocal 'Obsidian\Obsidian.exe'),(Join-Path $userLocal 'Programs\Obsidian\Obsidian.exe'),(Join-Path $env:LOCALAPPDATA 'Obsidian\Obsidian.exe'),(Join-Path $env:ProgramFiles 'Obsidian\Obsidian.exe'))
$installed = $paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ($installed) { Write-Output 'Obsidian 已安装，保留当前版本及配置。'; exit 0 }
if ($DetectOnly) { Write-Output '未检测到 Obsidian；未执行安装。'; exit 0 }
if ($processInspectionFailed) { throw '本机进程检测权限不足。请在获准的本机环境重新检测后安装，避免重复安装已有自定义路径软件。' }
if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw '未找到 winget。请从 https://obsidian.md/download 安装 Obsidian。' }
& winget.exe install --id Obsidian.Obsidian --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity
if ($LASTEXITCODE -ne 0) { throw 'Obsidian 安装未完成；请查看 winget 返回或使用官方安装器。' }
if (-not ($paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })) { throw '安装返回成功，但未核实 Obsidian.exe。需要检查实际安装目录。' }
Write-Output 'Obsidian 已安装；请打开所选知识库目录。'
