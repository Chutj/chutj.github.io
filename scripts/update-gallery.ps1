param([switch]$DryRun, [switch]$Json, [string]$Source)
$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $siteRoot
try {
    $importArguments = @('scripts/import_gallery.py')
    if ($DryRun) { $importArguments += '--dry-run' }
    if ($Json) { $importArguments += '--json' }
    if ($Source) { $importArguments += @('--source', $Source) }
    python @importArguments
    if ($LASTEXITCODE -ne 0) { throw 'FIG import stopped. Existing source files were not modified.' }
}
finally { Pop-Location }
