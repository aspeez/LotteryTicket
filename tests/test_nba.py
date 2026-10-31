"""NBA parsing + daily-scoreboard date selection. NBA fixtures are hand-built to
ESPN's response shape (see the `_note` key in each) — swap in captured responses
when convenient."""
import json
from datetime import date
from pathlib import Path

from lotteryticket.ingest.espn_daily import daily_dates_to_fetch
from lotteryticket.transform.curate import _parse_games, _parse_injuries, _parse_player_game_stats

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_nba_games_uses_eastern_game_date():
    games = _parse_games("nba", _load("espn_scoreboard_nba_sample.json"))
    assert len(games) == 1
    g = games[0]
    assert g["home_team_name"] == "Los Angeles Lakers"
    assert g["away_team_id"] == "7"
    assert (g["home_score"], g["away_score"]) == (112, 118)
    assert g["status"] == "STATUS_FINAL"
    assert g["season"] == 2027 and g["season_type"] == 2
    assert g["week"] is None
    # 7:30pm PT tip on Oct 30 is 02:30Z on Oct 31 — the slate date must stay Oct 30
    assert g["commence_time"] == "2026-10-31T02:30Z"
    assert g["game_date"] == "2026-10-30"


def test_parse_nba_box_score():
    rows = _parse_player_game_stats("nba", "401810123", _load("espn_summary_nba_sample.json"))

    def stat(name, key):
        return next(
            r["stat_value_numeric"] for r in rows if r["athlete_name"] == name and r["stat_name"] == key
        )

    assert stat("Nikola Jokic", "points") == 32.0
    assert stat("Nikola Jokic", "rebounds") == 14.0
    assert stat("Nikola Jokic", "assists") == 11.0
    assert stat("Nikola Jokic", "minutes") == 37.0
    assert stat("Jamal Murray", "plusMinus") == 4.0
    # made/attempted pairs are split into their own numeric stats
    assert stat("Jamal Murray", "threePointFieldGoalsMade") == 4.0
    assert stat("Jamal Murray", "threePointFieldGoalsAttempted") == 10.0
    combined = next(
        r for r in rows
        if r["athlete_name"] == "Jamal Murray"
        and r["stat_name"] == "threePointFieldGoalsMade-threePointFieldGoalsAttempted"
    )
    assert combined["stat_value"] == "4-10" and combined["stat_value_numeric"] is None

    jokic = next(r for r in rows if r["athlete_name"] == "Nikola Jokic")
    assert jokic["stat_category"] == "boxscore"
    assert jokic["position"] == "C"
    assert jokic["starter"] is True
    assert jokic["team_id"] == "7"
    # DNPs carry no stats and produce no rows
    assert not any(r["athlete_name"] == "Bench Guy" for r in rows)


def test_parse_nba_injuries():
    rows = _parse_injuries("nba", _load("espn_injuries_nba_sample.json"))
    assert len(rows) == 1
    assert rows[0]["athlete_name"] == "Austin Reaves"
    assert rows[0]["status"] == "Out"
    assert rows[0]["team_id"] == "13"


def test_nfl_completions_split_into_numeric_halves():
    rows = _parse_player_game_stats("nfl", "401872948", _load("espn_summary_nfl_sample.json"))
    passing = {r["stat_name"]: r for r in rows if r["stat_category"] == "passing"}
    assert passing["completions"]["stat_value_numeric"] == 18.0
    assert passing["passingAttempts"]["stat_value_numeric"] == 25.0


def _raw(tmp_path, fetched_on, scoreboard_day):
    d = tmp_path / fetched_on
    d.mkdir(exist_ok=True)
    p = d / f"100000_d{scoreboard_day}.json.gz"
    p.touch()
    return p


def test_daily_dates_window_only_when_no_season_start():
    assert daily_dates_to_fetch(date(2026, 10, 31), None, []) == [
        date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1),
    ]


def test_daily_dates_backfills_dates_not_fetched_after_they_ended(tmp_path):
    paths = [
        _raw(tmp_path, "2026-10-26", "20261025"),  # fetched the day after: covered
        _raw(tmp_path, "2026-10-26", "20261026"),  # only fetched same day: needs refetch
        _raw(tmp_path, "2026-10-26", "20261027"),  # only fetched the day before: needs refetch
    ]
    dates = daily_dates_to_fetch(date(2026, 10, 29), date(2026, 10, 25), paths)
    assert dates == [
        date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28),
        date(2026, 10, 29), date(2026, 10, 30),
    ]
