"""
IBKR IV/HV history updater (Option A) — run on the Windows desktop with IB Gateway up.

Pulls each watchlist ticker's 1-year DAILY implied & historical volatility from
IBKR and refreshes data/iv_history.csv (source='ibkr'). One run = full-year
history, so IV Rank works immediately. The screener never needs IB Gateway — it
just reads the CSV this writes. Safe to run daily or weekly (a 1-yr window
doesn't care about a missing day or two).

Usage:
    cd C:\\ibkr_screener
    venv\\Scripts\\python.exe update_iv_history.py
"""

import os
import logging
from ib_insync import IB, Stock

import screener as S          # reuse TICKERS, IV_HISTORY_PATH, helpers
import pandas as pd

logging.getLogger('ib_insync').setLevel(logging.CRITICAL)  # quiet Error 200 on contract fallbacks

HOST      = '127.0.0.1'
PORT      = 4001              # live gateway (paper = 4002)
CLIENT_ID = 4                # 1=test_connection, 2=screener(reserved), 3=monitor, 5=test

# IBKR symbology differs from yfinance for some names (share classes etc.).
# Map the yfinance watchlist ticker -> IBKR symbol; rows are still stored under
# the original ticker so the screener (yfinance side) matches them.
IBKR_SYMBOL = {'BRK-B': 'BRK B', 'BRK.B': 'BRK B', 'BF-B': 'BF B'}


def qualify_stock(ib, ticker):
    """Resolve an IBKR Stock contract, trying SMART then primary exchanges."""
    sym = IBKR_SYMBOL.get(ticker, ticker.replace('-', ' '))
    for kwargs in ({}, {'primaryExchange': 'NYSE'}, {'primaryExchange': 'NASDAQ'},
                   {'primaryExchange': 'ARCA'}):
        c = Stock(sym, 'SMART', 'USD', **kwargs)
        try:
            if ib.qualifyContracts(c) and c.conId:
                return c
        except Exception:
            pass
    return None


def fetch_vol(ib, stock, what):
    """Return {date_str: value} of daily vol bars for a whatToShow type."""
    bars = ib.reqHistoricalData(
        stock, endDateTime='', durationStr='1 Y',
        barSizeSetting='1 day', whatToShow=what, useRTH=True, formatDate=1)
    return {str(b.date): b.close for b in bars if b.close is not None and b.close > 0}


def main():
    ib = IB()
    print(f"Connecting to IB Gateway {HOST}:{PORT} (clientId={CLIENT_ID}) ...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"✗ Could not connect: {e}")
        print("  Is IB Gateway running and logged in on port", PORT, "?")
        return
    print(f"✓ Connected: {ib.isConnected()}  (server v{ib.client.serverVersion()})\n")

    rows, failed = [], []
    for t in S.TICKERS:
        try:
            stk = qualify_stock(ib, t)
            if stk is None:
                failed.append(t)
                print(f"  ✗ {t}: could not resolve IBKR contract")
                continue
            iv = fetch_vol(ib, stk, 'OPTION_IMPLIED_VOLATILITY')
            hv = fetch_vol(ib, stk, 'HISTORICAL_VOLATILITY')
            for d in sorted(set(iv) | set(hv)):
                rows.append({'date': d, 'ticker': t,
                             'iv': iv.get(d), 'hv': hv.get(d), 'source': 'ibkr'})
            print(f"  ✓ {t}: {len(iv)} IV / {len(hv)} HV bars")
        except Exception as e:
            failed.append(t)
            print(f"  ✗ {t}: {e}")

    ib.disconnect()
    if failed:
        print(f"\nUnresolved on IBKR ({len(failed)}): {', '.join(failed)}")

    if not rows:
        print("\nNo data fetched — nothing written.")
        return

    new = pd.DataFrame(rows)[S.IV_HISTORY_COLS]
    os.makedirs(os.path.dirname(S.IV_HISTORY_PATH), exist_ok=True)
    if os.path.exists(S.IV_HISTORY_PATH):
        old = S.load_iv_history()
        if old is not None:
            # refresh IBKR rows for these tickers; keep everything else (yf backup)
            old = old[~((old['source'] == 'ibkr') & (old['ticker'].isin(new['ticker'])))]
            new = pd.concat([old, new], ignore_index=True)
    new = (new[S.IV_HISTORY_COLS]
           .sort_values(['ticker', 'source', 'date'])
           .reset_index(drop=True))
    new.to_csv(S.IV_HISTORY_PATH, index=False)
    print(f"\nSaved -> {S.IV_HISTORY_PATH}  ({len(rows)} IBKR rows, {len(new)} total)")

    # IV Rank preview (what the screener will use)
    print("\nIV Rank preview (source the screener will pick):")
    for t in S.TICKERS:
        rank, src, iv_now, hv_now = S.ticker_iv_rank(new, t)
        if rank is not None:
            ivhv = f"{iv_now/hv_now:.2f}" if hv_now else "n/a"
            print(f"  {t}: IV Rank {rank:4.0f}/100  (src={src}, IV={iv_now:.3f}, IV/HV={ivhv})")
        else:
            print(f"  {t}: insufficient history")


if __name__ == '__main__':
    main()
