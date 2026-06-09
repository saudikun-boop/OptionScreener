@echo off
REM Weekly: refresh IBKR IV/HV history (needs IB Gateway up). Schedule e.g. Sunday:
REM   schtasks /Create /TN "OptionsWeeklyIV" /TR "C:\ibkr_screener\run_weekly.bat" /SC WEEKLY /D SUN /ST 17:00
cd /d C:\ibkr_screener
echo [%date% %time%] update_iv_history.py
venv\Scripts\python.exe update_iv_history.py
echo [%date% %time%] done
