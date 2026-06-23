from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

from backend.app.core.paths import DEMO_WORKBOOK_PATH, RUNTIME_ROOT


DEFAULT_INPUT_PATH = DEMO_WORKBOOK_PATH
DEFAULT_OUTPUT_PATH = RUNTIME_ROOT / "manual" / "penalty_automation_output.xlsx"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the Qliksense dump, filter by date, consolidate duplicate Booking IDs, "
            "and save the final dataset."
        )
    )
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--input-date",
        default="2026-03-19",
        help="Date to filter on in YYYY-MM-DD format. The filter is applied on the date portion only.",
    )
    parser.add_argument(
        "--date-column",
        default=DEFAULT_DATE_COLUMN,
        help=f"Column used for date filtering. Defaults to {DEFAULT_DATE_COLUMN!r}.",
    )
    parser.add_argument(
        "--sheet-name",
        default=0,
        help="Excel sheet name or index to read. Defaults to the first sheet.",
    )
    return parser.parse_args()


def read_input_file(path: Path, sheet_name: str | int) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    df.columns = [str(column).strip() for column in df.columns]
    return df


def filter_by_input_date(df: pd.DataFrame, date_column: str, input_date: str) -> pd.DataFrame:
    if date_column not in df.columns:
        raise KeyError(f"Column {date_column!r} not found in input file.")

    filter_date = pd.to_datetime(input_date).normalize()
    output = df.copy()
    output[date_column] = pd.to_datetime(output[date_column], errors="coerce")
    output = output.loc[output[date_column].dt.normalize() == filter_date].copy()
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


def main() -> None:
    args = parse_args()

    raw_df = read_input_file(args.input_path, args.sheet_name)
    date_filtered_df = filter_by_input_date(raw_df, args.date_column, args.input_date)
    filtered_df = keep_only_carbd_loss_dept(date_filtered_df)
    filtered_df = normalize_numeric_columns(
        filtered_df,
        ["Loss Amount", "Loss Amount (INR)", "Recoverable", "Recoverable (INR)"],
    )
    recoverable_filtered_df = remove_zero_recoverable_rows(filtered_df)

    consolidated_df = consolidate_duplicate_bookings(recoverable_filtered_df)

    save_output(consolidated_df, args.output_path)

    print(f"Rows in raw input: {len(raw_df)}")
    print(f"Rows after date filter: {len(date_filtered_df)}")
    print(f"Rows after CARBD Loss Dept filter: {len(filtered_df)}")
    print(f"Rows after non-zero Recoverable filter: {len(recoverable_filtered_df)}")
    print(f"Rows after dedupe: {len(consolidated_df)}")
    print(f"Saved final output to: {args.output_path}")


if __name__ == "__main__":
    main()
