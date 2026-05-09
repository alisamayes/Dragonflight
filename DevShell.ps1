<#
.SYNOPSIS
  Activate the Dragonflight virtualenv in the CURRENT PowerShell session.

.USAGE
  From project root (required - dot-source so activation persists):

    . .\DevShell.ps1

  If you run it without the leading dot, a child process activates venv and exits - your prompt will NOT change.
#>
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$activate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Host "No .venv found. Run first:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\Setup-DragonflightDev.ps1" -ForegroundColor White
    return
}

. $activate
Write-Host "Dragonflight venv active - $(python --version)" -ForegroundColor Green
Write-Host "Tip: python -m dragonflight" -ForegroundColor DarkGray
