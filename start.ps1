$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try { $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/bootstrap' -TimeoutSec 2 } catch { $existing = $null }
if ($existing.name -eq 'S4.3-R Trader') { Write-Host 'Already running: http://127.0.0.1:8765'; exit 0 }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { & '.\setup.ps1' }
Write-Host 'S4.3-R Trader: http://127.0.0.1:8765  (Ctrl+C to stop)'
& '.\.venv\Scripts\python.exe' -m backend.app
