param([int]$Port = 58519)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Install or select Python 3.12, then follow the README local startup commands.'
    }
    if ($env:DATABASE_URL) {
        throw 'The local preview expects no DATABASE_URL. Open a clean terminal or clear that variable for this session before continuing.'
    }
    & py -3.12 build_preview.py
    if ($LASTEXITCODE -ne 0) { throw 'Homepage preparation failed.' }
    & py -3.12 import_snapshot.py data/forward-snapshot.json
    if ($LASTEXITCODE -ne 0) { throw 'The local snapshot could not be imported.' }
    Write-Host "Open http://127.0.0.1:$Port/forward/ . Press Ctrl+C here to stop."
    & py -3.12 serve.py --port $Port
}
finally { Pop-Location }
