@echo off
setlocal
REM Weekly: refresh IBKR IV/HV history (needs IB Gateway up). Streams output live to the
REM console AND logs\weekly.log via PowerShell Tee-Object. Schedule e.g. Sunday:
REM   schtasks /Create /TN "OptionsWeeklyIV" /TR "C:\ibkr_screener\run_weekly.bat" /SC WEEKLY /D SUN /ST 17:00
cd /d C:\ibkr_screener
if not exist logs mkdir logs
set "LOG=logs\weekly.log"
type nul > "%LOG%"

echo(
echo ================================================================
echo  WEEKLY IV REFRESH   update_iv_history.py  (full-year IBKR IV/HV)
echo  [%date% %time%]  running (needs IB Gateway) ...
echo ================================================================
echo [%date% %time%] update_iv_history.py >> "%LOG%"
venv\Scripts\python.exe update_iv_history.py 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG%' -Append"

echo(
echo  [%date% %time%]  DONE   full log: %LOG%
endlocal
goto :eof
