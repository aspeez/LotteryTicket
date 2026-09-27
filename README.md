# LotteryTicket

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Issues](https://img.shields.io/github/issues/aspeez/LotteryTicket.svg)](https://github.com/aspeez/LotteryTicket/issues)

Automated NFL data collection platform. Pulls games, per-player box-score stats, and injury reports from ESPN's public API, curates them into clean Parquet tables, and hands them to Claude to turn into a ranked list of sports picks.

**No betting odds are collected here, on purpose.** This isn't an odds-value/EV project — it's a sports-data pipeline. You check the actual FanDuel line yourself; Claude's job is to make sure the underlying performance data (recent form, matchups, injuries) is good enough to reason from.

How Claude turns curated data into up to 20 ranked picks when you ask for "the lottery ticket for [date]": **[docs/LOTTERY_TICKET_PLAYBOOK.md](docs/LOTTERY_TICKET_PLAYBOOK.md)**.

## How it works

- **Collect** — a GitHub Action pulls ESPN's scoreboard, injury report, and (for finished games) box scores on a daily schedule, writing immutable raw JSON.
- **Curate** — raw JSON is parsed into three clean Parquet tables: `games`, `player_game_stats`, `injuries`.
- **Review** — open the **Lottery Ticket** Claude.ai project (or Claude Code in this repo) and ask for the lottery ticket for a date. Claude queries the curated Parquet with DuckDB, checks recent form and injury status, and returns up to 20 picks with reasoning — player stat lines ("Ja'Marr Chase, 5+ receptions") or team/game lines ("Chargers @ Bills, combined score over 50").

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/aspeez/LotteryTicket.git
cd LotteryTicket
python -m venv .venv
```
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No API key needed — ESPN's public endpoints are keyless.

### 2. Run the pipeline locally

```powershell
$env:PYTHONPATH = "src"
python -m lotteryticket.ingest.espn_daily          # scoreboard + injuries
python -m lotteryticket.transform.curate           # -> games, injuries
python -m lotteryticket.ingest.player_box_scores   # box scores for finished games
python -m lotteryticket.transform.curate           # -> player_game_stats
```

Order matters the first time: `curate` needs `games.parquet` to exist before `player_box_scores` can read game statuses from it. Once data exists, re-running any of these and re-curating is always safe — every curated table is fully rebuilt each run, never appended to (see "Current state" in [CLAUDE.md](CLAUDE.md)).

Check `data/curated/` for the output, or query it directly:

```bash
python -c "import duckdb; print(duckdb.sql(\"SELECT * FROM 'data/curated/games/league=nfl/*.parquet'\"))"
```

### 3. Set up GitHub Actions

1. Push this repo to GitHub.
2. `.github/workflows/espn_daily.yml` runs once a day, or trigger it manually from the **Actions** tab. No secrets to configure.
3. Each run opens a "data refreshed, ready for review" issue.

## Project Structure

```
LotteryTicket/
├── config/
│   └── leagues.yaml               ← active leagues, ESPN path per league
├── src/lotteryticket/
│   ├── clients/espn.py            ← ESPN client (HTTP + retries only)
│   ├── ingest/                    ← jobs: call the client, write raw JSON
│   ├── transform/curate.py        ← raw JSON -> curated Parquet
│   └── util/                      ← io, time helpers
├── data/
│   ├── raw/{source}/{league}/{date}/{time}.json.gz   ← immutable, committed
│   └── curated/{table}/league={x}/*.parquet          ← committed (games, player_game_stats, injuries)
├── tests/                          ← unit tests + ESPN response fixtures
├── docs/
│   ├── LOTTERY_TICKET_PLAYBOOK.md  ← how Claude turns data into picks (the actual design)
│   └── LOTTERYTICKET_SPEC.md       ← an earlier, much larger design — superseded, kept for history
├── CLAUDE.md                       ← orientation for Claude Code sessions
├── .github/workflows/espn_daily.yml
├── requirements.txt
└── pyproject.toml
```

## Data Source

| Data | Source | Notes |
|---|---|---|
| Games, scores, injuries, box scores | [ESPN public scoreboard API](https://site.api.espn.com) | Unofficial/undocumented, no key required — see `docs/LOTTERYTICKET_SPEC.md` §3.2 for why every parser here is fixture-tested rather than trusted blindly. |

Team identity is ESPN's own team id throughout — there's no cross-source name matching to worry about, since ESPN is the only source.

## Troubleshooting

- **Zero games some days** — normal off-season, or a day with nothing scheduled.
- **`player_game_stats` missing a game** — box scores are only fetched for games ESPN marks `STATUS_FINAL`; give it until the next daily run after a game ends.

## License

MIT — see [LICENSE](LICENSE).
