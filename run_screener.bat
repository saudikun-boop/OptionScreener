@echo off
REM Run the IBKR put screener (no IB Gateway needed)
REM Output saved to: C:\ibkr_screener\reports\screener_output.csv

cd /d C:\ibkr_screener
if not exist logs mkdir logs
call venv\Scripts\activate
python code\screener.py >> logs\screener.log 2>&1
