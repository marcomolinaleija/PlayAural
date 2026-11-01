[CmdletBinding()]
param([string]$Output = (Join-Path $PSScriptRoot '../../dist/marco'))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    $selectedPython = if ($env:UV_PYTHON) { $env:UV_PYTHON } else { '3.13' }
    & uv sync --project client --locked --python $selectedPython --extra dev
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
    $python = Join-Path $root 'client/.venv/Scripts/python.exe'
    & uv pip install --python $python pyinstaller==6.22.3
    if ($LASTEXITCODE) { throw 'Build tooling installation failed' }
    & $python -m pytest client/tests -q
    if ($LASTEXITCODE) { throw 'Desktop tests failed' }
    & $python -m PyInstaller --noconfirm --distpath $Output PlayAural.spec
    if ($LASTEXITCODE) { throw 'Desktop build failed' }
    & $python -m PyInstaller --noconfirm --distpath $Output updater.spec
    if ($LASTEXITCODE) { throw 'Updater build failed' }
    & $python deployment/marco-vps/package_desktop.py $Output
    if ($LASTEXITCODE) { throw 'Release verification failed' }
} finally { Pop-Location }
