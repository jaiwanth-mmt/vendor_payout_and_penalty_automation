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
PACKAGE_FILENAME = "penalty_automation_package.zip"
FINAL_OUTPUT_FILENAME = "final_output.xlsx"
FINAL_EXPORT_COLUMNS = [
    "complaint_reasons",
    "complaint_against",
    "complaint_against_id",
    "title",
    "message",
    "fine",
]
FINAL_EXPORT_COLUMN_MAP = [
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
    preview_limit: int,
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
        "preview_rows": dataframe_preview(processed_df, limit=preview_limit),
        "status": "failed" if failed else "completed",
        "error": error,
    }


def build_manifest(
    *,
    approval_date: str,
    raw_rows: int,
    prepared_rows: int,
    categories: list[dict[str, Any]],
    final_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "approval_date": approval_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_rows": raw_rows,
        "prepared_rows": prepared_rows,
        "category_count": len(categories),
        "final_output": final_output,
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
) -> None:
    output_package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, manifest_path.relative_to(root_dir).as_posix())
        archive.write(final_output_path, final_output_path.relative_to(root_dir).as_posix())
        for category in categories:
            archive.write(root_dir / category["prepared_filename"], category["prepared_filename"])
            archive.write(root_dir / category["processed_filename"], category["processed_filename"])


def dataframe_preview(df: pd.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    preview_df = df.head(limit).copy()
    preview_df = preview_df.astype(object).where(pd.notna(preview_df), "")
    records = preview_df.to_dict(orient="records")
    return [{key: serialize_preview_value(value) for key, value in record.items()} for record in records]


def serialize_preview_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value
