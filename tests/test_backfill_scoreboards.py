from lotteryticket.ingest.backfill_scoreboards import _parse_weeks


def test_parse_weeks_range():
    assert _parse_weeks("1-2") == [1, 2]


def test_parse_weeks_mixed_list_and_range():
    assert _parse_weeks("1,3-4") == [1, 3, 4]


def test_parse_weeks_dedupes_and_sorts():
    assert _parse_weeks("3,1-2,2") == [1, 2, 3]
