from __future__ import annotations

import asyncio
import json

import pandas as pd

from backend.app.agents.models import AgentDecision, ClaimCase, EvidenceItem
from backend.app.agents.orchestrator import build_agent_progress, build_portfolio_summary_async, investigate_category_frame_async
from backend.app.agents.specialists import run_judge_agent_async, run_specialist_agent_async
from backend.app.domain.complaint_message import MESSAGE_COLUMN


def evidence_item(booking_id: str, suffix: str, *, status: str = "available") -> EvidenceItem:
    return EvidenceItem(
        id=f"{booking_id}:{suffix}",
        title=suffix.title(),
        source="test",
        status=status,  # type: ignore[arg-type]
        summary=f"{suffix} evidence",
        fields={"comments": "Customer said driver collected extra cash.", "driver_started_after_pickup_minutes": 22},
    )


def test_valid_specialist_llm_json_becomes_agent_decision() -> None:
    case = ClaimCase("B1", "Extra Money Taken", "driver collected extra", 80, 0)
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
                "rationale": "Comment and fare evidence support extra money taken.",
                "recommended_action": "Ready for Cab Ops recovery package",
                "review_status": "auto_ready",
                "review_reason": "Evidence is cited and sufficient.",
                "evidence_ids": ["B1:comments", "B1:fare"],
            }
        )

    asyncio.run(run_specialist_agent_async(case, llm_generator=llm, semaphore=asyncio.Semaphore(1)))

    assert case.specialist_decision is not None
    assert case.specialist_decision.decision_source == "llm"
    assert case.specialist_decision.complaint_categories == ["Extra Money Taken"]
    assert case.specialist_decision.evidence_ids == ["B1:comments", "B1:fare"]
    assert calls == [(8192, "medium")]


def test_invalid_specialist_llm_json_uses_fallback() -> None:
    case = ClaimCase("B1", "Extra Money Taken", "driver collected extra", 80, 0)
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
    case = ClaimCase("B1", "Cab Delay", "Cab Delay", 100, 0)
    case.evidence = [evidence_item("B1", "penalty"), evidence_item("B1", "timing")]

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


def test_judge_missing_evidence_guardrail_overrides_overconfident_llm() -> None:
    case = ClaimCase("B9", "Cab Delay", "Cab Delay", 100, 0)
    case.evidence = [evidence_item("B9", "penalty"), evidence_item("B9", "timing", status="missing")]
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
        evidence_ids=["B9:penalty"],
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
                "evidence_ids": ["B9:penalty"],
            }
        )

    asyncio.run(run_judge_agent_async(case, llm_generator=judge_llm, semaphore=asyncio.Semaphore(1)))

    assert case.judge_decision is not None
    assert case.judge_decision.decision_source == "llm"
    assert case.judge_decision.review_status == "missing_evidence"
    assert case.judge_decision.confidence <= 0.58
    assert calls == [(8192, "high")]


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
            "recoverable_amount": 100,
            "review_status": "auto_ready",
            "final_decision": {"confidence": 0.91},
            "evidence": [],
        }
    ]

    summary = asyncio.run(build_portfolio_summary_async(cases, llm_generator=llm, llm_concurrency=1))

    assert summary["executive_summary"] == "Portfolio summary from LLM."
    assert calls == [(4096, "medium")]


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
    }
    assert {item["agent"]: item["status"] for item in warning_progress} == {
        "Intake Agent": "completed",
        "Evidence Retrieval Agent": "warning",
        "Category Specialist Agents": "warning",
        "Judge Agent": "warning",
        "Portfolio Summary Agent": "warning",
    }
    assert {item["agent"]: item["status"] for item in failed_progress} == {
        "Intake Agent": "completed",
        "Evidence Retrieval Agent": "failed",
        "Category Specialist Agents": "failed",
        "Judge Agent": "failed",
        "Portfolio Summary Agent": "completed",
    }


def test_agent_decision_becomes_final_message() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "B5",
                "Sub Category": "Extra Money Taken",
                "Remarks": "driver collected extra",
                "Recoverable": 80,
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
