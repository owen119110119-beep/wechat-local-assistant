$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config=Get-Content (Join-Path $projectRoot 'config/local.json') -Raw | ConvertFrom-Json
Push-Location $projectRoot
try {
    New-Item -ItemType Directory '.runtime/tmp' -Force | Out-Null
    $env:TEMP=(Resolve-Path '.runtime/tmp').Path; $env:TMP=$env:TEMP
    $env:HF_HOME=Join-Path $projectRoot '.runtime/huggingface'; $env:HF_HUB_CACHE=Join-Path $env:HF_HOME 'hub'
    $env:HF_HUB_DISABLE_TELEMETRY='1'; $env:HF_HUB_DISABLE_XET='1'
    if (-not (Test-Path $config.voicePythonPath)) {
        & $config.pythonPath -m venv '.venv'
        if ($LASTEXITCODE -ne 0) { throw 'Local voice venv creation failed' }
    }
    & $config.voicePythonPath -m pip install -r 'scripts/requirements-voice.lock.txt'
    if ($LASTEXITCODE -ne 0) { throw 'Local voice dependencies failed' }
    & $config.voicePythonPath 'scripts/install-silk.py'
    if ($LASTEXITCODE -ne 0) { throw 'SILK verified install failed' }
    & $config.voicePythonPath 'scripts/transcribe.py' --model-dir '.runtime/models/base' --download
    if ($LASTEXITCODE -ne 0) { throw 'Speech model download failed' }
} finally { Pop-Location }
