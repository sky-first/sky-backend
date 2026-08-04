"""Unit tests for the Console revenue MTD / EOM-projection helper.

``_month_to_date_and_projection`` is a pure function so the arithmetic
(month filtering + linear extrapolation) is tested without standing up
the FastAPI app or mocking Cost Explorer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.api.v1.console import _month_to_date_and_projection
from src.services.console_telemetry import TimeseriesPoint


def test_mtd_filters_current_month_and_projects_linearly():
    # Day 10 of a 31-day month.
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    daily = [
        TimeseriesPoint(t="2026-06-28T00:00:00+00:00", value=99.0),  # prev month
        TimeseriesPoint(t="2026-06-30T00:00:00+00:00", value=99.0),  # prev month
        TimeseriesPoint(t="2026-07-01T00:00:00+00:00", value=2.0),
        TimeseriesPoint(t="2026-07-05T00:00:00+00:00", value=3.0),
        TimeseriesPoint(t="2026-07-10T00:00:00+00:00", value=5.0),
    ]

    mtd, projection = _month_to_date_and_projection(daily, now)

    # June points excluded → MTD = 2 + 3 + 5.
    assert mtd == 10.0
    # 10 / 10 days elapsed * 31 days in month = 31.0.
    assert projection == 31.0


def test_projection_empty_series_is_zero_not_error():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    mtd, projection = _month_to_date_and_projection([], now)
    assert mtd == 0.0
    assert projection == 0.0


def test_first_of_month_does_not_divide_by_zero():
    # day==1 → days_elapsed clamps to 1, projection = day1 * days_in_month.
    now = datetime(2026, 2, 1, 6, 0, tzinfo=timezone.utc)  # Feb 2026 = 28 days
    daily = [TimeseriesPoint(t="2026-02-01T00:00:00+00:00", value=4.0)]

    mtd, projection = _month_to_date_and_projection(daily, now)

    assert mtd == 4.0
    assert projection == 4.0 * 28
