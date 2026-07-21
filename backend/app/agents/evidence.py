from __future__ import annotations

from typing import Any

from backend.app.agents.models import AgentTraceStep, ClaimCase, EvidenceItem, clean_text
from backend.app.agents.source_alignment import build_source_alignment, compact_source_analysis


SOURCE_HIERARCHY = ("comments", "remarks", "sub_category")
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


class EvidenceToolset:
    """Agent decisions use comments, Remarks, and Sub Category only; tracking rows are not exposed."""

    def __init__(self) -> None:
        pass

    def gather_for_case(self, case: ClaimCase) -> tuple[list[EvidenceItem], list[AgentTraceStep]]:
        if case.source_analysis:
            analysis_payload = case.source_analysis
        else:
            analysis = build_source_alignment(case)
            analysis_payload = analysis.to_dict()
            case.source_analysis = analysis_payload
        evidence = self.source_evidence(case)
        trace = [
            AgentTraceStep(
                agent="Evidence Retrieval Agent",
                action="compare_sources",
                status="completed" if clean_text(analysis_payload.get("review_status")) == "auto_ready" else "warning",
                summary=clean_text(analysis_payload.get("reason")),
                evidence_ids=[item.id for item in evidence if item.status == "available"],
                metadata={
                    "source_priority": ["comments", "remarks"],
                    "primary_source": clean_text(analysis_payload.get("primary_source")),
                    "source_alignment_status": clean_text(analysis_payload.get("status")),
                },
            )
        ]
        return evidence, trace

    def source_evidence(self, case: ClaimCase) -> list[EvidenceItem]:
        values = {
            "comments": case.comments,
            "remarks": case.remarks,
            "sub_category": case.sub_category,
        }
        items = [source_item(case, source_field, values[source_field]) for source_field in SOURCE_HIERARCHY]
        items.append(alignment_item(case))
        return items


def source_item(case: ClaimCase, source_field: str, value: Any) -> EvidenceItem:
    source_text = clean_text(value)
    status = "available" if source_text else "missing"
    summary = (
        f"{SOURCE_LABELS[source_field]} text is available for source alignment."
        if source_text
        else f"{SOURCE_LABELS[source_field]} text is missing."
    )
    return EvidenceItem(
        id=f"{case.booking_id}:{source_field}",
        title=SOURCE_TITLES[source_field],
        source="source_alignment",
        status=status,
        summary=summary,
        fields={
            "source_field": source_field,
            "source_label": SOURCE_LABELS[source_field],
            "text": source_text,
            source_field: source_text,
        },
    )


def alignment_item(case: ClaimCase) -> EvidenceItem:
    source_analysis = case.source_analysis
    review_status = clean_text(source_analysis.get("review_status"))
    return EvidenceItem(
        id=f"{case.booking_id}:source_alignment",
        title="Source alignment",
        source="source_alignment",
        status="missing" if review_status == "missing_evidence" else "available",
        summary=clean_text(source_analysis.get("reason")),
        fields=compact_source_analysis(source_analysis),
    )
