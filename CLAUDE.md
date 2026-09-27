# LotteryTicket

This pipeline collects NFL sports data (games, player box-score stats, injuries) from ESPN's public API. **There is no betting-odds collection in this repo, on purpose** — no Odds API, no FanDuel/Pinnacle lines, no player props, no scoring engine. The user checks actual sportsbook odds themselves; this project's job is to make sure the underlying sports data (recent form, matchups, injuries) is solid enough for Claude to reason from.

## The actual goal

When the user asks "give me the lottery ticket for [date]" (or "sports picks for this week", etc.), follow **[docs/LOTTERY_TICKET_PLAYBOOK.md](docs/LOTTERY_TICKET_PLAYBOOK.md)** exactly — it's the concrete method (which tables, what order, what to check, output format) for turning curated ESPN data into a ranked list of up to 20 picks (player stat lines or team/game lines, e.g. "Chargers @ Bills — combined score over 50"), each with a plain-language reason. Claude is the entire reasoning layer here — there's no scoring engine to defer to.

`docs/LOTTERYTICKET_SPEC.md` is an earlier, much larger design (odds collection, no-vig scoring, parlay builder, CLV tracking, a CLI) that the project deliberately moved away from — it's marked superseded at the top and kept for history, not as a roadmap. Don't build toward it.

## Current state

- `src/lotteryticket/clients/espn.py` — ESPN's public scoreboard/injuries/summary endpoints. HTTP + retries only, no parsing.
- `src/lotteryticket/ingest/` — `espn_daily.py` (scoreboard + injuries), `player_box_scores.py` (box scores for finished games, dedup'd by event id embedded in the raw filename so a full season isn't re-downloaded every day). Both just call the client and write raw responses immutably to `data/raw/{source}/{league}/{date}/{time}.json.gz`.
- `src/lotteryticket/transform/curate.py` — raw JSON → curated Parquet in `data/curated/{table}/league={x}/`. Every table (`games`, `player_game_stats`, `injuries`) is a **STATE table**: rebuilt fully from all raw data on every run, written to a fixed filename. Re-running never duplicates rows — it just replaces "what we know right now". (There used to be a second, snapshot/append write pattern for odds line-history; it's gone along with the odds collection it existed for. If you ever see snapshot-pattern code again, it doesn't belong here.)
- `config/leagues.yaml` — active leagues and their ESPN path. NFL only right now; adding a league is a config-only change (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- `.github/workflows/espn_daily.yml` — the one workflow: fetch scoreboard/injuries → curate → fetch box scores for newly-finished games → curate again → commit → open a "data refreshed, ready for review" issue.
- Team identity is ESPN's own team id throughout (`games.home_team_id`/`away_team_id`, `player_game_stats.team_id`, `injuries.team_id`) — there's no cross-source team-name matching to worry about, since there's only one source now.

## Working in this repo

- Run modules with `PYTHONPATH=src python -m lotteryticket.ingest.espn_daily` (or `pip install -e .` and drop the `PYTHONPATH`).
- Tests: `pytest` (pythonpath is set via `pyproject.toml`). ESPN's API is undocumented — any new parser needs a fixture in `tests/fixtures/` per spec §3.2, not just a live-call smoke test.
- Reading a single known curated Parquet file in Python code: use `pyarrow.parquet.ParquetFile(path).read()`, **not** `pq.read_table(path)`. The latter goes through pyarrow's dataset/partition-discovery machinery, which misreads the `league=nfl` directory segment as a Hive partition column and throws a schema-collision error against the real `league` data column already inside the file. (DuckDB's `read_parquet('*.parquet')` glob queries, as used in ad-hoc review, don't have this problem.)
- Raw data (`data/raw/`) and curated data (`data/curated/`) are committed to git — they're the storage layer, not scratch output.
- No API key is required anywhere in this pipeline (ESPN's endpoints are keyless). Don't add one back without the user asking.
