"""LangGraph investigation graph, tools, and HITL tests."""

from __future__ import annotations

import asyncio

import pandas as pd

from backend.app.agents.graphs import (
    build_case_graph,
    build_portfolio_graph,
    graph_topology_payload,
    sanitize_mermaid,
)
from backend.app.agents.runner import (
    get_pending_interrupts,
    investigate_category_frame_async,
    resume_case,
)
from backend.app.agents.tools import INVESTIGATION_TOOLS


def test_case_and_portfolio_graphs_compile_and_expose_mermaid() -> None:
    case_graph = build_case_graph(enable_hitl=True)
    portfolio_graph = build_portfolio_graph()
    case_mermaid = sanitize_mermaid(case_graph.get_graph().draw_mermaid())
    portfolio_mermaid = sanitize_mermaid(portfolio_graph.get_graph().draw_mermaid())
    assert "intake" in case_mermaid
    assert "evidence_agent" in case_mermaid
    assert "human_review" in case_mermaid
    assert "finalize" in case_mermaid
    assert "<p>" not in case_mermaid
    assert "portfolio_summary" in portfolio_mermaid
    topology = graph_topology_payload()
    assert "intake" in topology["case"]["nodes"]
    assert "vendor_penalty_analysis" in topology["portfolio"]["nodes"]
    assert "<p>" not in topology["case"]["mermaid"]


def test_sanitize_mermaid_strips_html_wrappers() -> None:
    raw = "graph TD;\n__start__([<p>__start__</p>]):::first\n"
    cleaned = sanitize_mermaid(raw)
    assert "<p>" not in cleaned
    assert "</p>" not in cleaned
    assert "__start__" in cleaned


def test_investigation_tools_are_registered() -> None:
    names = {tool.name for tool in INVESTIGATION_TOOLS}
    assert names == {
        "get_comments",
        "get_remarks",
        "get_sub_category",
        "get_source_alignment",
        "get_tracking_context",
        "get_vendor_context",
    }


def test_tools_return_tracking_and_source_evidence() -> None:
    state = {
        "booking_id": "NC9999999",
        "comments": "Customer said cab was late",
        "remarks": "Cab Delay",
        "sub_category": "Cab Delay",
        "message": "Cab Delay",
        "vendor_name": "Acme Cabs",
        "recoverable_amount": 120,
        "row_index": 0,
        "source_analysis": {},
        "tracking_context": {
            "first_row": {
                "order_reference_number": "NC9999999",
                "fare": "450",
                "vehicle_type": "Sedan",
                "supplier_id": "42",
            }
        },
    }
    comments = INVESTIGATION_TOOLS[0].invoke({"state": state})
    tracking = INVESTIGATION_TOOLS[4].invoke({"state": state})
    vendor = INVESTIGATION_TOOLS[5].invoke({"state": state})
    assert comments["evidence"]["status"] == "available"
    assert tracking["evidence"]["status"] == "available"
    assert tracking["fields"]["fare"] == "450"
    assert vendor["fields"]["vendor_name"] == "Acme Cabs"


def test_hitl_interrupt_and_resume() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "NC1111111",
                "Sub Category": "Cab Delay",
                "Remarks": "",
                "Recoverable": 50,
                "comments": "",
                "message": "",
                "vendor_name": "Vendor A",
            }
        ]
    )

    async def run() -> None:
        _output, cases = await investigate_category_frame_async(
            df,
            tracking_bookings={},
            llm_generator=None,
            llm_concurrency=1,
            job_id="test-hitl-job",
            enable_hitl=True,
        )
        assert cases[0]["pending_interrupt"] is True
        pending = get_pending_interrupts("test-hitl-job")
        assert len(pending) == 1
        resumed = await resume_case(
            job_id="test-hitl-job",
            booking_id="NC1111111",
            human_decision={
                "decision": "valid_penalty",
                "review_status": "auto_ready",
                "recommended_recovery_amount": 50,
                "review_reason": "Human approved",
            },
        )
        assert resumed["pending_interrupt"] is False
        assert resumed["review_status"] == "auto_ready"
        assert get_pending_interrupts("test-hitl-job") == []

    asyncio.run(run())


def test_investigation_without_hitl_completes_missing_evidence() -> None:
    df = pd.DataFrame(
        [
            {
                "Booking ID": "NC2222222",
                "Sub Category": "Cab Delay",
                "Remarks": "",
                "Recoverable": 50,
                "comments": "",
                "message": "",
                "vendor_name": "Vendor B",
            }
        ]
    )
    _output, cases = asyncio.run(
        investigate_category_frame_async(
            df,
            tracking_bookings={},
            llm_generator=None,
            llm_concurrency=1,
            job_id="test-no-hitl",
            enable_hitl=False,
        )
    )
    assert cases[0]["pending_interrupt"] is False
    assert cases[0]["review_status"] == "missing_evidence"
    assert any(call["name"] == "get_tracking_context" for call in cases[0].get("tool_calls", []))
