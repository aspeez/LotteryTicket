# LotteryTicket — Project Spec for Claude Code

> **⚠️ Superseded, kept for history.** The project scope narrowed after this was written: no betting odds are collected at all anymore (no Odds API, no FanDuel/Pinnacle lines, no player props, no no-vig/EV scoring, no parlay builder, no CLV tracking, no `lt` CLI, no Parquet-over-`src/lotteryticket` split into clients/ingest/transform quite this elaborately — though that part did stick). The pipeline is ESPN-only now (games, player box-score stats, injuries), and Claude itself is the entire reasoning layer for turning that into picks — see **[LOTTERY_TICKET_PLAYBOOK.md](LOTTERY_TICKET_PLAYBOOK.md)** for the actual current design and method. Read what follows as "the ambitious version we chose not to build," not as a roadmap.

> Drop this file into the repo (suggested: `docs/LOTTERYTICKET_SPEC.md`) and reference it from `CLAUDE.md` so every Claude Code session starts from it.
> The repo is already being structured. **Adapt this spec to the existing layout rather than overwriting it.** Where they conflict, ask before moving files.

---

## 1. Purpose

LotteryTicket is an automated pipeline that collects sports results, context, and **FanDuel odds**, scores individual bet legs, and helps build **parlays** with a measurable edge.

It follows the same pattern as the InvestmentEngine project:

| InvestmentEngine | LotteryTicket |
|---|---|
| Python pipeline | Python pipeline |
| FMP / Finviz APIs for market data | The Odds API (FanDuel lines) + ESPN endpoints (results, injuries) |
| GitHub Actions on a schedule | GitHub Actions on a schedule |
| GitHub as the storage layer | GitHub as the storage layer (raw JSON + curated Parquet) |
| Claude via Anthropic SDK for analysis | Claude via Anthropic SDK for leg write-ups and parlay review |
| Investment Scorecard (weighted pillars) | Leg Scorecard (weighted pillars) |
| Sector watchlists | Sport/league configs |
| Named workflows ("full diagnostics", "swing") | Named workflows ("slate scan", "parlay build", "CLV review", "full diagnostics") |
| Robinhood MCP for portfolio actions | **No automated bet placement.** Bets are placed by hand in the FanDuel app and logged back into the system |

---

## 2. Non-negotiable principles

1. **No lookahead leakage.** Every row carries a `captured_at` timestamp (UTC). Features for a pick may only use data captured **before** the pick time. Backtests must enforce this with an as-of join, not by convention.
2. **Snapshot odds from day one.** Historical odds are a paid product. The cheapest way to get them is to record them ourselves on a schedule, starting now.
3. **Closing Line Value (CLV) is the primary scorecard.** Win/loss records need hundreds of bets to mean anything. CLV shows skill much sooner.
4. **Parlays only from +EV legs.** Parlays multiply whatever edge each leg has, positive or negative (see §8).
5. **Never automate bet placement or scrape FanDuel.** FanDuel odds come only through The Odds API.
6. **Raw data is immutable.** Store every API response as-is so any table can be rebuilt.

---

## 3. Data sources

### 3.1 The Odds API (FanDuel + a sharp reference book)

- Docs: https://the-odds-api.com/liveapi/guides/v4/ (**verify parameters and credit costs against current docs before coding.**)
- Odds per sport:
  ```
  GET https://api.the-odds-api.com/v4/sports/{sport_key}/odds
      ?apiKey={ODDS_API_KEY}
      &bookmakers=fanduel,pinnacle
      &markets=h2h,spreads,totals
      &oddsFormat=american
  ```
- Sports list (free, no credit cost): `GET /v4/sports?apiKey=...`
- Scores (for settling): `GET /v4/sports/{sport_key}/scores?daysFrom=3&apiKey=...`
- Player props: event-level endpoint `GET /v4/sports/{sport_key}/events/{event_id}/odds?markets=player_pass_yds,...` (phase 3; props cost more credits).
- **Why Pinnacle:** FanDuel is what we get paid on. Pinnacle's no-vig line is the best free estimate of the "true" probability and the benchmark for CLV.
- **Credit budget (check your plan):** cost per call is roughly markets × regions, and the `bookmakers` param counts every 10 books as one region. With 3 markets and 2 books, that's about 3 credits per sport per snapshot. At 4 snapshots/day for one sport over 30 days: 3 × 4 × 30 = **360 credits/month**. Log `x-requests-remaining` from every response header and fail loudly below a threshold.

### 3.2 ESPN (unofficial, undocumented)

These endpoints are unsupported and can change without notice. Build every parser against **saved fixture files** in `tests/fixtures/` and validate the response shape before parsing.

- Scoreboard: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=YYYYMMDD`
  - e.g. `football/nfl`, `football/college-football`, `basketball/nba`, `baseball/mlb`
- Game summary / box score: `.../{sport}/{league}/summary?event={espn_event_id}`
- Teams: `.../{sport}/{league}/teams`
- Injuries: `.../{sport}/{league}/injuries` (verify availability per league)

Use polite rate limiting (≥1s between calls), a descriptive User-Agent, and retries with backoff.

### 3.3 Team/event matching (key engineering problem)

The Odds API and ESPN name teams and events differently. Build a `team_map` table (`league`, `espn_team_id`, `odds_api_name`, aliases), and match games on league + home team + away team + commence date (±1 day for timezone edges). Log unmatched events to `data/quality/unmatched_*.json`, and never silently drop them.

---

## 4. Suggested repo layout

```
LotteryTicket/
├── CLAUDE.md
├── README.md
├── config/
│   ├── leagues.yaml          # which sports are active, sport keys, ESPN paths
│   ├── scorecard.yaml        # pillar weights and thresholds
│   └── bankroll.yaml         # unit size, max stake, max legs
├── src/lotteryticket/
│   ├── clients/              # odds_api.py, espn.py (HTTP + retries only)
│   ├── ingest/                # jobs that call clients and write raw JSON
│   ├── transform/             # raw JSON -> curated Parquet
│   ├── features/              # as-of feature builders
│   ├── scoring/                # leg scorecard, no-vig math, EV
│   ├── parlay/                 # parlay builder + math
│   ├── llm/                    # Claude prompts + calls (Anthropic SDK)
│   ├── picks/                  # pick logging CLI, settlement, CLV
│   └── util/                   # odds conversion, time, io
├── data/
│   ├── raw/{source}/{league}/{YYYY-MM-DD}/{HHMMSS}.json.gz
│   ├── curated/{table}/league={x}/season={y}/*.parquet
│   ├── picks/picks.csv       # human-readable, hand-editable bet log
│   └── quality/
├── reports/                  # generated markdown slate + parlay reports
├── tests/ (fixtures/, unit tests for math + parsers)
└── .github/workflows/
```

Query curated data with **DuckDB directly over Parquet**. No database server, and nothing to host.

---

## 5. Data model (curated tables)

```sql
-- games: one row per game, from ESPN
game_id TEXT PK, league TEXT, season INT, week INT NULL,
commence_time TIMESTAMP, home_team_id TEXT, away_team_id TEXT,
espn_event_id TEXT, odds_event_id TEXT NULL,
status TEXT, home_score INT NULL, away_score INT NULL, venue TEXT, neutral_site BOOL

-- odds_snapshots: append-only, one row per book/market/outcome per capture
game_id TEXT, odds_event_id TEXT, book TEXT,           -- 'fanduel' | 'pinnacle'
market TEXT,                                           -- 'h2h' | 'spreads' | 'totals'
outcome TEXT,                                          -- team name | 'Over' | 'Under'
point DOUBLE NULL, price_american INT, price_decimal DOUBLE,
book_last_update TIMESTAMP, captured_at TIMESTAMP

-- closing_lines: derived, last snapshot before commence_time per book/market/outcome
game_id, book, market, outcome, point, price_american, captured_at

-- injuries: append-only snapshots
league, team_id, player_id, player_name, position, status, detail, captured_at

-- team_game_stats: from ESPN summaries after games finish
game_id, team_id, (sport-specific stat columns), captured_at

-- legs_scored: output of the scorecard at a point in time
leg_id, game_id, market, outcome, point, fd_price, fair_prob, fd_implied_prob,
edge_pct, ev_pct, pillar scores..., total_score, scored_at, model_version

-- picks: every bet actually placed (also mirrored to data/picks/picks.csv)
pick_id, placed_at, bet_type ('single'|'parlay'|'sgp'), legs JSON,
fd_price_american, stake, result ('W'|'L'|'P'|'open'), payout,
clv_pct NULL, notes
```

---

## 6. Jobs and schedules (GitHub Actions)

| Workflow | Schedule (UTC, adjust per season) | What it does |
|---|---|---|
| `odds_snapshot.yml` | every 4–6h, plus hourly within 3h of kickoff on game days | Pull FanDuel + Pinnacle odds for active leagues and write raw + curated |
| `espn_daily.yml` | daily 10:00 | Scoreboard for yesterday/today/next 7 days, injuries, and summaries for finished games |
| `settle.yml` | daily 11:00 | Build `closing_lines`, settle open picks, compute CLV |
| `slate_report.yml` | game-day mornings | Score all legs on the slate and write `reports/{date}_slate.md` |
| `backfill.yml` | manual (`workflow_dispatch`) | ESPN results for past N seasons |

Each workflow commits changed files under `data/` and `reports/` back to the repo, as InvestmentEngine does. Use `concurrency:` groups so two runs never commit at the same time. Secrets: `ODDS_API_KEY`, `ANTHROPIC_API_KEY`.

---

## 7. Leg Scorecard

Mirrors the InvestmentEngine scorecard: weighted pillars, each scored 0–100, with weights in `config/scorecard.yaml`. Starting weights (to be tuned from CLV results):

| Pillar | Weight | What it measures |
|---|---|---|
| **Price Edge** | 40% | FanDuel price vs Pinnacle no-vig fair probability |
| **Matchup Strength** | 25% | Rating/efficiency gap, recent form (last 3–5 games), home/away splits |
| **Situational** | 20% | Rest days, travel, back-to-backs, weather (outdoor), divisional/rivalry |
| **Line Movement** | 15% | Direction and size of the move since open, and whether FanDuel lags the sharp book |

**Hard gates (fail = leg excluded regardless of score):**
- `ev_pct <= 0` against Pinnacle no-vig
- Key injury flagged within the last 24h that the line hasn't moved for (manual review)
- Stale odds: `book_last_update` older than a configurable threshold

### 7.1 Core math (put in `scoring/odds_math.py` with unit tests)

```python
def american_to_decimal(a: int) -> float:
    return 1 + (a / 100 if a > 0 else 100 / abs(a))

def implied_prob(a: int) -> float:
    return 1 / american_to_decimal(a)

def no_vig_two_way(a1: int, a2: int) -> tuple[float, float]:
    p1, p2 = implied_prob(a1), implied_prob(a2)
    total = p1 + p2
    return p1 / total, p2 / total

def ev_pct(fair_prob: float, fd_american: int) -> float:
    return fair_prob * american_to_decimal(fd_american) - 1
```

**Test cases (must pass):**
- `-110` → decimal 1.9091, implied 52.38%
- `+150` → decimal 2.50, implied 40.00%
- Pinnacle `-105 / -105` → no-vig 50.00% / 50.00%
- Fair 50%, FanDuel `+105` → EV = 0.50 × 2.05 − 1 = **+2.5%**
- Fair 50%, FanDuel `-110` → EV = 0.50 × 1.9091 − 1 = **−4.5%**

---

## 8. Parlay builder

### 8.1 Why parlays need +EV legs (include this math in the README)

Parlay decimal payout = product of the leg decimals. Fair probability = product of the leg fair probabilities (only if the legs are independent).

| Legs (each −110, true 50%) | Payout | True win % | EV |
|---|---|---|---|
| 1 | 1.909 (−110) | 50.0% | **−4.5%** |
| 2 | 3.645 (+264) | 25.0% | **−8.9%** |
| 3 | 6.958 (+596) | 12.5% | **−13.0%** |

Same legs, but the model is right and each leg is truly 55%:

| Legs (each −110, true 55%) | True win % | EV |
|---|---|---|
| 1 | 55.0% | **+5.0%** |
| 2 | 30.25% | **+10.3%** |
| 3 | 16.6% | **+15.6%** |

The takeaway: a parlay amplifies each leg's edge. Only +EV legs are allowed in.

### 8.2 Rules

- Candidate legs = legs that passed all gates, ranked by `total_score`.
- Default max legs: 3 (configurable in `bankroll.yaml`).
- **Different games only by default.** Legs from the same game are correlated, and FanDuel prices Same Game Parlays with its own correlation adjustment, so SGP payouts **cannot** be computed by multiplying legs, and The Odds API does not supply SGP prices. SGPs: the user enters the app's quoted price manually and the system logs it.
- Output per parlay: legs, FanDuel combined price, fair combined probability, EV%, suggested stake.
- Staking: flat units by default. Optional fractional Kelly (¼ Kelly), capped by `max_stake` in `bankroll.yaml`.

---

## 9. Claude integration

- Anthropic Python SDK, model set by env var `LT_CLAUDE_MODEL` (default `claude-sonnet-5`).
- Claude **does not generate probabilities or prices.** The numbers come from code. Claude:
  1. Writes a short plain-language case for and against each top leg from the scored data plus injury notes.
  2. Reviews each proposed parlay for hidden correlation or stale info.
  3. Summarizes the weekly CLV review.
- Prompts live in `src/lotteryticket/llm/prompts/*.md` and are versioned. Every output records `model_version` and prompt version.
- Force structured JSON output for anything the pipeline parses, and validate it with pydantic.

---

## 10. Named workflows (CLI entry points, like InvestmentEngine's defined workflows)

```
lt slate-scan   --league nfl --date 2026-09-27   # score every leg on the slate
lt parlay-build --league nfl --date 2026-09-27 --max-legs 3
lt log-bet      --type parlay --legs <leg_ids> --price +264 --stake 10
lt log-bet      --type sgp --desc "..." --price +410 --stake 5   # manual SGP price
lt settle                                        # grade open picks, compute CLV
lt clv-review   --since 2026-09-01               # weekly performance report
lt full-diagnostics                              # data freshness, credit balance,
                                                 # unmatched events, test suite, last runs
```

---

## 11. Config

`config/leagues.yaml`
```yaml
active:
  - key: nfl
    odds_api_sport: americanfootball_nfl
    espn_path: football/nfl
    snapshots_per_day: 4
  # enable when ready:
  # - key: ncaaf
  #   odds_api_sport: americanfootball_ncaaf
  #   espn_path: football/college-football
  # - key: nba
  #   odds_api_sport: basketball_nba
  #   espn_path: basketball/nba
books:
  target: fanduel
  sharp_reference: pinnacle
markets: [h2h, spreads, totals]
```

`config/bankroll.yaml`
```yaml
unit_size: 10
max_stake: 25
max_legs: 3
kelly_fraction: 0.25
use_kelly: false
```

---

## 12. Build phases (each ends with a verifiable check)

**Phase 1: Collect (start immediately, since odds history can't be recovered later)**
- Odds API client + `odds_snapshot` job for NFL (FanDuel + Pinnacle)
- ESPN scoreboard client + daily job, `team_map`, event matching
- ✅ Check: after 48h, `odds_snapshots` has ≥8 captures per upcoming game and unmatched events are under 2%

**Phase 2: Settle and measure**
- `closing_lines`, `lt log-bet`, `lt settle`, CLV calculation
- ✅ Check: a hand-logged bet at FanDuel −110 that closed −120 shows CLV of about **+2.2%** (implied 54.55% − 52.38%)

**Phase 3: Score**
- Odds math module with tests (§7.1), feature builders with as-of joins, Leg Scorecard, `lt slate-scan`, and the slate report
- ✅ Check: a leakage test that fails if any feature uses a row with `captured_at` > `scored_at`

**Phase 4: Parlays + Claude**
- Parlay builder, Claude write-ups, `lt parlay-build`
- ✅ Check: the parlay EV for two independent −110 legs at fair 55% prints +10.3%

**Phase 5: Backfill + expand**
- ESPN backfill of 3+ seasons, player props (credit budget permitting), more leagues

---

## 13. Open decisions (ask the user before building)

- Which leagues to enable beyond NFL, and in what order
- Odds API plan tier (sets snapshot frequency and whether props are affordable)
- Whether `picks.csv` stays in the public repo or moves to a private location, since betting history is personal data (**make sure the repo is private, or keep picks out of git**)
- Notification channel for slate reports (committed markdown only, or also email/Slack)
