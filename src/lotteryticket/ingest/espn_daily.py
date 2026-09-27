"""Pull today's scoreboard (+ best-effort injuries) for every active league and
write the raw response immutably. Run via:
python -m lotteryticket.ingest.espn_daily
"""
from __future__ import annotations

import json

from lotteryticket.clients.espn import ESPNClient
from lotteryticket.util.io import load_yaml, write_raw_json
from lotteryticket.util.time import date_stamp, time_stamp


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
        scoreboard = client.get_scoreboard(espn_path)
        events = (scoreboard or {}).get("events", [])
        scoreboard_path = write_raw_json("espn_scoreboard", key, scoreboard or {}, ds, ts)
        print(f"[INFO] {key}: {len(events)} scoreboard events -> {scoreboard_path}")

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
                "scoreboard_events": len(events),
                "scoreboard_path": str(scoreboard_path),
                "injuries_path": str(injuries_path) if injuries_path else None,
            }
        )

    return {"date": ds, "time": ts, "leagues": results}


def main() -> None:
    outputs = run()
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
