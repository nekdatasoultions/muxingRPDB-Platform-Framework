param(
  [Parameter(Mandatory = $true)]
  [string]$S3Uri,

  [Parameter(Mandatory = $false)]
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$projectRootPath = (Resolve-Path $ProjectRoot).Path
$tempZip = Join-Path $env:TEMP "muxingplus-platform-dev.zip"

if (Test-Path $tempZip) {
  Remove-Item $tempZip -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$excludeParts = @(".git", ".vscode", "__pycache__")

$zip = [System.IO.Compression.ZipFile]::Open($tempZip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  Get-ChildItem -Path $projectRootPath -Recurse -File | ForEach-Object {
    $fullPath = $_.FullName
    $relativePath = $fullPath.Substring($projectRootPath.Length).TrimStart('\')
    $relativeParts = $relativePath -split '[\\/]'

    if ($relativeParts | Where-Object { $excludeParts -contains $_ }) {
      return
    }

    if ($_.Extension -eq ".pyc") {
      return
    }

    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
      $zip,
      $fullPath,
      ($relativePath -replace '\\', '/'),
      [System.IO.Compression.CompressionLevel]::Optimal
    ) | Out-Null
  }
}
finally {
  $zip.Dispose()
}

aws s3 cp $tempZip $S3Uri
Write-Host "Uploaded project package to $S3Uri"
