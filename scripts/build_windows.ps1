# Build on Windows x64 with Python 3.13. Python is not needed on the recipient PC.
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project
py -3.13 -m venv .venv-build
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required to build' }
$python = Join-Path $project '.venv-build\Scripts\python.exe'
& $python -m pip install --disable-pip-version-check 'pyinstaller==6.22.3' 'setuptools==81.0.0'
if ($LASTEXITCODE -ne 0) { throw 'Build dependency install failed' }
& $python -m pip install --no-build-isolation -e '.[radio,audio]'
if ($LASTEXITCODE -ne 0) { throw 'App dependency install failed' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name IC7300_CW_AutoContest --paths src `
  --collect-all sounddevice --hidden-import serial.tools.list_ports `
  scripts/run_desktop.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
Write-Host ('Created: ' + (Join-Path $project 'dist\IC7300_CW_AutoContest.exe'))
Write-Host 'EXE is a PC receive/log prototype; no automatic RF transmission.'
