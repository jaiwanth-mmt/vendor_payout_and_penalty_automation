"""Orchestration for vendor penalty mail preview and send."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.agents.mailer.runner import run_mailer_graph
from backend.app.domain.cab_delay_enrichment import COMMENTS_COLUMN
from backend.app.integrations.smtp import (
    MailTransport,
    SmtpError,
    live_mail_transport_from_env,
    mailer_recipients_from_env,
)
from backend.app.services.package_builder import FINAL_EXPORT_COLUMNS, FINAL_OUTPUT_FILENAME, PROCESSED_CATEGORY_ROOT


MAILER_DISPATCH_FILENAME = "mailer_dispatch.json"
MailStatus = str

_JOB_LOCKS: dict[str, threading.RLock] = {}
_JOB_LOCKS_GUARD = threading.Lock()


def _job_lock(job_id: str) -> threading.RLock:
    with _JOB_LOCKS_GUARD:
        lock = _JOB_LOCKS.get(job_id)
        if lock is None:
            lock = threading.RLock()
            _JOB_LOCKS[job_id] = lock
        return lock


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mailer_dispatch_path(job_dir: Path) -> Path:
    return job_dir / MAILER_DISPATCH_FILENAME


def final_output_checksum(final_output_path: Path) -> str:
    digest = hashlib.sha256()
    with final_output_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 64)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_preview_token(*, job_id: str, checksum: str, recipients: list[str], drafts: list[dict[str, Any]]) -> str:
    payload = {
        "job_id": job_id,
        "checksum": checksum,
        "recipients": recipients,
        "assignments": [
            {
                "recipient": item.get("recipient"),
                "booking_id": item.get("booking_id"),
                "subject": item.get("subject"),
            }
            for item in drafts
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_dispatch(job_dir: Path) -> dict[str, Any] | None:
    path = mailer_dispatch_path(job_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_dispatch(job_dir: Path, payload: dict[str, Any]) -> Path:
    path = mailer_dispatch_path(job_dir)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _clean_cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _fine_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return int(number)
    return number


def load_call_transcripts(job_dir: Path) -> dict[str, str]:
    processed_root = job_dir / PROCESSED_CATEGORY_ROOT
    transcripts: dict[str, str] = {}
    if not processed_root.exists():
        return transcripts

    for path in sorted(processed_root.glob("*.xlsx")):
        frame = pd.read_excel(path)
        if frame.empty or "Booking ID" not in frame.columns:
            continue
        comments_column = COMMENTS_COLUMN if COMMENTS_COLUMN in frame.columns else None
        if comments_column is None:
            continue
        for _, row in frame.iterrows():
            booking_id = _clean_cell(row.get("Booking ID"))
            if not booking_id or booking_id in transcripts:
                continue
            comments = _clean_cell(row.get(comments_column))
            if comments:
                transcripts[booking_id] = comments
    return transcripts


def load_booking_rows_for_mailer(*, job_dir: Path, final_output_path: Path) -> list[dict[str, Any]]:
    frame = pd.read_excel(final_output_path)
    if frame.empty:
        raise ValueError("Final output has no rows to mail")

    for column in FINAL_EXPORT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    transcripts = load_call_transcripts(job_dir)
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        booking_id = _clean_cell(row.get("booking_id"))
        if not booking_id:
            continue
        rows.append(
            {
                "booking_id": booking_id,
                "title": _clean_cell(row.get("title")),
                "message": _clean_cell(row.get("message")),
                "fine": _fine_value(row.get("fine")),
                "call_transcript": transcripts.get(booking_id, ""),
                "complaint_reasons": _clean_cell(row.get("complaint_reasons")),
            }
        )
    if not rows:
        raise ValueError("Final output has no booking rows to mail")
    return rows


def dispatch_api_view(dispatch: dict[str, Any] | None) -> dict[str, Any]:
    if not dispatch:
        return {
            "status": "idle",
            "preview_token": None,
            "final_output_checksum": None,
            "recipients": [],
            "assignments": [],
            "drafts": [],
            "results": [],
            "sent_at": None,
            "error": None,
            "can_send": False,
        }

    status = str(dispatch.get("status") or "idle")
    drafts = list(dispatch.get("drafts") or [])
    return {
        "status": status,
        "preview_token": dispatch.get("preview_token"),
        "final_output_checksum": dispatch.get("final_output_checksum"),
        "recipients": list(dispatch.get("recipients") or []),
        "assignments": [
            {
                "recipient": item.get("recipient"),
                "booking_id": item.get("booking_id"),
                "subject": item.get("subject"),
            }
            for item in drafts
        ],
        "drafts": drafts,
        "results": list(dispatch.get("results") or []),
        "sent_at": dispatch.get("sent_at"),
        "error": dispatch.get("error"),
        "can_send": status in {"preview_ready", "failed", "partial"},
    }


async def preview_vendor_mails(
    *,
    job_id: str,
    job_dir: Path,
    final_output_path: Path,
    transport: MailTransport | None = None,
) -> dict[str, Any]:
    del transport  # preview never sends
    with _job_lock(job_id):
        checksum = final_output_checksum(final_output_path)
        existing = load_dispatch(job_dir)
        if existing and existing.get("final_output_checksum") == checksum and existing.get("drafts"):
            if str(existing.get("status") or "") == "sending":
                return dispatch_api_view(existing)
            return dispatch_api_view(existing)

        recipients = mailer_recipients_from_env()
        booking_rows = load_booking_rows_for_mailer(job_dir=job_dir, final_output_path=final_output_path)
        graph_result = await run_mailer_graph(
            job_id=job_id,
            mode="preview",
            preview_token="pending",
            final_output_checksum=checksum,
            recipients=recipients,
            booking_rows=booking_rows,
            transport=None,
        )
        drafts = list(graph_result.get("drafts") or [])
        token = build_preview_token(
            job_id=job_id,
            checksum=checksum,
            recipients=recipients,
            drafts=drafts,
        )
        payload = {
            "status": "preview_ready",
            "preview_token": token,
            "final_output_checksum": checksum,
            "recipients": recipients,
            "drafts": drafts,
            "results": [],
            "sent_at": None,
            "error": None,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "trace": list(graph_result.get("trace") or []),
        }
        save_dispatch(job_dir, payload)
        return dispatch_api_view(payload)


async def send_vendor_mails(
    *,
    job_id: str,
    job_dir: Path,
    final_output_path: Path,
    preview_token: str,
    transport: MailTransport | None = None,
) -> dict[str, Any]:
    with _job_lock(job_id):
        checksum = final_output_checksum(final_output_path)
        existing = load_dispatch(job_dir)
        if not existing or not existing.get("drafts"):
            raise ValueError("Mail preview must be generated before sending")
        if existing.get("final_output_checksum") != checksum:
            raise ValueError("Mail preview is stale because final_output.xlsx changed; refresh preview")
        if str(existing.get("preview_token") or "") != str(preview_token or "").strip():
            raise ValueError("preview_token does not match the frozen mail preview")

        status = str(existing.get("status") or "")
        if status == "sent":
            raise ValueError("Vendor mails were already sent for this job")
        if status == "sending":
            raise ValueError("Vendor mail send is already in progress")

        frozen = {
            "preview_token": str(existing.get("preview_token") or ""),
            "recipients": list(existing.get("recipients") or []),
            "drafts": list(existing.get("drafts") or []),
            "final_output_checksum": checksum,
            "created_at": existing.get("created_at"),
        }
        existing["status"] = "sending"
        existing["updated_at"] = _utc_now()
        existing["error"] = None
        save_dispatch(job_dir, existing)

    active_transport = transport or live_mail_transport_from_env()
    try:
        graph_result = await run_mailer_graph(
            job_id=job_id,
            mode="send",
            preview_token=frozen["preview_token"],
            final_output_checksum=checksum,
            recipients=frozen["recipients"],
            booking_rows=[],
            drafts=frozen["drafts"],
            transport=active_transport,
        )
    except Exception as error:
        with _job_lock(job_id):
            failed_payload = load_dispatch(job_dir) or {}
            failed_payload.update(frozen)
            failed_payload["status"] = "failed"
            failed_payload["error"] = str(error)
            failed_payload["results"] = []
            failed_payload["updated_at"] = _utc_now()
            save_dispatch(job_dir, failed_payload)
        if isinstance(error, SmtpError):
            raise
        raise SmtpError(str(error)) from error

    results = list(graph_result.get("results") or [])
    failed = sum(1 for item in results if item.get("status") == "failed")
    if failed == 0:
        next_status = "sent"
    elif failed == len(results):
        next_status = "failed"
    else:
        next_status = "partial"

    with _job_lock(job_id):
        payload = load_dispatch(job_dir) or {}
        payload.update(frozen)
        payload["status"] = next_status
        payload["results"] = results
        payload["sent_at"] = _utc_now() if next_status in {"sent", "partial"} else None
        payload["error"] = None if next_status == "sent" else "One or more recipient deliveries failed"
        payload["updated_at"] = _utc_now()
        payload["trace"] = list(graph_result.get("trace") or [])
        save_dispatch(job_dir, payload)
        return dispatch_api_view(payload)


def get_vendor_mail_status(*, job_dir: Path) -> dict[str, Any]:
    return dispatch_api_view(load_dispatch(job_dir))
