$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $root 'servers'
$venvPython = Join-Path $server '.venv\Scripts\python.exe'
if (-not (Test-Path (Join-Path $server '.env'))) {
    Copy-Item (Join-Path $server '.env.example') (Join-Path $server '.env')
    Write-Host 'servers/.env를 만들었습니다. GMS_KEY를 입력한 뒤 다시 실행하세요.' -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $venvPython)) {
    python -m venv (Join-Path $server '.venv')
    & $venvPython -m pip install -r (Join-Path $server 'requirements.txt')
}
Set-Location $server
& $venvPython 'main.py'
