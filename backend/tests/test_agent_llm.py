from __future__ import annotations

import asyncio
import json

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


def test_build_claim_case_captures_vendor_name() -> None:
    row = pd.Series(
        {
            "Booking ID": "B1",
            "Sub Category": "Cab Delay",
            "Remarks": "Cab Delay",
            "Recoverable": 100,
            "comments": "Customer said driver was late.",
            "vendor_name": "savaari",
        }
    )
    missing_vendor_row = row.copy()
    missing_vendor_row["vendor_name"] = ""

    case = build_claim_case(row, row_index=0)
    missing_vendor_case = build_claim_case(missing_vendor_row, row_index=1)

    assert case.vendor_name == "savaari"
    assert case.to_dict()["vendor_name"] == "savaari"
    assert missing_vendor_case.vendor_name == "Unknown vendor"


def test_valid_specialist_llm_json_becomes_agent_decision() -> None:
    case = ClaimCase("B1", "Extra Money Taken", "driver collected extra", 80, 0, comments="Customer said driver collected extra cash.")
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
    assert calls == [(8192, "medium")]


def test_invalid_specialist_llm_json_uses_fallback() -> None:
    case = ClaimCase("B1", "Extra Money Taken", "driver collected extra", 80, 0, comments="Customer said driver collected extra cash.")
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
    case.evidence = [evidence_item("B1", "comments", text="Customer said driver was late."), evidence_item("B1", "timing")]

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
    case = ClaimCase("B9", "Cab Delay", "Cab Delay", 100, 0, comments="Customer said driver was late.")
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
    assert calls == [(8192, "high")]


def test_judge_promotes_low_confidence_selected_source_to_auto_ready() -> None:
    case = ClaimCase(
        "B14",
        "Cab Delay",
        "Cab Delay",
        100,
        0,
        comments="Customer mentioned cab delay but did not give timing details.",
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


def test_source_priority_comments_beat_remarks_and_subcategory() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B10",
                "Sub Category": "Cab Delay",
                "Remarks": "Cab Delay",
                "Recoverable": 100,
                "comments": "Customer said driver collected extra cash.",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=None, llm_concurrency=1)
    )

    assert cases[0]["evidence"][0]["id"] == "B10:comments"
    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_source_priority_remarks_beat_subcategory_when_comments_empty() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B11",
                "Sub Category": "Cab Delay",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "",
            }
        ]
    )

    output, cases = asyncio.run(
        investigate_category_frame_async(df, tracking_bookings={}, llm_generator=None, llm_concurrency=1)
    )

    assert cases[0]["evidence"][0]["id"] == "B11:remarks"
    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_source_priority_subcategory_is_final_fallback() -> None:
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

    assert cases[0]["evidence"][0]["id"] == "B12:sub_category"
    assert cases[0]["final_decision"]["complaint_categories"] == ["Low Category Vehicle"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Low Category Vehicle"


def test_operational_tracking_fields_do_not_affect_agent_decision() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B13",
                "Sub Category": "Cab Delay",
                "Remarks": "driver collected extra cash",
                "Recoverable": 80,
                "comments": "",
                "driver_arrived": "19 Mar 2026 10:00 AM",
                "driver_started": "19 Mar 2026 10:01 AM",
                "cash_collected": 0,
                "vehicle_type": "sedan",
                "tracking status": "COMPLETED",
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
        investigate_category_frame_async(df, tracking_bookings=tracking, llm_generator=None, llm_concurrency=1)
    )

    assert [item["id"] for item in cases[0]["evidence"]] == ["B13:remarks"]
    assert cases[0]["final_decision"]["complaint_categories"] == ["Extra Money Taken"]
    assert cases[0]["review_status"] == "auto_ready"
    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"


def test_portfolio_summary_uses_large_default_token_budget() -> None:
    calls: list[tuple[int, str]] = []

    async def llm(_prompt: str, tokens: int, effort: str) -> str:
        calls.append((tokens, effort))
        return json.dumps(
            {
                "executive_summary": "Portfolio summary from LLM.",
                "top_complaint_drivers": ["Cab Delay: 1 case"],
                "recommended_actions": ["Proceed with reviewed recoveries."],
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

    assert summary["executive_summary"] == "Portfolio summary from LLM."
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


def test_agent_decision_becomes_final_message() -> None:
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
        evidence_ids = ["B5:comments", "B5:fare"] if "Agent specialist decision task." in prompt else ["B5:comments"]
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

    assert output.loc[0, MESSAGE_COLUMN] == "Extra Money Taken"
    assert cases[0]["final_decision"]["decision_source"] == "llm"
