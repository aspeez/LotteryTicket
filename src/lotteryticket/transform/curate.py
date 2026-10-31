"""Raw ESPN JSON -> curated Parquet.

Every curated table here is a STATE table: rebuilt fully from all raw data on
every run and written to a fixed filename. Re-running never duplicates rows —
it just replaces the current snapshot of "what we know right now". There's no
time-series data to append (no odds/lines being tracked over time — see
docs/LOTTERY_TICKET_PLAYBOOK.md for why this pipeline is ESPN-only).

`games` is the one table built from *every* raw scoreboard snapshot ever
written, not just the latest — ESPN's scoreboard endpoint only returns the
current week, so a game would otherwise disappear from `games` (and its box
score would become permanently unreachable) the moment the next week starts.
Snapshots are merged oldest-first so a newer snapshot of the same game_id
(e.g. SCHEDULED -> FINAL) always overwrites the older one.

Run via: python -m lotteryticket.transform.curate
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from lotteryticket.util.io import curated_path, latest_raw_json, list_raw_json, load_yaml, read_raw_json
from lotteryticket.util.time import utc_now


# US sports schedules are set in Eastern time; a 10pm ET tip-off (or a Monday Night
# Football kickoff) is already "tomorrow" in UTC, so slate-by-date uses this instead.
SCHEDULE_TZ = ZoneInfo("America/New_York")


def _local_game_date(commence_time: str | None) -> str | None:
    """ESPN's ISO UTC timestamp ('2026-10-30T00:15Z') -> Eastern date ('2026-10-29')."""
    if not commence_time:
        return None
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(SCHEDULE_TZ).date().isoformat()


def _parse_games(league: str, scoreboard: dict[str, Any]) -> list[dict[str, Any]]:
    games = []
    for event in scoreboard.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competition = competitions[0]
        competitors = {c.get("homeAway"): c for c in competition.get("competitors", [])}
        home = competitors.get("home", {})
        away = competitors.get("away", {})

        def _score(c: dict) -> int | None:
            raw = c.get("score")
            try:
                return int(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None

        games.append(
            {
                "game_id": event.get("id"),
                "league": league,
                "season": (event.get("season") or {}).get("year"),
                # 1=preseason, 2=regular, 3=postseason, 5=NBA play-in (ESPN's codes)
                "season_type": (event.get("season") or {}).get("type"),
                # NFL only; null for day-scheduled leagues like the NBA
                "week": (event.get("week") or {}).get("number"),
                "commence_time": event.get("date"),
                "game_date": _local_game_date(event.get("date")),
                "home_team_id": (home.get("team") or {}).get("id"),
                "home_team_name": (home.get("team") or {}).get("displayName"),
                "away_team_id": (away.get("team") or {}).get("id"),
                "away_team_name": (away.get("team") or {}).get("displayName"),
                "status": ((competition.get("status") or {}).get("type") or {}).get("name"),
                "home_score": _score(home),
                "away_score": _score(away),
                "venue": (competition.get("venue") or {}).get("fullName"),
                "neutral_site": competition.get("neutralSite", False),
            }
        )
    return games


def _accumulate_games(league: str, scoreboards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge every raw scoreboard snapshot (oldest first) into one deduplicated,
    chronologically sorted games list. A later snapshot of the same game_id always
    wins — see the module docstring for why this needs to span every snapshot ever
    pulled, not just the latest."""
    games_by_id: dict[str, dict[str, Any]] = {}
    for scoreboard in scoreboards:
        for g in _parse_games(league, scoreboard):
            games_by_id[g["game_id"]] = g
    return sorted(games_by_id.values(), key=lambda g: g.get("commence_time") or "")


def _parse_injuries(league: str, injuries_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team_block in injuries_payload.get("injuries", []):
        team_id = team_block.get("id")
        team_name = team_block.get("displayName")
        for injury in team_block.get("injuries", []):
            athlete = injury.get("athlete", {})
            injury_type = injury.get("type", {}) or {}
            details = injury.get("details", {}) or {}
            rows.append(
                {
                    "league": league,
                    "team_id": team_id,
                    "team_name": team_name,
                    "athlete_name": athlete.get("displayName"),
                    "position": (athlete.get("position") or {}).get("abbreviation"),
                    "status": injury.get("status"),
                    "status_abbreviation": injury_type.get("abbreviation"),
                    "injury_detail": details.get("type"),
                    "return_date": details.get("returnDate"),
                    "short_comment": injury.get("shortComment"),
                    "report_date": injury.get("date"),
                }
            )
    return rows


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_compound(key: str, value: Any) -> list[tuple[str, float]]:
    """ESPN packs made/attempted pairs into one cell: NBA
    'threePointFieldGoalsMade-threePointFieldGoalsAttempted' = '3-8', NFL
    'completions/passingAttempts' = '18/25'. Return each half as its own numeric
    stat so 'made 3+ threes' is queryable; [] if it isn't a clean pair."""
    for sep in ("-", "/"):
        if sep not in key or not isinstance(value, str):
            continue
        key_parts = key.split(sep)
        value_parts = value.split(sep)
        if len(key_parts) != 2 or len(value_parts) != 2 or not all(key_parts):
            continue
        nums = [_to_float(v) for v in value_parts]
        if any(n is None for n in nums):
            continue
        return list(zip(key_parts, nums))  # type: ignore[arg-type]
    return []


def _parse_player_game_stats(league: str, game_id: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Works for both leagues' box-score shapes: NFL splits stats into named
    categories (passing/rushing/receiving/...); the NBA has one unnamed block of
    per-player stats, curated as stat_category='boxscore'. Players who didn't play
    (NBA DNPs) come back with an empty stats list and produce no rows."""
    rows: list[dict[str, Any]] = []
    boxscore = summary.get("boxscore", {})
    for team_block in boxscore.get("players", []):
        team_id = (team_block.get("team") or {}).get("id")
        for stat_category in team_block.get("statistics", []):
            category = stat_category.get("name") or "boxscore"
            keys = stat_category.get("keys", [])
            labels = stat_category.get("labels") or keys
            for athlete_entry in stat_category.get("athletes", []):
                athlete = athlete_entry.get("athlete", {})
                base = {
                    "game_id": game_id,
                    "league": league,
                    "team_id": team_id,
                    "athlete_id": athlete.get("id"),
                    "athlete_name": athlete.get("displayName"),
                    # Present in NBA box scores; null for NFL, which doesn't send them
                    "position": (athlete.get("position") or {}).get("abbreviation"),
                    "starter": athlete_entry.get("starter"),
                    "stat_category": category,
                }
                for key, label, value in zip(keys, labels, athlete_entry.get("stats", [])):
                    rows.append(
                        {
                            **base,
                            "stat_name": key,
                            "stat_label": label,
                            "stat_value": value,
                            "stat_value_numeric": _to_float(value),
                        }
                    )
                    for part_key, part_value in _split_compound(key, value):
                        rows.append(
                            {
                                **base,
                                "stat_name": part_key,
                                "stat_label": f"{label} ({part_key})",
                                "stat_value": value,
                                "stat_value_numeric": part_value,
                            }
                        )
    return rows


def _write_state(table: str, league: str, records: list[dict[str, Any]]) -> str | None:
    """Fixed filename, fully replaced each run — see module docstring."""
    if not records:
        return None
    path = curated_path(table, league) / f"{table}.parquet"
    pq.write_table(pa.Table.from_pylist(records), path)
    return str(path)


def run(league_key: str | None = None) -> dict:
    config = load_yaml("leagues.yaml")
    leagues = config["active"]
    if league_key:
        leagues = [l for l in leagues if l["key"] == league_key]

    captured_at = utc_now().isoformat()
    results = []

    for league in leagues:
        key = league["key"]

        scoreboard_paths = list_raw_json("espn_scoreboard", key)
        if not scoreboard_paths:
            print(f"[WARN] No ESPN scoreboard raw data for {key} yet, skipping")
            continue

        games = _accumulate_games(key, [read_raw_json(sp) for sp in scoreboard_paths])

        injuries_path_raw = latest_raw_json("espn_injuries", key)
        injuries_rows = _parse_injuries(key, read_raw_json(injuries_path_raw)) if injuries_path_raw else []

        player_stats_rows: list[dict[str, Any]] = []
        for summary_path in list_raw_json("espn_summary", key):
            stem = summary_path.name.removesuffix(".json.gz")
            if "_" not in stem:
                continue
            event_id = stem.split("_", 1)[1]
            summary = read_raw_json(summary_path)
            player_stats_rows.extend(_parse_player_game_stats(key, event_id, summary))

        games_path = _write_state("games", key, games)
        injuries_curated_path = _write_state("injuries", key, injuries_rows)
        player_stats_path = _write_state("player_game_stats", key, player_stats_rows)

        results.append(
            {
                "league": key,
                "games": len(games),
                "games_path": games_path,
                "injuries_rows": len(injuries_rows),
                "injuries_path": injuries_curated_path,
                "player_game_stats_rows": len(player_stats_rows),
                "player_game_stats_path": player_stats_path,
            }
        )

    return {"captured_at": captured_at, "leagues": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate raw ESPN JSON into Parquet tables")
    parser.add_argument("--league", default=None, help="Curate a single league key, e.g. nfl")
    args = parser.parse_args()
    print(json.dumps(run(args.league), indent=2))


if __name__ == "__main__":
    main()
