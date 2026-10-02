$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$state = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 5
if ($state.running -or $state.armed -or $state.connected) { throw 'Stop replay/auto trading and disconnect Kiwoom in the app first.' }
if (@($state.orders | Where-Object { $_.status -in @('SENDING','ACCEPTED','PARTIAL','CANCEL_PENDING','UNKNOWN') }).Count -gt 0) { throw 'Resolve pending broker orders before shutdown.' }
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction Stop
$proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$expected = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($proc.ExecutablePath -ne $expected -or $proc.CommandLine -notmatch 'backend.app') { throw 'Process identity mismatch; nothing stopped.' }
Stop-Process -Id $proc.ProcessId -ErrorAction Stop
Write-Host 'S4.3-R Trader stopped. Saved records remain in runtime.'
