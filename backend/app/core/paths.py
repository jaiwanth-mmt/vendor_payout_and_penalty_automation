from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
DATA_ROOT = REPO_ROOT / "data"
DEMO_DATA_ROOT = DATA_ROOT / "demo"
RUNTIME_ROOT = BACKEND_ROOT / ".runtime"
JOB_RUNTIME_ROOT = RUNTIME_ROOT / "jobs"

DEMO_WORKBOOK_PATH = DEMO_DATA_ROOT / "qliksense_dump.xlsx"
DEMO_TRACKING_JSON_PATH = DEMO_DATA_ROOT / "tracking_reports_by_booking.json"
DEMO_EXPECTED_OUTPUT_PATH = DEMO_DATA_ROOT / "expected_agentic_loss_recovery_output.xlsx"
DEFAULT_START_DATE = "2026-03-19"
DEFAULT_END_DATE = "2026-03-19"
