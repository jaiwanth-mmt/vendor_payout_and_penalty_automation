from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from backend.app.core.tracking_utils import first_tracking_row, read_tracking_data
from backend.app.integrations.redash_call_comments import (
    DEFAULT_REDASH_BATCH_SIZE,
    DEFAULT_REDASH_HOST,
    DEFAULT_REDASH_SOURCE_IDS,
    fetch_call_comments_for_booking_ids,
    parse_source_ids,
)
from backend.app.integrations.tracking_reports import (
    DEFAULT_DB_HOST,
    DEFAULT_DB_NAME,
    DEFAULT_DB_PORT,
    DEFAULT_DB_USER,
    DEFAULT_SUPPLIERS_TABLE_NAME,
    DEFAULT_TABLE_NAME,
    MysqlConfig,
    SUPPLIER_LOOKUP_COLUMNS,
    SUPPLIER_OID_COLUMN,
    SUPPLIER_VENDOR_NAME_SOURCE_COLUMN,
    VENDOR_NAME_COLUMN,
    add_column_once,
    add_vendor_names_to_tracking_rows,
    build_booking_wise_output,
    choose_relevant_columns,
    collect_supplier_ids,
    connect_to_mysql_from_config,
    fetch_supplier_vendor_names,
    fetch_table_columns,
    fetch_tracking_rows,
    prune_unhelpful_columns,
    resolve_table_name,
)


@dataclass(frozen=True)
class RedashConfig:
    api_key: str
    host: str = DEFAULT_REDASH_HOST
    source_ids: tuple[int, ...] = DEFAULT_REDASH_SOURCE_IDS
    batch_size: int = DEFAULT_REDASH_BATCH_SIZE


class TrackingRepository(Protocol):
    async def get_bookings(
        self,
        booking_ids: list[str],
        *,
        penalty_df: pd.DataFrame | None = None,
        source_label: str = "live",
    ) -> dict[str, Any]:
        """Return bookings keyed by Booking ID in the processor-consumed shape."""


class InMemoryTrackingRepository:
    """Test/demo repository backed by an in-memory bookings dict or reference JSON."""

    def __init__(self, bookings: dict[str, Any] | None = None, *, json_path: Path | None = None) -> None:
        if bookings is not None:
            self._bookings = bookings
        elif json_path is not None:
            self._bookings = read_tracking_data(json_path)
        else:
            self._bookings = {}

    async def get_bookings(
        self,
        booking_ids: list[str],
        *,
        penalty_df: pd.DataFrame | None = None,
        source_label: str = "live",
    ) -> dict[str, Any]:
        del penalty_df, source_label
        requested = {str(booking_id).strip() for booking_id in booking_ids if str(booking_id).strip()}
        return {
            booking_id: payload
            for booking_id, payload in self._bookings.items()
            if booking_id in requested
        }


class LiveTrackingRepository:
    """Fetch tracking rows, supplier vendor names, and Redash comments for booking IDs."""

    def __init__(
        self,
        mysql_config: MysqlConfig,
        redash_config: RedashConfig | None = None,
    ) -> None:
        self._mysql = mysql_config
        self._redash = redash_config

    async def get_bookings(
        self,
        booking_ids: list[str],
        *,
        penalty_df: pd.DataFrame | None = None,
        source_label: str = "live",
    ) -> dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(
            self._fetch_bookings_sync,
            booking_ids,
            penalty_df,
            source_label,
        )

    def _fetch_bookings_sync(
        self,
        booking_ids: list[str],
        penalty_df: pd.DataFrame | None,
        source_label: str,
    ) -> dict[str, Any]:
        unique_ids = [booking_id for booking_id in dict.fromkeys(str(value).strip() for value in booking_ids) if booking_id]
        if not unique_ids:
            return {}

        if penalty_df is None:
            penalty_df = pd.DataFrame(
                {
                    "Booking ID": unique_ids,
                    "Sub Category": [""] * len(unique_ids),
                    "Remarks": [""] * len(unique_ids),
                }
            )
        else:
            penalty_df = penalty_df.copy()
            for column in ("Booking ID", "Sub Category", "Remarks"):
                if column not in penalty_df.columns:
                    penalty_df[column] = ""

        with connect_to_mysql_from_config(self._mysql) as connection:
            table_name = resolve_table_name(connection, self._mysql.database, self._mysql.table_name)
            available_columns = fetch_table_columns(connection, self._mysql.database, table_name)
            selected_columns = choose_relevant_columns(available_columns, penalty_df, 0)
            tracking_rows = fetch_tracking_rows(
                connection=connection,
                database=self._mysql.database,
                table_name=table_name,
                columns=selected_columns,
                booking_ids=unique_ids,
                batch_size=self._mysql.batch_size,
            )
            supplier_ids = collect_supplier_ids(tracking_rows)
            vendor_names_by_supplier_id, suppliers_table_name = fetch_supplier_vendor_names(
                connection=connection,
                database=self._mysql.database,
                suppliers_table_name=self._mysql.suppliers_table_name,
                supplier_ids=supplier_ids,
                batch_size=self._mysql.batch_size,
            )
            vendor_name_matched_row_count = add_vendor_names_to_tracking_rows(
                tracking_rows=tracking_rows,
                vendor_names_by_supplier_id=vendor_names_by_supplier_id,
            )
            if vendor_name_matched_row_count:
                selected_columns = add_column_once(selected_columns, VENDOR_NAME_COLUMN)

        tracking_rows, selected_columns, dropped_columns = prune_unhelpful_columns(
            rows=tracking_rows,
            selected_columns=selected_columns,
        )

        comments_by_booking: dict[str, str] = {}
        redash_comments_metadata: dict[str, Any]
        if self._redash and self._redash.api_key:
            comment_result = fetch_call_comments_for_booking_ids(
                booking_ids=unique_ids,
                api_key=self._redash.api_key,
                source_ids=self._redash.source_ids,
                redash_host=self._redash.host,
                batch_size=self._redash.batch_size,
            )
            comments_by_booking = comment_result.comments_by_booking
            redash_comments_metadata = {
                "enabled": True,
                "redash_host": self._redash.host,
                "source_id": comment_result.source_id,
                "rows_fetched": len(comment_result.rows),
                "booking_count_with_comments": len(comments_by_booking),
            }
        else:
            redash_comments_metadata = {"enabled": False, "reason": "REDASH_API_KEY was not provided."}

        vendor_name_metadata = {
            "source_table": suppliers_table_name,
            "source_tracking_columns": list(SUPPLIER_LOOKUP_COLUMNS),
            "source_key_column": SUPPLIER_OID_COLUMN,
            "source_value_column": SUPPLIER_VENDOR_NAME_SOURCE_COLUMN,
            "output_column": VENDOR_NAME_COLUMN,
            "supplier_id_count": len(supplier_ids),
            "matched_supplier_count": len(vendor_names_by_supplier_id),
            "matched_tracking_row_count": vendor_name_matched_row_count,
        }

        payload = build_booking_wise_output(
            penalty_df=penalty_df.loc[:, ["Booking ID", "Sub Category", "Remarks"]],
            tracking_rows=tracking_rows,
            selected_columns=selected_columns,
            dropped_columns=dropped_columns,
            table_name=table_name,
            source_workbook=Path(source_label),
            comments_by_booking=comments_by_booking,
            redash_comments_metadata=redash_comments_metadata,
            vendor_name_metadata=vendor_name_metadata,
        )
        return payload.get("bookings", {})


def mysql_config_from_env() -> MysqlConfig:
    password = os.getenv("MYSQL_PASSWORD", "").strip()
    if not password:
        raise ValueError("MYSQL_PASSWORD is required for live tracking. Set it in the environment or .env.")

    return MysqlConfig(
        host=os.getenv("MYSQL_HOST", DEFAULT_DB_HOST).strip() or DEFAULT_DB_HOST,
        port=int(os.getenv("MYSQL_PORT", str(DEFAULT_DB_PORT)) or DEFAULT_DB_PORT),
        user=os.getenv("MYSQL_USER", DEFAULT_DB_USER).strip() or DEFAULT_DB_USER,
        password=password,
        database=os.getenv("MYSQL_DATABASE", DEFAULT_DB_NAME).strip() or DEFAULT_DB_NAME,
        table_name=os.getenv("MYSQL_TABLE_NAME", DEFAULT_TABLE_NAME).strip() or DEFAULT_TABLE_NAME,
        suppliers_table_name=(
            os.getenv("MYSQL_SUPPLIERS_TABLE_NAME", DEFAULT_SUPPLIERS_TABLE_NAME).strip()
            or DEFAULT_SUPPLIERS_TABLE_NAME
        ),
        batch_size=int(os.getenv("MYSQL_BATCH_SIZE", "100") or 100),
    )


def redash_config_from_env() -> RedashConfig | None:
    api_key = os.getenv("REDASH_API_KEY", "").strip()
    if not api_key:
        return None
    source_ids_raw = os.getenv("REDASH_SOURCE_IDS", "").strip()
    source_ids = parse_source_ids(source_ids_raw) if source_ids_raw else DEFAULT_REDASH_SOURCE_IDS
    return RedashConfig(
        api_key=api_key,
        host=os.getenv("REDASH_HOST", DEFAULT_REDASH_HOST).strip() or DEFAULT_REDASH_HOST,
        source_ids=source_ids,
        batch_size=int(os.getenv("REDASH_BATCH_SIZE", str(DEFAULT_REDASH_BATCH_SIZE)) or DEFAULT_REDASH_BATCH_SIZE),
    )


def live_tracking_repository_from_env() -> LiveTrackingRepository:
    return LiveTrackingRepository(
        mysql_config=mysql_config_from_env(),
        redash_config=redash_config_from_env(),
    )


def matched_booking_ids(tracking_bookings: dict[str, Any], booking_ids: list[str]) -> list[str]:
    return [
        booking_id
        for booking_id in booking_ids
        if booking_id and first_tracking_row(tracking_bookings, booking_id)
    ]
