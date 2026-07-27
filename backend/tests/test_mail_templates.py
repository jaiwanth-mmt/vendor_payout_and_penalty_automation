from __future__ import annotations

import random

from backend.app.domain.mail_assignment import assign_bookings_to_recipients
from backend.app.domain.mail_templates import build_html_body, build_mail_draft, build_mail_subject, build_text_body


def test_build_mail_subject_uses_booking_id() -> None:
    assert build_mail_subject("BK-1") == "Penalty complaint details - BK-1"


def test_text_and_html_include_required_fields_and_omit_empty_transcript() -> None:
    text = build_text_body(title="Service Issue", message="Cab delayed", fine=250, booking_id="BK-1")
    html = build_html_body(title="Service Issue", message="Cab delayed", fine=250, booking_id="BK-1")
    assert "title : Service Issue" in text
    assert "message : Cab delayed" in text
    assert "Fine : 250" in text
    assert "complaint against booking : BK-1" in text
    assert "call transcript" not in text
    assert "<strong>title</strong>" in html
    assert "<strong>Fine</strong>" in html
    assert "call transcript" not in html


def test_html_includes_transcript_when_present_and_escapes() -> None:
    html = build_html_body(
        title="Service Issue",
        message="<script>",
        fine=10,
        booking_id="BK-2",
        call_transcript="said <b>late</b>",
    )
    assert "<strong>call transcript</strong>" in html
    assert "&lt;script&gt;" in html
    assert "said &lt;b&gt;late&lt;/b&gt;" in html


def test_build_mail_draft_shape() -> None:
    draft = build_mail_draft(
        recipient="ops@go-mmt.com",
        title="Service Issue",
        message="Vendor no show",
        fine=500,
        booking_id="BK-9",
        call_transcript="caller confirmed",
    )
    assert draft["subject"] == "Penalty complaint details - BK-9"
    assert draft["recipient"] == "ops@go-mmt.com"
    assert any(field["key"] == "call transcript" for field in draft["fields"])


def test_assign_unique_when_enough_rows() -> None:
    recipients = ["a@go-mmt.com", "b@go-mmt.com", "c@go-mmt.com"]
    rows = [{"booking_id": f"B{i}", "title": "t", "message": "m", "fine": i, "call_transcript": ""} for i in range(5)]
    assignments = assign_bookings_to_recipients(recipients, rows, rng=random.Random(7))
    assert len(assignments) == 3
    assert len({item["booking_id"] for item in assignments}) == 3
    assert [item["recipient"] for item in assignments] == recipients


def test_assign_reuses_when_fewer_rows_than_recipients() -> None:
    recipients = ["a@go-mmt.com", "b@go-mmt.com", "c@go-mmt.com"]
    rows = [{"booking_id": "ONLY", "title": "t", "message": "m", "fine": 1, "call_transcript": ""}]
    assignments = assign_bookings_to_recipients(recipients, rows, rng=random.Random(1))
    assert len(assignments) == 3
    assert {item["booking_id"] for item in assignments} == {"ONLY"}
