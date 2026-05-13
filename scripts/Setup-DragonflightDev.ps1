<#
.SYNOPSIS
  One-time setup: create .venv with Python 3.11-3.13 and install Dragonflight + dev deps.

.NOTES
  Run from anywhere:
    powershell -ExecutionPolicy Bypass -File .\scripts\Setup-DragonflightDev.ps1
#>
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Find-PythonForPygame {
    foreach ($ver in @("3.12", "3.13", "3.11")) {
        try {
            $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                return @{ Version = $ver; Executable = $exe.Trim() }
            }
        } catch {
            continue
        }
    }
    return $null
}

Write-Host "Dragonflight dev setup (project root: $ProjectRoot)" -ForegroundColor Cyan

$found = Find-PythonForPygame
if (-not $found) {
    Write-Host @"

No Python 3.11 / 3.12 / 3.13 found via the 'py' launcher.

Install one of them:
  1. https://www.python.org/downloads/windows/
  2. Run the installer; enable "Add python.exe to PATH" and "py launcher".
  3. Pick 3.12.x (recommended), then run this script again.

"@ -ForegroundColor Yellow
    exit 1
}

Write-Host "Using Python $($found.Version): $($found.Executable)" -ForegroundColor Green

& $found.Executable -m venv "$ProjectRoot\.venv"
& "$ProjectRoot\.venv\Scripts\python.exe" -m pip install --upgrade pip
Set-Location $ProjectRoot
& "$ProjectRoot\.venv\Scripts\pip.exe" install -e ".[dev]"

Write-Host "`nDone. Open a dev shell with:" -ForegroundColor Green
Write-Host "  . .\DevShell.ps1" -ForegroundColor White
Write-Host "Or double-click: scripts\Open-DragonflightDev.cmd`n" -ForegroundColor White
