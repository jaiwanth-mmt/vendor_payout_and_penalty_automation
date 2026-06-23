from __future__ import annotations

import os
from typing import Any

from backend.app.agents.models import AgentTraceStep, ClaimCase, EvidenceItem, clean_text, json_safe
from backend.app.domain.cab_delay_enrichment import (
    booking_comments,
    build_timing_context,
    duration_minutes,
    first_tracking_row,
    format_duration,
    format_ist_from_utc,
    format_existing_ist_time,
)


TRACKING_SOURCE = "tracking_json_fallback"
REDASH_SOURCE = "redash_comments_fallback"


class EvidenceToolset:
    def __init__(self, tracking_bookings: dict[str, Any]) -> None:
        self.tracking_bookings = tracking_bookings
        self.live_tracking_configured = bool(os.getenv("MYSQL_PASSWORD"))
        self.live_comments_configured = bool(os.getenv("REDASH_API_KEY"))

    def gather_for_case(self, case: ClaimCase) -> tuple[list[EvidenceItem], list[AgentTraceStep]]:
        evidence: list[EvidenceItem] = [self.penalty_row_evidence(case)]
        trace: list[AgentTraceStep] = [
            AgentTraceStep(
                agent="Evidence Retrieval Agent",
                action="plan_evidence",
                status="completed",
                summary=self._live_source_summary(),
            )
        ]

        tracking_evidence = self.tracking_report_lookup(case.booking_id)
        evidence.append(tracking_evidence)
        trace.append(
            AgentTraceStep(
                agent="Evidence Retrieval Agent",
                action="fetch_tracking_report",
                status="completed" if tracking_evidence.status == "available" else "warning",
                summary=tracking_evidence.summary,
                evidence_ids=[tracking_evidence.id],
            )
        )

        comment_evidence = self.call_comment_lookup(case.booking_id)
        evidence.append(comment_evidence)
        trace.append(
            AgentTraceStep(
                agent="Evidence Retrieval Agent",
                action="fetch_call_comments",
                status="completed" if comment_evidence.status == "available" else "warning",
                summary=comment_evidence.summary,
                evidence_ids=[comment_evidence.id],
            )
        )

        tracking_row = first_tracking_row(self.tracking_bookings, case.booking_id)
        if tracking_row:
            evidence.extend(
                [
                    self.timing_evidence(case.booking_id, tracking_row),
                    self.fare_payment_evidence(case.booking_id, tracking_row),
                    self.status_evidence(case.booking_id, tracking_row),
                    self.vehicle_evidence(case.booking_id, tracking_row),
                ]
            )

        return evidence, trace

    def penalty_row_evidence(self, case: ClaimCase) -> EvidenceItem:
        return EvidenceItem(
            id=f"{case.booking_id}:penalty",
            title="QlikSense penalty row",
            source="uploaded_workbook",
            status="available",
            summary=(
                f"{case.sub_category} claim with recoverable amount "
                f"{case.recoverable_amount:g}."
            ),
            fields={
                "booking_id": case.booking_id,
                "sub_category": case.sub_category,
                "remarks": case.remarks,
                "recoverable_amount": case.recoverable_amount,
            },
        )

    def tracking_report_lookup(self, booking_id: str) -> EvidenceItem:
        tracking_row = first_tracking_row(self.tracking_bookings, booking_id)
        if not tracking_row:
            return EvidenceItem(
                id=f"{booking_id}:tracking",
                title="Incabs tracking report",
                source=TRACKING_SOURCE,
                status="missing",
                summary="No tracking row was available for this booking.",
                fields={},
            )

        present_fields = sorted(key for key, value in tracking_row.items() if clean_text(value))
        return EvidenceItem(
            id=f"{booking_id}:tracking",
            title="Incabs tracking report",
            source=TRACKING_SOURCE,
            status="available",
            summary=f"Tracking row available with {len(present_fields)} populated fields.",
            fields={"present_fields": present_fields, **json_safe(tracking_row)},
        )

    def call_comment_lookup(self, booking_id: str) -> EvidenceItem:
        comments = booking_comments(self.tracking_bookings, booking_id)
        if not comments:
            return EvidenceItem(
                id=f"{booking_id}:comments",
                title="Customer call comments",
                source=REDASH_SOURCE,
                status="missing",
                summary="No customer call comment was available.",
                fields={},
            )

        return EvidenceItem(
            id=f"{booking_id}:comments",
            title="Customer call comments",
            source=REDASH_SOURCE,
            status="available",
            summary=comments[:220],
            fields={"comments": comments},
        )

    def timing_evidence(self, booking_id: str, tracking_row: dict[str, Any]) -> EvidenceItem:
        timing = build_timing_context(tracking_row)
        pickup_to_arrival = duration_minutes(timing.scheduled_pickup_ist, timing.driver_arrived)
        pickup_to_boarding = duration_minutes(timing.scheduled_pickup_ist, timing.boarded)
        pickup_to_start = duration_minutes(timing.scheduled_pickup_ist, timing.driver_started)
        summary_parts = []
        if pickup_to_arrival is not None:
            summary_parts.append(f"driver arrived {format_duration(pickup_to_arrival)} after pickup")
        if pickup_to_boarding is not None:
            summary_parts.append(f"customer boarded {format_duration(pickup_to_boarding)} after pickup")
        if pickup_to_start is not None:
            summary_parts.append(f"driver started {format_duration(pickup_to_start)} after pickup")

        return EvidenceItem(
            id=f"{booking_id}:timing",
            title="Pickup and driver timing evidence",
            source=TRACKING_SOURCE,
            status="available" if summary_parts else "missing",
            summary=", ".join(summary_parts) if summary_parts else "Timing fields were incomplete.",
            fields={
                "preferred_pickup_ist": format_ist_from_utc(tracking_row.get("start_time")),
                "driver_started_ist": format_existing_ist_time(tracking_row.get("driver_started")),
                "driver_arrived_ist": format_existing_ist_time(tracking_row.get("driver_arrived")),
                "boarded_ist": format_existing_ist_time(tracking_row.get("boarded")),
                "driver_started_after_pickup_minutes": pickup_to_start,
                "driver_arrived_after_pickup_minutes": pickup_to_arrival,
                "boarded_after_pickup_minutes": pickup_to_boarding,
            },
        )

    def fare_payment_evidence(self, booking_id: str, tracking_row: dict[str, Any]) -> EvidenceItem:
        fields = {
            key: tracking_row.get(key)
            for key in [
                "amount",
                "base_amount",
                "amount_paid",
                "cash_collected",
                "route_toll_charges",
                "toll_charges",
                "parking_charges",
                "state_tax",
                "airport_entry_fee",
                "night_charges",
                "waiting_charges",
                "extra_travelled_fare",
            ]
            if clean_text(tracking_row.get(key))
        }
        return EvidenceItem(
            id=f"{booking_id}:fare",
            title="Fare, toll, and payment evidence",
            source=TRACKING_SOURCE,
            status="available" if fields else "missing",
            summary=(
                f"Fare/payment fields available: {', '.join(sorted(fields))}."
                if fields
                else "No fare/payment fields were available."
            ),
            fields=json_safe(fields),
        )

    def status_evidence(self, booking_id: str, tracking_row: dict[str, Any]) -> EvidenceItem:
        fields = {
            key: tracking_row.get(key)
            for key in [
                "booking_status",
                "tracking_status",
                "is_cancelled",
                "is_unfulfilled",
                "terminal_status",
                "terminal_status_reason",
                "not_boarded_timestamp",
                "unfulfilled_reason",
            ]
            if clean_text(tracking_row.get(key))
        }
        status_text = ", ".join(f"{key}={value}" for key, value in fields.items())
        return EvidenceItem(
            id=f"{booking_id}:status",
            title="Booking and fulfillment status evidence",
            source=TRACKING_SOURCE,
            status="available" if fields else "missing",
            summary=status_text or "No booking/tracking status fields were available.",
            fields=json_safe(fields),
        )

    def vehicle_evidence(self, booking_id: str, tracking_row: dict[str, Any]) -> EvidenceItem:
        fields = {
            key: tracking_row.get(key)
            for key in ["vehicle_subcategory", "vehicle_type", "vehicle_sku_id"]
            if clean_text(tracking_row.get(key))
        }
        return EvidenceItem(
            id=f"{booking_id}:vehicle",
            title="Vehicle category evidence",
            source=TRACKING_SOURCE,
            status="available" if fields else "missing",
            summary=(
                "Vehicle evidence: " + ", ".join(f"{key}={value}" for key, value in fields.items())
                if fields
                else "No vehicle category fields were available."
            ),
            fields=json_safe(fields),
        )

    def _live_source_summary(self) -> str:
        tracking = "configured" if self.live_tracking_configured else "not configured"
        comments = "configured" if self.live_comments_configured else "not configured"
        return (
            "Evidence plan: use live tools when configured, then bundled tracking JSON fallback. "
            f"MySQL is {tracking}; Redash is {comments}."
        )
