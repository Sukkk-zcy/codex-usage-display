$ErrorActionPreference = 'Stop'
$Project = Split-Path $PSScriptRoot -Parent
$TargetExe = Join-Path $Project 'dist\MagpieDisplay.exe'
$RunningClient = Get-Process -Name MagpieDisplay -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $TargetExe }
if ($RunningClient) { throw 'Close Magpie Display before rebuilding the desktop client.' }
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    python -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
}
& $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt') 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Push-Location $Project
try {
    $Icon = Join-Path $PSScriptRoot 'assets\magpie.ico'
    $Staging = Join-Path $Project 'build\desktop-release'
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name MagpieDisplay --icon $Icon --add-data "$Icon;." --paths $PSScriptRoot --collect-submodules bleak.backends.winrt --collect-submodules winrt --distpath $Staging --workpath (Join-Path $Project 'build\desktop') --specpath (Join-Path $Project 'build\desktop') (Join-Path $PSScriptRoot 'desktop_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    New-Item -ItemType Directory -Path (Split-Path $TargetExe -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Staging 'MagpieDisplay.exe') -Destination $TargetExe -Force
    Write-Output ('Desktop client ready: ' + $TargetExe)
} finally {
    Pop-Location
}
