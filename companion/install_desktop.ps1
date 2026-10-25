$ErrorActionPreference = 'Stop'
$Project = Split-Path $PSScriptRoot -Parent
$Exe = Join-Path $Project 'dist\MagpieDisplay.exe'
if (-not (Test-Path $Exe)) { throw 'Run build_desktop.ps1 first' }
$Wsh = New-Object -ComObject WScript.Shell
$Link = $Wsh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Magpie Display.lnk'))
$Link.TargetPath = $Exe
$Link.WorkingDirectory = $Project
$Link.Description = 'Magpie Display - start and stop usage sync'
$Link.Save()
$LegacyPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Magpie Usage Display.lnk'
if (Test-Path -LiteralPath $LegacyPath) {
    $Legacy = $Wsh.CreateShortcut($LegacyPath)
    $Legacy.TargetPath = $Exe
    $Legacy.Arguments = '--start --minimized'
    $Legacy.WorkingDirectory = $Project
    $Legacy.Description = 'Magpie Display desktop client'
    $Legacy.Save()
}
Write-Host ('Desktop shortcut created: ' + $Exe)
