from __future__ import annotations

from backend.app.domain.complaint_message import (
    build_fallback_message,
    build_message_from_row,
    classify_cab_delay_window,
    format_message_categories,
    map_complaint_labels,
    normalize_cab_delay_selection,
    parse_message_categories,
)


def test_parse_message_categories_keeps_only_allowed_unique_categories_in_allowed_order() -> None:
    categories = parse_message_categories(
        '{"categories": ["Extra Money Taken", "Not Allowed", "AC Not Working", "Extra Money Taken"]}'
    )

    assert categories == ["AC Not Working", "Extra Money Taken"]
    assert format_message_categories(categories) == "AC Not Working + Extra Money Taken"


def test_message_uses_remarks_before_sub_category() -> None:
    message = build_message_from_row(
        remarks="Driver collected extra cash for toll.",
        sub_category="Unknown",
    )

    assert message == "Extra Money Taken"


def test_message_falls_back_to_sub_category_when_remarks_empty() -> None:
    assert (
        build_message_from_row(remarks="", sub_category="Lower Category Vehicle") == "Low Category Vehicle"
    )
    assert build_message_from_row(remarks="", sub_category="Vehicle Breakdown") == "Cab Breakdown"
    assert (
        build_message_from_row(remarks="", sub_category="Driver Behavior") == "Bad Driver Behaviour/Skill"
    )
    assert map_complaint_labels("Accidental Case") == ["Accident on the Way"]
    assert map_complaint_labels("Brand New Penalty Type") == []


def test_fulfillment_not_done_maps_to_vendor_no_show() -> None:
    assert build_message_from_row(remarks="FULFILLMENT NOT DONE", sub_category="") == "Vendor No Show"
    assert build_message_from_row(remarks="", sub_category="Fulfillment Not Done") == "Vendor No Show"
    assert map_complaint_labels("fulfillment not done") == ["Vendor No Show"]


def test_fallback_wrapper_ignores_comments() -> None:
    message = build_fallback_message(
        sub_category="Cab Delay",
        remarks="Cab Delay",
        comments="Customer said the cab was delayed by 45 minutes.",
    )

    assert message == "Cab Delay"


def test_cab_delay_window_selection_is_text_only() -> None:
    assert classify_cab_delay_window("Customer said the cab was delayed by 45 minutes.") == (
        "Cab Delayed by 30-60 Minutes"
    )
    assert classify_cab_delay_window("Driver said they needed 20 minutes.") == "Cab Delayed > 15 Minutes"
    assert classify_cab_delay_window("Customer said the cab was delayed by 90 minutes.") == "Cab Delayed > 1 Hour"
    assert classify_cab_delay_window("Customer waited 1 hour 15 minutes for the cab.") == "Cab Delayed > 1 Hour"
    assert classify_cab_delay_window("Customer said cab was delayed more than an hour.") == "Cab Delayed > 1 Hour"
    assert classify_cab_delay_window("Customer waited one hour for the delayed cab.") == (
        "Cab Delayed by 30-60 Minutes"
    )
    assert classify_cab_delay_window("Customer waited an hour for the delayed cab.") == (
        "Cab Delayed by 30-60 Minutes"
    )
    assert classify_cab_delay_window("Customer reported cab delay but no timing window.") == "Cab Delay"


def test_cab_delay_normalize_uses_remarks_not_comments() -> None:
    categories = normalize_cab_delay_selection(
        ["Cab Delay", "Extra Money Taken"],
        sub_category="Cab Delay",
        remarks="Cab Delay",
        comments="Customer said the cab was delayed 30-60 mins.",
    )

    assert categories == ["Cab Delay", "Extra Money Taken"]


def test_cab_delay_normalize_reads_window_from_remarks() -> None:
    categories = normalize_cab_delay_selection(
        ["Cab Delay", "Extra Money Taken"],
        sub_category="Cab Delay",
        remarks="Cab delayed 30-60 mins and driver collected extra money",
        comments="ignored timing text needed 20 minutes",
    )

    assert categories == ["Cab Delayed by 30-60 Minutes", "Extra Money Taken"]


def test_message_collapses_multiple_cab_delay_labels() -> None:
    message = build_message_from_row(
        remarks="Cab Delay",
        sub_category="Cab Delayed > 1 Hour",
    )

    assert message == "Cab Delay"


def test_unmapped_remarks_and_sub_category_leave_blank_message() -> None:
    message = build_message_from_row(
        remarks="Brand New Penalty Type",
        sub_category="ZZZ_UNKNOWN_LABEL_XYZ",
    )

    assert message == ""
