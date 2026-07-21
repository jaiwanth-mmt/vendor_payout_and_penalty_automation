from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.models import JobResponse, WarningItem


STEP_DEFINITIONS: list[tuple[str, str]] = [
    ("upload_received", "Upload received"),
    ("workbook_parsed", "Workbook parsed"),
    ("date_filtered", "Date filtered"),
    ("filters_applied", "CARBD and recoverable filters applied"),
    ("duplicates_consolidated", "Duplicate bookings consolidated"),
    ("categories_split", "Subcategories split"),
    ("tracking_matched", "Live tracking matched"),
    ("categories_processed", "Subcategories processed"),
    ("package_prepared", "ZIP package prepared"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            }
        }
        payload["warnings"] = [WarningItem(**warning) for warning in payload["warnings"]]
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
