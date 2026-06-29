"""
Quick diagnostic on TODAY's prices:
  • <200MA FLAG  — names below a FALLING 200-MA (the new screener flag; NOT filtered out,
                   just marked with '*' so you can see your "buy the dip" candidates).
  • regime GATE  — names still hard-filtered by the breakdown gate (sharp drop / vol spike,
                   plus slow-downtrend only if regime.block_below_falling_ma is on).

Reuses screener.py's exact functions. Fast (prices only). Run with internet:

    python code/check_gate.py
"""

import screener as S


def main():
    names = S.EQUITIES + S.ETFS
    print(f"Trend check on current prices — {len(names)} names")
    print(f"regime mode={S.REGIME_MODE} | block_below_falling_ma={S.BLOCK_BELOW_FALLING_MA} "
          f"(False = flag only, not filtered)\n")

    flagged, gated, passed, skipped = [], [], 0, 0
    for t in names:
        yf_t = S.yf.Ticker(t)
        price = S.get_price(yf_t)
        hist = S.get_price_history(yf_t)
        if not price or hist is None:
            skipped += 1
            continue
        tech = S.compute_technicals(hist)
        ma200, slope = tech.get('ma200'), tech.get('ma200_slope')
        below = bool(ma200 and slope is not None and price < ma200 and slope < 0)
        is_block, why = S.regime_block(price, tech)
        if below:
            flagged.append((t, price, ma200, slope))
        if is_block:
            gated.append((t, price, why))
        else:
            passed += 1

    print(f"PASS gate {passed}   GATED {len(gated)}   <200MA flagged {len(flagged)}   "
          f"skipped(no data) {skipped}\n")

    print("── <200MA FLAG (below a FALLING 200-MA — kept in results, marked '*') ──")
    if not flagged:
        print("  (none today)")
    for t, p, ma, sl in sorted(flagged):
        below = (p / ma - 1) * 100 if ma else float('nan')
        slope = f"{sl*100:+5.1f}%/mo" if sl is not None else "  n/a"
        print(f"  {t:<6} ${p:>9.2f}   200-MA ${ma:>9.2f} ({below:+5.1f}%)   slope {slope}")

    print("\n── regime GATE (hard-filtered before scoring) ──")
    if not gated:
        print("  (none today)")
    for t, p, why in sorted(gated):
        print(f"  {t:<6} ${p:>9.2f}   {why}")


if __name__ == '__main__':
    main()
