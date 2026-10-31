# The Lottery Ticket Playbook

This is what Claude should do when the user asks something like **"give me the lottery ticket for September 27, 2026"** (or "lottery picks for tomorrow", "sports picks for this week", "NBA picks tonight", etc.). Paste this file into a Claude.ai Project's custom instructions, or point Claude Code at it when working in this repo.

## The goal

Return **up to 20 specific sports picks** — player or team, NFL and/or NBA — each with a short, concrete reason grounded entirely in this pipeline's curated ESPN data: recent performance, matchups, and injury status. No betting odds are collected by this project on purpose — the picks are pure sports analysis, not odds-derived value bets. Example of the target output shape:

> 1. **Chargers @ Bills — combined score over 50 points.** Both teams are averaging 27+ points per game over their last 3; Buffalo's defense has allowed 24+ in back-to-back weeks.
> 2. **Ja'Marr Chase — 5+ receptions.** 7 and 6 receptions in his last two games; Bengals are leaning on the passing game with the run game banged up.
> 3. **Jahmyr Gibbs — 40+ rushing yards.** Averaging 68 rushing yards over his last 3 games; no injury concerns on the report.
> 4. **Nikola Jokić — 10+ rebounds (NBA).** 14, 12, 11, 13 boards in his last four, 35+ minutes in each; Lakers are playing the second night of a back-to-back.
> 5. **Nuggets @ Lakers — combined score over 225 (NBA).** These two have combined for 230 and 236 in their last two games each; neither defense has held an opponent under 110 in a week.

There is no scoring/EV engine and no live odds feed (see [LOTTERYTICKET_SPEC.md](LOTTERYTICKET_SPEC.md) for the earlier, broader design this repo intentionally moved away from — it's kept for history, not as a roadmap). Claude *is* the entire reasoning layer: read the data, apply real sports judgment, explain why in plain terms.

## Data available (query with DuckDB over the Parquet files)

All paths are `data/curated/{table}/league={league}/`, with `league` = `nfl` or `nba` (see `config/leagues.yaml`). Every table is rebuilt fully on each pipeline run and lives in a single file — no history to page through, just query the current picture.

| Table | What's in it |
|---|---|
| `games` | Every game pulled so far this season: `game_id`, `season`, `season_type` (1 pre / 2 regular / 3 post / 5 NBA play-in), `week` (NFL only), `commence_time` (UTC), **`game_date` (US Eastern — use this for "the slate on date X")**, `home_team_id`/`home_team_name`, `away_team_id`/`away_team_name`, `status` (`STATUS_SCHEDULED`/`STATUS_FINAL`/...), `home_score`, `away_score`, `venue`. |
| `player_game_stats` | One row per (player, stat) per **finished** game: `game_id`, `team_id`, `athlete_id`, `athlete_name`, `position` + `starter` (NBA only; null for NFL), `stat_category`, `stat_name`, `stat_value` (raw string), `stat_value_numeric` (parsed float; null for compound values like `"18/25"` or `"4-10"`, which are *also* split into their own numeric rows — e.g. `completions`/`passingAttempts`, `threePointFieldGoalsMade`/`threePointFieldGoalsAttempted`). NFL `stat_category` is `passing`/`rushing`/`receiving`/...; NBA is always `boxscore`. |
| `injuries` | Current injury report: `team_id`, `team_name`, `athlete_name`, `position`, `status` (`Questionable`/`Out`/`Injured Reserve`/...), `injury_detail`, `return_date`. |

## Method

1. **Resolve the slate.** Filter `games` to the requested date with `game_date = 'YYYY-MM-DD'` (not `commence_time`, which is UTC — a 10:30pm ET NBA tip or a Monday Night Football kickoff falls on the next UTC day). Check **both** leagues unless the user named one; on a fall Sunday that's a full NFL slate plus an NBA slate, so mix the two in one ranked list. If nothing matches, say so plainly rather than guessing — don't silently substitute a different date.
2. **For each game**, pull both teams' recent form: query `games` for `home_team_id`/`away_team_id` matching either team, `status = 'STATUS_FINAL'`, ordered by `commence_time` descending, last 3-5 games. Note scoring trends (points scored *and* allowed), home/away splits, and any lopsided results — this is what supports a team-level pick like a combined-score total.
3. **Pull the relevant players.** Query `player_game_stats` for athletes on those two teams' recent finished games. NFL: skill positions (QB/RB/WR/TE), stat categories `passing`/`rushing`/`receiving`, last 2-4 games. NBA: `stat_category = 'boxscore'`, last 4-6 games (more games, smaller samples each) — see the NBA section below for which stats matter. Either way, look at the trend (is usage climbing or dropping?), not just a flat season average that could hide a role change.
4. **Check `injuries`** for every player and team you're about to recommend. A player listed `Out` or `Injured Reserve` should be dropped, not just footnoted. `Questionable` should be mentioned explicitly as a risk in the rationale, since it affects confidence.
5. **State the pick as a concrete threshold**, phrased the way the user actually bets: a player stat line ("5+ receptions", "40+ rushing yards") or a team/game line ("combined score over 50", "wins by double digits"). Pick the threshold yourself from the historical data — there's no live sportsbook number to anchor to, and that's fine; the user checks the actual FanDuel odds themselves before betting.
6. **Rank and select up to 20.** Prioritize picks with the clearest statistical story (consistent recent trend + favorable matchup + clean injury report) over speculative ones. Fewer than 20 is fine on a light slate — don't pad with weak picks to hit the number.
7. **Always caveat appropriately.** This is directional research from historical performance data, not a guaranteed outcome — say that plainly, don't overstate confidence.

## NBA specifics

The method above applies as-is; these are the basketball-specific things to check on top of it.

**Stats** (`stat_category = 'boxscore'`, every one a numeric `stat_name`): `points`, `rebounds`, `assists`, `threePointFieldGoalsMade`, `steals`, `blocks`, `turnovers`, `minutes`, plus `offensiveRebounds`/`defensiveRebounds`, `fieldGoalsMade`/`fieldGoalsAttempted`, `freeThrowsMade`/`freeThrowsAttempted`, `plusMinus`. Combos the user is likely to bet ("25+ points + rebounds + assists", "8+ rebounds + assists") are just sums of those rows per `game_id` — compute them, don't guess.

**Minutes first.** NBA production follows minutes more than anything else. Before recommending any player line, check `minutes` over the last 4-6 games and the `starter` flag: a player who just moved into the starting lineup (or out of it) has a different role than their season average says. A player with a missing row in a recent game didn't play (DNP — ESPN sends no stats), which is itself a signal. Big swings in minutes can also mean blowouts — check the final margin in `games` before reading a low-minutes game as a role change.

**Back-to-backs and rest.** From `games`, check whether either team played the day before `game_date` (or plays three games in four nights). Teams on the second night of a back-to-back often rest stars or limit minutes and tend to defend worse late — relevant both for player lines (risk) and game totals (opponent upside). Mention it explicitly when it applies.

**Game totals.** NBA combined scores live around 210-240. Base a totals pick on both teams' last 5+ results (points scored *and* allowed), and say what the recent combined numbers actually were. Don't treat the NFL ranges as meaningful here, or vice versa.

**Injuries matter more, and change late.** One absence reshapes an NBA rotation far more than an NFL depth chart — a star being `Out` usually means more shots/minutes for the teammates who replace him (call that out as a reason, if the data from games he missed backs it up). NBA injury reports update through game day and `Questionable`/`Day-To-Day` players are frequently decided at shootaround, so flag those clearly and remind the user to confirm before tip-off.

**Season labelling.** ESPN labels an NBA season by the year it ends — the 2026-27 season has `season = 2027`. Filter `season_type = 2` (regular season) or `3`/`5` for playoffs/play-in so preseason games never leak into "recent form".

**Early season.** In the first couple of weeks, there are only a handful of games per team. Say so, size thresholds conservatively, and prefer players whose role is unambiguous.

## What NOT to do

- Don't fabricate a stat that isn't actually in the curated data.
- Don't recommend a player who's `Out`/`Injured Reserve` in `injuries`.
- Don't treat a single big game as a "trend" — look at at least 2-3 recent games (NFL) or 4-5 (NBA) before projecting.
- Don't slate games by the UTC date in `commence_time` — use `game_date`.
- Don't reference betting odds, lines, or "value" against a sportsbook price — this pipeline doesn't collect any of that anymore, on purpose. Picks are framed as sports predictions, not EV calculations.
