# IBKR Options Screener — Project Log

---

## Entry 001 — 2026-06-07

### Project Purpose
Build a personal daily options screening and recommendation system that combines:
- **Greeks** (delta, theta, IV Rank) for options selection
- **Technical analysis** (support/resistance levels, moving averages) for entry timing
- **Fundamentals** (market cap, earnings dates) for stock filtering
- **Position monitoring** (flag open positions hitting 50% profit or stop criteria)

Goal: receive daily pre-market recommendations on what to open and what to close, without manually scanning the market.

---

### Scope
- **Market:** US options market only (JP market excluded for now — thinner liquidity, wider spreads)
- **Broker:** Interactive Brokers (IBKR PRO account)
- **Phase:** Phase 1 — local desktop build and test
- **Phase 2 (later):** Migrate to cloud VM for always-on headless execution

---

### Key Decisions

| Decision | Choice | Reasoning |
|---|---|---|
| Data source | IBKR TWS API via `ib_insync` | Already has IBKR PRO account; Greeks + chain data included; no extra data cost |
| External data APIs considered | Tradier, ORATS, Polygon, Intrinio, ThetaData, FlashAlpha | Evaluated but deferred — IBKR covers the need for Phase 1 |
| Python library | `ib_insync` | Cleaner async wrapper vs raw `ibapi`; well-documented; community standard |
| Technicals library | `pandas-ta` | Lightweight, pandas-native, covers MA + S/R indicators |
| Deployment (Phase 1) | Local Windows desktop | Desktop already available; migrate to cloud VM in Phase 2 |
| Deployment (Phase 2) | Cloud VM (AWS/Hetzner) + cron job | Always-on; IB Gateway runs headlessly; results pushed via Telegram or email |
| Alert delivery | TBD (Telegram bot or email) | To be decided when pipeline is working |
| JP market | Excluded for now | Much lower options volume vs US → wider spreads → worse execution |

---

### Environment

| Item | Detail |
|---|---|
| OS | Windows (desktop) |
| Username path | C:\Users\Yusuke |
| Python version | 3.13.13 (via `py -3.13`) |
| Python 3.14.5 | Also installed but incompatible with ib_insync — do not use |
| Project folder | C:\ibkr_screener |
| Virtual env | C:\ibkr_screener\venv (created with py -3.13) |
| IB Gateway path | C:\Jts\ibgateway\1045 |
| IB Gateway port (paper) | 4002 |
| IB Gateway port (live) | 4001 |

---

### Dependencies Installed
```
ib_insync
pandas
numpy
pandas-ta
requests
```
Install command:
```bash
cd C:\ibkr_screener
venv\Scripts\activate
pip install ib_insync pandas numpy pandas-ta requests
```

---

### Progress

- [x] Evaluated options data API landscape (Tradier, ORATS, Polygon, Intrinio, ThetaData, FlashAlpha)
- [x] Decided to use IBKR as primary data source (account already exists)
- [x] Switched IBKR account from LITE to PRO (required for API access)
- [x] Installed IB Gateway at C:\Jts\ibgateway\1045
- [x] Installed Python 3.13.13
- [x] Created virtual environment (venv) with Python 3.13
- [x] Installed all dependencies successfully
- [ ] Confirm IB Gateway login (may need time to propagate after LITE→PRO switch)
- [ ] Run test_connection.py and confirm `Connected: True`
- [ ] Build fundamentals filter module
- [ ] Build options chain + Greeks filter module
- [ ] Build technical analysis (S/R + MA) filter module
- [ ] Build position monitoring module (50% profit / stop flag)
- [ ] Build daily report output (CSV or notification)
- [ ] Schedule via Windows Task Scheduler
- [ ] Phase 2: Migrate to cloud VM

---

### Planned Screening Pipeline
```
Daily Pre-Market Run
        │
        ▼
1. Pull watchlist (S&P 500 or custom list)
        │
        ▼
2. Fundamentals filter
   - Market cap > $10B
   - No earnings within 7 days
        │
        ▼
3. Options filter
   - IV Rank threshold
   - DTE: 30–45 days
   - Delta: ~0.20 (short puts / wheel strategy)
        │
        ▼
4. Technical filter
   - Price near support level
   - Above 200-day MA
        │
        ▼
5. Score & rank candidates
        │
        ▼
6. Output daily report (CSV / email / Telegram)
        │
        ▼
7. Check open positions → flag 50% profit or stop criteria
```

---

### Open Questions / Blockers
- IB Gateway login issue — likely needs time after LITE→PRO account switch
- Alert delivery method not yet decided (Telegram vs email)
- Watchlist source not yet decided (hardcoded S&P 500 tickers vs dynamic pull)
- Fundamentals data source: IBKR fundamentals vs supplemental API (e.g. Financial Modeling Prep free tier)

---

### Resources
- `ib_insync` docs: https://ib-insync.readthedocs.io
- IB Gateway download: https://ibkr.com/en/trading/ibgateway.html
- pandas-ta docs: https://github.com/twopirllc/pandas-ta
- Financial Modeling Prep (fundamentals supplement): https://financialmodelingprep.com
- FlashAlpha (GEX analytics, MCP-compatible): https://flashalpha.com
- ORATS (smoothed Greeks + IV, backtesting): https://orats.com

---

## Entry 002 — 2026-06-08

### Session Summary
Completed IB Gateway connection, built and validated `screener.py` and `monitor.py`. Both scripts are working end-to-end.

---

### Key Decisions (updated)

| Decision | Choice | Reasoning |
|---|---|---|
| Options data source | `yfinance` (not IBKR market data) | IBKR requires paid Level 1 subscription even for delayed options data; yfinance is free and sufficient for pre-market screening |
| Greeks computation | Black-Scholes (scipy) from `lastPrice` | yfinance IV values are stale/wrong when markets are closed; solving IV from last traded price via BS gives accurate Greeks at any time |
| IB Gateway port | 4001 (live) | Confirmed live account; paper is 4002 |
| IBKR avgCost for options | Divide by 100 | IBKR reports avgCost per-contract (×100 multiplier); yfinance returns per-share — must normalise before P&L calc |
| Profit target | 70% (raised from 50%) | More time premium to let decay with 15–60 DTE window |
| Hard close rule | 21 DTE | Avoid gamma acceleration near expiry; captures ~70–75% of total theta by that point |
| DTE window | 15–60 days (was 30–45) | Wider window gives more candidates; min 15 avoids short-dated gamma risk on entry |
| Earnings filter | Skip expiries that straddle earnings | yfinance `calendar` used to fetch next earnings date; any expiry where earnings ≤ expiry date is skipped |

---

### Files Created

| File | Purpose |
|---|---|
| `test_connection.py` | Verifies IB Gateway connection (`Connected: True`) |
| `screener.py` | Daily screener — Mag7 puts, 15–60 DTE, delta 0.15–0.30, earnings filter |
| `monitor.py` | Position monitor — pulls live IBKR positions, flags 70% profit or ≤21 DTE |
| `debug_screener.py` | Temporary debug script — can delete |

---

### Dependencies Installed (updated)
```
ib_insync, pandas, numpy, pandas-ta, requests   # from Entry 001
yfinance                                         # added — options data + pricing
scipy                                            # added — Black-Scholes IV solver
```

---

### Architecture
Two separate scripts, intentionally decoupled:
- **`screener.py`** — no IBKR connection needed; pure yfinance + BS. Finds new trade candidates.
- **`monitor.py`** — requires IB Gateway running; pulls positions via `ib_insync`, prices via yfinance.

clientId assignments: 1 = test_connection, 2 = screener (reserved), 3 = monitor

---

### Screener Config (current)
```python
TICKERS           = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA']  # Mag7
MIN_DTE           = 15
MAX_DTE           = 60
DELTA_MIN         = 0.15
DELTA_MAX         = 0.30
RISK_FREE         = 0.045
PROFIT_TARGET_PCT = 0.70   # documented in screener; enforced in monitor
HARD_CLOSE_DTE    = 21
```

---

### Monitor Output (first live run)
13 positions found. Correct close flags:
- `QQQ C 760` — 75% profit → CLOSE ✓
- `HOOD P 67`, `MSFT P 395 Jun`, `QQQ P 685` — ≤21 DTE → CLOSE ✓
- `QQQ P 685` also showing loss (-71%) — flagged by DTE rule, correct behaviour

Known issue: CMCSA has two short put legs at different strikes ($26 and $24) — these are a combo/spread position. Monitor currently treats them as independent legs. Need to decide how to handle combo positions (group by ticker+expiry, or flag separately with a "combo" tag).

---

### Progress (updated)
- [x] IB Gateway confirmed connected (port 4001, server version 176)
- [x] `test_connection.py` — Connected: True
- [x] `screener.py` — working, earnings filter active, 61+ candidates on first run
- [x] `monitor.py` — working, P&L and DTE flags correct after avgCost/100 fix
- [x] `type` (P/C) column added to both outputs — ready for call selling later
- [ ] Schedule screener + monitor via Windows Task Scheduler (next)
- [ ] Handle combo/spread positions in monitor (CMCSA case)
- [ ] Add calls to screener
- [ ] Alert delivery (Telegram or email)
- [ ] Technical analysis filter (S/R, 200MA)
- [ ] Expand watchlist beyond Mag7
- [ ] Phase 2: Cloud VM migration

---

### Open Questions
- **Alert delivery**: Telegram bot vs email — still TBD
- **VIX position**: yfinance returns NaN for VIX options price — VIX options trade on CBOE with non-standard settlement; may need separate handling
- **MSFT P 395 Jul-2**: showing -140% loss — position moved significantly against; 19 DTE → flagged CLOSE ✓
- **Screener refinement**: next focus area (see Entry 003)

---

## Entry 003 — 2026-06-08 (continued)

### Session Summary
Fixed combo position handling in monitor.py, confirmed output against live positions. Moving to screener refinement.

---

### monitor.py Changes
- **Now pulls ALL option positions** (not just short legs) — long hedge legs were previously silently dropped
- **Combo detection**: positions sharing same (ticker, expiry) tagged `COMBO`. If any leg triggers close, all legs in the group are flagged — ensures spreads/strangles close as a unit
- **Long leg P&L**: computed correctly as `(current - entry) / entry` (inverted vs short legs)
- **Profit-target rule** only applied to short legs; DTE rule applies to all legs
- **Sort order**: ticker → DTE → type → strike (was: action first, then ticker)

### Live Monitor Output (confirmed correct)
```
CMCSA  COMBO  C 2026-08-21  75  30.0   +10  (long call — hedge leg)
CMCSA  COMBO  P 2026-08-21  75  24.0    -4
CMCSA  COMBO  P 2026-08-21  75  26.0    -5
MSFT         P 2026-07-02  25  395.0    -2   HOLD  (-140% loss, 25 DTE — just outside hard-close window)
... (10 HOLD, 4 CLOSE)
HOOD         P 2026-06-26  19   67.0    -4   CLOSE ⚡ 19 DTE
MSFT         P 2026-06-26  19  395.0    -3   CLOSE ⚡ 19 DTE
QQQ          P 2026-06-26  19  685.0    -1   CLOSE ⚡ 19 DTE (-71% loss)
QQQ          C 2026-06-30  23  760.0    -1   CLOSE ⚡ 75% profit
```
Total: 14 positions (1 long leg), 4 CLOSE, 10 HOLD

### CMCSA Combo Structure
- Short put spread: -5 × $26P + -4 × $24P (both short puts at different strikes)
- Long calls: +10 × $30C (hedge / risk reversal component)
- All same expiry (2026-08-21) → correctly tagged COMBO

---

### Progress (updated)
- [x] monitor.py — combo detection and grouping working
- [x] monitor.py — long/short legs both shown with correct P&L direction
- [x] monitor.py — sort by ticker/DTE
- [ ] Screener refinement (current focus)
- [ ] Schedule screener + monitor (deferred — screener needs more work first)
- [ ] Handle VIX options (non-standard settlement, NaN price)
- [ ] Alert delivery (Telegram or email)
- [ ] Add calls screening to screener
- [ ] Technical analysis filter (S/R, 200MA)
- [ ] Expand watchlist beyond Mag7
- [ ] Phase 2: Cloud VM migration

---

## Entry 004 — 2026-06-08 (continued)

### Session Summary
Finalized the **screening criteria spec** (consult w/ Opus) and ran a **gap analysis** of `screener.py` against it. Introduced a `docs/` folder for project documentation, separate from `logs/` (run output). Moved `PROJECT_LOG.md` into `docs/`.

---

### Docs Structure (new)

| File | Purpose |
|---|---|
| `docs/screening_spec.md` | Canonical screening spec — every metric tagged GATE / SCORE / GATE+SCORE, thresholds, weights (45% option edge / 30% fundamentals / 25% technical), worked example in §7 |
| `docs/screener_gap_analysis.md` | What `screener.py` implements vs the spec, gaps ordered by impact, suggested build order |
| `docs/PROJECT_LOG.md` | This log (moved from project root) |
| `logs/` | Run output only — NOT documentation |

---

### Screening Spec — key concepts locked in
- **Frame:** wheel/short-put = "would I want to own this if assigned, and am I paid richly to wait?" — not "will it go up."
- **Gates vs Score:** hard gates prune the universe; a weighted composite ranks only the survivors. A name can never score past a gate.
- **Core edge = IV/HV ratio** (> ~1.2): premium fat *beyond what realized risk justifies*, distinct from high IV alone.
- **Solvency gate** (Piotroski/Altman + leverage) = the "don't get assigned a falling knife" guard — the most important fundamental add.
- **Liquidity gate** (spread % + OI) = non-negotiable; wide spreads erase premium on entry + 50% close.
- **IV Rank** is not a direct API field — reconstruct from a self-persisted daily IV series.

---

### Gap Analysis — headline findings
`screener.py` currently implements only the **option-mechanics slice**: DTE, delta band, strike range, BS-IV, theta, earnings filter. Missing, by impact:
1. 🔴 **Liquidity gate** — captures bid/ask/OI but filters on none (cheapest high-value fix)
2. 🔴 **Scoring/ranking layer** — output is sorted, not scored
3. 🔴 **Annualized return on collateral** — not computed
4. 🟠 **IV Rank & IV/HV** — the stated edge, absent (HV computable from yfinance now; IV Rank needs daily IV persistence going forward)
5. 🟠 **Fundamentals bucket** — entirely missing, incl. solvency gate (mostly free via `yf.Ticker().info`)
6. 🟠 **Technical bucket** — entirely missing; `pandas-ta` installed but unused (200-MA regime gate = highest value)

Suggested build order: liquidity gate → ann. return + composite scoring → 200-MA gate + HV/IV-HV → start persisting daily IV → fundamentals solvency gate → expand watchlist.

### Data-source note
Spec was drafted assuming IBKR, but the implementation uses **yfinance + Black-Scholes** (IBKR needs paid L1 sub for options data). Spec §5 and the gap analysis both reconcile this — fundamentals/HV/IV all sourceable from yfinance; IBKR retained for live positions in `monitor.py`.

---

### Progress (updated)
- [x] Screening criteria spec finalized → `docs/screening_spec.md`
- [x] Gap analysis of `screener.py` → `docs/screener_gap_analysis.md`
- [x] `docs/` folder created; `PROJECT_LOG.md` moved into it
- [ ] Implement liquidity gate (spread % + OI) in screener
- [ ] Implement annualized-return + composite scoring
- [ ] Add 200-MA regime gate + HV / IV-HV
- [ ] Begin persisting daily ATM IV (for IV Rank over time)
- [ ] Add fundamentals solvency gate + valuation score
- [ ] Schedule screener + monitor (Windows Task Scheduler)
- [ ] Expand watchlist beyond Mag7
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 005 — 2026-06-08 (continued)

### Session Summary
**Rewrote `screener.py` to fully implement the spec** — all gap-analysis items closed. Added gates, the IV-edge metrics, fundamentals + technical buckets, and a weighted composite scoring/ranking layer. Logic unit-tested (28/28 pass).

---

### screener.py — what changed (now ~560 lines, was ~220)
**New GATES (hard filters):**
- Liquidity: bid-ask spread % < 10% AND open interest ≥ 100 (was captured but never filtered)
- 200-MA regime: skip ticker if price < 200-day MA
- Solvency: conservative distress check (high D/E + weak current ratio / negative FCF). Missing data never rejects a name.
- (existing kept: DTE 15–60, |delta| 0.15–0.30, strike range, earnings-straddle skip)

**New SCORE metrics → weighted composite (option 45% / fundamental 30% / technical 25%):**
- Option edge: IV Rank, IV/HV, annualized return on collateral `(prem/strike)/dte×365`, theta decay
- Fundamentals (free via `yf.Ticker().info`): forward P/E, PEG, ROE, revenue growth
- Technical (computed from price history, no pandas-ta dep): RSI(14) sweet-spot score, Bollinger %B, swing-low support cushion
- Buckets renormalize over available metrics, so missing data degrades gracefully (e.g. IV Rank absent early → other metrics still score)

**New infra:**
- HV(30) computed from yfinance price history → enables IV/HV
- **IV history store** at `data/iv_history.csv` — each run persists per-ticker ATM IV; IV Rank builds up over ~weeks/months. Recorded even on no-candidate runs.
- Output now **ranked by composite score**, new columns (mid, spread_pct, open_int, hv_pct, iv_hv, iv_rank, bucket scores)

**Design notes:**
- Technicals hand-rolled in pandas (RSI/MA/Bollinger) instead of pandas-ta — avoids that lib's numpy-version fragility
- Fundamentals/technicals fetched once per ticker (not per option)
- IV Rank gracefully None until ≥20 days of stored IV history exist

---

### Testing
- 28/28 unit tests pass (`test_screener.py`, run in sandbox): Black-Scholes round-trip (IV recovers to 0.30), HV, technicals, annualized return (≈18.2% matches spec §7), RSI/Bollinger scorers, solvency gate (healthy pass / distressed fail / missing-data pass), IV Rank, and end-to-end composite scoring incl. the no-IV-history path.
- Syntax/AST valid (563 lines).
- **Live yfinance run NOT possible in sandbox** (network blocks Yahoo, 403) — must be run on the Windows desktop. Old screener already proven to fetch there, so live run expected to work; **first real run is the validation step still outstanding.**

---

### Known follow-ups / tuning
- Solvency thresholds are deliberately loose (won't bite on Mag7); revisit when watchlist expands to riskier names.
- Fundamentals depend on `yf.Ticker().info` fields being populated (occasionally sparse/None) — composite renormalizes, but watch `forwardPE`/`pegRatio` coverage.
- Scoring weights (45/30/25) are starting values — re-tune against realized P&L quarterly per spec §4.
- IV Rank needs history accrual — schedule the daily run soon so the series starts building.

### Note: sandbox mount glitch (no action needed)
During this session the agent's Linux mirror of `screener.py` went stale (showed a truncated old copy). The actual file on disk is correct and complete (563 lines) — verified via host read. Testing was routed through a verified copy. Flagging only so a future session isn't confused by a stale mirror.

---

### Progress (updated)
- [x] Implement liquidity gate (spread % + OI)
- [x] Implement annualized-return + composite scoring
- [x] Add 200-MA regime gate + HV / IV-HV
- [x] Daily ATM IV persistence wired (`data/iv_history.csv`) — IV Rank accrues over time
- [x] Add fundamentals solvency gate + valuation/ROE/growth score
- [x] Add technical bucket (RSI / Bollinger / support)
- [x] Unit tests written and passing (28/28)
- [ ] **First live run on Windows desktop** (validation — sandbox can't reach yfinance)
- [ ] Schedule screener + monitor (Windows Task Scheduler)
- [ ] Expand watchlist beyond Mag7
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 006 — 2026-06-08 (continued)

### Session Summary
Added an **IBKR options-data subscription** and made **IBKR the canonical IV-Rank source** via a separate updater (Option A). Built `update_iv_history.py`, reworked the screener's IV logic to be source-aware, tested an IBKR fetch end-to-end (works), and unit-tested the new logic (all pass).

---

### IBKR IV test result (`test_ibkr_iv.py`, run on desktop)
- Connected port 4001 (server v176), qualified AAPL.
- **Historical `OPTION_IMPLIED_VOLATILITY`: 250 daily bars** (2025-06-06 → 2026-06-05). Demo IV Rank = 51/100.
- **Historical `HISTORICAL_VOLATILITY`: 251 bars.** Demo IV/HV = 1.07.
- Live option greeks failed with **Error 10089** (real-time L1 feed needs a separate subscription; delayed available). **Not needed** — screener uses yfinance for live per-strike data; IBKR is only for the historical IV/HV series. Markets were closed (Sunday) anyway.
- **Conclusion:** IBKR delivers the full-year IV/HV series → IV Rank works *immediately*, no multi-month accrual.

### Gotcha logged: `py -3.13` bypasses the venv
`py -3.13 script.py` runs *system* Python (no `ib_insync`) even after `activate`. **Always use `venv\Scripts\python.exe script.py`** for anything importing ib_insync. (test_ibkr_iv.py docstring updated.)

---

### Decision: Option A — separate IV updater (chosen over integrate / integrate+fallback)
Rationale: keeps `screener.py` Gateway-independent (runnable anytime), `monitor.py` already owns the Gateway dependency, and IBKR's one-call full-year fetch means a periodic refresh (even weekly) is enough. The "fallback" is implicit: screener just reads whatever's in the CSV.

### Files
| File | Change |
|---|---|
| `update_iv_history.py` | **NEW.** Connects to IBKR (clientId=4), pulls 1-yr daily IV + HV per watchlist ticker, refreshes `data/iv_history.csv` with `source='ibkr'`. Prints an IV-Rank preview. Run with Gateway up: `venv\Scripts\python.exe update_iv_history.py` |
| `screener.py` | IV logic now **source-aware**. New CSV schema `date,ticker,iv,hv,source`. `ticker_iv_rank()` computes a **per-ticker** rank from a **single consistent source** (IBKR preferred, yf fallback — never mixed, ≥20 pts required). `latest_ibkr_hv()` feeds IV/HV. Screener still imports no IBKR; yfinance snapshots still written as `source='yf'` backup. Output adds `iv_src` column. |
| `test_ibkr_iv.py` | NEW (prior step) — IBKR connectivity/data probe. |

### Key design point (consistency)
IV Rank is **per-underlying** and computed *within one source only*. Mixing IBKR's constant-maturity 30-d ATM IV with yfinance/BS per-strike IV in one range would corrupt the rank — so sources are tagged and never blended. IV/HV (cross-sectional) may use IBKR HV with yfinance option IV; that's fine.

---

### Testing
- 30+ unit tests pass (`test_iv_v2.py`, sandbox): all prior logic plus source-preference (ibkr>yf), <20-pt skip, schema migration (old `atm_iv` → `iv`), record/load roundtrip, and end-to-end scoring with no IV history.
- Sandbox can't reach IBKR (no route to local Gateway) or Yahoo (403) — so live `update_iv_history.py` + `screener.py` runs happen on the desktop.

### Sandbox quirks logged (no action)
- The agent's Linux mirror intermittently served stale copies of in-place-edited files and reused stale `__pycache__` (gave new source an old mtime). Worked around by testing from a clean /tmp copy. **On-disk files are correct** (verified via host).

---

### Suggested run order on desktop
1. `venv\Scripts\python.exe update_iv_history.py`  (Gateway up — backfills IBKR IV/HV, prints IV-Rank preview; sanity-check a couple vs TWS)
2. `venv\Scripts\python.exe screener.py`           (no Gateway needed — should now show real `iv_rank` with `iv_src=ibkr`)

### Progress (updated)
- [x] IBKR options-data subscription added + verified (historical IV/HV: 250/251 bars)
- [x] Decision: Option A (separate IBKR IV updater)
- [x] `update_iv_history.py` built (IBKR → data/iv_history.csv, source-tagged)
- [x] screener.py IV logic made source-aware (per-ticker rank, IBKR preferred)
- [x] Unit tests for new logic passing
- [x] `update_iv_history.py` desktop run OK — IBKR IV Rank preview reasonable (AAPL 51, MSFT 58, NVDA 44, AMZN 38, GOOGL 37, META 49, TSLA 36; all src=ibkr)
- [x] Bugfix: NaN-safe numeric parse in screener (`_num()`) — yfinance returns NaN volume/OI; `int(NaN)` was crashing screen_ticker. NaN now → 0 (correctly fails liquidity gate). Verified.
- [x] Desktop run of `screener.py` works — full ranked table (112 candidates across Mag7)
- [ ] Sanity-check computed IV Rank vs TWS for 1–2 tickers
- [ ] Schedule updater (weekly ok) + screener + monitor (Windows Task Scheduler)
- [ ] Expand watchlist beyond Mag7
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 007 — 2026-06-08 (continued)

### Session Summary
First full live run surfaced two issues + a design question; all three resolved. Tuned the gates and reworked how fundamentals factor in.

### 1. Regime: 200-MA hard gate → confirmed-downtrend gate
The hard "price > 200-MA" gate auto-skipped MSFT/META/TSLA even though they were holding support and going sideways — a fine put-selling setup (you're not betting on upside, just that price stays above the strike). Replaced with `REGIME_MODE` (`'gate' | 'downtrend' | 'score'`, default **`'downtrend'`**): now skips a ticker ONLY if it's a confirmed falling knife — **below both 50 & 200-MA AND 200-MA sloping down (>2%/~20 sessions) AND within 3% of the 50-day low.** Sideways-below-200MA-with-support passes. Tunable via `DOWNTREND_SLOPE`, `NEAR_LOW_PCT`. Added `compute_technicals` outputs: `ma200_slope`, `swing_low_50`.

### 2. Liquidity gate wiped everything on weekends (data artifact)
Diag showed 100% of strikes rejected on `open_interest` — yfinance returns 0/NaN OI when markets are closed. Added `ALLOW_MISSING_OI=True`: a missing/zero OI no longer rejects (counted as `oi_missing_allowed` in diag); a *real* positive-but-small OI still fails on weekdays. So weekend testing works and live filtering is unaffected. Also added a per-ticker rejection-reason **diag line** + raw-sample print for future debugging.

### 3. Fundamentals: weighted score → quality GATE (user decision)
Observation: NVDA (fund 91.5) vs META (67.9) barely moved the composite, because the 30% fundamental edge was *offset* by META's higher option-edge score — i.e. premium could buy past quality. Also the fundamental percentile was computed per-row, so names with more option rows skewed it. Decision: make fundamentals a **pass/fail quality gate** (`fundamental_ok`: FCF>0, rev growth ≥0, ROE ≥8%, fwd P/E ≤60; missing data never rejects), on top of solvency. Composite is now **option 65% / technical 35%** (fundamentals no longer scored). For Mag7 all pass; the gate earns its keep on a wider watchlist. Raw `fwd_pe/roe/rev_growth` kept in the CSV for reference.

### Testing
- Logic unit-tested from clean /tmp copies (sandbox can't reach yfinance/IBKR): regime_block all 3 modes, compute_technicals slope/swing_low_50, `_num` NaN-safety, `fundamental_ok` (each threshold + missing-data pass), and composite = 0.65·option + 0.35·technical. All pass.
- First live `screener.py` run produced 112 ranked candidates (NVDA/META/AAPL/AMZN/GOOGL/MSFT/TSLA all evaluated; none auto-skipped by regime).

### New / changed config knobs (top of screener.py)
`REGIME_MODE`, `DOWNTREND_SLOPE`, `NEAR_LOW_PCT`, `ALLOW_MISSING_OI`, `REQUIRE_FUNDAMENTALS`, `REQUIRE_FCF_POSITIVE`, `MIN_ROE`, `MIN_REV_GROWTH`, `MAX_FORWARD_PE`, `W_OPTION=0.65`, `W_TECHNICAL=0.35`.

### Note
The script truncated once when copied via the sandbox file bridge (an in-place `cp` didn't flush fully → `main()` cut off → empty run). Re-written in full via the host file tool and verified complete (650 lines). When updating screener.py, prefer a full host write over bash cp.

---

## Entry 008 — 2026-06-08 (continued)

### Session Summary
Compact one-line-per-ticker output, then three feature additions: cross-asset ETFs, a portfolio-relative diversification score, and assignment-drawdown position sizing.

### Display
Per-ticker scan is now a single line (`TICKER  $price | earn … | HV … | div NN(corr) | N cand`), skips/diag folded onto the same line — readable when scanning many names. `iv_rank` rounded to 1 decimal.

### ETFs (cross-asset diversification)
Added a curated ETF basket to the watchlist: SPY/QQQ/IWM, TLT/IEF/HYG, GLD/SLV, VNQ. ETFs are detected via `quoteType=='ETF'` or an `ETF_TICKERS` set and **bypass the fundamentals/solvency/earnings gates** (no financials), while still passing through liquidity/regime/IV/delta + sizing + diversification. Rationale: genuine negative correlation to equities lives in bonds (TLT) and gold (GLD), not in more stocks. Caveats noted: lower IV → smaller premiums; USO-type commodity ETFs avoided (contango).

### Diversification score (decision: score vs current portfolio)
Chosen over post-rank selection because positions are added gradually → a rolling book naturally diversifies. `load_holdings()` reads current underlyings from `monitor_output.csv` (keeps screener Gateway-free); `fetch_returns()` pulls ~6mo daily returns once; `diversification_score()` = avg correlation of candidate to holdings mapped to 0–100 (corr −1→100, 0→50, +1→0, **absolute** not percentile, so when everything is correlated nothing scores high). Composite reweighted to **option 55% / technical 25% / diversification 20%**; when the book is empty the bucket is skipped and weights renormalize. Reality check recorded: equity correlations cluster toward 1 in selloffs and put-selling shares a short-vol factor, so the realistic goal is low correlation, not true negatives.

### Position sizing (assignment + drawdown basis)
`position_size()` → recommended `lots` under a per-trade risk cap. Risk/contract ≈ `strike×100×ASSUMED_DRAWDOWN`; `lots = (ACCOUNT_SIZE×MAX_RISK_PCT) // risk/contract`. Defaults `ACCOUNT_SIZE=100_000`, `MAX_RISK_PCT=0.03`, `ASSUMED_DRAWDOWN=0.20` (all top-of-file). Output adds `lots`, `collat_ct`, `risk_ct`, `income`. **User must set ACCOUNT_SIZE to their real account.**

### Testing
Logic unit-tested from clean /tmp copies: ETF detection, `position_size` (NVDA190→0 lots, $100→1, $57.5→2), `diversification_score` (corr +1→0, −1→100, no-holdings→None), `load_holdings` (dedup/upper), and composite = .55opt+.25tech+.20div with renorm when div missing. All pass. (Sandbox file bridge kept truncating the large file on read — verified composite math in isolation and authored content directly to host.)

### Other suggestions raised for later
Universe liquidity pre-filter + performance (yfinance is slow/rate-limited at 100s of names), notional caps as a secondary sizing guard, backtest/calibration of weights before trusting them, sector tags.

### Progress (updated)
- [x] Compact per-ticker display; iv_rank rounded
- [x] Cross-asset ETF basket + ETF-aware gates
- [x] Diversification score vs current holdings (from monitor_output.csv); weights 55/25/20
- [x] Position sizing (assignment+drawdown, 3% cap); set ACCOUNT_SIZE
- [ ] Liquidity pre-filter + performance pass before expanding to 100s of tickers
- [ ] Schedule updater + screener + monitor (Windows Task Scheduler)
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 009 — 2026-06-08 (continued)

### Session Summary
First ETF-inclusive run: non-QQQ ETFs didn't surface in the global top list. Diagnosed and fixed; added a per-sleeve diversification view. ACCOUNT_SIZE set to $700k.

### Why diversifiers didn't surface (two causes)
1. **Structural:** composite is 55% option-edge; bonds/gold carry far less premium, so they sit at the bottom of that bucket. The 20% diversification bucket has a *compressed range* (corr 0→score 50; a tech book gives most equities +0.3–0.7 = scores 15–35, best diversifiers ~50–65), so it can't lift a low option score. A single edge-ranked list inherently buries low-premium diversifiers — correct behavior, wrong tool for building a diversified book.
2. **Data gap (fixed):** ETFs showed `iv_rank=NaN` because the IBKR IV pull predated adding ETFs. Re-ran `update_iv_history.py` (it imports the ETF-inclusive TICKERS) → now all 16 have IBKR IV Rank. Notable: SPY IV/HV 1.50, QQQ 1.38, IWM 1.29, HYG 1.28 (rich); bonds tiny IV (TLT 0.10, IEF 0.058, HYG 0.051) confirming low premium.

### Fix: per-sleeve view (decision)
Added sleeve tagging — ETFs via `ETF_SLEEVE` map (Equity Index / Bonds / Commodity / REIT / …), equities via yfinance `sector`. New **BEST PER SLEEVE** output prints top `PER_SLEEVE_TOP` (=2) candidates per sleeve, so diversifiers surface on their own merits; build the book by picking across sleeves rather than the tech-skewed global top-N. Weights left at 55/25/20 (chose per-sleeve over bumping W_DIVERSIFY). Logic unit-tested (sleeve mapping + groupby head-per-sleeve).

### Cross-asset put-selling note (user Q)
Recommended ETFs (TLT/IEF/HYG bonds, GLD/SLV gold, VNQ REIT, SPY/QQQ/IWM index) as the genuine source of negative/low correlation — individual stocks can't provide it. Caveat: bond/gold premiums are small; USO-type commodity ETFs avoided (contango).

### Progress
- [x] Re-ran update_iv_history.py — ETFs now have IBKR IV Rank
- [x] Per-sleeve diversification view (BEST PER SLEEVE table)
- [x] ACCOUNT_SIZE = 700_000
- [ ] Weekday run with live quotes (spreads/OI engage)
- [ ] Liquidity pre-filter + performance pass before 100s of tickers
- [ ] Schedule updater + screener + monitor
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 010 — 2026-06-08 (continued)

### Session Summary
Per-sleeve run validated the design (diversifiers surface; GLD best non-equity, bonds thin as expected; diversification *score* near-uniform because nothing is negatively correlated to the book right now — per-sleeve view carries the diversification, not the 20% bucket). Then expanded the watchlist to the S&P 100 + ETFs.

### Watchlist expansion
`TICKERS` is now **S&P 100 (101 names, incl. GOOG+GOOGL; BRK-B for yfinance) + 9 ETFs = 110**. Source: Wikipedia S&P 100 (as of 2025-09) — fetched, not from memory. Structured as `SP100`, `ETFS`, `TICKERS = SP100 + ETFS`. Chose S&P 100 over S&P 500: every name has deep/tight options (put-selling needs liquidity); the 500 adds illiquid noise the gates would reject anyway. Full sector coverage → fills equity sleeves; ETFs add Bonds/Commodity/REIT/Index sleeves.

### Action required / caveats
- **Re-run `update_iv_history.py`** after this change — it imports the now-110-name TICKERS, so the ~94 new equities need their IBKR IV history backfilled (else iv_rank=NaN for them).
- **Performance is now the bottleneck.** ~110 names × (.info + 1y history + option chains/expiry) via yfinance = slow (minutes) and may throttle; per-ticker try/except skips failures so it won't crash. → Next priority: liquidity/market-cap pre-filter + caching/parallelism before scaling further or scheduling.
- VIX in holdings logs `possibly delisted` in fetch_returns (yfinance can't price 'VIX') — harmless, just skipped from the correlation baseline.

### Progress
- [x] Watchlist = S&P 100 + ETFs (110 tickers), validated list (no dupes, no dotted symbols)
- [ ] Re-run update_iv_history.py for the 110-name universe
- [ ] Performance pass: liquidity pre-filter + cache .info + parallelize
- [ ] Schedule updater + screener + monitor
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 011 — 2026-06-08 (continued)

### Session Summary
Two fixes + a monitor feature. (1) IBKR symbology fix in the updater. (2) Sleeve view now shows component scores. (3) Roll suggestions added to monitor.py, reusing the screener's scoring framework.

### IBKR updater symbology fix (`update_iv_history.py`)
BK and BRK-B failed IBKR contract resolution (yfinance uses `BRK-B`; IBKR wants `BRK B`; `BK` needs a primary exchange). Added `IBKR_SYMBOL` map (`BRK-B`→`BRK B`) + `qualify_stock()` that tries SMART then NYSE/NASDAQ/ARCA, an "Unresolved on IBKR" summary, and silenced ib_insync Error-200 log spam. Rows still stored under the yfinance ticker so the screener matches. (Screener side already handled these via yfinance — only the IBKR updater needed it.)

### Sleeve view
BEST PER SLEEVE table now includes `score_option / score_technical / score_diversify` alongside the composite (user request).

### Weights
User set `W_TECHNICAL = 0.4` (heavier technical for a safety-margin tilt). Composite renormalizes over whatever weights are set, so this is fine.

### Roll suggestions (monitor.py) — reuse screener scoring
Decision (user): instead of a fixed roll-strike rule, score roll candidates with the SAME screener framework on the same ticker and show the top 3 per close-flagged position.
- `screen_ticker()` got a `verbose=False` flag so the monitor can call it quietly.
- `build_roll_suggestions(df, iv_hist_df, holdings_returns)`: for each CLOSE-flagged **single-leg short put** (combos & short calls skipped for now), runs `screen_ticker` + `score_candidates` on the ticker, keeps **later-expiry** puts only (roll out), computes `net_credit = new_mid − buyback`, returns top-N (default 3) by composite score. Gated ticker → no roll → "recommend CLOSE".
- `print_roll_suggestions()` renders per-position blocks (new expiry/dte/strike/mid/net_credit/delta/iv_rank/iv_hv/ann_ret + component & composite scores) and saves `roll_suggestions.csv`.
- Diversification baseline for rolls uses the **live** positions (sorted unique tickers from the pulled book), not the CSV.
- Note: roll composite scores rank candidates *within* the ticker (relative), not comparable to a global screener run.

### Testing
8 logic checks + render/CSV smoke test pass (monkeypatched `screen_ticker`, installed ib_insync in sandbox): only CLOSE-flagged single-leg short puts rolled (HOLD/combo excluded), later-expiry filter, net credit math (mid−buyback), top-N sort, gated→None, CSV written. screener.py (796 lines) & monitor.py (273) both parse.

### Progress
- [x] IBKR updater symbology fix (BK, BRK-B) + Unresolved summary
- [x] Sleeve view shows component scores
- [x] Roll suggestions in monitor.py (top-3 scored rolls per close-flagged short put → roll_suggestions.csv)
- [ ] Extend rolls to short calls + combos (deferred)
- [ ] Performance pass: liquidity pre-filter + cache .info + parallelize (now pressing at 110 tickers)
- [ ] Schedule updater + screener + monitor
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 012 — 2026-06-08 (continued)

### Monitor: ATM/ITM positions now trigger rolls
Gap: a short put gone ITM with plenty of DTE was just "HOLD" — no roll suggested. Added moneyness:
- New config `NEAR_ATM_BUFFER = 0.03`. A short put is **"challenged"** when `stock <= strike*(1+buffer)` (ATM or ITM).
- Fetch live underlying prices once per ticker (`get_stock_price` → `S.get_price`); added `stock` and `money` (ITM/ATM/OTM) columns to the monitor table.
- New action **`ROLL?`** for challenged single-leg short puts that aren't already CLOSE-flagged (combos/calls excluded). Summary line now shows Close / Roll? / Hold counts.
- `build_roll_suggestions` filter broadened to `(CLOSE* OR ROLL?)` so challenged positions get the top-3 scored rolls too.
- Note: rolling an ITM put down-and-out is often a **net debit** — shown via `net_credit` (negative) so the user can weigh roll-down vs roll-out-same-strike (credit, stays ITM) vs assignment.

### Testing
Standalone logic checks pass: moneyness (ITM/ATM/OTM; only short puts; long puts & calls excluded) and the broadened roll filter (picks ROLL?+CLOSE puts, excludes HOLD/calls/combos). Earlier build_roll_suggestions tests still hold (net credit, later-expiry, top-N, gated→CLOSE). Host files verified complete via Read (sandbox mirror was serving a stale truncated monitor.py — host disk is correct).

### Progress
- [x] Monitor shows stock/money; ATM/ITM short puts flagged ROLL? and get roll suggestions
- [ ] Extend rolls to short calls + combos (deferred)
- [ ] Performance pass (pressing at 110 tickers)
- [ ] Schedule updater + screener + monitor
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 013 — 2026-06-08 (continued)

### Screener: underlying price + cushion, exposure, real account size
1. **otm_% column** = downside cushion to the strike `(price-strike)/price*100` (positive = OTM). Underlying already shown as `stock_price`.
2. **Exposure from lot sizing:** per-candidate `exposure` = collateral `strike*100*lots` and `exp_%` = exposure/account. New **One-per-sleeve book** line under BEST PER SLEEVE: total exposure of the top pick per sleeve as $ and % of portfolio, with a ⚠ if >100% (3%-drawdown sizing caps risk, not collateral, so a CSP book can sum past cash).
3. **Real account size from IBKR.** `ACCOUNT_SIZE` is now a fallback only. `monitor.py` fetches `NetLiquidation` via `ib.accountSummary()` and calls `S.save_account_size()` → `data/account.json`. Screener `get_account_size()` reads it (Gateway-free); `main()` sets `ACCOUNT_SIZE = get_account_size()` and the banner shows `acct: IBKR | default`. Run monitor once to populate; screener auto-uses it.

Display: screener tables now include otm_% / exposure / exp_%. Run order: monitor.py (saves NLV) → screener.py (uses it).

### Testing
Standalone logic checks pass: account.json save/read/fallback roundtrip, otm_% cushion (7.4 for 205.1/190), exposure (5 lots × $19k = $95k, 13.6% of $700k), one-per-sleeve total exposure sum. Host files verified complete via Read (sandbox mirror kept truncating the large screener.py on read; host disk correct).

### Progress
- [x] Screener: otm_% cushion (exposure moved to monitor — see Entry 014)
- [x] Real account size (IBKR NetLiquidation via monitor → data/account.json → screener)
- [ ] Extend rolls to short calls + combos
- [ ] Performance pass (pressing at 110 tickers)
- [ ] Schedule updater + screener + monitor
- [ ] Alert delivery (Telegram or email)
- [ ] Phase 2: Cloud VM migration

---

## Entry 014 — 2026-06-08 (continued)

### -X% rule → 15%; exposure moved to the monitor (max-loss definition)
- `ASSUMED_DRAWDOWN` 0.20 → **0.15** (user: won't hold a position down 20%). Single source of truth for screener lot sizing AND monitor exposure (monitor uses `S.ASSUMED_DRAWDOWN`). Side effect: screener lots increase slightly.
- **Removed `exposure`/`exp_%` and the one-per-sleeve total from the screener** (lots already conveys sizing there). Kept `otm_%`. Display/sleeve columns cleaned.
- **Monitor `exposure` column** = user's chosen definition: **max loss at the −X% stop** for short puts = `strike × 0.15 × 100 × |qty|` (not collateral). Calls/long legs/combos → blank. New summary line: **total short-put exposure as % of NLV** (NLV from `ib.accountSummary()`), i.e., real risk-budget-in-use under the 15% stop.

### Testing
Exposure formula validated standalone (O ×10 @57.5 → $8,625; MSFT ×2 @395 → $11,850; etc.). Host files verified complete via Read at all edited regions + tails (sandbox mount kept truncating its mirror on read; host disk correct — screener 829 lines, monitor coherent, `nlv` in scope).

### Progress
- [x] -X% rule = 15% (shared sizing/exposure constant)
- [x] Exposure removed from screener; added to monitor as max-loss-at-stop + total vs NLV
- [ ] Extend rolls to short calls + combos
- [ ] Performance pass (pressing at 110 tickers)
- [ ] Alert delivery + scheduling — see Entry 015
- [ ] Stop-order automation — pending decisions (Entry 015)
- [ ] Phase 2: Cloud VM migration

---

## Entry 015 — 2026-06-08 (continued)

### Automation discussion + report delivery (decisions)
- **Delivery: Telegram** (free; @BotFather token + chat id). **Host: GitHub Actions** (free scheduled workflow) — the screener is yfinance-only so it runs PC-free in the cloud.
- **Architecture split confirmed:** screener report → cloud (PC-free); monitor + stop orders → stay on the PC (need IB Gateway). Full PC-free monitor/stops = Phase 2 (headless IB Gateway on a VM).
- **Cloud "lite vs full":** cloud screener degrades gracefully without the PC's IBKR files (IV Rank falls back to yf snapshot series, diversification off, fallback account size). Fix = commit `data/iv_history.csv` weekly from the PC so cloud gets IBKR IV Rank.

### Built
| File | Purpose |
|---|---|
| `notify.py` | Telegram sender (free Bot API). Creds via env (GH secrets) or `telegram_config.json`. Splits long msgs, HTML-escapes tables. |
| `daily_report.py` | Reads screener_output.csv (+ monitor_output.csv / roll_suggestions.csv if present) → compact Telegram digest (monitor actions + exposure, top rolls, screener top-10 + best-per-sleeve). Decoupled; same on PC or cloud. |
| `.github/workflows/screener.yml` | Daily cron (UTC) → install reqs → run screener.py → daily_report.py with TELEGRAM_* secrets. Manual dispatch enabled. |
| `requirements.txt` | yfinance, pandas, numpy, scipy, requests |
| `.gitignore` | Excludes telegram_config.json, data/account.json, venv, __pycache__, transient CSVs; keeps data/iv_history.csv trackable for cloud. |

### Testing
Report formatting + notifier tested (synthetic CSVs, no live send): message chunking under Telegram limit, graceful no-creds handling, HTML escaping, screener section (top-N + best-per-sleeve), monitor section (only CLOSE/ROLL rows; whole-book exposure total = $21,975 in the sample). All pass.

### Setup (user, ~10 min)
BotFather token + chat id → telegram_config.json (local test: notify.py / screener.py / daily_report.py) → push repo to GitHub → add TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID secrets → workflow runs on cron.

### Still pending: stop-order automation (PC-side, needs Gateway)
Recommended design: resting **GTC** stops at IBKR (broker-enforced 24/7), idempotent (place only for short puts missing a stop), **paper + dry-run default**, user flips to live. Guardrail: agent builds the tool but does not transmit live orders. Awaiting user decisions: (a) auto-place vs advisory-only; (b) trigger = underlying at strike−15% vs option-price multiple vs −15% from entry.

### Progress
- [x] Report delivery: Telegram via GitHub Actions (notify.py, daily_report.py, workflow, gitignore)
- [x] **LIVE: cloud screener → Telegram confirmed working** (bot OpScreen_bot, repo saudikun-boop/OptionScreener public, secrets set, manual run delivered to phone 2026-06-08)
- [x] PC helpers: run_daily.bat (monitor→screener→report), run_weekly.bat (IV update); monitor connect made fault-tolerant
- [ ] User: schedule run_daily.bat / run_weekly.bat via Task Scheduler (schtasks given); IB Gateway auto-restart + weekly 2FA
- [ ] Weekly PC push of data/iv_history.csv for cloud IBKR IV (cloud currently "lite")
- [x] Stop-order automation — place_stops.py (Entry 016)
- [ ] Extend rolls to short calls + combos
- [ ] Performance pass
- [ ] Phase 2: Cloud VM (headless Gateway → PC-free monitor/stops)

---

## Entry 016 — 2026-06-08 (continued)

### Stop-order tool — place_stops.py
Builds GTC buy-to-close stops for single-leg short puts, triggered when the
**underlying hits strike × (1 − 0.15)** (= strike −15%, `S.ASSUMED_DRAWDOWN`), matching
the monitor's exposure metric.

- **Modes:** `MODE='advisory'` (DEFAULT) prints proposed stops, submits nothing; `MODE='live'` transmits after a typed **YES** confirmation. Agent never transmits — user flips MODE + confirms.
- **Idempotent:** skips any short put that already has an open BUY order (stop/roll/close), so re-runs never duplicate. Skips combos (>1 leg per symbol/expiry) and short calls.
- **Order:** GTC `MarketOrder('BUY', qty)` with a `PriceCondition` on the underlying (`isMore=False`, price=trigger). Market = guaranteed exit (slippage risk; switchable to limit). Connects PORT 4001 (live — that's where positions are).
- Advisory table shows symbol/expiry/strike/qty/current stock/trigger/% to trigger.
- Pure helpers `stop_trigger`, `combo_keys`, `plan_stops` unit-tested (9 checks): trigger math (395→335.75, 57.5→48.88), combo flagged, protected-skip, calls/longs/combos excluded, qty abs.

### IBKR login automation (guidance given, not code)
Standard pattern: IB Gateway with **Auto Restart** (Configure→Lock and Exit), log in once (2FA), stays up days; full re-login (2FA) ~weekly. Optional IBC tool for auto-start. Truly unattended = Phase-2 VM. monitor.py made connect-fault-tolerant so scheduled runs don't crash when Gateway is down.

### Usage
Advisory: `venv\Scripts\python.exe place_stops.py` (Gateway up). Go live: set MODE='live', rerun, type YES. Re-run adds only missing stops.

### Progress
- [x] place_stops.py (advisory default → live; GTC underlying-conditional buy-to-close; idempotent)
- [ ] Optional: fold advisory "puts missing a stop" list into the daily digest
- [ ] Extend rolls to short calls + combos
- [ ] Performance pass
- [ ] Phase 2: Cloud VM (headless Gateway)

---

## Entry 017 — 2026-06-08 (continued)

### Stop basis discussion + final design
Discussed underlying-trigger vs option-price stop. Key points captured: underlying-conditional stops are immune to wide/noisy option quotes and are time-invariant; option-price stops (native STP) cap $ loss directly but can misfire on thin quotes and (for credit-multiple) trigger on IV spikes / whipsaw — a known drag on short-premium returns. User chose **underlying basis**, then tuned the level **15% → 10% → 7%**.

### place_stops.py — final
- **Configurable `STOP_BASIS`**: `'underlying'` (default) | `'option_intrinsic'` | `'credit'`.
  - underlying → conditional buy-to-close when stock ≤ strike×(1−STOP_DROP)
  - option_intrinsic → native STP at option price = strike×STOP_DROP
  - credit → native STP at CREDIT_MULT × entry credit (entry credit = avgCost/100)
- **`STOP_DROP = 0.07`** (−7%), a separate knob from sizing/exposure (`S.ASSUMED_DRAWDOWN = 0.15`): size for a 15% move, cut at 7% (conservative buffer). `CREDIT_MULT = 2.5`.
- Advisory default, idempotent, combos/calls skipped, live path builds MarketOrder+PriceCondition (underlying) or StopOrder (option), GTC, YES-gated.
- Pure helpers `stop_spec` / `plan_stops` / `combo_keys` unit-tested across all three bases (underlying 100→93.0, intrinsic→7.0, credit 2.5×2→5.0; MSFT 395→367.35; idempotent skip; entry credit from avgCost/100). Host file verified complete (180 lines).

---

## Entry 018 — 2026-06-08 (continued)

### Technical documentation created
Wrote **`docs/TECHNICAL_DOC.md`** (2267 lines) — full system reference: overview & architecture (components, data files, data-flow diagram), strategy/theory (wheel, IV vs HV, IV Rank vs IV/HV, gates-vs-score), data sources + the Option-A decision, the screener (universe, every gate, scoring buckets & exact formulas, sleeves, sizing), monitor (P&L/moneyness/exposure/actions/combos + roll suggestions), stops (bases/STOP_DROP/modes), reporting & Telegram, automation (GitHub Actions + Task Scheduler + IBKR login reality), a **Key Decisions** table (13 decision points), a **field glossary** for every output column, a **config reference**, **how-to-use**, a **GitHub** section, limitations/future work, and an **appendix with the full raw source** of all 9 code/config files (embedded via concatenation, fences balanced).

This is the canonical human-facing doc; PROJECT_LOG.md remains the chronological build journal.

---

## Entry 019 — 2026-06-08 (continued)

### Polished Word guide for first-time readers
Created **`docs/Options_System_Guide.docx`** (11 pages) — a visually designed, plain-English version aimed at someone seeing the system for the first time. Title page, auto table of contents, styled headings (navy/blue), colored tables with alternating rows, and blue "callout" boxes. Decisions are written narratively (e.g., "why volatility history is refreshed separately" instead of "Option A").

Two requested deep-dives are the centerpiece:
- **§6 How the score is calculated** — a fully worked 4-candidate example (NVDA/QQQ/META/GLD): raw inputs → per-factor percentile ranks → bucket averages → weighted composite (META 72.9 wins; GLD last due to low premium → motivates the per-sleeve view).
- **§7 Diversification** — the `(1−corr)/2×100` mapping table plus a live example against the actual 9-name book, showing scores cluster ~40s because nothing is negatively correlated now (so the per-sleeve view does the real work).

Built with docx-js, validated (412 paragraphs, all checks passed), rendered to PDF to verify layout. User noted an HTML version may follow once content is refined.

---

## Entry 020 — 2026-06-10

### Central config.json (repo-synced) + regime Option 3 + Bollinger-z oversold flag
**Why config.json:** user's hand-tuned `W_TECHNICAL=0.40` had been silently reverted by my later full-file rewrites (the code carried 0.25). Fix: pull tunables out of code into **`config.json`**, loaded by `screener.py` (`load_config()` + `_c()` overrides the in-code defaults). `monitor.py` and `place_stops.py` read the same file via `S.CFG`. config.json is **tracked (NOT gitignored)** so GitHub Actions (cloud) and the PC run identical settings — user explicitly wanted this in-sync. Sections: weights, gates, regime, oversold, sizing, monitor, stops. Missing keys fall back to code defaults.

**Regime gate → Option 3 (true falling knives only).** User felt "below 50 & 200-MA" was too broad — many fine basing/support setups live there. New `'downtrend'` rule: skip **only** when 200-MA is falling AND price is still within `NEW_LOW_TOL` (2%) of a **new ~6-month low** (`swing_low_126`). Names that dropped then based above their low now pass and are judged by the score. (Dropped the below-50&200 + near-50d-low combo.)

**Bollinger-z oversold = flag, not gate.** Discussed: a 3σ-below move is usually capitulation (rich premium + bounce) — an *opportunity* for a put seller, so excluding it would be backwards. Implemented `bb_z` (sigma below 20-day mean) as a column + a **mean-reversion bonus**: `bb_z ≤ OVERSOLD_Z` (−2.5) adds `OVERSOLD_BONUS` (8) to the technical score (clipped 100). Surfaces capitulation/support entries instead of hiding them.

**Tested (standalone, mount kept truncating the big file on read):** config overrides apply (weights/oversold/new_low_tol), new regime gate (falling+new-low blocked; based-above-low passes; flat-200MA passes; ma200 None passes), oversold bonus (+8/clip 100), bb_z formula. Host screener.py verified complete (874 lines). compute_technicals adds `bb_z` + `swing_low_126`.

Docs updated: TECHNICAL_DOC §5 (regime + oversold) and §12 (config.json). Word guide not yet regenerated (offer pending).

### Progress
- [x] config.json (weights/gates/regime/oversold/sizing/monitor/stops), repo-tracked, loaded by all 3 scripts
- [x] Regime Option 3 (falling-knife only) + Bollinger-z oversold bonus + bb_z column
- [ ] User: re-run screener; commit config.json so cloud picks it up; set weights in config (e.g. technical 0.40)
- [x] Regenerated Word guide (v1.1 → v1.2): regime=falling-knife, oversold flag, weights 40/40/20, config.json + Git callouts, bb_z glossary
- [x] Word guide §6 deep-dive (v1.2): added 6.1 "technical factors explained" (RSI tent peak@40 w/ table, Bollinger %B definition + band table, support-cushion formula) and rebuilt 6.2 as a 4-scenario step-by-step example (PYPL capitulation / META sweet-spot / NVDA overbought / GLD low-premium) showing every raw→score conversion incl. the oversold bonus. 12 pages, validated.
- [ ] Extend rolls/stops to calls + combos; performance pass; Phase 2 VM

---

## Entry 021 — 2026-06-15

### Call-writes, earnings, breakdown regime gate, doc refresh, encoding fix, single-file delivery
(Consolidated entry — covers everything since 020; an earlier draft of this entry didn't persist.)

**Telegram polish.** Compacted the report to one line per item so nothing wraps on a phone:
sleeve names abbreviated (`SLEEVE_ABBR`, 5–6 chars) with Δ + ann-yield on the per-sleeve line;
monitor/rolls reduced from wide tables to compact rows; earnings shown as **M/D**; deltas printed
without the leading zero. Added a command reference to `TECHNICAL_DOC.md` (§13.2a) and sleeve
abbreviations (§13.2b).

**Word guide v2 → v3.** v2 resolved 9 user comments (module-aligned §1 bullets, wheel framing in
§2, merged volatility §3+§4, "Quality"→"Fundamentals", monitor roll/assign alternatives, moved
"Where the details live" before the Glossary, consolidated Glossary with output-columns/commands/
terms/sleeves; comments stripped; renumbered). v3 (`Options_System_Guide_v3.docx`, v1.3) adds the
breakdown gate, **§8.4 Call-write suggestions + WMT worked example**, earnings, roll DTE variety,
CSV-attachment note, and glossary rows. (docx edited via python-docx: dup style names → reuse
style objects; no Table Grid → manual XML borders. Mount corrupted docx reads twice → user
re-uploaded; worked from a sandbox copy.)

**Regime gate → `breakdown` (steepness, not level).** Replaced the falling-knife/new-low rule.
`regime_block` now skips only an ACTIVE breakdown: steep drop (`dd_fast` ≥ `DROP_PCT` 15% over
`DROP_WINDOW` 10d) OR vol spike (`hv_fast`/`hv_slow` ≥ `VOL_RATIO` 1.8 AND `hv_fast` ≥ `VOL_ABS`
50%). A calm base at a low now passes. `compute_technicals` gained `dd_fast/hv_fast/hv_slow/
vol_ratio`. Legacy `downtrend_slope`/`new_low_tol`/`swing_low_126` retired (unused). Tested on
synthetic series.

**IV history.** Confirmed already fully backfilled (27,108 IBKR rows, ~251/ticker, current) in
`data/iv_history.csv` — the near-zero IV Rank is genuine (vol mean-reverted post-pullback), not a
data gap.

**Call-write (covered call / roll-up) suggestions** (`monitor.py`). For underlyings with long
exposure — shares (≥100) or long calls — score OTM calls to **sell**: `CC_W_OPTION` 0.6 ×
option-edge (IV rank, IV/HV, ann premium, percentile-ranked) + `CC_W_RESIST` 0.4 × resistance
cushion (strike vs the higher of 20-day upper Bollinger / swing high) + a capped `CC_LONG_BONUS`
(6) when the strike clears / stock is near the ~3-month high (`long_high_days` 63). Conservative
0.15–0.25Δ. **Coverage netting**: writable lots = shares/100 + long calls − calls already written;
`respect_coverage` toggle (set **false** so fully-covered names still appear as roll targets).
**Nearest-strike fallback**: when no strike lands in the Δ band (e.g. high-priced MSFT, strikes
skip the band) it shows the strikes closest to mid-band so you still get candidates. Writes
`covered_calls.csv`. Per-ticker diagnostics print (and log) detection + band counts.

**Earnings dates** surfaced as an `earnings` column (screener + monitor), shown as M/D in console
and Telegram headers/lines.

**Roll suggestions → DTE variety.** `build_roll_suggestions` now shows the best strike per expiry
across the nearest few DTEs (was top-3-by-score, which clustered in one expiry).

**cp932 encoding crash (important).** The Japanese (cp932) Windows console couldn't encode `—`
(—), so `screener.py`'s verbose `_p(summary)` threw `UnicodeEncodeError` and the screener died
mid-scan → stale `screener_output.csv`. Fix: force UTF-8 (`sys.stdout/stderr.reconfigure(
encoding='utf-8', errors='replace')`) at the top of `screener.py` (process-wide; `monitor.py`/
`place_stops.py` inherit via import) and `daily_report.py`.

**Single-file delivery.** `daily_report.py` now attaches ONE combined file via `notify.send_document`:
a multi-tab `daily_report.xlsx` (Screener/Monitor/Rolls/CallWrites via openpyxl), with a single
combined `daily_report.csv` (sections stacked) as the fallback when openpyxl is missing — never the
four separate CSVs again. `requirements.txt` += `openpyxl`. Clubbed the call-writes into one
compact block (all tickers, one line each) instead of a header+box per ticker.

**Batch logging.** `run_daily.bat` / `run_weekly.bat` tee full output (incl. call-write/coverage
diagnostics) to `logs\daily.log` / `logs\weekly.log` and echo to console.

**config.json**: added `regime` breakdown params, `covered_calls` (incl. `respect_coverage`),
`report.attach_csv`. **.gitignore**: += `covered_calls.csv`, `daily_report.xlsx`, `daily_report.csv`.

### Progress
- [x] Breakdown regime gate (drop/vol-spike) + config + tests; legacy knobs retired
- [x] Call-write suggestions (shares + long calls), coverage toggle, nearest-strike fallback (MSFT fixed)
- [x] Earnings column (screener+monitor+Telegram, M/D); roll DTE variety
- [x] cp932 UTF-8 fix (screener completes again); batch logging
- [x] Single combined attachment (xlsx tabs / combined-csv fallback); compact clubbed call-writes
- [x] Docs: TECHNICAL_DOC.md refreshed; Word guide v3; openpyxl in requirements
- [ ] User: pip install -r requirements.txt; run_daily.bat; verify xlsx + MSFT; commit/push
- [ ] Open offers: drop inline text tables (rely on attachment); widen CC delta_max vs fallback; short-call roll engine; skip-stale-monitor guard; IV/HV shorter-HV representativeness
- [ ] Extend rolls/stops to calls + combos; performance pass; Phase 2 VM

---

## Entry 021 — 2026-06-14

### Telegram report polish, docs v2, regime redesign, covered calls, earnings, roll variety

**Telegram "Best per sleeve" compacted.** Sleeve names were eating the line, so added a `SLEEVE_ABBR` map (5–6 letter codes, e.g. Equity Index→`EQIDX`, Financial Services→`FINSVC`) in `daily_report.py`, and added Δ and annualized yield to each sleeve line (delta shown without leading zero to save width). Lines land ~32–34 chars; legend documented.

**Command reference in the manual.** Added §13.2a to `TECHNICAL_DOC.md`: a table of every script with the exact `venv\Scripts\python.exe …` command, whether it needs IB Gateway, and what it writes.

**Word guide v2 (`Options_System_Guide_v2.docx`).** User added 9 inline comments; mount served a corrupted/stale copy so the user re-uploaded the file. Addressed all 9: (1) §1 bullets relabeled to module names (Screener/Monitor/Stops with file names); (3) §2 now frames the wheel and notes the covered-call leg isn't built yet; (7) merged §3+§4 into one volatility section (3.1 IV vs HV, 3.2 IV Rank vs IV/HV); (10) "Quality" gate → "Fundamentals"; (21/22) monitor actions now spell out roll-vs-close and assign-vs-roll alternatives; (32) "Where the details live" moved before the Glossary. Also consolidated the glossary into one section (output columns incl. `open_int`/`iv_src`/`spread_pct`, command reference, terms, sleeve abbreviations), stripped the comments, and renumbered. (docx edited via python-docx: dup style names → reuse style objects; no `Table Grid` → manual XML borders.)

**Regime gate redesigned → `breakdown` (steepness/vol, not price level).** User reframed the "falling knife" purpose: it's about the **steepness of the move**, not being at a low. Removed the old 200-MA-falling + new-6-month-low logic. New `regime_block` (`mode:"breakdown"`) skips a name only on an ACTIVE sharp move: **steep drop** (peak→now fall ≥ `drop_pct` 15% over `drop_window` 10d) **OR vol spike** (`vol_fast` 10d realized vol ≥ `vol_ratio` 1.8× `vol_slow` 63d baseline AND ≥ `vol_abs` 50%). Added `dd_fast`/`hv_fast`/`hv_slow`/`vol_ratio` to `compute_technicals`. A stock that ground down to a low but is now calm now PASSES. Legacy `gate` (price<200-MA) still selectable; `DOWNTREND_SLOPE`/`NEW_LOW_TOL`/`swing_low_126` remain defined but unused. Tested on synthetic series (steep drop & vol spike blocked; based-at-low passes). config `regime` section rewritten.

**IV history — already backfilled.** User asked to backfill for the near-zero IV Rank. Found `update_iv_history.py` already pulls a **full year** (`durationStr='1 Y'`); `data/iv_history.csv` has 27,108 IBKR rows (~251/ticker) current to today. So IV Rank already uses a complete year — the low reading is genuine (vol mean-reverted post-pullback). Offered (not yet built) an IV/HV + shorter-HV representativeness tweak.

**Covered-call suggestions (`monitor.py`).** New `build_covered_calls`/`print_covered_calls`: for held shares (≥100), scores OTM calls in 0.15–0.25Δ (conservative, user's pick). Score = `w_option` 0.6 × option-edge (IV rank, IV/HV, ann. premium, percentile-ranked across pool) + `w_resist` 0.4 × resistance cushion (strike above 20-day upper Bollinger / swing high) + a small capped bonus (`long_high_bonus` 6) that fires only when the strike clears the ~3-month high and/or the stock is near it. Decision: primary resistance = 20-day (binds over the option life); the 3–6 month high is a **weak conditional bonus + always-visualized columns** (`high_3m`, `strike_vs_3mhigh_%`) — avoids flooding with uninformative long-horizon signals. No gates. Writes `covered_calls.csv`. Validated scoring + call-delta on synthetic data.

**Earnings dates.** `earnings` column added to `screener_output` (from existing `get_next_earnings`) and `monitor_output` (per-ticker lookup); shown in console tables and appended to Telegram headers as `E:MM-DD`.

**Roll suggestions → DTE variety.** `build_roll_suggestions` was top-3-by-score (clustered in one expiry, e.g. all META same DTE). Now: best strike **per expiry**, then nearest N expiries → several different DTEs to compare. `daily_report` roll block shows up to 3 with `roll_dte`.

**daily_report decoupling (clarified for user).** `daily_report.py` reads CSVs only; each `fmt_*` skips if its file is absent. So monitor isn't a hard dependency — it enriches the report when `monitor.py` has run (PC + Gateway). Cloud run stays screener-only. Caveat noted: CSVs persist, so a failed monitor run could surface stale positions (offered a "skip stale monitor" guard).

**config.json:** new `covered_calls` block; `regime` rewritten to breakdown params.

### Progress
- [x] Sleeve abbreviations + Δ/yield in Telegram; command reference in TECHNICAL_DOC §13.2a
- [x] Word guide v2: 9 comments addressed, glossary consolidated, comments stripped, renumbered
- [x] Regime gate → breakdown (steep drop OR vol spike); config + tests
- [x] Confirmed IV history fully backfilled (full-year IBKR in data/iv_history.csv)
- [x] Covered-call suggestions (option-edge + resistance + capped 3-mo bonus, 0.15–0.25Δ)
- [x] Earnings column (screener + monitor + Telegram); roll DTE variety
- [x] daily_report wired for covered calls + earnings + richer rolls
- [ ] User: TEST outputs on PC (monitor → daily_report with Gateway); then commit + push screener.py/monitor.py/daily_report.py/config.json
- [ ] Pending offers: update guide (§11.1 + covered-call subsection); IV/HV representativeness tweak (shorter HV); skip-stale-monitor guard
- [ ] Extend rolls/stops to calls + combos; performance pass; Phase 2 VM

---

## Entry 022 — 2026-06-17

### Folder reorg (code/ + reports/), Telegram layout fixes, Excel hardening, top-10, JNJ explained

**Universe / display.** `report.top_tickers` 5 → 10.

**JNJ "missing" explained.** Not a quality reject — it passed all gates but produced 0 tradable
contracts: earnings 2026-07-15 trips the earnings gate on the in-window expiries, and the
remaining near strikes were rejected for wide spread (>10%), low OI (<100), and delta band. Found
via the per-ticker reject counter now captured in `logs/daily.log`. It returns post-earnings.

**yfinance noise + batch stderr.** Silenced yfinance's own logging (`logging.getLogger('yfinance')`
→ CRITICAL in screener, inherited by monitor) so "$VIX possibly delisted / 404 no fundamentals
(QQQ/VIX)" stops printing. Mapped index symbols in `monitor.get_stock_price` (`VIX→^VIX`, etc.).
Batch PowerShell now sets `$ErrorActionPreference='Continue'` and pipes through
`ForEach-Object { [string]$_ }`, so native stderr no longer renders as red `NativeCommandError`.

**Live batch progress.** The first tee approach (`cmd | powershell "$input | Tee-Object"`) buffered
everything → console looked frozen. Fixed to pipe *inside* PowerShell + run Python `-u`
(unbuffered) → output now streams ticker-by-ticker, with a per-step banner.

**Excel attachment hardened.** `build_workbook` now: explicit `openpyxl` import, per-sheet error
print, never saves an empty workbook, and uses a **dated filename** (`daily_report_YYYY-MM-DD.xlsx`)
to dodge file locks. Added a **single combined-CSV fallback** (`daily_report.csv` with a `section`
column) so you never get four separate CSVs again. `openpyxl` added to requirements; `send_document`
MIME → octet-stream. Confirmed working in the log (`Workbook built … 4 sheets / Attached`).

**Call-write asterisk.** `cc_open` flag marks names where a short call is already open (e.g. `MSFT*`),
shown in console + Telegram with a `* = call already open` legend.

**Telegram screener/rolls layout.** Root cause of the "red screener" pinned down: the long message
was being **chunk-split through the middle of the screener `<pre>`** (best-per-sleeve landed in an
intact chunk, so it stayed white). Fixed `notify._chunks` to split on blank-line **section
boundaries — never cutting a `<pre>`**. Reverted screener + rolls to single aligned monospace
blocks like the other sections (no 8-line partitions). Rolls render `cur>new strike` across several
DTEs. (Briefly tried plain text and 8-line sub-blocks before finding the chunk-split cause.)

**FOLDER REORGANIZATION.** Python → `code/`, all generated outputs → `reports/`, `config.json` +
`telegram_config.json` stay in root, `data/` unchanged. Rewired every path to be **root-anchored**
(`_ROOT` = parent of `code/`): screener (config/data/holdings + `REPORTS_DIR` + makedirs), monitor
(3 outputs via `S.REPORTS_DIR`), notify (telegram_config), daily_report (`_ROOT` for config,
`_REPORTS` for outputs). Updated all four `.bat` files (`code\…`), the GitHub workflow
(`python code/…`), and `.gitignore` (`reports/`). Moved old test scripts into `code/`, cleared
stale root CSVs, cleaned `__pycache__`. Verified by importing screener+daily_report+notify (all
paths resolve correctly, config loads) and compiling the ib_insync scripts. A sandbox `git mv`
glitched the index (mount) → `git reset` cleaned it; the move is committed from the PC via
`git add -A`.

**Docs.** TECHNICAL_DOC command paths → `code\`; Word guide **v4** (`Options_System_Guide_v4.docx`,
v1.4) command examples → `code\` + a project-layout note.

### Progress
- [x] top 10; JNJ explained (earnings + liquidity gate, not quality)
- [x] yfinance noise silenced; VIX→^VIX; batch stderr clean; live ticker-by-ticker streaming
- [x] Excel hardened + single-file (xlsx or combined-csv) attachment; openpyxl in requirements
- [x] call-write `*` when already open; screener+rolls single aligned blocks; `_chunks` never splits `<pre>`
- [x] Folder reorg: code/ + reports/, all paths/bats/workflow/gitignore rewired; verified imports/compiles
- [x] Docs: TECHNICAL_DOC + Word guide v4 command paths + layout note
- [ ] User: commit reorg from PC (`git add -A`); re-run `run_daily.bat`
- [ ] Pending: IV/HV shorter-HV representativeness; skip-stale-monitor guard; short-call roll engine; extend rolls/stops to calls+combos; Phase 2 VM

---

## Entry 023 — 2026-06-20

### Fundamentals (FCF-yield) bucket, dividend watchlist, require-live-quote gate, field layout

**Fundamentals scoring bucket (Goldman "art of put selling").** User shared the GS paper: selling
puts on **high-FCF-yield** stocks (top quintile) beat the index by ~250bps/yr at a higher Sharpe —
FCF yield is a "margin of safety" proxy. Implemented a **4th scoring bucket** `score_fundamental`
(weight **0.30**, `weights.fundamental`): percentile-ranked **FCF yield** (FCF ÷ market cap) blended
with ROE. Composite renormalizes over available buckets (ETFs have no FCF → skip). Added
`fcf_yield` to fundamentals (`freeCashflow/marketCap×100`) and to the candidate rows. Tested: a
candidate with the best option-edge but weak fundamentals correctly drops below a high-FCF name.

**Dividend yield 100× bug + dividend watchlist.** yfinance now returns `dividendYield` already as a
percent; code still ×100 (TLT showed 455%). Fixed. Then built an **ungated dividend watchlist**
(option 2): `screen_ticker` captures each stock's div yield BEFORE the gates (via a `div_collector`),
so high-yield names knocked out by earnings/liquidity (USB, VZ, PFE, PEP, …) still surface. Writes
`reports/dividends.csv`; Telegram `DIVIDENDS` section (monospace, ETFs excluded) + console block +
Excel `Dividends` tab. Size via `report.top_dividends` (3).

**Require live quote gate.** GILD showed a 43% IV on a strike with **no bids** — IV was back-solved
from a stale `lastPrice` and the put wasn't sellable. Added `gates.require_quote` (default **true**):
a contract needs a live **bid & ask** to qualify (no more stale-last fallback). Caveat: pre-market/
weekend runs return few/none (quotes not live) — set `require_quote:false` for those. Also taught the
team that the screener's per-strike OTM-put IV (skew) is expected to exceed IBKR's ATM IV.

**Reports no longer accumulate.** Each run deletes prior `daily_report_*.xlsx` / `daily_report.csv`
before writing the new dated one (keeps only the latest).

**Screener field layout (user's Sheet1 spec).** Applied to the Excel **Screener tab** (the full-field
view) via `daily_report._screener_view`: reordered columns, **dropped `etf`**, **shortened sleeve**
(abbrev), **rounded delta/theta to 3**, `_pct`→`%` (`spread%`,`ann_ret%`,`iv%`,`hv%`,`%B`), added
`fcf_yield%`, and slotted `score_fundamental` with the other score columns. The raw CSV keeps
original names so the report code + cloud keep working.

**Monitor: collateral + dividend yield.** Added `collateral` (strike×100×|qty| — cash secured) and
`div_yield` (underlying) columns to the monitor table (console + Excel Monitor tab).

**Misc.** VIX→^VIX index map; yfinance logging silenced; batch live-streaming + stderr cleanup (from
prior turns, in place).

### config.json additions
`weights.fundamental` 0.30 · `gates.require_quote` true · `report.top_dividends` 3.

### Progress
- [x] Fundamentals/FCF-yield bucket (0.30) + fcf_yield computation; tested
- [x] Dividend 100× fix + ungated dividend watchlist (csv + Telegram + Excel tab)
- [x] require_quote gate (live bid/ask; filters no-bid/stale-IV contracts)
- [x] Reports auto-cleanup (no accumulation); screener Excel field layout; monitor collateral + div yield
- [ ] User: commit (`git add code/ config.json`); re-run during market hours to verify
- [ ] Docs: update TECHNICAL_DOC + Word guide for the fundamentals bucket etc. (in progress)
- [ ] Pending: IV/HV shorter-HV tweak; short-call roll engine; calls/combos rolls; Phase 2 VM

---
