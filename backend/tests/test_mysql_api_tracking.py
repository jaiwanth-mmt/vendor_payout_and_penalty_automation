from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from backend.app.integrations.tracking import (
    DEFAULT_MYSQL_API_URL,
    LiveTrackingRepository,
    MysqlApiError,
    MysqlConfig,
    execute_mysql_api_query,
    mysql_config_from_env,
)
from backend.app.integrations.tracking_reports import (
    escape_sql_literal,
    fetch_supplier_vendor_names,
    fetch_table_columns,
    fetch_tracking_rows,
    resolve_table_name,
)


def test_escape_sql_literal() -> None:
    assert escape_sql_literal(None) == "NULL"
    assert escape_sql_literal(123) == "'123'"
    assert escape_sql_literal("normal") == "'normal'"
    assert escape_sql_literal("O'Reilly") == "'O''Reilly'"
    assert escape_sql_literal("slash\\and'quote") == "'slash\\\\and''quote'"


def test_execute_mysql_api_query_success() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": [{"id": 1, "value": "test"}],
    }

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    result = execute_mysql_api_query(
        api_url="http://fake-host/query",
        database="test_db",
        query="SELECT 1;",
        client=mock_client,
    )

    assert result == [{"id": 1, "value": "test"}]
    mock_client.post.assert_called_once_with(
        "http://fake-host/query",
        json={"dbname": "test_db", "query": "SELECT 1;"},
        headers={"Content-Type": "application/json"},
        timeout=60.0,
    )


def test_execute_mysql_api_query_failure_raises_error() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": False,
        "message": "Syntax error in SQL",
        "error": "ER_PARSE_ERROR",
    }

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    with pytest.raises(MysqlApiError, match="Syntax error in SQL"):
        execute_mysql_api_query(
            api_url="http://fake-host/query",
            database="test_db",
            query="BAD SQL;",
            client=mock_client,
        )


def test_execute_mysql_api_query_http_error_retries_and_raises() -> None:
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")

    with patch("backend.app.integrations.tracking_reports.time_module.sleep"):  # don't actually wait in tests
        with pytest.raises(MysqlApiError, match="Failed to execute MySQL API query after 3 attempts"):
            execute_mysql_api_query(
                api_url="http://fake-host/query",
                database="test_db",
                query="SELECT 1;",
                client=mock_client,
                max_retries=3,
            )

    assert mock_client.post.call_count == 3


def test_resolve_table_name_via_api() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": [{"TABLE_NAME": "tracking_reports_raw"}, {"TABLE_NAME": "incabs_suppliers"}],
    }
    mock_client.post.return_value = mock_response

    table = resolve_table_name(
        target="http://fake-host/query",
        database="test_db",
        requested_table_name="TRACKING_REPORTS_RAW",
        client=mock_client,
    )
    assert table == "tracking_reports_raw"


def test_fetch_table_columns_via_api() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": [
            {"COLUMN_NAME": "order_reference_number"},
            {"COLUMN_NAME": "supplier_id"},
            {"COLUMN_NAME": "amount"},
        ],
    }
    mock_client.post.return_value = mock_response

    cols = fetch_table_columns(
        target="http://fake-host/query",
        database="test_db",
        table_name="tracking_reports_raw",
        client=mock_client,
    )
    assert cols == ["order_reference_number", "supplier_id", "amount"]


def test_fetch_tracking_rows_via_api() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": [
            {"order_reference_number": "B1", "amount": 100, "supplier_id": "S1"},
            {"order_reference_number": "B2", "amount": 200, "supplier_id": "S2"},
        ],
    }
    mock_client.post.return_value = mock_response

    rows = fetch_tracking_rows(
        target="http://fake-host/query",
        database="test_db",
        table_name="tracking_reports_raw",
        columns=["order_reference_number", "amount", "supplier_id"],
        booking_ids=["B1", "B2"],
        batch_size=10,
        client=mock_client,
    )
    assert len(rows) == 2
    assert rows[0]["order_reference_number"] == "B1"
    assert rows[1]["order_reference_number"] == "B2"


def test_fetch_supplier_vendor_names_via_api() -> None:
    mock_client = MagicMock()

    # Call 1: resolve table name
    resp_tables = MagicMock(status_code=200)
    resp_tables.json.return_value = {"success": True, "data": [{"TABLE_NAME": "incabs_suppliers"}]}

    # Call 2: fetch columns
    resp_cols = MagicMock(status_code=200)
    resp_cols.json.return_value = {
        "success": True,
        "data": [{"COLUMN_NAME": "oid"}, {"COLUMN_NAME": "on_final"}],
    }

    # Call 3: fetch supplier rows
    resp_suppliers = MagicMock(status_code=200)
    resp_suppliers.json.return_value = {
        "success": True,
        "data": [
            {"supplier_oid": "S1", "supplier_vendor_name": "Vendor Alpha"},
            {"supplier_oid": "S2", "supplier_vendor_name": "Vendor Beta"},
        ],
    }

    mock_client.post.side_effect = [resp_tables, resp_cols, resp_suppliers]

    vendors, resolved = fetch_supplier_vendor_names(
        target="http://fake-host/query",
        database="test_db",
        suppliers_table_name="incabs_suppliers",
        supplier_ids=["S1", "S2"],
        batch_size=10,
        client=mock_client,
    )

    assert resolved == "incabs_suppliers"
    assert vendors == {"S1": "Vendor Alpha", "S2": "Vendor Beta"}


def test_mysql_config_from_env_defaults() -> None:
    with patch.dict("os.environ", {}, clear=True):
        config = mysql_config_from_env()
        assert config.api_url == DEFAULT_MYSQL_API_URL
        assert config.database == "incabs_blocks_and_confirms"
        assert config.table_name == "tracking_reports_raw"
        assert config.suppliers_table_name == "incabs_suppliers"
        assert config.batch_size == 100
        assert config.timeout_seconds == 60.0


def test_live_tracking_repository_end_to_end_mocked() -> None:
    # Set up mock responses for repository._fetch_bookings_sync
    # 1. resolve table tracking_reports_raw
    resp_tables = {"success": True, "data": [{"TABLE_NAME": "tracking_reports_raw"}]}
    # 2. columns for tracking_reports_raw
    resp_cols = {
        "success": True,
        "data": [
            {"COLUMN_NAME": "order_reference_number"},
            {"COLUMN_NAME": "dispatch_id"},
            {"COLUMN_NAME": "amount"},
            {"COLUMN_NAME": "ttrip_type"},
            {"COLUMN_NAME": "supplier_id"},
            {"COLUMN_NAME": "booking_status"},
            {"COLUMN_NAME": "tracking_status"},
        ],
    }
    # 3. tracking rows
    resp_tracking = {
        "success": True,
        "data": [
            {
                "order_reference_number": "B100",
                "dispatch_id": "D100",
                "amount": 1500,
                "ttrip_type": "airport",
                "supplier_id": "SUPP_1",
                "booking_status": "CONFIRMED",
                "tracking_status": "ARRIVED",
            }
        ],
    }
    # 4. resolve table incabs_suppliers
    resp_supp_tables = {"success": True, "data": [{"TABLE_NAME": "incabs_suppliers"}]}
    # 5. columns for incabs_suppliers
    resp_supp_cols = {
        "success": True,
        "data": [{"COLUMN_NAME": "oid"}, {"COLUMN_NAME": "on_final"}],
    }
    # 6. supplier lookup
    resp_supp_lookup = {
        "success": True,
        "data": [{"supplier_oid": "SUPP_1", "supplier_vendor_name": "Mega Cabs"}],
    }

    mock_responses = [
        resp_tables,
        resp_cols,
        resp_tracking,
        resp_supp_tables,
        resp_supp_cols,
        resp_supp_lookup,
    ]

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda r=r: r, raise_for_status=lambda: None)
            for r in mock_responses
        ]

        config = MysqlConfig(api_url="http://fake-host/query", database="test_db")
        repo = LiveTrackingRepository(mysql_config=config, redash_config=None)

        penalty_df = pd.DataFrame(
            [{"Booking ID": "B100", "Sub Category": "Cab Delay", "Remarks": "Delayed"}]
        )
        bookings = repo._fetch_bookings_sync(
            booking_ids=["B100"],
            penalty_df=penalty_df,
            source_label="test.xlsx",
        )

        assert "B100" in bookings
        booking_data = bookings["B100"]
        assert booking_data["penalty"]["sub_category"] == "Cab Delay"
        assert len(booking_data["tracking_reports_raw"]) == 1
        row = booking_data["tracking_reports_raw"][0]
        assert row["order_reference_number"] == "B100"
        assert row["vendor_name"] == "Mega Cabs"
        assert row["amount"] == 1500
        assert row["supplier_id"] == "SUPP_1"
