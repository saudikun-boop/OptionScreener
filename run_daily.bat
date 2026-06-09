@echo off
REM Daily full run: monitor (needs IB Gateway up) -> screener -> Telegram report.
REM Schedule this with Windows Task Scheduler, e.g.:
REM   schtasks /Create /TN "OptionsDailyReport" /TR "C:\ibkr_screener\run_daily.bat" /SC DAILY /ST 08:00
cd /d C:\ibkr_screener

echo [%date% %time%] monitor.py
venv\Scripts\python.exe monitor.py

echo [%date% %time%] screener.py
venv\Scripts\python.exe screener.py

echo [%date% %time%] daily_report.py
venv\Scripts\python.exe daily_report.py

echo [%date% %time%] done
