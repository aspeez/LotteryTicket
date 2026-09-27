"""Fetch ESPN box scores for finished games so per-player stats can be curated.
Skips games already fetched (tracked via event id embedded in the raw filename)
so a full season doesn't get re-downloaded every day.

Reads the curated `games` state table, so run this *after* espn_daily has produced
at least one games.parquet. Run via:
python -m lotteryticket.ingest.player_box_scores
"""
from __future__ import annotations

import json

import pyarrow.parquet as pq

from lotteryticket.clients.espn import ESPNClient
from lotteryticket.util.io import curated_path, list_raw_json, load_yaml, write_raw_json
from lotteryticket.util.time import date_stamp, time_stamp

FINISHED_STATUSES = {"STATUS_FINAL"}


def _already_fetched_event_ids(league: str) -> set[str]:
    ids = set()
    for path in list_raw_json("espn_summary", league):
        stem = path.name.removesuffix(".json.gz")
        if "_" in stem:
            ids.add(stem.split("_", 1)[1])
    return ids


def _finished_game_ids(league: str) -> list[str]:
    path = curated_path("games", league) / "games.parquet"
    if not path.exists():
        return []
    # ParquetFile(path).read(), not pq.read_table(path): the latter goes through
    # pyarrow's dataset/partition-discovery machinery, which misreads the
    # "league=nfl" directory segment as a Hive partition column and collides with
    # the real "league" data column already inside the file.
    rows = pq.ParquetFile(path).read().to_pylist()
    return [row["game_id"] for row in rows if row.get("status") in FINISHED_STATUSES]


def run() -> dict:
    config = load_yaml("leagues.yaml")
    active_leagues = config["active"]

    client = ESPNClient()
    ds, ts = date_stamp(), time_stamp()

    results = []
    for league in active_leagues:
        key = league["key"]
        espn_path = league["espn_path"]

        finished_ids = _finished_game_ids(key)
        already_fetched = _already_fetched_event_ids(key)
        to_fetch = [gid for gid in finished_ids if gid not in already_fetched]

        print(f"[INFO] {key}: {len(finished_ids)} finished games, {len(to_fetch)} new box scores to fetch")

        fetched = 0
        for event_id in to_fetch:
            summary = client.get_summary(espn_path, event_id)
            if summary is None:
                continue
            write_raw_json("espn_summary", key, summary, ds, ts, name=event_id)
            fetched += 1

        results.append({"league": key, "finished_games": len(finished_ids), "box_scores_fetched": fetched})

    return {"date": ds, "time": ts, "leagues": results}


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
