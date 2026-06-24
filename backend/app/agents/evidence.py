from __future__ import annotations

from typing import Any

from backend.app.agents.models import AgentTraceStep, ClaimCase, EvidenceItem, clean_text


SOURCE_HIERARCHY = ("comments", "remarks", "sub_category")
SOURCE_TITLES = {
    "comments": "Customer call comments",
    "remarks": "QlikSense remarks",
    "sub_category": "QlikSense sub category",
}
SOURCE_LABELS = {
    "comments": "comments",
    "remarks": "Remarks",
    "sub_category": "Sub Category",
}


class EvidenceToolset:
    def __init__(self, _tracking_bookings: dict[str, Any]) -> None:
        # The agent review contract is intentionally strict: decisions may only
        # use comments, then Remarks, then Sub Category.
        pass

    def gather_for_case(self, case: ClaimCase) -> tuple[list[EvidenceItem], list[AgentTraceStep]]:
        evidence = self.primary_source_evidence(case)
        trace = [
            AgentTraceStep(
                agent="Evidence Retrieval Agent",
                action="select_primary_source",
                status="completed" if evidence.status == "available" else "warning",
                summary=evidence.summary,
                evidence_ids=[evidence.id] if evidence.status == "available" else [],
                metadata={
                    "source_priority": list(SOURCE_HIERARCHY),
                    "selected_source": evidence.fields.get("source_field", ""),
                },
            )
        ]
        return [evidence], trace

    def primary_source_evidence(self, case: ClaimCase) -> EvidenceItem:
        source_field, source_text = selected_source(case)
        if not source_field:
            return EvidenceItem(
                id=f"{case.booking_id}:source",
                title="Agent source text",
                source="source_hierarchy",
                status="missing",
                summary="No comments, Remarks, or Sub Category text was available for agent review.",
                fields={"source_priority": list(SOURCE_HIERARCHY)},
            )

        return EvidenceItem(
            id=f"{case.booking_id}:{source_field}",
            title=SOURCE_TITLES[source_field],
            source="source_hierarchy",
            status="available",
            summary=f"Selected {SOURCE_LABELS[source_field]} as the primary agent source.",
            fields={
                "source_field": source_field,
                "source_label": SOURCE_LABELS[source_field],
                "text": source_text,
                source_field: source_text,
            },
        )


def selected_source(case: ClaimCase) -> tuple[str, str]:
    values = {
        "comments": case.comments,
        "remarks": case.remarks,
        "sub_category": case.sub_category,
    }
    for source_field in SOURCE_HIERARCHY:
        text = clean_text(values[source_field])
        if text:
            return source_field, text
    return "", ""
