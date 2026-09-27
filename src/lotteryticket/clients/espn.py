from __future__ import annotations

import time
from typing import Any

import requests

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
USER_AGENT = "LotteryTicket/1.0 (+https://github.com/aspeez/LotteryTicket; personal research use)"
MIN_REQUEST_INTERVAL_SECONDS = 1.0


class ESPNClient:
    """Client for ESPN's public but unofficial/undocumented endpoints. These can
    change shape without notice, so every parser downstream should be validated
    against saved fixtures (see tests/fixtures/) rather than trusted blindly.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request_at: float = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def _get(self, url: str, params: dict | None = None, timeout: int = 30, retries: int = 3) -> dict[str, Any] | None:
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._rate_limit()
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
                self._last_request_at = time.monotonic()
                if attempt < retries - 1:
                    time.sleep(2**attempt)
        print(f"[WARN] ESPN request failed after {retries} attempts ({url}): {last_exc}")
        return None

    def get_scoreboard(self, espn_path: str, date: str | None = None) -> dict[str, Any] | None:
        """espn_path like 'football/nfl'. date is YYYYMMDD; omit for today."""
        url = f"{ESPN_BASE_URL}/{espn_path}/scoreboard"
        params = {"dates": date} if date else None
        return self._get(url, params=params)

    def get_scoreboard_week(
        self, espn_path: str, season: int, week: int, seasontype: int = 2
    ) -> dict[str, Any] | None:
        """Scoreboard for a specific season/week. seasontype: 1=pre, 2=regular, 3=post."""
        url = f"{ESPN_BASE_URL}/{espn_path}/scoreboard"
        return self._get(url, params={"dates": season, "seasontype": seasontype, "week": week})

    def get_teams(self, espn_path: str) -> dict[str, Any] | None:
        url = f"{ESPN_BASE_URL}/{espn_path}/teams"
        return self._get(url)

    def get_injuries(self, espn_path: str) -> dict[str, Any] | None:
        """Not all leagues expose this — treat None as "unavailable", not an error."""
        url = f"{ESPN_BASE_URL}/{espn_path}/injuries"
        return self._get(url)

    def get_summary(self, espn_path: str, event_id: str) -> dict[str, Any] | None:
        url = f"{ESPN_BASE_URL}/{espn_path}/summary"
        return self._get(url, params={"event": event_id})
