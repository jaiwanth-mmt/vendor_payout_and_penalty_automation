from __future__ import annotations

import asyncio
import json
import re

import pandas as pd

from backend.app.agents.models import AgentDecision, ClaimCase, EvidenceItem
from backend.app.agents.orchestrator import (
    build_agent_progress,
    build_claim_case,
    build_portfolio_summary,
    build_portfolio_summary_async,
    investigate_category_frame_async,
)
from backend.app.agents.specialists import run_judge_agent_async, run_specialist_agent_async
from backend.app.domain.complaint_message import MESSAGE_COLUMN


def evidence_item(
    booking_id: str,
    suffix: str,
    *,
    status: str = "available",
    text: str | None = None,
) -> EvidenceItem:
    text = text or "Customer said driver collected extra cash."
    fields = {"text": text, "driver_started_after_pickup_minutes": 22}
    if suffix in {"comments", "remarks", "sub_category"}:
        fields["source_field"] = suffix
        fields[suffix] = text
    if suffix == "comments":
        fields["comments"] = text
    return EvidenceItem(
        id=f"{booking_id}:{suffix}",
        title=suffix.title(),
        source="test",
        status=status,  # type: ignore[arg-type]
        summary=f"{suffix} evidence",
        fields=fields,
    )


def source_aligned_llm(prompt: str, _tokens: int, _effort: str) -> str:
    if "Complaint category classification task." in prompt:
        return json.dumps({"categories": categories_for_prompt(classification_subject(prompt))})

    evidence_ids = list(dict.fromkeys(re.findall(r'"id":\s*"([^"]+)"', prompt)))[:3]
    categories = source_categories_for_prompt(prompt) or categories_for_prompt(prompt)
    status = "auto_ready" if evidence_ids else "missing_evidence"
    return json.dumps(
        {
            "decision": "valid_penalty" if status == "auto_ready" else "needs_review",
            "complaint_categories": categories,
            "confidence": 0.91 if status == "auto_ready" else 0.55,
            "recommended_recovery_amount": 100 if status == "auto_ready" else 0,
            "rationale": "Mock LLM followed source alignment categories.",
            "recommended_action": "Ready" if status == "auto_ready" else "Review",
            "review_status": status,
            "review_reason": "Mock LLM followed source alignment.",
            "evidence_ids": evidence_ids,
        }
    )


def categories_for_prompt(prompt: str) -> list[str]:
    normalized = prompt.casefold()
    categories: list[str] = []
    if "paid amount refund" in normalized:
        return []
    if "cab delayed > 1 hour" in prompt or "more than 1 hour" in normalized:
        categories.append("Cab Delayed > 1 Hour")
    elif "cab delayed > 15 minutes" in prompt or "20 minutes" in normalized:
        categories.append("Cab Delayed > 15 Minutes")
    elif "cab delay" in normalized or "driver was late" in normalized or "delayed" in normalized:
        categories.append("Cab Delay")
    if "driver collected extra" in normalized or "extra cash" in normalized or "extra money" in normalized:
        categories.append("Extra Money Taken")
    if "lower category vehicle" in normalized:
        categories.append("Low Category Vehicle")
    if "vendor no show" in normalized or "did not arrive" in normalized:
        categories.append("Vendor No Show")
    return categories


def classification_subject(prompt: str) -> str:
    values: dict[str, str] = {}
    for line in prompt.splitlines():
        for label in ["Comments", "Remarks", "Sub Category"]:
            prefix = f"{label}:"
            if line.startswith(prefix):
                values[label] = line.removeprefix(prefix).strip()

    if values.get("Comments"):
        return values["Comments"]
    if values.get("Remarks"):
        return values["Remarks"]
    return values.get("Sub Category", "")


def source_categories_for_prompt(prompt: str) -> list[str]:
    match = re.search(r'"source_categories":\s*(\[[^\]]*\])', prompt)
    if not match:
        return []
    try:
        categories = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [str(category) for category in categories]


def test_build_claim_case_captures_vendor_name() -> None:
    row = pd.Series(
        {
            "Booking ID": "B1",
            "Sub Category": "Cab Delay",
            "Remarks": "Cab Delay",
            "Recoverable": 100,
            "comments": "Customer said driver was late.",
            MESSAGE_COLUMN: "Cab Delay",
            "vendor_name": "savaari",
        }
    )
    missing_vendor_row = row.copy()
    missing_vendor_row["vendor_name"] = ""

    case = build_claim_case(row, row_index=0)
    missing_vendor_case = build_claim_case(missing_vendor_row, row_index=1)

    assert case.vendor_name == "savaari"
    assert case.message == "Cab Delay"
    assert case.to_dict()["vendor_name"] == "savaari"
    assert missing_vendor_case.vendor_name == "Unknown vendor"


def test_valid_specialist_llm_json_becomes_agent_decision() -> None:
    case = ClaimCase(
        "B1",
        "Extra Money Taken",
        "driver collected extra",
        80,
        0,
        comments="Customer said driver collected extra cash.",
        message="Extra Money Taken",
    )
    case.evidence = [evidence_item("B1", "penalty"), evidence_item("B1", "comments"), evidence_item("B1", "fare")]
    calls: list[tuple[int, str]] = []

    async def llm(_prompt: str, tokens: int, effort: str) -> str:
        calls.append((tokens, effort))
        return json.dumps(
            {
                "decision": "valid_penalty",
                "complaint_categories": ["Extra Money Taken"],
                "confidence": 0.93,
                "recommended_recovery_amount": 80,
                "rationale": "Comment evidence supports extra money taken.",
                "recommended_action": "Ready for Cab Ops recovery package",
                "review_status": "auto_ready",
                "review_reason": "Evidence is cited and sufficient.",
                "evidence_ids": ["B1:comments"],
            }
        )

    asyncio.run(run_specialist_agent_async(case, llm_generator=llm, semaphore=asyncio.Semaphore(1)))

    assert case.specialist_decision is not None
    assert case.specialist_decision.decision_source == "llm"
    assert case.specialist_decision.complaint_categories == ["Extra Money Taken"]
    assert case.specialist_decision.evidence_ids == ["B1:comments"]
    assert calls == [(2048, "minimal"), (2048, "minimal"), (8192, "medium")]


def test_invalid_specialist_llm_json_uses_fallback() -> None:
    case = ClaimCase(
        "B1",
        "Extra Money Taken",
        "driver collected extra",
        80,
        0,
        comments="Customer said driver collected extra cash.",
        message="Extra Money Taken",
    )
    case.evidence = [evidence_item("B1", "penalty"), evidence_item("B1", "comments"), evidence_item("B1", "fare")]

    asyncio.run(
        run_specialist_agent_async(
            case,
            llm_generator=lambda _prompt, _tokens, _effort: "not json",
            semaphore=asyncio.Semaphore(1),
        )
    )

    assert case.specialist_decision is not None
    assert case.specialist_decision.decision_source == "fallback"
    assert case.specialist_decision.llm_error == "invalid_json"
    assert case.specialist_decision.complaint_categories == ["Extra Money Taken"]


def test_uncited_evidence_ids_are_rejected() -> None:
    case = ClaimCase("B1", "Cab Delay", "Cab Delay", 100, 0, comments="Customer said driver was late.")
    case.evidence = [
        evidence_item("B1", "comments", text="Customer said driver was late."),
        evidence_item("B1", "timing"),
    ]

    async def llm(_prompt: str, _tokens: int, _effort: str) -> str:
        return json.dumps(
            {
                "decision": "valid_penalty",
                "complaint_categories": ["Cab Delay"],
                "confidence": 0.9,
                "recommended_recovery_amount": 100,
                "rationale": "Unsupported fake evidence.",
                "recommended_action": "Ready",
                "review_status": "auto_ready",
                "review_reason": "Fake evidence cited.",
                "evidence_ids": ["fake:evidence"],
            }
        )

    asyncio.run(run_specialist_agent_async(case, llm_generator=llm, semaphore=asyncio.Semaphore(1)))

    assert case.specialist_decision is not None
    assert case.specialist_decision.decision_source == "fallback"
    assert case.specialist_decision.llm_error == "no_valid_evidence_ids"


def test_judge_ignores_missing_timing_when_selected_source_exists() -> None:
    case = ClaimCase(
        "B9",
        "Cab Delay",
        "Cab Delay",
        100,
        0,
        comments="Customer said driver was late.",
        message="Cab Delay",
    )
    case.evidence = [
        evidence_item("B9", "comments", text="Customer said driver was late."),
        evidence_item("B9", "timing", status="missing"),
    ]
    case.specialist_decision = AgentDecision(
        agent="Cab Delay Agent",
        decision="valid_penalty",
        complaint_categories=["Cab Delay"],
        confidence=0.95,
        recommended_recovery_amount=100,
        rationale="Specialist thinks the penalty is valid.",
        recommended_action="Ready",
        review_status="auto_ready",
        review_reason="Specialist approved.",
        evidence_ids=["B9:comments"],
        decision_source="llm",
    )

    calls: list[tuple[int, str]] = []

    async def judge_llm(_prompt: str, tokens: int, effort: str) -> str:
        calls.append((tokens, effort))
        return json.dumps(
            {
                "decision": "valid_penalty",
                "complaint_categories": ["Cab Delay"],
                "confidence": 0.99,
                "recommended_recovery_amount": 100,
                "rationale": "Approved despite missing timing.",
                "recommended_action": "Ready",
                "review_status": "auto_ready",
                "review_reason": "Approved.",
                "evidence_ids": ["B9:comments"],
            }
        )

    asyncio.run(run_judge_agent_async(case, llm_generator=judge_llm, semaphore=asyncio.Semaphore(1)))

    assert case.judge_decision is not None
    assert case.judge_decision.decision_source == "llm"
    assert case.judge_decision.review_status == "auto_ready"
    assert case.judge_decision.evidence_ids == ["B9:comments"]
    assert calls == [(2048, "minimal"), (2048, "minimal"), (8192, "high")]


def test_judge_promotes_low_confidence_selected_source_to_auto_ready() -> None:
    case = ClaimCase(
        "B14",
        "Cab Delay",
        "Cab Delay",
        100,
        0,
        comments="Customer mentioned cab delay but did not give timing details.",
        message="Cab Delay",
    )
    case.evidence = [evidence_item("B14", "comments", text=case.comments)]
    case.specialist_decision = AgentDecision(
        agent="Cab Delay Agent",
        decision="needs_review",
        complaint_categories=["Cab Delay"],
        confidence=0.42,
        recommended_recovery_amount=0,
        rationale="Comments are brief.",
        recommended_action="Review",
        review_status="needs_review",
        review_reason="LLM thought the comment was too brief.",
        evidence_ids=["B14:comments"],
        decision_source="llm",
    )

    async def judge_llm(_prompt: str, _tokens: int, _effort: str) -> str:
        return json.dumps(
            {
                "decision": "needs_review",
                "complaint_categories": ["Cab Delay"],
                "confidence": 0.41,
                "recommended_recovery_amount": 0,
                "rationale": "Comment is vague.",
                "recommended_action": "Review",
                "review_status": "needs_review",
                "review_reason": "Selected source is brief.",
                "evidence_ids": ["B14:comments"],
            }
        )

    asyncio.run(run_judge_agent_async(case, llm_generator=judge_llm, semaphore=asyncio.Semaphore(1)))

    assert case.judge_decision is not None
    assert case.judge_decision.review_status == "auto_ready"
    assert case.judge_decision.decision == "valid_penalty"
    assert case.judge_decision.confidence == 0.86
    assert case.judge_decision.recommended_recovery_amount == 100


def test_comments_mismatch_routes_to_review() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B10",
                "Sub Category": "Cab Delay",
                "Remarks": "Cab Delay",
                "Recoverable": 100,
                "comments": "Customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "needs_review"
    assert cases[0]["source_analysis"]["source_categories"] == ["Extra Money Taken"]
    assert cases[0]["source_analysis"]["row_categories"] == ["Cab Delay"]
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_matching_comments_and_row_context_are_auto_ready() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B10",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                "Recoverable": 100,
                "comments": "Customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_comments_with_expected_and_extra_categories_are_auto_ready() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B10X",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                "Recoverable": 100,
                "comments": "Customer said the cab was delayed and driver collected extra cash.",
                MESSAGE_COLUMN: "Cab Delay + Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["final_decision"]["complaint_categories"] == ["Cab Delay", "Extra Money Taken"]
    assert output.loc[0, MESSAGE_COLUMN] == "Cab Delay + Extra Money Taken"


def test_comment_booking_id_mismatch_routes_to_review() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "NC1234567890",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                "Recoverable": 100,
                "comments": "For booking ID NC9999999999, customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    _output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "needs_review"
    assert cases[0]["source_analysis"]["status"] == "booking_id_mismatch"


def test_booking_words_do_not_create_false_id_mismatch() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "NC1234567890",
                "Sub Category": "Cab Delay",
                "Remarks": "Cab Delay",
                "Recoverable": 100,
                "comments": (
                    "Customer called about a cab booking scheduled for 4 PM. "
                    "The driver was delayed due to refueling and would arrive in 20 minutes."
                ),
                MESSAGE_COLUMN: "Cab Delayed > 15 Minutes",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["source_analysis"]["mentioned_booking_ids"] == []
    assert cases[0]["source_analysis"]["status"] == "aligned"
    assert output.loc[0, MESSAGE_COLUMN] == "Cab Delayed > 15 Minutes"


def test_cab_delay_duration_categories_align_with_generic_cab_delay() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "NC1234567891",
                "Sub Category": "Cab Delay",
                "Remarks": "Cab Delay",
                "Recoverable": 100,
                "comments": "Customer said the cab was delayed for more than 1 hour.",
                MESSAGE_COLUMN: "Cab Delayed > 1 Hour",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["source_analysis"]["source_categories"] == ["Cab Delayed > 1 Hour"]
    assert cases[0]["source_analysis"]["row_categories"] == ["Cab Delay"]
    assert cases[0]["source_analysis"]["status"] == "aligned"
    assert output.loc[0, MESSAGE_COLUMN] == "Cab Delayed > 1 Hour"


def test_remarks_drive_reasoning_when_comments_empty() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["source_analysis"]["primary_source"] == "remarks"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_remarks_take_priority_over_mismatched_subcategory() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11X",
                "Sub Category": "Cab Delay",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_empty_remarks_uses_subcategory_for_alignment() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11Y",
                "Sub Category": "Cab Delay",
                "Remarks": "",
                "Recoverable": 80,
                "comments": "Customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "needs_review"
    assert cases[0]["source_analysis"]["comparison_source"] == "sub_category"
    assert cases[0]["source_analysis"]["row_categories"] == ["Cab Delay"]
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_unmappable_remarks_can_still_auto_ready_when_subcategory_matches() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11Z",
                "Sub Category": "Vendor No Show",
                "Remarks": "paid amount refund",
                "Recoverable": 80,
                "comments": "Customer said the vendor did not arrive.",
                MESSAGE_COLUMN: "Vendor No Show",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=source_aligned_llm, llm_concurrency=1)
    )

    assert cases[0]["review_status"] == "auto_ready"
    assert cases[0]["source_analysis"]["comparison_source"] == "remarks_or_sub_category"
    assert cases[0]["source_analysis"]["remarks_categories"] == []
    assert cases[0]["source_analysis"]["sub_category_categories"] == ["Vendor No Show"]
    assert output.loc[0, MESSAGE_COLUMN] == "Vendor No Show"


def test_row_context_llm_failure_routes_to_review_without_regex_fallback() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11F",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "Customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )

    def failing_alignment_llm(prompt: str, _tokens: int, _effort: str) -> str:
        if "Complaint category classification task." in prompt:
            return "not json"
        return source_aligned_llm(prompt, _tokens, _effort)

    output, cases = asyncio.run(
        investigate_category_frame_async(
            df,
            tracking_bookings={},
            llm_generator=failing_alignment_llm,
            llm_concurrency=1,
        )
    )

    assert cases[0]["review_status"] == "needs_review"
    assert cases[0]["source_analysis"]["row_categories"] == []
    assert cases[0]["source_analysis"]["reason"] == (
        "Remarks could not be classified by the LLM.; "
        "Sub Category could not be classified by the LLM."
    )
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_subcategory_only_is_missing_evidence() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B12",
                "Sub Category": "Lower Category Vehicle",
                "Remarks": "",
                "Recoverable": 200,
                "comments": "",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=None, llm_concurrency=1)
    )

    assert cases[0]["source_analysis"]["row_categories"] == []
    assert cases[0]["final_decision"]["complaint_categories"] == []
    assert cases[0]["review_status"] == "missing_evidence"
    assert output.loc[0, MESSAGE_COLUMN] == ""


def test_operational_tracking_fields_do_not_affect_agent_decision() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B13",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "",
                "driver_arrived": "19 Mar 2026 10:00 AM",
                "driver_started": "19 Mar 2026 10:01 AM",
                "cash_collected": 0,
                "vehicle_type": "sedan",
                "tracking status": "COMPLETED",
                MESSAGE_COLUMN: "Extra Money Taken",
            }
        ]
    )
    tracking = {
        "B13": {
            "comments": "Customer said cab was delayed.",
            "tracking_reports_raw": [
                {
                    "driver_arrived": "19 Mar 2026 10:00 AM",
                    "driver_started": "19 Mar 2026 10:01 AM",
                    "cash_collected": 0,
                    "vehicle_type": "sedan",
                }
            ],
        }
    }

    output, cases = asyncio.run(
        investigate_category_frame_async(
            df,
            tracking_bookings=tracking,
            llm_generator=source_aligned_llm,
            llm_concurrency=1,
        )
    )

    evidence_ids = [item["id"] for item in cases[0]["evidence"]]
    assert "B13:remarks" in evidence_ids
    assert all("timing" not in evidence_id and "fare" not in evidence_id for evidence_id in evidence_ids)
    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_portfolio_summary_uses_large_default_token_budget() -> None:
    calls: list[tuple[int, str]] = []

    async def llm(_prompt: str, tokens: int, effort: str) -> str:
        calls.append((tokens, effort))
        return json.dumps(
            {
                "executive_summary": "Portfolio summary from LLM with $100 recoverable.",
                "top_complaint_drivers": ["Cab Delay: $100 recoverable"],
                "recommended_actions": ["Proceed with $100 recoveries."],
                "missing_data_hotspots": [],
                "category_breakdown": [{"category": "Cab Delay", "cases": 1, "recoverable": 100}],
            }
        )

    cases = [
        {
            "booking_id": "B1",
            "sub_category": "Cab Delay",
            "vendor_name": "savaari",
            "recoverable_amount": 100,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.91},
            "evidence": [],
        }
    ]

    summary = asyncio.run(build_portfolio_summary_async(cases, llm_generator=llm, llm_concurrency=1))

    assert summary["executive_summary"] == "Portfolio summary from LLM with ₹100 recoverable."
    assert summary["top_complaint_drivers"] == ["Cab Delay: ₹100 recoverable"]
    assert summary["recommended_actions"] == ["Proceed with ₹100 recoveries."]
    assert summary["top_vendors_by_penalty"][0]["vendor_name"] == "savaari"
    assert calls == [(4096, "medium")]


def test_portfolio_summary_adds_vendor_penalty_analysis() -> None:
    cases = [
        {
            "booking_id": "B1",
            "sub_category": "Cab Delay",
            "vendor_name": "alpha",
            "recoverable_amount": 100,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
        {
            "booking_id": "B2",
            "sub_category": "Extra Money Taken",
            "vendor_name": "alpha",
            "recoverable_amount": 90,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
        {
            "booking_id": "B3",
            "sub_category": "Cab Delay",
            "vendor_name": "beta",
            "recoverable_amount": 190,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
        {
            "booking_id": "B4",
            "sub_category": "Driver Behavior",
            "vendor_name": "gamma",
            "recoverable_amount": 190,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
        {
            "booking_id": "B5",
            "sub_category": "Cab Delay",
            "vendor_name": "delta",
            "recoverable_amount": 80,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
        {
            "booking_id": "B6",
            "sub_category": "AC not working",
            "vendor_name": "",
            "recoverable_amount": 70,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.9},
            "evidence": [],
        },
    ]

    summary = build_portfolio_summary(cases)

    assert [item["vendor_name"] for item in summary["top_vendors_by_penalty"]] == ["alpha", "beta", "gamma"]
    assert summary["top_vendors_by_penalty"][0] == {
        "vendor_name": "alpha",
        "case_count": 2,
        "total_recoverable": 190,
        "top_subcategories": [
            {"subcategory": "Cab Delay", "case_count": 1, "total_recoverable": 100},
            {"subcategory": "Extra Money Taken", "case_count": 1, "total_recoverable": 90},
        ],
    }
    assert summary["top_subcategories_by_penalty"] == [
        {"subcategory": "Cab Delay", "case_count": 3, "total_recoverable": 370},
        {"subcategory": "Driver Behavior", "case_count": 1, "total_recoverable": 190},
        {"subcategory": "Extra Money Taken", "case_count": 1, "total_recoverable": 90},
    ]
    assert summary["top_subcategories_by_count"] == [
        {"subcategory": "Cab Delay", "case_count": 3, "total_recoverable": 370},
        {"subcategory": "Driver Behavior", "case_count": 1, "total_recoverable": 190},
        {"subcategory": "Extra Money Taken", "case_count": 1, "total_recoverable": 90},
    ]
    missing_vendor_summary = build_portfolio_summary([cases[-1]])
    assert missing_vendor_summary["top_vendors_by_penalty"][0]["vendor_name"] == "Unknown vendor"


def test_agent_progress_reports_completed_warning_and_failed_states() -> None:
    completed_case = {
        "booking_id": "B1",
        "review_status": "auto_ready",
        "evidence": [{"status": "available"}],
        "specialist_decision": {"review_status": "auto_ready"},
        "judge_decision": {"review_status": "auto_ready"},
    }
    warning_case = {
        "booking_id": "B2",
        "review_status": "missing_evidence",
        "evidence": [{"status": "missing"}],
        "specialist_decision": {"review_status": "needs_review", "llm_error": "invalid_json"},
        "judge_decision": {"review_status": "missing_evidence"},
    }
    failed_case = {
        "booking_id": "B3",
        "review_status": "failed",
        "evidence": [{"status": "error"}],
        "specialist_decision": None,
        "judge_decision": None,
    }

    completed_progress = build_agent_progress([completed_case])
    warning_progress = build_agent_progress([warning_case], agent_summary={"portfolio_llm_error": "invalid_json"})
    failed_progress = build_agent_progress([failed_case])

    assert {item["agent"]: item["status"] for item in completed_progress} == {
        "Intake Agent": "completed",
        "Evidence Retrieval Agent": "completed",
        "Category Specialist Agents": "completed",
        "Judge Agent": "completed",
        "Portfolio Summary Agent": "completed",
        "Vendor Penalty Analysis Agent": "completed",
    }
    assert {item["agent"]: item["status"] for item in warning_progress} == {
        "Intake Agent": "completed",
        "Evidence Retrieval Agent": "warning",
        "Category Specialist Agents": "warning",
        "Judge Agent": "warning",
        "Portfolio Summary Agent": "warning",
        "Vendor Penalty Analysis Agent": "completed",
    }
    assert {item["agent"]: item["status"] for item in failed_progress} == {
        "Intake Agent": "completed",
        "Evidence Retrieval Agent": "failed",
        "Category Specialist Agents": "failed",
        "Judge Agent": "failed",
        "Portfolio Summary Agent": "completed",
        "Vendor Penalty Analysis Agent": "completed",
    }


def test_llm_message_is_preserved_after_agent_decision() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B5",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                "Recoverable": 80,
                "comments": "Customer said driver collected extra cash.",
                MESSAGE_COLUMN: "Cab Delay",
            }
        ]
    )
    tracking = {
        "B5": {
            "comments": "Customer said driver collected extra cash.",
            "tracking_reports_raw": [{"cash_collected": 500, "route_toll_charges": 50}],
        }
    }

    async def llm(prompt: str, _tokens: int, _effort: str) -> str:
        evidence_ids = (
            ["B5:comments", "B5:source_alignment"]
            if "Agent specialist decision task." in prompt
            else ["B5:comments"]
        )
        return json.dumps(
            {
                "decision": "valid_penalty",
                "complaint_categories": ["Extra Money Taken"],
                "confidence": 0.91,
                "recommended_recovery_amount": 80,
                "rationale": "Extra money claim is supported.",
                "recommended_action": "Ready",
                "review_status": "auto_ready",
                "review_reason": "Approved.",
                "evidence_ids": evidence_ids,
            }
        )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings=tracking, llm_generator=llm, llm_concurrency=2)
    )

    assert output.loc[0, MESSAGE_COLUMN] == "Cab Delay"
    assert cases[0]["review_status"] == "needs_review"
    assert cases[0]["final_decision"]["decision_source"] == "llm"
