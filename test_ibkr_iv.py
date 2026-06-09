"""
IBKR IV/HV data test — run on the Windows desktop with IB Gateway running.
Confirms the new options-data subscription delivers:
  1. Historical OPTION_IMPLIED_VOLATILITY bars on the underlying  (the IV-Rank series)
  2. Historical HISTORICAL_VOLATILITY bars                        (for IV/HV)
  3. (best-effort) live option model greeks / implied vol         (needs market open)

Usage (use the venv interpreter directly — `py -3.13` bypasses the venv):
    cd C:\\ibkr_screener
    venv\\Scripts\\python.exe test_ibkr_iv.py
"""

from ib_insync import IB, Stock, Option

HOST       = '127.0.0.1'
PORT       = 4001          # live gateway (paper = 4002)
CLIENT_ID  = 5             # 1=test_connection, 2=screener, 3=monitor -> 5 free
TEST_TICKER = 'AAPL'


def divider(t):
    print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)


def hist_vol_series(ib, stock, what, label):
    """Pull ~1Y of daily vol bars; return list of (date, value)."""
    try:
        bars = ib.reqHistoricalData(
            stock, endDateTime='', durationStr='1 Y',
            barSizeSetting='1 day', whatToShow=what,
            useRTH=True, formatDate=1)
    except Exception as e:
        print(f"  ✗ {label}: request failed -> {e}")
        return []
    if not bars:
        print(f"  ✗ {label}: 0 bars returned (subscription / permission issue?)")
        return []
    series = [(b.date, b.close) for b in bars if b.close is not None and b.close > 0]
    print(f"  ✓ {label}: {len(series)} bars  "
          f"[{series[0][0]} .. {series[-1][0]}]")
    print(f"    last 5: " + ", ".join(f"{v:.3f}" for _, v in series[-5:]))
    return series


def main():
    ib = IB()
    divider(f"CONNECT  {HOST}:{PORT}  clientId={CLIENT_ID}")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"  ✗ Could not connect to IB Gateway: {e}")
        print("    Is IB Gateway running and logged in on port", PORT, "?")
        return
    print(f"  ✓ Connected: {ib.isConnected()}  (server v{ib.client.serverVersion()})")

    stock = Stock(TEST_TICKER, 'SMART', 'USD')
    try:
        ib.qualifyContracts(stock)
        print(f"  ✓ Qualified {TEST_TICKER}  conId={stock.conId}")
    except Exception as e:
        print(f"  ✗ Could not qualify {TEST_TICKER}: {e}")
        ib.disconnect(); return

    # ── 1. Historical implied volatility (the IV-Rank series) ──
    divider("1. HISTORICAL OPTION_IMPLIED_VOLATILITY")
    iv_series = hist_vol_series(ib, stock, 'OPTION_IMPLIED_VOLATILITY', 'IV')
    if iv_series:
        vals = [v for _, v in iv_series]
        cur, lo, hi = vals[-1], min(vals), max(vals)
        if hi > lo:
            rank = (cur - lo) / (hi - lo) * 100
            print(f"    => IV Rank (demo): cur {cur:.3f} in [{lo:.3f}, {hi:.3f}] = {rank:.0f}/100")
            print(f"    (compare this to the IV Rank shown in TWS for {TEST_TICKER})")

    # ── 2. Historical (realized) volatility, for IV/HV ──
    divider("2. HISTORICAL_VOLATILITY (realized)")
    hv_series = hist_vol_series(ib, stock, 'HISTORICAL_VOLATILITY', 'HV')
    if iv_series and hv_series:
        iv_hv = iv_series[-1][1] / hv_series[-1][1] if hv_series[-1][1] else None
        if iv_hv:
            print(f"    => IV/HV (demo): {iv_series[-1][1]:.3f} / {hv_series[-1][1]:.3f} = {iv_hv:.2f}")

    # ── 3. Live option model greeks / IV (best effort; needs market open) ──
    divider("3. LIVE OPTION GREEKS / IV  (best-effort — needs market open)")
    try:
        ib.reqMarketDataType(1)  # 1=live; will fall back if delayed-only
        chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        if not chains:
            print("  ✗ No option parameters returned.")
        else:
            chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
            expirations = sorted(chain.expirations)
            strikes = sorted(chain.strikes)
            # pick a near-term expiry and a near-ATM strike
            [ticker_md] = ib.reqTickers(stock)
            spot = ticker_md.marketPrice() or ticker_md.close
            atm = min(strikes, key=lambda k: abs(k - spot)) if spot else strikes[len(strikes)//2]
            expiry = expirations[len(expirations)//2]
            opt = Option(TEST_TICKER, expiry, atm, 'P', 'SMART')
            ib.qualifyContracts(opt)
            t = ib.reqMktData(opt, '', False, False)
            ib.sleep(3)
            mg = t.modelGreeks
            if mg and mg.impliedVol:
                print(f"  ✓ Live option {TEST_TICKER} {expiry} P{atm}: "
                      f"IV={mg.impliedVol:.3f} delta={mg.delta:.3f} theta={mg.theta:.4f}")
            else:
                print("  ⚠ No live greeks (market likely closed, or delayed-data only). "
                      "Historical IV/HV above is what the IV-Rank series needs anyway.")
            ib.cancelMktData(opt)
    except Exception as e:
        print(f"  ⚠ Live greeks step skipped: {e}")

    divider("SUMMARY")
    print(f"  Historical IV bars : {'OK (' + str(len(iv_series)) + ')' if iv_series else 'MISSING'}")
    print(f"  Historical HV bars : {'OK (' + str(len(hv_series)) + ')' if hv_series else 'MISSING'}")
    print("  If both show OK, IBKR can be the canonical IV-Rank source.")
    print("  If IV bars are MISSING, the options-data permission isn't applying to")
    print("  historical IV yet — we stay on yfinance for the rank series.")

    ib.disconnect()
    print("\n  Disconnected.")


if __name__ == '__main__':
    main()
