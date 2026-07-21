from __future__ import annotations

from backend.app.core.paths import (
    DEMO_EXPECTED_OUTPUT_PATH,
    DEMO_TRACKING_JSON_PATH,
    DEMO_WORKBOOK_PATH,
    REPO_ROOT,
)
from backend.app.domain import category_processors, subcategories
from backend.app.services import package_builder, pipeline


def test_demo_paths_are_repo_relative() -> None:
    assert DEMO_WORKBOOK_PATH == REPO_ROOT / "data" / "demo" / "qliksense_dump.xlsx"
    assert DEMO_TRACKING_JSON_PATH == REPO_ROOT / "data" / "demo" / "tracking_reports_by_booking.json"
    assert DEMO_EXPECTED_OUTPUT_PATH == REPO_ROOT / "data" / "demo" / "expected_agentic_loss_recovery_output.xlsx"
    assert DEMO_WORKBOOK_PATH.exists()
    assert DEMO_TRACKING_JSON_PATH.exists()
    assert DEMO_EXPECTED_OUTPUT_PATH.exists()


def test_tracking_infrastructure_modules_exist() -> None:
    assert (REPO_ROOT / "backend" / "app" / "integrations" / "tracking" / "repository.py").exists()
    assert (REPO_ROOT / "backend" / "app" / "core" / "tracking_utils.py").exists()
    assert (REPO_ROOT / "backend" / "app" / "integrations" / "llm_client.py").exists()


def test_pipeline_facade_reexports_agent_friendly_modules() -> None:
    assert pipeline.CategoryBatch is subcategories.CategoryBatch
    assert pipeline.process_category_batch_async is category_processors.process_category_batch_async
    assert pipeline.FINAL_EXPORT_COLUMNS is package_builder.FINAL_EXPORT_COLUMNS
    assert "Cab Delay" in category_processors.CATEGORY_PROCESSORS
    assert "Cab Delay" in category_processors.CATEGORY_ASYNC_ENRICHERS
