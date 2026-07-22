from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.models import JobResponse, PendingInterrupt, WarningItem


STEP_DEFINITIONS: list[tuple[str, str]] = [
    ("upload_received", "Upload received"),
    ("workbook_parsed", "Workbook parsed"),
    ("date_filtered", "Date filtered"),
    ("filters_applied", "CARBD and recoverable filters applied"),
    ("duplicates_consolidated", "Duplicate bookings consolidated"),
    ("categories_split", "Subcategories split"),
    ("tracking_matched", "Live tracking matched"),
    ("categories_processed", "Subcategories processed"),
    ("agent_investigation", "LangGraph investigation"),
    ("package_prepared", "ZIP package prepared"),
]

# Node id → executive-facing stage (order matters for status line).
INVESTIGATION_STAGE_DEFS: list[tuple[str, str]] = [
    ("intake", "Intake"),
    ("evidence_agent", "Evidence gathering"),
    ("specialist", "Specialist review"),
    ("judge", "Judge verification"),
    ("human_review", "Human review"),
    ("finalize", "Case finalized"),
    ("portfolio_summary", "Portfolio summary"),
    ("vendor_penalty_analysis", "Vendor analysis"),
]

STAGE_DONE_STATUSES = frozenset({"completed", "skipped", "warning"})
GRAPH_EVENT_RETENTION = 40


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_investigation_summary(*, total_cases: int = 0) -> dict[str, Any]:
    return {
        "total_cases": max(0, total_cases),
        "cases_seen": 0,
        "cases_finalized": 0,
        "pending_review": 0,
        "status_line": "Investigation has not started yet.",
        "stages": [
            {
                "id": stage_id,
                "label": label,
                "completed_units": 0,
                "total_units": max(0, total_cases),
                "status": "pending",
            }
            for stage_id, label in INVESTIGATION_STAGE_DEFS
        ],
    }


def _stage_status(*, completed: int, total: int, pending_review: int = 0, stage_id: str = "") -> str:
    if total <= 0 and completed <= 0:
        return "pending"
    if stage_id == "human_review" and pending_review > 0:
        return "warning"
    if total > 0 and completed >= total:
        return "completed"
    if completed > 0:
        return "running"
    return "pending"


def rebuild_investigation_summary(job: dict[str, Any]) -> dict[str, Any]:
    tracker: dict[str, set[str]] = job.setdefault(
        "_investigation_tracker",
        {stage_id: set() for stage_id, _ in INVESTIGATION_STAGE_DEFS},
    )
    pending_bookings: set[str] = job.setdefault("_investigation_pending_review", set())
    seen: set[str] = job.setdefault("_investigation_seen", set())
    total = int(job.get("_investigation_total_cases") or 0)
    cases_seen = len(seen)
    if total < cases_seen:
        total = cases_seen
    job["_investigation_total_cases"] = total

    stages = []
    for stage_id, label in INVESTIGATION_STAGE_DEFS:
        completed = len(tracker.get(stage_id, set()))
        stage_total = total if stage_id not in {"portfolio_summary", "vendor_penalty_analysis"} else max(total, 1)
        if stage_id in {"portfolio_summary", "vendor_penalty_analysis"}:
            # Job-level stages: 0 or 1 completion unit.
            completed_units = 1 if completed else 0
            total_units = 1 if total > 0 else 0
        else:
            completed_units = completed
            total_units = total
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "completed_units": completed_units,
                "total_units": total_units,
                "status": _stage_status(
                    completed=completed_units,
                    total=total_units,
                    pending_review=len(pending_bookings),
                    stage_id=stage_id,
                ),
            }
        )

    finalized = len(tracker.get("finalize", set()))
    pending_review = len(pending_bookings)
    if pending_review:
        status_line = (
            f"Paused for human review · {pending_review} booking"
            f"{'s' if pending_review != 1 else ''} waiting · {finalized} of {total or cases_seen} finalized"
        )
    elif total > 0 and finalized >= total and any(len(tracker.get(s, set())) for s, _ in INVESTIGATION_STAGE_DEFS if s.startswith("portfolio")):
        status_line = f"Investigation complete · {finalized} bookings reviewed"
    elif cases_seen:
        # Find furthest active stage for a calm headline.
        active_label = "Intake"
        for stage in stages:
            if stage["status"] in {"running", "warning"} or (
                stage["total_units"] > 0 and stage["completed_units"] < stage["total_units"] and stage["completed_units"] > 0
            ):
                active_label = stage["label"]
        status_line = f"{active_label} · {finalized} of {total or cases_seen} bookings finalized"
    else:
        status_line = "Waiting to start investigation."

    summary = {
        "total_cases": total,
        "cases_seen": cases_seen,
        "cases_finalized": finalized,
        "pending_review": pending_review,
        "status_line": status_line,
        "stages": stages,
    }
    job["investigation_summary"] = summary
    return summary


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def create_job(
        self,
        *,
        job_id: str,
        original_filename: str,
        start_date: str,
        end_date: str,
        job_dir: Path,
        upload_path: Path,
    ) -> None:
        now = utc_now()
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "current_step": None,
                "original_filename": original_filename,
                "start_date": start_date,
                "end_date": end_date,
                "created_at": now,
                "updated_at": now,
                "job_dir": job_dir,
                "upload_path": upload_path,
                "package_path": None,
                "final_output_path": None,
                "agent_audit_path": None,
                "review_queue_path": None,
                "agent_summary_path": None,
                "steps": [
                    {
                        "id": step_id,
                        "label": label,
                        "status": "pending",
                        "message": "",
                        "completed_units": 0,
                        "total_units": 0,
                        "started_at": None,
                        "completed_at": None,
                    }
                    for step_id, label in STEP_DEFINITIONS
                ],
                "metrics": {},
                "warnings": [],
                "category_progress": [],
                "category_outputs": [],
                "final_output": None,
                "agent_summary": None,
                "case_counts": {},
                "agent_progress": [],
                "agent_cases": [],
                "graph_events": [],
                "pending_interrupts": [],
                "graph_topology": None,
                "investigation_summary": empty_investigation_summary(),
                "_investigation_tracker": {stage_id: set() for stage_id, _ in INVESTIGATION_STAGE_DEFS},
                "_investigation_pending_review": set(),
                "_investigation_seen": set(),
                "_investigation_total_cases": 0,
                "download_ready": False,
                "error": None,
            }

    def mark_step_running(self, job_id: str, step_id: str, message: str = "") -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["status"] = "running"
            job["current_step"] = step_id
            job["updated_at"] = now
            step = self._get_step(job, step_id)
            step["status"] = "running"
            step["message"] = message
            step["started_at"] = step["started_at"] or now
            step["completed_at"] = None

    def mark_step_completed(self, job_id: str, step_id: str, message: str = "") -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["updated_at"] = now
            step = self._get_step(job, step_id)
            step["status"] = "completed"
            step["message"] = message or step["message"]
            if step["total_units"] and step["completed_units"] < step["total_units"]:
                step["completed_units"] = step["total_units"]
            step["completed_at"] = now

    def update_step_units(
        self,
        job_id: str,
        step_id: str,
        *,
        completed_units: int,
        total_units: int,
        message: str = "",
    ) -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["updated_at"] = now
            step = self._get_step(job, step_id)
            step["completed_units"] = completed_units
            step["total_units"] = total_units
            if message:
                step["message"] = message

    def initialize_category_progress(self, job_id: str, categories: list[dict[str, Any]]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["category_progress"] = [
                {
                    "name": category["name"],
                    "slug": category["slug"],
                    "row_count": category["row_count"],
                    "status": "pending",
                    "message": "Waiting to process",
                    "started_at": None,
                    "completed_at": None,
                    "cab_delay": category.get("cab_delay"),
                }
                for category in categories
            ]
            job["updated_at"] = utc_now()

    def update_category_progress(
        self,
        job_id: str,
        slug: str,
        *,
        status: str | None = None,
        message: str | None = None,
        cab_delay: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            for category in job["category_progress"]:
                if category["slug"] != slug:
                    continue

                if status:
                    category["status"] = status
                    if status == "running":
                        category["started_at"] = category["started_at"] or now
                        category["completed_at"] = None
                    if status in {"completed", "failed"}:
                        category["completed_at"] = now
                if message is not None:
                    category["message"] = message
                if cab_delay is not None:
                    current = category.get("cab_delay") or {}
                    current.update(cab_delay)
                    category["cab_delay"] = current
                break
            job["updated_at"] = now

    def add_warning(self, job_id: str, warning: dict[str, Any]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["warnings"].append(warning)
            job["updated_at"] = utc_now()

    def init_investigation_progress(self, job_id: str, *, total_cases: int) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["_investigation_total_cases"] = max(0, int(total_cases))
            job.setdefault("_investigation_tracker", {stage_id: set() for stage_id, _ in INVESTIGATION_STAGE_DEFS})
            job.setdefault("_investigation_pending_review", set())
            job.setdefault("_investigation_seen", set())
            rebuild_investigation_summary(job)
            job["updated_at"] = utc_now()

    def append_graph_event(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            events = job.setdefault("graph_events", [])
            events.append(event)
            if len(events) > GRAPH_EVENT_RETENTION:
                del events[: len(events) - GRAPH_EVENT_RETENTION]

            tracker: dict[str, set[str]] = job.setdefault(
                "_investigation_tracker",
                {stage_id: set() for stage_id, _ in INVESTIGATION_STAGE_DEFS},
            )
            pending_bookings: set[str] = job.setdefault("_investigation_pending_review", set())
            seen: set[str] = job.setdefault("_investigation_seen", set())

            booking_id = str(event.get("booking_id") or "").strip()
            node = str(event.get("node") or "").strip()
            event_type = str(event.get("type") or "").strip()
            status = str(event.get("status") or "").strip()

            if booking_id:
                seen.add(booking_id)

            if event_type == "interrupt" and booking_id:
                pending_bookings.add(booking_id)
                tracker.setdefault("human_review", set())
            elif event_type == "node" and node in tracker:
                if status in STAGE_DONE_STATUSES:
                    key = booking_id or "__job__"
                    if node in {"portfolio_summary", "vendor_penalty_analysis"}:
                        key = "__job__"
                    tracker[node].add(key)
                    if node == "finalize" and booking_id:
                        pending_bookings.discard(booking_id)
                    if node == "human_review" and status == "skipped" and booking_id:
                        pending_bookings.discard(booking_id)

            rebuild_investigation_summary(job)

            # Keep investigation step message calm and current.
            try:
                step = self._get_step(job, "agent_investigation")
                summary = job.get("investigation_summary") or {}
                if job.get("status") == "running":
                    step["status"] = "running"
                    step["message"] = summary.get("status_line") or step.get("message") or ""
                    step["completed_units"] = int(summary.get("cases_finalized") or 0)
                    step["total_units"] = int(summary.get("total_cases") or 0)
                    step["started_at"] = step["started_at"] or utc_now()
            except KeyError:
                pass

            job["updated_at"] = utc_now()

    def set_pending_interrupts(self, job_id: str, interrupts: list[dict[str, Any]]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["pending_interrupts"] = interrupts
            pending_bookings: set[str] = job.setdefault("_investigation_pending_review", set())
            pending_bookings.clear()
            for item in interrupts:
                booking_id = str(item.get("booking_id") or "").strip()
                if booking_id:
                    pending_bookings.add(booking_id)
            rebuild_investigation_summary(job)
            summary = job.get("investigation_summary") or {}
            try:
                step = self._get_step(job, "agent_investigation")
                if job.get("status") == "awaiting_review":
                    step["status"] = "warning" if interrupts else "running"
                    step["message"] = summary.get("status_line") or (
                        f"{len(interrupts)} cases awaiting human review" if interrupts else "Resuming after human review"
                    )
                    step["completed_units"] = int(summary.get("cases_finalized") or 0)
                    step["total_units"] = int(summary.get("total_cases") or 0)
            except KeyError:
                pass
            job["updated_at"] = utc_now()

    def set_graph_topology(self, job_id: str, topology: dict[str, Any]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["graph_topology"] = topology
            job["updated_at"] = utc_now()

    def mark_awaiting_review(
        self,
        job_id: str,
        *,
        metrics: dict[str, Any],
        category_outputs: list[dict[str, Any]],
        case_counts: dict[str, int],
        agent_progress: list[dict[str, Any]],
        agent_cases: list[dict[str, Any]],
        pending_interrupts: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["status"] = "awaiting_review"
            job["current_step"] = "agent_investigation"
            job["metrics"] = metrics
            job["category_outputs"] = category_outputs
            job["case_counts"] = case_counts
            job["agent_progress"] = agent_progress
            job["agent_cases"] = agent_cases
            job["pending_interrupts"] = pending_interrupts
            job["download_ready"] = False
            pending_bookings: set[str] = job.setdefault("_investigation_pending_review", set())
            pending_bookings.clear()
            for item in pending_interrupts:
                booking_id = str(item.get("booking_id") or "").strip()
                if booking_id:
                    pending_bookings.add(booking_id)
            rebuild_investigation_summary(job)
            job["updated_at"] = now
            step = self._get_step(job, "agent_investigation")
            step["status"] = "warning"
            step["message"] = (job.get("investigation_summary") or {}).get("status_line") or (
                f"{len(pending_interrupts)} cases awaiting human review"
            )
            step["started_at"] = step["started_at"] or now

    def update_agent_cases(self, job_id: str, agent_cases: list[dict[str, Any]]) -> None:
        with self._lock:
            job = self._get_job(job_id)
            job["agent_cases"] = agent_cases
            job["updated_at"] = utc_now()

    def complete_job(
        self,
        job_id: str,
        *,
        metrics: dict[str, Any],
        category_outputs: list[dict[str, Any]],
        package_path: Path,
        final_output_path: Path,
        final_output: dict[str, Any],
        agent_audit_path: Path,
        review_queue_path: Path,
        agent_summary_path: Path,
        agent_summary: dict[str, Any],
        case_counts: dict[str, int],
        agent_progress: list[dict[str, Any]],
        agent_cases: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["status"] = "succeeded"
            job["current_step"] = None
            job["metrics"] = metrics
            job["category_outputs"] = category_outputs
            job["package_path"] = package_path
            job["final_output_path"] = final_output_path
            job["final_output"] = final_output
            job["agent_audit_path"] = agent_audit_path
            job["review_queue_path"] = review_queue_path
            job["agent_summary_path"] = agent_summary_path
            job["agent_summary"] = agent_summary
            job["case_counts"] = case_counts
            job["agent_progress"] = agent_progress
            job["agent_cases"] = agent_cases
            job["download_ready"] = package_path.exists()
            job["_investigation_total_cases"] = int(
                case_counts.get("total_cases") or job.get("_investigation_total_cases") or 0
            )
            tracker = job.setdefault(
                "_investigation_tracker",
                {stage_id: set() for stage_id, _ in INVESTIGATION_STAGE_DEFS},
            )
            for booking in agent_cases:
                booking_id = str(booking.get("booking_id") or "").strip()
                if not booking_id:
                    continue
                for stage_id, _ in INVESTIGATION_STAGE_DEFS:
                    if stage_id in {"portfolio_summary", "vendor_penalty_analysis"}:
                        continue
                    tracker.setdefault(stage_id, set()).add(booking_id)
            tracker.setdefault("portfolio_summary", set()).add("__job__")
            tracker.setdefault("vendor_penalty_analysis", set()).add("__job__")
            job.setdefault("_investigation_pending_review", set()).clear()
            rebuild_investigation_summary(job)
            job["updated_at"] = now

    def fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._get_job(job_id)
            now = utc_now()
            job["status"] = "failed"
            job["error"] = error
            job["updated_at"] = now
            current_step = job.get("current_step")
            if current_step:
                step = self._get_step(job, current_step)
                step["status"] = "failed"
                step["message"] = error
                step["completed_at"] = now

    def snapshot(self, job_id: str) -> JobResponse:
        with self._lock:
            job = deepcopy(self._get_job(job_id))

        payload = {
            key: value
            for key, value in job.items()
            if key
            not in {
                "job_dir",
                "upload_path",
                "package_path",
                "final_output_path",
                "agent_audit_path",
                "review_queue_path",
                "agent_summary_path",
                "agent_cases",
                "_investigation_tracker",
                "_investigation_pending_review",
                "_investigation_seen",
                "_investigation_total_cases",
            }
        }
        payload["warnings"] = [WarningItem(**warning) for warning in payload["warnings"]]
        payload["pending_interrupts"] = [
            PendingInterrupt(
                booking_id=str(item.get("booking_id", "")),
                thread_id=str(item.get("thread_id", "")),
                payload=dict(item.get("payload") or {}),
            )
            for item in payload.get("pending_interrupts") or []
        ]
        if not payload.get("investigation_summary"):
            payload["investigation_summary"] = empty_investigation_summary()
        # Technical detail only — keep a short tail for the collapsed UI panel.
        payload["graph_events"] = list(payload.get("graph_events") or [])[-GRAPH_EVENT_RETENTION:]
        return JobResponse(**payload)

    def get_package_path(self, job_id: str) -> Path | None:
        with self._lock:
            package_path = self._get_job(job_id).get("package_path")
            return Path(package_path) if package_path else None

    def get_final_output_path(self, job_id: str) -> Path | None:
        with self._lock:
            final_output_path = self._get_job(job_id).get("final_output_path")
            return Path(final_output_path) if final_output_path else None

    def get_agent_audit_path(self, job_id: str) -> Path | None:
        with self._lock:
            path = self._get_job(job_id).get("agent_audit_path")
            return Path(path) if path else None

    def get_review_queue_path(self, job_id: str) -> Path | None:
        with self._lock:
            path = self._get_job(job_id).get("review_queue_path")
            return Path(path) if path else None

    def get_job_dir(self, job_id: str) -> Path | None:
        with self._lock:
            job_dir = self._get_job(job_id).get("job_dir")
            return Path(job_dir) if job_dir else None

    def get_category_processed_path(self, job_id: str, slug: str) -> Path | None:
        with self._lock:
            job = self._get_job(job_id)
            job_dir = job.get("job_dir")
            if job_dir is None:
                return None

            for category in job.get("category_outputs", []):
                if category.get("slug") == slug:
                    filename = category.get("processed_filename")
                    return Path(job_dir) / filename if filename else None
            return None

    def get_agent_cases(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._get_job(job_id).get("agent_cases", []))

    def _get_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return self._jobs[job_id]

    @staticmethod
    def _get_step(job: dict[str, Any], step_id: str) -> dict[str, Any]:
        for step in job["steps"]:
            if step["id"] == step_id:
                return step
        raise KeyError(step_id)
