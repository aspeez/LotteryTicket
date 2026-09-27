"""Regression test: curated tables are rebuilt fully each run and written to a
fixed filename, so re-curating the same day never duplicates rows. See the
module docstring in transform/curate.py."""
import pyarrow.parquet as pq

from lotteryticket.transform.curate import _write_state


def test_write_state_overwrites_same_file_on_repeated_calls(tmp_path, monkeypatch):
    import lotteryticket.transform.curate as curate_module

    monkeypatch.setattr(curate_module, "curated_path", lambda table, league: tmp_path)

    _write_state("games", "nfl", [{"game_id": "1"}, {"game_id": "2"}])
    _write_state("games", "nfl", [{"game_id": "1"}, {"game_id": "2"}, {"game_id": "3"}])

    files = list(tmp_path.glob("*.parquet"))
    assert len(files) == 1
    assert len(pq.read_table(files[0])) == 3
