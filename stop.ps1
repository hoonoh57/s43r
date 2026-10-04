# stop.ps1 -- ASCII only. Stops every process on port 8775 (any folder) + stale s43r instances.
param([int]$Port = 8775)
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot
$base = "http://127.0.0.1:$Port"

# 1) Graceful: halt automation and disconnect Kiwoom if this app answers.
try {
    $boot = Invoke-RestMethod -Uri "$base/api/bootstrap" -TimeoutSec 3
    if ($boot.name -like 'S4.3-R*') {
        $h = @{ 'x-session' = $boot.token }
        $state = Invoke-RestMethod -Uri "$base/api/state" -TimeoutSec 5
        if ($state.running) { Invoke-RestMethod -Method Post -Uri "$base/api/control" -Headers $h -ContentType 'application/json' -Body '{"action":"stop_replay"}' -TimeoutSec 5 | Out-Null }
        if ($state.armed)   { Invoke-RestMethod -Method Post -Uri "$base/api/control" -Headers $h -ContentType 'application/json' -Body '{"action":"halt"}' -TimeoutSec 5 | Out-Null }
        $open = @($state.orders | Where-Object { $_.status -in 'SENDING','ACCEPTED','PARTIAL','CANCEL_PENDING','UNKNOWN' }).Count
        if ($open -gt 0) { Write-Host "[WARN] $open pending order(s) may remain at the broker. Check HTS after restart." }
        if ($state.connected) { Invoke-RestMethod -Method Post -Uri "$base/api/disconnect" -Headers $h -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null }
        Write-Host '[OK] automation halted, Kiwoom disconnected'
    }
} catch { Write-Host "[INFO] graceful step skipped: $($_.Exception.Message)" }

# 2) Collect targets: all port listeners + stale backend.app from this folder, with python parent/children.
$all  = @(Get-CimInstance Win32_Process)
$byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
$seed = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
$root = [regex]::Escape($PSScriptRoot)
$seed += @($all | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -match 'backend' -and (($_.CommandLine -match $root) -or ($_.ExecutablePath -match $root)) } | ForEach-Object { [int]$_.ProcessId })
$targets = New-Object 'System.Collections.Generic.HashSet[int]'
function Add-Tree([int]$id) {
    if ($id -le 4 -or $id -eq $PID -or -not $byId.ContainsKey($id) -or -not $targets.Add($id)) { return }
    $par = [int]$byId[$id].ParentProcessId
    if ($byId.ContainsKey($par) -and $byId[$par].Name -like 'python*.exe') { Add-Tree $par }
    foreach ($c in $all | Where-Object { [int]$_.ParentProcessId -eq $id -and $_.Name -like 'python*.exe' }) { Add-Tree ([int]$c.ProcessId) }
}
foreach ($id in $seed) { Add-Tree ([int]$id) }

# 3) Stop and verify.
if ($targets.Count -eq 0) { Write-Host "[OK] nothing running on port $Port"; exit 0 }
foreach ($id in $targets) {
    Write-Host ("  stop PID {0}  {1}" -f $id, $byId[$id].CommandLine)
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
$left  = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
$alive = @($targets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
if ($left.Count -or $alive.Count) { Write-Host "[FAIL] still alive PID: $($alive -join ', ') / port listeners: $($left.Count). Retry as administrator."; exit 1 }
Write-Host "[OK] stopped $($targets.Count) process(es); port $Port is free. Records remain in runtime."
