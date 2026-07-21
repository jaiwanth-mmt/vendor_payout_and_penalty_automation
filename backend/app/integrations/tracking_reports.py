from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from backend.app.core.paths import REPO_ROOT
from backend.app.integrations.redash_call_comments import (
    DEFAULT_REDASH_BATCH_SIZE,
    DEFAULT_REDASH_HOST,
    DEFAULT_REDASH_SOURCE_IDS,
    fetch_call_comments_for_booking_ids,
    parse_source_ids,
)


DEFAULT_DB_HOST = "10.212.92.159"
DEFAULT_DB_PORT = 3307
DEFAULT_DB_USER = "incabs_blocks_and_confirms_stg"
DEFAULT_DB_NAME = "incabs_blocks_and_confirms"
DEFAULT_TABLE_NAME = "tracking_reports_raw"
DEFAULT_SUPPLIERS_TABLE_NAME = "incabs_suppliers"
ORDER_REFERENCE_COLUMN = "order_reference_number"
SUPPLIER_ID_COLUMN = "supplier_id"
ORIGINAL_SUPPLIER_ID_COLUMN = "original_supplier_id"
DETACHED_SUPPLIER_ID_COLUMN = "detached_supplier_id"
SUPPLIER_LOOKUP_COLUMNS = (
    SUPPLIER_ID_COLUMN,
    ORIGINAL_SUPPLIER_ID_COLUMN,
    DETACHED_SUPPLIER_ID_COLUMN,
)
SUPPLIER_OID_COLUMN = "oid"
SUPPLIER_VENDOR_NAME_SOURCE_COLUMN = "on_final"
VENDOR_NAME_COLUMN = "vendor_name"

CURATED_TRACKING_COLUMNS = [
    "dispatch_id",
    ORDER_REFERENCE_COLUMN,
    "ref_number",
    "booking_status",
    "tracking_status",
    "complaints_count",
    "is_cancelled",
    "cancelled_by_name",
    "cancelled_at",
    "cancellation_reason",
    "cancellation_string",
    "is_unfulfilled",
    "unfulfilled_reason",
    "unfulfilled_timestamp",
    "not_boarded_timestamp",
    "not_boarded_refund",
    "terminal_status",
    "terminal_status_reason",
    "type",
    "trip_type",
    "ttrip_type",
    "sub_trip_type",
    "booking_tags",
    "flags",
    "vehicle_subcategory",
    "vehicle_type",
    "vehicle_sku_id",
    "supplier_id",
    "original_supplier_id",
    "supplier_reference_number",
    "detached",
    "detached_supplier_id",
    "driver_assignment_count",
    "action_by",
    "createdAt",
    "start_time",
    "end_time",
    "travel_date",
    "modifiedAt",
    "updatedAt_orig",
    "supplier_assigned",
    "first_driver_assigned",
    "last_driver_assigned",
    "driver_assigned",
    "driver_reassigned",
    "driver_started",
    "driver_arrived",
    "boarded",
    "trip_alight",
    "system_alight",
    "driver_consent_datetime",
    "source_name",
    "source_point",
    "source_city_name",
    "source_state",
    "destination_name",
    "destination_point",
    "destination_city_name",
    "destination_state",
    "amount",
    "base_amount",
    "amount_paid",
    "cash_collected",
    "per_km_rate",
    "total_distance",
    "total_distance_travelled",
    "extra_travelled",
    "extra_travelled_fare",
    "extra_time",
    "extra_time_fare",
    "route_toll_charges",
    "toll_charges",
    "toll_paid",
    "parking_charges",
    "state_tax",
    "airport_entry_fee",
    "night_charges",
    "waiting_charges",
    "miscellaneous_charges",
    "driver_charge_per_day",
    "total_driver_charge",
    "started_latlon",
    "arrived_latlon",
    "boarded_latlon",
    "alight_latlon",
    "tracking_percentage",
    "distance_missed",
    "latlon_count",
    "flight_number",
    "flight_departure_time",
    "flight_arrival_time",
    "flight_date",
    "is_flight_early",
    "is_flight_delay",
]

ALWAYS_KEEP_COLUMNS = {"dispatch_id", ORDER_REFERENCE_COLUMN, "ref_number"}
DEFAULT_NOISE_VALUES = {"0", "0.0", "false", "none", "nan", "nat"}


def format_source_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)



def read_penalty_bookings(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [str(column).strip() for column in df.columns]

    required_columns = {"Booking ID", "Sub Category", "Remarks"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise KeyError(f"Missing required columns in {path}: {sorted(missing_columns)}")

    output = df.loc[:, ["Booking ID", "Sub Category", "Remarks"]].copy()
    output["Booking ID"] = output["Booking ID"].astype("string").str.strip()
    output = output.loc[output["Booking ID"].notna() & output["Booking ID"].ne("")].drop_duplicates("Booking ID")
    return output



@dataclass(frozen=True)
class MysqlConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    table_name: str = DEFAULT_TABLE_NAME
    suppliers_table_name: str = DEFAULT_SUPPLIERS_TABLE_NAME
    batch_size: int = 100


def connect_to_mysql_from_config(config: MysqlConfig) -> Connection:
    if not config.password:
        raise ValueError("MYSQL_PASSWORD is required. Set it in the environment or pass --password.")

    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=15,
        read_timeout=120,
        write_timeout=120,
    )


def normalize_identifier(value: str) -> str:
    return re.sub(r"[\s_]+", "", value.casefold())


def resolve_table_name(connection: Connection, database: str, requested_table_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            """,
            (database,),
        )
        table_names = [row["TABLE_NAME"] for row in cursor.fetchall()]

    if requested_table_name in table_names:
        return requested_table_name

    requested_normalized = normalize_identifier(requested_table_name)
    for table_name in table_names:
        if normalize_identifier(table_name) == requested_normalized:
            return table_name

    raise LookupError(f"Could not find table {requested_table_name!r} in database {database!r}.")


def fetch_table_columns(connection: Connection, database: str, table_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (database, table_name),
        )
        return [row["COLUMN_NAME"] for row in cursor.fetchall()]


def choose_relevant_columns(columns: list[str], _penalty_df: pd.DataFrame, max_columns: int) -> list[str]:
    available_columns_by_name = {column_name.casefold(): column_name for column_name in columns}
    selected = [
        available_columns_by_name[column_name.casefold()]
        for column_name in CURATED_TRACKING_COLUMNS
        if column_name.casefold() in available_columns_by_name
    ]

    if ORDER_REFERENCE_COLUMN.casefold() not in available_columns_by_name:
        raise KeyError(f"Table does not contain required column {ORDER_REFERENCE_COLUMN!r}.")

    if max_columns > 0:
        selected = selected[:max_columns]
    return selected


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_tracking_rows(
    connection: Connection,
    database: str,
    table_name: str,
    columns: list[str],
    booking_ids: list[str],
    batch_size: int,
) -> list[dict[str, Any]]:
    qualified_table_name = f"{quote_identifier(database)}.{quote_identifier(table_name)}"
    selected_columns = ", ".join(quote_identifier(column) for column in columns)
    all_rows: list[dict[str, Any]] = []

    with connection.cursor() as cursor:
        for booking_id_batch in chunked(booking_ids, batch_size):
            placeholders = ", ".join(["%s"] * len(booking_id_batch))
            sql = (
                f"SELECT {selected_columns} "
                f"FROM {qualified_table_name} "
                f"WHERE {quote_identifier(ORDER_REFERENCE_COLUMN)} IN ({placeholders})"
            )
            cursor.execute(sql, booking_id_batch)
            all_rows.extend(cursor.fetchall())

    return all_rows


def normalize_lookup_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError:
            return value.hex()
    return str(value).strip()


def collect_supplier_ids(tracking_rows: list[dict[str, Any]]) -> list[str]:
    supplier_ids = {
        normalize_lookup_value(row.get(column))
        for row in tracking_rows
        for column in SUPPLIER_LOOKUP_COLUMNS
    }
    return sorted(supplier_id for supplier_id in supplier_ids if supplier_id)


def fetch_supplier_vendor_names(
    connection: Connection,
    database: str,
    suppliers_table_name: str,
    supplier_ids: list[str],
    batch_size: int,
) -> tuple[dict[str, str], str]:
    resolved_suppliers_table_name = resolve_table_name(connection, database, suppliers_table_name)
    if not supplier_ids:
        return {}, resolved_suppliers_table_name

    available_columns = fetch_table_columns(connection, database, resolved_suppliers_table_name)
    available_columns_by_name = {
        column_name.casefold(): column_name
        for column_name in available_columns
    }
    required_columns = [SUPPLIER_OID_COLUMN, SUPPLIER_VENDOR_NAME_SOURCE_COLUMN]
    missing_columns = [
        column_name
        for column_name in required_columns
        if column_name.casefold() not in available_columns_by_name
    ]
    if missing_columns:
        raise KeyError(
            f"Supplier table {resolved_suppliers_table_name!r} is missing required columns: {missing_columns}"
        )

    oid_column = available_columns_by_name[SUPPLIER_OID_COLUMN.casefold()]
    vendor_name_column = available_columns_by_name[SUPPLIER_VENDOR_NAME_SOURCE_COLUMN.casefold()]
    qualified_table_name = (
        f"{quote_identifier(database)}.{quote_identifier(resolved_suppliers_table_name)}"
    )
    vendor_names_by_supplier_id: dict[str, str] = {}

    with connection.cursor() as cursor:
        for supplier_id_batch in chunked(supplier_ids, batch_size):
            placeholders = ", ".join(["%s"] * len(supplier_id_batch))
            sql = (
                f"SELECT {quote_identifier(oid_column)} AS supplier_oid, "
                f"{quote_identifier(vendor_name_column)} AS supplier_vendor_name "
                f"FROM {qualified_table_name} "
                f"WHERE {quote_identifier(oid_column)} IN ({placeholders})"
            )
            cursor.execute(sql, supplier_id_batch)
            for row in cursor.fetchall():
                supplier_id = normalize_lookup_value(row.get("supplier_oid"))
                vendor_name = normalize_lookup_value(row.get("supplier_vendor_name"))
                if supplier_id and vendor_name:
                    vendor_names_by_supplier_id[supplier_id] = vendor_name

    return vendor_names_by_supplier_id, resolved_suppliers_table_name


def supplier_lookup_id_for_tracking_row(row: dict[str, Any]) -> str:
    for column in SUPPLIER_LOOKUP_COLUMNS:
        supplier_id = normalize_lookup_value(row.get(column))
        if supplier_id:
            return supplier_id
    return ""


def add_vendor_names_to_tracking_rows(
    tracking_rows: list[dict[str, Any]],
    vendor_names_by_supplier_id: dict[str, str],
) -> int:
    matched_row_count = 0
    for row in tracking_rows:
        supplier_id = supplier_lookup_id_for_tracking_row(row)
        vendor_name = vendor_names_by_supplier_id.get(supplier_id)
        if vendor_name:
            row[VENDOR_NAME_COLUMN] = vendor_name
            matched_row_count += 1
    return matched_row_count


def add_column_once(columns: list[str], column: str) -> list[str]:
    if column.casefold() in {existing_column.casefold() for existing_column in columns}:
        return columns
    return [*columns, column]


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def normalize_value_for_pruning(value: Any) -> str:
    if is_empty_value(value):
        return ""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return str(int(value))
        return str(float(value))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().casefold()


def prune_unhelpful_columns(
    rows: list[dict[str, Any]],
    selected_columns: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    kept_columns: list[str] = []
    dropped_columns: list[str] = []

    for column in selected_columns:
        values = [row.get(column) for row in rows]
        normalized_values = {
            normalize_value_for_pruning(value)
            for value in values
            if not is_empty_value(value)
        }

        if column not in ALWAYS_KEEP_COLUMNS and not normalized_values:
            dropped_columns.append(column)
            continue

        if column not in ALWAYS_KEEP_COLUMNS and normalized_values and normalized_values.issubset(DEFAULT_NOISE_VALUES):
            dropped_columns.append(column)
            continue

        kept_columns.append(column)

    pruned_rows = [
        {column: row.get(column) for column in kept_columns}
        for row in rows
    ]
    return pruned_rows, kept_columns, dropped_columns


def to_json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def compact_json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: to_json_safe(value)
        for key, value in row.items()
        if not is_empty_value(value)
    }


def build_booking_wise_output(
    penalty_df: pd.DataFrame,
    tracking_rows: list[dict[str, Any]],
    selected_columns: list[str],
    dropped_columns: list[str],
    table_name: str,
    source_workbook: Path,
    comments_by_booking: dict[str, str] | None = None,
    redash_comments_metadata: dict[str, Any] | None = None,
    vendor_name_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comments_by_booking = comments_by_booking or {}
    rows_by_booking_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tracking_rows:
        booking_id = str(row.get(ORDER_REFERENCE_COLUMN, "")).strip()
        if not booking_id:
            continue

        rows_by_booking_id[booking_id].append(compact_json_row(row))

    bookings: dict[str, Any] = {}
    for record in penalty_df.to_dict(orient="records"):
        booking_id = str(record["Booking ID"]).strip()
        booking = {
            "penalty": {
                "sub_category": record.get("Sub Category"),
                "remarks": record.get("Remarks"),
            }
        }
        comment = comments_by_booking.get(booking_id, "").strip()
        if comment:
            booking["comments"] = comment
        booking["tracking_reports_raw"] = rows_by_booking_id.get(booking_id, [])
        bookings[booking_id] = booking

    metadata = {
        "source_workbook": format_source_path(source_workbook),
        "table_name": table_name,
        "booking_count": len(bookings),
        "selected_column_count": len(selected_columns),
        "selected_columns": selected_columns,
        "dropped_empty_or_default_columns": dropped_columns,
        "matched_tracking_row_count": len(tracking_rows),
        "commented_booking_count": len(comments_by_booking),
    }
    if redash_comments_metadata is not None:
        metadata["redash_comments"] = redash_comments_metadata
    if vendor_name_metadata is not None:
        metadata["vendor_name"] = vendor_name_metadata

    return {
        "metadata": metadata,
        "bookings": bookings,
    }


