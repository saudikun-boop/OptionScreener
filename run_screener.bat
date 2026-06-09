@echo off
REM Run the IBKR put screener (no IB Gateway needed)
REM Output saved to: C:\ibkr_screener\screener_output.csv

cd /d C:\ibkr_screener
call venv\Scripts\activate
python screener.py >> logs\screener.log 2>&1
