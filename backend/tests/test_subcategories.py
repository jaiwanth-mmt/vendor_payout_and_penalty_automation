from __future__ import annotations

import pandas as pd

from backend.app.domain.cab_delay_enrichment import INCABS_INSIGHT_COLUMN
from backend.app.domain.penalty_dataset import FINAL_OUTPUT_COLUMNS
from backend.app.domain.subcategories import build_unique_slug_map, normalize_subcategory_name, slugify
from backend.app.services.pipeline import shape_prepared_output, split_by_subcategory


def test_split_by_subcategory_routes_each_row_once() -> None:
    df = pd.DataFrame(
        [
            {"Booking ID": "B1", "Sub Category": "Cab Delay"},
            {"Booking ID": "B2", "Sub Category": "Extra Money Taken"},
            {"Booking ID": "B3", "Sub Category": "Cab Delay"},
        ]
    )

    batches = split_by_subcategory(df)

    assert [batch.name for batch in batches] == ["Cab Delay", "Extra Money Taken"]
    assert [batch.slug for batch in batches] == ["cab-delay", "extra-money-taken"]
    assert [len(batch.df) for batch in batches] == [2, 1]
    routed_booking_ids = sorted(
        booking_id
        for batch in batches
        for booking_id in batch.df["Booking ID"].tolist()
    )
    assert routed_booking_ids == ["B1", "B2", "B3"]


def test_subcategory_names_and_slugs_have_stable_fallbacks() -> None:
    assert normalize_subcategory_name("") == "Uncategorized"
    assert normalize_subcategory_name(None) == "Uncategorized"
    assert normalize_subcategory_name("  Cab Delay  ") == "Cab Delay"
    assert slugify("Lower Category Vehicle") == "lower-category-vehicle"
    assert slugify("###") == "uncategorized"


def test_build_unique_slug_map_suffixes_collisions() -> None:
    slug_map = build_unique_slug_map(["Cab Delay", "Cab-Delay", "Cab Delay!"])

    assert slug_map == {
        "Cab Delay": "cab-delay",
        "Cab-Delay": "cab-delay-2",
        "Cab Delay!": "cab-delay-3",
    }


def test_shape_prepared_output_does_not_add_cab_delay_columns() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B1",
                "Booking Date": "2026-03-19",
                "Booking Month": "Mar 2026",
                "Loss Dept": "CARBD",
                "Sub Category": "CARBD - Cab Delay",
                "Loss Amount": 100,
                "Recoverable": 100,
                "Remarks": "Cab Delay - Auto Claim Raised",
                INCABS_INSIGHT_COLUMN: "Existing insight",
            }
        ]
    )

    shaped = shape_prepared_output(df)

    assert shaped.columns.tolist() == FINAL_OUTPUT_COLUMNS
    assert shaped.loc[0, "Sub Category"] == "Cab Delay"
    assert shaped.loc[0, "Remarks"] == "Cab Delay"
    assert INCABS_INSIGHT_COLUMN not in shaped.columns
