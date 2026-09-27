import json
from pathlib import Path

from lotteryticket.transform.curate import _parse_games, _parse_injuries

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_games_against_espn_fixture():
    scoreboard = json.loads((FIXTURES / "espn_scoreboard_nfl_sample.json").read_text())
    games = _parse_games("nfl", scoreboard)

    assert len(games) == 1
    game = games[0]
    assert game["game_id"] == "401671789"
    assert game["home_team_id"] == "9"
    assert game["home_team_name"] == "Green Bay Packers"
    assert game["away_team_id"] == "6"
    assert game["away_team_name"] == "Dallas Cowboys"
    assert game["season"] == 2026
    assert game["week"] == 4
    assert game["status"] == "STATUS_SCHEDULED"
    assert game["venue"] == "Lambeau Field"
    assert game["neutral_site"] is False


def test_parse_injuries_against_espn_fixture():
    injuries_payload = json.loads((FIXTURES / "espn_injuries_nfl_sample.json").read_text())
    rows = _parse_injuries("nfl", injuries_payload)

    assert len(rows) == 1
    row = rows[0]
    assert row["team_name"] == "Arizona Cardinals"
    assert row["athlete_name"] == "Roy Lopez"
    assert row["position"] == "DT"
    assert row["status"] == "Questionable"
    assert row["injury_detail"] == "Groin"
    assert row["return_date"] == "2026-09-27"
