<#
Opens the Independent Trading Agent dashboard: starts the local server in the
background (no console window) if it is not already running, then opens
http://127.0.0.1:8765 in an Edge app window (or the default browser).
Used by the desktop shortcut; see create_shortcut.ps1.
#>
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$port = 8765
$url = "http://127.0.0.1:$port/"

function Test-Dashboard {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true }
    catch { return $false }
}

if (-not (Test-Dashboard)) {
    $pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $pythonw)) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("محیط پایتون پروژه پیدا نشد:`n$pythonw", "میز هوشمندی بازار") | Out-Null
        exit 1
    }
    Start-Process -FilePath $pythonw -ArgumentList "-m independent_trading_agent serve --no-browser --port $port" `
        -WorkingDirectory $repo -WindowStyle Hidden
    for ($i = 0; $i -lt 60 -and -not (Test-Dashboard); $i++) { Start-Sleep -Milliseconds 250 }
    if (-not (Test-Dashboard)) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("سرور داشبورد بالا نیامد. جزئیات در independent_trading_agent\logs\independent_agent.log", "میز هوشمندی بازار") | Out-Null
        exit 1
    }
}

$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) { Start-Process -FilePath $edge -ArgumentList "--app=$url" } else { Start-Process $url }
