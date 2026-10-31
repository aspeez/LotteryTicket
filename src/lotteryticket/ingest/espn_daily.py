"""Pull the current scoreboard (+ best-effort injuries) for every active league and
write the raw responses immutably. Run via:
python -m lotteryticket.ingest.espn_daily

Two scoreboard modes, set per league in config/leagues.yaml:

- `weekly` (NFL): one undated call — ESPN returns the whole current week.
- `daily` (NBA): ESPN's undated call is a single day, so instead fetch
  yesterday/today/tomorrow by explicit date (written as `{time}_d{YYYYMMDD}`),
  plus any date since `season_start` that hasn't yet been fetched *after* that
  date ended. That auto-backfills the season on the first run and heals a
  missed workflow day, without re-pulling the whole season every day.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from lotteryticket.clients.espn import ESPNClient
from lotteryticket.util.io import list_raw_json, load_yaml, write_raw_json
from lotteryticket.util.time import date_stamp, time_stamp, utc_now

DAILY_WINDOW_DAYS = (-1, 0, 1)


def _dated_snapshots(paths: list[Path]) -> dict[date, date]:
    """Map scoreboard date -> latest raw-partition date it was fetched on, for
    raw files named `{time}_d{YYYYMMDD}.json.gz` under `{YYYY-MM-DD}/`."""
    latest_fetch: dict[date, date] = {}
    for path in paths:
        stem = path.name.removesuffix(".json.gz")
        if "_d" not in stem:
            continue
        try:
            scoreboard_day = datetime.strptime(stem.split("_d", 1)[1], "%Y%m%d").date()
            fetched_on = datetime.strptime(path.parent.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        prev = latest_fetch.get(scoreboard_day)
        if prev is None or fetched_on > prev:
            latest_fetch[scoreboard_day] = fetched_on
    return latest_fetch


def daily_dates_to_fetch(
    today: date, season_start: date | None, raw_paths: list[Path]
) -> list[date]:
    """Dates to pull for a `daily`-mode league: the rolling window around today,
    plus every past date since season_start not yet fetched on a later day."""
    wanted = {today + timedelta(days=d) for d in DAILY_WINDOW_DAYS}
    if season_start is not None:
        fetched = _dated_snapshots(raw_paths)
        day = season_start
        while day < today:
            last_fetch = fetched.get(day)
            if last_fetch is None or last_fetch <= day:
                wanted.add(day)
            day += timedelta(days=1)
    return sorted(wanted)


def _fetch_scoreboards(client: ESPNClient, league: dict, ds: str, ts: str) -> list[dict]:
    key = league["key"]
    espn_path = league["espn_path"]
    mode = league.get("scoreboard_mode", "weekly")

    if mode == "weekly":
        scoreboard = client.get_scoreboard(espn_path)
        events = (scoreboard or {}).get("events", [])
        path = write_raw_json("espn_scoreboard", key, scoreboard or {}, ds, ts)
        print(f"[INFO] {key}: {len(events)} scoreboard events -> {path}")
        return [{"events": len(events), "path": str(path)}]

    if mode != "daily":
        raise ValueError(f"Unknown scoreboard_mode {mode!r} for league {key}")

    season_start = league.get("season_start")
    season_start_date = date.fromisoformat(str(season_start)) if season_start else None
    today = utc_now().date()
    dates = daily_dates_to_fetch(today, season_start_date, list_raw_json("espn_scoreboard", key))

    out = []
    for day in dates:
        stamp = day.strftime("%Y%m%d")
        scoreboard = client.get_scoreboard(espn_path, date=stamp)
        if scoreboard is None:
            # Don't write an empty file — that would mark the date as covered.
            print(f"[WARN] {key} {stamp}: scoreboard fetch failed, will retry next run")
            continue
        events = scoreboard.get("events", [])
        path = write_raw_json("espn_scoreboard", key, scoreboard, ds, ts, name=f"d{stamp}")
        print(f"[INFO] {key} {stamp}: {len(events)} scoreboard events -> {path}")
        out.append({"date": stamp, "events": len(events), "path": str(path)})
    return out


def run() -> dict:
    config = load_yaml("leagues.yaml")
    active_leagues = config["active"]

    client = ESPNClient()
    ds, ts = date_stamp(), time_stamp()

    results = []
    for league in active_leagues:
        key = league["key"]
        espn_path = league["espn_path"]

        print(f"[INFO] Fetching {key} scoreboard from ESPN ({espn_path})...")
        scoreboards = _fetch_scoreboards(client, league, ds, ts)

        print(f"[INFO] Fetching {key} injuries from ESPN...")
        injuries = client.get_injuries(espn_path)
        injuries_path = None
        if injuries is not None:
            injuries_path = write_raw_json("espn_injuries", key, injuries, ds, ts)
            print(f"[INFO] {key}: injuries -> {injuries_path}")
        else:
            print(f"[INFO] {key}: injuries endpoint unavailable, skipped")

        results.append(
            {
                "league": key,
                "scoreboards": scoreboards,
                "injuries_path": str(injuries_path) if injuries_path else None,
            }
        )

    return {"date": ds, "time": ts, "leagues": results}


def main() -> None:
    outputs = run()
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
