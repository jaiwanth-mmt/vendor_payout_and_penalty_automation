from __future__ import annotations

import pandas as pd
import pytest

from backend.app.domain.penalty_dataset import filter_by_input_date_range


def test_filter_by_input_date_range_is_inclusive() -> None:
    df = pd.DataFrame(
        {
            "Approval/Rejected DateTime": [
                "2026-03-18 23:00:00",
                "2026-03-19 10:00:00",
                "2026-03-20 01:00:00",
                "2026-03-21 12:00:00",
            ],
            "Booking ID": ["A", "B", "C", "D"],
        }
    )

    filtered = filter_by_input_date_range(
        df,
        "Approval/Rejected DateTime",
        "2026-03-19",
        "2026-03-20",
    )

    assert filtered["Booking ID"].tolist() == ["B", "C"]


def test_filter_by_input_date_range_rejects_inverted_bounds() -> None:
    df = pd.DataFrame(
        {
            "Approval/Rejected DateTime": ["2026-03-19"],
            "Booking ID": ["A"],
        }
    )
    with pytest.raises(ValueError, match="start_date"):
        filter_by_input_date_range(df, "Approval/Rejected DateTime", "2026-03-21", "2026-03-19")
