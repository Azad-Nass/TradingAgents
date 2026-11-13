<#
Registers (or removes) a Windows Task Scheduler job that runs the
Independent Trading Agent's daily run on weekdays.

  Install:   powershell -ExecutionPolicy Bypass -File independent_trading_agent\scheduler\windows_task.ps1 -Time 18:30
  Remove:    powershell -ExecutionPolicy Bypass -File independent_trading_agent\scheduler\windows_task.ps1 -Remove
  Run now:   Start-ScheduledTask -TaskName "IndependentTradingAgentDaily"

The task runs as the current user, only when logged on, with the project's
own virtual environment. The app itself skips days on which no enabled
market trades, holds a lock against overlapping runs and logs to
independent_trading_agent\logs\independent_agent.log.
#>
param(
    [string]$Time = "18:30",
    [string]$TaskName = "IndependentTradingAgentDaily",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed $TaskName"
    return
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python not found at $python; create the .venv first (see README)." }

$action = New-ScheduledTaskAction -Execute $python -Argument "-m independent_trading_agent daily" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Independent Trading Agent: daily scan, analysis and Persian report (simulation only)." -Force | Out-Null
Write-Output "Registered $TaskName weekdays at $Time (local time) -> $python -m independent_trading_agent daily"
