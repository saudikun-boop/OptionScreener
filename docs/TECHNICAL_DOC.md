# Options Wheel / Put-Selling System — Technical Documentation

*A personal, semi-automated system for finding, sizing, monitoring, rolling, and
protecting cash-secured short-put positions on US equities and ETFs.*

Last updated: 2026-06-08

---

## 1. Overview

This system supports a **cash-secured put-selling ("wheel") strategy**: sell out-of-the-money
puts on quality underlyings you'd be content to own, collect premium, and manage the
positions to a profit target, a roll, or a stop. It has three jobs:

1. **Find** trades — a screener ranks a universe (S&P 100 + cross-asset ETFs) by a
   composite of option edge, technicals, and portfolio diversification, after passing a
   set of hard quality/liquidity gates.
2. **Manage** open positions — a monitor flags positions for close / roll / hold, computes
   P&L, moneyness and exposure, and proposes scored roll candidates.
3. **Protect** — a stop tool proposes (and, on demand, places) GTC stop orders.

Delivery is via a daily **Telegram** digest. The screener can run **PC-free in the cloud**
(GitHub Actions); position management and order placement run on the **PC** (they need IB
Gateway).

### Design philosophy in one line
*Gates prune the universe to what is safe and tradable; a weighted score ranks only the
survivors; sizing and stops cap risk; everything is observable and reversible.*

---

## 2. Architecture

| Component | File | Runs where | Needs IB Gateway? | Purpose |
|---|---|---|---|---|
| Screener | `screener.py` | PC or cloud | No (yfinance) | Find & rank candidates |
| IV updater | `update_iv_history.py` | PC | Yes | Pull IBKR IV/HV history for IV Rank |
| Monitor | `monitor.py` | PC | Yes | Flag/close/roll positions, exposure, NLV |
| Stops | `place_stops.py` | PC | Yes | Propose/place GTC stops |
| Notifier | `notify.py` | PC or cloud | No | Send Telegram messages |
| Reporter | `daily_report.py` | PC or cloud | No | Assemble + send the digest |
| Cloud schedule | `.github/workflows/screener.yml` | GitHub | No | Daily screener report, PC-free |
| PC schedule | `run_daily.bat`, `run_weekly.bat` | PC (Task Scheduler) | Yes | Daily full digest, weekly IV refresh |

### Data files (in `data/` or project root)

| File | Written by | Read by | Notes |
|---|---|---|---|
| `data/iv_history.csv` | updater (`ibkr`) + screener (`yf`) | screener | Daily IV/HV series → IV Rank. Committed to repo for cloud. |
| `data/account.json` | monitor | screener | NetLiquidation for sizing. Gitignored (personal). |
| `monitor_output.csv` | monitor | screener (holdings), report | Current positions + flags. Gitignored. |
| `screener_output.csv` | screener | report | Ranked candidates. Gitignored. |
| `roll_suggestions.csv` | monitor | report | Top rolls per flagged position. Gitignored. |
| `telegram_config.json` | you | notifier | Bot token + chat id. **Gitignored — secret.** |

### Data flow

```
              (weekly, PC)                         (daily)
 IB Gateway ── update_iv_history.py ─► data/iv_history.csv ─┐
                                                            │
 yfinance ───────────────────────────────────────────────► screener.py ─► screener_output.csv ─┐
                                                            │                                    │
 IB Gateway ── monitor.py ─► monitor_output.csv, account.json, roll_suggestions.csv ─────────────┤
                                                                                                 ▼
                                                                                       daily_report.py ─► Telegram
 IB Gateway ── place_stops.py ─► (GTC stop orders)
```

---

## 3. Strategy & theory

### 3.1 The wheel / cash-secured put
Selling a put obligates you to **buy 100 shares at the strike** if assigned, in exchange for
an up-front **credit**. Done on names you're happy to own, this is a high-probability income
strategy: most puts expire worthless (you keep the credit); if assigned, you own a stock you
wanted, at a discount, and can then sell covered calls (the "wheel"). The screening question
is therefore not *"will this stock go up?"* but **"would I be content to own this if assigned,
and am I being paid richly to wait?"**

### 3.2 Implied vs historical volatility (the edge)
- **HV (historical / realized volatility)** is measured from the **stock's own past returns**
  (annualized standard deviation of daily log returns). Backward-looking; "how much did it
  actually move?"
- **IV (implied volatility)** is backed out of **option prices**; it's the market's
  forward-looking expectation. They are *different instruments measured in different
  directions in time* — IV is **not** a smoothed HV.
- The put seller's structural edge is the **variance risk premium**: IV usually sits a little
  **above** HV (you're paid more than the realized risk). The ratio **IV/HV > 1** is that edge
  made explicit. After a real move, HV rises too, so the ratio compresses — which is correct.

### 3.3 IV Rank vs IV/HV (a common confusion)
- **IV/HV** compares today's implied vol to today's realized vol → *"are options rich vs what
  the stock is actually doing?"*
- **IV Rank** compares today's IV to **its own trailing 1-year range**:
  `(IV − 52wk low) / (52wk high − 52wk low) × 100` → *"is vol elevated for this name vs its
  own history?"*
- They are independent and routinely disagree. A name can have rich IV/HV yet a middling IV
  Rank (today's vol is above realized, but not high versus its own past spikes). Both feed the
  option-edge score because they answer different questions.

### 3.4 Gates vs score
A single ranked list cannot both *exclude the un-tradable/unsafe* and *order the rest*. So:
- **Gates** are hard pass/fail filters (safety + tradability). A name can never "score its way"
  past a gate.
- **Scores** rank only the survivors. This keeps the dangerous 5% out entirely while letting
  the edge metrics differentiate the good from the great.

---

## 4. Data sources & the "Option A" decision

| Need | Source | Why |
|---|---|---|
| Live option chains, greeks, prices | **yfinance** (free) + Black-Scholes | IBKR options market data needs a paid subscription; yfinance + a BS solver is sufficient and free. Keeps the screener Gateway-independent. |
| IV Rank history (per-underlying daily IV) | **IBKR** `reqHistoricalData(whatToShow='OPTION_IMPLIED_VOLATILITY')` | IBKR returns a full, consistent 1-year daily IV series in one call — so IV Rank works immediately, no months of accrual. |
| Realized vol (HV) | IBKR `HISTORICAL_VOLATILITY` (preferred) or computed from yfinance | For the IV/HV ratio. |
| Positions, NetLiquidation, orders | **IBKR** via `ib_insync` | Live account state for the monitor and stops. |
| Fundamentals (P/E, ROE, growth, sector, ETF flag) | **yfinance** `.info` | Free; enough for the quality gate. |

**Option A (chosen):** keep IV Rank on a *single, consistent source*. A dedicated updater
(`update_iv_history.py`) pulls IBKR's full-year IV/HV into `data/iv_history.csv` (tagged
`source=ibkr`); the screener simply *reads* that file and never needs the Gateway. The
screener also appends its own daily yfinance/BS ATM-IV snapshot (`source=yf`) as a fallback
series. **IV Rank is always computed within one source** (IBKR preferred, yfinance fallback,
never mixed) because mixing two differently-measured IV series corrupts the rank.

---

## 5. The screener (`screener.py`)

### 5.1 Universe
`SP100` (101 names incl. both Alphabet classes; `BRK-B` for yfinance) **+** `ETFS`
(SPY, QQQ, IWM, TLT, IEF, HYG, GLD, SLV, VNQ) = ~110 tickers. ETFs are detected via
`quoteType=='ETF'` or the `ETF_TICKERS` set and **bypass the fundamentals/solvency/earnings
gates** (they have no financials/earnings). S&P 100 was chosen over the S&P 500 because every
name has deep, liquid options — liquidity matters more to a put seller than raw breadth.

### 5.2 Gates (hard filters)
| Gate | Rule | Rationale |
|---|---|---|
| DTE window | 15–60 days | Theta sweet spot; avoid short-dated gamma. |
| Delta band | 0.15 ≤ |Δ| ≤ 0.30 | ~70–85% probability OTM; the wheel's strike zone. |
| Strike range | 0.75–1.02 × spot | Scan meaningful OTM puts (+ small ATM buffer). |
| Liquidity — spread | bid-ask ≤ 10% of mid | Wide spreads erase edge on entry + exit. |
| Liquidity — OI | open interest ≥ 100 (when present) | Tradability. `ALLOW_MISSING_OI` lets weekend 0/NaN OI through (data artifact, not illiquidity). |
| Liquidity — live quote | `require_quote` (default on): need a real **bid & ask** | A no-bid put isn't sellable, and its IV would be back-solved from a stale last price. Turn off (`require_quote:false`) for pre-market/weekend runs. |
| Earnings | skip expiries that straddle the next earnings date | Avoid binary vol-crush / gap risk. (Equities only.) |
| Regime | `REGIME_MODE='breakdown'`: skip only **active sharp breakdowns** (steep drop OR vol spike) | See below. |
| Solvency | drop clearly distressed balance sheets | "Don't get assigned a falling knife." Equities only. |
| Fundamentals | quality bar (FCF>0, rev growth ≥0, ROE ≥8%, fwd P/E ≤60) | Quality screen; missing data never rejects. Equities only. |

**Regime gate — active breakdowns only (revised again).** The point of avoiding a "falling
knife" is the **steepness of the move, not the price level** — a name that quietly ground down
to a low but is now calm is a fine put-sell, whereas one crashing *today* is not. So the gate no
longer looks at 200-MA position or new lows at all. `REGIME_MODE='breakdown'` (default) skips a
ticker only when it is in an **active sharp breakdown**, defined as either:

- **Steep drop** — price has fallen ≥ `DROP_PCT` (15%) from its high over the last `DROP_WINDOW`
  (10) trading days (`dd_fast` = peak→now drawdown over the window), **or**
- **Volatility spike** — short-window realized vol `hv_fast` (`VOL_FAST`=10d, annualized) is ≥
  `VOL_RATIO` (1.8) × its `VOL_SLOW` (63d) baseline **and** ≥ `VOL_ABS` (50%). Both conditions
  must hold so a normally-calm name merely doubling off a tiny base doesn't trip it.

A stock that fell months ago and is now basing (vol back to normal) passes through to the score
(including the oversold bonus). Modes: `'breakdown'` (default), `'gate'` (legacy strict
price<200-MA), `'score'`/`'off'` (no gate). The old `downtrend_slope`/`new_low_tol` knobs are
retired (still accepted but unused).

**Oversold flag (Bollinger z-score).** Deep oversold is an *opportunity* for a mean-reverting put
seller (rich premium + bounce potential), not a danger — so it is a **score bonus, not a gate**.
The system computes `bb_z` = how many standard deviations price sits below its 20-day mean; when
`bb_z ≤ OVERSOLD_Z` (default −2.5) it adds `OVERSOLD_BONUS` (default 8) points to the technical
score and surfaces `bb_z` as a column, so capitulation/support entries are highlighted rather
than hidden.

**Fundamentals as a gate, not a score (decision).** Originally fundamentals were a 30% scoring
bucket, but a strong-fundamental name's advantage kept being *offset* by a weaker name's richer
premium — i.e., premium could "buy past" quality. And per-row percentile-ranking skewed with
how many option rows each ticker contributed. So fundamentals became a **pass/fail quality
gate**; ranking is left to option edge + technicals + diversification.

### 5.3 Scores (rank the survivors)
The composite is a weighted, **renormalizing** average over whichever buckets are available
(so a missing bucket doesn't zero out a candidate):

```
score = (Σ weightᵢ · bucketᵢ) / (Σ weightᵢ over available buckets)
```

| Bucket | Weight* | Components | How each is scored |
|---|---|---|---|
| Option edge | `W_OPTION` | IV Rank, IV/HV, annualized return, theta decay | **Percentile-rank** across candidates (higher = better) |
| Technical | `W_TECHNICAL` | RSI sweet-spot, Bollinger %B, support cushion | RSI/BB are **direct 0–100**; support is percentile |
| Diversification | `W_DIVERSIFY` | avg correlation to current holdings | **Absolute** 0–100 (not percentile) |
| Fundamentals | `W_FUNDAMENTAL` | **FCF yield** (FCF ÷ market cap) + ROE | **Percentile-rank** (higher = better) |

*Weights are tunable constants (config.json `weights`); the composite renormalizes so they need
not sum to 1. Current default is 0.40 / 0.40 / 0.20 / 0.30 (option / technical / diversify /
fundamental). Check `config.json` for live values.

**Fundamentals components (decision — FCF yield is now scored).** Based on Goldman Sachs' *"The Art
of Put Selling"*: selling puts on **high-FCF-yield** stocks (top quintile) historically beat the
index by ~250bps/yr at a higher Sharpe — FCF yield is a "margin of safety" proxy (higher margins,
deleveraging, cash cushion). So a **fundamentals bucket** ranks candidates by **FCF yield**
(`freeCashflow ÷ marketCap × 100`) blended with **ROE**, percentile-ranked, higher = better. Note
fundamentals are *also* still a pass/fail gate (FCF>0, ROE≥8%, growth≥0, fwd P/E≤60); the bucket
then ranks the survivors by quality. ETFs have no FCF yield → the bucket is skipped and the
composite renormalizes.

**Option-edge components**
- **IV Rank** — per *ticker* (underlying-level), from the preferred IV source (§4). Same value
  for all of that ticker's options. Needs ≥20 stored points or it's blank (NaN) and simply
  drops out of the bucket.
- **IV/HV** — option's implied vol ÷ realized vol (IBKR HV preferred). >1 = rich.
- **Annualized return on collateral** — `(premium / strike) / DTE × 365 × 100` (%). Compares
  yield across strikes/expiries on equal footing.
- **Theta decay** — |theta| (income velocity).

**Technical components**
- **RSI(14) score** — direct 0–100, peaks at ~40 (the 30–50 "fear but not collapse" zone),
  penalizes overbought (>70) and falling-knife (<25). Formula: `max(0, 100 − |rsi−40|·2)`,
  halved if rsi<25 or >75.
- **Bollinger %B score** — lower %B (price near/below the lower band) scores higher:
  `clip((1 − %B)·100, 0, 100)`.
- **Support cushion** — `(swing_low_20 − strike)/price`, percentile-ranked; more cushion below
  a recent swing low is better.

**Diversification component (decision: score vs current portfolio).** Each candidate's average
**correlation of daily returns (≈6 months) to your current holdings** (read from
`monitor_output.csv`), mapped **absolutely**: `clip((1 − avg_corr)/2 · 100, 0, 100)` →
corr −1→100, 0→50, +1→0. It's *absolute* (not percentile) so that when nothing is genuinely
uncorrelated, nothing scores high. When the book is empty the bucket is skipped. Reality
check: among long equities, true negative correlation is rare and correlations spike toward 1
in selloffs — so the realistic goal is *low* correlation, and genuine diversification comes
from the **ETF sleeves** (bonds/gold), not from more stocks.

### 5.4 Sleeves & "best per sleeve"
Because an edge-ranked list structurally buries low-premium diversifiers (bonds/gold), each
candidate is tagged with a **sleeve** (ETFs by asset class via `ETF_SLEEVE`; equities by
yfinance `sector`). The screener prints a **BEST PER SLEEVE** table — the top N per sleeve — so
you build a diversified book by *picking across sleeves* rather than taking the global top-N
(which skews to whatever sector has the richest premium that day).

### 5.5 Position sizing
`position_size()` recommends **lots** under an **assignment + drawdown** risk model:
```
risk per contract = strike × 100 × ASSUMED_DRAWDOWN
lots = floor( (ACCOUNT_SIZE × MAX_RISK_PCT) / risk per contract )
```
`ASSUMED_DRAWDOWN = 0.15` (you size as if the stock could fall 15% below strike before you
exit), `MAX_RISK_PCT = 0.03` (≤3% of the account at risk per position). `ACCOUNT_SIZE` is read
from `data/account.json` (real IBKR NetLiquidation, written by the monitor); the hardcoded
value is only a fallback.

---

## 6. The monitor (`monitor.py`)

Connects to IB Gateway, pulls **all** option positions, and for each computes:

- **P&L %** — short legs profit when the option cheapens; long legs the opposite. (IBKR
  `avgCost` is per-contract → divide by 100 for per-share.)
- **Moneyness** (`stock`, `money`) — for short puts: `ITM` if stock<strike, `ATM` if within
  `NEAR_ATM_BUFFER` (3%) above, else `OTM`.
- **Earnings** — the next earnings date per ticker (`get_next_earnings`), shown compactly as
  **M/D** in the console and the Telegram lines so you can see binary risk at a glance.
- **Collateral** — for short puts, the cash-secured amount set aside: `strike × 100 × |qty|`.
- **Dividend yield** — the underlying's yield (%), so you can see income if assigned.
- **Exposure** — for short puts, **max loss at the stop**: `strike × ASSUMED_DRAWDOWN × 100 ×
  |qty|` (your "−15% rule" expressed as dollars at risk). A whole-book total is printed as a
  **% of NLV**.
- **Action**:
  - `CLOSE` — short leg at ≥70% profit (`PROFIT_TARGET_PCT`) or ≤21 DTE (`HARD_CLOSE_DTE`).
  - `ROLL?` — single-leg short put that is **ATM/ITM** (challenged) but not otherwise flagged.
  - `HOLD` — otherwise.
- **Combos** — legs sharing (ticker, expiry) are tagged `COMBO`; if any leg triggers, the group
  is flagged together. Combos are excluded from roll/stop automation (handled deliberately).

It also fetches **NetLiquidation** and saves it to `data/account.json` for the screener's
sizing, and writes `monitor_output.csv` (used for the report and the screener's diversification
baseline).

### 6.1 Roll suggestions (reuse the screener's brain)
For each **close-flagged or ATM/ITM single-leg short put**, the monitor runs the *same*
screener gates + scoring on that ticker's **later-expiry** puts, annotated with **net credit** =
new put mid − cost to buy back the current put (positive = you're paid to roll out). If the
ticker is now gated, there are no roll candidates → the implicit recommendation is *close*.

**DTE variety (revised).** Instead of the top 3 strikes by score (which clustered into a single
expiry), the monitor now shows the **best-scoring strike per expiry**, then the **nearest few
expiries**, so you can compare several *different DTEs* side by side rather than three strikes in
one month. Roll composite scores rank candidates *within* that ticker, so they aren't directly
comparable to a global screener run. (Rolls currently cover short puts only; short calls/combos
are future work — for now manage short calls via the call-write table in §6.2.)

### 6.2 Call-write suggestions (covered calls & roll-ups)
For every underlying where you have **long exposure** — shares (≥100) or long calls — the monitor
proposes calls to **sell**, the mirror of the put-entry logic. Shares → a true covered call;
long calls → selling a higher call against them = a vertical/diagonal **spread / roll-up**. There
are **no gates** (every eligible call is scored and surfaced); writes `covered_calls.csv`.

**Eligibility & coverage.** Writable lots = `shares/100 + long calls − calls already written`.
With `respect_coverage=true` a fully-covered name (e.g. 200 shares with 2 calls already sold)
nets to 0 and is **skipped**; set it `false` (current default) to always show every underlying so
the suggestions double as **roll targets** for calls you already hold.

**Conservative strikes.** Only OTM calls with delta in `CC_DELTA_MIN..CC_DELTA_MAX` (0.15–0.25)
— further OTM, so the shares are less likely to be called away.

**Score = option-edge + resistance + a small 3-month bonus:**

- **Option edge** (`CC_W_OPTION`, 0.6): IV rank, IV/HV, and annualized premium yield on the
  shares (`mid/stock /DTE×365`), **percentile-ranked across the whole candidate pool**.
- **Resistance cushion** (`CC_W_RESIST`, 0.4): how far the strike sits **above near-term
  resistance** — the higher of the 20-day upper Bollinger band and the 20-day swing high —
  percentile-ranked. A strike above resistance is less likely to be breached (you keep the
  shares). This is the mirror of the put side's *support* cushion.
- **3-month-high bonus** (capped at `CC_LONG_BONUS`, 6 pts): fires only when the strike clears
  the ~3-month high (`long_high_days`=63) and/or the stock is within `near_high_pct` (3%) of that
  high. The longer high is shown as the `high_3m` / `strike_vs_3mhigh_%` columns regardless, but
  only *nudges* the score in the cases where it's genuinely predictive — avoiding a flood of
  uninformative long-horizon signals on a 1-month option.

`score = clip(0.6·option_edge + 0.4·resistance + bonus, 0, 100)`.

**Worked example.** Suppose you hold 300 WMT shares (3 lots), WMT = $121, the 20-day upper band
is $124 and the 20-day swing high $126 (so near-term resistance ≈ **$126**), and the 3-month high
is $135. A **$122 call, 47 DTE** has Δ0.23 (inside the band), mid $3.80 → annualized yield
≈ `3.80/121/47×365 ≈ 24%`. Its resistance cushion is `(122 − 126)/121 = −3.3%` (below resistance —
not ideal), and it's well below the 3-month high, so **no bonus**. Across the pool it lands around
the middle on resistance and decent on premium → composite ≈ **67**. Contrast a **$127 call**:
cushion `(127 − 126)/121 = +0.8%` (clears near-term resistance), still below the $135 3-month high
(no bonus), a bit less premium — it scores **higher on resistance** but lower on yield, so the
two compete and the system surfaces both for you to choose your aggressiveness. Had the stock been
near $134 (within 3% of the $135 3-month high) and the strike ≥ $135, the capped **+6 bonus**
would kick in — writing calls "at the top of the range," exactly when it's most attractive.

---

## 7. Stops (`place_stops.py`)

Proposes (and, on demand, places) **GTC buy-to-close stops** for single-leg short puts that
lack a protective order. **Idempotent** (skips puts that already have an open BUY order),
**combos/calls skipped**.

- **`MODE`** — `'advisory'` (default; prints, submits nothing) or `'live'` (transmits after you
  type `YES`). The default-safe path lets you validate triggers before anything is live.
- **`STOP_BASIS`** —
  - `'underlying'` (default) — conditional order; fires when the **stock** hits
    `strike × (1 − STOP_DROP)`. Immune to noisy option quotes, time-invariant. Fires a market
    buy-to-close.
  - `'option_intrinsic'` — native STP on the option at `strike × STOP_DROP`.
  - `'credit'` — native STP at `CREDIT_MULT × entry credit` (classic premium stop).
- **`STOP_DROP = 0.07`** — the stop cuts at **strike −7%**, a separate (tighter) knob from the
  15% sizing assumption — i.e., *size for a 15% move, but exit at 7%* (conservative buffer).
- **`CREDIT_MULT = 2.5`** — for the credit basis.

**Why underlying-basis is the default.** Option-price stops can misfire on wide/thin option
quotes and (credit-multiple) trigger on IV spikes — a documented drag on short-premium returns
via whipsaw. An underlying trigger only fires on a genuine stock breakdown. The trade-off:
fewer false exits but a larger loss when it does fire. (Configurable so you can A/B.)

**Safety.** Connects to **port 4001 (live)** because that's where positions are. The tool never
transmits unless you set `MODE='live'` *and* type `YES`.

---

## 8. Reporting & delivery

- **`notify.py`** — sends Telegram messages via the free Bot API. Credentials come from env
  vars `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (GitHub Actions secrets) or
  `telegram_config.json` (local). Splits long messages under Telegram's 4096-char limit and
  HTML-escapes monospace tables.
- **`daily_report.py`** — reads `screener_output.csv` (+ `monitor_output.csv`,
  `roll_suggestions.csv`, `covered_calls.csv` if present) and sends a **phone-friendly** digest:
  monitor actions + exposure, rolls (several DTEs), **call-write suggestions**, and the screener
  (top-5 tickers × top-3 contracts + best-per-sleeve). Decoupled from the other scripts (reads
  their CSVs, skipping any that are absent), so it behaves identically on PC and cloud.
  - **Compact layout** — wide tables were replaced with one-line-per-item rows (sleeve names
    abbreviated, earnings as M/D, deltas without the leading zero) so nothing wraps on a phone.
  - **CSV attachments** — after the text digest, `notify.send_document()` uploads the full CSVs
    as Telegram file attachments (open them in any spreadsheet app — no screen-width limits).
    Toggle with `report.attach_csv` (default `true`). The cloud run attaches the screener CSV;
    the monitor/roll/call-write CSVs attach only on PC runs (they need Gateway to be produced).

---

## 9. Automation

### 9.1 Cloud — GitHub Actions (screener only, PC-free)
`.github/workflows/screener.yml` runs on a weekday cron (UTC): checkout → install deps → run
`screener.py` → run `daily_report.py` with the Telegram secrets. The screener is yfinance-only,
so it runs with no PC and no Gateway. **Lite vs full:** without the PC's IBKR files the cloud
run degrades gracefully (IV Rank falls back to the yfinance snapshot series, diversification
off, fallback account size). Commit `data/iv_history.csv` from the weekly PC updater to give
the cloud IBKR-grade IV Rank.

### 9.2 PC — Windows Task Scheduler (full digest)
`run_daily.bat` runs monitor → screener → report (the **full** digest incl. live positions and
exposure). `run_weekly.bat` refreshes IBKR IV. Schedule:
```
schtasks /Create /TN "OptionsDailyReport" /TR "C:\ibkr_screener\run_daily.bat" /SC DAILY /ST 08:00
schtasks /Create /TN "OptionsWeeklyIV"  /TR "C:\ibkr_screener\run_weekly.bat" /SC WEEKLY /D SUN /ST 17:00
```
`monitor.py` is fault-tolerant: if Gateway is down it skips the monitor section rather than
crashing, so the screener/report still run. Both batch files now tee their full output (incl. the
call-write / coverage diagnostics) to `logs\daily.log` / `logs\weekly.log` and echo it to the
console, so scheduled runs are reviewable after the fact.

### 9.3 IBKR login reality
A fully unattended login is not possible (2FA). The standard pattern: run **IB Gateway with
Auto Restart** (Configure → Lock and Exit), log in **once** (2FA), and it stays up for days;
IBKR forces a fresh 2FA login roughly **weekly** — the one recurring manual touch. The
scheduled jobs just connect to the already-running Gateway. (Fuller automation = the community
**IBC** tool; truly unattended = Phase-2 cloud VM with headless Gateway.)

---

## 10. Key discussions & decision points

| # | Decision | Outcome & reasoning |
|---|---|---|
| 1 | Options data source | **yfinance + Black-Scholes** (IBKR options data is paid). Keeps the screener Gateway-free. |
| 2 | IV Rank source | **Option A** — separate IBKR updater writes a full-year IV series; screener reads it. Single-source consistency (never mix IBKR + yf in one rank). |
| 3 | Fundamentals | **Gate, not score** — premium shouldn't buy past quality; per-row percentile skew. |
| 4 | Regime filter | Evolved: hard 200-MA → confirmed-downtrend → **breakdown gate** (steep drop OR vol spike). It's the *steepness* of the move that matters, not the price level — a calm base at a low passes. |
| 5 | Weekend OI wipeout | `ALLOW_MISSING_OI` — 0/NaN OI is a closed-market artifact, not illiquidity. |
| 6 | Diversification | **Score vs current holdings** (gradual book) **+ per-sleeve view** (forces representation). Absolute, not percentile. |
| 7 | Negative correlation | Only real via **cross-asset ETFs** (bonds/gold); equities cluster toward +1 in selloffs. |
| 8 | Exposure metric | **Max loss at the −X% stop** (`strike × X% × 100 × qty`), shown as % of NLV — not collateral. |
| 9 | Account size | Pull **IBKR NetLiquidation** (monitor → `account.json`); hardcode is fallback. |
| 10 | Stop basis | **Underlying** trigger (immune to option-quote noise) over option-price stop; configurable. |
| 11 | Stop level | `STOP_DROP` tuned 15% → 10% → **7%**, decoupled from the 15% sizing assumption. |
| 12 | Rolls | Reuse the **screener scoring** on the same ticker's later expiries; **best per expiry across several DTEs** + net credit. |
| 13 | Delivery / host | **Telegram** (free) + **GitHub Actions** (cloud screener) and **Task Scheduler** (PC full digest). |
| 14 | Call-writes | **Covered-call / roll-up suggestions** on held shares & long calls: option-edge + resistance + capped 3-month-high bonus, conservative 0.15–0.25Δ. Coverage toggle nets out calls already written. |
| 15 | Earnings dates | Surfaced as an `earnings` column (screener + monitor), shown as **M/D** in console and Telegram. |
| 16 | CSV to phone | `daily_report` also **attaches the full CSVs** to Telegram (`sendDocument`) so detail is openable on the phone without screen-width limits. |
| 17 | Universe | Expanded S&P 100 → + Dow & Nasdaq-100 names (liquid, optioned); ~149 equities + 9 ETFs. |
| 18 | Fundamentals scored | Added a **4th bucket — FCF yield + ROE** (weight 0.30) per Goldman's *Art of Put Selling* (high FCF yield = margin of safety, +250bps/yr historically). Fundamentals remain a gate too. |
| 19 | Live-quote gate | `require_quote` (default on): a contract needs a real **bid & ask** — no-bid puts aren't sellable and their IV would come from a stale last price. |
| 20 | Dividend watchlist | Ungated `dividends.csv` — top dividend *stocks* by yield, captured before the gates (high yielders surface even when not tradable). Fixed a 100× yield bug. |

## 11. Field glossary (output columns)

**Screener (`screener_output.csv` / console)**

| Field | Meaning |
|---|---|
| `ticker`, `type` | Underlying; `P` = put |
| `stock_price` | Underlying spot |
| `otm_%` | Downside cushion to strike = `(price−strike)/price×100` (positive = OTM) |
| `expiry`, `dte` | Expiration date; days to expiry |
| `earnings` | Next earnings date (shown as M/D in displays); blank for ETFs |
| `strike`, `mid` | Strike; option mid price |
| `spread_pct` | Bid-ask spread as % of mid (None when no two-sided quote) |
| `open_int`, `volume` | Option open interest / day volume |
| `delta`, `theta` | Black-Scholes greeks (put delta negative) |
| `iv_pct`, `hv_pct` | Option implied vol; underlying realized vol (annualized, %) |
| `iv_hv` | IV ÷ HV (the richness ratio; >1 = rich) |
| `iv_rank`, `iv_src` | Per-ticker IV Rank 0–100; source (`ibkr`/`yf`) |
| `ann_ret_pct` | Annualized return on collateral, % |
| `lots` | Recommended contracts under the 3%/15% sizing |
| `div_corr` | Avg correlation to current holdings (−1..+1) |
| `fcf_yield` (shown `fcf_yield%`) | Free cash flow ÷ market cap, % (fundamentals-bucket input) |
| `score_option`/`score_technical`/`score_diversify`/`score_fundamental` | Bucket scores 0–100 |
| `score` | Weighted composite (the ranking key) |
| `sleeve` | Diversification sleeve (asset class / sector) |

*Excel "Screener" tab note:* the workbook reorders/renames these for readability (drops `etf`,
shortens `sleeve`, `_pct`→`%`, rounds delta/theta) — the CSV keeps the raw names above.

**Monitor (`monitor_output.csv`)**

| Field | Meaning |
|---|---|
| `combo` | `COMBO` if part of a multi-leg group |
| `earnings` | Next earnings date (M/D) |
| `stock`, `money` | Underlying spot; ITM/ATM/OTM |
| `div_yield` | Underlying dividend yield (%) |
| `qty`, `entry`, `current` | Contracts (− short); entry & current option price |
| `pnl_%` | Position P&L (% of credit) |
| `collateral` | Cash-secured collateral (short puts): `strike×100×|qty|` |
| `exposure` | Max loss at the stop (short puts): `strike×0.15×100×|qty|` |
| `action`, `reason` | CLOSE / ROLL? / HOLD and why |

**Dividend watchlist (`dividends.csv`)** — top dividend-paying *stocks* across the whole scan,
**ungated** (captured before the gates), ranked by yield: `ticker`, `div_yield` (%), `stock_price`,
`sector`. Surfaces high-yield names even when they're not currently tradable.

**Roll suggestions (`roll_suggestions.csv`)** — `pos_*` describe the position being rolled;
`roll_*` the candidate (now one per expiry across several DTEs); `net_credit` = new mid −
buyback; plus the candidate's score.

**Call-writes (`covered_calls.csv`)**

| Field | Meaning |
|---|---|
| `basis` | `shares` (true covered call) or `long call` (roll-up / spread) |
| `lots` | Writable lots (net of calls already written, unless coverage off) |
| `strike`, `otm_%`, `mid`, `delta` | Call strike; % OTM; mid; call delta (0.15–0.25 band) |
| `iv_rank`, `iv_hv`, `ann_ret_pct` | Option-edge inputs (premium yield is on the shares) |
| `income` | `mid × 100 × lots` (premium collected) |
| `resist_cushion_%` | Strike vs near-term resistance (20-day band/swing high); + = above |
| `high_3m`, `strike_vs_3mhigh_%` | The ~3-month high and the strike's distance to it |
| `score_option`/`score_resist`/`long_bonus`/`score` | Bucket scores, capped 3-mo bonus, composite |

---

## 12. Configuration reference

**`config.json` (edit here, not the code).** The tunable settings live in a single
repo-tracked `config.json` that `screener.py` loads at startup and that `monitor.py` and
`place_stops.py` read via the screener. Editing it changes behaviour without touching code, and
because it's committed, the **cloud (GitHub Actions) and your PC run identical settings**. Sections:
`weights` (option/technical/diversify/**fundamental**), `gates` (DTE, delta, spread, OI,
**require_quote**, ROE, growth, P/E), `regime` (mode, drop_window, drop_pct, vol_fast, vol_slow,
vol_ratio, vol_abs), `oversold` (z_threshold, bonus), `report` (top_tickers, per_ticker,
**top_dividends**, attach_csv), `sizing`
(account_size_fallback, max_risk_pct, assumed_drawdown), `monitor` (profit_target_pct,
hard_close_dte, near_atm_buffer, roll_top_n), **`covered_calls`** (delta_min, delta_max,
w_option, w_resist, resist_window, long_high_days, long_high_bonus, near_high_pct, top_n,
respect_coverage), `stops` (basis, drop, credit_mult). Any key missing from the file falls back
to the code default. After editing: `git add config.json && git commit && git push`.

**`screener.py`** (code defaults, overridden by config.json)

| Constant | Default | Meaning |
|---|---|---|
| `TICKERS` | SP100 + ETFS | Universe |
| `MIN_DTE`/`MAX_DTE` | 15 / 60 | DTE gate |
| `DELTA_MIN`/`DELTA_MAX` | 0.15 / 0.30 | Delta gate |
| `STRIKE_PCT_LOW/HIGH` | 0.75 / 1.02 | Strike scan range |
| `MAX_SPREAD_PCT` | 0.10 | Liquidity (spread) gate |
| `MIN_OPEN_INTEREST` | 100 | Liquidity (OI) gate |
| `ALLOW_MISSING_OI` | True | Let 0/NaN OI through (weekends) |
| `REQUIRE_QUOTE` | True | Require a live bid & ask (no stale-last IV; sellable) |
| `REGIME_MODE` | `'breakdown'` | Regime gate mode (`breakdown`/`gate`/`off`) |
| `DROP_WINDOW`/`DROP_PCT` | 10 / 0.15 | Steep-drop test: peak→now fall over N days |
| `VOL_FAST`/`VOL_SLOW`/`VOL_RATIO`/`VOL_ABS` | 10 / 63 / 1.8 / 0.50 | Vol-spike test (fast vs baseline realized vol) |
| `REQUIRE_SOLVENCY`/`REQUIRE_FUNDAMENTALS` | True | Quality gates |
| `MIN_ROE`/`MIN_REV_GROWTH`/`MAX_FORWARD_PE` | 0.08 / 0.0 / 60 | Fundamental thresholds |
| `W_OPTION`/`W_TECHNICAL`/`W_DIVERSIFY`/`W_FUNDAMENTAL` | 0.40/0.40/0.20/0.30 | Composite weights (4 buckets) |
| `CORR_LOOKBACK_DAYS` | 126 | Correlation window |
| `ACCOUNT_SIZE` | 700000 (fallback) | Overridden by `account.json` |
| `MAX_RISK_PCT`/`ASSUMED_DRAWDOWN` | 0.03 / 0.15 | Sizing risk model |

**`place_stops.py`**: `MODE` (advisory/live), `STOP_BASIS`, `STOP_DROP` (0.07), `CREDIT_MULT`
(2.5), `PORT` (4001). **`monitor.py`**: `PROFIT_TARGET_PCT` (0.70), `HARD_CLOSE_DTE` (21),
`NEAR_ATM_BUFFER` (0.03), `ROLL_TOP_N` (3); **call-writes** `CC_DELTA_MIN/MAX` (0.15/0.25),
`CC_W_OPTION/CC_W_RESIST` (0.6/0.4), `CC_RESIST_WIN` (20), `CC_LONG_DAYS` (63),
`CC_LONG_BONUS` (6), `CC_NEAR_HIGH` (0.03), `CC_TOP_N` (3), `CC_RESPECT_COVER` (False).
**`daily_report.py`**: `ATTACH_CSV` (True). **`update_iv_history.py`**: `PORT`, `CLIENT_ID`,
`IBKR_SYMBOL` map. **client IDs**: 1=test, 2=screener(reserved), 3=monitor, 4=updater,
5=iv-test, 6=stops.

---

## 13. How to use

### 13.1 First-time setup
1. Python 3.13 venv at `C:\ibkr_screener\venv`; `pip install -r requirements.txt` (plus
   `ib_insync` for the IBKR scripts).
2. IB Gateway installed; log in; enable **Auto Restart**. Live port 4001, paper 4002.
3. Telegram: create a bot via **@BotFather**, get the token; get your chat id via
   **@userinfobot**; put both in `telegram_config.json`.
4. `venv\Scripts\python.exe code\notify.py` → confirm a test message arrives.

### 13.2 Daily workflow (PC)
```
venv\Scripts\python.exe code\monitor.py        # positions, flags, exposure, NLV, rolls
venv\Scripts\python.exe code\screener.py       # ranked candidates
venv\Scripts\python.exe code\daily_report.py   # Telegram digest
venv\Scripts\python.exe code\place_stops.py    # (advisory) review stops; flip MODE='live' to place
```
or just schedule `run_daily.bat`. Weekly: `update_iv_history.py` (or `run_weekly.bat`).

### 13.2a Command reference (every script)
Run all commands from the project root `C:\ibkr_screener`. On the PC, always use the
venv interpreter (`venv\Scripts\python.exe`) — plain `python` or `py -3.13` skips the venv
and won't have `ib_insync`. Scripts that talk to IBKR (monitor, place_stops,
update_iv_history) need **IB Gateway running and logged in**; the rest are yfinance-only.

| What you want to do | Command | Needs IB Gateway? | Writes |
|---|---|---|---|
| Open `cmd` in the folder | `cd C:\ibkr_screener` | — | — |
| One-time: install deps | `venv\Scripts\python.exe -m pip install -r requirements.txt` | No | — |
| Test Telegram is wired up | `venv\Scripts\python.exe code\notify.py` | No | sends a test msg |
| Check positions, P&L, exposure, rolls | `venv\Scripts\python.exe code\monitor.py` | **Yes** | `monitor_output.csv`, `roll_suggestions.csv`, `data\account.json` |
| Find & rank candidates | `venv\Scripts\python.exe code\screener.py` | No | `screener_output.csv` |
| Build + send the Telegram digest | `venv\Scripts\python.exe code\daily_report.py` | No | sends Telegram |
| Review stop orders (advisory) | `venv\Scripts\python.exe code\place_stops.py` | **Yes** | nothing (prints) |
| Actually place the stops | set `MODE='live'` in `place_stops.py`, then run it and type **YES** | **Yes** | resting GTC orders |
| Refresh IV/HV history (weekly) | `venv\Scripts\python.exe code\update_iv_history.py` | **Yes** | `data\iv_history.csv` |
| Run the whole daily flow | `run_daily.bat` | for monitor/stops | all of the above |
| Run the weekly IV refresh | `run_weekly.bat` | **Yes** | `data\iv_history.csv` |

Typical morning, copy-paste:
```
cd C:\ibkr_screener
venv\Scripts\python.exe code\monitor.py
venv\Scripts\python.exe code\screener.py
venv\Scripts\python.exe code\daily_report.py
```

Notes:
- **Order matters for the report.** `daily_report.py` reads the CSVs produced by
  `screener.py` (and, if present, `monitor.py`), so run those first. On its own it just
  reports whatever CSVs already exist.
- **PowerShell vs cmd.** Both work. In PowerShell you can also write
  `.\venv\Scripts\python.exe code\screener.py`.
- **The cloud copy runs itself.** GitHub Actions runs `screener.py` then `daily_report.py`
  on a schedule (see §14) — no commands needed there. You only run the IBKR scripts
  (monitor / place_stops / update_iv_history) locally, since those need Gateway.

### 13.2b Sleeve abbreviations (Telegram "Best per sleeve" line)
To keep the per-sleeve diversification line on one phone line, sleeve names are shortened to
5-6 letters. The line shows: `SLEEVE TICKER strikeP dte Δdelta yield% score`.

**ETF / asset-class sleeves**

| Full | Abbr |
|---|---|
| Equity Index | `EQIDX` |
| Intl Equity | `INTLEQ` |
| Bonds | `BONDS` |
| Commodity | `COMMOD` |
| REIT | `REIT` |
| Energy | `ENERGY` |
| Financials | `FINANC` |
| generic ETF | `ETF` |

**Equity sector sleeves (from yfinance)**

| Full | Abbr |
|---|---|
| Technology | `TECH` |
| Financial Services | `FINSVC` |
| Healthcare | `HEALTH` |
| Consumer Cyclical | `CONCYC` |
| Consumer Defensive | `CONDEF` |
| Communication Services | `COMMS` |
| Industrials | `INDUS` |
| Utilities | `UTILS` |
| Real Estate | `RLEST` |
| Basic Materials | `MATER` |
| generic Equity | `EQUITY` |

The map lives in `daily_report.py` (`SLEEVE_ABBR`); add a row there if a new sleeve appears.

### 13.3 Going live on stops
Edit `place_stops.py`, set `MODE='live'`, run, review the table, type **YES**. Verify resting
GTC orders in TWS → Orders. Set back to `'advisory'` for routine re-runs.

---

## 14. GitHub (cloud automation)

### 14.1 One-time
1. Install Git; create a GitHub account; create an empty repo (e.g. `OptionScreener`).
2. From the project folder:
   ```
   git init
   git add .
   git commit -m "options screener"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
3. Repo → **Settings → Secrets and variables → Actions** → add `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID`.
4. **Actions** tab → enable → **Daily Options Screener** → **Run workflow** to test.

### 14.2 What runs & secrets
The workflow (`.github/workflows/screener.yml`) runs the screener + report on a weekday cron
in a throwaway Linux VM; the Telegram secrets are injected only at run time and never logged.
`.gitignore` keeps `telegram_config.json` and `data/account.json` out of the repo — in the
cloud, credentials come from Secrets. Verify nothing secret was pushed:
`git ls-files | findstr telegram` should print nothing.

### 14.3 Keeping the cloud "full"
Commit `data/iv_history.csv` after the weekly PC updater so the cloud screener uses IBKR IV
Rank rather than the lite yfinance series. (Monitor-dependent sections — live positions,
exposure — only appear in the PC digest, since the cloud can't reach IB Gateway.)

---

## 15. Known limitations & future work
- **Rolls/stops cover short puts only** — calls (covered calls) and combos are skipped; handle
  deliberately for now.
- **Performance** — ~110 tickers via yfinance is sequential and can be slow / rate-limited; a
  liquidity/market-cap pre-filter + caching/parallelism is the next scaling step.
- **Cloud is screener-only** — monitor/stops need IB Gateway. Phase 2: a cloud VM running
  headless Gateway (IBC + weekly 2FA) for fully PC-free management.
- **Diversification score is near-uniform** when correlations are all positive (current
  regime); the per-sleeve view carries the real diversification.
- **Tooling, not advice** — sizing/stops are mechanical aids; you own every order. Nothing
  here is investment advice.

---

## Appendix — raw source code

*(Embedded below: `screener.py`, `update_iv_history.py`, `monitor.py`, `place_stops.py`,
`notify.py`, `daily_report.py`, `.github/workflows/screener.yml`, `requirements.txt`,
`.gitignore`. These are snapshots — the live files in the repo are authoritative. Note: this
embedded copy predates the breakdown regime gate, call-write suggestions, earnings column, and
CSV-attachment changes documented in §5–§12 above; read the repo for current source.)*


### screener.py

```python
"""
IBKR Put Selling Screener — Phase 1 (spec-aligned)
Data:    yfinance (free) for live option chains + Black-Scholes greeks
IV Rank: IBKR historical implied vol (preferred) via update_iv_history.py,
         falling back to a self-built yfinance snapshot series.
Logic:   gates prune the universe -> weighted composite score ranks survivors
Output:  console + screener_output.csv
Spec:    docs/screening_spec.md  |  Gaps closed: docs/screener_gap_analysis.md

Fundamentals are a GATE (quality screen), not a score. ETFs bypass the
fundamentals/solvency/earnings gates (no financials). Ranking = option edge +
technicals + diversification (correlation vs current holdings). A position
sizer recommends lots under a per-trade risk cap.
"""

import os
import warnings
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import brentq
from scipy.stats import norm

warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
# Equity universe: S&P 100 (as of 2025-09; review periodically). yfinance uses
# '-' not '.' for share classes (BRK-B). Quality/liquidity is high across the set.
SP100 = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMD', 'AMGN', 'AMT', 'AMZN',
    'AVGO', 'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C',
    'CAT', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DUK', 'EMR', 'FDX', 'GD', 'GE', 'GILD', 'GM',
    'GOOG', 'GOOGL', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU', 'ISRG', 'JNJ',
    'JPM', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD', 'MDLZ', 'MDT',
    'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE', 'NFLX', 'NKE',
    'NOW', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PLTR', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UBER', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WFC', 'WMT', 'XOM',
]
# Cross-asset ETFs (bypass the fundamentals/earnings gates).
ETFS = ['SPY', 'QQQ', 'IWM', 'TLT', 'IEF', 'HYG', 'GLD', 'SLV', 'VNQ']
TICKERS = SP100 + ETFS
ETF_TICKERS = {'SPY', 'QQQ', 'IWM', 'DIA', 'TLT', 'IEF', 'SHY', 'LQD', 'HYG', 'AGG',
               'GLD', 'SLV', 'DBC', 'USO', 'VNQ', 'IYR', 'EEM', 'EFA', 'XLE', 'XLF'}

# Map ETFs to a diversification "sleeve"; equities use their yfinance sector.
ETF_SLEEVE = {
    'SPY': 'Equity Index', 'QQQ': 'Equity Index', 'IWM': 'Equity Index', 'DIA': 'Equity Index',
    'TLT': 'Bonds', 'IEF': 'Bonds', 'SHY': 'Bonds', 'AGG': 'Bonds', 'LQD': 'Bonds', 'HYG': 'Bonds',
    'GLD': 'Commodity', 'SLV': 'Commodity', 'DBC': 'Commodity', 'USO': 'Commodity',
    'VNQ': 'REIT', 'IYR': 'REIT', 'EEM': 'Intl Equity', 'EFA': 'Intl Equity',
    'XLE': 'Energy', 'XLF': 'Financials',
}
PER_SLEEVE_TOP = 2   # best-N candidates shown per sleeve in the diversification view

MIN_DTE   = 15
MAX_DTE   = 60
DELTA_MIN = 0.15
DELTA_MAX = 0.30
STRIKE_PCT_LOW  = 0.75
STRIKE_PCT_HIGH = 1.02
RISK_FREE = 0.045

MAX_SPREAD_PCT     = 0.10
MIN_OPEN_INTEREST  = 100   # require some resting liquidity (when OI data is present)
ALLOW_MISSING_OI   = True   # weekends/pre-data: don't reject when OI is unavailable (0/NaN)
MA_REGIME_WINDOW   = 200
# Regime handling — how the 200-MA is used:
#   'gate'       : hard reject if price < 200-MA
#   'downtrend'  : reject ONLY confirmed downtrends (below 50 & 200-MA + 200-MA
#                  falling + near 50-day low). Lets healthy sideways names through.
#   'score'/'off': no regime gate
REGIME_MODE        = 'downtrend'
DOWNTREND_SLOPE    = -0.02
NEAR_LOW_PCT       = 0.03
REQUIRE_SOLVENCY   = True

# Fundamental quality GATE (equities only; ETFs bypass). Missing data never rejects.
REQUIRE_FUNDAMENTALS = True
REQUIRE_FCF_POSITIVE = True
MIN_ROE              = 0.08
MIN_REV_GROWTH       = 0.0
MAX_FORWARD_PE       = 60

# Composite weights (fundamentals are a gate, not scored). Must sum to 1.0.
W_OPTION      = 0.55
W_TECHNICAL   = 0.25
W_DIVERSIFY   = 0.20

# Diversification — score each candidate by correlation to CURRENT holdings.
# Holdings are read from monitor_output.csv (keeps screener Gateway-free).
HOLDINGS_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'monitor_output.csv')
CORR_LOOKBACK_DAYS = 126   # ~6 months of daily returns

# Position sizing — assignment + drawdown basis.
# risk/contract ≈ strike*100*ASSUMED_DRAWDOWN ; lots = (ACCOUNT*MAX_RISK_PCT)/risk
ACCOUNT_SIZE     = 700_000   # fallback only; auto-overridden by data/account.json
                             # (monitor.py writes IBKR NetLiquidation there)
MAX_RISK_PCT     = 0.03      # max risk per position as % of account
ASSUMED_DRAWDOWN = 0.15      # -X% rule: adverse move below strike where you'd exit (sizing + monitor exposure)

PROFIT_TARGET_PCT = 0.70
HARD_CLOSE_DTE    = 21

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IV_HISTORY_PATH = os.path.join(_SCRIPT_DIR, 'data', 'iv_history.csv')
ACCOUNT_FILE = os.path.join(_SCRIPT_DIR, 'data', 'account.json')   # written by monitor.py
IV_RANK_LOOKBACK = 252
IV_HISTORY_COLS = ['date', 'ticker', 'iv', 'hv', 'source']
# ─────────────────────────────────────────────────────────────────────────────


# ── Black-Scholes ─────────────────────────────────────────────────────────────

def bs_put_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(market_price, S, K, T, r):
    if T <= 0 or not market_price or market_price <= 0:
        return None
    if market_price < max(K - S, 0.0) * 0.99:
        return None
    try:
        return brentq(
            lambda sig: bs_put_price(S, K, T, r, sig) - market_price,
            1e-4, 5.0, xtol=1e-5, maxiter=200
        )
    except (ValueError, RuntimeError):
        return None


def bs_put_greeks(S, K, T, r, iv):
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (np.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    delta = norm.cdf(d1) - 1.0
    theta = (-(S * norm.pdf(d1) * iv) / (2 * np.sqrt(T))
             + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
    return delta, theta

# ─────────────────────────────────────────────────────────────────────────────


def get_next_earnings(yf_t):
    try:
        cal = yf_t.calendar
        if not cal:
            return None
        earn_dates = []
        if isinstance(cal, dict):
            raw = cal.get('Earnings Date', [])
            earn_dates = list(raw) if hasattr(raw, '__iter__') and not isinstance(raw, str) else [raw]
        elif hasattr(cal, 'loc') and 'Earnings Date' in cal.index:
            earn_dates = list(cal.loc['Earnings Date'])
        today = date.today()
        for ed in earn_dates:
            d = ed.date() if hasattr(ed, 'date') else (
                date.fromisoformat(str(ed)[:10]) if ed else None)
            if d and d >= today:
                return d
    except Exception:
        pass
    return None


def get_price(yf_t):
    try:
        p = yf_t.fast_info.last_price or yf_t.fast_info.previous_close
        if p and p > 0:
            return float(p)
    except Exception:
        pass
    try:
        hist = yf_t.history(period='3d')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
    except Exception:
        pass
    return None


# ── Technicals ────────────────────────────────────────────────────────────────

def get_price_history(yf_t):
    try:
        hist = yf_t.history(period='1y')
        return hist if hist is not None and not hist.empty else None
    except Exception:
        return None


def compute_hv(hist, window=30):
    try:
        close = hist['Close'].dropna()
        if len(close) < window + 1:
            return None
        rets = np.log(close / close.shift(1)).dropna()
        hv = rets.tail(window).std() * np.sqrt(252)
        return float(hv) if hv and hv > 0 else None
    except Exception:
        return None


def compute_technicals(hist):
    """50/200-MA (+200-MA slope), RSI(14), Bollinger %B, 20/50-day swing lows."""
    out = {'ma50': None, 'ma200': None, 'ma200_slope': None, 'rsi': None,
           'bb_pctb': None, 'swing_low_20': None, 'swing_low_50': None}
    try:
        close = hist['Close'].dropna()
        low = hist['Low'].dropna() if 'Low' in hist else close
        if len(close) >= 50:
            out['ma50'] = float(close.rolling(50).mean().iloc[-1])
            out['swing_low_50'] = float(low.rolling(50).min().iloc[-1])
        if len(close) >= MA_REGIME_WINDOW:
            ma200s = close.rolling(MA_REGIME_WINDOW).mean()
            out['ma200'] = float(ma200s.iloc[-1])
            if len(ma200s.dropna()) > 21:
                prev = ma200s.iloc[-21]
                if prev and prev > 0:
                    out['ma200_slope'] = float((ma200s.iloc[-1] - prev) / prev)
        if len(close) >= 20:
            out['swing_low_20'] = float(low.rolling(20).min().iloc[-1])
            mid = close.rolling(20).mean().iloc[-1]
            sd = close.rolling(20).std().iloc[-1]
            if sd and sd > 0:
                upper, lower = mid + 2 * sd, mid - 2 * sd
                out['bb_pctb'] = float((close.iloc[-1] - lower) / (upper - lower))
        if len(close) >= 15:
            diff = close.diff()
            gain = diff.clip(lower=0).rolling(14).mean().iloc[-1]
            loss = (-diff.clip(upper=0)).rolling(14).mean().iloc[-1]
            if loss and loss > 0:
                rs = gain / loss
                out['rsi'] = float(100 - 100 / (1 + rs))
            elif gain and gain > 0:
                out['rsi'] = 100.0
    except Exception:
        pass
    return out


def regime_block(price, tech):
    """Whether to skip a ticker on trend grounds, per REGIME_MODE. -> (bool, reason)."""
    ma200 = tech.get('ma200')
    if REGIME_MODE in ('score', 'off') or ma200 is None:
        return False, ''
    if REGIME_MODE == 'gate':
        return (price < ma200), f"price ${price:.2f} < 200-MA ${ma200:.2f}"
    ma50  = tech.get('ma50')
    slope = tech.get('ma200_slope')
    low50 = tech.get('swing_low_50')
    below   = price < ma200 and (ma50 is not None and price < ma50)
    falling = slope is not None and slope < DOWNTREND_SLOPE
    near_lo = low50 is not None and price <= low50 * (1 + NEAR_LOW_PCT)
    if below and falling and near_lo:
        return True, "confirmed downtrend (below 50 & 200-MA, 200-MA falling, near 50-day low)"
    return False, ''


# ── Fundamentals ──────────────────────────────────────────────────────────────

def get_fundamentals(yf_t):
    f = {'forward_pe': None, 'peg': None, 'roe': None, 'rev_growth': None,
         'div_yield': None, 'payout': None, 'debt_to_equity': None,
         'current_ratio': None, 'fcf': None, 'quote_type': None, 'sector': None}
    try:
        info = yf_t.info or {}
        f['sector']         = info.get('sector')
        f['forward_pe']     = info.get('forwardPE')
        f['peg']            = info.get('pegRatio') or info.get('trailingPegRatio')
        f['roe']            = info.get('returnOnEquity')
        f['rev_growth']     = info.get('revenueGrowth')
        f['div_yield']      = info.get('dividendYield')
        f['payout']         = info.get('payoutRatio')
        f['debt_to_equity'] = info.get('debtToEquity')
        f['current_ratio']  = info.get('currentRatio')
        f['fcf']            = info.get('freeCashflow')
        f['quote_type']     = info.get('quoteType')
    except Exception:
        pass
    return f


def is_etf(ticker, fund):
    return (fund.get('quote_type') or '').upper() == 'ETF' or ticker in ETF_TICKERS


def sleeve(ticker, fund):
    """Diversification sleeve: ETFs by asset-class map, equities by yfinance sector."""
    if is_etf(ticker, fund):
        return ETF_SLEEVE.get(ticker, 'ETF')
    return fund.get('sector') or 'Equity'


def solvency_ok(f):
    de = f.get('debt_to_equity')
    cr = f.get('current_ratio')
    fcf = f.get('fcf')
    distressed = False
    if de is not None and de > 400:
        if (cr is not None and cr < 1.0) or (fcf is not None and fcf < 0):
            distressed = True
    if fcf is not None and fcf < 0 and de is not None and de > 250:
        distressed = True
    return not distressed


def fundamental_ok(f):
    """Quality GATE -> (bool, reason). Only fails on PRESENT metrics below the bar."""
    fcf = f.get('fcf')
    rg  = f.get('rev_growth')
    roe = f.get('roe')
    pe  = f.get('forward_pe')
    if REQUIRE_FCF_POSITIVE and fcf is not None and fcf <= 0:
        return False, "FCF <= 0"
    if rg is not None and rg < MIN_REV_GROWTH:
        return False, f"revenue growth {rg:.1%} < {MIN_REV_GROWTH:.0%}"
    if roe is not None and roe < MIN_ROE:
        return False, f"ROE {roe:.1%} < {MIN_ROE:.0%}"
    if pe is not None and pe > MAX_FORWARD_PE:
        return False, f"forward P/E {pe:.0f} > {MAX_FORWARD_PE}"
    return True, ""


# ── Diversification (correlation vs current holdings) ──────────────────────────

def load_holdings(path=HOLDINGS_PATH):
    """Unique underlying tickers from monitor_output.csv (current positions)."""
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_csv(path)
        col = 'ticker' if 'ticker' in df.columns else df.columns[0]
        return sorted(df[col].dropna().astype(str).str.upper().unique().tolist())
    except Exception:
        return []


def fetch_returns(tickers, lookback_days=CORR_LOOKBACK_DAYS):
    """ticker -> daily-return Series (last ~6 months). Skips anything that fails."""
    out = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period='1y')
            if h is not None and not h.empty:
                r = h['Close'].pct_change().dropna().tail(lookback_days)
                if len(r) > 20:
                    out[t] = r
        except Exception:
            pass
    return out


def diversification_score(cand_ret, holdings_returns):
    """Avg correlation of candidate to current holdings -> 0-100 (lower corr = higher).
    corr -1 -> 100, 0 -> 50, +1 -> 0. None when no usable data."""
    if cand_ret is None or not holdings_returns:
        return None, None
    corrs = []
    for hr in holdings_returns.values():
        try:
            c = cand_ret.corr(hr)
            if c == c:                      # not NaN
                corrs.append(c)
        except Exception:
            pass
    if not corrs:
        return None, None
    avg = float(np.mean(corrs))
    score = float(np.clip((1 - avg) / 2 * 100, 0, 100))
    return round(score, 1), round(avg, 2)


# ── IV history store / IV Rank ────────────────────────────────────────────────

def load_iv_history():
    if not os.path.exists(IV_HISTORY_PATH):
        return None
    try:
        df = pd.read_csv(IV_HISTORY_PATH)
    except Exception:
        return None
    if 'iv' not in df.columns and 'atm_iv' in df.columns:
        df = df.rename(columns={'atm_iv': 'iv'})
    if 'source' not in df.columns:
        df['source'] = 'yf'
    if 'hv' not in df.columns:
        df['hv'] = np.nan
    return df


def record_iv(rows):
    if not rows:
        return
    today = str(date.today())
    new = pd.DataFrame([{'date': today, 'ticker': r['ticker'],
                         'iv': r['iv'], 'hv': r.get('hv'), 'source': 'yf'}
                        for r in rows])
    if os.path.exists(IV_HISTORY_PATH):
        old = load_iv_history()
        if old is not None:
            old = old[~((old['date'] == today) & (old['source'] == 'yf')
                        & (old['ticker'].isin(new['ticker'])))]
            new = pd.concat([old, new], ignore_index=True)
    os.makedirs(os.path.dirname(IV_HISTORY_PATH), exist_ok=True)
    new = new[[c for c in IV_HISTORY_COLS if c in new.columns]]
    new.to_csv(IV_HISTORY_PATH, index=False)


def ticker_iv_rank(hist_df, ticker):
    if hist_df is None:
        return None, None, None, None
    sub = hist_df[hist_df['ticker'] == ticker]
    for src in ('ibkr', 'yf'):
        s = (sub[sub['source'] == src].dropna(subset=['iv'])
             .sort_values('date').tail(IV_RANK_LOOKBACK))
        if len(s) >= 20:
            iv_vals = s['iv'].astype(float)
            lo, hi = iv_vals.min(), iv_vals.max()
            latest_iv = float(iv_vals.iloc[-1])
            hv_nonan = s['hv'].dropna()
            latest_hv = float(hv_nonan.iloc[-1]) if not hv_nonan.empty else None
            rank = (float(np.clip((latest_iv - lo) / (hi - lo) * 100, 0, 100))
                    if hi > lo else None)
            return rank, src, latest_iv, latest_hv
    return None, None, None, None


def latest_ibkr_hv(hist_df, ticker):
    if hist_df is None:
        return None
    sub = hist_df[(hist_df['ticker'] == ticker) & (hist_df['source'] == 'ibkr')].dropna(subset=['hv'])
    if sub.empty:
        return None
    try:
        return float(sub.sort_values('date')['hv'].iloc[-1])
    except Exception:
        return None


def annualized_return(premium, strike, dte):
    if not premium or not strike or not dte or dte <= 0:
        return None
    return (premium / strike) / dte * 365 * 100


def get_account_size(default=ACCOUNT_SIZE):
    """Account NetLiquidation from data/account.json (monitor writes it), else fallback."""
    try:
        import json
        with open(ACCOUNT_FILE) as f:
            v = json.load(f).get('net_liquidation')
        return float(v) if v and float(v) > 0 else default
    except Exception:
        return default


def save_account_size(value, account=''):
    """Persist NetLiquidation so the (Gateway-free) screener can size on the real account."""
    try:
        import json
        os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
        with open(ACCOUNT_FILE, 'w') as f:
            json.dump({'net_liquidation': float(value), 'account': account,
                       'asof': str(date.today())}, f)
        return True
    except Exception:
        return False


def position_size(strike, premium):
    """Recommended lots under the per-trade risk cap (assignment+drawdown basis).
    Returns (lots, collateral_per_contract, risk_per_contract)."""
    risk_ct = strike * 100 * ASSUMED_DRAWDOWN
    budget  = ACCOUNT_SIZE * MAX_RISK_PCT
    lots = int(budget // risk_ct) if risk_ct > 0 else 0
    return lots, round(strike * 100), round(risk_ct)


def _num(x, default=0.0):
    """NaN/None-safe float (yfinance puts NaN in volume/OI/bid/ask)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return x if x == x else default


# ── Per-ticker scan ───────────────────────────────────────────────────────────

def screen_ticker(ticker, iv_hist_df, holdings_returns, verbose=True):
    _p = print if verbose else (lambda *a, **k: None)
    today = date.today()
    yf_t  = yf.Ticker(ticker)

    price = get_price(yf_t)
    if not price:
        _p(f"{ticker:<6} SKIP: no price")
        return [], None

    hist = get_price_history(yf_t)
    tech = compute_technicals(hist) if hist is not None else {}
    hv_yf = compute_hv(hist) if hist is not None else None
    fund = get_fundamentals(yf_t)
    etf  = is_etf(ticker, fund)
    sl   = sleeve(ticker, fund)

    ibkr_hv = latest_ibkr_hv(iv_hist_df, ticker)
    hv_used = ibkr_hv if ibkr_hv else hv_yf

    # candidate return series (for diversification) — computed once per ticker
    cand_ret = None
    if hist is not None and len(hist) > 5:
        cand_ret = hist['Close'].pct_change().dropna().tail(CORR_LOOKBACK_DAYS)
    div_score, div_corr = diversification_score(cand_ret, holdings_returns)

    blocked, why = regime_block(price, tech)
    if blocked:
        _p(f"{ticker:<6} ${price:>8.2f} | SKIP regime[{REGIME_MODE}]: {why}")
        return [], None

    # ETFs bypass solvency / fundamentals / earnings gates (no financials)
    if not etf:
        if REQUIRE_SOLVENCY and not solvency_ok(fund):
            _p(f"{ticker:<6} ${price:>8.2f} | SKIP solvency: distressed balance sheet")
            return [], None
        if REQUIRE_FUNDAMENTALS:
            ok, fund_why = fundamental_ok(fund)
            if not ok:
                _p(f"{ticker:<6} ${price:>8.2f} | SKIP fundamentals: {fund_why}")
                return [], None

    earnings = None if etf else get_next_earnings(yf_t)
    hv_str = f"{hv_used:.2f}" if hv_used else "n/a"

    results, atm_iv_tracker, atm_best_dist = [], None, None
    reasons, scanned, exps_used = Counter(), 0, 0

    for exp_str in yf_t.options:
        exp_date = date.fromisoformat(exp_str)
        dte      = (exp_date - today).days
        if not (MIN_DTE <= dte <= MAX_DTE):
            continue
        if earnings and today < earnings <= exp_date:
            reasons['earnings_expiry'] += 1
            continue
        exps_used += 1

        T    = dte / 365.0
        puts = yf_t.option_chain(exp_str).puts

        for _, row in puts.iterrows():
            strike = float(row['strike'])
            if not (price * STRIKE_PCT_LOW <= strike <= price * STRIKE_PCT_HIGH):
                continue
            scanned += 1

            bid  = _num(row.get('bid'))
            ask  = _num(row.get('ask'))
            last = _num(row.get('lastPrice'))
            oi   = int(_num(row.get('openInterest')))
            vol  = int(_num(row.get('volume')))
            opt_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            if opt_price <= 0:
                reasons['no_price'] += 1
                continue

            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2)
                if spread_pct > MAX_SPREAD_PCT:
                    reasons['spread'] += 1
                    continue
            else:
                spread_pct = None
            if oi < MIN_OPEN_INTEREST:
                if ALLOW_MISSING_OI and oi <= 0:
                    reasons['oi_missing_allowed'] += 1
                else:
                    reasons['open_interest'] += 1
                    continue

            iv = implied_vol(opt_price, price, strike, T, RISK_FREE)
            if not iv or iv <= 0:
                reasons['no_iv'] += 1
                continue

            delta, theta = bs_put_greeks(price, strike, T, RISK_FREE, iv)
            if delta is None:
                reasons['no_greeks'] += 1
                continue
            if not (DELTA_MIN <= abs(delta) <= DELTA_MAX):
                reasons['delta_band'] += 1
                continue

            dist = abs(strike - price)
            if atm_best_dist is None or dist < atm_best_dist:
                atm_best_dist, atm_iv_tracker = dist, iv

            iv_hv = (iv / hv_used) if (hv_used and hv_used > 0) else None
            ann_ret = annualized_return(opt_price, strike, dte)
            swing_low = tech.get('swing_low_20')
            support_margin = ((swing_low - strike) / price) if swing_low else None
            lots, collat_ct, risk_ct = position_size(strike, opt_price)
            otm_pct = round((price - strike) / price * 100, 1)     # downside cushion to strike

            results.append({
                'ticker':      ticker,
                'etf':         etf,
                'sleeve':      sl,
                'type':        'P',
                'stock_price': round(price, 2),
                'otm_%':       otm_pct,
                'expiry':      exp_date.strftime('%Y-%m-%d'),
                'dte':         dte,
                'strike':      strike,
                'mid':         round(opt_price, 2),
                'spread_pct':  round(spread_pct * 100, 1) if spread_pct is not None else None,
                'open_int':    oi,
                'volume':      vol,
                'delta':       round(delta, 3),
                'theta':       round(theta, 4),
                'iv_pct':      round(iv * 100, 1),
                'hv_pct':      round(hv_used * 100, 1) if hv_used else None,
                'iv_hv':       round(iv_hv, 2) if iv_hv else None,
                'ann_ret_pct': round(ann_ret, 1) if ann_ret else None,
                'lots':        lots,
                'collat_ct':   collat_ct,
                'risk_ct':     risk_ct,
                'income':      round(opt_price * 100 * lots),
                'div_corr':    div_corr,
                'div_score':   div_score,
                'fwd_pe':      round(fund['forward_pe'], 1) if fund.get('forward_pe') else None,
                'roe':         round(fund['roe'], 3) if fund.get('roe') else None,
                '_rsi':        tech.get('rsi'),
                '_bb_pctb':    tech.get('bb_pctb'),
                '_support_margin': support_margin,
                'div_yield':   round(fund['div_yield'] * 100, 2) if fund.get('div_yield') else None,
            })

    tag = ' ETF' if etf else ''
    earn_str = str(earnings) if earnings else ('—' if etf else 'n/a')
    div_str = f"div {div_score:.0f}(corr {div_corr:+.2f})" if div_score is not None else "div n/a"
    summary = (f"{ticker:<6}{tag:<4} ${price:>8.2f} | earn {earn_str} | "
               f"HV {hv_str}{'(ibkr)' if ibkr_hv else ''} | {div_str} | {len(results):>2} cand")
    if not results:
        summary += f"  [0 passed; rejects: {dict(reasons)}]"
    _p(summary)

    atm_row = ({'ticker': ticker, 'iv': round(atm_iv_tracker, 4),
                'hv': round(hv_yf, 4) if hv_yf else None}
               if atm_iv_tracker else None)
    return results, atm_row


# ── Scoring (option + technical + diversification; fundamentals are a gate) ─────

def _pct_rank(series, higher_is_better=True):
    r = series.rank(pct=True)
    if not higher_is_better:
        r = 1 - r
    return (r * 100)


def _rsi_score(rsi):
    if rsi is None or pd.isna(rsi):
        return np.nan
    score = max(0.0, 100 - abs(rsi - 40) * 2)
    if rsi < 25 or rsi > 75:
        score *= 0.5
    return score


def _bb_score(pctb):
    if pctb is None or pd.isna(pctb):
        return np.nan
    return float(np.clip((1 - pctb) * 100, 0, 100))


def score_candidates(df, iv_hist_df):
    if df.empty:
        return df

    rank_map = {t: ticker_iv_rank(iv_hist_df, t) for t in df['ticker'].unique()}
    df['iv_rank'] = pd.to_numeric(df['ticker'].map(lambda t: rank_map[t][0]),
                                  errors='coerce').round(1)
    df['iv_src']  = df['ticker'].map(lambda t: rank_map[t][1])

    # ---- Option-edge bucket ----
    opt_parts = []
    if df['iv_rank'].notna().any():
        opt_parts.append(_pct_rank(df['iv_rank'], True))
    if df['iv_hv'].notna().any():
        opt_parts.append(_pct_rank(df['iv_hv'], True))
    if df['ann_ret_pct'].notna().any():
        opt_parts.append(_pct_rank(df['ann_ret_pct'], True))
    if df['theta'].notna().any():
        opt_parts.append(_pct_rank(df['theta'].abs(), True))
    df['score_option'] = (pd.concat(opt_parts, axis=1).mean(axis=1)
                          if opt_parts else np.nan)

    # ---- Technical bucket ----
    tech_parts = []
    rsi_s = df['_rsi'].apply(_rsi_score)
    if rsi_s.notna().any():
        tech_parts.append(rsi_s)
    bb_s = df['_bb_pctb'].apply(_bb_score)
    if bb_s.notna().any():
        tech_parts.append(bb_s)
    if df['_support_margin'].notna().any():
        tech_parts.append(_pct_rank(df['_support_margin'], True))
    df['score_technical'] = (pd.concat(tech_parts, axis=1).mean(axis=1)
                             if tech_parts else np.nan)

    # ---- Diversification bucket (absolute 0-100; NaN when no holdings) ----
    df['score_diversify'] = (pd.to_numeric(df['div_score'], errors='coerce')
                             if 'div_score' in df.columns else np.nan)

    # ---- Weighted composite (renormalize over available buckets) ----
    buckets = [('score_option', W_OPTION),
               ('score_technical', W_TECHNICAL),
               ('score_diversify', W_DIVERSIFY)]

    def _composite(row):
        num = den = 0.0
        for col, w in buckets:
            v = row[col]
            if pd.notna(v):
                num += v * w
                den += w
        return round(num / den, 1) if den > 0 else np.nan

    df['score'] = df.apply(_composite, axis=1)
    for c in ('score_option', 'score_technical', 'score_diversify'):
        df[c] = df[c].round(1)
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global ACCOUNT_SIZE
    acct_from_file = os.path.exists(ACCOUNT_FILE)
    ACCOUNT_SIZE = get_account_size()
    acct_src = "IBKR" if acct_from_file else "default — run monitor.py to fetch real NLV"
    print("=" * 74)
    print("PUT SELLING SCREENER  |  spec-aligned  |  yfinance + Black-Scholes")
    print(f"Gates: {MIN_DTE}-{MAX_DTE} DTE | |delta| {DELTA_MIN}-{DELTA_MAX} | "
          f"spread<{int(MAX_SPREAD_PCT*100)}% | OI>={MIN_OPEN_INTEREST} | "
          f"regime={REGIME_MODE} | solvency+fundamentals (equities)")
    print(f"Score: option {int(W_OPTION*100)}% / technical {int(W_TECHNICAL*100)}% "
          f"/ diversify {int(W_DIVERSIFY*100)}%   |   "
          f"sizing: {int(MAX_RISK_PCT*100)}% risk on ${ACCOUNT_SIZE:,.0f} "
          f"({int(ASSUMED_DRAWDOWN*100)}% drawdown, acct: {acct_src})")
    print("=" * 74)

    iv_hist_df = load_iv_history()
    if iv_hist_df is None:
        print("Note: no IV history yet. Run update_iv_history.py (IBKR) for full-year IV Rank.")
    else:
        print(f"IV history loaded: {iv_hist_df['source'].value_counts().to_dict()}")

    holdings = load_holdings()
    holdings_returns = fetch_returns(holdings) if holdings else {}
    if holdings_returns:
        print(f"Diversification baseline: {len(holdings_returns)} holdings "
              f"({', '.join(sorted(holdings_returns))})\n")
    else:
        print("Diversification: no holdings found — diversification score skipped.\n")

    all_results, atm_rows = [], []
    for ticker in TICKERS:
        rows, atm = screen_ticker(ticker, iv_hist_df, holdings_returns)
        all_results.extend(rows)
        if atm:
            atm_rows.append(atm)

    record_iv(atm_rows)

    if not all_results:
        print("\nNo candidates matched the gates.")
        return

    df = pd.DataFrame(all_results)
    df = score_candidates(df, iv_hist_df)
    df = df.sort_values('score', ascending=False, na_position='last').reset_index(drop=True)

    display_cols = ['ticker', 'type', 'stock_price', 'otm_%', 'expiry', 'dte', 'strike', 'mid',
                    'lots', 'open_int', 'delta', 'iv_pct', 'iv_hv',
                    'iv_rank', 'iv_src', 'ann_ret_pct', 'div_corr',
                    'score_option', 'score_technical', 'score_diversify', 'score']
    display_cols = [c for c in display_cols if c in df.columns]

    print("\n" + "=" * 74)
    print(f"RANKED CANDIDATES  ({len(df)} total, sorted by composite score)")
    print("=" * 74)
    print(df[display_cols].head(25).to_string(index=False))

    # Best candidate(s) per sleeve — for building a diversified book across asset classes
    if 'sleeve' in df.columns:
        best = (df.sort_values('score', ascending=False)
                  .groupby('sleeve', as_index=False).head(PER_SLEEVE_TOP)
                  .sort_values('score', ascending=False))
        sleeve_cols = ['sleeve', 'ticker', 'type', 'stock_price', 'otm_%', 'expiry', 'dte',
                       'strike', 'mid', 'lots', 'delta', 'iv_hv',
                       'iv_rank', 'ann_ret_pct', 'div_corr',
                       'score_option', 'score_technical', 'score_diversify', 'score']
        sleeve_cols = [c for c in sleeve_cols if c in best.columns]
        print("\n" + "=" * 74)
        print(f"BEST PER SLEEVE  (top {PER_SLEEVE_TOP}/sleeve — pick across sleeves to diversify)")
        print("=" * 74)
        print(best[sleeve_cols].to_string(index=False))

    df.to_csv('screener_output.csv', index=False)
    print(f"\nSaved -> screener_output.csv  ({len(df)} rows)")


if __name__ == '__main__':
    main()

```


### update_iv_history.py

```python
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

```


### monitor.py

```python
"""
IBKR Position Monitor
Connects to IB Gateway, pulls ALL open option positions, and flags:
  - 70% profit reached  → close for profit
  - DTE ≤ 21            → time-based close (avoid gamma risk near expiry)

Combo detection: positions sharing (ticker, expiry) are tagged COMBO and
flagged together — if any leg triggers, the whole group is flagged.

Requires IB Gateway running on PORT below.
"""

from ib_insync import IB
import yfinance as yf
from datetime import date
import pandas as pd
import warnings

import screener as S          # reuse screener gates + scoring for roll candidates
warnings.filterwarnings('ignore')

# ── Config ────────────────────────────────────────────────────────────────────
PORT              = 4001   # 4001 live / 4002 paper
CLIENT_ID         = 3      # different from screener (2) and test (1)
PROFIT_TARGET_PCT = 0.70   # close at 70% profit
HARD_CLOSE_DTE    = 21     # close at 21 DTE regardless of profit
ROLL_TOP_N        = 3      # roll candidates to show per flagged short put
NEAR_ATM_BUFFER   = 0.03   # short put is "challenged" (ATM/ITM) if stock <= strike*(1+this)
# ─────────────────────────────────────────────────────────────────────────────


def get_current_option_price(ticker: str, expiry_yyyymmdd: str,
                              strike: float, right: str) -> float | None:
    """Fetch current mid or last price for an option via yfinance."""
    try:
        exp_date = date(
            int(expiry_yyyymmdd[:4]),
            int(expiry_yyyymmdd[4:6]),
            int(expiry_yyyymmdd[6:8]),
        )
        exp_yf = exp_date.strftime('%Y-%m-%d')

        yf_t = yf.Ticker(ticker)
        if exp_yf not in yf_t.options:
            return None

        chain = yf_t.option_chain(exp_yf)
        df    = chain.puts if right == 'P' else chain.calls
        row   = df[df['strike'] == strike]
        if row.empty:
            return None
        row = row.iloc[0]

        bid  = float(row.get('bid', 0)      or 0)
        ask  = float(row.get('ask', 0)       or 0)
        last = float(row.get('lastPrice', 0) or 0)

        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return last if last > 0 else None
    except Exception:
        return None


def get_stock_price(ticker):
    try:
        return S.get_price(yf.Ticker(ticker))
    except Exception:
        return None


def build_roll_suggestions(df, iv_hist_df, holdings_returns, top_n=ROLL_TOP_N):
    """For each CLOSE-flagged single-leg short PUT, score later-expiry puts on the
    SAME ticker with the screener framework and return the top-N rolls + net credit.
    Net credit (per share) = new put mid - cost to buy back the current put.
    Returns a list of (position_row, candidates_df_or_None)."""
    out = []
    flagged = df[((df['action'].astype(str).str.startswith('CLOSE')) |
                  (df['action'] == 'ROLL?')) &
                 (df['type'] == 'P') & (df['qty'] < 0) & (df['combo'] != 'COMBO')]
    for _, pos in flagged.iterrows():
        tkr, cur_exp, buyback = pos['ticker'], pos['expiry'], pos['current']
        try:
            results, _ = S.screen_ticker(tkr, iv_hist_df, holdings_returns, verbose=False)
        except Exception:
            results = []
        cand = pd.DataFrame(results)
        if not cand.empty:
            cand = S.score_candidates(cand, iv_hist_df)
            cand = cand[cand['expiry'] > cur_exp]          # roll OUT to a later expiry only
        if cand.empty:
            out.append((pos, None))
            continue
        cand = cand.copy()
        cand['net_credit'] = ((cand['mid'] - float(buyback)).round(2)
                              if buyback is not None else None)
        out.append((pos, cand.sort_values('score', ascending=False).head(top_n)))
    return out


def print_roll_suggestions(rolls):
    """Render roll suggestions and save roll_suggestions.csv."""
    if not rolls:
        return
    print("\n" + "=" * 90)
    print(f"ROLL SUGGESTIONS  (close-flagged or ATM/ITM short puts — top {ROLL_TOP_N} by composite score)")
    print("Net credit (per share) = new put mid − buyback of current put. Rolls to a later expiry only.")
    print("=" * 90)
    cols = ['expiry', 'dte', 'strike', 'mid', 'net_credit', 'delta', 'iv_rank',
            'iv_hv', 'ann_ret_pct', 'score_option', 'score_technical',
            'score_diversify', 'score']
    flat = []
    for pos, top in rolls:
        bb = f"${pos['current']}" if pos['current'] is not None else "n/a"
        print(f"\n{pos['ticker']} P {pos['strike']:g}  exp {pos['expiry']} ({pos['dte']}d)"
              f"  | buyback {bb} | flag: {pos['reason']}")
        if top is None or top.empty:
            print("   no qualifying roll (ticker gated or no later expiry) → recommend CLOSE")
            continue
        show = [c for c in cols if c in top.columns]
        print(top[show].to_string(index=False))
        for _, r in top.iterrows():
            flat.append({'pos_ticker': pos['ticker'], 'pos_strike': pos['strike'],
                         'pos_expiry': pos['expiry'], 'pos_dte': pos['dte'],
                         'flag': pos['reason'], 'buyback': pos['current'],
                         'roll_expiry': r['expiry'], 'roll_dte': r['dte'],
                         'roll_strike': r['strike'], 'roll_mid': r['mid'],
                         'net_credit': r.get('net_credit'), 'delta': r['delta'],
                         'iv_rank': r.get('iv_rank'), 'score': r['score']})
    if flat:
        pd.DataFrame(flat).to_csv('roll_suggestions.csv', index=False)
        print("\nSaved → roll_suggestions.csv")


def main():
    # ── Connect to IBKR ───────────────────────────────────────────────────────
    ib = IB()
    try:
        ib.connect('127.0.0.1', PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"✗ Could not connect to IB Gateway on port {PORT}: {e}")
        print("  Is IB Gateway running and logged in? Skipping monitor "
              "(the screener/report will still run).")
        return
    print(f"Connected: {ib.isConnected()}  |  Server: {ib.client.serverVersion()}")

    positions = ib.positions()

    # Account NetLiquidation → persist for the screener's position sizing
    try:
        nlv = next((float(v.value) for v in ib.accountSummary()
                    if v.tag == 'NetLiquidation'), None)
    except Exception:
        nlv = None
    if nlv and S.save_account_size(nlv):
        print(f"Account NetLiquidation: ${nlv:,.0f}  → saved for screener sizing")

    ib.disconnect()

    # ── Filter to ALL option positions (short AND long legs of combos) ─────────
    all_opts = [
        p for p in positions
        if p.contract.secType == 'OPT'
    ]

    if not all_opts:
        print("\nNo open option positions found.")
        return

    print(f"\n{len(all_opts)} option position(s) found.\n")

    today = date.today()
    rows  = []
    stock_prices = {t: get_stock_price(t)
                    for t in sorted({p.contract.symbol for p in all_opts})}

    for pos in all_opts:
        c          = pos.contract
        ticker     = c.symbol
        expiry_str = c.lastTradeDateOrContractMonth   # YYYYMMDD
        strike     = c.strike
        right      = c.right                          # 'P' or 'C'
        qty        = int(pos.position)                # negative = short, positive = long
        # IBKR avgCost is per-contract (×100); divide by 100 for per-share
        avg_cost   = pos.avgCost / 100

        exp_date = date(
            int(expiry_str[:4]),
            int(expiry_str[4:6]),
            int(expiry_str[6:8]),
        )
        dte = (exp_date - today).days

        current = get_current_option_price(ticker, expiry_str, strike, right)

        # P&L: for short (qty < 0) profit when current < entry
        #       for long  (qty > 0) profit when current > entry
        if current is not None and avg_cost and avg_cost > 0:
            if qty < 0:
                pnl_pct = (avg_cost - current) / avg_cost
            else:
                pnl_pct = (current - avg_cost) / avg_cost
        else:
            pnl_pct = None

        # Moneyness for short puts (challenged = at/in the money)
        stock = stock_prices.get(ticker)
        challenged = (right == 'P' and qty < 0 and stock is not None
                      and stock <= strike * (1 + NEAR_ATM_BUFFER))
        if right == 'P' and stock is not None:
            money = 'ITM' if stock < strike else ('ATM' if challenged else 'OTM')
        else:
            money = ''

        # Exposure = max loss at the -X% stop for short puts: strike * X% * 100 * |qty|
        exposure = (round(strike * S.ASSUMED_DRAWDOWN * 100 * abs(qty))
                    if (right == 'P' and qty < 0) else None)

        # Per-leg close triggers (only apply profit target to short legs)
        leg_reasons = []
        if qty < 0 and pnl_pct is not None and pnl_pct >= PROFIT_TARGET_PCT:
            leg_reasons.append(f"{pnl_pct * 100:.0f}% profit")
        if 0 <= dte <= HARD_CLOSE_DTE:
            leg_reasons.append(f"{dte} DTE ≤ {HARD_CLOSE_DTE}")

        rows.append({
            'ticker':       ticker,
            'type':         right,
            'expiry':       exp_date.strftime('%Y-%m-%d'),
            '_expiry_str':  expiry_str,   # internal key for grouping
            'dte':          dte,
            'strike':       strike,
            'stock':        round(stock, 2) if stock else None,
            'money':        money,
            'exposure':     exposure,
            'qty':          qty,
            'entry':        round(avg_cost, 2) if avg_cost else None,
            'current':      round(current, 2)  if current  else None,
            'pnl_%':        round(pnl_pct * 100, 1) if pnl_pct is not None else None,
            '_leg_trigger': bool(leg_reasons),
            '_leg_reason':  '  +  '.join(leg_reasons),
            '_challenged':  bool(challenged),
        })

    df = pd.DataFrame(rows)

    # ── Combo detection: group by (ticker, expiry) ────────────────────────────
    group_counts = df.groupby(['ticker', '_expiry_str']).size()

    def get_combo_tag(row):
        count = group_counts.get((row['ticker'], row['_expiry_str']), 1)
        return 'COMBO' if count > 1 else ''

    df['combo'] = df.apply(get_combo_tag, axis=1)

    # If ANY leg in a combo group triggers, flag ALL legs in that group
    trigger_groups = set(
        df.loc[df['_leg_trigger'], ['ticker', '_expiry_str']]
        .apply(tuple, axis=1)
    )

    def resolve_action(row):
        key = (row['ticker'], row['_expiry_str'])
        if row['_leg_trigger']:
            return 'CLOSE ⚡'
        if row['combo'] == 'COMBO' and key in trigger_groups:
            return 'CLOSE ⚡'   # sibling leg triggered — close together
        if row['_challenged'] and row['combo'] != 'COMBO':
            return 'ROLL?'      # at/in the money — consider rolling down-and-out
        return 'HOLD'

    def resolve_reason(row):
        key = (row['ticker'], row['_expiry_str'])
        if row['_leg_trigger']:
            return row['_leg_reason']
        if row['combo'] == 'COMBO' and key in trigger_groups:
            return 'combo leg triggered'
        if row['_challenged'] and row['combo'] != 'COMBO':
            return f"{row['money']} (stock {row['stock']} vs strike {row['strike']:g})"
        return ''

    df['action'] = df.apply(resolve_action, axis=1)
    df['reason'] = df.apply(resolve_reason, axis=1)

    # ── Clean up and sort ─────────────────────────────────────────────────────
    df = (df
          .drop(columns=['_expiry_str', '_leg_trigger', '_leg_reason', '_challenged'])
          .sort_values(
              ['ticker', 'dte', 'type', 'strike'],
              ascending=[True, True, True, True]
          )
          .reset_index(drop=True))

    # Reorder columns for readability
    df = df[['ticker', 'combo', 'type', 'expiry', 'dte', 'strike', 'stock', 'money',
             'qty', 'entry', 'current', 'pnl_%', 'exposure', 'action', 'reason']]

    print("=" * 90)
    print("POSITION MONITOR")
    print(f"Exit rules: {int(PROFIT_TARGET_PCT * 100)}% profit (short legs)  or  ≤{HARD_CLOSE_DTE} DTE")
    print("Combo: legs sharing ticker+expiry are grouped — any trigger closes all legs")
    print("=" * 90)
    print(df.to_string(index=False))

    close_ct = (df['action'].str.startswith('CLOSE')).sum()
    roll_ct  = (df['action'] == 'ROLL?').sum()
    hold_ct  = (df['action'] == 'HOLD').sum()
    long_ct  = (df['qty'] > 0).sum()
    print(f"\n→ Close: {close_ct}   Roll?: {roll_ct}   Hold: {hold_ct}   (Long/hedge legs: {long_ct})")

    total_exp = int(df['exposure'].dropna().sum()) if 'exposure' in df.columns else 0
    dd = int(S.ASSUMED_DRAWDOWN * 100)
    if nlv:
        print(f"→ Short-put exposure (max loss at strike −{dd}%): ${total_exp:,} = "
              f"{total_exp / nlv * 100:.1f}% of ${nlv:,.0f} NLV")
    else:
        print(f"→ Short-put exposure (max loss at strike −{dd}%): ${total_exp:,}  (NLV n/a — run with Gateway)")

    df.to_csv('monitor_output.csv', index=False)
    print(f"Saved → monitor_output.csv")

    # ── Roll suggestions: reuse screener scoring on the same ticker ────────────
    iv_hist_df = S.load_iv_history()
    holdings_returns = S.fetch_returns(sorted(df['ticker'].dropna().unique()))
    rolls = build_roll_suggestions(df, iv_hist_df, holdings_returns)
    print_roll_suggestions(rolls)


if __name__ == '__main__':
    main()

```


### place_stops.py

```python
"""
Stop-order tool for short puts.

Default: buy-to-close when the UNDERLYING falls to strike x (1 - STOP_DROP),
i.e. strike -7%. The basis is configurable (STOP_BASIS):

  'underlying'       -> conditional order; fires when the STOCK hits strike*(1-STOP_DROP).
                        Immune to noisy option quotes; matches a stock-level rule. (DEFAULT)
  'option_intrinsic' -> native STP on the option; stop price = strike*STOP_DROP
                        (~the option's intrinsic at strike -STOP_DROP).
  'credit'           -> native STP on the option; stop price = CREDIT_MULT x entry credit
                        (classic premium stop; caps loss at ~(mult-1)x credit).

MODES (safety):
  MODE = 'advisory'  (DEFAULT) -> prints the stops it WOULD place; submits NOTHING.
  MODE = 'live'                -> transmits GTC stops to the account on PORT, after you
                                  type YES. Places REAL orders.

Idempotent: short puts that already have an open BUY order (stop/roll/close) are
skipped. Combos and short calls are skipped. Sizing/exposure uses a separate 15%
assumption (S.ASSUMED_DRAWDOWN); this stop cuts tighter at STOP_DROP=7%.

NOTE: connects to PORT 4001 (live — where your positions are). The agent does not
transmit orders; you flip MODE and type YES.
"""

from collections import Counter

import yfinance as yf
from ib_insync import IB, Stock, MarketOrder, StopOrder, PriceCondition

import screener as S

HOST        = '127.0.0.1'
PORT        = 4001          # live account (where your positions are)
CLIENT_ID   = 6
MODE        = 'live'    # 'advisory' (print only) | 'live' (transmit GTC stops)
STOP_BASIS  = 'underlying'  # 'underlying' | 'option_intrinsic' | 'credit'
STOP_DROP   = 0.07          # underlying/option_intrinsic: distance below strike
CREDIT_MULT = 2.5           # credit basis: buy-to-close at this multiple of entry credit


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def stop_spec(strike, entry_credit, basis=STOP_BASIS, drop=STOP_DROP, mult=CREDIT_MULT):
    """Stop definition for one short put.
    Returns dict(kind, price, label):
      kind='underlying' -> price is the STOCK trigger (conditional buy-to-close)
      kind='option'     -> price is the OPTION stop price (native STP buy)
    """
    if basis == 'underlying':
        px = round(strike * (1 - drop), 2)
        return {'kind': 'underlying', 'price': px,
                'label': f"stock<={px} (strike -{int(drop*100)}%)"}
    if basis == 'option_intrinsic':
        px = round(strike * drop, 2)
        return {'kind': 'option', 'price': px,
                'label': f"opt>={px} (~intrinsic at strike -{int(drop*100)}%)"}
    if basis == 'credit':
        px = round((entry_credit or 0) * mult, 2)
        return {'kind': 'option', 'price': px,
                'label': f"opt>={px} ({mult}x credit {entry_credit})"}
    raise ValueError(f"unknown STOP_BASIS: {basis}")


def combo_keys(positions):
    cnt = Counter((p.contract.symbol, p.contract.lastTradeDateOrContractMonth)
                  for p in positions if p.contract.secType == 'OPT')
    return {k for k, v in cnt.items() if v > 1}


def plan_stops(positions, protected_conids, combos,
               basis=STOP_BASIS, drop=STOP_DROP, mult=CREDIT_MULT):
    """Stop plans for single-leg short puts lacking a protective order."""
    plans = []
    for p in positions:
        c = p.contract
        if not (c.secType == 'OPT' and c.right == 'P' and p.position < 0):
            continue
        if (c.symbol, c.lastTradeDateOrContractMonth) in combos:
            continue
        if c.conId in protected_conids:
            continue
        avg = getattr(p, 'avgCost', None)
        entry_credit = round(avg / 100, 2) if avg else None   # IBKR avgCost is per-contract
        spec = stop_spec(c.strike, entry_credit, basis, drop, mult)
        plans.append({
            'symbol':  c.symbol, 'conId': c.conId,
            'expiry':  c.lastTradeDateOrContractMonth, 'strike': c.strike,
            'qty':     int(abs(p.position)), 'entry_credit': entry_credit,
            'kind':    spec['kind'], 'price': spec['price'], 'label': spec['label'],
        })
    return plans


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"x Could not connect to IB Gateway on port {PORT}: {e}")
        print("  Is IB Gateway running and logged in?")
        return
    print(f"Connected: {ib.isConnected()}  |  port {PORT}  |  MODE={MODE}  |  basis={STOP_BASIS}")

    positions = ib.positions()
    open_trades = ib.openTrades()
    protected = {t.contract.conId for t in open_trades
                 if t.order.action == 'BUY' and t.contract.secType == 'OPT'}
    combos = combo_keys(positions)
    plans = plan_stops(positions, protected, combos)

    n_short = sum(1 for p in positions
                  if p.contract.secType == 'OPT' and p.contract.right == 'P' and p.position < 0)
    print(f"\n{n_short} short put(s); {len(plans)} need a stop "
          f"({n_short - len(plans)} skipped: combo / already protected).")
    if not plans:
        ib.disconnect()
        return

    print("\n" + "=" * 80)
    print(f"PROPOSED GTC STOPS  (basis={STOP_BASIS}, drop={int(STOP_DROP*100)}%)")
    print("=" * 80)
    print(f"{'symbol':<8}{'expiry':<10}{'strike':>8}{'qty':>5}{'credit':>8}{'stock':>9}  stop-rule")
    for pl in plans:
        try:
            spot = S.get_price(yf.Ticker(pl['symbol']))
        except Exception:
            spot = None
        spot_s = f"{spot:>9.2f}" if spot else "      n/a"
        cr = f"{pl['entry_credit']:>8.2f}" if pl['entry_credit'] is not None else "     n/a"
        print(f"{pl['symbol']:<8}{pl['expiry']:<10}{pl['strike']:>8g}{pl['qty']:>5}"
              f"{cr}{spot_s}  {pl['label']}")

    if MODE != 'live':
        print("\nADVISORY mode — no orders submitted. Set MODE='live' to transmit.")
        ib.disconnect()
        return

    ans = input(f"\nTransmit {len(plans)} GTC stop orders to account on port {PORT}? Type YES: ")
    if ans.strip() != 'YES':
        print("Aborted — no orders sent.")
        ib.disconnect()
        return

    sent = 0
    for pl in plans:
        try:
            opt = next(p.contract for p in positions if p.contract.conId == pl['conId'])
            opt.exchange = opt.exchange or 'SMART'
            if pl['kind'] == 'underlying':
                stk = Stock(pl['symbol'].replace('-', ' '), 'SMART', 'USD')
                if not ib.qualifyContracts(stk) or not stk.conId:
                    print(f"  x {pl['symbol']}: underlying unresolved — skipped")
                    continue
                order = MarketOrder('BUY', pl['qty'])
                order.tif = 'GTC'
                order.transmit = True
                order.conditions = [PriceCondition(price=pl['price'], conId=stk.conId,
                                                   exch='SMART', isMore=False)]
                order.conditionsCancelOrder = False
            else:  # native option stop
                order = StopOrder('BUY', pl['qty'], pl['price'])
                order.tif = 'GTC'
                order.transmit = True
            ib.placeOrder(opt, order)
            sent += 1
            print(f"  + {pl['symbol']} {pl['strike']:g}P x{pl['qty']}  {pl['label']}")
        except Exception as e:
            print(f"  x {pl['symbol']}: {e}")
    ib.sleep(1)
    print(f"\nTransmitted {sent} GTC stop order(s). Verify in TWS (Orders tab).")
    ib.disconnect()


if __name__ == '__main__':
    main()

```


### notify.py

```python
"""
Telegram notifier (free Bot API).

Credentials (in order):
  1. env vars  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   (used by GitHub Actions secrets)
  2. telegram_config.json next to this file: {"bot_token": "...", "chat_id": "..."}

Setup: message @BotFather -> /newbot -> copy the token. Get your chat_id by messaging
your bot once, then visiting https://api.telegram.org/bot<token>/getUpdates and reading
result[].message.chat.id  (or message @userinfobot).
"""

import os
import json
import html

import requests

_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'telegram_config.json')
_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX = 3900   # Telegram hard limit is 4096; leave headroom


def _creds():
    tok = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if tok and chat:
        return tok, chat
    try:
        with open(_CFG) as f:
            c = json.load(f)
        return c.get('bot_token'), c.get('chat_id')
    except Exception:
        return None, None


def _chunks(text, n=_MAX):
    """Split on line boundaries so each message stays under Telegram's limit."""
    buf = ''
    for ln in text.split('\n'):
        if len(buf) + len(ln) + 1 > n:
            if buf:
                yield buf
            buf = ln[:n]
        else:
            buf = (buf + '\n' + ln) if buf else ln
    if buf:
        yield buf


def mono(table_str):
    """Wrap a (monospace) block for Telegram HTML, escaping &<>."""
    return "<pre>" + html.escape(table_str) + "</pre>"


def send_telegram(text, token=None, chat=None):
    token = token or _creds()[0]
    chat = chat or _creds()[1]
    if not token or not chat:
        print("Telegram not configured — set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
              "or create telegram_config.json. (Message not sent.)")
        return False
    ok = True
    for chunk in _chunks(text):
        try:
            r = requests.post(_API.format(token=token),
                              data={'chat_id': chat, 'text': chunk,
                                    'parse_mode': 'HTML',
                                    'disable_web_page_preview': True},
                              timeout=20)
            if r.status_code != 200:
                print("Telegram error:", r.status_code, r.text[:300])
                ok = False
        except Exception as e:
            print("Telegram send failed:", e)
            ok = False
    return ok


if __name__ == '__main__':
    # quick test: python notify.py
    send_telegram("✅ Test message from your options screener notifier.")

```


### daily_report.py

```python
"""
Assemble the daily digest and push it to Telegram.

Run AFTER screener.py (and optionally monitor.py). Reads the CSVs they produce —
screener_output.csv, and if present monitor_output.csv / roll_suggestions.csv —
so this stays decoupled and works the same on your PC or on GitHub Actions.

    python screener.py        # writes screener_output.csv
    python daily_report.py    # formats + sends Telegram
"""

import os
from datetime import date

import pandas as pd

import notify

_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_N = 10   # candidates in the screener section


def _path(name):
    return os.path.join(_DIR, name)


def fmt_monitor():
    """Positions needing action (CLOSE / ROLL?) + total exposure line, if monitor ran."""
    f = _path('monitor_output.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if 'action' not in df.columns or df.empty:
        return ''
    act = df[df['action'].astype(str).str.startswith(('CLOSE', 'ROLL'))]
    if act.empty:
        return "<b>MONITOR</b> — no positions need action."
    cols = [c for c in ['ticker', 'type', 'strike', 'dte', 'money', 'pnl_%', 'exposure', 'action']
            if c in act.columns]
    out = "<b>MONITOR — action needed</b>\n" + notify.mono(act[cols].to_string(index=False))
    if 'exposure' in df.columns:
        tot = int(pd.to_numeric(df['exposure'], errors='coerce').dropna().sum())
        out += f"\nShort-put exposure (max loss at stop): ${tot:,}"
    return out


def fmt_rolls():
    """Top roll suggestion per flagged position, if present."""
    f = _path('roll_suggestions.csv')
    if not os.path.exists(f):
        return ''
    try:
        df = pd.read_csv(f)
    except Exception:
        return ''
    if df.empty:
        return ''
    best = df.sort_values('score', ascending=False).groupby('pos_ticker', as_index=False).head(1)
    cols = [c for c in ['pos_ticker', 'pos_strike', 'roll_expiry', 'roll_strike',
                        'net_credit', 'score'] if c in best.columns]
    return "<b>TOP ROLL per position</b>\n" + notify.mono(best[cols].to_string(index=False))


def fmt_screener():
    f = _path('screener_output.csv')
    if not os.path.exists(f):
        return "<b>SCREENER</b> — no output (screener.py did not produce results)."
    try:
        df = pd.read_csv(f)
    except Exception:
        return "<b>SCREENER</b> — could not read output."
    if df.empty:
        return "<b>SCREENER</b> — no candidates passed the gates."
    df = df.sort_values('score', ascending=False)
    cols = [c for c in ['ticker', 'expiry', 'dte', 'strike', 'mid', 'delta',
                        'iv_rank', 'ann_ret_pct', 'score'] if c in df.columns]
    out = [f"<b>SCREENER</b> — {len(df)} candidates (top {TOP_N})",
           notify.mono(df[cols].head(TOP_N).to_string(index=False))]
    if 'sleeve' in df.columns:
        book = df.groupby('sleeve', as_index=False).head(1)
        scols = [c for c in ['sleeve', 'ticker', 'strike', 'dte', 'ann_ret_pct', 'score']
                 if c in book.columns]
        out.append("<b>Best per sleeve</b>")
        out.append(notify.mono(book[scols].to_string(index=False)))
    return "\n".join(out)


def main():
    parts = [f"<b>📈 Daily Options Report — {date.today()}</b>"]
    mon = fmt_monitor()
    if mon:
        parts.append(mon)
    rolls = fmt_rolls()
    if rolls:
        parts.append(rolls)
    parts.append(fmt_screener())
    msg = "\n\n".join(parts)
    sent = notify.send_telegram(msg)
    print("Report sent." if sent else "Report NOT sent (see message above).")


if __name__ == '__main__':
    main()

```


### .github/workflows/screener.yml

```yaml
name: Daily Options Screener

# Runs the (yfinance-only) screener in the cloud and pushes the report to Telegram.
# No PC required. The monitor + stop orders stay on your PC (they need IB Gateway).
#
# Setup:
#   1. Push this repo to GitHub.
#   2. Repo Settings -> Secrets and variables -> Actions -> add:
#        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#   3. (Optional, for IBKR-grade IV Rank in the cloud) commit data/iv_history.csv
#      from your PC's weekly update_iv_history.py run.

on:
  schedule:
    # cron is UTC. 13:00 UTC ≈ 08:00 ET (EST) / 09:00 ET (EDT). Adjust to taste.
    - cron: '0 13 * * 1-5'
  workflow_dispatch: {}        # lets you run it manually from the Actions tab

jobs:
  screen:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run screener
        run: python screener.py
      - name: Send report
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python daily_report.py

```


### requirements.txt

```text
yfinance
pandas
numpy
scipy
requests

```


### .gitignore

```text
# Secrets & personal data — never commit
telegram_config.json
data/account.json

# Environment / caches
venv/
__pycache__/
*.pyc

# Transient run outputs (regenerated each run)
screener_output.csv
monitor_output.csv
roll_suggestions.csv
logs/

# NOTE: data/iv_history.csv is intentionally NOT ignored —
# commit it (from your weekly PC update_iv_history.py run) so the
# cloud screener gets IBKR-grade IV Rank instead of lite mode.

```
