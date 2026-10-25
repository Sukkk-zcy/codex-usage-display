param(
    [switch]$Once,
    [switch]$VerboseLog,
    [string]$MagpieUrl = '',
    [string]$Device = 'Magpie Display'
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
        else { & python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.9+ is required.' }
    }
    & $venvPython -c "import importlib.metadata as m, sys; from importlib.util import find_spec; v=m.version('bleak') if find_spec('bleak') else '0.0.0'; parts=tuple(int(x) for x in v.split('.')[:3]); sys.exit(not ((1,1,1) <= parts < (2,0,0)))"
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install companion dependencies.' }
    }
    $companionArgs = @('-m', 'codex_display', '--device', $Device)
    if ($Once) { $companionArgs += '--once' }
    if ($VerboseLog) { $companionArgs += '--verbose' }
    if ($MagpieUrl) { $companionArgs += @('--magpie-url', $MagpieUrl) }
    & $venvPython @companionArgs
    if ($LASTEXITCODE -ne 0) { throw 'Companion failed; see the error above.' }
} finally { Pop-Location }
