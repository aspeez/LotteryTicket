# Quick Start

No API key needed — ESPN's public endpoints are keyless.

## 1. Local run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"

python -m lotteryticket.ingest.espn_daily
python -m lotteryticket.transform.curate
python -m lotteryticket.ingest.player_box_scores
python -m lotteryticket.transform.curate
```

Output lands in `data/curated/`. Query it with DuckDB:

```python
import duckdb
duckdb.sql("SELECT * FROM 'data/curated/games/league=nfl/*.parquet'").show()
```

## 2. Run the tests

```powershell
pytest
```

## 3. Wire up GitHub Actions

1. Push this repo to GitHub.
2. `.github/workflows/espn_daily.yml` runs once a day, or trigger it manually from the **Actions** tab.
3. Each run commits fresh curated data and opens a "data refreshed" issue.

## 4. Review with Claude

Open this repo in Claude Code (or a Claude.ai project with repo access) and ask for "the lottery ticket for [date]" — see [docs/LOTTERY_TICKET_PLAYBOOK.md](docs/LOTTERY_TICKET_PLAYBOOK.md) for exactly how Claude should turn the curated data into picks.
