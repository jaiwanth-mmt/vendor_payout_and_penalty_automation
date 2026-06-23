from __future__ import annotations

import importlib

from backend.app.domain import category_processors, subcategories
from backend.app.cli import (
    add_redash_comments_to_tracking_json as add_redash_cli,
    build_penalty_dataset as build_cli,
    enrich_cab_delay_reasons as enrich_cli,
    extract_tracking_reports as extract_cli,
)
from backend.app.core.paths import (
    DEMO_EXPECTED_OUTPUT_PATH,
    DEMO_TRACKING_JSON_PATH,
    DEMO_WORKBOOK_PATH,
    REPO_ROOT,
)
from backend.app.services import package_builder, pipeline


def test_demo_paths_are_repo_relative() -> None:
    assert DEMO_WORKBOOK_PATH == REPO_ROOT / "data" / "demo" / "qliksense_dump.xlsx"
    assert DEMO_TRACKING_JSON_PATH == REPO_ROOT / "data" / "demo" / "tracking_reports_by_booking.json"
    assert DEMO_EXPECTED_OUTPUT_PATH == REPO_ROOT / "data" / "demo" / "expected_penalty_automation_output.xlsx"
    assert DEMO_WORKBOOK_PATH.exists()
    assert DEMO_TRACKING_JSON_PATH.exists()
    assert DEMO_EXPECTED_OUTPUT_PATH.exists()


def test_root_cli_wrappers_dispatch_to_package_entrypoints() -> None:
    assert importlib.import_module("build_penalty_dataset").main is build_cli.main
    assert importlib.import_module("enrich_cab_delay_reasons").main is enrich_cli.main
    assert importlib.import_module("extract_tracking_reports").main is extract_cli.main
    assert importlib.import_module("add_redash_comments_to_tracking_json").main is add_redash_cli.main


def test_pipeline_facade_reexports_agent_friendly_modules() -> None:
    assert pipeline.CategoryBatch is subcategories.CategoryBatch
    assert pipeline.process_category_batch is category_processors.process_category_batch
    assert pipeline.FINAL_EXPORT_COLUMNS is package_builder.FINAL_EXPORT_COLUMNS
    assert "Cab Delay" in category_processors.CATEGORY_PROCESSORS
