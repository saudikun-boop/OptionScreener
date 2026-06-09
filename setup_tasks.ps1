# setup_tasks.ps1
# Registers two Windows Scheduled Tasks:
#   - ibkr_screener  : runs screener.py at 8:30 AM ET, Mon-Fri
#   - ibkr_monitor   : runs monitor.py  at 8:35 AM ET, Mon-Fri
#
# Run once from an elevated PowerShell prompt:
#   cd C:\ibkr_screener
#   .\setup_tasks.ps1
#
# Notes:
#   - IB Gateway must already be running (auto-started or manual) before monitor runs
#   - Times below assume your PC clock is in ET (or adjust accordingly)
#   - Logs are written to C:\ibkr_screener\logs\

$projectDir = "C:\ibkr_screener"

# Create logs folder if it doesn't exist
New-Item -ItemType Directory -Force -Path "$projectDir\logs" | Out-Null

# ── Task 1: Screener (8:30 AM, Mon-Fri) ──────────────────────────────────────
$screenerAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$projectDir\run_screener.bat`"" `
    -WorkingDirectory $projectDir

$screenerTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "8:30AM"

$screenerSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "ibkr_screener" `
    -Action $screenerAction `
    -Trigger $screenerTrigger `
    -Settings $screenerSettings `
    -Description "Daily pre-market IBKR put screener (Mag7, yfinance + Black-Scholes)" `
    -Force

Write-Host "Registered: ibkr_screener  (8:30 AM Mon-Fri)"

# ── Task 2: Monitor (8:35 AM, Mon-Fri) ───────────────────────────────────────
$monitorAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$projectDir\run_monitor.bat`"" `
    -WorkingDirectory $projectDir

$monitorTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "8:35AM"

$monitorSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "ibkr_monitor" `
    -Action $monitorAction `
    -Trigger $monitorTrigger `
    -Settings $monitorSettings `
    -Description "Daily pre-market IBKR position monitor (requires IB Gateway on port 4001)" `
    -Force

Write-Host "Registered: ibkr_monitor   (8:35 AM Mon-Fri)"

Write-Host ""
Write-Host "Done. Verify in Task Scheduler (taskschd.msc) -> Task Scheduler Library."
Write-Host "Logs: $projectDir\logs\"
