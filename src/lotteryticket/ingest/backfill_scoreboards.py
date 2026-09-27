"""One-off / on-demand backfill of past-week ESPN scoreboards into raw storage.
Run via:
python -m lotteryticket.ingest.backfill_scoreboards --season 2026 --weeks 1-2
Then: curate -> player_box_scores -> curate.
"""
from __future__ import annotations

import argparse
import json

from lotteryticket.clients.espn import ESPNClient
from lotteryticket.util.io import load_yaml, write_raw_json
from lotteryticket.util.time import date_stamp, time_stamp


def _parse_weeks(spec: str) -> list[int]:
    weeks: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            weeks.extend(range(int(lo), int(hi) + 1))
        elif part:
            weeks.append(int(part))
    return sorted(set(weeks))


def run(season: int, weeks: list[int], seasontype: int = 2, league_key: str = "nfl") -> dict:
    config = load_yaml("leagues.yaml")
    league = next(l for l in config["active"] if l["key"] == league_key)
    espn_path = league["espn_path"]

    client = ESPNClient()
    ds, ts = date_stamp(), time_stamp()

    results = []
    for week in weeks:
        scoreboard = client.get_scoreboard_week(espn_path, season, week, seasontype)
        events = (scoreboard or {}).get("events", [])
        if not events:
            print(f"[WARN] {league_key} {season} wk{week}: no events returned, skipped")
            continue
        path = write_raw_json(
            "espn_scoreboard", league_key, scoreboard, ds, ts,
            name=f"s{season}t{seasontype}w{week:02d}",
        )
        print(f"[INFO] {league_key} {season} wk{week}: {len(events)} events -> {path}")
        results.append({"week": week, "events": len(events), "path": str(path)})

    return {"league": league_key, "season": season, "seasontype": seasontype, "weeks": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill past ESPN scoreboards")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--weeks", default="1-2", help="e.g. '1-2' or '1,2,5-7'")
    parser.add_argument("--seasontype", type=int, default=2)
    parser.add_argument("--league", default="nfl")
    args = parser.parse_args()
    print(json.dumps(run(args.season, _parse_weeks(args.weeks), args.seasontype, args.league), indent=2))


if __name__ == "__main__":
    main()
