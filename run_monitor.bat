@echo off
REM Run the IBKR position monitor (requires IB Gateway running on port 4001)
REM Output saved to: C:\ibkr_screener\monitor_output.csv

cd /d C:\ibkr_screener
call venv\Scripts\activate
python monitor.py >> logs\monitor.log 2>&1
