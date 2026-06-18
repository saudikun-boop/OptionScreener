@echo off
REM Run the IBKR position monitor (requires IB Gateway running on port 4001)
REM Output saved to: C:\ibkr_screener\reports\monitor_output.csv

cd /d C:\ibkr_screener
if not exist logs mkdir logs
call venv\Scripts\activate
python code\monitor.py >> logs\monitor.log 2>&1
