@echo off
REM Daily full run: monitor (needs IB Gateway up) -> screener -> Telegram report.
REM Output (incl. call-write detection / coverage diagnostics) is saved to logs\daily.log
REM and also echoed to the console. Schedule with Windows Task Scheduler, e.g.:
REM   schtasks /Create /TN "OptionsDailyReport" /TR "C:\ibkr_screener\run_daily.bat" /SC DAILY /ST 08:00
cd /d C:\ibkr_screener
if not exist logs mkdir logs
set "LOG=logs\daily.log"

echo [%date% %time%] START > "%LOG%"

echo [%date% %time%] monitor.py        (positions, rolls, call-writes - needs IB Gateway) >> "%LOG%"
venv\Scripts\python.exe monitor.py        >> "%LOG%" 2>&1

echo [%date% %time%] screener.py       (ranked put candidates) >> "%LOG%"
venv\Scripts\python.exe screener.py       >> "%LOG%" 2>&1

echo [%date% %time%] daily_report.py   (Telegram digest + CSV attachments) >> "%LOG%"
venv\Scripts\python.exe daily_report.py   >> "%LOG%" 2>&1

echo [%date% %time%] DONE >> "%LOG%"

REM Show this run's log on the console when run interactively
type "%LOG%"
