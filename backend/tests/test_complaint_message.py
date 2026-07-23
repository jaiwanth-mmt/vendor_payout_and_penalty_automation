from __future__ import annotations

from backend.app.domain.complaint_message import (
    build_fallback_message,
    build_message_from_response,
    classify_cab_delay_window,
    format_message_categories,
    map_complaint_labels,
    parse_message_categories,
)


def test_parse_message_categories_keeps_only_allowed_unique_categories_in_allowed_order() -> None:
    categories = parse_message_categories(
        '{"categories": ["Extra Money Taken", "Not Allowed", "AC Not Working", "Extra Money Taken"]}'
    )

    assert categories == ["AC Not Working", "Extra Money Taken"]
    assert format_message_categories(categories) == "AC Not Working + Extra Money Taken"


def test_fallback_uses_remarks_when_comments_are_empty() -> None:
    message = build_fallback_message(
        sub_category="Unknown",
        remarks="Driver collected extra cash for toll.",
        comments="",
    )

    assert message == "Extra Money Taken"


def test_fallback_maps_local_subcategory_names_to_allowed_categories() -> None:
    assert (
        build_fallback_message(sub_category="Lower Category Vehicle", remarks="", comments="")
        == "Low Category Vehicle"
    )
    assert build_fallback_message(sub_category="Vehicle Breakdown", remarks="", comments="") == "Cab Breakdown"
    assert (
        build_fallback_message(sub_category="Driver Behavior", remarks="", comments="")
        == "Bad Driver Behaviour/Skill"
    )
    assert map_complaint_labels("Accidental Case") == ["Accident on the Way"]
    assert map_complaint_labels("Brand New Penalty Type") == []


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


def test_llm_cab_delay_category_is_normalized_to_text_window() -> None:
    message = build_message_from_response(
        '{"categories": ["Cab Delay", "Extra Money Taken"]}',
        sub_category="Cab Delay",
        remarks="Cab Delay",
        comments="Customer said the driver collected extra money and cab was delayed 30-60 mins.",
    )

    assert message == "Cab Delayed by 30-60 Minutes + Extra Money Taken"


def test_llm_multiple_cab_delay_categories_are_collapsed_to_one() -> None:
    message = build_message_from_response(
        '{"categories": ["Cab Delay", "Cab Delayed by 30-60 Minutes", "Cab Delayed > 1 Hour"]}',
        sub_category="Cab Delay",
        remarks="Cab Delay",
        comments="Customer reported cab delay but no timing window.",
    )

    assert message == "Cab Delay"


def test_empty_llm_categories_do_not_fallback_to_row_context() -> None:
    message = build_message_from_response(
        '{"categories": []}',
        sub_category="Lower Category Vehicle",
        remarks="Lower Category Vehicle",
        comments="Customer only asked for driver details.",
    )

    assert message == ""
