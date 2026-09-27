from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def date_stamp(dt: datetime | None = None) -> str:
    """YYYY-MM-DD, used for raw-data partition directories."""
    return (dt or utc_now()).strftime("%Y-%m-%d")


def time_stamp(dt: datetime | None = None) -> str:
    """HHMMSS, used for raw-data filenames within a day."""
    return (dt or utc_now()).strftime("%H%M%S")
