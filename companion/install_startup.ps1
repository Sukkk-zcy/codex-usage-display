param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Magpie Usage Display.lnk'
if ($Uninstall) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    Write-Output 'Magpie companion startup removed.'
    exit
}
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Run .\companion\run.ps1 -Once first.' }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m codex_display'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Magpie usage display Bluetooth companion'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output 'Installed for the current user. Starts at the next Windows sign-in.'
