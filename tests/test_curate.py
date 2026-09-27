import json
from pathlib import Path

from lotteryticket.transform.curate import _accumulate_games, _parse_games, _parse_injuries

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


def _scoreboard_event(game_id, status, home_score, away_score, commence_time="2026-09-14T17:00Z"):
    return {
        "events": [
            {
                "id": game_id,
                "date": commence_time,
                "season": {"year": 2026},
                "week": {"number": 1},
                "competitions": [
                    {
                        "status": {"type": {"name": status}},
                        "venue": {"fullName": "Test Stadium"},
                        "neutralSite": False,
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": str(home_score),
                                "team": {"id": "9", "displayName": "Green Bay Packers"},
                            },
                            {
                                "homeAway": "away",
                                "score": str(away_score),
                                "team": {"id": "6", "displayName": "Dallas Cowboys"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_accumulate_games_dedupes_and_keeps_the_newer_snapshot():
    older_snapshot = _scoreboard_event("game-A", "STATUS_SCHEDULED", 0, 0, "2026-09-14T17:00Z")
    # Newer snapshot: game-A is now FINAL with a real score, and a second game (game-B,
    # from a later week) has appeared that the older snapshot never had.
    newer_snapshot = {
        "events": [
            _scoreboard_event("game-A", "STATUS_FINAL", 24, 17, "2026-09-14T17:00Z")["events"][0],
            _scoreboard_event("game-B", "STATUS_SCHEDULED", 0, 0, "2026-09-21T17:00Z")["events"][0],
        ]
    }

    games = _accumulate_games("nfl", [older_snapshot, newer_snapshot])

    assert [g["game_id"] for g in games] == ["game-A", "game-B"]
    game_a = games[0]
    assert game_a["status"] == "STATUS_FINAL"
    assert game_a["home_score"] == 24
    assert game_a["away_score"] == 17


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
