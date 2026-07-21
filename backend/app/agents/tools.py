"""LangGraph @tool evidence gatherers for investigation nodes."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from backend.app.agents.models import clean_text
from backend.app.agents.source_alignment import build_source_alignment, compact_source_analysis
from backend.app.core.tracking_utils import first_tracking_row, raw_tracking_value


SOURCE_TITLES = {
    "comments": "Customer call transcript",
    "remarks": "QlikSense remarks",
    "sub_category": "QlikSense sub category",
}
SOURCE_LABELS = {
    "comments": "comments",
    "remarks": "Remarks",
    "sub_category": "Sub Category",
}


def _state_dict(state: dict[str, Any] | Any) -> dict[str, Any]:
    if isinstance(state, dict):
        return state
    return dict(state)


@tool
def get_comments(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """Return customer call comments text for the current booking."""
    data = _state_dict(state)
    text = clean_text(data.get("comments"))
    booking_id = clean_text(data.get("booking_id"))
    return {
        "tool": "get_comments",
        "evidence": {
            "id": f"{booking_id}:comments",
            "title": SOURCE_TITLES["comments"],
            "source": "source_alignment",
            "status": "available" if text else "missing",
            "summary": "comments text is available for source alignment." if text else "comments text is missing.",
            "fields": {"source_field": "comments", "source_label": "comments", "text": text, "comments": text},
            "error": None,
        },
        "text": text,
    }


@tool
def get_remarks(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """Return QlikSense Remarks text for the current booking."""
    data = _state_dict(state)
    text = clean_text(data.get("remarks"))
    booking_id = clean_text(data.get("booking_id"))
    return {
        "tool": "get_remarks",
        "evidence": {
            "id": f"{booking_id}:remarks",
            "title": SOURCE_TITLES["remarks"],
            "source": "source_alignment",
            "status": "available" if text else "missing",
            "summary": "Remarks text is available for source alignment." if text else "Remarks text is missing.",
            "fields": {"source_field": "remarks", "source_label": "Remarks", "text": text, "remarks": text},
            "error": None,
        },
        "text": text,
    }


@tool
def get_sub_category(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """Return Sub Category row context for the current booking."""
    data = _state_dict(state)
    text = clean_text(data.get("sub_category"))
    booking_id = clean_text(data.get("booking_id"))
    return {
        "tool": "get_sub_category",
        "evidence": {
            "id": f"{booking_id}:sub_category",
            "title": SOURCE_TITLES["sub_category"],
            "source": "source_alignment",
            "status": "available" if text else "missing",
            "summary": "Sub Category text is available." if text else "Sub Category text is missing.",
            "fields": {
                "source_field": "sub_category",
                "source_label": "Sub Category",
                "text": text,
                "sub_category": text,
            },
            "error": None,
        },
        "text": text,
    }


@tool
def get_source_alignment(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """
    Return source-alignment analysis.

    Primary text priority remains comments → Remarks; Sub Category is row context.
    """
    data = _state_dict(state)
    booking_id = clean_text(data.get("booking_id"))
    analysis = data.get("source_analysis") or {}
    if not analysis:
        from backend.app.agents.models import ClaimCase

        case = ClaimCase(
            booking_id=booking_id,
            sub_category=clean_text(data.get("sub_category")),
            remarks=clean_text(data.get("remarks")),
            recoverable_amount=float(data.get("recoverable_amount") or 0),
            row_index=int(data.get("row_index") or 0),
            comments=clean_text(data.get("comments")),
            message=clean_text(data.get("message")),
            vendor_name=clean_text(data.get("vendor_name")) or "Unknown vendor",
        )
        analysis = build_source_alignment(case).to_dict()

    review_status = clean_text(analysis.get("review_status"))
    return {
        "tool": "get_source_alignment",
        "evidence": {
            "id": f"{booking_id}:source_alignment",
            "title": "Source alignment",
            "source": "source_alignment",
            "status": "missing" if review_status == "missing_evidence" else "available",
            "summary": clean_text(analysis.get("reason")),
            "fields": compact_source_analysis(analysis),
            "error": None,
        },
        "analysis": analysis,
    }


@tool
def get_tracking_context(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """Return live tracking context (timing/fare/vehicle hints) for the booking when available."""
    data = _state_dict(state)
    booking_id = clean_text(data.get("booking_id"))
    tracking = data.get("tracking_context") or {}
    row = tracking.get("first_row") if isinstance(tracking, dict) else {}
    if not isinstance(row, dict):
        row = {}
    fields = {
        "order_reference_number": raw_tracking_value(row.get("order_reference_number")),
        "start_time": raw_tracking_value(row.get("start_time")),
        "end_time": raw_tracking_value(row.get("end_time")),
        "pickup_time": raw_tracking_value(row.get("pickup_time")),
        "drop_time": raw_tracking_value(row.get("drop_time")),
        "fare": raw_tracking_value(row.get("fare") or row.get("total_fare")),
        "vehicle_type": raw_tracking_value(row.get("vehicle_type") or row.get("car_type")),
        "driver_name": raw_tracking_value(row.get("driver_name")),
    }
    available = any(fields.values())
    return {
        "tool": "get_tracking_context",
        "evidence": {
            "id": f"{booking_id}:tracking",
            "title": "Tracking context",
            "source": "tracking",
            "status": "available" if available else "missing",
            "summary": "Tracking context is available." if available else "No tracking row was matched.",
            "fields": fields,
            "error": None,
        },
        "fields": fields,
    }


@tool
def get_vendor_context(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """Return vendor / supplier context for the booking."""
    data = _state_dict(state)
    booking_id = clean_text(data.get("booking_id"))
    vendor_name = clean_text(data.get("vendor_name")) or "Unknown vendor"
    tracking = data.get("tracking_context") or {}
    supplier_id = ""
    if isinstance(tracking, dict):
        row = tracking.get("first_row") or {}
        if isinstance(row, dict):
            supplier_id = raw_tracking_value(row.get("supplier_id") or row.get("oid"))
    fields = {"vendor_name": vendor_name, "supplier_id": supplier_id}
    return {
        "tool": "get_vendor_context",
        "evidence": {
            "id": f"{booking_id}:vendor",
            "title": "Vendor context",
            "source": "tracking",
            "status": "available",
            "summary": f"Vendor: {vendor_name}",
            "fields": fields,
            "error": None,
        },
        "fields": fields,
    }


INVESTIGATION_TOOLS = [
    get_comments,
    get_remarks,
    get_sub_category,
    get_source_alignment,
    get_tracking_context,
    get_vendor_context,
]


def build_tracking_context(bookings: dict[str, Any], booking_id: str) -> dict[str, Any]:
    row = first_tracking_row(bookings, booking_id)
    return {"first_row": row, "booking_id": booking_id}

