# Options Screening Spec — Wheel / Short-Put Income System

**Strategy frame:** Sell cash-secured puts (and covered calls post-assignment) on quality stocks you'd be happy to own, when you're being overpaid in premium relative to realized risk. The screen is NOT "will this stock go up" — it's **"would I want to own this if assigned, and am I getting paid richly to wait?"**

**How to read this doc:**
- **GATE** = hard filter. Fail it → drop the candidate. A name can NEVER score its way past a gate. Keep these few and non-negotiable.
- **SCORE** = normalize to 0–100, then combine into a weighted composite to rank survivors.
- **GATE + SCORE** = has a floor AND contributes to the rank above that floor.
- Flow: **gates prune the universe → score ranks the survivors.** Don't hard-gate everything or you'll get zero candidates most days.

---

## 1. Fundamentals — "would I want to own this if put to me?"

| Metric | Type | Threshold / Logic | Why | Source |
|---|---|---|---|---|
| Forward P/E | SCORE | Score vs the stock's own 5-yr history (z-score) AND sector median. Cheaper = higher score. | "Excessively valued" is relative, not absolute. Trailing P/E misleads across sectors. | FMP |
| PEG ratio | SCORE | < 1.5 favored; lower = better | Valuation adjusted for growth | FMP |
| Revenue growth (3-yr CAGR) | SCORE | Positive & steady favored | Growth trajectory | FMP |
| Revenue growth *stability* | SCORE | Low stdev of YoY growth = higher score | Steady compounder > volatile grower as collateral | FMP (derive) |
| FCF growth + FCF positive | GATE + SCORE | GATE: FCF > 0 (most recent FY). SCORE: growth trend | Cash generation = survivability | FMP |
| Gross/operating margin trend | SCORE | Stable or rising = higher score | Business quality | FMP |
| ROIC − WACC | SCORE | > 0 to score well; bigger = better | Value creation, not just a high ROIC number | FMP |
| ROE | SCORE | Secondary quality signal | Profitability | FMP |
| **Solvency gate (Piotroski F or Altman Z)** | **GATE** | Piotroski ≥ 4, or Altman Z > 1.8 | **Stops you being assigned a falling knife. Most important add.** | FMP |
| Net debt / EBITDA | GATE | < ~4x (sector-adjust) | Leverage / bankruptcy risk | FMP |
| Interest coverage | GATE | > ~3x | Can it service debt | FMP |
| Dividend yield | INFO/SCORE | Flag payer; modest score bonus | Income + cushion if assigned | FMP / IBKR |
| Payout ratio | GATE | < ~80% (REITs/utilities differ) | Dividend sustainability | FMP |
| **Ex-dividend date** | **FLAG** | Note upcoming ex-div | Early-assignment risk on short calls; inflates put premium | FMP / IBKR |
| **Earnings date** | **GATE** | No earnings within 7 days | Avoid binary vol crush / gap risk | IBKR / FMP |
| Other binary catalysts | GATE | Exclude pending FDA/M&A names | Tail risk | manual / news |

---

## 2. Technical — bias toward healthy stocks slightly out of favor

The wheel sweet spot is a **quality name in a mild pullback within an uptrend** — not a breakdown.

| Metric | Type | Threshold / Logic | Why | Source |
|---|---|---|---|---|
| **200-day MA (regime filter)** | **GATE** | Price > 200-MA | Only sell puts on stocks in a healthy long-term regime | IBKR hist / pandas-ta |
| 50-day MA | SCORE | Price near/above 50-MA = higher score | Dynamic support | pandas-ta |
| 9 / 21 EMA | SCORE | Short-term bounce starting (9 crossing back above 21) = bonus | Entry timing for 30–45 DTE; noisy, so low weight | pandas-ta |
| RSI(14) | SCORE | **Sweet spot 30–50.** Penalize > 70 (overbought) AND < ~25 (falling knife) | Enough fear to fatten premium, not a collapse | pandas-ta |
| Bollinger Bands (20, 2σ) | SCORE | Price near/below lower band = bonus, **only if 200-MA gate passed & bands not expanding on a breakdown** | Mean-reversion premium without catching a crash | pandas-ta |
| Swing-low support proximity | SCORE | Short strike sits below recent swing low (rolling min, 20/50d) | Strike under real support = lower assignment odds | derive |
| Pivot points (classic) | SCORE | Distance of strike below S1/S2 pivot | Deterministic S/R proxy | derive |
| ATR(14) | INPUT | Used for strike distance & sizing, not scored directly | Volatility-adjusted positioning | pandas-ta |
| Beta | INFO | Context for portfolio risk | Concentration awareness | FMP / IBKR |

> **Note on support/resistance:** the discretionary version is an art and not worth automating. Use swing lows + pivots + the 200-MA as calculable proxies; let RSI/Bollinger/MAs carry the rest.

---

## 3. Option technicals — where the actual edge lives

| Metric | Type | Threshold / Logic | Why | Source |
|---|---|---|---|---|
| **IV Rank (or IV Percentile)** | **GATE + SCORE** | GATE: IVR > 30. SCORE: higher = better. Prefer **IV Percentile** (robust to single spikes). | Are you being paid above this stock's normal vol? | IBKR `OPTION_IMPLIED_VOLATILITY` hist (store daily) — see note in §5 |
| **IV / HV ratio** | **GATE + SCORE** | > ~1.2. Higher = more overpaid vs realized. | **The core edge:** market pricing more movement than the stock delivers. IV high in $ terms = fat premium; IV high *relative to HV* = fat *beyond what risk justifies*. | IBKR `OPTION_IMPLIED_VOLATILITY` + `HISTORICAL_VOLATILITY` |
| Annualized return on collateral | SCORE | `(premium / strike) / DTE × 365`. Rank descending. | Apples-to-apples yield across DTEs/strikes | IBKR chain |
| Delta | GATE + INPUT | ~0.15–0.25 (target ~0.20). P(assignment) ≈ delta; POP ≈ 1−delta | Probability framing | IBKR greeks |
| Expected value | SCORE | `(1−|delta|)×premium − |delta|×(assignment loss est)` | Combines yield + assignment odds | derive |
| **Bid-ask spread %** | **GATE** | < ~5–10% of mid at the target strike | Wide spreads erase premium on entry + 50% close. Non-negotiable. | IBKR chain |
| **Open interest / volume** | **GATE** | OI above a floor (e.g. > 100–500); some daily volume | Liquidity to enter/exit | IBKR chain |
| DTE | GATE | 30–45 days | Theta sweet spot | IBKR chain |
| Theta / day | SCORE | Higher decay per day = bonus | Income velocity | IBKR greeks |
| Put skew | SCORE | Richer downside puts = bonus | More premium to harvest | derive from chain |

---

## 4. Scoring model

1. **Apply GATES first** — drop any name failing safety (solvency, leverage, earnings), regime (200-MA), or tradability (spread, OI, DTE, IVR floor, delta band).
2. **Normalize each SCORE metric** to 0–100 (percentile-rank across surviving candidates, or z-score → clip).
3. **Weighted composite** — starting weights (tune over time):

| Bucket | Weight | Rationale |
|---|---|---|
| Option edge (IV Rank, IV/HV, ann. return, EV, theta) | **45%** | This is where the money is made |
| Fundamentals / quality (valuation, ROIC, solvency, growth) | **30%** | Survivorship if assigned |
| Technical (regime, RSI, Bollinger, support) | **25%** | Entry timing |

4. **Rank by composite**, output top N. Re-evaluate weights against realized P&L quarterly.

---

## 5. Data sourcing notes

> **Phase-1 reality:** the actual implementation uses **yfinance + Black-Scholes**, not IBKR market data (IBKR requires a paid Level 1 sub for options data). So below, the IBKR-specific advice maps to: **compute HV from yfinance price history and persist daily ATM IV yourself** for IV Rank; pull fundamentals free from `yf.Ticker().info` (or FMP). IBKR is still used for live position data in `monitor.py`. See `screener_gap_analysis.md`.

- **IBKR covers more than expected.** Live greeks/IV via market data (market open / delayed sub). IV *and* HV history via `reqHistoricalData(whatToShow='OPTION_IMPLIED_VOLATILITY')` and `'HISTORICAL_VOLATILITY'` on the underlying — pull 1–2 yrs.
- **IV Rank is not a direct API field.** TWS computes and *displays* IV Rank in the UI, but the API only gives the raw IV (generic tick 106 + the historical IV series). You reconstruct Rank yourself: `IV Rank = (today IV − 52wk low) / (52wk high − 52wk low)`. Sanity-check your computed value against the TWS display on a couple of tickers.
- **History ingestion lives inside the Python job.** Each run calls `reqHistoricalData(...)`, appends new bars to a stored IV table (CSV/SQLite), then computes Rank/Percentile + IV/HV from that table. First run backfills ~1–2 yrs; later runs just top up the latest bar. No manual step, no external vol service.
- **Store IV daily from day one** so ranks are fast and consistent.
- **Fundamentals → FMP.** IBKR fundamentals are thin; use Financial Modeling Prep for valuation, growth, ROIC, solvency, dividend/ex-div, earnings dates.
- **Liquidity/spread data is in the live chain** — capture it at screen time, not from stale snapshots.

---

## 6. Suggested module additions to your pipeline

- Add a **solvency/quality gate** inside the fundamentals module (Piotroski/Altman + leverage).
- Add an **IV history store** (daily job) feeding IV Rank & IV/HV.
- Add a **liquidity gate** (spread % + OI) early in the options module to cut compute on untradable names.
- Make the final step a **weighted composite score**, not sequential hard filters, so you always surface a ranked list.
- Keep the **position-monitor** leg (50% profit / stop) as-is — it's good.

---

## 7. Worked example (illustrative — numbers are made up)

Walking one hypothetical ticker **ABC** through the full pipeline. This is a reference for *how the machinery runs*, not a real recommendation.

### Step A — Raw inputs (from IBKR + FMP)
- Price: $98 · 200-MA: $90 · 50-MA: $96 · RSI(14): 42
- Bollinger: price sitting just above the lower band
- FCF: positive · Piotroski: 6 · Net debt/EBITDA: 1.8x · Interest coverage: 9x
- Payout ratio: 35% · Next earnings: 35 days out
- Fwd P/E: slightly below its 5-yr median · ROIC − WACC: +6pts
- Target put: **strike $95, 38 DTE, premium $1.80, delta 0.20**
- IV Rank: 45 · HV(30): 0.24 · IV: 0.32 → **IV/HV = 1.33**
- Bid/ask: $1.76 / $1.84 → mid $1.80, **spread = $0.08 = 4.4% of mid**
- Open interest: 1,200

### Step B — GATE check (pass/fail, no scoring yet)
| Gate | Value | Threshold | Result |
|---|---|---|---|
| FCF > 0 | yes | > 0 | ✅ |
| Solvency (Piotroski) | 6 | ≥ 4 | ✅ |
| Net debt/EBITDA | 1.8x | < 4x | ✅ |
| Interest coverage | 9x | > 3x | ✅ |
| Payout ratio | 35% | < 80% | ✅ |
| Earnings ≥ 7 days out | 35d | ≥ 7d | ✅ |
| Price > 200-MA | 98 > 90 | yes | ✅ |
| IV Rank | 45 | > 30 | ✅ |
| IV/HV | 1.33 | > 1.2 | ✅ |
| Delta in band | 0.20 | 0.15–0.25 | ✅ |
| Spread % | 4.4% | < 10% | ✅ |
| Open interest | 1,200 | > 100 | ✅ |
| DTE | 38 | 30–45 | ✅ |

**All gates pass → ABC survives to scoring.** (Had spread been, say, 12%, ABC is dropped here regardless of everything else.)

### Step C — Annualized return on collateral
```
(premium / strike) / DTE × 365
= (1.80 / 95) / 38 × 365
= 0.01895 / 38 × 365
≈ 18.2% annualized on collateral
```

### Step D — Normalize each SCORE metric to 0–100 (percentile-rank vs the day's surviving universe — illustrative)
**Option edge bucket**
| Metric | Norm score |
|---|---|
| IV Rank (45) | 60 |
| IV/HV (1.33) | 70 |
| Ann. return (18.2%) | 65 |
| Expected value | 62 |
| Theta/day | 55 |
| **Bucket avg** | **62.4** |

**Fundamentals bucket**
| Metric | Norm score |
|---|---|
| Fwd P/E (z) | 58 |
| PEG | 60 |
| Rev growth | 55 |
| ROIC − WACC | 72 |
| Solvency/quality | 80 |
| **Bucket avg** | **65.0** |

**Technical bucket**
| Metric | Norm score |
|---|---|
| 50-MA proximity | 60 |
| RSI (42, sweet spot) | 75 |
| Bollinger (near lower) | 68 |
| Support proximity | 64 |
| **Bucket avg** | **66.8** |

### Step E — Weighted composite
```
Composite = 0.45 × 62.4  +  0.30 × 65.0  +  0.25 × 66.8
          = 28.08        +  19.50        +  16.70
          ≈ 64.3 / 100
```

**ABC final score ≈ 64.** It's then ranked against the other survivors; the top N go into the daily report. Note how the strong fundamentals/technicals couldn't have rescued it if a gate had failed in Step B — gates are absolute, the score only orders what's already cleared them.
