# Windows x64 + Python 3.13 (stable) required. Run in PowerShell on Windows.
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $project
py -3.13 -m venv .venv-build
$python = Join-Path $project '.venv-build\Scripts\python.exe'
& $python -m pip install --disable-pip-version-check 'pyinstaller==6.22.3' 'setuptools==81.0.0'
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed' }
& $python -m pip install --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Project install failed' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name IC7300_CW_AutoContest --paths src scripts/run_desktop.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Write-Host ('Created: ' + (Join-Path $project 'dist\IC7300_CW_AutoContest.exe'))
Write-Host 'Windows executable: unverified until run on Windows. No RF transmission in GUI.'
