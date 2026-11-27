param([string]$Destination = 'D:\май проджектс\mas-test-generator')
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    throw 'Destination must be the existing mas-test-generator project folder.'
}
$targetRoot = (Resolve-Path -LiteralPath $Destination).Path
if ((Split-Path -Leaf $targetRoot) -ne 'mas-test-generator') {
    throw 'Expected a destination named mas-test-generator.'
}
if ($targetRoot -eq $sourceRoot) { throw 'Source and destination must differ.' }
$backupRoot = Join-Path $targetRoot ('.mas-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
# A file list prevents copying secrets, repository metadata, caches or generated reports.
$manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'delivery-manifest.json') -Raw | ConvertFrom-Json
foreach ($relativeFile in $manifest.files) {
    $sourceFile = Join-Path $sourceRoot $relativeFile
    $targetFile = [System.IO.Path]::GetFullPath((Join-Path $targetRoot $relativeFile))
    if (-not $targetFile.StartsWith($targetRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest contains a path outside the target project.'
    }
    if ((Split-Path -Leaf $targetFile) -in @('.env', '.git')) { throw 'Protected destination.' }
    if (Test-Path -LiteralPath $targetFile -PathType Leaf) {
        $backupFile = Join-Path $backupRoot $relativeFile
        New-Item -ItemType Directory -Path (Split-Path -Parent $backupFile) -Force | Out-Null
        Copy-Item -LiteralPath $targetFile -Destination $backupFile
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $targetFile) -Force | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $targetFile -Force
}
Write-Host ('Updated project: ' + $targetRoot)
Write-Host ('Backup of replaced files: ' + $backupRoot)
Write-Host 'Existing .env and .git were preserved.'
