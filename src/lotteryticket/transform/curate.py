"""Raw ESPN JSON -> curated Parquet.

Every curated table here is a STATE table: rebuilt fully from all raw data on
every run and written to a fixed filename. Re-running never duplicates rows —
it just replaces the current snapshot of "what we know right now". There's no
time-series data to append (no odds/lines being tracked over time — see
docs/LOTTERY_TICKET_PLAYBOOK.md for why this pipeline is ESPN-only).

Run via: python -m lotteryticket.transform.curate
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from lotteryticket.util.io import curated_path, latest_raw_json, list_raw_json, load_yaml, read_raw_json
from lotteryticket.util.time import utc_now


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
                "week": (event.get("week") or {}).get("number"),
                "commence_time": event.get("date"),
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


def _parse_player_game_stats(league: str, game_id: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    boxscore = summary.get("boxscore", {})
    for team_block in boxscore.get("players", []):
        team_id = (team_block.get("team") or {}).get("id")
        for stat_category in team_block.get("statistics", []):
            category = stat_category.get("name")
            keys = stat_category.get("keys", [])
            labels = stat_category.get("labels", keys)
            for athlete_entry in stat_category.get("athletes", []):
                athlete = athlete_entry.get("athlete", {})
                values = athlete_entry.get("stats", [])
                for key, label, value in zip(keys, labels, values):
                    numeric: float | None
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        numeric = None
                    rows.append(
                        {
                            "game_id": game_id,
                            "league": league,
                            "team_id": team_id,
                            "athlete_id": athlete.get("id"),
                            "athlete_name": athlete.get("displayName"),
                            "stat_category": category,
                            "stat_name": key,
                            "stat_label": label,
                            "stat_value": value,
                            "stat_value_numeric": numeric,
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

        scoreboard_path = latest_raw_json("espn_scoreboard", key)
        if scoreboard_path is None:
            print(f"[WARN] No ESPN scoreboard raw data for {key} yet, skipping")
            continue

        scoreboard = read_raw_json(scoreboard_path)
        games = _parse_games(key, scoreboard)

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
