@echo off
setlocal
REM Daily full run: monitor (needs IB Gateway up) -> screener -> Telegram report.
REM Each step prints a banner and streams its output LIVE to the console AND logs\daily.log.
REM Schedule with Windows Task Scheduler, e.g.:
REM   schtasks /Create /TN "OptionsDailyReport" /TR "C:\ibkr_screener\run_daily.bat" /SC DAILY /ST 08:00
cd /d C:\ibkr_screener
if not exist logs mkdir logs
set "LOG=logs\daily.log"
type nul > "%LOG%"

call :run "[1/3] MONITOR   positions, rolls, call-writes  (needs IB Gateway)" monitor.py
call :run "[2/3] SCREENER  ranked put candidates (~158 tickers - one line per ticker)" screener.py
call :run "[3/3] REPORT    Telegram digest + Excel attachment" daily_report.py

echo(
echo ================================================================
echo  [%date% %time%]  ALL STEPS COMPLETE   full log: %LOG%
echo ================================================================
endlocal
goto :eof

:run
echo(
echo ================================================================
echo  %~1
echo  [%date% %time%]  running %~2 ...
echo ================================================================
powershell -NoProfile -Command "& '.\venv\Scripts\python.exe' -u %~2 2>&1 | Tee-Object -FilePath '%LOG%' -Append"
goto :eof
