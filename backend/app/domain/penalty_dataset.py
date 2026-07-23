from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from backend.app.core.paths import DEMO_WORKBOOK_PATH, RUNTIME_ROOT
from backend.app.domain.complaint_message import normalize_category_key


DEFAULT_INPUT_PATH = DEMO_WORKBOOK_PATH
DEFAULT_OUTPUT_PATH = RUNTIME_ROOT / "manual" / "agentic_loss_recovery_output.xlsx"
DEFAULT_WORKING_FOLDER = RUNTIME_ROOT / "manual"
DEFAULT_DATE_COLUMN = "Approval/Rejected DateTime"
DEFAULT_REMARK_SEPARATOR = " / "
DEFAULT_DUPLICATE_OUTPUT_TEMPLATE = "duplicate_bookings_{date}.xlsx"
SUB_CATEGORY_PREFIX_PATTERN = r"(?i)^\s*(?:carbd|car)\s*-\s*"
AUTO_CLAIM_RAISED_REMARK_PATTERN = r"(?i)\s*-\s*auto\s*claim\s*raised\b"

FINAL_OUTPUT_COLUMNS = [
    "Booking ID",
    "Booking Date",
    "Booking Month",
    "Loss Dept",
    "Sub Category",
    "Loss Amount",
    "Recoverable",
    "Remarks",
]



def read_input_file(path: Path, sheet_name: str | int) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    df.columns = [str(column).strip() for column in df.columns]
    return df


def parse_approval_datetimes(series: pd.Series) -> pd.Series:
    """Parse Approval/Rejected DateTime cells into timestamps.

    Handles Excel datetime cells and QlikSense text like ``20/07/2026  4:29:37 PM``
    (day-first, collapsed whitespace). Time is kept on the timestamp; callers strip
    to calendar day via ``.dt.normalize()`` when filtering.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    text = (
        series.astype("string")
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    # DD/MM/YYYY exports (with optional time) — day-first to avoid US month/day swap.
    day_first_mask = text.str.match(r"^\d{1,2}/\d{1,2}/\d{4}", na=False)
    if day_first_mask.any():
        day_first_text = text.loc[day_first_mask]
        day_first_parsed = pd.Series(pd.NaT, index=day_first_text.index, dtype="datetime64[ns]")
        for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            still_missing = day_first_parsed.isna()
            if not still_missing.any():
                break
            day_first_parsed.loc[still_missing] = pd.to_datetime(
                day_first_text.loc[still_missing],
                format=fmt,
                errors="coerce",
            )
        still_missing = day_first_parsed.isna() & day_first_text.notna()
        if still_missing.any():
            day_first_parsed.loc[still_missing] = pd.to_datetime(
                day_first_text.loc[still_missing],
                errors="coerce",
                dayfirst=True,
            )
        parsed.loc[day_first_mask] = day_first_parsed
    # ISO / Excel-style and other remaining values.
    remaining = ~day_first_mask & text.notna()
    if remaining.any():
        parsed.loc[remaining] = pd.to_datetime(text.loc[remaining], errors="coerce")
    return parsed


def filter_by_input_date(df: pd.DataFrame, date_column: str, input_date: str) -> pd.DataFrame:
    """Filter rows to a single calendar day. Prefer filter_by_input_date_range for jobs."""
    return filter_by_input_date_range(df, date_column, input_date, input_date)


def filter_by_input_date_range(
    df: pd.DataFrame,
    date_column: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if date_column not in df.columns:
        raise KeyError(f"Column {date_column!r} not found in input file.")

    start = pd.to_datetime(start_date).normalize()
    end = pd.to_datetime(end_date).normalize()
    if start > end:
        raise ValueError(f"start_date {start_date!r} must be on or before end_date {end_date!r}.")

    output = df.copy()
    parsed = parse_approval_datetimes(output[date_column])
    day = parsed.dt.normalize()
    output = output.loc[day.ge(start) & day.le(end)].copy()
    return output


def keep_only_carbd_loss_dept(df: pd.DataFrame, loss_dept_column: str = "Loss Dept") -> pd.DataFrame:
    if loss_dept_column not in df.columns:
        raise KeyError(f"Column {loss_dept_column!r} not found in input file.")

    loss_dept = df[loss_dept_column].astype("string").str.strip().str.upper()
    return df.loc[loss_dept == "CARBD"].copy()


def normalize_numeric_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    output = df.copy()
    for column in columns:
        if column in output.columns:
            output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0)
    return output


def remove_zero_recoverable_rows(df: pd.DataFrame, recoverable_column: str = "Recoverable") -> pd.DataFrame:
    if recoverable_column not in df.columns:
        raise KeyError(f"Column {recoverable_column!r} not found in input file.")

    recoverable = pd.to_numeric(df[recoverable_column], errors="coerce").fillna(0)
    return df.loc[recoverable != 0].copy()


def _subcategory_exclusion_key(value: object) -> str:
    """Normalize Sub Category for exclusion matching (strip CARBD/CAR- prefix first)."""
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    cleaned = re.sub(SUB_CATEGORY_PREFIX_PATTERN, "", text).strip()
    return normalize_category_key(cleaned)


def is_excluded_subcategory(value: object) -> bool:
    """True for User cancellation or any Customer Delight variant (case-insensitive)."""
    key = _subcategory_exclusion_key(value)
    if not key:
        return False
    return key == "user cancellation" or "customer delight" in key


def drop_excluded_subcategories(
    df: pd.DataFrame,
    sub_category_column: str = "Sub Category",
) -> pd.DataFrame:
    """Drop Sub Categories that never receive vendor penalty (User cancellation / Customer Delight)."""
    if sub_category_column not in df.columns:
        raise KeyError(f"Column {sub_category_column!r} not found in input file.")

    keep_mask = ~df[sub_category_column].map(is_excluded_subcategory)
    return df.loc[keep_mask].copy()


def get_duplicate_entries(df: pd.DataFrame) -> pd.DataFrame:
    if "Booking ID" not in df.columns:
        raise KeyError("Column 'Booking ID' not found in input file.")
    return df.loc[df["Booking ID"].duplicated(keep=False)].copy()


def build_duplicate_output_path(input_date: str, output_path: Path) -> Path:
    safe_date = pd.to_datetime(input_date).strftime("%Y-%m-%d")
    file_name = DEFAULT_DUPLICATE_OUTPUT_TEMPLATE.format(date=safe_date)
    return DEFAULT_WORKING_FOLDER / file_name





def _safe_string(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _select_primary_row(group: pd.DataFrame) -> pd.Series:
    carbd_rows = group.loc[group["Loss Dept"].astype(str).str.upper() == "CARBD"]
    candidates = carbd_rows if not carbd_rows.empty else group
    return candidates.sort_values("Loss Amount", ascending=False).iloc[0].copy()


def _build_merged_remarks(group: pd.DataFrame) -> str:
    remarks = [_safe_string(value) for value in group["Remarks"].tolist()]
    remarks = [remark for remark in remarks if remark]
    return DEFAULT_REMARK_SEPARATOR.join(dict.fromkeys(remarks))


def consolidate_duplicate_bookings(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"Booking ID", "Loss Dept", "Loss Amount", "Remarks", "Recoverable"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise KeyError(f"Missing required columns for dedupe logic: {sorted(missing_columns)}")

    if "Loss Amount (INR)" not in df.columns:
        df["Loss Amount (INR)"] = df["Loss Amount"]
    if "Recoverable (INR)" not in df.columns:
        df["Recoverable (INR)"] = df["Recoverable"]

    grouped_rows: list[pd.Series] = []

    for _, group in df.groupby("Booking ID", dropna=False, sort=False):
        group = group.copy()
        group["Loss Dept"] = group["Loss Dept"].astype(str).str.upper().str.strip()
        primary_row = _select_primary_row(group)

        primary_row["Loss Amount"] = group["Loss Amount"].sum()
        primary_row["Loss Amount (INR)"] = group["Loss Amount (INR)"].sum()

        recoverable_mask = group["Loss Dept"].ne("CD")
        primary_row["Recoverable"] = group.loc[recoverable_mask, "Recoverable"].sum()
        primary_row["Recoverable (INR)"] = group.loc[recoverable_mask, "Recoverable (INR)"].sum()

        if group["Loss Dept"].eq("CARBD").all():
            primary_row["Remarks"] = _build_merged_remarks(group)

        primary_row["Merged Row Count"] = len(group)
        primary_row["Merged Loss Depts"] = DEFAULT_REMARK_SEPARATOR.join(dict.fromkeys(group["Loss Dept"].tolist()))
        grouped_rows.append(primary_row)

    output = pd.DataFrame(grouped_rows).reset_index(drop=True)
    return output


def shape_loss_recovery_output(df: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in FINAL_OUTPUT_COLUMNS if column not in df.columns]
    if missing_columns:
        raise KeyError(f"Missing required columns for final output: {missing_columns}")

    return df.loc[:, FINAL_OUTPUT_COLUMNS].copy()


def clean_output_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = {"Sub Category", "Remarks"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise KeyError(f"Missing required columns for text cleanup: {sorted(missing_columns)}")

    output = df.copy()
    output["Sub Category"] = (
        output["Sub Category"]
        .astype("string")
        .str.replace(SUB_CATEGORY_PREFIX_PATTERN, "", regex=True)
        .str.strip()
    )
    output["Remarks"] = (
        output["Remarks"]
        .astype("string")
        .str.replace(AUTO_CLAIM_RAISED_REMARK_PATTERN, "", regex=True)
        .str.strip()
    )
    return output


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_df = clean_output_text_columns(df)
    shaped_df = shape_loss_recovery_output(cleaned_df)
    shaped_df.to_excel(output_path, index=False)


