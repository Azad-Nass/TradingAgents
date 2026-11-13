<#
Stops the dashboard server started by the desktop shortcut (whatever listens on 127.0.0.1:8765).
  powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\stop_dashboard.ps1
#>
$port = 8765
$conns = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) { Write-Output "Dashboard is not running."; return }
$conns | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    $p = Get-Process -Id $_ -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") { Stop-Process -Id $_ -Force; Write-Output "Stopped dashboard (PID $_)." }
    else { Write-Output "Port $port is used by $($p.ProcessName) (PID $_); not stopped." }
}
