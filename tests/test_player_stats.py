import json
from pathlib import Path

from lotteryticket.transform.curate import _parse_player_game_stats

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_player_game_stats_against_espn_fixture():
    summary = json.loads((FIXTURES / "espn_summary_nfl_sample.json").read_text())
    rows = _parse_player_game_stats("nfl", "401872948", summary)

    receiving_yards = {
        r["athlete_name"]: r["stat_value_numeric"]
        for r in rows
        if r["stat_category"] == "receiving" and r["stat_name"] == "receivingYards"
    }
    assert receiving_yards["Drake London"] == 194.0
    assert receiving_yards["Bijan Robinson"] == 19.0

    rushing_yards = {
        r["athlete_name"]: r["stat_value_numeric"]
        for r in rows
        if r["stat_category"] == "rushing" and r["stat_name"] == "rushingYards"
    }
    assert rushing_yards["Bijan Robinson"] == 194.0

    # completions/attempts ("18/25") should be kept as-is, not coerced to a float
    comp_att = next(r for r in rows if r["stat_name"] == "completions/passingAttempts")
    assert comp_att["stat_value"] == "18/25"
    assert comp_att["stat_value_numeric"] is None
    assert comp_att["game_id"] == "401872948"
