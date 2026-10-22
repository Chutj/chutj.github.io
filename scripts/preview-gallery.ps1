param([int]$Port = 1313)
$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $siteRoot
try {
    if (-not (Test-Path -LiteralPath '.gallery-local/catalog.json')) {
        throw 'Import the private FIG sample first. See docs/gallery-prototype.md.'
    }
    git check-ignore --quiet .gallery-local/catalog.json
    if ($LASTEXITCODE -ne 0) { throw 'Private gallery files must be Git-ignored.' }
    $hugoCommand = Get-Command hugo -ErrorAction SilentlyContinue
    if ($hugoCommand) { $hugoExecutable = $hugoCommand.Source }
    else {
        $hugoExecutable = Join-Path $env:LOCALAPPDATA 'Microsoft/WinGet/Packages/Hugo.Hugo.Extended_Microsoft.Winget.Source_8wekyb3d8bbwe/hugo.exe'
    }
    & $hugoExecutable server --config 'hugo.toml,.gallery-local/hugo.toml' --bind 127.0.0.1 --port $Port --baseURL "http://localhost:$Port/" --renderToMemory --noBuildLock --disableFastRender
    if ($LASTEXITCODE -ne 0) { throw 'Hugo gallery preview failed.' }
}
finally { Pop-Location }
