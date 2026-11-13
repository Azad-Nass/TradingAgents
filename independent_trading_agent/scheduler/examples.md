# Scheduling examples

The scheduled command is always the same, run from the repository root
(the folder that contains `independent_trading_agent/`):

```
<repo>/.venv/bin/python -m independent_trading_agent daily      # Linux / macOS
<repo>\.venv\Scripts\python.exe -m independent_trading_agent daily   # Windows
```

The app checks the market calendars itself (it skips a day on which no
enabled market trades unless `--force` is given), takes a lock so two runs
never overlap, retries a failed data fetch once, and logs to
`independent_trading_agent/logs/independent_agent.log` with keys masked.

## Windows Task Scheduler

See `windows_task.ps1` in this folder.

## Linux cron

`crontab -e`, then (18:30 local time, Monday to Friday):

```
30 18 * * 1-5 cd /path/to/TradingAgents && .venv/bin/python -m independent_trading_agent daily >> independent_trading_agent/logs/cron.log 2>&1
```

## macOS launchd

Save as `~/Library/LaunchAgents/com.local.independent-trading-agent.plist`,
replace `/path/to/TradingAgents`, then
`launchctl load ~/Library/LaunchAgents/com.local.independent-trading-agent.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local.independent-trading-agent</string>
  <key>WorkingDirectory</key><string>/path/to/TradingAgents</string>
  <key>ProgramArguments</key><array>
    <string>/path/to/TradingAgents/.venv/bin/python</string>
    <string>-m</string><string>independent_trading_agent</string><string>daily</string>
  </array>
  <key>StartCalendarInterval</key><array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/path/to/TradingAgents/independent_trading_agent/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>/path/to/TradingAgents/independent_trading_agent/logs/launchd.log</string>
</dict></plist>
```
