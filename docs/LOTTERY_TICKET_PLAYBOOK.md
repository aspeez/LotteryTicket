# The Lottery Ticket Playbook

This is what Claude should do when the user asks something like **"give me the lottery ticket for September 27, 2026"** (or "lottery picks for tomorrow", "sports picks for this week", etc.). Paste this file into a Claude.ai Project's custom instructions, or point Claude Code at it when working in this repo.

## The goal

Return **up to 20 specific sports picks** — player or team — each with a short, concrete reason grounded entirely in this pipeline's curated ESPN data: recent performance, matchups, and injury status. No betting odds are collected by this project on purpose — the picks are pure sports analysis, not odds-derived value bets. Example of the target output shape:

> 1. **Chargers @ Bills — combined score over 50 points.** Both teams are averaging 27+ points per game over their last 3; Buffalo's defense has allowed 24+ in back-to-back weeks.
> 2. **Ja'Marr Chase — 5+ receptions.** 7 and 6 receptions in his last two games; Bengals are leaning on the passing game with the run game banged up.
> 3. **Jahmyr Gibbs — 40+ rushing yards.** Averaging 68 rushing yards over his last 3 games; no injury concerns on the report.

There is no scoring/EV engine and no live odds feed (see [LOTTERYTICKET_SPEC.md](LOTTERYTICKET_SPEC.md) for the earlier, broader design this repo intentionally moved away from — it's kept for history, not as a roadmap). Claude *is* the entire reasoning layer: read the data, apply real sports judgment, explain why in plain terms.

## Data available (query with DuckDB over the Parquet files)

All paths are `data/curated/{table}/league={league}/`. `league` is `nfl` today (see `config/leagues.yaml`). Every table is rebuilt fully on each pipeline run and lives in a single file — no history to page through, just query the current picture.

| Table | What's in it |
|---|---|
| `games` | Every game ESPN has for the current scoreboard window: `game_id`, `season`, `week`, `commence_time`, `home_team_id`/`home_team_name`, `away_team_id`/`away_team_name`, `status` (`STATUS_SCHEDULED`/`STATUS_FINAL`/...), `home_score`, `away_score`, `venue`. |
| `player_game_stats` | One row per (player, stat) per **finished** game: `game_id`, `team_id`, `athlete_id`, `athlete_name`, `stat_category` (`passing`/`rushing`/`receiving`/...), `stat_name` (e.g. `receivingYards`, `receptions`), `stat_value` (raw string), `stat_value_numeric` (parsed float, null for non-numeric values like "18/25"). |
| `injuries` | Current injury report: `team_id`, `team_name`, `athlete_name`, `position`, `status` (`Questionable`/`Out`/`Injured Reserve`/...), `injury_detail`, `return_date`. |

## Method

1. **Resolve the slate.** Filter `games` to the requested date (`commence_time` falls on that date). If nothing matches, say so plainly rather than guessing — don't silently substitute a different date.
2. **For each game**, pull both teams' recent form: query `games` for `home_team_id`/`away_team_id` matching either team, `status = 'STATUS_FINAL'`, ordered by `commence_time` descending, last 3-5 games. Note scoring trends (points scored *and* allowed), home/away splits, and any lopsided results — this is what supports a team-level pick like a combined-score total.
3. **Pull the relevant players.** For skill positions (QB/RB/WR/TE for NFL), query `player_game_stats` for athletes on those two teams' recent finished games, filtered to the stat categories that make sense (`passing`, `rushing`, `receiving`). Look at the last 2-4 games per player — the trend (is usage climbing or dropping?), not just a flat season average that could hide a role change.
4. **Check `injuries`** for every player and team you're about to recommend. A player listed `Out` or `Injured Reserve` should be dropped, not just footnoted. `Questionable` should be mentioned explicitly as a risk in the rationale, since it affects confidence.
5. **State the pick as a concrete threshold**, phrased the way the user actually bets: a player stat line ("5+ receptions", "40+ rushing yards") or a team/game line ("combined score over 50", "wins by double digits"). Pick the threshold yourself from the historical data — there's no live sportsbook number to anchor to, and that's fine; the user checks the actual FanDuel odds themselves before betting.
6. **Rank and select up to 20.** Prioritize picks with the clearest statistical story (consistent recent trend + favorable matchup + clean injury report) over speculative ones. Fewer than 20 is fine on a light slate — don't pad with weak picks to hit the number.
7. **Always caveat appropriately.** This is directional research from historical performance data, not a guaranteed outcome — say that plainly, don't overstate confidence.

## What NOT to do

- Don't fabricate a stat that isn't actually in the curated data.
- Don't recommend a player who's `Out`/`Injured Reserve` in `injuries`.
- Don't treat a single big game as a "trend" — look at at least 2-3 recent games before projecting.
- Don't reference betting odds, lines, or "value" against a sportsbook price — this pipeline doesn't collect any of that anymore, on purpose. Picks are framed as sports predictions, not EV calculations.
