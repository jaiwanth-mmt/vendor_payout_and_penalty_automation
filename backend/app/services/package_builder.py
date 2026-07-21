from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.domain.complaint_message import MESSAGE_COLUMN


PREPARED_CATEGORY_ROOT = Path("category_files") / "prepared"
PROCESSED_CATEGORY_ROOT = Path("category_files") / "processed"
MANIFEST_FILENAME = "manifest.json"
PACKAGE_FILENAME = "agentic_loss_recovery_package.zip"
FINAL_OUTPUT_FILENAME = "final_output.xlsx"
AGENT_AUDIT_FILENAME = "agent_audit.xlsx"
REVIEW_QUEUE_FILENAME = "review_queue.xlsx"
AGENT_SUMMARY_FILENAME = "agent_summary.json"
AGENT_AUDIT_COLUMNS = [
    "booking_id",
    "sub_category",
    "message",
    "recoverable_amount",
    "review_status",
    "decision",
    "decision_source",
    "llm_error",
    "complaint_categories",
    "confidence",
    "recommended_recovery_amount",
    "recommended_action",
    "review_reason",
    "rationale",
    "source_used",
    "source_categories",
    "row_categories",
    "source_alignment_status",
    "source_alignment_reason",
    "mentioned_booking_ids",
    "specialist_agent",
    "specialist_decision_source",
    "specialist_llm_error",
    "specialist_confidence",
    "judge_decision_source",
    "judge_llm_error",
    "judge_confidence",
    "evidence_ids",
    "evidence_count",
    "trace_count",
]
REVIEW_QUEUE_COLUMNS = [
    "booking_id",
    "sub_category",
    "message",
    "recoverable_amount",
    "review_status",
    "decision",
    "decision_source",
    "llm_error",
    "confidence",
    "recommended_action",
    "review_reason",
    "rationale",
    "source_used",
    "source_categories",
    "row_categories",
    "source_alignment_status",
    "source_alignment_reason",
    "evidence_ids",
]
FINAL_EXPORT_COLUMNS = [
    "booking_id",
    "complaint_reasons",
    "complaint_against",
    "complaint_against_id",
    "title",
    "message",
    "fine",
]
FINAL_EXPORT_COLUMN_MAP = [
    ("Booking ID", "booking_id"),
    ("Sub Category", "complaint_reasons"),
    ("complaint_against", "complaint_against"),
    ("complaint_against_id", "complaint_against_id"),
    ("title", "title"),
    (MESSAGE_COLUMN, "message"),
    ("Recoverable", "fine"),
]


def write_workbook(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)


def build_final_output_dataframe(processed_frames: list[pd.DataFrame]) -> pd.DataFrame:
    final_frames: list[pd.DataFrame] = []
    for frame in processed_frames:
        output = pd.DataFrame(index=frame.index)
        for source_column, target_column in FINAL_EXPORT_COLUMN_MAP:
            if source_column in frame.columns:
                output[target_column] = frame[source_column]
            else:
                output[target_column] = pd.Series([""] * len(frame), index=frame.index, dtype=object)
        final_frames.append(output.loc[:, FINAL_EXPORT_COLUMNS].copy())

    if not final_frames:
        return pd.DataFrame(columns=FINAL_EXPORT_COLUMNS)
    return pd.concat(final_frames, ignore_index=True).loc[:, FINAL_EXPORT_COLUMNS]


def build_final_output_summary(
    *,
    final_output_path: Path,
    final_output_df: pd.DataFrame,
    root_dir: Path,
) -> dict[str, Any]:
    return {
        "filename": final_output_path.relative_to(root_dir).as_posix(),
        "row_count": len(final_output_df),
        "columns": FINAL_EXPORT_COLUMNS,
        "download_ready": final_output_path.exists(),
    }


def build_category_output_payload(
    *,
    name: str,
    slug: str,
    prepared_path: Path,
    processed_path: Path,
    processed_df: pd.DataFrame,
    root_dir: Path,
    failed: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "slug": slug,
        "row_count": len(processed_df),
        "output_columns": processed_df.columns.tolist(),
        "prepared_filename": prepared_path.relative_to(root_dir).as_posix(),
        "processed_filename": processed_path.relative_to(root_dir).as_posix(),
        "status": "failed" if failed else "completed",
        "error": error,
    }


def build_manifest(
    *,
    start_date: str,
    end_date: str,
    raw_rows: int,
    prepared_rows: int,
    categories: list[dict[str, Any]],
    final_output: dict[str, Any],
    agent_summary: dict[str, Any] | None = None,
    agent_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_rows": raw_rows,
        "prepared_rows": prepared_rows,
        "category_count": len(categories),
        "final_output": final_output,
        "agent_summary": agent_summary or {},
        "agent_artifacts": agent_artifacts or {},
        "categories": [
            {
                "name": category["name"],
                "slug": category["slug"],
                "row_count": category["row_count"],
                "output_columns": category["output_columns"],
                "prepared_filename": category["prepared_filename"],
                "processed_filename": category["processed_filename"],
                "status": category.get("status", "completed"),
                "error": category.get("error"),
            }
            for category in categories
        ],
    }


def write_package_zip(
    *,
    output_package_path: Path,
    manifest_path: Path,
    categories: list[dict[str, Any]],
    final_output_path: Path,
    root_dir: Path,
    agent_artifact_paths: list[Path] | None = None,
) -> None:
    output_package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, manifest_path.relative_to(root_dir).as_posix())
        archive.write(final_output_path, final_output_path.relative_to(root_dir).as_posix())
        for artifact_path in agent_artifact_paths or []:
            if artifact_path.exists():
                archive.write(artifact_path, artifact_path.relative_to(root_dir).as_posix())
        for category in categories:
            archive.write(root_dir / category["prepared_filename"], category["prepared_filename"])
            archive.write(root_dir / category["processed_filename"], category["processed_filename"])


def build_agent_audit_dataframe(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case in cases:
        decision = case.get("final_decision") or {}
        specialist = case.get("specialist_decision") or {}
        judge = case.get("judge_decision") or {}
        source_analysis = case.get("source_analysis") or {}
        rows.append(
            {
                "booking_id": case.get("booking_id", ""),
                "sub_category": case.get("sub_category", ""),
                "message": case.get("message", ""),
                "recoverable_amount": case.get("recoverable_amount", 0),
                "review_status": case.get("review_status", ""),
                "decision": decision.get("decision", ""),
                "decision_source": decision.get("decision_source", ""),
                "llm_error": decision.get("llm_error", ""),
                "complaint_categories": " + ".join(decision.get("complaint_categories", [])),
                "confidence": decision.get("confidence", 0),
                "recommended_recovery_amount": decision.get("recommended_recovery_amount", 0),
                "recommended_action": decision.get("recommended_action", ""),
                "review_reason": decision.get("review_reason", ""),
                "rationale": decision.get("rationale", ""),
                "source_used": source_analysis.get("source_label", ""),
                "source_categories": join_values(source_analysis.get("source_categories", [])),
                "row_categories": join_values(source_analysis.get("row_categories", [])),
                "source_alignment_status": source_analysis.get("status", ""),
                "source_alignment_reason": source_analysis.get("reason", ""),
                "mentioned_booking_ids": join_values(source_analysis.get("mentioned_booking_ids", [])),
                "specialist_agent": specialist.get("agent", ""),
                "specialist_decision_source": specialist.get("decision_source", ""),
                "specialist_llm_error": specialist.get("llm_error", ""),
                "specialist_confidence": specialist.get("confidence", 0),
                "judge_decision_source": judge.get("decision_source", ""),
                "judge_llm_error": judge.get("llm_error", ""),
                "judge_confidence": judge.get("confidence", 0),
                "evidence_ids": ", ".join(decision.get("evidence_ids", [])),
                "evidence_count": len(case.get("evidence", [])),
                "trace_count": len(case.get("trace", [])),
            }
        )
    return pd.DataFrame(rows, columns=AGENT_AUDIT_COLUMNS)


def build_review_queue_dataframe(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.get("review_status") == "auto_ready":
            continue

        decision = case.get("final_decision") or {}
        source_analysis = case.get("source_analysis") or {}
        rows.append(
            {
                "booking_id": case.get("booking_id", ""),
                "sub_category": case.get("sub_category", ""),
                "message": case.get("message", ""),
                "recoverable_amount": case.get("recoverable_amount", 0),
                "review_status": case.get("review_status", ""),
                "decision": decision.get("decision", ""),
                "decision_source": decision.get("decision_source", ""),
                "llm_error": decision.get("llm_error", ""),
                "confidence": decision.get("confidence", 0),
                "recommended_action": decision.get("recommended_action", ""),
                "review_reason": decision.get("review_reason", ""),
                "rationale": decision.get("rationale", ""),
                "source_used": source_analysis.get("source_label", ""),
                "source_categories": join_values(source_analysis.get("source_categories", [])),
                "row_categories": join_values(source_analysis.get("row_categories", [])),
                "source_alignment_status": source_analysis.get("status", ""),
                "source_alignment_reason": source_analysis.get("reason", ""),
                "evidence_ids": ", ".join(decision.get("evidence_ids", [])),
            }
        )
    return pd.DataFrame(rows, columns=REVIEW_QUEUE_COLUMNS)


def join_values(value: Any) -> str:
    if isinstance(value, list):
        return " + ".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value).strip()
