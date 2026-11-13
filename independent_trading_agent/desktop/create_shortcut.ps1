<#
Creates the desktop shortcut "میز هوشمندی بازار" that opens the dashboard.
  powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\create_shortcut.ps1
  powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\create_shortcut.ps1 -Remove
#>
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "میز هوشمندی بازار.lnk"
$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop $name
if ($Remove) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path; Write-Output "Removed $path" } else { Write-Output "No shortcut at $path" }
    return
}
$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here "..\..")).Path
$shell = New-Object -ComObject WScript.Shell
# WScript.Shell cannot write a non-ANSI file name: save under an ASCII name, then rename.
$tmp = Join-Path $desktop "ITA-Dashboard-tmp.lnk"
$lnk = $shell.CreateShortcut($tmp)
$lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $here 'launch_dashboard.ps1')`""
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = "$(Join-Path $here 'icon.ico'),0"
$lnk.WindowStyle = 7
$lnk.Description = "Independent Trading Agent dashboard (local, simulation only)"
$lnk.Save()
Move-Item -LiteralPath $tmp -Destination $path -Force
Write-Output "Created $path"
