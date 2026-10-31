# Contributing

## Adding a league

Add an entry to `active` in [config/leagues.yaml](config/leagues.yaml):

```yaml
- key: nba
  espn_path: basketball/nba   # site.api.espn.com/apis/site/v2/sports/{espn_path}/scoreboard
  scoreboard_mode: daily
  season_start: "2026-10-20"
```

Set `scoreboard_mode` to match how ESPN schedules the sport:

- `weekly` — ESPN's undated scoreboard returns the whole current week (NFL). Past weeks are pulled with `ingest/backfill_scoreboards.py`.
- `daily` — ESPN's undated scoreboard is a single day (NBA). Also set `season_start: "YYYY-MM-DD"`; `espn_daily` then pulls yesterday/today/tomorrow by date every run and backfills any earlier date in the season automatically. Bump `season_start` each new season.

That's it — `espn_daily`, `player_box_scores`, and `curate` all loop over `config/leagues.yaml`'s active list. A new sport's box-score shape may differ, though (the NBA's has no stat-category names, for example), so add fixtures for its scoreboard/summary/injuries in `tests/fixtures/` and a test like `tests/test_nba.py` before trusting the curated output. Then add a section for the sport to [docs/LOTTERY_TICKET_PLAYBOOK.md](docs/LOTTERY_TICKET_PLAYBOOK.md).

## Adding a stat category or fixing a parser

`_parse_player_game_stats` in [src/lotteryticket/transform/curate.py](src/lotteryticket/transform/curate.py) already walks every stat category ESPN returns for a box score (passing, rushing, receiving, defensive, kicking, ...) generically — there's usually nothing to add there. If a specific stat is missing, check the raw file under `data/raw/espn_summary/` first; the shape may differ from what the fixture assumes.

## ESPN parser changes

ESPN's endpoints are unofficial and undocumented — they can change shape without notice. Any change to `_parse_games`, `_parse_injuries`, or `_parse_player_game_stats` needs a fixture in `tests/fixtures/` (see `tests/test_curate.py` / `tests/test_player_stats.py` for the pattern) so a shape change shows up as a failing test, not a silent bad parse in production.

## Code style

- `black` (line length 100) and `isort` (black profile) — see `pyproject.toml`.
- Type hints on public functions.
- Network calls fail soft (log a `[WARN]`, return an empty result/`None`) rather than raising — one data source having a bad day shouldn't kill the whole run.
- Curated tables are rebuilt fully from raw data every run (state, not append) — see the module docstring in `transform/curate.py`. Don't reintroduce a snapshot/append pattern unless there's genuinely time-series data to track.

## Out of scope

Betting odds collection (FanDuel/Pinnacle lines, player props, an Odds API integration), a no-vig/EV scoring engine, a parlay builder, and CLV tracking were explored and deliberately dropped — see the superseded-notice at the top of `docs/LOTTERYTICKET_SPEC.md`. This project's job is sports data + Claude's reasoning ([docs/LOTTERY_TICKET_PLAYBOOK.md](docs/LOTTERY_TICKET_PLAYBOOK.md)), not odds/EV math. Don't add that machinery back without the user asking for it again.
