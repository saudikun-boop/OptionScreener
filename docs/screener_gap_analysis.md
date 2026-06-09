# screener.py — Gap Analysis vs Screening Spec

**Date:** 2026-06-08
**Reviewed file:** `screener.py` (Entry 003 state)
**Compared against:** `docs/screening_spec.md`

## TL;DR
`screener.py` currently implements only the **option-mechanics slice** of the spec: DTE window, delta band, strike range, IV (Black-Scholes), theta, and an earnings filter. The **entire fundamentals bucket, the entire technical bucket, the IV-edge metrics (IV Rank, IV/HV), the liquidity gate, and the scoring/ranking layer are not yet implemented.** Output is sorted, not scored.

Also note a **data-source divergence**: the spec was written assuming IBKR, but the actual implementation uses **yfinance + Black-Scholes** (IBKR requires a paid Level 1 sub for options data). The "how to add" column below is written for the yfinance reality.

---

## What's already implemented ✅

| Spec item | Status | Notes |
|---|---|---|
| DTE window (GATE) | ✅ | 15–60 (spec suggested 30–45; widened deliberately per Entry 002) |
| Delta band (GATE) | ✅ | `abs(delta)` 0.15–0.30 |
| IV per option | ✅ | Solved via Black-Scholes from mid/last price (robust when market closed) |
| Theta | ✅ | Computed, but **not scored** |
| Earnings gate | ✅ | Skips any expiry that straddles next earnings — equivalent to / better than the "7 days out" rule |
| Strike range | ✅ | 0.75–1.02 × spot |

---

## Gaps — ordered by impact

### 🔴 1. Liquidity gate — MISSING (highest priority, cheapest fix)
Spec marks bid-ask spread % and open interest as hard **GATES**. Screener captures `bid`/`ask`/`volume`/`openInterest` from the chain but **filters on none of them**. Right now an illiquid strike with a 30%-wide spread can rank alongside a tradable one.
**Add:** drop rows where `(ask-bid)/mid > ~0.10` and `openInterest < ~100`. yfinance `option_chain().puts` already includes `openInterest` and `volume`.

### 🔴 2. Scoring / ranking layer — MISSING
Output is `sort_values(['ticker','dte','strike'])` — there is no composite score. The spec's whole point (gates prune → score ranks) isn't realized; you can't tell the best candidate from the worst.
**Add:** the annualized-return + normalized weighted composite from spec §4/§7.

### 🔴 3. Annualized return on collateral — MISSING
Not computed. This is the core yield metric for ranking.
**Add:** `(premium/strike)/dte*365` as a column. Trivial — data is already in hand.

### 🟠 4. IV Rank & IV/HV ratio — MISSING (the stated edge)
No IV Rank, no IV/HV. The spec calls IV/HV the single most predictive seller metric. yfinance gives no historical *implied* vol, so:
- **HV:** compute from price history (yfinance `history()` → stdev of log returns, annualized). IV/HV is then immediately available.
- **IV Rank:** needs an IV history you don't have yet. Since the screener runs daily, **persist each ticker's ATM IV to a CSV/SQLite on every run** and build the 52-wk range over time (same pattern the spec describes for IBKR, just sourced from yfinance/BS).

### 🟠 5. Fundamentals bucket — ENTIRELY MISSING
No valuation, growth, ROIC/ROE, dividend, and — most importantly — **no solvency gate** (the spec's "don't get assigned a falling knife" guard). Good news: most of this is free via `yf.Ticker(t).info` (`forwardPE`, `pegRatio`, `returnOnEquity`, `debtToEquity`, `revenueGrowth`, `dividendYield`, `payoutRatio`). Piotroski/Altman components are derivable from yfinance financial statements, or use FMP if you want them prebuilt.
**Add at minimum:** a solvency/leverage GATE + valuation/ROIC SCORE.

### 🟠 6. Technical bucket — ENTIRELY MISSING
No 200-MA regime gate, no 50-MA, RSI, Bollinger, or swing-low support. `pandas-ta` is installed but unused by the screener. All achievable from yfinance price history.
**Add at minimum:** the **200-MA regime GATE** (price > 200-MA) — single highest-value technical filter — then RSI/Bollinger as SCORE.

### 🟡 7. Minor
- Universe is hardcoded Mag7 (7 names) — fine for testing; spec assumes a wider watchlist. Expanding the universe is what makes gates/scoring meaningful (7 names rarely need ranking).
- Put skew, expected-value metric — nice-to-have, low priority.

---

## Suggested build order
1. **Liquidity gate** (1 hr, prevents untradable picks) →
2. **Annualized return + composite scoring** (turns the list into a ranking) →
3. **200-MA regime gate + HV/IV-HV** (price history you'll pull anyway) →
4. **Start persisting daily IV** (so IV Rank exists in ~3 months) →
5. **Fundamentals solvency gate + valuation score** →
6. Expand watchlist, then add the rest of the technical/fundamental scores.

> Note: items 1–3 are mostly free given data already in `screen_ticker()`. The fundamentals/technical buckets are the larger lifts.
